"""Pipeline shared by the KiCad dialog and the command line."""

import os

from . import config, design as design_mod, exporters, grid, imaging


class Pipeline(object):
    """Caches the loaded image and mask so GUI previews stay fast."""

    def __init__(self):
        self._img_key = None
        self._img = None
        self._mask_key = None
        self._mask = None

    def mask(self, cfg):
        max_dim = None if cfg["sample_mode"] == "pixel" else int(cfg["work_res"])
        key = (cfg["image_path"], max_dim, _mtime(cfg["image_path"]))
        if key != self._img_key:
            self._img = imaging.load_gray(cfg["image_path"], max_dim)
            self._img_key = key
            self._mask_key = None
        mkey = (key, int(cfg["threshold"]), bool(cfg["invert"]), bool(cfg["use_alpha"]))
        if mkey != self._mask_key:
            self._mask = imaging.to_mask(self._img, int(cfg["threshold"]), cfg["invert"], cfg["use_alpha"])
            self._mask_key = mkey
        return self._mask

    def layout(self, cfg):
        mask = self.mask(cfg)
        return mask, grid.place(mask, cfg)


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def outline_for(layout, mask, cfg, boxes, mode=None):
    """Cut-line loops in board mm; boxes are the parts' bounds (x0, y0, x1, y1)."""
    preset = config.preset_for(cfg)
    origin = (float(cfg["origin_x"]), float(cfg["origin_y"]))
    mode = mode or cfg["outline"]
    if mode == "none" and cfg["route"]:
        mode = "rect"  # Freerouting needs a board boundary
    if mode == "rect":
        return grid.rect_outline(boxes, float(cfg["outline_margin"]))
    if mode in ("shape", "shape_only"):
        return grid.outline_loops(layout, mask, cfg, preset["body"], origin, boxes,
                                  include_parts=(mode == "shape"))
    return []


def led_boxes(design):
    """Approximate part bounds from LED bodies (used when there is no board)."""
    bw, bh = design.preset["body"]
    boxes = []
    for c in design.leds:
        w, h = (bh, bw) if 45.0 < c.rotation % 180.0 < 135.0 else (bw, bh)
        boxes.append((c.xy[0] - w / 2.0, c.xy[1] - h / 2.0, c.xy[0] + w / 2.0, c.xy[1] + h / 2.0))
    return boxes


def generate(cfg, board=None, board_path="", pipeline=None, log=print, keep_going=None):
    """Run everything enabled in cfg.  Returns a list of written file paths."""
    cfg = config.normalized(cfg)
    pipeline = pipeline or Pipeline()
    mask, layout = pipeline.layout(cfg)
    if layout.count == 0:
        raise ValueError("No LEDs fit the shape - check threshold, invert, width and border offset")
    preset = config.preset_for(cfg)
    design = design_mod.build(layout, cfg, preset)
    log("Grid %d x %d, %d LEDs" % (layout.rows, layout.cols, layout.count))
    overlaps = design_mod.find_overlaps(design.components, preset, design.side)
    if overlaps:
        log("WARNING: %d pairs of parts overlap (e.g. %s / %s). Increase the LED pitch or change "
            "the cap position / rotation." % (len(overlaps), overlaps[0][0].ref, overlaps[0][1].ref))

    out_dir = cfg["out_dir"] or (os.path.dirname(board_path) if board_path else os.getcwd())
    base = cfg["base_name"] or "leds"
    os.makedirs(out_dir, exist_ok=True)
    written = []

    def write(ext, text):
        path = os.path.join(out_dir, base + ext)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        written.append(path)
        log("Wrote " + path)

    if cfg["export_json"]:
        write(".json", exporters.to_json(layout, cfg, design))
    if cfg["export_txt"]:
        write(".txt", exporters.to_txt(layout, cfg, design))
    if cfg["export_h"]:
        write(".h", exporters.to_header(layout, cfg, design))
    if cfg["gen_sch"]:
        from . import schematic
        project = os.path.splitext(os.path.basename(board_path))[0] if board_path else base
        separate = os.path.join(out_dir, base + ".kicad_sch")
        path, root_uuid = separate, None
        if cfg["sch_target"] == "project" and board_path:
            project_sch = os.path.splitext(board_path)[0] + ".kicad_sch"
            state, existing_uuid = schematic.inspect_existing(project_sch)
            if state in ("missing", "empty", "autoled"):
                path, root_uuid = project_sch, existing_uuid
            else:
                log("NOTE: %s already has your own content, so it was not changed. The LED "
                    "schematic was written to %s. Add it in the Schematic Editor with Place -> "
                    "Hierarchical Sheet, then Update PCB from Schematic (re-link footprints by "
                    "reference)." % (os.path.basename(project_sch), separate))
        if os.path.exists(path):
            os.replace(path, path + ".bak")
        _, symbols = schematic.write(path, design, project, title="%s LED array" % preset["value"],
                                     root_uuid=root_uuid)
        written.append(path)
        log("Wrote " + path)
        lock = os.path.join(os.path.dirname(path), "~" + os.path.basename(path) + ".lck")
        if os.path.exists(lock):
            log("WARNING: %s is open in the Schematic Editor. Close it WITHOUT saving and open it "
                "again to see the LEDs (saving the open copy would overwrite them)."
                % os.path.basename(path))
        lib_path = os.path.join(out_dir, schematic.LIB + ".kicad_sym")
        schematic.write_library(lib_path, symbols)
        written.append(lib_path)
        if schematic.register_library(os.path.dirname(board_path) if board_path else out_dir, lib_path):
            log("Added %s library to sym-lib-table" % schematic.LIB)
    cut = {}

    def outline_fn(boxes):
        cut["loops"] = outline_for(layout, mask, cfg, boxes)
        return cut["loops"]

    if cfg["place_pcb"] and board is not None:
        from . import pcb
        n = pcb.apply(board, design, cfg, board_path, outline_fn)
        log("Placed %d footprints on the board" % n)
        if cfg["route"]:
            from . import router
            router.route(board, out_dir, cfg, log, keep_going)
    if cfg["export_cut"]:
        loops = cut.get("loops") or outline_for(
            layout, mask, cfg, led_boxes(design),
            mode=cfg["outline"] if cfg["outline"] != "none" else "shape_only")
        if loops:
            write("_cut.svg", exporters.to_cut_svg(loops))
            write("_cut.dxf", exporters.to_cut_dxf(loops))
        else:
            log("No cut line to export")
    return layout, design, written
