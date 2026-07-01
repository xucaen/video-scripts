#!/usr/bin/env python3

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from vosk import Model, KaldiRecognizer

MODEL_PATH = r"C:\VOSK_MODELS\vosk-model-en-us-0.42-gigaspeech"

def parse_parameters():
    parser = argparse.ArgumentParser(description="Vosk Transcriber (hardcoded model + ffmpeg pipeline)")
    parser.add_argument("--audio", help="Input audio file (any format)")

    return parser.parse_args()


def open_audio_file(input_file):
    """
    Uses ffmpeg to convert ANY audio into:
    16kHz, mono, 16-bit PCM WAV (Vosk-friendly)
    """

    print("Converting audio with FFmpeg...")
    cmd = [
        "ffmpeg",
        "-y",
        "-i", input_file,
        "-ar", "16000",
        "-ac", "1",
        "-f", "s16le",
        "-"
    ]

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL
    )

    return process.stdout


def transcribe(audio_stream):
    
    print("Loading model...")
    model = Model(MODEL_PATH)
    recognizer = KaldiRecognizer(model, 16000)

    transcript = []

    print("Transcribing...")

    while True:
        data = audio_stream.read(4000)
        if len(data) == 0:
            break

        if recognizer.AcceptWaveform(data):
            result = json.loads(recognizer.Result())
            if result.get("text"):
                transcript.append(result["text"])

    final = json.loads(recognizer.FinalResult())
    if final.get("text"):
        transcript.append(final["text"])


    return "\n".join(transcript)



def main():

    args = parse_parameters()


    if not os.path.exists(args.audio):
        print(f"File not found: {args.audio}")
        sys.exit(1)

    audio_stream = open_audio_file(args.audio)


    

    text = transcribe(audio_stream)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.splitext(args.audio)[0] + f"_{timestamp}" + ".txt"

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(text)

    print(f"\nDone. Saved to: {output_file}")


if __name__ == "__main__":
    main()