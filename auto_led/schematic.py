"""Write a self-contained KiCad schematic (.kicad_sch) for a Design.

All symbols are embedded in the file (library nickname "AutoLED"), so no
symbol library setup is needed.  Connections are made with net labels placed
exactly on pin ends.  The file uses the KiCad 7 format, which KiCad 7, 8, 9
and 10 all open.
"""

import datetime
import math
import os
import re
import uuid

SCH_VERSION = "20230121"
LIB = "AutoLED"
FONT = "(effects (font (size 1.27 1.27)))"
FONT_HIDE = "(effects (font (size 1.27 1.27)) hide)"


def _f(v):
    s = ("%.4f" % v).rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _q(s):
    return '"%s"' % str(s).replace("\\", "\\\\").replace('"', '\\"')


def _uid():
    return str(uuid.uuid4())


def _sym_name(value):
    return re.sub(r"[^A-Za-z0-9_.+-]", "_", value)


# --------------------------------------------------------------- symbols
# Each symbol: {"name", "ref", "value", "graphics": [...], "pins": [(num, name, type, x, y, angle, length)],
#               "power": bool, "hide_pin_names": bool, "hide_pin_numbers": bool}

def _rect(x0, y0, x1, y1):
    return ("(rectangle (start %s %s) (end %s %s) (stroke (width 0.254) (type default)) "
            "(fill (type background)))" % (_f(x0), _f(y0), _f(x1), _f(y1)))


def _poly(pts, width=0.254, fill="none"):
    xy = " ".join("(xy %s %s)" % (_f(x), _f(y)) for x, y in pts)
    return "(polyline (pts %s) (stroke (width %s) (type default)) (fill (type %s)))" % (
        xy, _f(width), fill)


def addressable_symbol(preset):
    p = preset["pins"]
    return {
        "name": _sym_name(preset["value"]), "ref": "D", "value": preset["value"],
        "graphics": [_rect(-5.08, 5.08, 5.08, -5.08)],
        "pins": [
            (p["VDD"], "VDD", "power_in", 0, 7.62, 270, 2.54),
            (p["GND"], "GND", "power_in", 0, -7.62, 90, 2.54),
            (p["DIN"], "DIN", "input", -7.62, 0, 0, 2.54),
            (p["DOUT"], "DOUT", "output", 7.62, 0, 180, 2.54),
        ],
    }


def led_symbol(preset):
    p = preset["pins"]
    return {
        "name": _sym_name(preset["value"]), "ref": "D", "value": preset["value"],
        "hide_pin_names": True,
        "graphics": [
            _poly([(1.27, -1.27), (1.27, 1.27), (-1.27, 0), (1.27, -1.27)]),
            _poly([(-1.27, -1.27), (-1.27, 1.27)]),
            _poly([(-1.27, 0), (1.27, 0)], 0),
        ],
        "pins": [
            (p["K"], "K", "passive", -3.81, 0, 0, 2.54),
            (p["A"], "A", "passive", 3.81, 0, 180, 2.54),
        ],
    }


def cap_symbol():
    return {
        "name": "C", "ref": "C", "value": "C", "hide_pin_names": True,
        "graphics": [_poly([(-2.032, -0.762), (2.032, -0.762)], 0.508),
                     _poly([(-2.032, 0.762), (2.032, 0.762)], 0.508)],
        "pins": [("1", "1", "passive", 0, 3.81, 270, 2.794),
                 ("2", "2", "passive", 0, -3.81, 90, 2.794)],
    }


def conn_symbol(n):
    return {
        "name": "Conn_01x%02d" % n, "ref": "J", "value": "Conn_01x%02d" % n,
        "graphics": [_rect(-1.27, 1.27, 3.81, -(n - 1) * 2.54 - 1.27)],
        "pins": [(str(i + 1), "Pin_%d" % (i + 1), "passive", -5.08, -i * 2.54, 0, 3.81)
                 for i in range(n)],
    }


def pwr_flag_symbol():
    return {
        "name": "PWR_FLAG", "ref": "#FLG", "value": "PWR_FLAG", "power": True,
        "hide_pin_names": True, "hide_pin_numbers": True,
        "graphics": [_poly([(0, 0), (0, 1.27), (-1.016, 1.905), (0, 2.54),
                            (1.016, 1.905), (0, 1.27)], 0)],
        "pins": [("1", "pwr", "power_out", 0, 0, 90, 0)],
    }


def _lib_symbol(sym, prefix=LIB + ":"):
    name = sym["name"]
    head = "(symbol %s" % _q(prefix + name)
    if sym.get("power"):
        head += " (power)"
    if sym.get("hide_pin_numbers"):
        head += " (pin_numbers hide)"
    if sym.get("hide_pin_names"):
        head += " (pin_names (offset 0) hide)"
    head += " (in_bom yes) (on_board yes)"
    ref_hide = FONT_HIDE if sym.get("power") else FONT
    lines = [
        head,
        "  (property \"Reference\" %s (at 0 8.89 0) %s)" % (_q(sym["ref"]), ref_hide),
        "  (property \"Value\" %s (at 0 -8.89 0) %s)" % (_q(sym["value"]), FONT),
        "  (property \"Footprint\" \"\" (at 0 0 0) %s)" % FONT_HIDE,
        "  (property \"Datasheet\" \"\" (at 0 0 0) %s)" % FONT_HIDE,
        "  (symbol %s" % _q("%s_0_1" % name),
    ]
    lines += ["    " + g for g in sym["graphics"]]
    lines.append("  )")
    lines.append("  (symbol %s" % _q("%s_1_1" % name))
    for num, pname, ptype, x, y, ang, length in sym["pins"]:
        lines.append("    (pin %s line (at %s %s %d) (length %s) (name %s %s) (number %s %s))" % (
            ptype, _f(x), _f(y), ang, _f(length), _q(pname), FONT, _q(num), FONT))
    lines.append("  )")
    lines.append(")")
    return "\n".join("    " + l for l in lines)


# --------------------------------------------------------------- writer

class _Sheet(object):
    def __init__(self, project, root_uuid):
        self.project = project
        self.root = root_uuid
        self.items = []

    def label(self, name, x, y, pin_angle):
        # pin_angle points from the pin end toward the symbol body
        ang, just = {0: (180, "right"), 180: (0, "left"),
                     270: (90, "left"), 90: (270, "right")}[pin_angle]
        self.items.append(
            "  (label %s (at %s %s %d) (effects (font (size 1.27 1.27)) (justify %s bottom)) (uuid %s))"
            % (_q(name), _f(x), _f(y), ang, just, _uid()))

    def symbol(self, sym, ref, value, footprint, x, y, sym_uuid, nets, in_bom=True, on_board=True):
        """Place sym at (x, y); nets maps pin number -> net name."""
        yes = lambda b: "yes" if b else "no"
        ref_hide = sym.get("power")
        out = [
            "  (symbol (lib_id %s) (at %s %s 0) (unit 1)" % (_q("%s:%s" % (LIB, sym["name"])), _f(x), _f(y)),
            "    (in_bom %s) (on_board %s) (dnp no)" % (yes(in_bom), yes(on_board)),
            "    (uuid %s)" % sym_uuid,
            "    (property \"Reference\" %s (at %s %s 0) %s)" % (
                _q(ref), _f(x + 1.27), _f(y - 6.35), FONT_HIDE if ref_hide else
                "(effects (font (size 1.27 1.27)) (justify left))"),
            "    (property \"Value\" %s (at %s %s 0) %s)" % (
                _q(value), _f(x + 1.27), _f(y + 6.35 if not sym.get("power") else y - 3.81),
                "(effects (font (size 1.27 1.27)) (justify left))"),
            "    (property \"Footprint\" %s (at %s %s 0) %s)" % (_q(footprint), _f(x), _f(y), FONT_HIDE),
            "    (property \"Datasheet\" \"\" (at %s %s 0) %s)" % (_f(x), _f(y), FONT_HIDE),
        ]
        for num, _, _, _, _, _, _ in sym["pins"]:
            out.append("    (pin %s (uuid %s))" % (_q(num), _uid()))
        out += [
            "    (instances (project %s (path %s (reference %s) (unit 1))))" % (
                _q(self.project), _q("/" + self.root), _q(ref)),
            "  )",
        ]
        self.items.append("\n".join(out))
        for num, _, _, px, py, ang, _ in sym["pins"]:
            net = nets.get(num)
            if net:
                self.label(net, x + px, y - py, ang)
            elif num in nets:  # explicitly unconnected (e.g. an NC connector pin)
                self.items.append("  (no_connect (at %s %s) (uuid %s))" % (
                    _f(x + px), _f(y - py), _uid()))


_PAPERS = [("A4", 297, 210), ("A3", 420, 297), ("A2", 594, 420), ("A1", 841, 594), ("A0", 1189, 841)]


def _snap(v, g=2.54):
    return round(v / g) * g


GENERATED_MARK = "generated by KiCad AutoLED"
_CONTENT_TOKENS = ("(lib_id", "(sheet ", "(sheet\n", "(wire", "(label", "(global_label",
                   "(hierarchical_label", "(text ", "(junction", "(bus", "(polyline", "(rectangle",
                   "(image")


def inspect_existing(path):
    """('missing' | 'empty' | 'autoled' | 'user', root uuid or None) for a schematic file.

    'empty': no symbols, sheets, wires, labels or graphics outside lib_symbols.
    'autoled': written by this plugin before (safe to regenerate).
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return "missing", None
    m = re.search(r'\(uuid\s+"?([0-9a-fA-F-]{36})"?\)', text)
    root = m.group(1) if m else None
    if GENERATED_MARK in text:
        return "autoled", root
    # ignore the embedded symbol library, it may contain graphics
    body = text
    i = body.find("(lib_symbols")
    if i >= 0:
        depth, j = 0, i
        while j < len(body):
            if body[j] == "(":
                depth += 1
            elif body[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        body = body[:i] + body[j + 1:]
    if any(tok in body for tok in _CONTENT_TOKENS):
        return "user", root
    return "empty", root


def write(path, design, project_name, title="LED array", root_uuid=None):
    """Write the schematic.  root_uuid keeps an existing sheet's UUID (project root sheet)."""
    preset = design.preset
    root = root_uuid or _uid()
    sheet = _Sheet(project_name, root)
    addressable = preset["kind"] == "addressable"
    led_sym = addressable_symbol(preset) if addressable else led_symbol(preset)
    syms = {led_sym["name"]: led_sym}
    cap = cap_symbol()
    flag = pwr_flag_symbol()

    leds = design.leds
    caps = {c.ref[1:]: c for c in design.components if c.kind == "cap"}
    conns = [c for c in design.components if c.kind == "conn"]

    margin = 25.4
    # header strip: connectors and power flags
    x = margin + 10.16
    header_h = 20.32
    for comp in conns:
        n = len(comp.pins)
        sym = conn_symbol(n)
        syms[sym["name"]] = sym
        sheet.symbol(sym, comp.ref, comp.value, comp.footprint, x, margin + 5.08, comp.uuid,
                     {num: net for num, _, net in comp.pins})
        header_h = max(header_h, (n - 1) * 2.54 + 17.78)
        x += 30.48
    if addressable:
        syms[flag["name"]] = flag
        for i, net in enumerate(("+5V", "GND")):
            sheet.symbol(flag, "#FLG%02d" % (i + 1), "PWR_FLAG", "", x, margin + 10.16, _uid(),
                         {"1": net}, in_bom=False, on_board=False)
            x += 15.24
    header_w = x

    # LED grid
    if addressable:
        cell_w, cell_h = (40.64 if caps else 27.94), 27.94
    else:
        cell_w, cell_h = 17.78, 12.7
    n = max(1, len(leds))
    ncols = max(1, int(round(math.sqrt(n * cell_h / cell_w * 1.414))))
    ncols = min(ncols, n)
    nrows = int(math.ceil(n / float(ncols)))
    y0 = _snap(margin + header_h + 5.08)
    x0 = margin + 10.16
    if caps:
        syms[cap["name"]] = cap
    for i, comp in enumerate(leds):
        gx = x0 + (i % ncols) * cell_w
        gy = y0 + (i // ncols) * cell_h
        sheet.symbol(led_sym, comp.ref, comp.value, comp.footprint, gx, gy, comp.uuid,
                     {num: net for num, _, net in comp.pins})
        c = caps.get(comp.ref[len(comp.ref.rstrip("0123456789")):])
        if c is not None:
            sheet.symbol(cap, c.ref, c.value, c.footprint, gx + 17.78, gy, c.uuid,
                         {num: net for num, _, net in c.pins})

    need_w = max(header_w, x0 + ncols * cell_w) + margin
    need_h = y0 + nrows * cell_h + margin
    paper = None
    for name, w, h in _PAPERS:
        if need_w <= w and need_h <= h:
            paper = "(paper %s)" % _q(name)
            break
    if paper is None:
        paper = "(paper \"User\" %s %s)" % (_f(math.ceil(need_w)), _f(math.ceil(need_h)))

    lib = "\n".join(_lib_symbol(s) for s in syms.values())
    text = "\n".join([
        "(kicad_sch (version %s) (generator eeschema)" % SCH_VERSION,
        "  (uuid %s)" % root,
        "  " + paper,
        "  (title_block (title %s) (date %s) (comment 1 %s))" % (
            _q(title), _q(datetime.date.today().isoformat()),
            _q("%d x %s, %s" % (len(leds), preset["value"], GENERATED_MARK))),
        "  (lib_symbols",
        lib,
        "  )",
        "\n".join(sheet.items),
        "  (sheet_instances (path \"/\" (page \"1\")))",
        ")",
        "",
    ])
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return root, list(syms.values())


def _top_level_blocks(text):
    """Top-level '(symbol ...)' blocks of a .kicad_sym file, keyed by name."""
    blocks, depth, start, in_str, esc = {}, 0, None, False, False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "(":
            depth += 1
            if depth == 2:
                start = i
        elif ch == ")":
            if depth == 2 and start is not None:
                block = text[start:i + 1]
                m = re.match(r'\(symbol\s+"([^"]+)"', block)
                if m:
                    blocks[m.group(1)] = block
            depth -= 1
    return blocks


def write_library(path, symbols):
    """Write / update AutoLED.kicad_sym, keeping symbols from earlier runs."""
    blocks = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            blocks = _top_level_blocks(f.read())
    except OSError:
        pass
    for sym in symbols:
        blocks[sym["name"]] = _lib_symbol(sym, prefix="").strip()
    text = "(kicad_symbol_lib (version 20220914) (generator kicad_autoled)\n%s\n)\n" % (
        "\n".join("  " + b for b in blocks.values()))
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def register_library(project_dir, lib_path):
    """Add the AutoLED library to the project's sym-lib-table if missing."""
    table = os.path.join(project_dir, "sym-lib-table")
    rel = os.path.relpath(lib_path, project_dir)
    uri = "${KIPRJMOD}/" + rel.replace(os.sep, "/") if not rel.startswith("..") else lib_path
    entry = '  (lib (name "%s")(type "KiCad")(uri "%s")(options "")(descr "KiCad AutoLED symbols"))' % (
        LIB, uri)
    try:
        with open(table, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        text = "(sym_lib_table\n  (version 7)\n)\n"
    if re.search(r'\(name\s+"?%s"?\)' % LIB, text):
        return False
    idx = text.rfind(")")
    text = text[:idx].rstrip() + "\n" + entry + "\n)\n"
    with open(table, "w", encoding="utf-8") as f:
        f.write(text)
    return True
