"""Load SVG / PNG / BMP / JPG images and turn them into a black & white mask.

Uses wxPython (always present inside KiCad).  Outside KiCad it falls back to
Pillow, and to cairosvg for SVG files.
"""

import itertools
import math
import operator
import os

_wx_app = None


class GrayImage(object):
    """8-bit grayscale image with optional alpha, both as flat bytes."""

    def __init__(self, width, height, gray, alpha=None, native_size=None):
        self.width = width
        self.height = height
        self.gray = gray
        self.alpha = alpha
        # size before resampling: SVG user units or raster pixels (96 per inch)
        self.native_size = native_size or (width, height)


class Mask(object):
    """Binary mask (1 = shape / LED area) with an integral image for fast area sums."""

    def __init__(self, width, height, data, native_size=None):
        self.width = width
        self.height = height
        self.data = data  # bytes of 0/1, row major
        self.native_size = native_size or (width, height)
        self._integral = None
        self._disks = {}

    def at(self, x, y):
        if 0 <= x < self.width and 0 <= y < self.height:
            return self.data[y * self.width + x]
        return 0

    @property
    def integral(self):
        if self._integral is None:
            w, h = self.width, self.height
            stride = w + 1
            ii = [0] * (stride * (h + 1))
            for y in range(h):
                prev = y * stride
                base = prev + stride
                acc = itertools.accumulate(self.data[y * w:(y + 1) * w])
                ii[base + 1:base + stride] = map(operator.add, ii[prev + 1:prev + stride], acc)
            self._integral = ii
        return self._integral

    def rect_sum(self, x0, y0, x1, y1):
        """Number of set pixels in [x0, x1) x [y0, y1), clipped to the image."""
        x0 = max(0, min(self.width, x0))
        x1 = max(0, min(self.width, x1))
        y0 = max(0, min(self.height, y0))
        y1 = max(0, min(self.height, y1))
        if x1 <= x0 or y1 <= y0:
            return 0
        ii = self.integral
        s = self.width + 1
        return ii[y1 * s + x1] - ii[y0 * s + x1] - ii[y1 * s + x0] + ii[y0 * s + x0]

    def bbox(self):
        """(x0, y0, x1, y1) inclusive bounds of set pixels, or None."""
        w = self.width
        rows = [y for y in range(self.height) if 1 in self.data[y * w:(y + 1) * w]]
        if not rows:
            return None
        cols = [x for x in range(w) if self.rect_sum(x, rows[0], x + 1, rows[-1] + 1)]
        return cols[0], rows[0], cols[-1], rows[-1]

    def _disk(self, r):
        r = int(math.ceil(r))
        if r not in self._disks:
            self._disks[r] = [(dx, dy) for dy in range(-r, r + 1) for dx in range(-r, r + 1)
                              if dx * dx + dy * dy <= r * r]
        return r, self._disks[r]

    def disk_all_inside(self, cx, cy, radius):
        r, offsets = self._disk(radius)
        side = 2 * r + 1
        if self.rect_sum(cx - r, cy - r, cx + r + 1, cy + r + 1) == side * side:
            return True
        at = self.at
        return all(at(cx + dx, cy + dy) for dx, dy in offsets)

    def disk_any_inside(self, cx, cy, radius):
        r, offsets = self._disk(radius)
        if self.rect_sum(cx - r, cy - r, cx + r + 1, cy + r + 1) == 0:
            return False
        at = self.at
        return any(at(cx + dx, cy + dy) for dx, dy in offsets)


def _target_size(w0, h0, max_dim):
    if not max_dim or w0 <= 0 or h0 <= 0:
        return max(1, int(round(w0))), max(1, int(round(h0)))
    k = float(max_dim) / max(w0, h0)
    return max(1, int(round(w0 * k))), max(1, int(round(h0 * k)))


def _ensure_wx_app():
    global _wx_app
    import wx
    if wx.GetApp() is None:
        _wx_app = wx.App(False)
    return wx


def _load_wx(path, max_dim):
    wx = _ensure_wx_app()
    if path.lower().endswith(".svg"):
        import wx.svg
        svg = wx.svg.SVGimage.CreateFromFile(path)
        if svg.width <= 0 or svg.height <= 0:
            raise ValueError("SVG has no usable width/height: %s" % path)
        native = (svg.width, svg.height)
        w, h = _target_size(svg.width, svg.height, max_dim)
        img = svg.ConvertToScaledBitmap(wx.Size(w, h)).ConvertToImage()
    else:
        img = wx.Image(path)
        if not img.IsOk():
            raise ValueError("Cannot read image: %s" % path)
        native = (img.GetWidth(), img.GetHeight())
        w, h = _target_size(img.GetWidth(), img.GetHeight(), max_dim)
        if (w, h) != (img.GetWidth(), img.GetHeight()):
            quality = wx.IMAGE_QUALITY_NEAREST if w > img.GetWidth() else wx.IMAGE_QUALITY_HIGH
            img = img.Scale(w, h, quality)
    if img.HasMask():
        img.InitAlpha()
    w, h = img.GetWidth(), img.GetHeight()
    gray = bytes(img.ConvertToGreyscale().GetData())[0::3]
    alpha = bytes(img.GetAlpha()) if img.HasAlpha() else None
    return GrayImage(w, h, gray, alpha, native)


def _load_pil(path, max_dim):
    from PIL import Image
    if path.lower().endswith(".svg"):
        import io
        import cairosvg  # optional dependency for CLI use outside KiCad
        png = cairosvg.svg2png(url=path)
        im = Image.open(io.BytesIO(png))
        native = im.size
        if max_dim:
            w, h = _target_size(im.width, im.height, max_dim)
            png = cairosvg.svg2png(url=path, output_width=w, output_height=h)
            im = Image.open(io.BytesIO(png))
    else:
        im = Image.open(path)
        native = im.size
        w, h = _target_size(im.width, im.height, max_dim)
        if (w, h) != im.size:
            im = im.resize((w, h), Image.NEAREST if w > im.width else Image.LANCZOS)
    im = im.convert("RGBA")
    alpha = im.getchannel("A").tobytes()
    gray = im.convert("L").tobytes()
    return GrayImage(im.width, im.height, gray, alpha, native)


def load_gray(path, max_dim=None):
    """Load an image as grayscale, scaled so its longest side is max_dim.

    max_dim=None keeps the native resolution (used by pixel mode).
    Transparent pixels are composited onto white.
    """
    if not path or not os.path.isfile(path):
        raise ValueError("Image file not found: %r" % path)
    try:
        img = _load_wx(path, max_dim)
    except ImportError:
        img = _load_pil(path, max_dim)
    if img.alpha is not None and img.alpha.count(255) != len(img.alpha):
        img.gray = bytes(255 - ((255 - g) * a) // 255 for g, a in zip(img.gray, img.alpha))
    return img


def to_mask(img, threshold=128, invert=False, use_alpha=False):
    """Black (darker than threshold) becomes 1, unless inverted.

    With use_alpha, opaque pixels (alpha >= threshold) become 1 instead.
    """
    if use_alpha and img.alpha is not None:
        table = bytes(int((v >= threshold) != invert) for v in range(256))
        return Mask(img.width, img.height, img.alpha.translate(table), img.native_size)
    table = bytes(int((v < threshold) != invert) for v in range(256))
    return Mask(img.width, img.height, img.gray.translate(table), img.native_size)
