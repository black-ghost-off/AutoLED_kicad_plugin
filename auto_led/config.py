"""Default settings, LED presets and config persistence."""

import copy
import json
import os

# Pin maps are symbol pin number == footprint pad number, taken from the
# KiCad standard LED symbol library for the matching footprint.
PRESETS = {
    "WS2812B (5050)": {
        "kind": "addressable",
        "value": "WS2812B",
        "footprint": "LED_SMD:LED_WS2812B_PLCC4_5.0x5.0mm_P3.2mm",
        "pins": {"VDD": "1", "DOUT": "2", "GND": "3", "DIN": "4"},
        "body": (5.0, 5.0),
        "cap_offset": (0.0, 4.2),
    },
    "WS2812B-2020 (2020)": {
        "kind": "addressable",
        "value": "WS2812B-2020",
        "footprint": "LED_SMD:LED_WS2812B-2020_PLCC4_2.0x2.0mm",
        "pins": {"DOUT": "1", "GND": "2", "DIN": "3", "VDD": "4"},
        "body": (2.0, 2.0),
        "cap_offset": (0.0, 2.0),
    },
    "SK6812MINI (3535)": {
        "kind": "addressable",
        "value": "SK6812MINI",
        "footprint": "LED_SMD:LED_SK6812MINI_PLCC4_3.5x3.5mm_P1.75mm",
        "pins": {"DOUT": "1", "GND": "2", "DIN": "3", "VDD": "4"},
        "body": (3.5, 3.5),
        "cap_offset": (0.0, 3.0),
    },
    "LED 0805": {
        "kind": "simple",
        "value": "LED_0805",
        "footprint": "LED_SMD:LED_0805_2012Metric",
        "pins": {"K": "1", "A": "2"},
        "body": (2.0, 1.25),
    },
    "LED 0603": {
        "kind": "simple",
        "value": "LED_0603",
        "footprint": "LED_SMD:LED_0603_1608Metric",
        "pins": {"K": "1", "A": "2"},
        "body": (1.6, 0.8),
    },
    "LED 1206": {
        "kind": "simple",
        "value": "LED_1206",
        "footprint": "LED_SMD:LED_1206_3216Metric",
        "pins": {"K": "1", "A": "2"},
        "body": (3.2, 1.6),
    },
}

SAMPLE_MODES = [
    ("center", "Grid: LED centre inside shape"),
    ("coverage", "Grid: cell coverage %"),
    ("pixel", "Pixel: 1 image pixel = 1 LED"),
]

ORDERS = [
    ("rows", "Along rows"),
    ("cols", "Along columns"),
]

START_CORNERS = [
    ("top-left", "Top-left"),
    ("top-right", "Top-right"),
    ("bottom-left", "Bottom-left"),
    ("bottom-right", "Bottom-right"),
]

SIDES = [("front", "Front (F.Cu)"), ("back", "Back (B.Cu)")]

SCH_TARGETS = [
    ("project", "Project schematic (if empty / AutoLED)"),
    ("separate", "Separate file <base>.kicad_sch"),
]

CONN_PLACEMENTS = [("auto", "Auto: beside first / last LED"), ("manual", "Manual X / Y")]

CONN_SIDES = [("same", "Same side as LEDs"), ("opposite", "Opposite side")]

OUTLINES = [
    ("none", "None"),
    ("rect", "Rectangle around parts"),
    ("shape", "Image shape + parts"),
    ("shape_only", "Image shape only"),
]

OUTLINE_LAYERS = [
    ("Edge.Cuts", "Edge.Cuts (board cut)"),
    ("User.1", "User.1"),
    ("User.2", "User.2"),
    ("Dwgs.User", "Dwgs.User"),
    ("Cmts.User", "Cmts.User"),
]

SCALE_MODES = [
    ("width", "Width in mm"),
    ("height", "Height in mm"),
    ("percent", "Percent of native size"),
    ("dpi", "Image DPI"),
]

DEFAULTS = {
    # image -> black & white
    "image_path": "",
    "threshold": 128,
    "invert": False,
    "use_alpha": False,
    "work_res": 600,
    # geometry
    "sample_mode": "center",
    "scale_mode": "width",
    "width_mm": 100.0,
    "height_mm": 60.0,
    "scale_pct": 100.0,
    "dpi": 96.0,
    "pitch_x": 10.0,
    "pitch_y": 10.0,
    "border_mm": 1.0,
    "fit_body": True,
    "coverage": 50,
    "grid_dx": 0.0,
    "grid_dy": 0.0,
    # LED
    "preset": "WS2812B (5050)",
    "footprint": "",
    "rotation": 0.0,
    "side": "front",
    "ref_prefix": "D",
    "decoupling": True,
    "cap_value": "100nF",
    "cap_footprint": "Capacitor_SMD:C_0402_1005Metric",
    "cap_rotation": 90.0,         # relative to the LED base rotation
    "cap_custom_offset": False,   # False: use the LED preset's cap position
    "cap_dx": 0.0,                # cap centre relative to LED centre (unrotated LED), mm
    "cap_dy": 4.2,
    "connectors": True,
    "conn_in": True,              # J1: power + data in
    "conn_out": True,             # J2: power + data out (chain boards)
    # {n} = pin count, e.g. "Connector_JST:JST_PH_B{n}B-PH-K_1x{n:02d}_P2.00mm_Vertical"
    "conn_footprint": "Connector_PinHeader_2.54mm:PinHeader_1x{n:02d}_P2.54mm_Vertical",
    "conn_pinout": "+5V,DATA,GND",  # pin 1..n; DATA = DIN on J1 / DOUT on J2, NC = unused
    "conn_placement": "auto",     # auto: beside first / last LED; manual: X/Y below
    "conn_gap": 2.54,             # auto: gap between the outermost LED and the connector, mm
    "conn_in_x": 90.0,
    "conn_in_y": 100.0,
    "conn_out_x": 210.0,
    "conn_out_y": 100.0,
    "conn_rotation": 0.0,
    "conn_side": "same",          # same side as the LEDs, or "opposite"
    "conn_max_pins": 40,          # matrix mode: split row / column connectors
    # chain / numbering
    "order": "rows",
    "zigzag": True,
    "zigzag_rotate": False,
    "start_corner": "top-left",
    # output
    "origin_x": 100.0,
    "origin_y": 100.0,
    "out_dir": "",
    "base_name": "leds",
    "c_prefix": "led",
    "export_json": True,
    "export_txt": True,
    "export_h": True,
    "gen_sch": True,
    "sch_target": "project",      # write into <project>.kicad_sch when it is empty or ours
    "place_pcb": True,
    "clear_prev": True,
    "outline": "none",
    "outline_margin": 2.0,
    "outline_layer": "Edge.Cuts",
    "export_cut": False,
    "footprint_dir": "",
    # autorouting with Freerouting
    "route": False,
    "gnd_plane": True,
    "route_passes": 20,
    "route_timeout": 600,
    "freerouting_jar": "",
    "java_path": "",
}


def choice_values(choices):
    return [v for v, _ in choices]


def preset_for(cfg):
    p = copy.deepcopy(PRESETS.get(cfg["preset"], PRESETS[DEFAULTS["preset"]]))
    if cfg.get("footprint", "").strip():
        p["footprint"] = cfg["footprint"].strip()
    return p


def normalized(cfg):
    """Return DEFAULTS overlaid with known keys of cfg, coerced to default types."""
    out = copy.deepcopy(DEFAULTS)
    cfg = _migrate(cfg)
    for k, default in DEFAULTS.items():
        if k not in cfg:
            continue
        v = cfg[k]
        try:
            if isinstance(default, bool):
                v = bool(v)
            elif isinstance(default, int):
                v = int(v)
            elif isinstance(default, float):
                v = float(v)
            else:
                v = str(v)
        except (TypeError, ValueError):
            continue
        out[k] = v
    return out


def _migrate(cfg):
    # older configs encoded zigzag in the order name ("rows_serpentine")
    order = str(cfg.get("order", ""))
    if order.endswith("_serpentine"):
        cfg = dict(cfg, order=order[:-len("_serpentine")])
        cfg.setdefault("zigzag", True)
    return cfg


def load(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return normalized(_migrate(json.load(f)))
    except (OSError, ValueError):
        return copy.deepcopy(DEFAULTS)


def save(path, cfg):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(normalized(cfg), f, indent=2)
    except OSError:
        pass


def config_path_for_board(board_path):
    if board_path:
        return os.path.splitext(board_path)[0] + ".autoled.json"
    return os.path.join(os.path.expanduser("~"), ".kicad_autoled.json")
