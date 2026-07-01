#!/usr/bin/env python3
import os
import json
import argparse
import random
import numpy as np
from datetime import datetime
from manim import *

def parse_parameters():
    parser = argparse.ArgumentParser(description="Orthogonal Command Line Engine")
    
    # Structural Input Configuration Options
    parser.add_argument("--theme", type=str, help="The mname of the Theme color scheme")
    parser.add_argument("--shapes", type=str, help="Name of the shape group")
    parser.add_argument("--animstyle", type=str, help="one of the animation algorithms")
    parser.add_argument("--diststyle", type=str, default="StarField", help="One of the distribution layouts")
    parser.add_argument("--sizestyle", type=str, default="Sequential", help="One of the scaling sizing structures")
    parser.add_argument("--count", type=int, default=11, help="Explicit total number of structural shapes to generate")
    parser.add_argument("--length", type=float, default=10.0, help="Length of the mp4 in seconds")
    parser.add_argument("--opacity", type=float, default=100.0, help="the percent of opacity for each shape, 100 is solid, 0 and invisible.")
    parser.add_argument("--theme_json", type=str, default="./themes/theme.json", help="The theme json file (default is ./themes/theme.json)")
    
    return parser.parse_args()

# ==========================================
# SHAPE & MOTION FACTORIES
# ==========================================

def shape_factory(name, color, size=2.0, opacity=1.0):
    """Maps custom string identifiers to concrete Manim geometry objects."""
    name = name.lower().strip()
    # Define the 3D rendering configuration dictionary here
    config_3d = {
        "fill_color": color,
        "fill_opacity": opacity,
    }
    # Generic mappings supporting complex group schemas
    if "circle" in name:
        return Circle(radius=size/2, color=color, fill_color=color, fill_opacity=opacity).scale_to_fit_width(size)
    elif "square" in name:
        return Square(side_length=size, color=color, fill_color=color, fill_opacity=opacity).scale_to_fit_width(size)
    elif "triangle" in name:
        return Triangle(color=color, fill_color=color, fill_opacity=opacity).scale_to_fit_width(size)
    elif "pentagon" in name:
        return RegularPolygon(n=5, radius=size/2, color=color, fill_color=color, fill_opacity=opacity).scale_to_fit_width(size)
    elif "hexagon" in name:
        return RegularPolygon(n=6, radius=size/2, color=color, fill_color=color, fill_opacity=opacity).scale_to_fit_width(size)
    elif "octagon" in name:
        return RegularPolygon(n=8, radius=size/2, color=color, fill_color=color, fill_opacity=opacity).scale_to_fit_width(size)
    elif "star3" in name:
        return Star(n=3, outer_radius=size/2, inner_radius=size/4, color=color, fill_color=color, fill_opacity=opacity).scale_to_fit_width(size)
    elif "star4" in name:
        return Star(n=4, outer_radius=size/2, inner_radius=size/4, color=color, fill_color=color, fill_opacity=opacity).scale_to_fit_width(size)
    elif "star5" in name:
        return Star(n=5, outer_radius=size/2, inner_radius=size/4, color=color, fill_color=color, fill_opacity=opacity).scale_to_fit_width(size)
    elif "star6" in name:
        return Star(n=6, outer_radius=size/2, inner_radius=size/4, color=color, fill_color=color, fill_opacity=opacity).scale_to_fit_width(size)
    elif "star7" in name:
        return Star(n=7, outer_radius=size/2, inner_radius=size/4, color=color, fill_color=color, fill_opacity=opacity).scale_to_fit_width(size)
    elif "star8" in name:
        return Star(n=8, outer_radius=size/2, inner_radius=size/4, color=color, fill_color=color, fill_opacity=opacity).scale_to_fit_width(size)
    elif "sphere" in name:
        return Sphere(radius=size/2, **config_3d)
    elif "cube" in name:
        return Cube(side_length=size, **config_3d)
    elif "cone" in name:
        return Cone(base_radius=size/2, height=size, **config_3d)
    elif "prism" in name:
        # Using Prism as a generic variant
        return Prism(dimensions=[size, size, size*0.5], **config_3d)
    elif "cylinder" in name:
        return Cylinder(radius=size/2, height=size, **config_3d)
    else:
        print(f"ERROR in theme_json file: shape doesn't exist: {name}")
        exit(1)

def apply_distribution(style, the_shape, index, config_params):
    """Maps custom structural layout positioning formulas to Manim spatial grids."""
    style = style.lower().strip()
    
    if style == "golden":
        munit = config_params.get("Munit", 1.0)
        # Golden Angle formula implementation: 137.5 degrees in Radians
        golden_angle = 137.5 * np.pi / 180



        # 1. Pull the new positioning values from your JSON
        # distance_scale pushes everything outward. Increase this to separate the shapes!
        distance_scale = config_params.get("distance_scale", 1.0)
        # growth_factor changes how tightly or loosely wound the spiral is (0.5 is standard sqrt)
        growth_factor = config_params.get("growth_factor", 0.5)
        
        # 2. Compute the spiral radius using the custom growth factor
        radius = distance_scale * (index ** growth_factor)
        angle = index * golden_angle
        

        # 3. Project coordinates out into Manim space
        translateX = radius * np.cos(angle) * munit
        translateY = radius * np.sin(angle) * munit


        the_shape.move_to(np.array([translateX, translateY, 0]))
        
    elif style == "starfield":
        # Random distribution within safe visual boundaries of Manim's screen canvas limits
        munit = config_params.get("Munit", 1.0)
        half_width = config.frame_width / 2
        half_height = config.frame_height / 2

        translateX = random.uniform(-half_width, half_width)
        translateY = random.uniform(-half_height, half_height)

        the_shape.move_to(np.array([translateX, translateY, 0]))
    else:
        print(f"ERROR in apply_distribution(): style does not exist: {style}")
        exit(12)


def apply_motion_logic(style, mobjects, progress, total_frames, config_params):
    """Calculates loopable frame modifications per structural layout."""
    style = style.lower().strip()
    angle_cycle = progress * TAU
    
    if style == "pulse":
        # Smooth scaling oscillation using a cosine wave profile
        scale_val = 1.0 + 0.25 * (0.5 + 0.5 * np.cos(angle_cycle))
        for idx, the_shape in enumerate(mobjects):
            base_size = 1.2 + (idx * 0.8)
            the_shape.scale_to_fit_width(base_size * scale_val)
            
    elif style == "disco":
        # Dynamic rotational offsetting layered across dimensions
        for idx, the_shape in enumerate(mobjects):
            layer_dir = 1 if idx % 2 == 0 else -1
            the_shape.rotate(layer_dir * (TAU / total_frames) * (idx + 1))
            
    elif style == "glitch":
        # Controlled parametric positional jittering that safely terminates cleanly at 0.0/1.0
        jitter_amp = 0.15 * np.sin(angle_cycle * 4)
        for the_shape in mobjects:
            the_shape.shift(np.array([jitter_amp, -jitter_amp, 0]))

    elif style == "orbiting":
        speed = config_params.get("Speed", 1.0)
        for idx, the_shape in enumerate(mobjects):
            phase_shift = idx * (TAU / len(mobjects))
            radius = 2.0 + (idx * 0.5)
            # Standard structural circular orbital positioning
            x = radius * np.cos(angle_cycle * speed + phase_shift)
            y = radius * np.sin(angle_cycle * speed + phase_shift)
            the_shape.move_to(np.array([x, y, 0]))
            the_shape.rotate(TAU / total_frames)

    elif style == "spin":
        direction = config_params.get("Direction", 1)
        for idx, the_shape in enumerate(mobjects):
            # Alternates direction between consecutive shape layers
            layer_dir = direction if idx % 2 == 0 else -direction
            the_shape.rotate(layer_dir * (TAU / total_frames) * (idx + 1))
    else:
        print(f"apply_motion_logic failed with unknown AnimationStyle")
        exit(3)

def apply_size_styles(step, style, config_params):
    """Calculates layout scaling properties across mathematical generation profiles."""
    style = style.lower().strip()
    one_pixel_manimal = config.frame_width / config.pixel_width
    if style == "random":
        seed_value = config_params.get("seed", 1)
        rng = random.Random(seed_value)
        pixel_size = rng.randint(1, 50)
        return pixel_size * one_pixel_manimal


    elif style == "sequential":
        starting_pixels = config_params.get("starting_value", 1)
        
        # Grow linearly by adding the current loop step directly to the starting pixels
        pixel_size = starting_pixels * step
        return pixel_size * one_pixel_manimal
        
       
    elif style == "exponential":
        exponent = config_params.get("exponent", 3)
        
        # Grow exponentially: loop step raised to the power of your JSON exponent
        pixel_size = step ** exponent
        return pixel_size * one_pixel_manimal

    print(f"apply_size_styles failed with unknown SizeStyle")
    exit(3)


def fibonacci(n):
    if n < 0:
        print(f"Input must be a non-negative integer.")
        exit(5)
    if n == 0:
        return 0
    if n == 1:
        return 1
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b


# ==========================================
# THE DECOUPLED RENDER PIPELINE FUNCTION
# ==========================================

class ScriptClipContainer(Scene):
    """Minimal runtime wrapper required by Manim to hook the context pipeline."""
    def construct(self):
        pass

def generate_clip(script_parms, theme_json_data, script_clip_container):
    """Executes the video compilation sequentially without custom object overhead."""
    fps = theme_json_data["RenderSettings"]["FPS"]
    duration = script_parms.length
    total_frames = int(fps * duration)
    
    # 1. Extract Palette Layers from Registry (No hardcoded fallback strings)
    theme_data = theme_json_data["Themes"][script_parms.theme]
    bg_color = random.choice(theme_data["Background"])
    script_clip_container.camera.background_color = bg_color
    shape_colors = theme_data["Shapes"]
    
    # 2. Extract Structural Manifest Arrays
    group_data = theme_json_data["ShapeGroups"][script_parms.shapes]
    shape_strings = group_data["Shapes"]
    
    # 3. Build Spatial Grid Pipeline
    shapes_group = VGroup()
    total_shapes = script_parms.count

    # Extract sizing configurations from the registry profile
    size_style = script_parms.sizestyle
    size_params = theme_json_data.get("SizeStyles", {}).get(size_style, {})

    distribution_style = script_parms.diststyle
    distribution_params = theme_json_data.get("DistributionStyles", {}).get(distribution_style, {})

    # Calculate opacity float multiplier (e.g. 15.0 -> 0.15, 100.0 -> 1.0) bound safely between 0.0 and 1.0
    target_opacity = max(0.0, min(1.0, script_parms.opacity / 100.0))


    for i in range(total_shapes):
        shape_name = shape_strings[i % len(shape_strings)]
        assigned_color = shape_colors[i % len(shape_colors)]

        # Implement SizeStyles via unified factory dispatcher hook
        theme_size = apply_size_styles(step=i, style=size_style, config_params=size_params)
        
        # Generated the shape
        the_shape = shape_factory(shape_name, assigned_color, size=theme_size, opacity=target_opacity)

        # Apply the spatial placement layout engine calculations
        apply_distribution(script_parms.diststyle, the_shape, index=i, config_params=distribution_params)

        shapes_group.add(the_shape)
        

    script_clip_container.add(shapes_group)
    
    # 4. Attach Dynamic Motion Callbacks
    motion_style = script_parms.animstyle
    motion_params = theme_json_data["AnimationStyles"].get(motion_style, {})

    def runtime_loop_updater(mobjects, dt):
        current_frame = int(script_clip_container.renderer.time * fps)
        progress = (current_frame % total_frames) / total_frames
        apply_motion_logic(motion_style, mobjects, progress, total_frames, motion_params)

    shapes_group.add_updater(runtime_loop_updater)
    script_clip_container.wait(duration)
    shapes_group.remove_updater(runtime_loop_updater)

    #TODO: if error condition, print message and exit

# ==========================================
# RUNTIME INTERFACE ENTRYPOINT
# ==========================================

if __name__ == "__main__":

    parms = parse_parameters()

    # Load profile data from companion asset manifest file
    if os.path.exists(parms.theme_json):
        with open(parms.theme_json, "r") as f:
            theme_json_data = json.load(f)
    else:
        print(f"theme_json file missing")
        exit(1)

    render_settings = theme_json_data["RenderSettings"]
    random.seed(render_settings.get("RandomSeed", 42))
    np.random.seed(render_settings.get("RandomSeed", 42))
    
    # Push dimensions over to the internal Manim environment configurations
    config.pixel_width = render_settings["Width"]
    config.pixel_height = render_settings["Height"]
    config.frame_rate = render_settings["FPS"]
    
    # Form output file naming target based directly on parameter execution details
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    count_suffix = f"_c{parms.count}" if parms.count is not None else ""
    trans_suffix = f"_op{int(parms.opacity)}"
    config.output_file = os.path.abspath(f"./{parms.theme}_{parms.shapes}_{parms.animstyle}_{parms.diststyle}_{parms.sizestyle}{count_suffix}{trans_suffix}_{timestamp}.mp4")
    config.write_to_movie = True
    
    # Initialize the engine context container and pass it directly to our runner function
    scene = ScriptClipContainer()
    
    # Intercept construction pipeline using our simple functional loop execution layout
    scene.construct = lambda: generate_clip(script_parms=parms, theme_json_data=theme_json_data, script_clip_container=scene)
    scene.render()