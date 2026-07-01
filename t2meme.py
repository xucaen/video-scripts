import cv2
import numpy as np
import math
import random
import argparse

import importlib.util

# Directly load the python file from an absolute path string, anywhere!
spec = importlib.util.spec_from_file_location("themes", r"C:\PROJECTS\POWERSHELL\VIDEO SCRIPTS\themes.py")
themes_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(themes_module)

# Now grab your data variable

def process_parms():
    # Setup full interface argument parser handling flags straight from terminal
    parser = argparse.ArgumentParser(description="Procedural Video Engine")
    parser.add_argument("--theme", type=str, default="C:\\PROJECTS\POWERSHELL\\VIDEO SCRIPTS\\themes.py", help="location of the theme script")
    parser.add_argument("--duration", type=int, default=10, help="Target run length in total seconds")
    parser.add_argument("--output", type=str, default="output.mp4", help="Filename of compiled asset file output")
    
    return parser.parse_args()


# ==========================================
# PROCEDURAL MATHEMATHICAL SHAPE TEMPLATES
# ==========================================
def draw_star(frame, cx, cy, color, size, points=5, inner_ratio=0.4, rotation=0):
    pts = []
    r_outer = size / 2
    r_inner = r_outer * inner_ratio
    for i in range(points * 2):
        angle = math.radians(rotation) + i * (math.pi / points)
        r = r_outer if i % 2 == 0 else r_inner
        pts.append([cx + r * math.cos(angle), cy + r * math.sin(angle)])
    cv2.drawContours(frame, [np.array(pts, np.int32)], 0, color, -1, lineType=cv2.LINE_AA)

def draw_regular_polygon(frame, cx, cy, color, size, sides=6, rotation=0):
    pts = []
    radius = size / 2
    for i in range(sides):
        angle = math.radians(rotation) + i * (2 * math.pi / sides)
        pts.append([cx + radius * math.cos(angle), cy + radius * math.sin(angle)])
    cv2.drawContours(frame, [np.array(pts, np.int32)], 0, color, -1, lineType=cv2.LINE_AA)

def draw_circle(frame, cx, cy, color, size, **kwargs):
    cv2.circle(frame, (int(cx), int(cy)), int(size / 2), color, -1, lineType=cv2.LINE_AA)

# ==========================================
# MASTER GENERATOR PIPELINE
# ==========================================
def generate_themed_content(output_name, theme_name, duration, width=1280, height=720, fps=30):
    # Retrieve configuration metrics natively out from the external module array
    if theme_name not in THEMES:
        print(f"Error: Theme '{theme_name}' not found in themes.py registry. Defaulting to ElectricIndigo.")
        theme_name = "ElectricIndigo"
        
    theme = THEMES[theme_name]
    
    # Intelligently resolve which layout algorithm to execute based on theme metadata flags
    algo_key = random.choice(theme["algorithms"])
    algorithm = ALGORITHMS[algo_key]
    
    writer = cv2.VideoWriter(output_name, cv2.VideoWriter_fourcc(*'mp4v'), fps, (width, height))
    total_frames = int(duration * fps)
    dt = 1.0 / fps
    
    bg_color = random.choice(theme["backgrounds"])
    num_elements = random.randint(15, 30)
    
    # Initialize structural arrays
    elements = []
    for i in range(num_elements):
        elements.append({
            "template": random.choice(SHAPE_TEMPLATES),
            "color": random.choice(theme["shapes"]),
            "size": random.randint(35, 95),
            "rot_speed": random.uniform(-45, 45),
            "rotation": random.uniform(0, 360)
        })
        
    print(f"Compiling Engine: '{theme['name']}' using '{algo_key}' layout module...")

    for frame_idx in range(total_frames):
        time_elapsed = frame_idx * dt
        frame = np.full((height, width, 3), bg_color, dtype=np.uint8)
        
        ctx = {
            "time_elapsed": time_elapsed,
            "width": width,
            "height": height,
            "center_x": width // 2,
            "center_y": height // 2,
            "spread": 50.0
        }
        
        for i, elem in enumerate(elements):
            ctx["index"] = i
            x, y = algorithm(ctx)
            
            elem["rotation"] += elem["rot_speed"] * dt
            template = elem["template"]
            
            kwargs = {
                "frame": frame, "cx": x, "cy": y,
                "color": elem["color"], "size": elem["size"],
                "rotation": elem["rotation"], **template["args"]
            }
            template["func"](**kwargs)
            
        writer.write(frame)
        
    writer.release()
    print(f"File closed. Successfully exported to: {output_name}")


##### MAIN()
if __name__ == "__main__":

    args = process_parms()
    generate_themed_content(
        output_name=args.output,
        theme_name=args.theme,
        duration=args.duration
    )

#endif