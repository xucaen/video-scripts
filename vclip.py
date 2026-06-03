import os
import sys
import re
import csv
import glob
import argparse
import subprocess

# --- COLOR DEFINITIONS ---
# We define standard ANSI escape characters to match your original PowerShell telemetry 
# colors, maintaining UI consistency across terminal environments.
CYAN = "\033[96m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
RED = "\033[91m"
GRAY = "\033[90m"
RESET = "\033[0m"

def parse_arguments():
    """
    Defines the script interface. We preserve your exact parameter flags and aliases 
    to prevent breaking existing automation setups or manual execution habits.
    """
    parser = argparse.ArgumentParser(description="Bulletproof Multi-Track Video Slicer Engine.")
    
    parser.add_argument("-i", "--ListFile", type=str, 
                        help="Path to the CSV file containing pre-defined clip boundaries.")
    parser.add_argument("-a", "--AudioTrack", type=int, default=1, 
                        help="The explicit audio track index FFmpeg will monitor for voice activity.")
    parser.add_argument("-db", "--DecibleThreshold", type=int, default=-30, 
                        help="The decibel limit below which audio is classified as absolute silence.")
    parser.add_argument("-l", "--MinClipLength", type=float, default=3.0, 
                        help="The minimum runtime required for a non-silent region to be saved.")
    parser.add_argument("-sl", "--SilenceLength", type=float, default=1.5, 
                        help="The minimum duration of quiet time required to trigger a clip split.")
    
    return parser.parse_args()


def get_video_metadata(input_video):
    """
    Queries ffprobe to extract structural metadata. We fetch both duration and FPS 
    in a single utility function to minimize external process overhead.
    """
    # Fetching total duration safely
    duration_args = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration", 
        "-of", "default=noprint_wrappers=1:nokey=1", input_video
    ]
    
    # Fetching frame rate to compute precise frame boundaries if necessary
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
            fps = num / den if den != 0 else 60.0
        else:
            fps = float(fps_text) if fps_text else 60.0
    except Exception:
        fps = 60.0

    return total_duration, fps


def convert_to_seconds(time_value):
    """
    Normalizes time representations. Since input matrices can mixed-format data, 
    this safely interprets both standard raw floats and timestamp strings (HH:MM:SS).
    """
    time_str = str(time_value).strip()
    if ":" in time_str:
        parts = time_str.split(":")
        if len(parts) == 3:  # HH:MM:SS
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        elif len(parts) == 2:  # MM:SS
            return float(parts[0]) * 60 + float(parts[1])
    return float(time_str)


def detect_silence(audio_track, decibel_threshold, silence_length, min_clip_length):
    """
    Scans the local working directory for supported media configurations, executing 
    algorithmic tone analysis to flag regions containing viable voice data.
    """
    print(f"{CYAN}\n--------------------------------------------------")
    print(" [Detect-Silence Configuration]")
    print(f"  -> Target Audio Track   : {YELLOW}{audio_track}{RESET}")
    print(f"  -> Volume Threshold     : {YELLOW}{decibel_threshold} dB{RESET}")
    print(f"  -> Min Silence Duration : {YELLOW}{silence_length} seconds{RESET}")
    print(f"  -> Target Clip Length   : {YELLOW}{min_clip_length} seconds.{RESET}")
    print(f"{CYAN}--------------------------------------------------{RESET}")

    video_extensions = ("*.mp4", "*.mkv", "*.mov", "*.avi")
    video_files = []
    
    # We aggregate files across multiple extensions and explicitly sort them by creation 
    # time to guarantee the final output assets retain a chronological chronological narrative flow.
    for ext in video_extensions:
        video_files.extend(glob.glob(ext))
    
    video_files.sort(key=os.path.getctime)

    if not video_files:
        print(f"{RED}Error: No matching video files found in the current folder.{RESET}")
        sys.exit(1)

    print(f"{GREEN}Found {len(video_files)} videos to process (sorted chronologically).{RESET}")
    all_clips = []

    for file_path in video_files:
        print(f"{YELLOW}\n==================================================")
        print(f"Analyzing: {file_path}")
        print(f"=================================================={RESET}")

        total_duration, _ = get_video_metadata(file_path)
        if total_duration == 0.0:
            print(f"{YELLOW}Warning: Could not determine duration for {file_path}. Skipping.{RESET}")
            continue

        # We construct the exact algorithmic analysis filter matrix. Note that FFmpeg utilizes 
        # 0-indexed stream mapping, natively tracking the stream configurations.
        ffmpeg_args = [
            "ffmpeg", "-i", file_path,
            "-filter_complex", f"[0:a:{audio_track}]silencedetect=noise={decibel_threshold}dB:d={silence_length}",
            "-f", "null", "-"
        ]

        # Intercepting stderr is required because FFmpeg routes analytical logging metadata 
        # to the error stream rather than standard output streams.
        result = subprocess.run(ffmpeg_args, stderr=subprocess.PIPE, text=True)
        ffmpeg_logs = result.stderr

        # Regex targets matching patterns generated by the native FFmpeg engine engine filters
        silence_matches = re.finditer(r'silence_start:\s*(?P<start>[\d\.]+)|silence_end:\s*(?P<end>[\d\.]+)', ffmpeg_logs)

        local_clips = []
        current_start = 0.0

        for match in silence_matches:
            if match.group('start'):
                silence_start = float(match.group('start'))
                if silence_start > current_start:
                    clip_start = current_start
                    clip_end = silence_start

                    # Discard regions falling below the user runtime criteria to avoid artifact spam
                    if (clip_end - clip_start) >= min_clip_length:
                        local_clips.append({
                            "File": file_path,
                            "Start": str(round(clip_start, 2)),
                            "End": str(round(clip_end, 2))
                        })
            elif match.group('end'):
                current_start = float(match.group('end'))

        # Append any active audio data sitting between the final quiet region and the file's literal end
        if current_start < total_duration:
            clip_start = current_start
            clip_end = total_duration
            if (clip_end - clip_start) >= min_clip_length:
                local_clips.append({
                    "File": file_path,
                    "Start": str(round(clip_start, 2)),
                    "End": str(round(clip_end, 2))
                })

        if not local_clips:
            print(f"{GRAY}No voice regions detected in {file_path}.{RESET}")
            continue

        all_clips.extend(local_clips)

    return all_clips


def parse_list_file(list_file_path):
    """
    Parses and sanitizes user-provided batch schedules, stripping whitespaces 
    and escape characters to handle imperfect CSV construction.
    """
    if not os.path.exists(list_file_path):
        print(f"{RED}Error: List file '{list_file_path}' not found.{RESET}")
        sys.exit(1)

    clips = []
    with open(list_file_path, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            clean_row = {key.strip(): value.strip().strip('"') for key, value in row.items()}
            clips.append(clean_row)
    return clips


def process_clips(clips, min_clip_length):
    """
    Iterates through designated split coordinates, slicing clips using optimized
    FFmpeg mapping definitions that prevent stream downmixing or structural track loss.
    """
    clip_number = 1

    for row in clips:
        try:
            input_file = row.get("File")
            if not input_file or not os.path.exists(input_file):
                print(f"{YELLOW}Warning: Skipping {input_file} (Not found){RESET}")
                continue

            total_duration, fps = get_video_metadata(input_file)
            if fps == 0:
                fps = 60.0
                print(f"{YELLOW}Warning: FPS check failed for {input_file}, defaulting to 60{RESET}")

            # Parse string-based formats down to raw floating-point seconds
            start_seconds = convert_to_seconds(row.get("Start", 0.0))
            end_seconds = convert_to_seconds(row.get("End", 0.0))

            frame_start = int(start_seconds * fps)
            frame_end = int(end_seconds * fps)

            # Enforce a strict minimum length check to filter out empty, corrupt micro-renders
            if (frame_end - frame_start) < 3:
                print(f"{YELLOW}Warning: Skipping micro-clip range ({frame_start} to {frame_end}) because it's too short to render safely.{RESET}")
                continue

            base_name, extension = os.path.splitext(os.path.basename(input_file))
            padded_number = f"{clip_number:03d}"
            output_file = f"{base_name}_Clip_{padded_number}{extension}"

            print(f"{CYAN}\n--- Processing Clip #{clip_number} ---")
            print(f"{RESET}Source: {input_file} ({fps} fps)")
            print(f"Range:  {row.get('Start')} ({frame_start}) to {row.get('End')} ({frame_end})")
            print(f"Output: {output_file}")

            # --- THE FIX INTEGRATION ---
            # 1. We position -ss and -to BEFORE the -i parameter to enable lightning-fast 
            #    seek operations, avoiding decoding unneeded hours of footage.
            # 2. "-map 0" instructs FFmpeg to target and retain ALL available data tracks 
            #    (Video stream, plus all 3 separate Audio tracks, plus Subtitles).
            # 3. By using standard video encoders alongside individual audio stream encoding 
            #    (-c:a aac), FFmpeg duplicates and encodes each discrete track into the new 
            #    asset completely separated—preventing them from collapsing into a single track.
            ffmpeg_slice_args = [
                "ffmpeg", "-y",
                "-ss", str(start_seconds),
                "-to", str(end_seconds),
                "-i", input_file,
                "-map", "0",
                "-c:v", "libx264",
                "-crf", "18",
                "-c:a", "aac",
                output_file
            ]

            # Standard process control executing block operations in the background
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
    Main controller orchestrating application lifecycle execution based 
    on structural command inputs.
    """
    args = parse_arguments()

    # Route programmatic workflow branches depending on whether an input database file is present
    if args.ListFile:
        clips = parse_list_file(args.ListFile)
    else:
        clips = detect_silence(
            audio_track=args.AudioTrack,
            decibel_threshold=args.DecibleThreshold,
            silence_length=args.SilenceLength,
            min_clip_length=args.MinClipLength
        )

    if not clips:
        print(f"{RED}Error: No data found to process.{RESET}")
        sys.exit(1)

    process_clips(clips, args.MinClipLength)


if __name__ == "__main__":
    main()