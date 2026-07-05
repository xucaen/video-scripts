import os
import argparse
import subprocess
import cv2

def parse_arguments():
    parser = argparse.ArgumentParser(description="Origin-Anchored Max Aspect Crop Engine")
    parser.add_argument("--InputFile", type=str, required=True, help="Path to the input video file")
    parser.add_argument("--x", type=int, default=0, help="Scripture Crop X Coordinate Start Point")
    parser.add_argument("--y", type=int, default=0, help="Scripture Crop Y Coordinate Start Point")
    return parser.parse_args()

def calculate_max_crop_from_origin(args, native_w, native_h):
    # Absolute rule: crop_x and crop_y match args.x and args.y precisely
    crop_x = args.x
    crop_y = args.y

    # Determine the maximum remaining canvas real estate from the starting points
    available_w = native_w - args.x
    available_h = native_h - args.y

    # Determine target aspect ratio based on original video orientation
    if native_w >= native_h:
        # Landscape original -> Target 16:9 box
        target_ratio = 16 / 9
    else:
        # Portrait original -> Target 9:16 box
        target_ratio = 9 / 16

    # Calculate the largest bounding box that fits within remaining canvas space
    if (available_w / available_h) > target_ratio:
        crop_h = available_h
        crop_w = int(round(crop_h * target_ratio))
    else:
        crop_w = available_w
        crop_h = int(round(crop_w / target_ratio))

    # Force dimensions to even numbers for strict H.264 / macroblock codec compliance
    crop_w = crop_w & ~1
    crop_h = crop_h & ~1

    # Ensure dimensions never drop below minimum required pixels
    crop_w = max(2, crop_w)
    crop_h = max(2, crop_h)

    return crop_x, crop_y, crop_w, crop_h

def main():
    args = parse_arguments()
    
    if not os.path.exists(args.InputFile):
        print(f"❌ Error: Input file '{args.InputFile}' not found.")
        exit(2)

    # Fetch video dimensions
    cap = cv2.VideoCapture(args.InputFile)
    native_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    native_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()

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

    crop_x, crop_y, crop_w, crop_h = calculate_max_crop_from_origin(args, native_w, native_h)
    
    print(" CALCULATED CROP GEOMETRY")
    print("-" * 50)
    print(f"  Calculated Crop X: {crop_x} (Unchanged)")
    print(f"  Calculated Crop Y: {crop_y} (Unchanged)")
    print(f"  Calculated Crop W: {crop_w}")
    print(f"  Calculated Crop H: {crop_h}")
    print("=" * 50)
    
    base_name = os.path.splitext(os.path.basename(args.InputFile))[0]
    final_output = f"{base_name}_ZOOM_FINAL.mkv"

    # FFMPEG crop execution
    cmd = [
        "ffmpeg", "-y", "-i", args.InputFile,
        "-vf", f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k", "-pix_fmt", "yuv420p",
        final_output
    ]
    
    print(f"Rendering frame slice starting at ({crop_x}, {crop_y}): {final_output}\n")
    subprocess.run(cmd)

if __name__ == "__main__":
    main()