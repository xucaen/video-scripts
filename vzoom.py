import os
import glob
import argparse
import subprocess
import numpy as np
import cv2
import librosa

# --- SIGNAL CALIBRATION ---
MOTION_WEIGHT = 0.7
AUDIO_WEIGHT = 0.3

def parse_arguments():
    parser = argparse.ArgumentParser(description="Multi-Signal Slicer with Aspect-Correct Render Engine")
    parser.add_argument("--x", type=int, required=True, help="Search Window X Coordinate")
    parser.add_argument("--y", type=int, required=True, help="Search Window Y Coordinate")
    parser.add_argument("--w", type=int, required=True, help="Search Window Width")
    parser.add_argument("--h", type=int, required=True, help="Search Window Height")
    return parser.parse_args()

def get_motion_data(video_path, total_video_frames, args):
    """Measures true pixel occupancy per frame on each side of the midpoint, eliminating centroids."""
    video_capture = cv2.VideoCapture(video_path)
    motion_scores = np.zeros(total_video_frames)
    
    # Track raw physical pixel energy allocations per frame directly from threshold masks
    left_energy = np.zeros(total_video_frames)
    right_energy = np.zeros(total_video_frames)
    
    read_success, prev = video_capture.read()
    if not read_success: 
        video_capture.release()
        return motion_scores, left_energy, right_energy
        
    prev_gray = cv2.cvtColor(prev[args.y:args.y+args.h, args.x:args.x+args.w], cv2.COLOR_BGR2GRAY)
    midpoint_x = args.w // 2
    
    frame_idx = 1
    while frame_idx < total_video_frames:
        read_success, curr = video_capture.read()
        if not read_success: break
        curr_gray = cv2.cvtColor(curr[args.y:args.y+args.h, args.x:args.x+args.w], cv2.COLOR_BGR2GRAY)
        diff = cv2.absdiff(prev_gray, curr_gray)
        _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
        
        # Total frame motion score remains normalized for the temporal timeline slicer
        score = np.sum(thresh) / 255
        motion_scores[frame_idx] = score
        
        if score > 0:
            # Directly count activated motion pixels on either side of our local search midpoint
            left_energy[frame_idx] = np.count_nonzero(thresh[:, :midpoint_x])
            right_energy[frame_idx] = np.count_nonzero(thresh[:, midpoint_x:])
                
        prev_gray = curr_gray
        frame_idx += 1
        
    video_capture.release()
    if motion_scores.max() > 0: 
        motion_scores /= motion_scores.max()
    return motion_scores, left_energy, right_energy

def get_audio_data(video_path, target_frame_count):
    temp_wav = "temp_audio_analyze.wav"
    subprocess.run(["ffmpeg", "-y", "-i", video_path, "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "1", temp_wav], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    y, sr = librosa.load(temp_wav, sr=44100)
    os.remove(temp_wav)
    
    rms = librosa.feature.rms(y=y)[0]
    if len(rms) == 0:
        return np.zeros(target_frame_count)
        
    rms_resampled = np.interp(
        np.linspace(0, len(rms) - 1, target_frame_count),
        np.arange(len(rms)),
        rms
    )
    
    if rms_resampled.max() > 0: 
        rms_resampled /= rms_resampled.max()
    return rms_resampled

def build_timeline(motion, audio, fps):
    combined = (motion * MOTION_WEIGHT) + (audio * AUDIO_WEIGHT)
    threshold = np.percentile(combined, 85)
    is_active = combined > threshold
    
    total_frames = len(combined)
    timeline = []
    
    MIN_CUT_FRAMES = int(round(4.0 * fps))       
    ZOOM_FRAMES = int(round(3.0 * fps))          
    MIN_ZOOM_GUARD = int(round(0.8 * fps))       
    
    current_frame = 0
    
    while current_frame < total_frames:
        cut_start = current_frame
        cut_end = min(cut_start + MIN_CUT_FRAMES, total_frames)
        
        triggered_zoom = False
        frame_idx = cut_end
        
        while frame_idx < total_frames:
            if is_active[frame_idx]:
                zoom_start = frame_idx
                zoom_end = min(zoom_start + ZOOM_FRAMES, total_frames)
                
                if (zoom_end - zoom_start) < MIN_ZOOM_GUARD:
                    frame_idx += 1
                    continue
                
                if zoom_start > cut_start:
                    timeline.append((cut_start, zoom_start, "CUT"))
                
                timeline.append((zoom_start, zoom_end, "ZOOM"))
                current_frame = zoom_end
                triggered_zoom = True
                break
            else:
                frame_idx += 1
                
        if not triggered_zoom:
            if total_frames > cut_start:
                timeline.append((cut_start, total_frames, "CUT"))
            break
            
    sanitized_timeline = []
    for start, end, mode in timeline:
        if sanitized_timeline and start < sanitized_timeline[-1][1]:
            start = sanitized_timeline[-1][1]
        if end > start:  
            sanitized_timeline.append((start, end, mode))
            
    return sanitized_timeline

def process_segment(video_path, start_frame, end_frame, mode, index, target_w, target_h, fps, crop_x, crop_y, crop_w, crop_h):
    temp_snippet = f"temp_snippet_{index:03d}.mp4"
    start_sec = start_frame / fps
    duration_sec = (end_frame - start_frame) / fps
    
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-ss", f"{start_sec:.6f}",
        "-t", f"{duration_sec:.6f}"
    ]
    
    if mode == "CUT":
        cmd.extend(["-vf", f"scale={target_w}:{target_h}"])
    else:  
        cmd.extend(["-vf", f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y},scale={target_w}:{target_h}"])
        
    cmd.extend([
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "18",
        "-c:a", "aac",
        "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-avoid_negative_ts", "make_zero",
        temp_snippet
    ])
    
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0 or not os.path.exists(temp_snippet) or os.path.getsize(temp_snippet) == 0:
        print(f"\n❌ ERROR: Processing failed on segment {index} ({mode}).")
        if result.stderr:
            print(result.stderr)
        
    return temp_snippet

def render_final_video(video_path, timeline, total_frames, fps, motion_scores, left_energy, right_energy, args):
    if not timeline:
        print(f"Skipping {video_path}: No valid timeline targets.")
        return

    cap = cv2.VideoCapture(video_path)
    target_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    target_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()

    print(f"\n--- PROCESSING TIMELINE FOR {video_path} ---")
    
    # --- CORE GEOMETRIC REALIGNMENT ENGINE ---
    target_ratio = target_w / target_h
    search_ratio = args.w / args.h
    
    if search_ratio > target_ratio:
        crop_h = args.h
        crop_w = int(round(crop_h * target_ratio))
    else:
        crop_w = args.w
        crop_h = int(round(crop_w / target_ratio))

    segment_files = []
    
    # Tracking states initialized to full layout center positions
    last_crop_x = args.x + (args.w - crop_w) // 2
    last_bias = "LEFT"

    try:
        for idx, (start, end, mode) in enumerate(timeline):
            print(f"\nProcessing segment {idx:03d}/{len(timeline)-1:03d} [{mode}]...")
            
            if mode == "ZOOM":
                seg_scores = motion_scores[start:end]
                sum_scores = np.sum(seg_scores)
                
                if sum_scores <= 0:
                    # Sticky Panning: Quiet window handler locks to last known framing position
                    bias = last_bias
                    crop_x = last_crop_x
                    decision_source = "FALLBACK (ZERO MOTION TEMPORAL STABILITY STICKY)"
                else:
                    # Sum up actual raw spatial pixel occurrences over the temporal block window
                    total_left_pixels = np.sum(left_energy[start:end])
                    total_right_pixels = np.sum(right_energy[start:end])
                    
                    decision_source = "HARD PIXEL OCCUPANCY ENERGY RULE"
                    
                    # Tie-breaker handles equal distribution cleanly by defaulting to Left via '>=' condition
                    if total_left_pixels >= total_right_pixels:
                        bias = "LEFT"
                        crop_x = args.x
                    else:
                        bias = "RIGHT"
                        crop_x = args.x + args.w - crop_w
                        
                    print(f"  [DEBUG DIAGNOSTIC] Left Accumulated Moving Pixels: {total_left_pixels}")
                    print(f"  [DEBUG DIAGNOSTIC] Right Accumulated Moving Pixels: {total_right_pixels}")
                
                # Vertically center the box inside the search window region
                crop_y = args.y + (args.h - crop_h) // 2
                
                # Absolute image canvas border protection mapping
                crop_x = max(0, min(crop_x, target_w - crop_w))
                crop_y = max(0, min(crop_y, target_h - crop_h))
                
                # Update sticky history cache
                last_crop_x = crop_x
                last_bias = bias
                
                print(f"[DECISION SOURCE] {decision_source}")
                print(f"[BIAS SELECTED] {bias}")
                print(f"[NEW X] {crop_x} | [NEW Y] {crop_y}")
            else:
                # Pass-through configuration (full-frame unzoomed layout)
                crop_x = args.x
                crop_y = args.y
                print(f"[DECISION SOURCE] PASS-THROUGH LAYOUT")
                print(f"[NEW X] {crop_x} | [NEW Y] {crop_y}")

            seg_file = process_segment(
                video_path, start, end, mode, idx, 
                target_w, target_h, fps, 
                crop_x, crop_y, crop_w, crop_h
            )
            segment_files.append(seg_file)
        
        # --- STITCH ENGINE ---
        concat_list = "inputs.txt"
        with open(concat_list, "w") as f:
            for seg in segment_files:
                f.write(f"file '{seg}'\n")
        
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        final_output = f"{base_name}_FINAL.mp4"
        
        stitch_cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list, 
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", final_output
        ]
        stitch_result = subprocess.run(stitch_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        if stitch_result.returncode == 0:
            print(f"\nSuccessfully generated final video: {final_output}\n")
        else:
            print(f"❌ Concat stitch failed.")
        
    finally:
        if os.path.exists("inputs.txt"): os.remove("inputs.txt")
        for seg in segment_files:
            if os.path.exists(seg): os.remove(seg)

def main():
    args = parse_arguments()
    for video in glob.glob("*.mkv") + glob.glob("*.mp4"):
        if "_final" in video.lower(): continue
        
        cap = cv2.VideoCapture(video)
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_video_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()
        
        if total_video_frames <= 0: continue
            
        motion_scores, left_energy, right_energy = get_motion_data(video, total_video_frames, args)
        audio_scores = get_audio_data(video, total_video_frames)
        
        assert len(motion_scores) == total_video_frames
        
        timeline = build_timeline(motion_scores, audio_scores, fps)
        render_final_video(video, timeline, total_video_frames, fps, motion_scores, left_energy, right_energy, args)

if __name__ == "__main__":
    main()