import argparse
import os
import subprocess
import cv2
import numpy as np
import av
import time
import sys

# Supported video extensions for directory scanning
VIDEO_EXTENSIONS = (".mkv", ".mp4", ".avi", ".mov", ".flv", ".webm")

# Dictionary Keys
KEY_FILE = "file"
KEY_START = "start"
KEY_END = "end"
KEY_PEAK = "peak"
KEY_SCORE = "score"
KEY_VOL = "volume"

# Configuration constants
BIN_DURATION = 0.1  # 100ms uniform time windows
WEIGHT_AUDIO = 1.5   # Prioritize those heavy game engine sound spikes
WEIGHT_FLOW = 1.2
WEIGHT_MOTION = 0.8

COEFF_BURST = 0.5
COEFF_EMA = 0.7
EMA_ALPHA = 0.1

EST_SCAN_FPS = 120.0  # Increased since we skip massive chunks of the files now!   
EST_RENDER_FPS = 45.0  


def print_runtime_parameters(args):
    """Dynamically iterates over argparse namespace and prints variables cleanly aligned."""
    print("┌────────────────────────────────────────────────────┐")
    print("│ ▶️ RUNTIME PARAMETERS                               │")
    print("├────────────────────────────────────────────────────┤")
    args_dict = vars(args)
    max_key_len = max(len(k) for k in args_dict.keys()) if args_dict else 0
    for key, value in args_dict.items():
        print(f"│   🔹 {key.ljust(max_key_len)} : {value}")
    print("└────────────────────────────────────────────────────┘\n")


def parse_arguments():
    parser = argparse.ArgumentParser(description="Production Segmented Dual-Track Audio Highlight Script.")
    parser.add_argument("-v", "--VoiceAudioTrack", type=int, default=1, help="Index of your mic stream (0-indexed).")
    parser.add_argument("-g", "--GameAudioTrack", type=int, default=2, help="Index of your game stream (0-indexed).")
    parser.add_argument("-l", "--MinClipLength", type=float, default=3.0, help="Minimum clip duration.")
    return parser.parse_args()


# ==========================================
# 0. PRE-FLIGHT TIME ESTIMATOR
# ==========================================
def display_job_estimation(video_files, target_windows):
    """Inspects clip durations to project total script runtime and frame counts."""
    print("\n📊 [Job Time Estimator] Calculating expected processing time...")
    
    total_scan_frames = 0
    estimated_render_seconds = 0
    frames_by_file = {}
    
    regions_by_file = {}
    for r in target_windows:
        regions_by_file.setdefault(r[KEY_FILE], []).append(r)
        
    for video_path in video_files:
        if not os.path.exists(video_path):
            continue
        try:
            container = av.open(video_path)
            video_stream = container.streams.video[0]
            fps = float(video_stream.average_rate) if video_stream.average_rate else 30.0
            
            regions = regions_by_file.get(video_path, [])
            analyzed_seconds = sum(max(0.0, r[KEY_END] - r[KEY_START]) for r in regions)
            
            file_target_frames = int(analyzed_seconds * fps)
            frames_by_file[video_path] = file_target_frames
            total_scan_frames += file_target_frames
            
            estimated_render_seconds += (analyzed_seconds * 0.10)
            container.close()
        except Exception as e:
            print(f"   ⚠️ Could not read metadata for estimation on: {os.path.basename(video_path)} ({e})")
            frames_by_file[video_path] = 1000

    scan_time_seconds = total_scan_frames / EST_SCAN_FPS
    render_time_seconds = (estimated_render_seconds * 30.0) / EST_RENDER_FPS
    total_projected_seconds = scan_time_seconds + render_time_seconds
    
    scan_mins, scan_secs = divmod(int(scan_time_seconds), 60)
    render_mins, render_secs = divmod(int(render_time_seconds), 60)
    tot_mins, tot_secs = divmod(int(total_projected_seconds), 60)
    
    print("   ------------------------------------------------")
    print(f"   🎯 Total targeted frames to evaluate: {int(total_scan_frames)} frames")
    print(f"   ⏱️ Projected Scanning Phase: {scan_mins}m {scan_secs}s  (@ {EST_SCAN_FPS} FPS)")
    print(f"   ⏱️ Projected Rendering Phase: {render_mins}m {render_secs}s (@ {EST_RENDER_FPS} FPS)")
    print(f"   🚀 Est. Total Execution Time: {tot_mins}m {tot_secs}s")
    print("   ------------------------------------------------\n")
    time.sleep(1.0)
    
    return frames_by_file


# ==========================================
# 1. VOICE SILENCE & GAME AUDIO PEAK DETECTOR
# ==========================================
def detect_voice_silence_game_peaks(video_path, voice_track_idx, game_track_idx, min_clip_length):
    """
    Parses native audio streams directly. Identifies intervals where the voice track
    is fully quiet, while capturing the precise volume levels of the game stream.
    """
    print(f"🎧 [Audio Analyzer] Scanning streams for: {os.path.basename(video_path)}")
    
    container = av.open(video_path)
    
    audio_streams = container.streams.audio
    if len(audio_streams) <= max(voice_track_idx, game_track_idx):
        print(f"   ⚠️ Audio configuration layout mismatch inside container. Skipping dynamic tracking.")
        container.close()
        return []

    voice_stream = audio_streams[voice_track_idx]
    game_stream = audio_streams[game_track_idx]

    timeline_bins = {}
    
    for packet in container.demux(voice_stream, game_stream):
        for frame in packet.decode():
            if frame.pts is None:
                continue
            t = float(frame.pts * packet.stream.time_base)
            bin_idx = int(t / BIN_DURATION)
            
            data = frame.to_ndarray().astype(np.float32)
            rms = float(np.sqrt(np.mean(data**2))) if data.size > 0 else 0.0
            
            if bin_idx not in timeline_bins:
                timeline_bins[bin_idx] = {"voice_rms": [], "game_rms": []}
                
            if packet.stream.index == voice_track_idx:
                timeline_bins[bin_idx]["voice_rms"].append(rms)
            else:
                timeline_bins[bin_idx]["game_rms"].append(rms)

    container.close()

    SILENCE_THRESHOLD = 0.001 
    in_silent_zone = False
    zone_start = 0.0
    game_vol_accumulator = []
    valid_regions = []

    sorted_bins = sorted(timeline_bins.keys())
    for b in sorted_bins:
        t_current = b * BIN_DURATION
        v_list = timeline_bins[b]["voice_rms"]
        g_list = timeline_bins[b]["game_rms"]
        
        avg_v = np.mean(v_list) if v_list else 0.0
        avg_g = np.mean(g_list) if g_list else 0.0
        
        is_quiet = (avg_v < SILENCE_THRESHOLD)
        
        if is_quiet:
            if not in_silent_zone:
                in_silent_zone = True
                zone_start = t_current
            game_vol_accumulator.append(avg_g)
        else:
            if in_silent_zone:
                zone_end = t_current
                duration = zone_end - zone_start
                if duration >= min_clip_length:
                    peak_game_vol = float(np.max(game_vol_accumulator)) if game_vol_accumulator else 0.0
                    valid_regions.append({
                        KEY_FILE: video_path,
                        KEY_START: zone_start,
                        KEY_END: zone_end,
                        KEY_VOL: peak_game_vol
                    })
                in_silent_zone = False
                game_vol_accumulator.clear()

    if in_silent_zone:
        zone_end = len(sorted_bins) * BIN_DURATION
        if (zone_end - zone_start) >= min_clip_length:
            peak_game_vol = float(np.max(game_vol_accumulator)) if game_vol_accumulator else 0.0
            valid_regions.append({
                KEY_FILE: video_path,
                KEY_START: zone_start,
                KEY_END: zone_end,
                KEY_VOL: peak_game_vol
            })

    # Sort targeted sections natively so highest priority items are evaluated first
    valid_regions.sort(key=lambda x: x[KEY_VOL], reverse=True)
    return valid_regions


# ==========================================
# 2. SEGMENTED VISUAL EXCITEMENT SCANNER (REPAIRED)
# ==========================================
def analyze_visual_excitement(target_regions, target_frames_map):
    """
    Scans only regions extracted by the Audio Analyzer using precise structural
    seeking, cutting decode runtime to only target payloads.
    """
    print(f"\n👁️ [Visual Scanner] Starting analysis across {len(target_regions)} loud/silent targeted windows...")
    timelines_by_file = {}
    regions_by_file = {}
    
    for region in target_regions:
        regions_by_file.setdefault(region[KEY_FILE], []).append(region)

    for video_path, regions in regions_by_file.items():
        print(f"   🎬 Opening Container: {os.path.basename(video_path)}")
        timelines_by_file[video_path] = []
        
        container = av.open(video_path)
        video_stream = container.streams.video[0]
        time_base = video_stream.time_base
        
        total_target_frames = max(1, target_frames_map.get(video_path, 1000))
        processed_target_frames = 0
        
        # Process each region completely independently using precise seeking hooks
        for idx, region in enumerate(regions):
            start_time = region[KEY_START]
            end_time = region[KEY_END]
            game_vol = region[KEY_VOL]
            
            # Form seek packet targets (seek takes position scaled into stream time_base units)
            seek_target = int(start_time / time_base)
            container.seek(seek_target, stream=video_stream)
            
            # Setup localized state containers for tracking calculations inside this window
            prev_gray = None
            bin_boundary = start_time + BIN_DURATION
            bin_audio = []
            bin_flow = []
            bin_motion = []
            
            prev_base_score = 0.0
            ema_score = 0.0
            
            # Stream decode frame loop context restricted strictly to this seek segment
            for video_frame in container.decode(video_stream):
                if video_frame.pts is None:
                    continue
                
                current_time = float(video_frame.pts * time_base)
                
                # If seek dropped us off before our exact starting window bounds, fast-forward skip parsing
                if current_time < start_time:
                    continue
                
                # Hard exit out of decoding loops instantly when boundary thresholds are crossed
                if current_time > end_time:
                    break
                    
                processed_target_frames += 1
                
                if processed_target_frames % 10 == 0 or processed_target_frames == total_target_frames:
                    progress = min(1.0, processed_target_frames / total_target_frames)
                    bar_len = 25
                    filled_len = int(round(bar_len * progress))
                    bar = '█' * filled_len + '░' * (bar_len - filled_len)
                    sys.stdout.write(f"\r      ⏳ [{bar}] {int(progress * 100)}% | Target Frame {processed_target_frames}/{total_target_frames}")
                    sys.stdout.flush()

                # Visual computer-vision analysis transformations 
                gray = video_frame.to_ndarray(format='gray')
                
                if prev_gray is not None:
                    diff = cv2.absdiff(prev_gray, gray)
                    motion_score = float(np.log1p(np.mean(diff)) * 5.0)
                    bin_motion.append(motion_score)

                    if motion_score > 4.0:
                        flow = cv2.calcOpticalFlowFarneback(
                            prev_gray, gray, None,
                            pyr_scale=0.5, levels=3, winsize=15, iterations=3, poly_n=5, poly_sigma=1.2, flags=0
                        )
                        magnitude, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
                        flow_score = float(np.mean(magnitude) * 3.0)
                        bin_flow.append(flow_score)

                prev_gray = gray
                bin_audio.append(game_vol * 10.0)

                # Segment evaluation calculations
                if current_time >= bin_boundary:
                    avg_audio = float(np.mean(bin_audio)) if bin_audio else 0.0
                    avg_flow = float(np.mean(bin_flow)) if bin_flow else 0.0
                    avg_motion = float(np.mean(bin_motion)) if bin_motion else 0.0
                    
                    bin_audio.clear()
                    bin_flow.clear()
                    bin_motion.clear()

                    base_score = (WEIGHT_AUDIO * avg_audio) + (WEIGHT_FLOW * avg_flow) + (WEIGHT_MOTION * avg_motion)
                    
                    acceleration = base_score - prev_base_score
                    ema_score = (EMA_ALPHA * base_score) + ((1.0 - EMA_ALPHA) * ema_score)
                    
                    raw_score = base_score + (COEFF_BURST * acceleration) + (COEFF_EMA * ema_score)
                    final_score = float(np.tanh(raw_score))

                    timelines_by_file[video_path].append({
                        "timestamp": bin_boundary,
                        KEY_SCORE: final_score
                    })

                    prev_base_score = base_score
                    bin_boundary += BIN_DURATION

        container.close()
        print(f"\n   🏁 Finished Video: {os.path.basename(video_path)} | Selective segment processing finalized.")
        
    return timelines_by_file


# ==========================================
# 3. TIMELINE SMOOTHING & PERCENTILE NMS
# ==========================================
def extract_highlights(timelines_by_file):
    """Filters, smoothes, and suppresses overlapping timeline candidate clips."""
    print("\n📈 [Highlight Extractor] Generating and smoothing timeline charts...")
    all_candidates = []
    SAMPLE_FPS = 10.0  
    SMOOTH_SECONDS = 3.0
    BEFORE_PEAK = 5.0
    AFTER_PEAK = 10.0
    PERCENTILE_FLOOR = 90.0  
    TOTAL_WINDOW = BEFORE_PEAK + AFTER_PEAK
    
    window_size = max(1, int(SAMPLE_FPS * SMOOTH_SECONDS))

    for video_path, timeline in timelines_by_file.items():
        if not timeline:
            continue

        # Ensure timeline items are natively ordered chronologically before computing convolve matrix mappings
        timeline.sort(key=lambda x: x["timestamp"])

        times = [item["timestamp"] for item in timeline]
        scores = [item[KEY_SCORE] for item in timeline]
        
        if len(scores) < window_size:
            smoothed_scores = np.array(scores)
        else:
            kernel = np.ones(window_size) / window_size
            smoothed_scores = np.convolve(scores, kernel, mode="same")[:len(times)]
        
        video_duration = times[-1] if times else 0.0
        
        for idx, smoothed_score in enumerate(smoothed_scores):
            peak_time = times[idx]
            c_start = max(0.0, peak_time - BEFORE_PEAK)
            c_end = min(video_duration, peak_time + AFTER_PEAK)

            all_candidates.append({
                KEY_FILE: video_path,
                KEY_PEAK: peak_time,
                KEY_START: c_start,
                KEY_END: c_end,
                KEY_SCORE: float(smoothed_score)
            })

    if not all_candidates:
        return []

    raw_scores = [c[KEY_SCORE] for c in all_candidates]
    resolved_floor = float(np.percentile(raw_scores, PERCENTILE_FLOOR))

    valid_candidates = [c for c in all_candidates if c[KEY_SCORE] >= resolved_floor]
    sorted_candidates = sorted(valid_candidates, key=lambda x: x[KEY_SCORE], reverse=True)
    selected_highlights = []
    
    while sorted_candidates:
        best_candidate = sorted_candidates.pop(0)
        selected_highlights.append(best_candidate)
        
        remaining_candidates = []
        for candidate in sorted_candidates:
            if candidate[KEY_FILE] == best_candidate[KEY_FILE]:
                overlap_start = max(candidate[KEY_START], best_candidate[KEY_START])
                overlap_end = min(candidate[KEY_END], best_candidate[KEY_END])
                
                if overlap_end > overlap_start:
                    overlap_duration = overlap_end - overlap_start
                    if (overlap_duration / TOTAL_WINDOW) > 0.6:
                        continue 
            remaining_candidates.append(candidate)
        sorted_candidates = remaining_candidates
            
    return selected_highlights


# ==========================================
# 4. HIGH-PERFORMANCE RENDER ENGINE
# ==========================================
def render_clips(highlights, min_clip_length):
    """Cuts and outputs video clips via FFmpeg using precise formatted second naming rules."""
    print("\n🎬 [Render Engine] Preparing output tasks...")
    if not highlights:
        print("   ❌ No clips met the required thresholds.")
        return

    output_dir = "."

    for idx, hl in enumerate(highlights):
        duration = hl[KEY_END] - hl[KEY_START]
        if duration < min_clip_length:
            continue
        
        base_name = os.path.splitext(os.path.basename(hl[KEY_FILE]))[0]
        
        start_secs = f"{hl.get(KEY_START, 0.0):.2f}"
        end_secs = f"{hl.get(KEY_END, 0.0):.2f}"
        
        suffix = ""
        letter_offset = 0
        
        while True:
            output_file = os.path.join(output_dir, f"{base_name}_Clip_{start_secs}_{end_secs}_FINAL{suffix}.mp4")
            if not os.path.exists(output_file):
                break
            suffix = f"_{chr(97 + letter_offset)}"
            letter_offset += 1
        
        print(f"   🚀 Slicing Highlight #{idx+1} -> {output_file} ({duration:.2f}s long)")

        coarse_seek = max(0.0, hl[KEY_START] - 2.0)
        fine_seek = hl[KEY_START] - coarse_seek

        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{coarse_seek:.2f}",   
            "-i", hl[KEY_FILE],
            "-ss", f"{fine_seek:.2f}",     
            "-t", f"{duration:.2f}",       
            "-map", "0",
            "-c:v", "libx264",
            "-crf", "18",
            "-c:a", "aac",
            output_file
        ]
        
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if result.returncode != 0:
            print(f"      ❌ FFmpeg execution failed for this clip! Error code: {result.returncode}")


# ==========================================
# MAIN EXECUTION CONTROL
# ==========================================
def main():
    print("====================================================")
    print("🚀 INITIALIZING GCLIP HIGHLIGHT PROCESSING SUITE 🚀")
    print("====================================================")
    
    args = parse_arguments()
    print_runtime_parameters(args)

    current_dir = os.getcwd()
    print(f"📂 Target working directory: {current_dir}")
    
    raw_files = [
        f for f in os.listdir(current_dir) 
        if f.lower().endswith(VIDEO_EXTENSIONS) and "clip" not in f.lower()
    ]
    raw_files.sort(key=lambda x: os.path.getctime(os.path.join(current_dir, x)))
    video_files = [os.path.join(current_dir, f) for f in raw_files]

    if not video_files:
        print(f"❌ Aborted: No valid source video files found in: {current_dir}")
        return

    print(f"📋 Loaded {len(video_files)} video file(s) into queue.")

    all_target_windows = []
    for video_path in video_files:
        file_windows = detect_voice_silence_game_peaks(
            video_path=video_path,
            voice_track_idx=args.VoiceAudioTrack,
            game_track_idx=args.GameAudioTrack,
            min_clip_length=args.MinClipLength
        )
        all_target_windows.extend(file_windows)
    
    if not all_target_windows:
        print("❌ Aborted: No silent voice regions found to evaluate.")
        return

    # Run pre-flight estimation using the actual mapped payloads
    target_frames_map = display_job_estimation(video_files=video_files, target_windows=all_target_windows)

    # Step 3 & 4: Run scanning and saving modules
    timelines_by_file = analyze_visual_excitement(target_regions=all_target_windows, target_frames_map=target_frames_map)
    top_highlights = extract_highlights(timelines_by_file=timelines_by_file)
    
    render_clips(highlights=top_highlights, min_clip_length=args.MinClipLength)
    
    print("\n====================================================")
    print("🎉 ALL PROCESSING PHASES COMPLETED SUCCESSFULLY! 🎉")
    print("====================================================")


if __name__ == "__main__":
    main()