"""Tests for the KiCad-independent parts.  Run: python3 -m unittest discover tests"""

import json
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from auto_led import config, design, exporters, grid, schematic  # noqa: E402
from auto_led.imaging import GrayImage, Mask, to_mask  # noqa: E402


def disk_mask(size=100, radius=40):
    c = size / 2.0
    data = bytes(int((x + 0.5 - c) ** 2 + (y + 0.5 - c) ** 2 <= radius ** 2)
                 for y in range(size) for x in range(size))
    return Mask(size, size, data)


def cfg(**kw):
    return config.normalized(dict(kw))


class MaskTest(unittest.TestCase):
    def test_threshold_and_invert(self):
        img = GrayImage(4, 1, bytes([0, 100, 200, 255]))
        self.assertEqual(list(to_mask(img, 128).data), [1, 1, 0, 0])
        self.assertEqual(list(to_mask(img, 128, invert=True).data), [0, 0, 1, 1])

    def test_alpha_mask(self):
        img = GrayImage(3, 1, bytes([255, 255, 255]), bytes([0, 200, 255]))
        self.assertEqual(list(to_mask(img, 128, use_alpha=True).data), [0, 1, 1])

    def test_rect_sum_and_bbox(self):
        m = disk_mask()
        self.assertEqual(m.rect_sum(0, 0, 100, 100), sum(m.data))
        self.assertEqual(m.bbox(), (10, 10, 89, 89))


class GridTest(unittest.TestCase):
    def test_center_mode_counts_and_border(self):
        m = disk_mask()
        # 100 px == 100 mm, pitch 10 -> LEDs whose centres fall in the r=40 disk
        base = grid.place(m, cfg(width_mm=100, pitch_x=10, pitch_y=10, border_mm=0))
        inset = grid.place(m, cfg(width_mm=100, pitch_x=10, pitch_y=10, border_mm=8))
        outset = grid.place(m, cfg(width_mm=100, pitch_x=10, pitch_y=10, border_mm=-8))
        self.assertGreater(base.count, 30)
        self.assertLess(inset.count, base.count)
        self.assertGreater(outset.count, base.count)
        for r, c in inset.order:  # every inset LED is >= 8 mm from the edge
            x, y = inset.x0_mm + c * 10, inset.y0_mm + r * 10
            self.assertLessEqual(((x - 50) ** 2 + (y - 50) ** 2) ** 0.5, 40 - 8 + 1)

    def test_fit_body_keeps_leds_inside(self):
        m = disk_mask()  # r = 40 mm; WS2812B body 5 x 5 mm
        loose = grid.place(m, cfg(width_mm=100, pitch_x=7, pitch_y=7, border_mm=1, fit_body=False))
        tight = grid.place(m, cfg(width_mm=100, pitch_x=7, pitch_y=7, border_mm=1, fit_body=True))
        self.assertLess(tight.count, loose.count)

        def corners_dist(lay, r, c):
            x, y = lay.x0_mm + c * 7, lay.y0_mm + r * 7
            return max(((x + dx - 50) ** 2 + (y + dy - 50) ** 2) ** 0.5
                       for dx in (-2.5, 2.5) for dy in (-2.5, 2.5))
        # every body corner is >= 1 mm inside the disk edge (1 px tolerance)
        self.assertLessEqual(max(corners_dist(tight, r, c) for r, c in tight.order), 40 - 1 + 1)
        self.assertGreater(max(corners_dist(loose, r, c) for r, c in loose.order), 40)

    def test_trimmed_and_symmetric(self):
        # odd size: disk centre and grid points fall on pixel centres -> exact symmetry
        lay = grid.place(disk_mask(101, 40), cfg(width_mm=101, pitch_x=10, pitch_y=10, border_mm=0,
                                                 fit_body=False))
        self.assertTrue(any(lay.cells[0]) and any(lay.cells[-1]))
        self.assertTrue(any(r[0] for r in lay.cells) and any(r[-1] for r in lay.cells))
        self.assertEqual(lay.cells, lay.cells[::-1])
        self.assertEqual(lay.cells, [row[::-1] for row in lay.cells])

    def test_pixel_mode(self):
        m = Mask(3, 2, bytes([1, 0, 1, 0, 0, 0]))
        lay = grid.place(m, cfg(sample_mode="pixel", pitch_x=5, pitch_y=5))
        self.assertEqual(lay.cells, [[1, 0, 1]])
        self.assertEqual(lay.board_xy(0, 2, (100, 100)), (110, 100))

    def test_coverage_mode(self):
        lay = grid.place(disk_mask(), cfg(sample_mode="coverage", coverage=100, border_mm=0,
                                          width_mm=100, pitch_x=10, pitch_y=10))
        full = grid.place(disk_mask(), cfg(sample_mode="coverage", coverage=1, border_mm=0,
                                           width_mm=100, pitch_x=10, pitch_y=10))
        self.assertLess(lay.count, full.count)


class ScaleTest(unittest.TestCase):
    def test_scale_modes(self):
        m = Mask(200, 100, bytes(200 * 100), native_size=(400, 200))  # rendered at half size
        self.assertAlmostEqual(grid.mm_per_px(m, cfg(scale_mode="width", width_mm=100)), 0.5)
        self.assertAlmostEqual(grid.mm_per_px(m, cfg(scale_mode="height", height_mm=100)), 1.0)
        # 400 native px at 96 DPI = 105.833 mm wide
        self.assertAlmostEqual(grid.mm_per_px(m, cfg(scale_mode="dpi", dpi=96)) * 200, 105.8333, 3)
        self.assertAlmostEqual(grid.mm_per_px(m, cfg(scale_mode="percent", scale_pct=50)) * 200,
                               52.9167, 3)
        with self.assertRaises(ValueError):
            grid.mm_per_px(m, cfg(scale_mode="width", width_mm=0))

    def test_led_count_follows_scale(self):
        small = grid.place(disk_mask(), cfg(scale_mode="height", height_mm=50, pitch_x=10, pitch_y=10))
        big = grid.place(disk_mask(), cfg(scale_mode="height", height_mm=200, pitch_x=10, pitch_y=10))
        self.assertGreater(big.count, 4 * small.count)


class OrderTest(unittest.TestCase):
    cells = [[1, 1, 1], [0, 0, 0], [1, 0, 1], [1, 1, 1]]

    def test_zigzag_rows_skips_empty_lines(self):
        o = grid.chain_order(self.cells, "rows", "top-left", zigzag=True)
        self.assertEqual(o, [(0, 0), (0, 1), (0, 2), (2, 2), (2, 0), (3, 0), (3, 1), (3, 2)])

    def test_no_zigzag(self):
        o = grid.chain_order(self.cells, "rows", "top-left", zigzag=False)
        self.assertEqual(o[3:5], [(2, 0), (2, 2)])

    def test_cols_from_bottom_right(self):
        o = grid.chain_order(self.cells, "cols", "bottom-right", zigzag=True)
        self.assertEqual(o[:4], [(3, 2), (2, 2), (0, 2), (0, 1)])

    def test_zigzag_rotate(self):
        m = Mask(3, 3, bytes([1, 1, 1, 1, 1, 1, 1, 1, 1]))
        on = cfg(sample_mode="pixel", zigzag=True, zigzag_rotate=True, rotation=90)
        lay = grid.place(m, on)
        self.assertEqual(lay.reversed, {(1, 0), (1, 1), (1, 2)})
        self.assertEqual(grid.led_rotation(lay, on, 0, 0), 90)
        self.assertEqual(grid.led_rotation(lay, on, 1, 0), 270)
        d = design.build(lay, on, config.preset_for(on))
        rots = {c.ref: c.rotation for c in d.components}
        self.assertEqual((rots["D1"], rots["D4"], rots["D7"]), (90, 270, 90))
        # caps are not flipped: same rotation and same side for every LED, so a
        # flipped row's caps cannot collide with the neighbouring row's caps
        self.assertEqual((rots["C1"], rots["C4"]), (180, 180))
        caps = {c.ref: c.xy for c in d.components if c.kind == "cap"}
        leds = {c.ref: c.xy for c in d.leds}
        off1 = (caps["C1"][0] - leds["D1"][0], caps["C1"][1] - leds["D1"][1])
        off4 = (caps["C4"][0] - leds["D4"][0], caps["C4"][1] - leds["D4"][1])
        self.assertAlmostEqual(off1[0], off4[0])
        self.assertAlmostEqual(off1[1], off4[1])
        off = cfg(sample_mode="pixel", zigzag=True, zigzag_rotate=False, rotation=90)
        self.assertEqual(grid.led_rotation(grid.place(m, off), off, 1, 0), 90)
        nozz = cfg(sample_mode="pixel", zigzag=False, zigzag_rotate=True)
        self.assertEqual(grid.place(m, nozz).reversed, set())

    def test_old_config_migrates(self):
        c = cfg(order="cols_serpentine")
        self.assertEqual((c["order"], c["zigzag"]), ("cols", True))
        c = cfg(order="rows", zigzag=False)
        self.assertEqual((c["order"], c["zigzag"]), ("rows", False))


class OutputTest(unittest.TestCase):
    def setUp(self):
        self.cfg = cfg(width_mm=100, pitch_x=10, pitch_y=10, border_mm=2)
        self.lay = grid.place(disk_mask(), self.cfg)
        self.d = design.build(self.lay, self.cfg, config.preset_for(self.cfg))

    def test_exports_consistent(self):
        data = json.loads(exporters.to_json(self.lay, self.cfg, self.d))
        self.assertEqual(data["count"], self.lay.count)
        self.assertEqual(data["mask"], self.lay.cells)
        self.assertEqual(data["leds"][0]["ref"], "D1")
        txt = exporters.to_txt(self.lay, self.cfg, self.d)
        self.assertEqual(txt.count("#") - txt.count("# "), sum(map(sum, self.lay.cells)))
        h = exporters.to_header(self.lay, self.cfg, self.d)
        self.assertIn("#define LED_COUNT %d" % self.lay.count, h)
        self.assertIn("#define LED_ZIGZAG 1", h)
        self.assertEqual(h.count("{"), h.count("}"))

    def test_chain_nets(self):
        leds = self.d.leds
        self.assertEqual(leds[0].net_of("4"), "DIN")        # WS2812B pin 4 = DIN
        self.assertEqual(leds[0].net_of("2"), leds[1].net_of("4"))
        self.assertEqual(leds[-1].net_of("2"), "DOUT")
        self.assertEqual(len([c for c in self.d.components if c.kind == "cap"]), len(leds))

    def test_matrix_nets(self):
        c = cfg(preset="LED 0805", width_mm=100, pitch_x=10, pitch_y=10)
        d = design.build(self.lay, c, config.preset_for(c))
        nets = d.nets()
        self.assertTrue(any(n.startswith("ROW") for n in nets))
        self.assertTrue(any(n.startswith("COL") for n in nets))

    def test_schematic_and_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "leds.kicad_sch")
            _, syms = schematic.write(path, self.d, "proj")
            text = open(path).read()
            self.assertEqual(text.count("("), text.count(")"))
            self.assertEqual(len(re.findall(r'\(reference "D\d+"\)', text)), self.lay.count)
            lib = os.path.join(tmp, "AutoLED.kicad_sym")
            schematic.write_library(lib, syms)
            schematic.write_library(lib, [schematic.cap_symbol(), schematic.conn_symbol(7)])
            names = set(schematic._top_level_blocks(open(lib).read()))
            self.assertTrue({"WS2812B", "C", "Conn_01x03", "Conn_01x07"} <= names)
            self.assertTrue(schematic.register_library(tmp, lib))
            self.assertFalse(schematic.register_library(tmp, lib))


class OutlineTest(unittest.TestCase):
    def test_shape_outline_encloses_leds(self):
        c = cfg(width_mm=100, pitch_x=10, pitch_y=10, border_mm=2, outline_margin=2)
        m = disk_mask()
        lay = grid.place(m, c)
        loops = grid.outline_loops(lay, m, c, (5, 5), (0, 0))
        self.assertEqual(len(loops), 1)
        xs = [p[0] for p in loops[0]]
        span = max(xs) - min(xs)
        self.assertAlmostEqual(span, 84, delta=3)  # disk diameter 80 + 2 * margin


class CutLineTest(unittest.TestCase):
    def test_shape_only_ignores_parts_and_exports(self):
        c = cfg(width_mm=100, pitch_x=10, pitch_y=10, border_mm=-20, outline_margin=0)
        m = disk_mask()
        lay = grid.place(m, c)  # LEDs reach 20 mm outside the disk
        with_parts = grid.outline_loops(lay, m, c, (5, 5), (0, 0), include_parts=True)
        shape_only = grid.outline_loops(lay, m, c, (5, 5), (0, 0), include_parts=False)
        def span(loops):  # parts not touching the shape form separate islands
            xs = [p[0] for loop in loops for p in loop]
            return max(xs) - min(xs)
        self.assertEqual(len(shape_only), 1)
        self.assertAlmostEqual(span(shape_only), 80, delta=2)
        self.assertGreater(span(with_parts), span(shape_only) + 20)
        svg = exporters.to_cut_svg(shape_only)
        self.assertIn('width="', svg)
        self.assertEqual(svg.count("<path"), 1)
        dxf = exporters.to_cut_dxf(shape_only)
        self.assertEqual(dxf.count("\nLINE\n"), len(shape_only[0]))
        self.assertTrue(dxf.rstrip().endswith("EOF"))


if __name__ == "__main__":
    unittest.main()
