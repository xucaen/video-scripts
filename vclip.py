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
PURPLE = "\033[95m"
GRAY = "\033[90m"
RESET = "\033[0m"


def parse_arguments():
    """
    Defines the script interface with exactly three allowed parameters.
    """
    parser = argparse.ArgumentParser(description="Bulletproof True Loudness Video Slicer Engine.")
    parser.add_argument("--InputFile", type=str, required=True, help="Path to the input video file")
    parser.add_argument("--VoiceAudioTrack", type=int, default=1, help="The explicit audio track index FFmpeg will monitor for voice/audio activity.")
    parser.add_argument("--DecibleThreshold", type=int, default=-30, help="The LUFS/dB loudness limit above which audio is marked as active.")
    parser.add_argument("--MinClipDuration", type=float, default=2.0, help="The minimum continuous duration in seconds the audio must remain loud to qualify as a clip.")
    parser.add_argument("--Label", type=str, default="", help="Label to append to filename (optional)")
    
    return parser.parse_args()


def convert_to_seconds(time_value):
    """
    Normalizes time representations from mixed types into standard float seconds.
    """
    time_str = str(time_value).strip()
    if ":" in time_str:
        parts = time_str.split(":")
        if len(parts) == 3:  # HH:MM:SS
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        elif len(parts) == 2:  # MM:SS
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

    fps_args = [
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
        "stream=r_frame_rate", "-of", "default=noprint_wrappers=1:nokey=1", file_path
    ]

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
    Scans directory for video assets, performs windowed audio energy scans via 
    FFmpeg silencedetect, and maps talking spikes chronologically.
    """

    print(f"{CYAN}\n--------------------------------------------------")
    print(" [Detect-Loudness Configuration]")
    print(f"  -> Audio Track Monitored : {YELLOW}{VoiceAudioTrack}")
    print(f"  {CYAN}-> True Energy Floor     : {YELLOW}{decibel_threshold} LUFS/dB")
    print(f"  {CYAN}-> Min Video Clip Duration: {YELLOW}{min_clip_duration} seconds")
    print(f"{CYAN}--------------------------------------------------")

    total_duration, frame_rate = get_video_metadata(file_path)

    print(f"{YELLOW}\n==================================================")
    print(f"Analyzing: {file_path}")
    print(f"=================================================={RESET}")

    if total_duration == 0.0:
        print(f"{RED}ERROR: Could not determine duration for {file_path}. Skipping.{RESET}")
        exit(4)

    # NEW: We need a reasonable pause duration to separate talk blocks. 
    # If a pause is longer than this many seconds, we split the clip.
    silence_gap_threshold = 0.9

    # Force FFmpeg to execute the filter chain using our gap threshold, NOT the final clip duration
    ffmpeg_args = [
        "ffmpeg", "-y", "-i", file_path,
        "-filter_complex", f"[0:a:{VoiceAudioTrack}]silencedetect=noise={decibel_threshold}dB:d={silence_gap_threshold}[outa]",
        "-map", "[outa]",
        "-f", "null", "-"
    ]

    result = subprocess.run(ffmpeg_args, stderr=subprocess.PIPE, text=True)
    ffmpeg_logs = result.stderr

    # Parse all silence transitions chronologically
    events = []
    for match in re.finditer(r'silence_(?P<type>start|end):\s*(?P<time>[\d\.]+)', ffmpeg_logs):
        events.append({'type': match.group('type'), 'time': float(match.group('time'))})

    # ERROR CHECK 1: The video has absolutely no silence
    if not events:
        print(f"{RED}ERROR: Video has no silence boundaries. Exiting.{RESET}")
        exit(5)

    # ERROR CHECK 2: The entire video is silent
    # (If there is only 1 event and it's a silence_start at 0.0, or if a single silence covers the full duration)
    if len(events) == 1 and events[0]['type'] == 'start' and events[0]['time'] == 0.0:
        print(f"{RED}ERROR: The entire video is silent. Exiting.{RESET}")
        exit(6)

    voice_segments = []
    print(f"{PURPLE}PROCESSING TIMELINE... Found {len(events)} audio transitions.{RESET}")

    current_voice_start = 0.0

    for ev in events:
        if ev['type'] == 'start':
            # Silence starts here -> Voice segment ends here
            voice_end = ev['time']
            
            # FIXED: Enforce that the voice block must meet your minimum video clip duration
            if (voice_end - current_voice_start) >= min_clip_duration:
                print(f"{PURPLE}Detected Voice Block -> Start: {round(current_voice_start, 2)}s | End: {round(voice_end, 2)}s | Length: {round(voice_end - current_voice_start, 2)}s{RESET}")
                voice_segments.append({"File": file_path, "Start": current_voice_start, "End": voice_end})
            else:
                print(f"{GRAY}Skipping Voice Block -> {round(voice_end - current_voice_start, 2)}s is below minimum clip duration ({min_clip_duration}s){RESET}")
                
        elif ev['type'] == 'end':
            # Silence ends here -> Next voice segment starts here
            current_voice_start = ev['time']

    # If the video ends while audio is still active
    if events and events[-1]['type'] == 'end':
        # FIXED: Enforce minimum clip duration for the final segment
        if (total_duration - current_voice_start) >= min_clip_duration:
            print(f"{PURPLE}Detected Voice Block -> Start: {round(current_voice_start, 2)}s | End: {round(total_duration, 2)}s | Length: {round(total_duration - current_voice_start, 2)}s{RESET}")
            voice_segments.append({"File": file_path, "Start": current_voice_start, "End": total_duration})

    if not voice_segments:
        print(f"{GRAY}No active voice segments found meeting the duration requirements.{RESET}")

    return voice_segments

def process_clips(clips, label):
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
                
            start_seconds = convert_to_seconds(row.get("Start", 0.0))
            end_seconds = convert_to_seconds(row.get("End", 0.0))

            if (end_seconds - start_seconds) < 0.2:
                continue

            # Apply 0.5-second structural padding safely bounded by media lengths
            buffered_start = max(0.0, start_seconds - 0.5)
            buffered_end = min(total_duration, end_seconds + 0.5)

            frame_start = int(buffered_start * fps)
            frame_end = int(buffered_end * fps)

            base_name, extension = os.path.splitext(os.path.basename(file_path))

            starttime_clean = str(round(buffered_start, 2)).replace(":", "-").replace(".", "-")
            endtime_clean = str(round(buffered_end, 2)).replace(":", "-").replace(".", "-")

            output_file = f"{base_name}_Clip_{starttime_clean}_{endtime_clean}_voice_{label}{extension}"

            print(f"{CYAN}\n--- Processing Clip #{clip_number} ---")
            print(f"{RESET}Source: {file_path} ({round(fps, 2)} fps)")
            print(f"Range:  {round(buffered_start, 2)}s (Frame {frame_start}) to {round(buffered_end, 2)}s (Frame {frame_end})")
            print(f"Output: {output_file}")

            ffmpeg_slice_args = [
                "ffmpeg", "-y",
                "-ss", str(buffered_start),
                "-to", str(buffered_end),
                "-i", file_path,
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

    process_clips(clips, args.Label)


if __name__ == "__main__":
    main()