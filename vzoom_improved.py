import os
import argparse
import subprocess
import numpy as np
import cv2

def parse_arguments():
    parser = argparse.ArgumentParser(description="Motion Slicer with Whole-Clip Pass-Through Prevention")
    parser.add_argument("--InputFile", type=str, required=True, help="Path to the input video file")
    parser.add_argument("--x", type=int, default=0, help="Scripture Crop X Coordinate Start Point")
    parser.add_argument("--y", type=int, default=0, help="Scripture Crop Y Coordinate Start Point")
    return parser.parse_args()

def calculate_max_crop_from_origin(args, native_w, native_h):
    # Absolute rule from vzoom.py: crop_x and crop_y match args.x and args.y precisely
    crop_x = args.x
    crop_y = args.y

    # Determine the maximum remaining canvas real estate from the starting points
    available_w = native_w - args.x
    available_h = native_h - args.y

    # Determine target aspect ratio based on original video orientation
    if native_w >= native_h:
        target_ratio = 16 / 9
    else:
        target_ratio = 9 / 16

    # Calculate the largest bounding box that fits within remaining canvas space
    if (available_w / available_h) > target_ratio:
        crop_h = available_h
        crop_w = int(round(crop_h * target_ratio))
    else:
        crop_w = available_w
        crop_h = int(round(crop_w / target_ratio))

    # Force dimensions to even numbers for strict H.264 compliance
    crop_w = crop_w & ~1
    crop_h = crop_h & ~1

    crop_w = max(2, crop_w)
    crop_h = max(2, crop_h)

    return crop_x, crop_y, crop_w, crop_h

def get_motion_data(video_path, total_video_frames, args, crop_w, crop_h):
    """Measures pixel occupancy per frame inside the calculated bounding box."""
    video_capture = cv2.VideoCapture(video_path)
    motion_scores = np.zeros(total_video_frames)
    
    left_energy = np.zeros(total_video_frames)
    right_energy = np.zeros(total_video_frames)
    
    read_success, prev = video_capture.read()
    if not read_success: 
        video_capture.release()
        return motion_scores, left_energy, right_energy
        
    prev_gray = cv2.cvtColor(prev[args.y:args.y+crop_h, args.x:args.x+crop_w], cv2.COLOR_BGR2GRAY)
    midpoint_x = crop_w // 2
    
    frame_idx = 1
    while frame_idx < total_video_frames:
        read_success, curr = video_capture.read()
        if not read_success: break
        curr_gray = cv2.cvtColor(curr[args.y:args.y+crop_h, args.x:args.x+crop_w], cv2.COLOR_BGR2GRAY)
        diff = cv2.absdiff(prev_gray, curr_gray)
        _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
        
        score = np.sum(thresh) / 255
        motion_scores[frame_idx] = score
        
        if score > 0:
            left_energy[frame_idx] = np.count_nonzero(thresh[:, :midpoint_x])
            right_energy[frame_idx] = np.count_nonzero(thresh[:, midpoint_x:])
                
        prev_gray = curr_gray
        frame_idx += 1
        
    video_capture.release()
    if motion_scores.max() > 0: 
        motion_scores /= motion_scores.max()
    return motion_scores, left_energy, right_energy

def build_timeline(motion, fps):
    """Slices video into segments based 100% on pixel metrics."""
    threshold = np.percentile(motion, 85)
    is_active = motion > threshold
    
    total_frames = len(motion)
    timeline = []
    
    MIN_CUT_FRAMES = int(round(0.5 * fps))       
    ZOOM_FRAMES = int(round(0.5 * fps))          
    MIN_ZOOM_GUARD = int(round(0.3 * fps))       
    
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
    temp_snippet = f"temp_snippet_{index:03d}.mkv"
    start_sec = start_frame / fps
    duration_sec = (end_frame - start_frame) / fps
    
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-ss", f"{start_sec:.6f}",
        "-t", f"{duration_sec:.6f}"
    ]
    
    if mode == "CUT":
        # Leave other frames unzoomed (standard scaling passthrough layout)
        cmd.extend(["-vf", f"scale={target_w}:{target_h}"])
    else:  
        # Zoom frames that have the high pixel activity
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
        
    return temp_snippet

def render_final_video(video_path, timeline, target_w, target_h, fps, motion_scores, left_energy, right_energy, args, crop_w, crop_h):
    # --- WHOLE-CLIP PASS-THROUGH PREVENTION ---
    # If the timeline is completely unzoomed (only contains CUT sequences), it is an illegal pass-through clip
    has_zoom_segments = any(mode == "ZOOM" for _, _, mode in timeline)
    if not timeline or not has_zoom_segments:
        print(f"SCRIPT FAILED: NO ZOOMABLE PARTS FOUND WITHIN THE DESIGNATED AREA")
        exit(2)

    print(f"\n--- PROCESSING TIMELINE FOR {video_path} ---")
    segment_files = []
    
    available_w = target_w - args.x
    extra_space_x = available_w - crop_w

    # Trace spatial tracking coordinates globally across active segments
    total_left = 0
    total_right = 0
    total_motion_sum = 0

    for start, end, mode in timeline:
        if mode == "ZOOM":
            seg_scores = motion_scores[start:end]
            total_motion_sum += np.sum(seg_scores)
            total_left += np.sum(left_energy[start:end])
            total_right += np.sum(right_energy[start:end])

    total_pixels = total_left + total_right
    BIAS_THRESHOLD = 0.60 

    if total_pixels == 0:
        bias = "CENTER"
        global_crop_x = args.x + max(0, extra_space_x) // 2
    elif total_left / total_pixels >= BIAS_THRESHOLD:
        bias = "LEFT"
        global_crop_x = args.x
    elif total_right / total_pixels >= BIAS_THRESHOLD:
        bias = "RIGHT"
        global_crop_x = args.x + max(0, extra_space_x)
    else:
        bias = "CENTER"
        global_crop_x = args.x + max(0, extra_space_x) // 2

    global_crop_y = args.y
    global_crop_x = max(0, min(global_crop_x, target_w - crop_w)) & ~1
    global_crop_y = max(0, min(global_crop_y, target_h - crop_h)) & ~1

    print("=" * 50)
    print(" TIMELINE EXECUTION OVERVIEW")
    print("=" * 50)
    print(f"  Global Zoom Alignment Window: ({global_crop_x}, {global_crop_y}) [Bias: {bias}]")
    print("=" * 50)

    try:
        for idx, (start, end, mode) in enumerate(timeline):
            print(f"Processing segment {idx:03d}/{len(timeline)-1:03d} [{mode}]...")
            
            seg_file = process_segment(
                video_path, start, end, mode, idx, 
                target_w, target_h, fps, 
                global_crop_x, global_crop_y, crop_w, crop_h
            )
            segment_files.append(seg_file)
        
        # --- STITCH ENGINE ---
        concat_list = "inputs.txt"
        with open(concat_list, "w") as f:
            for seg in segment_files:
                f.write(f"file '{seg}'\n")
        
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        final_output = f"{base_name}_FINAL.mkv"
        
        stitch_cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list, 
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", final_output
        ]
        stitch_result = subprocess.run(stitch_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        if stitch_result.returncode == 0:
            print(f"\nSuccessfully generated sequential video sequence: {final_output}\n")
        else:
            print(f"❌ Concat stitch failed.")
        
    finally:
        if os.path.exists("inputs.txt"): os.remove("inputs.txt")
        for seg in segment_files:
            if os.path.exists(seg): os.remove(seg)

def main():
    args = parse_arguments()
    
    if not os.path.exists(args.InputFile):
        print(f"❌ Error: Input file '{args.InputFile}' not found.")
        return

    video = args.InputFile
    cap = cv2.VideoCapture(video)
    fps = cap.get(cv2.CAP_PROP_FPS)
    native_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    native_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_video_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    
    if total_video_frames <= 0: return

    _, _, crop_w, crop_h = calculate_max_crop_from_origin(args, native_w, native_h)
        
    motion_scores, left_energy, right_energy = get_motion_data(video, total_video_frames, args, crop_w, crop_h)
    
# --- PARAMETER DISPLAY BLOCK ---
    print("=" * 50)
    print(" INPUT PARAMETERS & METRICS")
    print("=" * 50)
    print(f"  Input File:        {args.InputFile}")
    print(f"  Native Resolution: {native_w}x{native_h}")
    print(f"  Fixed Starting Origin:")
    print(f"    X:               {args.x}")
    print(f"    Y:               {args.y}")
    print("=" * 50)
    print(" CALCULATED CROP GEOMETRY")
    print("-" * 50)
    print(f"  Calculated Crop W: {crop_w}")
    print(f"  Calculated Crop H: {crop_h}")
    print("=" * 50)

    assert len(motion_scores) == total_video_frames
    
    if np.sum(motion_scores) == 0:
        print(f"SCRIPT FAILED: NO ZOOMABLE PARTS FOUND WITHIN THE DESIGNATED AREA")
        exit(2)
    
    timeline = build_timeline(motion_scores, fps)
    render_final_video(video, timeline, native_w, native_h, fps, motion_scores, left_energy, right_energy, args, crop_w, crop_h)

if __name__ == "__main__":
    main()