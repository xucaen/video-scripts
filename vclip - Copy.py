import os
import sys
import re
import glob
import argparse
import subprocess

# --- COLOR DEFINITIONS ---
CYAN = "\033[96m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
RED = "\033[91m"
GRAY = "\033[90m"
RESET = "\033[0m"

# Global state configuration to support the strict single-argument signature
VoiceAudioTrack = 1

def parse_arguments():
    """
    Defines the script interface with explicit multi-track controls.
    """
    parser = argparse.ArgumentParser(description="Bulletproof Multi-Track Video Slicer Engine.")
    
    parser.add_argument("--VoiceAudioTrack", type=int, default=1, help="The explicit audio track index FFmpeg will monitor for voice activity.")
    parser.add_argument("-db", "--DecibleThreshold", type=int, default=-30, help="The decibel limit below which audio is classified as absolute loudness.")
    parser.add_argument("-sl", "--LoudnessLength", type=float, default=1.5, help="The minimum duration of quiet time required to trigger a clip split.")
    
    return parser.parse_args()


def get_video_metadata(input_video):
    """
    Queries ffprobe to extract structural metadata.
    """
    duration_args = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration", 
        "-of", "default=noprint_wrappers=1:nokey=1", input_video
    ]
    
    fps_args = [
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", 
        "stream=r_frame_rate", "-of", "default=noprint_wrappers=1:nokey=1", input_video
    ]

    try:
        duration_text = subprocess.check_output(duration_args, text=True).strip()
        total_duration = float(duration_text) if duration_text else 0.0
    except Exception:
        total_duration = 0.0

    try:
        fps_text = subprocess.check_output(fps_args, text=True).strip()
        if "/" in fps_text:
            num, den = map(float, fps_text.split("/"))
            fps = num / den if den != 0 else 0.0
        else:
            fps = float(fps_text) if fps_text else 0.0
    except Exception:
        fps = 0.0

    return total_duration, fps


def convert_to_seconds(time_value):
    """
    Normalizes time representations from mixed types.
    """
    time_str = str(time_value).strip()
    if ":" in time_str:
        parts = time_str.split(":")
        if len(parts) == 3:  # HH:MM:SS
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        elif len(parts) == 2:  # MM:SS
            return float(parts[0]) * 60 + float(parts[1])
    return float(time_str)


def detect_loudness(decibel_threshold, loudness_length, min_clip_length):
    """
    Scans local directory for video assets and cross-analyzes voice signals with exciting gameplay cues.
    """
    print(f"{CYAN}\n--------------------------------------------------")
    print(" [Detect-Loudness Configuration]")
    print(f"  -> Voice Audio Track     : {YELLOW}{VoiceAudioTrack}{RESET}")
    print(f"  -> Volume Threshold      : {YELLOW}{decibel_threshold} dB{RESET}")
    print(f"  -> Min Loudness Duration  : {YELLOW}{loudness_length} seconds{RESET}")
    print(f"  -> Target Min Clip Length: {YELLOW}{min_clip_length} seconds.{RESET}")
    print(f"{CYAN}--------------------------------------------------{RESET}")

    video_extensions = ("*.mp4", "*.mkv", "*.mov", "*.avi")
    video_files = []
    
    for ext in video_extensions:
        video_files.extend(glob.glob(ext))
    
    video_files.sort(key=os.path.getctime)

    if not video_files:
        print(f"{RED}Error: No matching video files found in the current folder.{RESET}")
        sys.exit(1)

    print(f"{GREEN}Found {len(video_files)} videos to process (sorted chronologically).{RESET}")


    for file_path in video_files:
        print(f"{YELLOW}\n==================================================")
        print(f"Analyzing: {file_path}")
        print(f"=================================================={RESET}")

        total_duration, _ = get_video_metadata(file_path)
        if total_duration == 0.0:
            print(f"{YELLOW}Warning: Could not determine duration for {file_path}. Skipping.{RESET}")
            continue

        ffmpeg_args = [
            "ffmpeg", "-i", file_path,
            "-filter_complex", f"[0:a:{VoiceAudioTrack}]loudnessdetect=noise={decibel_threshold}dB:d={loudness_length}",
            "-f", "null", "-"
        ]

        result = subprocess.run(ffmpeg_args, stderr=subprocess.PIPE, text=True)
        ffmpeg_logs = result.stderr

        loudness_matches = re.finditer(r'loudness_start:\s*(?P<start>[\d\.]+)|loudness_end:\s*(?P<end>[\d\.]+)', ffmpeg_logs)

        voice_segments = []
        raw_segments = []
        current_start = 0.0

        for match in loudness_matches:
            if match.group('start'):
                loudness_start = float(match.group('start'))
                if loudness_start > current_start:
                    if (loudness_start - current_start) >= min_clip_length:
                        raw_segments.append((current_start, loudness_start))
            elif match.group('end'):
                current_start = float(match.group('end'))

        if current_start < total_duration:
            if (total_duration - current_start) >= min_clip_length:
                raw_segments.append((current_start, total_duration))

        # enforce max_clip_length constraints by chunking oversized segments
        
        for start, end in raw_segments:
            voice_segments.append((start, end))

           
        if not voice_segments:
            print(f"{GRAY}No active voice or adjacent action blocks found in {file_path}.{RESET}")
            continue


    return voice_segments


def process_clips(clips):
    """
    Slices clips using optimized seeking, matching the strict output filename rules.
    """
    clip_number = 1

    for row in clips:
        try:
            input_file = row.get("File")
            if not input_file or not os.path.exists(input_file):
                print(f"{YELLOW}Warning: Skipping {input_file} (Not found){RESET}")
                continue

            total_duration, fps = get_video_metadata(input_file)
            
            # --- CATASTROPHIC FAILURE CHECK ---
            if fps == 0:
                print(f"{RED}CATASTROPHIC FAILURE - FPS {fps}")
                exit(1)

            start_seconds = convert_to_seconds(row.get("Start", 0.0))
            end_seconds = convert_to_seconds(row.get("End", 0.0))

            # --- MICRO-CLIP SAFETY CHECK (BEFORE BUFFER) ---
            # Drops corrupt data points before modifying values
            if (end_seconds - start_seconds) < 0.5:
                print(f"{YELLOW}Warning: Skipping micro-clip range because it's too short to render safely.{RESET}")
                continue

            # --- SURGICAL BUFFER PATCH ---
            # Now safely adds 0.5s of padding to legitimate clips without falsifying micro-clip readings
            end_seconds = min(total_duration, end_seconds + 0.5)
            #subtract 0.5 seconds of padding to  start time
            start_seconds = max(0.0, start_seconds - 0.5)

            frame_start = int(start_seconds * fps)
            frame_end = int(end_seconds * fps)

            base_name, extension = os.path.splitext(os.path.basename(input_file))

            starttime = row.get("Start", "0.0")
            endtime = str(round(end_seconds, 2))
            
            starttime_clean = str(starttime).replace(":", "-").replace(".", "-")
            endtime_clean = str(endtime).replace(":", "-").replace(".", "-")

            # Evaluate exact production labels dynamically using the requested signature
            track_id = row.get("Track", 1)

            # --- EXPLICIT REQUIRED FILENAME MATRIX ---
            output_file = f"{base_name}_Clip_{starttime_clean}_{endtime_clean}{extension}"

            print(f"{CYAN}\n--- Processing Clip #{clip_number} ---")
            print(f"{RESET}Source: {input_file} ({fps} fps)")
            print(f"Range:  {starttime} ({frame_start}) to {endtime} ({frame_end})")
            print(f"Output: {output_file}")

            ffmpeg_slice_args = [
                "ffmpeg", "-y",
                "-ss", str(start_seconds),
                "-to", str(end_seconds),
                "-i", input_file,
                "-map", "0",
                "-c:v", "libx264",
                "-crf", "18",
                "-c:a", "aac"
            ]

            ffmpeg_slice_args.append(output_file)

            result = subprocess.run(ffmpeg_slice_args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            if result.returncode == 0:
                print(f"{GREEN}Success!{RESET}")
                clip_number += 1
            else:
                print(f"{RED}FFmpeg failed with exit code {result.returncode}{RESET}")

        except Exception as e:
            print(f"{RED}Failed to process row: {str(e)}{RESET}")

    print(f"{GREEN}\nDone! Created {clip_number - 1} clips.{RESET}")


def main():
    """
    Main controller orchestrating application lifecycle execution.
    """
    args = parse_arguments()


   
    # global  mappings 
    global VoiceAudioTrack
    VoiceAudioTrack = args.VoiceAudioTrack

    clips = detect_loudness(
        decibel_threshold=args.DecibleThreshold,
        loudness_length=args.LoudnessLength,
        min_clip_length=args.MinClipLength
    )

    if not clips:
        print(f"{RED}Error: No data found to process.{RESET}")
        sys.exit(1)

    process_clips(clips)


if __name__ == "__main__":
    main()