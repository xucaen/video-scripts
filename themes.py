# ==========================================
# themes.py
# External Theme Registry Module
# ==========================================
import math
import random

def _hex_to_bgr(hex_str):
    """Internal helper to safely convert hex strings over to OpenCV BGR tuples."""
    hex_str = hex_str.lstrip('#')
    rgb = tuple(int(hex_str[i:i+2], 16) for i in (0, 2, 4))
    return (rgb[2], rgb[1], rgb[0])  # Inverted into Blue, Green, Red order

def golden_ratio_layout(ctx):
    golden_angle = math.radians(137.5)
    radius = ctx["spread"] * math.sqrt(ctx["index"])
    angle = ctx["index"] * golden_angle + ctx["time_elapsed"] * 0.4
    return ctx["center_x"] + radius * math.cos(angle), ctx["center_y"] + radius * math.sin(angle)

def starfield_layout(ctx):
    random.seed(ctx["index"] + 500)
    base_x = random.randint(0, ctx["width"])
    base_y = random.randint(0, ctx["height"])
    x = (base_x + ctx["time_elapsed"] * 40) % ctx["width"]
    y = (base_y + ctx["time_elapsed"] * 20) % ctx["height"]
    return x, y

def orbital_layout(ctx):
    ring = (ctx["index"] % 3) + 1
    radius = ring * 100
    speed = (3.0 / ring) * (1.0 if ctx["index"] % 2 == 0 else -1.0)
    angle = ctx["time_elapsed"] * speed + (ctx["index"] * (2 * math.pi / 4))
    return ctx["center_x"] + radius * math.cos(angle), ctx["center_y"] + radius * math.sin(angle)

ALGORITHMS = {
    "golden": golden_ratio_layout,
    "starfield": starfield_layout,
    "orbit": orbital_layout
}

THEMES = {
    "VelvetOrchard": {
        "name": "Velvet Orchard",
        "header_font": "Britannic-Bold",
        "body_font": "Calibri-Bold-Italic",
        "backgrounds": [_hex_to_bgr(x) for x in ["#FFFFFF", "#F8F9FA", "#FFF8E1", "#E3F2FD", "#E8F5E9"]],
        "text": _hex_to_bgr("#000000"),
        "headers": [_hex_to_bgr(x) for x in ["#2E1A47", "#003366", "#004D40", "#4E342E", "#311B92", "#880E4F", "#1B5E20", "#BF360C"]],
        "shapes": [_hex_to_bgr(x) for x in ["#ff89ff", "#b2b9ff", "#a6daff", "#dbafff", "#ffccbc", "#ffab91", "#FFE0B2", "#F48FB1"]],
        "algorithms": ["golden", "orbit"]
    },
    "CherrySorbet": {
        "name": "Cherry Sorbet",
        "header_font": "Edwardian-Script-ITC",
        "body_font": "Century-Gothic",
        "backgrounds": [_hex_to_bgr(x) for x in ["#1A090D", "#2D0A12", "#121212", "#3E101A", "#1B1212"]],
        "text": _hex_to_bgr("#ffffff"),
        "headers": [_hex_to_bgr(x) for x in ["#FFB703", "#00F5D4", "#E0E1DD", "#F72585", "#4CC9F0"]],
        "shapes": [_hex_to_bgr(x) for x in ["#FF4D6D", "#FF758F", "#C9184A", "#FFB3C1", "#800F2F", "#A4133C"]],
        "algorithms": ["golden", "starfield"]
    },
    "CosmicJungle": {
        "name": "Cosmic Jungle",
        "header_font": "Chiller",
        "body_font": "Constantia",
        "backgrounds": [_hex_to_bgr(x) for x in ["#0A0915", "#060E14", "#050F0A", "#110D1A"]],
        "text": _hex_to_bgr("#ffffff"),
        "headers": [_hex_to_bgr(x) for x in ["#FFEAFE", "#E6FFFF", "#F0FFF0", "#FF007F", "#FFFF00", "#FF9900", "#00FFCC"]],
        "shapes": [_hex_to_bgr(x) for x in ["#66FF00", "#00FF66", "#00E5FF", "#0066FF", "#3300FF", "#9900FF"]],
        "algorithms": ["starfield", "orbit"]
    },
    "CyberPastel": {
        "name": "Cyber Pastel",
        "header_font": "Cooper-Black",
        "body_font": "Cascadia-Mono-Regular",
        "backgrounds": [_hex_to_bgr("#F8F9FA")],
        "text": _hex_to_bgr("#000000"),
        "headers": [_hex_to_bgr(x) for x in ["#311B92", "#2E1A47"]],
        "shapes": [_hex_to_bgr(x) for x in ["#ff89ff", "#b2b9ff", "#a6daff", "#dbafff"]],
        "algorithms": ["golden"]
    },
    "OceanBreeze": {
        "name": "Ocean Breeze",
        "header_font": "Edwardian-Script-ITC",
        "body_font": "Century-Gothic",
        "backgrounds": [_hex_to_bgr("#E3F2FD")],
        "text": _hex_to_bgr("#000000"),
        "headers": [_hex_to_bgr(x) for x in ["#003366", "#37474F"]],
        "shapes": [_hex_to_bgr(x) for x in ["#90caf9", "#80DEEA", "#a7ffeb", "#C5CAE9"]],
        "algorithms": ["orbit"]
    },
    "CorporateTech": {
        "name": "Corporate Tech",
        "header_font": "Agency-FB-Bold",
        "body_font": "Segoe-UI",
        "backgrounds": [_hex_to_bgr("#F8F9FA")],
        "text": _hex_to_bgr("#000000"),
        "headers": [_hex_to_bgr(x) for x in ["#003366", "#37474F"]],
        "shapes": [_hex_to_bgr(x) for x in ["#90caf9", "#a6daff", "#b2b9ff", "#C5CAE9"]],
        "algorithms": ["starfield"]
    },
    "TuscanHarvest": {
        "name": "Tuscan Harvest",
        "header_font": "Baskerville-Old-Face",
        "body_font": "Calibri",
        "backgrounds": [_hex_to_bgr("#FFF8E1")],
        "text": _hex_to_bgr("#000000"),
        "headers": [_hex_to_bgr(x) for x in ["#BF360C", "#4E342E"]],
        "shapes": [_hex_to_bgr(x) for x in ["#ffccbc", "#ffab91", "#FFE0B2", "#f0f4c3"]],
        "algorithms": ["golden", "orbit"]
    },
    "BotanicalGarden": {
        "name": "Botanical Garden",
        "header_font": "Centaur",
        "body_font": "Corbel",
        "backgrounds": [_hex_to_bgr("#E8F5E9")],
        "text": _hex_to_bgr("#000000"),
        "headers": [_hex_to_bgr(x) for x in ["#1B5E20", "#004D40"]],
        "shapes": [_hex_to_bgr(x) for x in ["#C8E6C9", "#a7ffeb", "#f0f4c3", "#ce93d8"]],
        "algorithms": ["golden"]
    },
    "VelvetRose": {
        "name": "Velvet Rose",
        "header_font": "Bodoni-MT-Bold",
        "body_font": "Century-Gothic",
        "backgrounds": [_hex_to_bgr("#FFFFFF")],
        "text": _hex_to_bgr("#000000"),
        "headers": [_hex_to_bgr(x) for x in ["#880E4F", "#212121"]],
        "shapes": [_hex_to_bgr(x) for x in ["#F48FB1", "#F8BBD0", "#ff89ff", "#dbafff"]],
        "algorithms": ["orbit"]
    },
    "RetroEditorial": {
        "name": "Retro Editorial",
        "header_font": "Cooper-Black",
        "body_font": "Trebuchet-MS",
        "backgrounds": [_hex_to_bgr("#FFF8E1")],
        "text": _hex_to_bgr("#000000"),
        "headers": [_hex_to_bgr(x) for x in ["#4E342E", "#BF360C"]],
        "shapes": [_hex_to_bgr(x) for x in ["#ffab91", "#FFE0B2", "#ffccbc", "#F48FB1"]],
        "algorithms": ["golden"]
    },
    "ElectricIndigo": {
        "name": "Electric Indigo",
        "header_font": "Britannic-Bold",
        "body_font": "Calibri-Bold-Italic",
        "backgrounds": [_hex_to_bgr(x) for x in ["#080D26", "#0A1128", "#001F3F", "#0B132B", "#1C2541"]],
        "text": _hex_to_bgr("#E0FBFC"),
        "headers": [_hex_to_bgr(x) for x in ["#00F5D4", "#9B5DE5", "#00BBF9", "#F15BB5", "#A2D2FF", "#BDB2FF"]],
        "shapes": [_hex_to_bgr(x) for x in ["#3F37C9", "#4361EE", "#4895EF", "#4CC9F0", "#7209B7", "#560BAD"]],
        "algorithms": ["golden", "starfield", "orbit"]
    }
}