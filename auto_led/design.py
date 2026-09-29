"""Netlist-level description of the LED array, shared by schematic and PCB output."""

import math
import re
import uuid

from . import grid

MAX_CONN_PINS = 40


class Component(object):
    def __init__(self, ref, kind, value, footprint, pins, xy=None, rotation=0.0, side=None):
        self.ref = ref
        self.side = side            # "front" / "back"; None = the LED side
        self.kind = kind            # "led", "cap", "conn"
        self.value = value
        self.footprint = footprint
        self.pins = pins            # [(pin_number, pin_name, net_name)]
        self.xy = xy                # board position in mm
        self.rotation = rotation
        self.uuid = str(uuid.uuid4())

    def net_of(self, number):
        for n, _, net in self.pins:
            if n == number:
                return net
        return None


class Design(object):
    def __init__(self, preset, side="front"):
        self.preset = preset
        self.side = side              # board side of the LEDs
        self.components = []
        self.overlaps = []

    @property
    def leds(self):
        return [c for c in self.components if c.kind == "led"]

    def nets(self):
        seen = []
        for comp in self.components:
            for _, _, net in comp.pins:
                if net and net not in seen:
                    seen.append(net)
        return seen


def _rotate(dx, dy, deg):
    # KiCad: positive angles are counter-clockwise on screen (y points down)
    a = math.radians(deg)
    return dx * math.cos(a) + dy * math.sin(a), -dx * math.sin(a) + dy * math.cos(a)


def footprint_body(lib_id, default=(1.0, 0.5)):
    """Approximate body size (w, h) in mm from a KiCad footprint name.

    C_0402_1005Metric -> 1.0 x 0.5, PinHeader_1x03_P2.54mm -> 2.54 x 7.62.
    """
    m = re.search(r"(\d\d)(\d\d)Metric", lib_id)
    if m:
        return int(m.group(1)) / 10.0, int(m.group(2)) / 10.0
    m = re.search(r"_1x(\d+)_P([\d.]+)mm", lib_id)
    if m:
        pitch = float(m.group(2))
        return pitch, pitch * int(m.group(1))
    return default


def component_box(comp, preset):
    """Axis-aligned approximate courtyard (x0, y0, x1, y1) of a component in board mm.

    LEDs use the preset body + 0.3 mm, chip caps body + pads (~0.45 / 0.25 mm), connectors
    the pin row (pin 1 at the footprint origin) + ~0.55 mm (PinHeader courtyard: 3.62 mm wide)."""
    if comp.kind == "led":
        w, h = preset["body"]
        w, h, anchor = w + 0.6, h + 0.6, (0.0, 0.0)
    elif comp.kind == "cap":
        w, h = footprint_body(comp.footprint)
        w, h, anchor = w + 0.9, h + 0.5, (0.0, 0.0)
    else:
        w, h = footprint_body(comp.footprint, (2.54, 2.54 * max(1, len(comp.pins))))
        anchor = (0.0, h / 2.0 - w / 2.0)
        w, h = w + 1.1, h + 1.1
    xs, ys = [], []
    for ux, uy in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)):
        rx, ry = _rotate(ux + anchor[0], uy + anchor[1], comp.rotation)
        xs.append(comp.xy[0] + rx)
        ys.append(comp.xy[1] + ry)
    return min(xs), min(ys), max(xs), max(ys)


def _boxes_hit(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def find_overlaps(components, preset, led_side="front", cell=10.0):
    """[(comp_a, comp_b)] whose approximate courtyards overlap on the same board side.

    Components with side None are on led_side."""
    boxes = [(c, component_box(c, preset)) for c in components]
    buckets = {}
    for i, (_, b) in enumerate(boxes):
        for gx in range(int(b[0] // cell), int(b[2] // cell) + 1):
            for gy in range(int(b[1] // cell), int(b[3] // cell) + 1):
                buckets.setdefault((gx, gy), []).append(i)
    pairs = set()
    for idx in buckets.values():
        for n, i in enumerate(idx):
            for j in idx[n + 1:]:
                ci, bi = boxes[i]
                cj, bj = boxes[j]
                same_side = (ci.side or led_side) == (cj.side or led_side)
                if same_side and _boxes_hit(bi, bj):
                    pairs.add((min(i, j), max(i, j)))
    return [(boxes[i][0], boxes[j][0]) for i, j in sorted(pairs)]


def _free_spot(candidate, others, preset, tries):
    """First position from tries (list of (x, y)) where candidate hits nothing in others."""
    obstacles = [component_box(o, preset) for o in others]
    for xy in tries:
        candidate.xy = xy
        box = component_box(candidate, preset)
        if not any(_boxes_hit(box, o) for o in obstacles):
            return True
    return False


def cap_offset(cfg, preset):
    """Cap centre relative to its LED (before the LED base rotation), in mm."""
    if cfg.get("cap_custom_offset"):
        return float(cfg["cap_dx"]), float(cfg["cap_dy"])
    return tuple(preset.get("cap_offset", (0.0, 0.0)))


POWER_ALIASES = {"+5V": "+5V", "5V": "+5V", "VCC": "+5V", "VDD": "+5V", "GND": "GND", "VSS": "GND"}


def conn_footprint(cfg, n):
    """Connector footprint for n pins from the {n} template."""
    tpl = cfg.get("conn_footprint") or "Connector_PinHeader_2.54mm:PinHeader_1x{n:02d}_P2.54mm_Vertical"
    try:
        return tpl.format(n=n)
    except (KeyError, IndexError, ValueError):
        raise ValueError("Bad connector footprint template %r (use {n} or {n:02d})" % tpl)


def parse_pinout(text, data_net):
    """'+5V,DATA,GND' -> [(num, name, net)]; DATA becomes data_net, NC is unconnected."""
    tokens = [t.strip().upper() for t in (text or "").replace(";", ",").split(",") if t.strip()]
    if "DATA" not in tokens:
        raise ValueError("Connector pin order must contain DATA, got %r" % text)
    pins = []
    for i, t in enumerate(tokens):
        if t == "DATA":
            pins.append((str(i + 1), data_net, data_net))
        elif t in POWER_ALIASES:
            pins.append((str(i + 1), POWER_ALIASES[t], POWER_ALIASES[t]))
        elif t == "NC":
            pins.append((str(i + 1), "NC", None))
        else:
            raise ValueError("Unknown connector pin %r (use +5V, GND, DATA or NC)" % t)
    return pins


def conn_side(cfg):
    led_side = cfg["side"]
    if cfg.get("conn_side") == "opposite":
        return "front" if led_side == "back" else "back"
    return led_side


def build(layout, cfg, preset):
    """Create components and nets for the placed LEDs.

    Addressable LEDs are daisy-chained in layout.order:
        J1(+5V, DIN, GND) -> D1 -> D2 -> ... -> DN -> J2(+5V, DOUT, GND)
    Simple LEDs are wired as a matrix: anode -> ROW<r>, cathode -> COL<c>.
    """
    d = Design(preset, cfg["side"])
    origin = (float(cfg["origin_x"]), float(cfg["origin_y"]))
    prefix = cfg["ref_prefix"] or "D"
    pins = preset["pins"]
    order = layout.order
    n = len(order)
    if n == 0:
        return d

    xs = [layout.board_xy(r, c, origin)[0] for r, c in order]
    left = min(xs)
    # auto placement: connector origin (pin 1) this far from the outermost LED centre
    conn_gap = preset["body"][0] / 2.0 + float(cfg.get("conn_gap", 2.54)) + 1.27
    manual = cfg.get("conn_placement") == "manual"
    c_rot = float(cfg.get("conn_rotation", 0.0))
    c_side = conn_side(cfg)

    if preset["kind"] == "addressable":
        for i, (r, c) in enumerate(order):
            din = "DIN" if i == 0 else "DATA%d" % i
            dout = "DOUT" if i == n - 1 else "DATA%d" % (i + 1)
            nets = {"VDD": "+5V", "GND": "GND", "DIN": din, "DOUT": dout}
            led_pins = [(pins[name], name, nets[name]) for name in ("VDD", "DOUT", "GND", "DIN")]
            d.components.append(Component("%s%d" % (prefix, i + 1), "led", preset["value"],
                                          preset["footprint"], led_pins,
                                          layout.board_xy(r, c, origin),
                                          grid.led_rotation(layout, cfg, r, c)))
        if cfg["decoupling"]:
            # Caps use only the base rotation, not the zigzag 180 deg flip: a flipped
            # cap would land in the gap of the neighbouring row and short into its cap.
            base_rot = float(cfg["rotation"])
            cdx, cdy = _rotate(*cap_offset(cfg, preset), deg=base_rot)
            cap_rot = (base_rot + float(cfg["cap_rotation"])) % 360.0
            for i, led in enumerate(d.leds):
                d.components.append(Component(
                    "C%d" % (i + 1), "cap", cfg["cap_value"], cfg["cap_footprint"],
                    [("1", "1", "+5V"), ("2", "2", "GND")],
                    (led.xy[0] + cdx, led.xy[1] + cdy), cap_rot))
        if cfg["connectors"]:
            def beside(led, n_pins):
                # next to the outer end of the LED's row, on the nearer side,
                # centred vertically on the LED (pin 1 at the footprint origin)
                row_xs = [xy[0] for xy in (l.xy for l in d.leds) if abs(xy[1] - led.xy[1]) < 1e-6]
                lo, hi = min(row_xs), max(row_xs)
                x = lo - conn_gap if led.xy[0] - lo <= hi - led.xy[0] else hi + conn_gap
                return (x, led.xy[1] - (n_pins - 1) * 2.54 / 2.0)
            specs = []
            if cfg.get("conn_in", True):
                specs.append(("LED_IN", "DIN", d.leds[0], ("conn_in_x", "conn_in_y")))
            if cfg.get("conn_out", True):
                specs.append(("LED_OUT", "DOUT", d.leds[-1], ("conn_out_x", "conn_out_y")))
            for jn, (value, net, led, keys) in enumerate(specs, 1):
                cpins = parse_pinout(cfg.get("conn_pinout"), net)
                xy = (float(cfg[keys[0]]), float(cfg[keys[1]])) if manual else beside(led, len(cpins))
                comp = Component("J%d" % jn, "conn", value, conn_footprint(cfg, len(cpins)),
                                 cpins, xy, c_rot, c_side)
                if not manual and c_side == cfg["side"]:
                    # the spot beside the LED may be taken by parts of other rows:
                    # move outward (away from the LED) in 1.27 mm steps until it is free
                    step = 1.27 if xy[0] >= led.xy[0] else -1.27
                    other = -step
                    tries = [(xy[0] + step * k, xy[1]) for k in range(0, 80)]
                    tries += [(led.xy[0] + (led.xy[0] - xy[0]) + other * k, xy[1])
                              for k in range(0, 80)]
                    if not _free_spot(comp, d.components, preset, tries):
                        comp.xy = xy
                d.components.append(comp)
        return d

    # simple LEDs: row / column matrix, numbered in layout.order
    for i, (r, c) in enumerate(order):
        led_pins = [(pins["K"], "K", "COL%d" % (c + 1)), (pins["A"], "A", "ROW%d" % (r + 1))]
        d.components.append(Component("%s%d" % (prefix, i + 1), "led", preset["value"],
                                      preset["footprint"], led_pins,
                                      layout.board_xy(r, c, origin),
                                      grid.led_rotation(layout, cfg, r, c)))
    if cfg["connectors"]:
        # rows connector(s) = "in" settings, columns connector(s) = "out" settings
        max_pins = max(1, int(cfg.get("conn_max_pins", MAX_CONN_PINS)))
        rows = [r for r in range(layout.rows) if any(layout.cells[r])]
        cols = [c for c in range(layout.cols) if any(row[c] for row in layout.cells)]
        top = origin[1] - preset["body"][1] / 2.0 - float(cfg.get("conn_gap", 2.54)) - 1.27
        jn = 1
        groups = []
        if cfg.get("conn_in", True):
            groups.append(("ROWS", "ROW", rows, ("conn_in_x", "conn_in_y"), 0.0,
                           lambda chunk: (left - conn_gap, origin[1] + chunk[0] * layout.pitch_y)))
        if cfg.get("conn_out", True):
            groups.append(("COLS", "COL", cols, ("conn_out_x", "conn_out_y"), 90.0,
                           lambda chunk: (origin[0] + chunk[0] * layout.pitch_x, top)))
        for value, net_prefix, lines, keys, auto_rot, auto_xy in groups:
            for k in range(0, len(lines), max_pins):
                chunk = lines[k:k + max_pins]
                if manual:
                    # further chunks continue along the pin direction
                    sx, sy = _rotate(0.0, 2.54 * k, c_rot)
                    xy, rot = (float(cfg[keys[0]]) + sx, float(cfg[keys[1]]) + sy), c_rot
                else:
                    xy, rot = auto_xy(chunk), auto_rot + c_rot
                d.components.append(Component(
                    "J%d" % jn, "conn", value, conn_footprint(cfg, len(chunk)),
                    [(str(i + 1), "%s%d" % (net_prefix, v + 1), "%s%d" % (net_prefix, v + 1))
                     for i, v in enumerate(chunk)], xy, rot % 360.0, c_side))
                jn += 1
    return d
