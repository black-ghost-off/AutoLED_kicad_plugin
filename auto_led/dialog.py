"""wxPython dialog: settings on the left, live black & white / LED preview on the right."""

import math
import os
import traceback

import wx
import wx.lib.scrolledpanel as scrolled

from . import config, generator, grid

IMAGE_WILDCARD = ("Images (*.svg;*.png;*.bmp;*.jpg;*.jpeg;*.gif)|*.svg;*.png;*.bmp;*.jpg;*.jpeg;*.gif|"
                  "All files (*.*)|*.*")

# (section, [(key, label, type, options)])
FORM = [
    ("Image", [
        ("image_path", "Image (SVG/PNG/BMP)", "file", {"wildcard": IMAGE_WILDCARD}),
        ("threshold", "B/W threshold", "slider", {"min": 1, "max": 255}),
        ("invert", "Invert (LEDs on white)", "bool", {}),
        ("use_alpha", "Use alpha channel as mask", "bool", {}),
        ("work_res", "Processing resolution, px", "int", {"min": 50, "max": 4000}),
    ]),
    ("Geometry", [
        ("sample_mode", "Placement mode", "choice", {"choices": config.SAMPLE_MODES}),
        ("scale_mode", "Image scale by", "choice", {"choices": config.SCALE_MODES}),
        ("width_mm", "Shape width, mm", "float", {"min": 1, "max": 5000}),
        ("height_mm", "Shape height, mm", "float", {"min": 1, "max": 5000}),
        ("scale_pct", "Scale, % of native size", "float", {"min": 0.1, "max": 100000}),
        ("dpi", "Image DPI", "float", {"min": 1, "max": 100000}),
        ("pitch_x", "LED pitch X, mm", "float", {"min": 0.5, "max": 500}),
        ("pitch_y", "LED pitch Y, mm", "float", {"min": 0.5, "max": 500}),
        ("border_mm", "Border offset, mm", "float", {"min": -200, "max": 200}),
        ("fit_body", "Keep whole LED body inside (offset from body edge)", "bool", {}),
        ("coverage", "Min cell coverage, %", "int", {"min": 1, "max": 100}),
        ("grid_dx", "Grid shift X, mm", "float", {"min": -500, "max": 500}),
        ("grid_dy", "Grid shift Y, mm", "float", {"min": -500, "max": 500}),
    ]),
    ("LED", [
        ("preset", "LED type", "choice", {"choices": [(k, k) for k in config.PRESETS]}),
        ("footprint", "Footprint override (Lib:Name)", "text", {}),
        ("rotation", "Rotation, deg", "float", {"min": -360, "max": 360}),
        ("side", "Board side", "choice", {"choices": config.SIDES}),
        ("ref_prefix", "Reference prefix", "text", {}),
        ("decoupling", "Decoupling cap per LED (addressable)", "bool", {}),
        ("cap_value", "Cap value", "text", {}),
        ("cap_footprint", "Cap footprint", "text", {}),
        ("cap_rotation", "Cap rotation (relative to LED), deg", "float", {"min": -360, "max": 360}),
        ("cap_custom_offset", "Custom cap position", "bool", {}),
        ("cap_dx", "Cap offset X from LED, mm", "float", {"min": -100, "max": 100}),
        ("cap_dy", "Cap offset Y from LED, mm", "float", {"min": -100, "max": 100}),
    ]),
    ("Connectors", [
        ("connectors", "Add connectors", "bool", {}),
        ("conn_in", "J1 input (matrix: rows)", "bool", {}),
        ("conn_out", "J2 output (matrix: columns)", "bool", {}),
        ("conn_footprint", "Footprint, {n} = pin count", "text", {}),
        ("conn_pinout", "Pin order (+5V, GND, DATA, NC)", "text", {}),
        ("conn_placement", "Placement", "choice", {"choices": config.CONN_PLACEMENTS}),
        ("conn_gap", "Auto: gap to LEDs, mm", "float", {"min": -50, "max": 200}),
        ("conn_in_x", "J1 X, mm", "float", {"min": -2000, "max": 2000}),
        ("conn_in_y", "J1 Y, mm", "float", {"min": -2000, "max": 2000}),
        ("conn_out_x", "J2 X, mm", "float", {"min": -2000, "max": 2000}),
        ("conn_out_y", "J2 Y, mm", "float", {"min": -2000, "max": 2000}),
        ("conn_rotation", "Rotation, deg", "float", {"min": -360, "max": 360}),
        ("conn_side", "Board side", "choice", {"choices": config.CONN_SIDES}),
        ("conn_max_pins", "Matrix: max pins per connector", "int", {"min": 1, "max": 200}),
    ]),
    ("Chain / numbering", [
        ("order", "Direction", "choice", {"choices": config.ORDERS}),
        ("zigzag", "Zigzag (serpentine)", "bool", {}),
        ("zigzag_rotate", "Rotate LEDs 180\u00b0 on backward zigzag lines", "bool", {}),
        ("start_corner", "Start corner", "choice", {"choices": config.START_CORNERS}),
    ]),
    ("Output", [
        ("out_dir", "Output folder", "dir", {}),
        ("base_name", "File base name", "text", {}),
        ("c_prefix", "C identifier prefix", "text", {}),
        ("export_json", "Export JSON", "bool", {}),
        ("export_txt", "Export TXT", "bool", {}),
        ("export_h", "Export C/C++ header", "bool", {}),
        ("gen_sch", "Generate schematic", "bool", {}),
        ("sch_target", "Schematic goes to", "choice", {"choices": config.SCH_TARGETS}),
        ("export_cut", "Export cut line (SVG + DXF)", "bool", {}),
    ]),
    ("PCB", [
        ("place_pcb", "Place footprints on board", "bool", {}),
        ("origin_x", "Origin X (first row/col), mm", "float", {"min": -2000, "max": 2000}),
        ("origin_y", "Origin Y, mm", "float", {"min": -2000, "max": 2000}),
        ("clear_prev", "Remove previous AutoLED group", "bool", {}),
        ("outline", "Outline / cut line", "choice", {"choices": config.OUTLINES}),
        ("outline_margin", "Cut line margin, mm", "float", {"min": 0, "max": 100}),
        ("outline_layer", "Cut line layer", "choice", {"choices": config.OUTLINE_LAYERS}),
        ("footprint_dir", "Extra footprint folder", "dir", {}),
    ]),
    ("Routing (Freerouting)", [
        ("route", "Autoroute with Freerouting", "bool", {}),
        ("gnd_plane", "GND plane on opposite side", "bool", {}),
        ("route_passes", "Max passes", "int", {"min": 1, "max": 999}),
        ("route_timeout", "Timeout, s", "int", {"min": 10, "max": 36000}),
        ("freerouting_jar", "Freerouting jar (auto if empty)", "file",
         {"wildcard": "Java archive (*.jar)|*.jar"}),
        ("java_path", "Java executable (auto if empty)", "file", {"wildcard": "*"}),
    ]),
]

LED_COLOR = wx.Colour(230, 40, 40)
CAP_COLOR = wx.Colour(200, 150, 60)
CONN_COLOR = wx.Colour(40, 40, 40)
SHAPE_GRAY = 70
BACKGROUND = wx.Colour(245, 245, 245)


def footprint_body(lib_id, default=(1.0, 0.5)):
    """Approximate body size (w, h) in mm from a KiCad footprint name.

    C_0402_1005Metric -> 1.0 x 0.5, PinHeader_1x03_P2.54mm -> 2.54 x 7.62.
    """
    import re
    m = re.search(r"(\d\d)(\d\d)Metric", lib_id)
    if m:
        return int(m.group(1)) / 10.0, int(m.group(2)) / 10.0
    m = re.search(r"_1x(\d+)_P([\d.]+)mm", lib_id)
    if m:
        pitch = float(m.group(2))
        return pitch, pitch * int(m.group(1))
    return default


def _rot(dx, dy, deg):
    # KiCad convention: positive angles are counter-clockwise on screen (y down)
    a = math.radians(deg)
    return dx * math.cos(a) + dy * math.sin(a), -dx * math.sin(a) + dy * math.cos(a)


class PreviewView(object):
    """Zoom / pan state of the preview, in image millimetres."""

    MIN_ZOOM, MAX_ZOOM = 0.2, 200.0

    def __init__(self):
        self.zoom = 1.0
        self.center = None  # image mm; None = centre of the image

    def reset(self):
        self.zoom, self.center = 1.0, None

    def transform(self, mask, mm_per_px, width, height):
        """(display px per mm, centre x mm, centre y mm) for this view."""
        sx, sy = mm_per_px
        fit = min(width / (mask.width * sx), height / (mask.height * sy)) * 0.98
        cx, cy = self.center or (mask.width * sx / 2.0, mask.height * sy / 2.0)
        return fit * self.zoom, cx, cy

    def zoom_at(self, factor, sx_screen, sy_screen, mask, mm_per_px, width, height):
        """Zoom by factor keeping the point under (sx_screen, sy_screen) fixed."""
        d, cx, cy = self.transform(mask, mm_per_px, width, height)
        px_mm = cx + (sx_screen - width / 2.0) / d
        py_mm = cy + (sy_screen - height / 2.0) / d
        self.zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, self.zoom * factor))
        d2, _, _ = self.transform(mask, mm_per_px, width, height)
        self.center = (px_mm - (sx_screen - width / 2.0) / d2,
                       py_mm - (sy_screen - height / 2.0) / d2)

    def pan(self, dx_screen, dy_screen, mask, mm_per_px, width, height):
        d, cx, cy = self.transform(mask, mm_per_px, width, height)
        self.center = (cx - dx_screen / d, cy - dy_screen / d)


def render_preview(mask, layout, cfg, width, height, view=None, design=None):
    """Bitmap of the B/W mask with LEDs, caps and connectors drawn on top.

    view (PreviewView) sets zoom / pan; default fits the whole image.
    design (design.Design) adds capacitor and connector bodies.
    """
    width, height = max(1, width), max(1, height)
    bmp = wx.Bitmap(width, height)
    dc = wx.MemoryDC(bmp)
    dc.SetBackground(wx.Brush(BACKGROUND))
    dc.Clear()
    if mask is None:
        dc.SelectObject(wx.NullBitmap)
        return bmp
    view = view or PreviewView()
    mm_px = layout.mm_per_px if layout else (1.0, 1.0)
    sx, sy = mm_px
    d, cx, cy = view.transform(mask, mm_px, width, height)

    def to_screen(x_mm, y_mm):
        return width / 2.0 + (x_mm - cx) * d, height / 2.0 + (y_mm - cy) * d

    # visible part of the mask only, so deep zoom stays fast
    x0_mm, y0_mm = cx - width / 2.0 / d, cy - height / 2.0 / d
    x1_mm, y1_mm = cx + width / 2.0 / d, cy + height / 2.0 / d
    ix0 = max(0, int(math.floor(x0_mm / sx)))
    iy0 = max(0, int(math.floor(y0_mm / sy)))
    ix1 = min(mask.width, int(math.ceil(x1_mm / sx)) + 1)
    iy1 = min(mask.height, int(math.ceil(y1_mm / sy)) + 1)
    if ix1 > ix0 and iy1 > iy0:
        g = mask.data.translate(bytes([255] + [SHAPE_GRAY] * 255))
        rgb = bytearray(3 * len(g))
        rgb[0::3] = g
        rgb[1::3] = g
        rgb[2::3] = g
        img = wx.Image(mask.width, mask.height, bytes(rgb))
        sub = img.GetSubImage(wx.Rect(ix0, iy0, ix1 - ix0, iy1 - iy0))
        sx0, sy0 = to_screen(ix0 * sx, iy0 * sy)
        sx1, sy1 = to_screen(ix1 * sx, iy1 * sy)
        dw, dh = max(1, int(round(sx1 - sx0))), max(1, int(round(sy1 - sy0)))
        quality = wx.IMAGE_QUALITY_NEAREST if d * sx > 2 else wx.IMAGE_QUALITY_NORMAL
        dc.DrawBitmap(wx.Bitmap(sub.Scale(dw, dh, quality)), int(round(sx0)), int(round(sy0)))

    if layout is None or not layout.count:
        dc.SelectObject(wx.NullBitmap)
        return bmp

    # board mm -> image mm
    ox, oy = float(cfg["origin_x"]), float(cfg["origin_y"])
    bx, by = layout.x0_mm - ox, layout.y0_mm - oy

    def body(x_mm, y_mm, w, h, rot, anchor=(0.0, 0.0)):
        """Screen polygon of a w x h body rotated by rot around (x_mm, y_mm).

        anchor shifts the body centre relative to the footprint origin (unrotated)."""
        pts = []
        for ux, uy in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)):
            rx, ry = _rot(ux + anchor[0], uy + anchor[1], rot)
            pts.append(wx.Point(*map(int, map(round, to_screen(x_mm + rx, y_mm + ry)))))
        return pts

    def visible(pts):
        return any(-50 <= p.x <= width + 50 and -50 <= p.y <= height + 50 for p in pts)

    # capacitors and connectors (from the design)
    if design is not None:
        for comp in design.components:
            if comp.kind == "led":
                continue
            w, h = footprint_body(comp.footprint)
            anchor = (0.0, 0.0)
            if comp.kind == "conn":
                anchor = (0.0, h / 2.0 - w / 2.0)  # pin 1 at the footprint origin
                if comp.side and comp.side != cfg["side"]:
                    # on the other side of the board: dashed outline only
                    dc.SetPen(wx.Pen(CONN_COLOR, 2, wx.PENSTYLE_SHORT_DASH))
                    dc.SetBrush(wx.TRANSPARENT_BRUSH)
                else:
                    dc.SetPen(wx.Pen(CONN_COLOR))
                    dc.SetBrush(wx.Brush(wx.Colour(90, 90, 90)))
            else:
                dc.SetPen(wx.Pen(wx.Colour(110, 70, 0)))
                dc.SetBrush(wx.Brush(CAP_COLOR))
            pts = body(comp.xy[0] + bx, comp.xy[1] + by, w, h, comp.rotation, anchor)
            if visible(pts):
                dc.DrawPolygon(pts)
                if comp.kind == "conn" and d > 3:
                    dc.SetTextForeground(wx.Colour(0, 0, 0))
                    dc.DrawText(comp.ref, pts[0].x, pts[0].y - 14)

    # LEDs
    preset = config.preset_for(cfg)
    bw, bh = preset["body"]
    dc.SetPen(wx.Pen(wx.Colour(120, 0, 0)))
    dc.SetBrush(wx.Brush(LED_COLOR))
    chain = []
    markers = []
    for r, c in layout.order:
        x_mm, y_mm = layout.x0_mm + c * layout.pitch_x, layout.y0_mm + r * layout.pitch_y
        rot = grid.led_rotation(layout, cfg, r, c)
        pts = body(x_mm, y_mm, bw, bh, rot)
        chain.append(wx.Point(*map(int, to_screen(x_mm, y_mm))))
        if visible(pts):
            dc.DrawPolygon(pts)
            mx, my = _rot(-bw * 0.3, -bh * 0.3, rot)  # pin-1 corner of the body
            markers.append(to_screen(x_mm + mx, y_mm + my))
    if bw * d >= 6:
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.SetBrush(wx.Brush(wx.Colour(255, 230, 0)))
        rad = max(1, int(bw * d / 8))
        for mx, my in markers:
            dc.DrawCircle(int(mx), int(my), rad)
    if 1 < len(chain) < 6000:
        dc.SetPen(wx.Pen(wx.Colour(30, 110, 230), 1))
        dc.DrawLines(chain)
    dc.SetPen(wx.Pen(wx.Colour(0, 160, 0), 3))
    dc.SetBrush(wx.TRANSPARENT_BRUSH)
    dc.DrawCircle(chain[0].x, chain[0].y, max(6, int(max(bw, bh) * d)))
    dc.SelectObject(wx.NullBitmap)
    return bmp


class PreviewPanel(wx.Panel):
    """Preview with mouse-wheel zoom, drag to pan, double-click to fit."""

    def __init__(self, parent):
        wx.Panel.__init__(self, parent, style=wx.BORDER_SUNKEN | wx.WANTS_CHARS)
        self.SetMinSize((520, 420))
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.mask = None
        self.layout = None
        self.cfg = None
        self.design = None
        self.view = PreviewView()
        self._drag = None
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_SIZE, lambda e: (self.Refresh(), e.Skip()))
        self.Bind(wx.EVT_MOUSEWHEEL, self._on_wheel)
        self.Bind(wx.EVT_LEFT_DOWN, self._on_down)
        self.Bind(wx.EVT_LEFT_UP, self._on_up)
        self.Bind(wx.EVT_MOTION, self._on_motion)
        self.Bind(wx.EVT_LEFT_DCLICK, lambda e: self.fit())
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST, lambda e: setattr(self, "_drag", None))

    def set_data(self, mask, layout, cfg, design=None):
        self.mask, self.layout, self.cfg, self.design = mask, layout, cfg, design
        self.Refresh()

    def _mm_per_px(self):
        return self.layout.mm_per_px if self.layout else (1.0, 1.0)

    def zoom(self, factor, at=None):
        if self.mask is None:
            return
        w, h = self.GetClientSize()
        x, y = at if at is not None else (w / 2.0, h / 2.0)
        self.view.zoom_at(factor, x, y, self.mask, self._mm_per_px(), w, h)
        self.Refresh()

    def fit(self):
        self.view.reset()
        self.Refresh()

    def _on_wheel(self, evt):
        factor = 1.25 if evt.GetWheelRotation() > 0 else 1 / 1.25
        self.zoom(factor, evt.GetPosition())

    def _on_down(self, evt):
        self._drag = evt.GetPosition()
        if not self.HasCapture():
            self.CaptureMouse()
        self.SetCursor(wx.Cursor(wx.CURSOR_SIZING))

    def _on_up(self, _evt):
        self._drag = None
        if self.HasCapture():
            self.ReleaseMouse()
        self.SetCursor(wx.NullCursor)

    def _on_motion(self, evt):
        if self._drag is None or not evt.Dragging() or self.mask is None:
            return
        pos = evt.GetPosition()
        w, h = self.GetClientSize()
        self.view.pan(pos.x - self._drag.x, pos.y - self._drag.y, self.mask, self._mm_per_px(), w, h)
        self._drag = pos
        self.Refresh()

    def _on_paint(self, _evt):
        dc = wx.AutoBufferedPaintDC(self)
        w, h = self.GetClientSize()
        dc.DrawBitmap(render_preview(self.mask, self.layout, self.cfg, w, h, self.view,
                                     self.design), 0, 0)


class AutoLedDialog(wx.Dialog):
    def __init__(self, parent, board):
        wx.Dialog.__init__(self, parent, title="AutoLED - place LEDs on image shape",
                           style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.board = board
        self.board_path = board.GetFileName() if board is not None else ""
        self.cfg_path = config.config_path_for_board(self.board_path)
        self.cfg = config.load(self.cfg_path)
        if not self.cfg["out_dir"] and self.board_path:
            self.cfg["out_dir"] = os.path.dirname(self.board_path)
        self.pipeline = generator.Pipeline()
        self.controls = {}
        self._timer = None
        self._build()
        self._load_values()
        self.SetSize((1150, 820))
        self.CentreOnScreen()
        wx.CallAfter(self.update_preview)

    # ---------------------------------------------------------- building
    def _build(self):
        root = wx.BoxSizer(wx.VERTICAL)
        body = wx.BoxSizer(wx.HORIZONTAL)

        form = scrolled.ScrolledPanel(self, size=(430, -1))
        fs = wx.BoxSizer(wx.VERTICAL)
        for title, fields in FORM:
            box = wx.StaticBoxSizer(wx.VERTICAL, form, title)
            grid = wx.FlexGridSizer(0, 2, 4, 8)
            grid.AddGrowableCol(1, 1)
            for key, label, kind, opts in fields:
                ctrl = self._make_control(box.GetStaticBox(), key, kind, opts)
                if kind == "bool":
                    grid.Add((0, 0))
                    grid.Add(ctrl, 0, wx.EXPAND)
                else:
                    grid.Add(wx.StaticText(box.GetStaticBox(), label=label), 0, wx.ALIGN_CENTER_VERTICAL)
                    grid.Add(ctrl, 1, wx.EXPAND)
                self.controls[key] = (ctrl, kind, opts)
            box.Add(grid, 1, wx.EXPAND | wx.ALL, 4)
            fs.Add(box, 0, wx.EXPAND | wx.ALL, 4)
        form.SetSizer(fs)
        form.SetupScrolling(scroll_x=False)
        body.Add(form, 0, wx.EXPAND | wx.ALL, 4)

        right = wx.BoxSizer(wx.VERTICAL)
        self.preview = PreviewPanel(self)
        tools = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in (("Zoom +", lambda e: self.preview.zoom(1.5)),
                               ("Zoom \u2212", lambda e: self.preview.zoom(1 / 1.5)),
                               ("Fit", lambda e: self.preview.fit())):
            b = wx.Button(self, label=label, style=wx.BU_EXACTFIT)
            b.Bind(wx.EVT_BUTTON, handler)
            tools.Add(b, 0, wx.RIGHT, 4)
        tools.Add(wx.StaticText(self, label="wheel = zoom, drag = move, double-click = fit"),
                  0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        right.Add(tools, 0, wx.LEFT | wx.TOP, 4)
        right.Add(self.preview, 1, wx.EXPAND | wx.ALL, 4)
        self.status = wx.StaticText(self, label="Choose an image")
        right.Add(self.status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        self.log = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 110))
        right.Add(self.log, 0, wx.EXPAND | wx.ALL, 4)
        body.Add(right, 1, wx.EXPAND)
        root.Add(body, 1, wx.EXPAND)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_generate = wx.Button(self, label="Generate")
        btn_close = wx.Button(self, wx.ID_CLOSE, "Close")
        buttons.AddStretchSpacer()
        buttons.Add(self.btn_generate, 0, wx.ALL, 4)
        buttons.Add(btn_close, 0, wx.ALL, 4)
        root.Add(buttons, 0, wx.EXPAND | wx.ALL, 4)
        self.SetSizer(root)

        self.btn_generate.Bind(wx.EVT_BUTTON, self.on_generate)
        btn_close.Bind(wx.EVT_BUTTON, self.on_close)
        self.Bind(wx.EVT_CLOSE, self.on_close)

    def _make_control(self, parent, key, kind, opts):
        changed = lambda evt: (self._schedule_preview(), evt.Skip())
        if kind == "bool":
            label = [f[1] for _, fields in FORM for f in fields if f[0] == key][0]
            c = wx.CheckBox(parent, label=label)
            c.Bind(wx.EVT_CHECKBOX, changed)
        elif kind == "int":
            c = wx.SpinCtrl(parent, min=opts["min"], max=opts["max"], size=(120, -1))
            c.Bind(wx.EVT_SPINCTRL, changed)
            c.Bind(wx.EVT_TEXT, changed)
        elif kind == "float":
            c = wx.SpinCtrlDouble(parent, min=opts["min"], max=opts["max"], inc=0.1, size=(120, -1))
            c.SetDigits(3)
            c.Bind(wx.EVT_SPINCTRLDOUBLE, changed)
            c.Bind(wx.EVT_TEXT, changed)
        elif kind == "slider":
            c = wx.Slider(parent, minValue=opts["min"], maxValue=opts["max"],
                          style=wx.SL_HORIZONTAL | wx.SL_VALUE_LABEL)
            c.Bind(wx.EVT_SLIDER, changed)
        elif kind == "choice":
            c = wx.Choice(parent, choices=[label for _, label in opts["choices"]])
            c.Bind(wx.EVT_CHOICE, changed)
        elif kind == "file":
            c = wx.FilePickerCtrl(parent, wildcard=opts.get("wildcard", "*"),
                                  style=wx.FLP_OPEN | wx.FLP_USE_TEXTCTRL | wx.FLP_FILE_MUST_EXIST)
            c.Bind(wx.EVT_FILEPICKER_CHANGED, changed)
        elif kind == "dir":
            c = wx.DirPickerCtrl(parent, style=wx.DIRP_USE_TEXTCTRL)
            c.Bind(wx.EVT_DIRPICKER_CHANGED, changed)
        else:
            c = wx.TextCtrl(parent)
            c.Bind(wx.EVT_TEXT, changed)
        return c

    # ---------------------------------------------------------- values
    def _load_values(self):
        for key, (c, kind, opts) in self.controls.items():
            v = self.cfg[key]
            if kind in ("bool", "int", "slider"):
                c.SetValue(v if kind == "bool" else int(v))
            elif kind == "float":
                c.SetValue(float(v))
            elif kind == "choice":
                values = [val for val, _ in opts["choices"]]
                c.SetSelection(values.index(v) if v in values else 0)
            elif kind in ("file", "dir"):
                c.SetPath(v)
            else:
                c.SetValue(v)

    def read_values(self):
        cfg = dict(self.cfg)
        for key, (c, kind, opts) in self.controls.items():
            if kind == "choice":
                sel = c.GetSelection()
                cfg[key] = opts["choices"][max(0, sel)][0]
            elif kind in ("file", "dir"):
                cfg[key] = c.GetPath()
            else:
                cfg[key] = c.GetValue()
        self.cfg = config.normalized(cfg)
        return self.cfg

    # ---------------------------------------------------------- preview
    def _schedule_preview(self):
        if self._timer is not None and self._timer.IsRunning():
            self._timer.Restart(250)
        else:
            self._timer = wx.CallLater(250, self.update_preview)

    def _update_enabled(self, cfg):
        pixel = cfg["sample_mode"] == "pixel"
        active = {"width": "width_mm", "height": "height_mm", "percent": "scale_pct", "dpi": "dpi"}
        for mode, key in active.items():
            self.controls[key][0].Enable(not pixel and cfg["scale_mode"] == mode)
        self.controls["scale_mode"][0].Enable(not pixel)
        self.controls["coverage"][0].Enable(cfg["sample_mode"] == "coverage")
        self.controls["border_mm"][0].Enable(not pixel)
        self.controls["fit_body"][0].Enable(cfg["sample_mode"] in ("center", "coverage"))
        caps = cfg["decoupling"] and config.preset_for(cfg)["kind"] == "addressable"
        for key in ("cap_value", "cap_footprint", "cap_rotation", "cap_custom_offset"):
            self.controls[key][0].Enable(caps)
        for key in ("cap_dx", "cap_dy"):
            self.controls[key][0].Enable(caps and cfg["cap_custom_offset"])
        self.controls["sch_target"][0].Enable(cfg["gen_sch"])
        conn = cfg["connectors"]
        manual = cfg["conn_placement"] == "manual"
        matrix = config.preset_for(cfg)["kind"] != "addressable"
        for key in ("conn_in", "conn_out", "conn_footprint", "conn_placement", "conn_rotation",
                    "conn_side"):
            self.controls[key][0].Enable(conn)
        self.controls["conn_pinout"][0].Enable(conn and not matrix)
        self.controls["conn_max_pins"][0].Enable(conn and matrix)
        self.controls["conn_gap"][0].Enable(conn and not manual)
        for key in ("conn_in_x", "conn_in_y"):
            self.controls[key][0].Enable(conn and manual and cfg["conn_in"])
        for key in ("conn_out_x", "conn_out_y"):
            self.controls[key][0].Enable(conn and manual and cfg["conn_out"])

    def update_preview(self):
        cfg = self.read_values()
        self._update_enabled(cfg)
        if not cfg["image_path"]:
            self.preview.set_data(None, None, cfg)
            self.status.SetLabel("Choose an image")
            return
        try:
            with wx.BusyCursor():
                mask, layout = self.pipeline.layout(cfg)
        except Exception as e:
            self.preview.set_data(None, None, cfg)
            self.status.SetLabel("Error: %s" % e)
            return
        design = None
        if layout.count and layout.count <= 20000:
            from . import design as design_mod
            design = design_mod.build(layout, cfg, config.preset_for(cfg))
        self.preview.set_data(mask, layout, cfg, design)
        sx, sy = layout.mm_per_px
        shape = "image %.1f x %.1f mm" % (mask.width * sx, mask.height * sy)
        if layout.count:
            self.status.SetLabel("Grid %d x %d, %d LEDs | %s | green = LED 1, blue = chain" % (
                layout.rows, layout.cols, layout.count, shape))
        else:
            self.status.SetLabel("No LEDs fit - adjust threshold / invert / width / border offset")

    # ---------------------------------------------------------- actions
    def _log(self, msg):
        self.log.AppendText(msg + "\n")
        wx.Yield()

    def on_generate(self, _evt):
        cfg = self.read_values()
        config.save(self.cfg_path, cfg)
        try:
            _, layout = self.pipeline.layout(cfg)
        except Exception as e:
            wx.MessageBox(str(e), "AutoLED", wx.OK | wx.ICON_ERROR, self)
            return
        if layout.count > 3000 and wx.MessageBox(
                "%d LEDs will be generated. Continue?" % layout.count, "AutoLED",
                wx.YES_NO | wx.ICON_WARNING, self) != wx.YES:
            return
        progress = None
        if cfg["route"] and cfg["place_pcb"]:
            progress = wx.ProgressDialog("AutoLED", "Placing and routing with Freerouting...",
                                         parent=self,
                                         style=wx.PD_APP_MODAL | wx.PD_CAN_ABORT | wx.PD_ELAPSED_TIME)
        keep_going = (lambda: progress.Pulse()[0]) if progress else None
        self.btn_generate.Disable()
        try:
            generator.generate(cfg, board=self.board, board_path=self.board_path,
                               pipeline=self.pipeline, log=self._log, keep_going=keep_going)
        except Exception as e:
            self._log("ERROR: %s" % e)
            self._log(traceback.format_exc())
            wx.MessageBox(str(e), "AutoLED", wx.OK | wx.ICON_ERROR, self)
        finally:
            if progress:
                progress.Destroy()
            self.btn_generate.Enable()
        if self.board is not None and cfg["place_pcb"]:
            import pcbnew
            pcbnew.Refresh()
        self._log("Done.")

    def on_close(self, _evt):
        config.save(self.cfg_path, self.read_values())
        self.EndModal(wx.ID_CLOSE)
