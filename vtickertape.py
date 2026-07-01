#!/usr/bin/env python3
import os
import sys
import argparse
import subprocess
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

def parse_parameters():
    parser = argparse.ArgumentParser(description="Zero-Overhead Pure FFmpeg Ticker Engine.")
    parser.add_argument("--width", type=int, default=1920, help="Video width")
    parser.add_argument("--height", type=int, default=1080, help="Video height")
    parser.add_argument("--fps", type=int, default=60, help="Frames per second")
    parser.add_argument("--duration", type=int, default=60, help="Video duration in seconds")
    parser.add_argument("--speed", type=int, default=220, help="Scroll speed in pixels per second")
    parser.add_argument("--ticker_file", type=str, required=True, help="Path to text file containing ticker content")
    parser.add_argument("--logo_image", type=str, required=True, help="Path to PNG logo")
    return parser.parse_args()

def get_text_size(text, font):
    if hasattr(font, "getbbox"):
        bbox = font.getbbox(text)
        return (bbox[2] - bbox[0], bbox[3] - bbox[1], bbox[1])
    return len(text) * 20, 40, 0

def main():
    args = parse_parameters()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_filename = f"ticker_{timestamp}.mp4"

    if not os.path.exists(args.ticker_file) or not os.path.exists(args.logo_image):
        print("[-] Error: Missing asset files.")
        sys.exit(1)
        
    with open(args.ticker_file, 'r', encoding='utf-8') as f:
        ticker_text = f.read().replace('\n', ' ').strip()
    
    bar_h = 160
    logo_w, logo_h = 310, 160
    bar_top = args.height - bar_h

    # Font Setup
    font_path = r"C:\Windows\Fonts\arial.ttf"
    if not os.path.exists(font_path):
        font_path = "arial.ttf"

    target_text_h = int(bar_h * 0.60)
    optimal_font_size = 12
    font = None
    for size in range(12, 144):
        try:
            test_font = ImageFont.truetype(font_path, size)
            _, th, _ = get_text_size(ticker_text, test_font)
            if th > target_text_h:
                break
            optimal_font_size = size
            font = test_font
        except IOError:
            break

    text_w, text_h, baseline_offset = get_text_size(ticker_text, font)
    text_y = (bar_h - text_h) // 2 - baseline_offset
    loop_width = text_w + args.width

    print("[+] Phase 1: Pre-rendering long transparent text ribbon...")
    ribbon_w = loop_width + args.width
    ribbon_pil = Image.new("RGBA", (ribbon_w, bar_h), (0, 0, 0, 0))
    ribbon_draw = ImageDraw.Draw(ribbon_pil)
    
    # Draw text sequence for seamless wrapping
    ribbon_draw.text((args.width, text_y), ticker_text, fill="#FFFFFF", font=font)
    ribbon_draw.text((args.width + loop_width, text_y), ticker_text, fill="#FFFFFF", font=font)
    
    temp_ribbon_path = "temp_ribbon.png"
    ribbon_pil.save(temp_ribbon_path)

    print("[+] Phase 2: Handing process off to FFmpeg C-Engine...")
    
    # FIXED: Stripped the accidental "=" signs out of the color dimensions string formatting
    filter_complex = (
        f"color=s={args.width}x{args.height}:c=black:r={args.fps}:d={args.duration}[bg]; "
        f"color=s={args.width}x{bar_h}:c=blue[blue_bar]; "
        f"[bg][blue_bar]overlay=x=0:y={bar_top}[with_bar]; "
        f"[with_bar][0:v]overlay=x='-mod(t*{args.speed}, {loop_width})':y={bar_top}:eval=frame[with_text]; "
        f"[1:v]scale={logo_w}:{logo_h}[scaled_logo]; "
        f"[with_text][scaled_logo]overlay=x=0:y={bar_top}"
    )

    ffmpeg_cmd = [
        'ffmpeg', '-y',
        '-noautorotate',
        '-i', temp_ribbon_path,
        '-i', args.logo_image,
        '-filter_complex', filter_complex,
        '-vcodec', 'libx264', '-pix_fmt', 'yuv420p',
        '-crf', '18', '-preset', 'faster',
        '-t', str(args.duration),
        output_filename
    ]

    try:
        subprocess.run(ffmpeg_cmd, check=True)
    finally:
        if os.path.exists(temp_ribbon_path):
            os.remove(temp_ribbon_path)
            
    print(f"[+] Render Completed: {output_filename}")

if __name__ == "__main__":
    main()