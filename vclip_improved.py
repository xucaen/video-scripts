import os
import sys
import re
import argparse
import subprocess

# --- COLOR DEFINITIONS ---
CYAN = "\033[96m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
RED = "\033[91m"
PURPLE = "\033[95m"
GRAY = "\033[90m"
RESET = "\033[0m"

def parse_arguments():
    """
    Defines the script interface with parameters.
    """
    parser = argparse.ArgumentParser(description="Bulletproof True Loudness Video Slicer Engine.")
    parser.add_argument("--InputFile", type=str, required=True, help="Path to the input video file")
    parser.add_argument("--VoiceAudioTrack", type=int, default=1, help="The explicit audio track index FFmpeg will monitor for voice/audio activity.")
    parser.add_argument("-db", "--DecibleThreshold", type=int, default=-30, help="The LUFS/dB loudness limit above which audio is marked as active.")
    parser.add_argument("-md", "--MinClipDuration", type=float, default=2.0, help="The minimum continuous duration in seconds the audio must remain loud to qualify as a clip.")
    return parser.parse_args()

def convert_to_seconds(time_value):
    """
    Normalizes time representations from mixed types into standard float seconds.
    """
    time_str = str(time_value).strip()
    if ":" in time_str:
        parts = time_str.split(":")
        if len(parts) == 3: # HH:MM:SS
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        elif len(parts) == 2: # MM:SS
            return float(parts[0]) * 60 + float(parts[1])
    return float(time_str)

def get_video_metadata(file_path):
    """
    Queries ffprobe to extract structural metadata safely.
    """
    duration_args = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", file_path
    ]
    print(f"{CYAN}DURATION_args: {duration_args}{RESET}")
    
    fps_args = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate",
        "-of", "default=noprint_wrappers=1:nokey=1", file_path
    ]
    print(f"{CYAN}FPS args: {fps_args}{RESET}")
    
    try:
        duration_text = subprocess.check_output(duration_args, text=True).strip()
        total_duration = float(duration_text) if duration_text else 0.0
    except Exception:
        print(f"{RED}EXCEPTION ERROR: ffprobe failed getting duration data{RESET}")
        exit(3)
        
    try:
        fps_text = subprocess.check_output(fps_args, text=True).strip()
        if "/" in fps_text:
            num, den = map(float, fps_text.split("/"))
            fps = num / den if den != 0 else 0.0
        else:
            fps = float(fps_text) if fps_text else 0.0
    except Exception:
        print(f"{RED}EXCEPTION ERROR: ffprobe failed getting frame rate{RESET}")
        exit(3)
        
    return total_duration, fps


def detect_loudness(decibel_threshold, min_clip_duration, VoiceAudioTrack, file_path):
    """
    Performs streaming audio energy scans via FFmpeg astats, processing logs 
    line-by-line via Popen to maintain an O(1) memory profile on massive files.
    """
    print(f"{CYAN}\n--------------------------------------------------")
    print(" [Detect-Loudness Configuration]")
    print(f" -> Audio Track Monitored : {YELLOW}{VoiceAudioTrack}")
    print(f" {CYAN}-> True Volume Floor     : {YELLOW}{decibel_threshold} RMS dB")
    print(f" {CYAN}-> Min Clip Duration     : {YELLOW}{min_clip_duration} seconds")
    print(f"{CYAN}--------------------------------------------------")
    
    total_duration, frame_rate = get_video_metadata(file_path)
    print(f"{YELLOW}\n==================================================")
    print(f"Streaming & Analyzing Volume Levels (O(1) RAM): {file_path}")
    print(f"=================================================={RESET}")
    
    if total_duration == 0.0:
        print(f"{RED}ERROR: Could not determine duration for {file_path}. Skipping.{RESET}")
        exit(4)
        
    # Standardized astats pipeline that pushes clean newlines directly down stderr
    ffmpeg_args = [
        "ffmpeg", 
        "-i", file_path, 
        "-map", f"0:a:{VoiceAudioTrack}", 
        "-af", "astats=metadata=1:reset=1", 
        "-f", "null", "-"
    ]
    
    process = subprocess.Popen(ffmpeg_args, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True, encoding='utf-8')
    
    # Matches the newline entries cleanly: pkt_pts_time:1.439104 RMS_level:-12.45
    pattern = re.compile(r"pkt_pts_time:(?P<time>[\d.]+).*RMS_level:(?P<volume>[-\d.]+)")
    loud_timestamps = []
    parsed_any_lines = False
    
    for line in process.stderr:
        match = pattern.search(line)
        if match:
            parsed_any_lines = True
            timestamp = float(match.group('time'))
            volume = float(match.group('volume'))
            
            if len(loud_timestamps) % 200 == 0:
                print(f"{GRAY}[Analyzing] Time: {timestamp:.2f}s | Current RMS Volume: {volume:.1f} dB{RESET}", end="\r")
            
            if volume >= decibel_threshold:
                loud_timestamps.append(timestamp)

    process.wait()
    print("") # Clear carriage return line
            
    if not parsed_any_lines:
        print(f"{RED}ERROR: FFmpeg did not yield valid metadata logs. Check if Audio Track {VoiceAudioTrack} actually exists inside this file.{RESET}")
        exit(3)
            
    if not loud_timestamps:
        print(f"{GRAY}No active voice or adjacent action blocks found in {file_path}.{RESET}")
        exit(3)
        
    # Group loose hot timestamps together into distinct start/end chunks
    voice_segments = []
    clip_start = max(0.0, loud_timestamps[0])
    prev_time = loud_timestamps[0]
    max_silence_gap = 1.5 
    
    for current_time in loud_timestamps[1:]:
        if current_time - prev_time > max_silence_gap:
            clip_end = min(total_duration, prev_time)
            
            if (clip_end - clip_start) >= min_clip_duration:
                voice_segments.append({"File": file_path, "Start": clip_start, "End": clip_end})
            else:
                print(f"{GRAY}Dropping brief burst: {clip_start:.2f}s to {clip_end:.2f}s (less than {min_clip_duration}s){RESET}")
                
            clip_start = current_time
            
        prev_time = current_time
        
    clip_end = min(total_duration, prev_time)
    if (clip_end - clip_start) >= min_clip_duration:
        voice_segments.append({"File": file_path, "Start": clip_start, "End": clip_end})
    else:
        print(f"{GRAY}Dropping brief burst: {clip_start:.2f}s to {clip_end:.2f}s (less than {min_clip_duration}s){RESET}")

    if not voice_segments:
        print(f"{GRAY}No action blocks met the minimum duration requirements.{RESET}")
        exit(3)
        
    return voice_segments


def process_clips(clips):
    """
    Slices target clips safely using optimized seeking based on dictionary records.
    """
    clip_number = 1
    for row in clips:
        try:
            file_path = row.get("File")
            if not file_path or not os.path.exists(file_path):
                print(f"{YELLOW}Warning: Skipping {file_path} (Not found){RESET}")
                continue
                
            total_duration, fps = get_video_metadata(file_path)
            if fps == 0:
                print(f"{RED}CATASTROPHIC FAILURE - FPS is 0{RESET}")
                exit(1)
            if total_duration == 0.0:
                print(f"{RED}ERROR: Could not determine duration for {file_path}. Skipping.{RESET}")
                exit(4)
                
            start_seconds = convert_to_seconds(row.get("Start", 0.0))
            end_seconds = convert_to_seconds(row.get("End", 0.0))
            
            if (end_seconds - start_seconds) < 0.5:
                print(f"{GRAY}Skipping micro-clip range ({start_seconds}s to {end_seconds}s): too short to extract safely.{RESET}")
                continue
                
            # Apply 0.5-second structural padding safely bounded by media lengths
            buffered_start = max(0.0, start_seconds - 0.5)
            buffered_end = min(total_duration, end_seconds + 0.5)
            
            frame_start = int(buffered_start * fps)
            frame_end = int(buffered_end * fps)
            
            base_name, extension = os.path.splitext(os.path.basename(file_path))
            starttime_clean = str(round(buffered_start, 2)).replace(":", "-").replace(".", "-")
            endtime_clean = str(round(buffered_end, 2)).replace(":", "-").replace(".", "-")
            output_file = f"{base_name}_Clip_{starttime_clean}_{endtime_clean}{extension}"
            
            print(f"{CYAN}\n--- Processing Clip #{clip_number} ---")
            print(f"{RESET}Source: {file_path} ({round(fps, 2)} fps)")
            print(f"Range: {round(buffered_start, 2)}s to {round(buffered_end, 2)}s")
            print(f"Output: {output_file}")
            
            # Precise input stream-seeking logic
            ffmpeg_slice_args = [
                "ffmpeg", "-y", "-ss", str(buffered_start), "-to", str(buffered_end), 
                "-i", file_path, "-map", "0", "-c:v", "libx264", "-crf", "18", "-c:a", "aac"
            ]
            ffmpeg_slice_args.append(output_file)
            
            result = subprocess.run(ffmpeg_slice_args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if result.returncode == 0:
                print(f"{GREEN}Success!{RESET}")
                clip_number += 1
            else:
                print(f"{RED}FFmpeg rendering failed with exit code {result.returncode}{RESET}")
        except Exception as e:
            print(f"{RED}Failed to process clip entry: {str(e)}{RESET}")
            exit(5)
            
    print(f"{GREEN}\nDone! Created {clip_number - 1} continuous high-energy clips.{RESET}")

def main():
    """
    Main controller orchestrating application lifecycle execution.
    """
    args = parse_arguments()
    if not os.path.exists(args.InputFile):
        print(f"❌ Error: Input file '{args.InputFile}' not found.")
        exit(2)
        
    clips = detect_loudness(
        decibel_threshold=args.DecibleThreshold,
        min_clip_duration=args.MinClipDuration,
        VoiceAudioTrack=args.VoiceAudioTrack,
        file_path=args.InputFile
    )
    
    if not clips:
        print(f"{RED}Error: No audio regions matched criteria. Exiting.{RESET}")
        exit(1)
    
    process_clips(clips)

if __name__ == "__main__":
    main()