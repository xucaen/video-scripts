import argparse
import glob
import os
import subprocess
import cv2
import librosa
import numpy as np
from moviepy.audio.io.AudioFileClip import AudioFileClip
from moviepy.video.io.VideoFileClip import VideoFileClip


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Bulletproof State-Driven Video Slicer Engine."
    )
    parser.add_argument(
        "--x", type=int, required=True, help="Top-left X coordinate"
    )
    parser.add_argument(
        "--y", type=int, required=True, help="Top-left Y coordinate"
    )
    parser.add_argument(
        "--w", type=int, required=True, help="Width of zoom box"
    )
    parser.add_argument(
        "--h", type=int, required=True, help="Height of zoom box"
    )
    return parser.parse_args()


def safe_subclip(clip, start, end):
    """Handles MoviePy v1 (subclip) vs v2 (subclipped) cross-compatibility."""
    if hasattr(clip, "subclipped"):
        return clip.subclipped(start, end)
    return clip.subclip(start, end)


def check_audio_track_availability(video_path, stream_index):
    """Verifies if the requested audio track actually exists via a swift test command."""
    test_file = f"temp_test_{stream_index}.aac"
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        "0",
        "-i",
        video_path,
        "-t",
        "0.1",
        "-map",
        f"0:a:{stream_index}",
        "-c:a",
        "aac",
        test_file,
    ]
    res = subprocess.run(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    exists = res.returncode == 0 and os.path.exists(test_file)
    if os.path.exists(test_file):
        os.remove(test_file)
    return exists


def calculate_clip_threshold(video_path, stream_index):
    """
    Scans the audio track to find its unique quietest and loudest levels,
    then automatically calculates a smart threshold line.
    """
    temp_audio = f"temp_threshold_scan_{stream_index}.aac"
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        video_path,
        "-map",
        f"0:a:{stream_index}",
        "-c:a",
        "aac",
        temp_audio,
    ]
    try:
        subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        if not os.path.exists(temp_audio):
            print(
                f" [Audio Engine] Could not extract audio track. Using a safe fallback threshold."
            )
            return 0.3

        # Load the raw audio data
        y, sr = librosa.load(temp_audio, sr=None, mono=True)
        if len(y) == 0:
            return 0.3

        # Calculate the energy envelope (volume levels) over time
        rms = librosa.feature.rms(y=y)[0]
        rms_min = np.min(rms)
        rms_max = np.max(rms)

        # If the video is completely dead silent, return a safe baseline
        if rms_max <= rms_min:
            return 0.3

        # Standardize the audio curve to a predictable 0.0 - 1.0 range
        normalized_rms = (rms - rms_min) / (rms_max - rms_min)

        # Calculate a smart "nice" threshold:
        # Find the mathematical average volume, and place the trigger line
        # just above it using the standard deviation (the variation in volume).
        audio_average = np.mean(normalized_rms)
        audio_variation = np.std(normalized_rms)
        calculated_threshold = audio_average + (audio_variation * 1.2)

        # Guard rails to keep the threshold realistic (never let it clip above 0.95)
        calculated_threshold = max(0.1, min(calculated_threshold, 0.95))

        print(
            f" [Audio Engine] Audio Range mapped. Low: {rms_min:.5f} | High: {rms_max:.5f}"
        )
        print(
            f" [Audio Engine] Automatically selected a responsive threshold of: {calculated_threshold:.2f}"
        )
        return float(calculated_threshold)

    except Exception as e:
        print(f"[WARNING] Automatic threshold calculation failed: {e}")
        return 0.3
    finally:
        if os.path.exists(temp_audio):
            os.remove(temp_audio)


def extract_audio_state_intervals(
    video_path, stream_index, duration, calculated_threshold
):
    """
    Slices the timeline into raw zoom states using the calculated threshold.
    Accepts zoom spikes of any length—no matter how short.
    """
    temp_audio = f"temp_state_scan_{stream_index}.aac"
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        video_path,
        "-map",
        f"0:a:{stream_index}",
        "-c:a",
        "aac",
        temp_audio,
    ]
    zoom_intervals = []
    try:
        subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        if not os.path.exists(temp_audio):
            return []

        y, sr = librosa.load(temp_audio, sr=None, mono=True)
        if len(y) == 0:
            return []

        rms = librosa.feature.rms(y=y)[0]
        times = librosa.frames_to_time(range(len(rms)), sr=sr)

        # Normalize the curve identically to Function 1
        rms_min, rms_max = np.min(rms), np.max(rms)
        if rms_max > rms_min:
            normalized_rms = (rms - rms_min) / (rms_max - rms_min)
        else:
            normalized_rms = np.zeros_like(rms)

        # Tag frames that cross our calculated trigger line
        above_threshold = normalized_rms > calculated_threshold
        in_peak = False
        start_time = 0.0

        for idx, active in enumerate(above_threshold):
            current_time = float(times[idx])
            if active and not in_peak:
                # The volume spike begins right here
                in_peak = True
                start_time = current_time
            elif not active and in_peak:
                # The volume drops back down
                in_peak = False
                end_time = current_time
                # Saved instantly with zero duration gating
                zoom_intervals.append((start_time, end_time))

        if in_peak:
            zoom_intervals.append((start_time, float(duration)))

    except Exception as e:
        print(f"[WARNING] Timeline state extraction failed: {e}")
    finally:
        if os.path.exists(temp_audio):
            os.remove(temp_audio)

    return zoom_intervals


def merge_overlapping_intervals(intervals):
    """Bugfix 5: Aggregates colliding or adjacent intervals chronologically."""
    if not intervals:
        return []

    sorted_intervals = sorted(intervals, key=lambda x: x[0])
    merged = [sorted_intervals[0]]

    for next_start, next_end in sorted_intervals[1:]:
        last_start, last_end = merged[-1]
        if next_start <= last_end:
            merged[-1] = (last_start, max(last_end, next_end))
        else:
            merged.append((next_start, next_end))

    return merged


def build_interwoven_timeline(zoom_intervals, total_duration):
    """Bugfix 6: Weaves standard cuts with sample-accurate absolute bounds."""
    timeline = []
    current_time = 0.0

    for z_start, z_end in zoom_intervals:
        if z_start > current_time:
            timeline.append((current_time, z_start, "cut"))
        timeline.append((z_start, z_end, "zoom"))
        current_time = z_end

    if current_time < total_duration:
        timeline.append((current_time, total_duration, "cut"))

    return timeline


def analyze_spatial_dynamics_window(video_path, start, end, args, v_w, v_h):
    """Bugfix 2, 8 & 9: Safe dual frame validation, ROI clamp verification, and grayscale brightness."""
    # Bugfix 8: Absolute clipping boundary safeguards
    r_x = max(0, min(args.x, v_w - 1))
    r_y = max(0, min(args.y, v_h - 1))
    r_w = max(1, min(args.w, v_w - r_x))
    r_h = max(1, min(args.h, v_h - r_y))

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    start_frame = int(start * fps)
    end_frame = int(end * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

    # Bugfix 2: Independent tuple verification to prevent partial None reads
    ret1, frame1 = cap.read()
    ret2, frame2 = cap.read()

    if not ret1 or not ret2:
        cap.release()
        return "right"

    left_movement, right_movement = 0, 0
    roi_center_x = r_w / 2
    current_frame = start_frame + 2

    while cap.isOpened() and current_frame < end_frame:
        roi1 = frame1[r_y : r_y + r_h, r_x : r_x + r_w]
        roi2 = frame2[r_y : r_y + r_h, r_x : r_x + r_w]

        if roi1.size == 0 or roi2.size == 0:
            break

        # Bugfix 9: Convert to full grayscale to inspect luminosity across all color spaces
        gray_roi = cv2.cvtColor(roi1, cv2.COLOR_BGR2GRAY)
        if gray_roi.mean() >= 3.0:
            diff = cv2.absdiff(roi1, roi2)
            gray_diff = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
            _, thresh = cv2.threshold(gray_diff, 25, 255, cv2.THRESH_BINARY)
            contours, _ = cv2.findContours(
                thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )

            for c in contours:
                area = cv2.contourArea(c)
                if area > 300:
                    M = cv2.moments(c)
                    if M["m00"] != 0:
                        cX = int(M["m10"] / M["m00"])
                        if cX < roi_center_x:
                            left_movement += area
                        else:
                            right_movement += area

        frame1 = frame2
        ret2, frame2 = cap.read()
        current_frame += 1
        if not ret2:
            break

    cap.release()
    return "left" if left_movement >= right_movement else "right"


def export_segment(
    video_path, start, end, mode, index, direction, audio_stream_idx, args
):
    """Bugfix 3 & 7: Protected sub-zero crop boundaries and try-finally asset cleanups."""
    output_filename = f"Clip_{index:03d}_{mode}.mp4"
    duration = end - start

    with VideoFileClip(video_path) as full_video:
        video_w, video_h = full_video.size
        sub_clip = safe_subclip(full_video, start, end)

        if mode == "zoom":
            pan_offset = int(args.w * 0.15)
            # Bugfix 3: Guarantee box measurements never evaluate below coordinate space minimums
            clamped_w = min(args.w, video_w)
            clamped_h = min(args.h, video_h)
            target_x = args.x

            if direction == "left":
                target_x = max(0, args.x - pan_offset)
            elif direction == "right":
                target_x = min(video_w - clamped_w, args.x + pan_offset)

            # Final verification fallback pass
            target_x = max(0, min(target_x, video_w - clamped_w))
            target_y = max(0, min(args.y, video_h - clamped_h))

            sub_clip = sub_clip.cropped(
                x1=target_x, y1=target_y, width=clamped_w, height=clamped_h
            )
            print(
                f" -> Clip_{index:03d}: ZOOM [{direction.upper()}] | {start:.2f}s to {end:.2f}s"
            )
        else:
            print(
                f" -> Clip_{index:03d}: CUT [Standard] | {start:.2f}s to {end:.2f}s"
            )

        temp_audio = f"temp_slice_{index}_{mode}.aac"
        ffmpeg_cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            str(start),
            "-i",
            video_path,
            "-t",
            str(duration),
            "-map",
            f"0:a:{audio_stream_idx}",
            "-c:a",
            "aac",
            temp_audio,
        ]
        subprocess.run(
            ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

        # Bugfix 7: Explicit try-finally wrapper blocks to guarantee OS resource cleanup on failure
        audio_clip = None
        try:
            if os.path.exists(temp_audio) and os.path.getsize(temp_audio) > 0:
                audio_clip = AudioFileClip(temp_audio)
                sub_clip = sub_clip.with_audio(audio_clip)
            sub_clip.write_videofile(
                output_filename, codec="libx264", audio_codec="aac", logger=None
            )
        finally:
            if audio_clip:
                audio_clip.close()
            if os.path.exists(temp_audio):
                os.remove(temp_audio)


def main():
    args = parse_arguments()

    # Early validation check
    if args.w <= 0 or args.h <= 0 or args.x < 0 or args.y < 0:
        print(
            "[CRITICAL] Initialization failed: Coordinates and dimensions must evaluate above zero."
        )
        return

    video_files = []
    for ext in ("*.mkv", "*.mp4", "*.webm"):
        video_files.extend(glob.glob(os.path.join(os.getcwd(), ext)))

    global_clip_counter = 1

    for video in video_files:
        filename = os.path.basename(video)
        if any(x in filename for x in ["_zoom", "_cut"]):
            continue

        cap = cv2.VideoCapture(video)
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        video_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        video_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()

        if fps == 0 or frame_count == 0:
            continue

        duration = frame_count / fps
        print(
            f"\nParsing Metadata for: {filename} ({duration:.2f}s) | Native Resolution: {video_w}x{video_h}"
        )

        # Bugfix 4: Adaptive Audio Stream Assessment Layer
        target_audio_stream = 2  # Preferred baseline target
        if not check_audio_track_availability(video, target_audio_stream):
            print(
                f" [Audio Engine] Track 3 (0:a:2) missing. Recalibrating to standard Track 1 (0:a:0)."
            )
            target_audio_stream = 0

        if not check_audio_track_availability(video, target_audio_stream):
            print(
                f" [Audio Engine] CRITICAL: No audio assets found in '{filename}'. Skipping."
            )
            continue

        # Automatically calculate unique threshold line for this video
        calculated_thresh = calculate_clip_threshold(
            video, stream_index=target_audio_stream
        )

        # Extract timeline map using calculated threshold bounds
        raw_intervals = extract_audio_state_intervals(
            video,
            stream_index=target_audio_stream,
            duration=duration,
            calculated_threshold=calculated_thresh,
        )
        merged_intervals = merge_overlapping_intervals(raw_intervals)
        timeline_map = build_interwoven_timeline(merged_intervals, duration)

        print(
            f"[Pipeline Factory] Split layout assigned. Compiling {len(timeline_map)} chronological segments."
        )

        for start, end, mode in timeline_map:
            # Skip rendering microscopic timeline noise
            if (end - start) < 0.01:
                continue

            direction = "right"
            if mode == "zoom":
                direction = analyze_spatial_dynamics_window(
                    video, start, end, args, video_w, video_h
                )

            export_segment(
                video,
                start,
                end,
                mode,
                global_clip_counter,
                direction,
                target_audio_stream,
                args,
            )
            global_clip_counter += 1

    print("\nProcessing workflow safely concluded.")


if __name__ == "__main__":
    main()