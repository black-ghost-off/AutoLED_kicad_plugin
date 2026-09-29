"""Netlist-level description of the LED array, shared by schematic and PCB output."""

import math
import uuid

from . import grid

MAX_CONN_PINS = 40


class Component(object):
    def __init__(self, ref, kind, value, footprint, pins, xy=None, rotation=0.0):
        self.ref = ref
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
    def __init__(self, preset):
        self.preset = preset
        self.components = []

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


def _header_fp(n):
    return "Connector_PinHeader_2.54mm:PinHeader_1x%02d_P2.54mm_Vertical" % n


def build(layout, cfg, preset):
    """Create components and nets for the placed LEDs.

    Addressable LEDs are daisy-chained in layout.order:
        J1(+5V, DIN, GND) -> D1 -> D2 -> ... -> DN -> J2(+5V, DOUT, GND)
    Simple LEDs are wired as a matrix: anode -> ROW<r>, cathode -> COL<c>.
    """
    d = Design(preset)
    origin = (float(cfg["origin_x"]), float(cfg["origin_y"]))
    prefix = cfg["ref_prefix"] or "D"
    pins = preset["pins"]
    order = layout.order
    n = len(order)
    if n == 0:
        return d

    xs = [layout.board_xy(r, c, origin)[0] for r, c in order]
    left = min(xs)
    conn_gap = max(layout.pitch_x, 5.0) + 2.54

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
            for i, led in enumerate(d.leds):
                # the cap follows its LED, including the zigzag 180 deg flip
                cdx, cdy = _rotate(preset["cap_offset"][0], preset["cap_offset"][1], led.rotation)
                d.components.append(Component(
                    "C%d" % (i + 1), "cap", cfg["cap_value"], cfg["cap_footprint"],
                    [("1", "1", "+5V"), ("2", "2", "GND")],
                    (led.xy[0] + cdx, led.xy[1] + cdy), (led.rotation + 90.0) % 360.0))
        if cfg["connectors"]:
            def beside(led):
                # next to the outer end of the LED's row, on the nearer side
                row_xs = [xy[0] for xy in (l.xy for l in d.leds) if abs(xy[1] - led.xy[1]) < 1e-6]
                lo, hi = min(row_xs), max(row_xs)
                x = lo - conn_gap if led.xy[0] - lo <= hi - led.xy[0] else hi + conn_gap
                return (x, led.xy[1] - 2.54)
            d.components.append(Component(
                "J1", "conn", "LED_IN", _header_fp(3),
                [("1", "+5V", "+5V"), ("2", "DIN", "DIN"), ("3", "GND", "GND")],
                beside(d.leds[0]), 0.0))
            d.components.append(Component(
                "J2", "conn", "LED_OUT", _header_fp(3),
                [("1", "+5V", "+5V"), ("2", "DOUT", "DOUT"), ("3", "GND", "GND")],
                beside(d.leds[-1]), 0.0))
        return d

    # simple LEDs: row / column matrix, numbered in layout.order
    for i, (r, c) in enumerate(order):
        led_pins = [(pins["K"], "K", "COL%d" % (c + 1)), (pins["A"], "A", "ROW%d" % (r + 1))]
        d.components.append(Component("%s%d" % (prefix, i + 1), "led", preset["value"],
                                      preset["footprint"], led_pins,
                                      layout.board_xy(r, c, origin),
                                      grid.led_rotation(layout, cfg, r, c)))
    if cfg["connectors"]:
        rows = [r for r in range(layout.rows) if any(layout.cells[r])]
        cols = [c for c in range(layout.cols) if any(row[c] for row in layout.cells)]
        top = origin[1] - max(layout.pitch_y, 5.0) - 2.54
        jn = 1
        for k in range(0, len(rows), MAX_CONN_PINS):
            chunk = rows[k:k + MAX_CONN_PINS]
            y = origin[1] + chunk[0] * layout.pitch_y
            d.components.append(Component(
                "J%d" % jn, "conn", "ROWS", _header_fp(len(chunk)),
                [(str(i + 1), "ROW%d" % (r + 1), "ROW%d" % (r + 1)) for i, r in enumerate(chunk)],
                (left - conn_gap, y), 0.0))
            jn += 1
        for k in range(0, len(cols), MAX_CONN_PINS):
            chunk = cols[k:k + MAX_CONN_PINS]
            x = origin[0] + chunk[0] * layout.pitch_x
            d.components.append(Component(
                "J%d" % jn, "conn", "COLS", _header_fp(len(chunk)),
                [(str(i + 1), "COL%d" % (c + 1), "COL%d" % (c + 1)) for i, c in enumerate(chunk)],
                (x, top), 90.0))
            jn += 1
    return d
