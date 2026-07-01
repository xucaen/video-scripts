#C:\Users\James\bin python3
import os
import json
import argparse
import subprocess
import numpy as np
import cv2
import librosa
from scipy.signal import find_peaks
from scipy.ndimage import gaussian_filter1d

def parse_arguments():
    parser = argparse.ArgumentParser(
        description="vB-roll.py v2: Timeline-based B-roll Finder Engine"
    )
    parser.add_argument("video", help="Path to the source video file")
    parser.add_argument("--VoiceTrack", type=int, default=1, help="FFmpeg audio track index for Voice")
    parser.add_argument("--GameTrack", type=int, default=2, help="FFmpeg audio track index for Game Audio")
    parser.add_argument("-db", "--DecibelThreshold", type=float, default=-30.0, help="Voice silence threshold in dBFS")
    parser.add_argument("-l", "--ClipLength", type=float, default=4.0, help="Fixed target length for extracted B-roll clips (seconds)")
    
    # Weights for the Composite Score calculation
    parser.add_argument("--MotionWeight", type=float, default=0.5, help="Weight for frame structural delta")
    parser.add_argument("--AudioWeight", type=float, default=0.3, help="Weight for game audio RMS")
    parser.add_argument("--SceneWeight", type=float, default=0.2, help="Weight for color histogram scene shifts")
    
    # Peak / Clustering Hyperparameters
    parser.add_argument("--MinPeakHeight", type=float, default=0.3, help="Minimum normalized composite score to qualify as a peak")
    parser.add_argument("--PeakDistance", type=float, default=10.0, help="Minimum separation between distinct local maxima (seconds)")
    parser.add_argument("--ClusterGap", type=float, default=15.0, help="Clustering window to merge nearby event peaks (seconds)")
    
    return parser.parse_args()


def extract_audio_track(video_path, track_index):
    """Extracts a targeted audio track out to a temporary mono WAV file via FFmpeg."""
    outfile = f"temp_track_{track_index}.wav"
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-map", f"0:a:{track_index}",
        "-ac", "1", "-ar", "22050",
        outfile
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return outfile


def compute_audio_rms_vector(wav_path, total_buckets, step_sec, sr=22050):
    """Chunks audio matching the timeline buckets and calculates raw energy arrays."""
    if not os.path.exists(wav_path):
        return np.zeros(total_buckets)
        
    # Load using memory mapping or standard stream if size is massive; standard load here for verification
    audio, _ = librosa.load(wav_path, sr=sr)
    hop_length = int(sr * step_sec)
    rms_vector = []
    
    for i in range(total_buckets):
        start_sample = i * hop_length
        end_sample = start_sample + hop_length
        chunk = audio[start_sample:end_sample]
        
        if len(chunk) == 0:
            rms_vector.append(0.0)
            continue
            
        rms = np.sqrt(np.mean(chunk ** 2))
        rms_vector.append(rms)
        
    return np.array(rms_vector)


def normalize_vector(vec):
    """Safely scales an array's values strictly between 0.0 and 1.0."""
    vmin, vmax = vec.min(), vec.max()
    denominator = vmax - vmin
    if denominator < 1e-6:
        return np.zeros_like(vec)
    return (vec - vmin) / denominator


def main():
    args = parse_arguments()
    STEP_SEC = 0.25  # 4 Hz uniform time buckets
    
    if not os.path.exists(args.video):
        print(f"Error: Video file '{args.video}' not found.")
        return

    # ---------------------------------------------------------
    # Gather Metadata and Initialize Timeline Matrix
    # ---------------------------------------------------------
    cap = cv2.VideoCapture(args.video)
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    if fps == 0 or total_frames == 0:
        print("Error: Could not read valid video properties via OpenCV.")
        return
        
    duration = total_frames / fps
    total_buckets = int(duration / STEP_SEC)
    
    print(f"Analyzing: {os.path.basename(args.video)}")
    print(f"Duration: {duration:.2f}s | Timeline Buckets (4 Hz): {total_buckets}")
    
    # ---------------------------------------------------------
    # STAGE 1 & 2: Audio Parsing (Voice Mask & Game Excitement)
    # ---------------------------------------------------------
    print("Processing audio tracks...")
    voice_wav = extract_audio_track(args.video, args.VoiceTrack)
    game_wav = extract_audio_track(args.video, args.GameTrack)
    
    voice_rms = compute_audio_rms_vector(voice_wav, total_buckets, STEP_SEC)
    game_rms = compute_audio_rms_vector(game_wav, total_buckets, STEP_SEC)
    
    # Clean up temp files immediately
    for f in [voice_wav, game_wav]:
        if os.path.exists(f): os.remove(f)
        
    # Convert voice RMS to dBFS to construct the gate
    # Protect against log10 of absolute zero
    safe_voice_rms = np.where(voice_rms <= 1e-9, 1e-9, voice_rms)
    voice_db = 20 * np.log10(safe_voice_rms)
    
    # Base binary mask: 1.0 if silent/quiet, 0.0 if talking
    voice_mask = (voice_db < args.DecibelThreshold).astype(float)
    
    # Mitigate the "Let's Go!" Paradox: Apply a 1.5-second look-back padding
    # If the user is speaking at bucket T, invalidate the 1.5s prior to preserve the clean action buildup
    lookback_buckets = int(1.5 / STEP_SEC)
    padded_voice_mask = np.copy(voice_mask)
    for i in range(len(voice_mask)):
        if voice_mask[i] == 0.0:
            start_clamp = max(0, i - lookback_buckets)
            padded_voice_mask[start_clamp:i] = 0.0
            
    # Normalize Game Audio Stream
    game_score_vec = normalize_vector(game_rms)

    # ---------------------------------------------------------
    # STAGE 3: Visual & Scene Change Array Extraction
    # ---------------------------------------------------------
    print("Scanning video matrix for Motion and Scene Changes (4 Hz)...")
    motion_vec = np.zeros(total_buckets)
    scene_vec = np.zeros(total_buckets)
    
    prev_gray = None
    prev_hist = None
    
    for b in range(total_buckets):
        target_time_ms = b * STEP_SEC * 1000.0
        cap.set(cv2.CAP_PROP_POS_MSEC, target_time_ms)
        ret, frame = cap.read()
        if not ret:
            break
            
        # Target optimization: Downscale down to 320x180 to purge spatial noise
        resized = cv2.resize(frame, (320, 180), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        
        # Color Histogram for Structural Scene Change tracking
        hist = cv2.calcHist([resized], [0, 1, 2], None, [4, 4, 4], [0, 256, 0, 256, 0, 256])
        cv2.normalize(hist, hist)
        
        if prev_gray is not None:
            # Motion: Macro frame absolute differences
            motion_vec[b] = np.mean(cv2.absdiff(prev_gray, gray))
            # Scene Change Density: Correlation delta
            scene_vec[b] = 1.0 - cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL)
            
        prev_gray = gray
        prev_hist = hist
        
    cap.release()
    
    motion_score_vec = normalize_vector(motion_vec)
    scene_score_vec = normalize_vector(scene_vec)

    # ---------------------------------------------------------
    # STAGE 4 & 5: Composite Scoring & Temporal Smoothing
    # ---------------------------------------------------------
    raw_composite = (
        (motion_score_vec * args.MotionWeight) +
        (game_score_vec * args.AudioWeight) +
        (scene_score_vec * args.SceneWeight)
    )
    
    # Smooth via a Gaussian Filter (Sigma 2 at 4 Hz provides roughly a 4-5 second window)
    smoothed_composite = gaussian_filter1d(raw_composite, sigma=2)
    
    # Apply our padded voice elimination mask
    final_timeline_score = smoothed_composite * padded_voice_mask

    # ---------------------------------------------------------
    # STAGE 6 & 7: Local Maxima Discovery & Event Clustering
    # ---------------------------------------------------------
    min_bucket_dist = int(args.PeakDistance / STEP_SEC)
    peaks, _ = find_peaks(
        final_timeline_score, 
        height=args.MinPeakHeight, 
        distance=min_bucket_dist
    )
    
    # Sort detected peaks based on raw intensity performance descending
    sorted_peaks = sorted(peaks, key=lambda p: final_timeline_score[p], reverse=True)
    
    accepted_peaks = []
    cluster_gap_buckets = int(args.ClusterGap / STEP_SEC)
    
    for p in sorted_peaks:
        # Check if this peak falls within the event cluster window of a higher scoring peak
        is_clustered = False
        for accepted in accepted_peaks:
            if abs(p - accepted) < cluster_gap_buckets:
                is_clustered = True
                break
        if not is_clustered:
            accepted_peaks.append(p)
            
    # Re-sort remaining survived events chronologically
    accepted_peaks.sort()

    # ---------------------------------------------------------
    # STAGE 8: Clip Packing & JSON Compilation
    # ---------------------------------------------------------
    candidates = []
    half_clip = args.ClipLength / 2.0
    
    for rank, peak_idx in enumerate(accepted_peaks, start=1):
        peak_time = peak_idx * STEP_SEC
        
        # Expand out boundaries evenly from the target score apex frame
        start_time = max(0.0, peak_time - half_clip)
        end_time = min(duration, peak_time + half_clip)
        
        candidates.append({
            "rank": rank,
            "score": round(float(final_timeline_score[peak_idx]) * 100, 2),
            "peak_time": round(peak_time, 2),
            "start": round(start_time, 2),
            "end": round(end_time, 2)
        })
        
    output_manifest = {
        "source": args.video,
        "total_duration_sec": round(duration, 2),
        "candidates": candidates
    }
    
    print("\nProcessing complete! Found B-roll Highlights:")
    print(json.dumps(output_manifest, indent=2))
    
    # Write directly out to disk adjacent to source manifest processing target
    output_filename = os.path.splitext(args.video)[0] + "_broll.json"
    with open(output_filename, "w") as f:
        json.dump(output_manifest, f, indent=2)
    print(f"\nManifest successfully written to: {output_filename}")


if __name__ == "__main__":
    main()