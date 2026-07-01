#!/usr/bin/env python3
import os
import argparse
from pydub import AudioSegment
from pydub.silence import detect_nonsilent

def main():
    parser = argparse.ArgumentParser(description="Split WAV into clips based purely on loudness threshold.")
    parser.add_argument("--input", required=True, help="Path to the input WAV file.")
    parser.add_argument("--DecibleThreshold", type=float, required=True, help="Loudness threshold in dB.")
    
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: Input file '{args.input}' not found.")
        return

    print(f"Loading {args.input}...")
    audio = AudioSegment.from_wav(args.input)

    # Step 1: Find the absolute, exact micro-boundaries of actual sound
    print(f"Analyzing precise speech onsets above {args.DecibleThreshold} dB...")
    precise_blocks = detect_nonsilent(
        audio,
        min_silence_len=300,  # Tight window catches the exact millisecond a word starts
        silence_thresh=args.DecibleThreshold
    )

    if not precise_blocks:
        print("No audio segments found crossing that loudness threshold.")
        return

    # Step 2: Merge those precise blocks into your 11 main segments
    # If the gap between words is less than 2 seconds, they stay in the same clip.
    INTERNAL_GAP_MS = 2000
    merged_blocks = []
    current_start, current_end = precise_blocks[0]

    for start, end in precise_blocks[1:]:
        if start - current_end < INTERNAL_GAP_MS:
            # Bridge the conversational gap, keeping the block continuous
            current_end = end
        else:
            # It's a real boundary break between your 11 clips
            merged_blocks.append((current_start, current_end))
            current_start, current_end = start, end
    # Catch the final segment
    merged_blocks.append((current_start, current_end))

    # Clean Padding Settings (DAW-standard alignment)
    PADDING_FRONT_MS = 200  # Safe cushion to protect initial consonants from being cut
    PADDING_BACK_MS = 1000  # Generous tail cushion so voice fades out naturally

    base_name, _ = os.path.splitext(os.path.basename(args.input))
    print(f"Processing {len(merged_blocks)} finalized voice segments...")

    for i, (start, end) in enumerate(merged_blocks):
        # Apply precise boundary cushions
        padded_start = max(0, start - PADDING_FRONT_MS)
        padded_end = min(len(audio), end + PADDING_BACK_MS)
        
        # Extract the perfect clip
        chunk = audio[padded_start:padded_end]
        duration = len(chunk) / 1000.0
        
        output_filename = f"{base_name}_clip_{i+1:02d}.wav"
        chunk.export(output_filename, format="wav")
        print(f"Saved: {output_filename} ({duration:.2f}s)")

    print("Done!")

if __name__ == "__main__":
    main()