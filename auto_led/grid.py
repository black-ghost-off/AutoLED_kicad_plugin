"""Fit a 2D LED grid onto a mask and compute chain order / board outline."""

import math


class Layout(object):
    """Result of placing LEDs on a mask.

    cells[r][c] is 1 where an LED exists.  Board position of cell (r, c) is
    origin + (c * pitch_x, r * pitch_y).  Image position (mm, from the image
    top-left) is (x0_mm + c * pitch_x, y0_mm + r * pitch_y).
    """

    def __init__(self, cells, pitch_x, pitch_y, x0_mm, y0_mm, mm_per_px):
        self.cells = cells
        self.rows = len(cells)
        self.cols = len(cells[0]) if cells else 0
        self.pitch_x = pitch_x
        self.pitch_y = pitch_y
        self.x0_mm = x0_mm
        self.y0_mm = y0_mm
        self.mm_per_px = mm_per_px  # (sx, sy)
        self.order = []  # [(r, c)] in chain / index order
        self.reversed = set()  # (r, c) on zigzag lines that run backwards
        self.index = [[-1] * self.cols for _ in range(self.rows)]

    @property
    def count(self):
        return len(self.order)

    def set_order(self, order, reversed_cells=()):
        self.order = order
        self.reversed = set(reversed_cells)
        self.index = [[-1] * self.cols for _ in range(self.rows)]
        for i, (r, c) in enumerate(order):
            self.index[r][c] = i

    def board_xy(self, r, c, origin=(0.0, 0.0)):
        return origin[0] + c * self.pitch_x, origin[1] + r * self.pitch_y

    def image_px(self, r, c):
        sx, sy = self.mm_per_px
        return (self.x0_mm + c * self.pitch_x) / sx, (self.y0_mm + r * self.pitch_y) / sy


def _trim(cells, xs, ys):
    rows = [i for i, row in enumerate(cells) if any(row)]
    if not rows:
        return [], xs[:0], ys[:0]
    cols = [j for j in range(len(cells[0])) if any(cells[i][j] for i in rows)]
    r0, r1, c0, c1 = rows[0], rows[-1], cols[0], cols[-1]
    return ([row[c0:c1 + 1] for row in cells[r0:r1 + 1]], xs[c0:c1 + 1], ys[r0:r1 + 1])


def mm_per_px(mask, cfg):
    """Size of one mask pixel in mm, from the scale settings."""
    mode = cfg.get("scale_mode", "width")
    native_w = float(mask.native_size[0]) or mask.width
    if mode == "height":
        size = float(cfg["height_mm"])
        s = size / mask.height
    elif mode == "percent":
        size = float(cfg["scale_pct"])
        s = native_w * 25.4 / 96.0 * size / 100.0 / mask.width
    elif mode == "dpi":
        size = float(cfg["dpi"])
        s = native_w * 25.4 / size / mask.width if size > 0 else 0
    else:
        size = float(cfg["width_mm"])
        s = size / mask.width
    if size <= 0 or s <= 0:
        raise ValueError("Image scale must be positive")
    return s


def place(mask, cfg):
    """Build a Layout for mask using cfg (see config.DEFAULTS)."""
    px, py = float(cfg["pitch_x"]), float(cfg["pitch_y"])
    if px <= 0 or py <= 0:
        raise ValueError("LED pitch must be positive")
    mode = cfg["sample_mode"]

    if mode == "pixel":
        w = mask.width
        cells = [list(mask.data[y * w:(y + 1) * w]) for y in range(mask.height)]
        xs = [(c + 0.5) * px for c in range(mask.width)]
        ys = [(r + 0.5) * py for r in range(mask.height)]
        cells, xs, ys = _trim(cells, xs, ys)
        if not cells:
            return Layout([], px, py, 0.0, 0.0, (px, py))
        return _finish(Layout(cells, px, py, xs[0], ys[0], (px, py)), cfg)

    s = mm_per_px(mask, cfg)
    bb = mask.bbox()
    if bb is None:
        return Layout([], px, py, 0.0, 0.0, (s, s))

    border = float(cfg["border_mm"])
    r_px = abs(border) / s
    grow = abs(border) if border < 0 else 0.0
    bx0 = bb[0] * s - grow
    bx1 = (bb[2] + 1) * s + grow
    by0 = bb[1] * s - grow
    by1 = (bb[3] + 1) * s + grow
    cx = (bx0 + bx1) / 2.0 + float(cfg["grid_dx"])
    cy = (by0 + by1) / 2.0 + float(cfg["grid_dy"])
    nx = int((bx1 - bx0) / px) + 3
    ny = int((by1 - by0) / py) + 3
    xs = [cx + (i - (nx - 1) / 2.0) * px for i in range(nx)]
    ys = [cy + (j - (ny - 1) / 2.0) * py for j in range(ny)]

    min_cov = float(cfg["coverage"]) / 100.0
    hw, hh = px / 2.0 / s, py / 2.0 / s

    def ok(xm, ym):
        fx, fy = xm / s, ym / s
        ix, iy = int(math.floor(fx)), int(math.floor(fy))
        if mode == "coverage":
            x0, x1 = int(round(fx - hw)), int(round(fx + hw))
            y0, y1 = int(round(fy - hh)), int(round(fy + hh))
            area = max(1, (x1 - x0) * (y1 - y0))
            if mask.rect_sum(x0, y0, x1, y1) < min_cov * area:
                return False
            return border <= 0 or mask.disk_all_inside(ix, iy, r_px)
        inside = mask.at(ix, iy)
        if border > 0:
            return bool(inside) and mask.disk_all_inside(ix, iy, r_px)
        if border < 0:
            return bool(inside) or mask.disk_any_inside(ix, iy, r_px)
        return bool(inside)

    cells = [[1 if ok(x, y) else 0 for x in xs] for y in ys]
    cells, xs, ys = _trim(cells, xs, ys)
    if not cells:
        return Layout([], px, py, 0.0, 0.0, (s, s))
    return _finish(Layout(cells, px, py, xs[0], ys[0], (s, s)), cfg)


def _finish(layout, cfg):
    order, back = [], []
    for line, is_reversed in chain_lines(layout.cells, cfg["order"], cfg["start_corner"],
                                         cfg["zigzag"]):
        order.extend(line)
        if is_reversed:
            back.extend(line)
    layout.set_order(order, back)
    return layout


def led_rotation(layout, cfg, r, c):
    """Rotation of the LED at (r, c): the global rotation, plus 180 deg on
    backward zigzag lines when zigzag_rotate is on (keeps DIN->DOUT pointing
    along the chain)."""
    rot = float(cfg["rotation"])
    if cfg.get("zigzag_rotate") and cfg.get("zigzag") and (r, c) in layout.reversed:
        rot += 180.0
    return rot % 360.0


def chain_order(cells, order="rows", start_corner="top-left", zigzag=True):
    """List of (r, c) in the order LEDs are numbered / daisy-chained."""
    return [rc for line, _ in chain_lines(cells, order, start_corner, zigzag) for rc in line]


def chain_lines(cells, order="rows", start_corner="top-left", zigzag=True):
    """[(line, is_reversed)]: the chain split into rows / columns.

    order is "rows" or "cols".  With zigzag every other line runs backwards
    (serpentine); only lines that contain LEDs count, so empty lines inside
    the shape do not break the zig-zag.
    """
    if not cells:
        return []
    R, C = len(cells), len(cells[0])
    rev_r = start_corner.startswith("bottom")
    rev_c = start_corner.endswith("right")
    rows = list(range(R))[::-1] if rev_r else list(range(R))
    cols = list(range(C))[::-1] if rev_c else list(range(C))
    by_cols = order.startswith("cols")
    serp = bool(zigzag)
    outer, inner = (cols, rows) if by_cols else (rows, cols)
    result = []
    line_no = 0
    for a in outer:
        line = [(b, a) if by_cols else (a, b) for b in inner]
        line = [(r, c) for r, c in line if cells[r][c]]
        if not line:
            continue
        backwards = serp and line_no % 2 == 1
        if backwards:
            line.reverse()
        result.append((line, backwards))
        line_no += 1
    return result


# ---------------------------------------------------------------- outline

def _simplify(points, tol):
    """Douglas-Peucker on an open polyline."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = points[a]
        bx, by = points[b]
        dx, dy = bx - ax, by - ay
        norm = math.hypot(dx, dy) or 1e-12
        best, idx = -1.0, -1
        for i in range(a + 1, b):
            x, y = points[i]
            d = abs(dy * (x - ax) - dx * (y - ay)) / norm
            if d > best:
                best, idx = d, i
        if idx > 0 and best > tol:
            keep[idx] = True
            stack.append((a, idx))
            stack.append((idx, b))
    return [p for p, k in zip(points, keep) if k]


def _simplify_closed(loop, tol):
    """Douglas-Peucker on a closed loop (split at the point farthest from loop[0])."""
    x0, y0 = loop[0]
    k = max(range(len(loop)), key=lambda i: (loop[i][0] - x0) ** 2 + (loop[i][1] - y0) ** 2)
    first = _simplify(loop[:k + 1], tol)
    second = _simplify(loop[k:] + [loop[0]], tol)
    return first[:-1] + second[:-1]


# marching squares: case -> segments between cell edges (T, R, B, L)
_MS = {
    1: [("L", "B")], 2: [("B", "R")], 3: [("L", "R")], 4: [("T", "R")],
    5: [("L", "B"), ("T", "R")], 6: [("T", "B")], 7: [("T", "L")],
    8: [("T", "L")], 9: [("T", "B")], 10: [("T", "L"), ("B", "R")],
    11: [("T", "R")], 12: [("L", "R")], 13: [("R", "B")], 14: [("L", "B")],
}


def _contours(field, w, h):
    """Closed loops (in doubled field coordinates) around set cells of field."""
    def v(i, j):
        return field[j][i] if 0 <= i < w and 0 <= j < h else 0

    adj = {}

    def link(p, q):
        adj.setdefault(p, []).append(q)
        adj.setdefault(q, []).append(p)

    for j in range(-1, h):
        for i in range(-1, w):
            case = v(i, j) * 8 + v(i + 1, j) * 4 + v(i + 1, j + 1) * 2 + v(i, j + 1)
            if case in (0, 15):
                continue
            pts = {"T": (2 * i + 1, 2 * j), "R": (2 * i + 2, 2 * j + 1),
                   "B": (2 * i + 1, 2 * j + 2), "L": (2 * i, 2 * j + 1)}
            for a, b in _MS[case]:
                link(pts[a], pts[b])

    loops = []
    seen = set()
    for start in adj:
        if start in seen:
            continue
        loop = [start]
        seen.add(start)
        prev, cur = None, start
        while True:
            nxt = [q for q in adj[cur] if q != prev]
            if not nxt:
                break
            prev, cur = cur, nxt[0]
            if cur == start:
                break
            if cur in seen:
                break
            seen.add(cur)
            loop.append(cur)
        if len(loop) >= 3:
            loops.append(loop)
    return loops


def outline_loops(layout, mask, cfg, led_body, origin, boxes=(), include_parts=True):
    """Board outline loops (lists of (x, y) mm in board coordinates).

    The outline is the image shape grown by outline_margin (not in pixel mode)
    united with every LED body and every box (x0, y0, x1, y1) of boxes, all
    grown by outline_margin.
    """
    if not layout.count:
        return []
    margin = max(0.0, float(cfg["outline_margin"]))
    bw, bh = led_body
    rot = float(cfg["rotation"]) % 180.0
    if 45.0 < rot < 135.0:
        bw, bh = bh, bw
    ox, oy = origin
    # everything below is in board mm
    pts = [layout.board_xy(r, c, origin) for r, c in layout.order]
    x0 = min(p[0] for p in pts) - bw / 2.0 - margin
    x1 = max(p[0] for p in pts) + bw / 2.0 + margin
    y0 = min(p[1] for p in pts) - bh / 2.0 - margin
    y1 = max(p[1] for p in pts) + bh / 2.0 + margin

    for bx0, by0, bx1, by1 in boxes:
        x0, y0 = min(x0, bx0 - margin), min(y0, by0 - margin)
        x1, y1 = max(x1, bx1 + margin), max(y1, by1 + margin)

    use_shape = cfg["sample_mode"] != "pixel" and mask is not None
    sx, sy = layout.mm_per_px
    # board -> image px
    dxm, dym = layout.x0_mm - ox, layout.y0_mm - oy
    if use_shape:
        bb = mask.bbox()
        x0 = min(x0, bb[0] * sx - dxm - margin)
        x1 = max(x1, (bb[2] + 1) * sx - dxm + margin)
        y0 = min(y0, bb[1] * sy - dym - margin)
        y1 = max(y1, (bb[3] + 1) * sy - dym + margin)

    g = max(0.1, max(x1 - x0, y1 - y0) / 350.0)
    if use_shape:
        g = max(g, sx)
    w = int(math.ceil((x1 - x0) / g)) + 1
    h = int(math.ceil((y1 - y0) / g)) + 1
    field = [[0] * w for _ in range(h)]

    half_w, half_h = bw / 2.0, bh / 2.0
    rects = [(px - half_w, py - half_h, px + half_w, py + half_h) for px, py in pts] + list(boxes)
    if not include_parts and mask is not None and cfg["sample_mode"] != "pixel":
        rects = []
    for (rx0, ry0, rx1, ry1) in rects:
        i0 = max(0, int(math.ceil((rx0 - margin - x0) / g)))
        i1 = min(w - 1, int(math.floor((rx1 + margin - x0) / g)))
        j0 = max(0, int(math.ceil((ry0 - margin - y0) / g)))
        j1 = min(h - 1, int(math.floor((ry1 + margin - y0) / g)))
        for j in range(j0, j1 + 1):
            row = field[j]
            for i in range(i0, i1 + 1):
                row[i] = 1

    if use_shape:
        r_px = margin / sx
        for j in range(h):
            row = field[j]
            iy = int(math.floor((y0 + j * g + dym) / sy))
            for i in range(w):
                if row[i]:
                    continue
                ix = int(math.floor((x0 + i * g + dxm) / sx))
                if mask.at(ix, iy) or (r_px > 0 and mask.disk_any_inside(ix, iy, r_px)):
                    row[i] = 1

    loops = []
    min_area = (2 * g) ** 2
    for loop in _contours(field, w, h):
        mm = [(x0 + X * g / 2.0, y0 + Y * g / 2.0) for X, Y in loop]
        area = 0.5 * abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(mm, mm[1:] + mm[:1])))
        if area < min_area:
            continue
        simple = _simplify_closed(mm, g * 0.5)
        if len(simple) >= 3:
            loops.append(simple)
    return loops


def rect_outline(boxes, margin):
    """Rectangle around all boxes (x0, y0, x1, y1), grown by margin."""
    x0 = min(b[0] for b in boxes) - margin
    y0 = min(b[1] for b in boxes) - margin
    x1 = max(b[2] for b in boxes) + margin
    y1 = max(b[3] for b in boxes) + margin
    return [[(x0, y0), (x1, y0), (x1, y1), (x0, y1)]]
