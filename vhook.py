import os
import sys
import argparse
import numpy as np
import cv2
import librosa
import json
import threading
import time


class FrameSpinner:
    def __init__(self, message="Analyzing video frames"):
        self.message = message
        self.spinner_symbols = ['|', '/', '-', '\\']
        self.stop_running = threading.Event()
        self.spinner_thread = None

    def _spin(self):
        idx = 0
        while not self.stop_running.is_set():
            # \r moves the cursor back to the start of the line
            # We write explicitly to sys.stderr so it avoids polluting STDOUT
            sys.stderr.write(f"\r{self.message}... {self.spinner_symbols[idx]}")
            sys.stderr.flush()
            idx = (idx + 1) % len(self.spinner_symbols)
            time.sleep(0.1)
        
        # Clean up the line when finished
        sys.stderr.write("\r" + " " * (len(self.message) + 10) + "\r")
        sys.stderr.flush()

    def start(self):
        self.stop_running.clear()
        self.spinner_thread = threading.Thread(target=self._spin)
        self.spinner_thread.daemon = True
        self.spinner_thread.start()

    def stop(self):
        if self.spinner_thread:
            self.stop_running.set()
            self.spinner_thread.join()    

# Setup the command line arguments
parser = argparse.ArgumentParser()
parser.add_argument("--input", type=str, required=True)
parser.add_argument("--output_json", type=str, required=True) # PowerShell passes the destination file path here
args = parser.parse_args()

# Verify the input video actually exists
if not os.path.exists(args.input):
    print(f"[VHOOK ERROR] Video file not found: {args.input}", file=sys.stderr)
    sys.exit(1)

# 2. Check if the output JSON file path exists
if os.path.exists(args.output_json):
    # If it exists, test that we can write to it by attempting to open it in append mode
    try:
        with open(args.output_json, 'a'):
            pass
    except (IOError, OSError) as e:
        print(f"[VHOOK ERROR] Output file exists but is not writeable: {e}", file=sys.stderr)
        sys.exit(1)
else:
    # 2b. If the file does not exist, attempt to create it empty right now
    try:
        with open(args.output_json, 'w') as f:
            f.write("") # Create a clean empty file template stub
    except (IOError, OSError) as e:
        print(f"[VHOOK ERROR] Output file did not exist and creation failed: {e}", file=sys.stderr)
        sys.exit(1)

# 3. Final verification: If the file STILL does not exist on disk, EXIT immediately
if not os.path.exists(args.output_json):
    print(f"[VHOOK ERROR] State Failure: Output file '{args.output_json}' is missing.", file=sys.stderr)
    sys.exit(1)
    
# Open the video file
cap = cv2.VideoCapture(args.input)
if not cap.isOpened():
    print("[VHOOK ERROR] OpenCV could not open the video file.", file=sys.stderr)
    sys.exit(1)

# Grab core properties from the video
fps = cap.get(cv2.CAP_PROP_FPS)
total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
duration = total_frames / fps

print(f"[VHOOK] Video Duration: {duration:.2f}s", file=sys.stderr)

# Calculate frame index parameters (Skip first 10 seconds and final 10 seconds)
start_frame = 0
end_frame = total_frames
print(f"[VHOOK] Search Region: {start_frame / fps:.2f}s -> {end_frame / fps:.2f}s", file=sys.stderr)

# -------------------------------------------------------------
# STEP 1: CALCULATE VISUAL MOTION PROFILE
# -------------------------------------------------------------
motion_scores = np.zeros(total_frames)
prev_gray = None
frame_idx = 0
skip_frames = 30  # Skipped 30 frames per iteration for maximum speed

spinner = FrameSpinner("Processing frame visual metadata")
spinner.start()

while frame_idx < total_frames:
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)

    ret, frame = cap.read()
    if not ret:
        break  # End of video reached

    # Convert frame to black and white
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    if prev_gray is not None:
        # Subtract the current frame from the previous frame to find movement
        diff = cv2.absdiff(gray, prev_gray)
        _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
        changed_pixels = cv2.countNonZero(thresh)

        # Fill the skipped frame block with this score to maintain timeline alignment
        motion_scores[frame_idx : frame_idx + skip_frames] = float(changed_pixels)

    prev_gray = gray
    frame_idx += skip_frames

cap.release()

# Normalize motion scores (scales numbers cleanly between 0.0 and 1.0)
if motion_scores.max() > 0:
    motion_scores = motion_scores / motion_scores.max()

# -------------------------------------------------------------
# STEP 2: CALCULATE AUDIO VOLUME PROFILE
# -------------------------------------------------------------
audio_scores = np.zeros(total_frames)
try:
    y, sr = librosa.load(args.input, sr=None, mono=True)
    rms = librosa.feature.rms(y=y)[0]
    
    if len(rms) > 0:
        # Map audio array length onto video frame count space
        xp = np.linspace(0, 1, len(rms))
        x = np.linspace(0, 1, total_frames)
        audio_scores = np.interp(x, xp, rms)
        
        # Scale audio scores between 0.0 and 1.0
        if audio_scores.max() > 0:
            audio_scores = audio_scores / audio_scores.max()
except Exception as e:
    print(f"[VHOOK WARNING] Audio skipped: {e}", file=sys.stderr)

# -------------------------------------------------------------
# STEP 3: COMBINE MATRIX AND FIND THE HIGHEST 5-SECOND SCORING WINDOW
# -------------------------------------------------------------
# Mix them: 70% value on motion, 30% value on volume
combined_timeline = (motion_scores * 0.70) + (audio_scores * 0.30)

window_size_frames = int(5.0 * fps)

# Vectorized rolling average to replace the slow Python loop
search_timeline = combined_timeline[start_frame:end_frame]
if len(search_timeline) >= window_size_frames:
    moving_sums = np.convolve(search_timeline, np.ones(window_size_frames), mode='valid')
    moving_averages = moving_sums / window_size_frames
    
    best_idx_in_search = np.argmax(moving_averages)
    best_score = float(moving_averages[best_idx_in_search])
    best_frame_index = start_frame + best_idx_in_search
else:
    best_score = 0.0
    best_frame_index = start_frame

# Translate frame index back into real-world time boundaries
hook_start = round(best_frame_index / fps, 2)
hook_end = round(hook_start + 5.0, 2)

if hook_end > duration:
    hook_end = round(duration, 2)
    hook_start = max(0.0, round(hook_end - 5.0, 2))

print(f"[VHOOK] Best Window: {hook_start}s -> {hook_end}s (Score: {best_score:.3f})", file=sys.stderr)

# -------------------------------------------------------------
# STEP 4: SAVE METADATA DIRECTLY TO THE PASSED TEMPORARY FILE PATH
# -------------------------------------------------------------
payload = {
    "hook_start": hook_start,
    "hook_end": hook_end,
    "hook_duration": 5.0,
    "hook_score": round(best_score, 3)
}

try:
    with open(args.output_json, "w") as f:
        json.dump(payload, f, indent=2)
except Exception as e:
    print(f"[VHOOK ERROR] Could not save JSON file: {e}", file=sys.stderr)
    sys.exit(1)

# Success finish execution pass
spinner.stop()
sys.exit(0)

