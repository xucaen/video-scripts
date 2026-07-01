#!/usr/bin/env python3
import argparse
from datetime import datetime
import os
import subprocess
import sys
import json

def has_audio_stream(file_path):
    """Checks if a media file contains an audio stream using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a",
        "-show_entries", "stream=codec_type",
        "-of", "json", file_path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        return len(data.get("streams", [])) > 0
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
        print(f"ERROR: Video file must be corrupt. ")
        exit(2)

def main():
    parser = argparse.ArgumentParser(
        description="Mix external audio into an MP4 video's audio track (or add it if silent)."
    )
    
    parser.add_argument("-v", "--video", required=True, help="Path to the input MP4 video file")
    parser.add_argument("-a", "--audio", required=True, help="Path to the input audio file")
    parser.add_argument("-g", "--gain", type=float, default=0.0, help="Gain adjustment for the new audio track in dB (e.g., -10)")
    parser.add_argument("-o", "--output", help="Path to the output MP4 file (optional)")

    args = parser.parse_args()

    # Validate inputs
    if not os.path.exists(args.video):
        print(f"Error: Video file '{args.video}' not found.", file=sys.stderr)
        sys.exit(1)
        
    if not os.path.exists(args.audio):
        print(f"Error: Audio file '{args.audio}' not found.", file=sys.stderr)
        sys.exit(1)

    # Dynamic output naming
    if not args.output:
        video_dir, video_file = os.path.split(args.video)
        video_base, video_ext = os.path.splitext(video_file)
        audio_base, _ = os.path.splitext(os.path.basename(args.audio))
        timestamp = datetime.now().strftime("%H%M%S")
        
        output_name = f"{video_base}_{audio_base}_{timestamp}{video_ext}"
        args.output = os.path.join(video_dir, output_name)

    # Determine execution behavior based on original audio presence (Strict handling)
    video_has_audio = has_audio_stream(args.video)

    if video_has_audio:
        print("-> Video has audio track. Executing MIX function...")
        filter_complex = f"[1:a]volume={args.gain}dB[bg];[0:a][bg]amix=inputs=2:duration=first:dropout_transition=0[outa]"
    else:
        print("-> Video is silent. Executing MAKE (direct layer) function...")
        filter_complex = f"[1:a]volume={args.gain}dB[outa]"

    cmd = [
        "ffmpeg", "-y",
        "-i", args.video,
        "-i", args.audio,
        "-filter_complex", filter_complex,
        "-map", "0:v",          
        "-map", "[outa]",       
        "-c:v", "copy",         
        "-c:a", "aac",          
        "-shortest",  
        args.output
    ]

    print(f"Executing FFmpeg invocation...\n")
    
    try:
        subprocess.run(cmd, check=True)
        print(f"\nProcessing complete. Output saved to: {args.output}")
    except subprocess.CalledProcessError as e:
        print(f"\nFFmpeg execution failed with exit code {e.returncode}.", file=sys.stderr)
        sys.exit(e.returncode)
    except FileNotFoundError:
        print("\nError: 'ffmpeg' executable not found in system PATH.", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()