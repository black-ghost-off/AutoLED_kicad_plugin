"""Place a Design on a pcbnew BOARD."""

import glob
import os
import re
import sys

import pcbnew

GROUP_NAME = "AutoLED"


# ------------------------------------------------------- footprint lookup

def _kicad_config_dirs():
    home = os.path.expanduser("~")
    if sys.platform == "darwin":
        bases = [os.path.join(home, "Library", "Preferences", "kicad")]
    elif sys.platform.startswith("win"):
        bases = [os.path.join(os.environ.get("APPDATA", ""), "kicad")]
    else:
        bases = [os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.join(home, ".config")), "kicad")]
    dirs = []
    try:
        dirs.append(pcbnew.SETTINGS_MANAGER.GetUserSettingsPath())
    except Exception:
        pass
    for base in bases:
        versions = sorted(glob.glob(os.path.join(base, "*")),
                          key=lambda p: [int(x) for x in re.findall(r"\d+", os.path.basename(p))] or [0],
                          reverse=True)
        dirs += versions
    return dirs


def _default_fp_dirs():
    env = [v for k, v in os.environ.items() if re.match(r"KICAD\d*_FOOTPRINT_DIR$", k)]
    guesses = [
        "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints",
        "/usr/share/kicad/footprints",
        "/usr/local/share/kicad/footprints",
        "/app/share/kicad/footprints",
    ]
    for pf in (os.environ.get("ProgramFiles", r"C:\Program Files"),):
        guesses += sorted(glob.glob(os.path.join(pf, "KiCad", "*", "share", "kicad", "footprints")),
                          reverse=True)
    return [d for d in env + guesses if d and os.path.isdir(d)]


def _expand(uri, extra_vars):
    def repl(m):
        name = m.group(1)
        return extra_vars.get(name) or os.environ.get(name) or m.group(0)
    return re.sub(r"\$\{([^}]+)\}", repl, uri)


def _parse_fp_lib_table(path, extra_vars):
    libs = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return libs
    for m in re.finditer(r"\(lib\s+\(name\s+\"?([^\")]+)\"?\).*?\(uri\s+\"?([^\")]+)\"?\)", text, re.S):
        libs[m.group(1)] = _expand(m.group(2), extra_vars)
    return libs


class FootprintResolver(object):
    def __init__(self, board_path="", extra_dir=""):
        self.extra_dir = extra_dir
        self.defaults = _default_fp_dirs()
        proj_dir = os.path.dirname(board_path) if board_path else ""
        extra_vars = {"KIPRJMOD": proj_dir}
        for d in self.defaults:
            for n in range(6, 12):
                extra_vars.setdefault("KICAD%d_FOOTPRINT_DIR" % n, d)
        self.table = {}
        for cfg_dir in reversed(_kicad_config_dirs()):
            self.table.update(_parse_fp_lib_table(os.path.join(cfg_dir, "fp-lib-table"), extra_vars))
        if proj_dir:
            self.table.update(_parse_fp_lib_table(os.path.join(proj_dir, "fp-lib-table"), extra_vars))
        self._plugins = {}

    def library_path(self, nickname):
        cands = []
        if self.extra_dir:
            cands += [os.path.join(self.extra_dir, nickname + ".pretty"), self.extra_dir]
        if nickname in self.table:
            cands.append(self.table[nickname])
        cands += [os.path.join(d, nickname + ".pretty") for d in self.defaults]
        for c in cands:
            if os.path.isdir(c):
                return c
        return None

    def load(self, lib_id):
        if ":" not in lib_id:
            raise ValueError("Footprint must be 'Library:Name', got %r" % lib_id)
        nick, name = lib_id.split(":", 1)
        path = self.library_path(nick)
        if path is None or not os.path.isfile(os.path.join(path, name + ".kicad_mod")):
            raise ValueError("Footprint %s not found. Set 'Extra footprint folder' to the folder "
                             "containing %s.pretty" % (lib_id, nick))
        # one plugin per library keeps the parsed library cached (much faster)
        plugin = self._plugins.get(path)
        if plugin is None:
            plugin = self._plugins[path] = pcbnew.GetPluginForPath(path)
        fp = plugin.FootprintLoad(path, name)
        if fp is None:
            raise ValueError("Cannot load footprint %s from %s" % (lib_id, path))
        fp.SetFPID(pcbnew.LIB_ID(nick, name))
        return fp


# --------------------------------------------------------------- helpers

def _mm(x, y):
    return pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))


def _flip(item):
    pos = item.GetPosition()
    try:
        item.Flip(pos, pcbnew.FLIP_DIRECTION_TOP_BOTTOM)  # KiCad 9+
    except (AttributeError, TypeError):
        item.Flip(pos, False)


def remove_previous(board):
    removed = 0
    for group in list(board.Groups()):
        if group.GetName() != GROUP_NAME:
            continue
        for item in list(group.GetItems()):
            group.RemoveItem(item)
            board.Remove(item)
            removed += 1
        board.Remove(group)
    return removed


def _net(board, name, cache):
    if name in cache:
        return cache[name]
    net = board.FindNet(name)
    if net is None:
        net = pcbnew.NETINFO_ITEM(board, name)
        board.Add(net)
    cache[name] = net
    return net


def _bbox_mm(fp):
    try:
        bb = fp.GetBoundingBox(False, False)
    except TypeError:
        bb = fp.GetBoundingBox()
    return (pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetTop()),
            pcbnew.ToMM(bb.GetRight()), pcbnew.ToMM(bb.GetBottom()))


def _area(loop):
    return 0.5 * abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(loop, loop[1:] + loop[:1])))


def _add_plane(board, group, loop, net, layer):
    """Copper zone covering the board outline, on the side opposite the LEDs."""
    zone = pcbnew.ZONE(board)
    zone.SetLayer(layer)
    zone.SetNet(net)
    zone.SetIsRuleArea(False)
    poly = zone.Outline()
    poly.NewOutline()
    for x, y in loop:
        poly.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
    board.Add(zone)
    group.AddItem(zone)
    try:
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    except Exception:
        pass  # unfilled zone still routes; press B in the editor to fill
    return zone


def apply(board, design, cfg, board_path="", outline_fn=None, net_prefix="/"):
    """Add the design's footprints to board, then the outline from outline_fn.

    outline_fn(boxes) gets the placed footprints' bounds (x0, y0, x1, y1) in mm
    and returns Edge.Cuts loops.

    Nets are named like eeschema names local labels on the root sheet
    ("/DIN", "/ROW1"), so a later "Update PCB from Schematic" keeps them.
    Returns the number of footprints placed.
    """
    if cfg["clear_prev"]:
        remove_previous(board)
    resolver = FootprintResolver(board_path, cfg["footprint_dir"])
    group = pcbnew.PCB_GROUP(board)
    group.SetName(GROUP_NAME)
    board.Add(group)
    nets = {}
    back = cfg["side"] == "back"
    placed = 0
    boxes = []
    for comp in design.components:
        fp = resolver.load(comp.footprint)
        fp.SetReference(comp.ref)
        fp.SetValue(comp.value)
        fp.SetPath(pcbnew.KIID_PATH("/" + comp.uuid))
        if comp.kind == "cap":
            fp.Reference().SetVisible(False)  # keeps the LED silkscreen readable
        board.Add(fp)
        fp.SetPosition(_mm(*comp.xy))
        fp.SetOrientationDegrees(comp.rotation)
        for pad in fp.Pads():
            net_name = comp.net_of(pad.GetNumber())
            if net_name:
                pad.SetNet(_net(board, net_prefix + net_name, nets))
        if back:
            _flip(fp)
        group.AddItem(fp)
        boxes.append(_bbox_mm(fp))
        placed += 1
    loops = outline_fn(boxes) if outline_fn else []
    layer = board.GetLayerID(cfg.get("outline_layer") or "Edge.Cuts")
    if layer < 0:
        layer = pcbnew.Edge_Cuts
    for loop in loops:
        for a, b in zip(loop, loop[1:] + loop[:1]):
            seg = pcbnew.PCB_SHAPE(board)
            seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
            seg.SetLayer(layer)
            seg.SetWidth(pcbnew.FromMM(0.1))
            seg.SetStart(_mm(*a))
            seg.SetEnd(_mm(*b))
            board.Add(seg)
            group.AddItem(seg)
    gnd = nets.get(net_prefix + "GND")
    if cfg.get("gnd_plane") and loops and gnd is not None and layer == pcbnew.Edge_Cuts:
        _add_plane(board, group, max(loops, key=_area), gnd,
                   pcbnew.F_Cu if back else pcbnew.B_Cu)
    try:
        board.BuildConnectivity()
    except Exception:
        pass
    return placed
