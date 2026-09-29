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
        ("connectors", "Add connectors", "bool", {}),
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
SHAPE_GRAY = 70


def render_preview(mask, layout, cfg, width, height):
    """Bitmap of the B/W mask with LED bodies drawn on top, fit into width x height."""
    bmp = wx.Bitmap(max(1, width), max(1, height))
    dc = wx.MemoryDC(bmp)
    dc.SetBackground(wx.Brush(wx.Colour(245, 245, 245)))
    dc.Clear()
    if mask is None:
        dc.SelectObject(wx.NullBitmap)
        return bmp
    g = mask.data.translate(bytes([255] + [SHAPE_GRAY] * 255))
    rgb = bytearray(3 * len(g))
    rgb[0::3] = g
    rgb[1::3] = g
    rgb[2::3] = g
    sx_mm, sy_mm = layout.mm_per_px if layout else (1.0, 1.0)
    aspect = (mask.width * sx_mm) / float(mask.height * sy_mm)
    if width / float(height) > aspect:
        dh = height
        dw = max(1, int(height * aspect))
    else:
        dw = width
        dh = max(1, int(width / aspect))
    img = wx.Image(mask.width, mask.height, bytes(rgb)).Scale(dw, dh, wx.IMAGE_QUALITY_NORMAL)
    ox, oy = (width - dw) // 2, (height - dh) // 2
    dc.DrawBitmap(wx.Bitmap(img), ox, oy)
    if layout is not None and layout.count:
        kx, ky = dw / float(mask.width), dh / float(mask.height)
        preset = config.preset_for(cfg)
        bw, bh = preset["body"]
        if 45.0 < float(cfg["rotation"]) % 180.0 < 135.0:
            bw, bh = bh, bw
        pw = max(2, int(bw / sx_mm * kx))
        ph = max(2, int(bh / sy_mm * ky))
        dc.SetPen(wx.Pen(wx.Colour(120, 0, 0)))
        dc.SetBrush(wx.Brush(LED_COLOR))
        pts = []
        centres = []
        for r, c in layout.order:
            px, py = layout.image_px(r, c)
            x, y = ox + px * kx, oy + py * ky
            pts.append((int(x), int(y)))
            centres.append((x, y, grid.led_rotation(layout, cfg, r, c)))
            dc.DrawRectangle(int(x - pw / 2.0), int(y - ph / 2.0), pw, ph)
        if pw >= 6:
            # pin-1 corner marker (top-left of the unrotated body) shows LED orientation
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.SetBrush(wx.Brush(wx.Colour(255, 230, 0)))
            base_rot = float(cfg["rotation"])
            for x, y, rot in centres:
                a = math.radians(rot - base_rot)  # body already drawn with base rotation
                dx, dy = -pw * 0.3, -ph * 0.3
                mx = x + dx * math.cos(a) + dy * math.sin(a)
                my = y - dx * math.sin(a) + dy * math.cos(a)
                dc.DrawCircle(int(mx), int(my), max(1, pw // 8))
        if len(pts) > 1 and len(pts) < 4000:
            dc.SetPen(wx.Pen(wx.Colour(30, 110, 230), 1))
            dc.DrawLines(pts)
        dc.SetPen(wx.Pen(wx.Colour(0, 160, 0), 3))
        dc.SetBrush(wx.TRANSPARENT_BRUSH)
        dc.DrawCircle(pts[0][0], pts[0][1], max(pw, ph))
    dc.SelectObject(wx.NullBitmap)
    return bmp


class PreviewPanel(wx.Panel):
    def __init__(self, parent):
        wx.Panel.__init__(self, parent, style=wx.BORDER_SUNKEN)
        self.SetMinSize((520, 420))
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.mask = None
        self.layout = None
        self.cfg = None
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_SIZE, lambda e: (self.Refresh(), e.Skip()))

    def set_data(self, mask, layout, cfg):
        self.mask, self.layout, self.cfg = mask, layout, cfg
        self.Refresh()

    def _on_paint(self, _evt):
        dc = wx.AutoBufferedPaintDC(self)
        w, h = self.GetClientSize()
        dc.DrawBitmap(render_preview(self.mask, self.layout, self.cfg, w, h), 0, 0)


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
        self.preview.set_data(mask, layout, cfg)
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
