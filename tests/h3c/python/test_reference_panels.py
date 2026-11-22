import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from h3_continuity import reference_panels


def picture(width, height, gutters_x=(), gutters_y=(), gutter=240, seed=1):
    pixels = np.random.default_rng(seed).integers(0, 200, (height, width, 3), dtype=np.uint8)
    for x0, x1, y0, y1 in gutters_x:
        pixels[y0:y1, x0:x1] = gutter
    for y0, y1, x0, x1 in gutters_y:
        pixels[y0:y1, x0:x1] = gutter
    return pixels


class ReferencePanelsTest(unittest.TestCase):
    def find(self, pixels):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'sheet.png'
            Image.fromarray(pixels).save(path)
            return reference_panels.panels(path)

    def test_a_two_by_two_location_sheet_gives_four_views_in_reading_order(self):
        boxes = self.find(picture(3000, 1600, [(1490, 1512, 0, 1600)], [(790, 810, 0, 3000)]))
        self.assertEqual(len(boxes), 4)
        self.assertEqual([(x > 1500, y > 800) for x, y, _, _ in boxes], [(False, False), (True, False), (False, True), (True, True)])
        for x, y, w, h in boxes:
            self.assertTrue(x + w <= 1490 or x >= 1512, 'a view must not include the vertical gutter')
            self.assertTrue(y + h <= 790 or y >= 810, 'a view must not include the horizontal gutter')
            self.assertGreater(w, 1400)
            self.assertGreater(h, 700)

    def test_an_uneven_sheet_splits_each_row_on_its_own(self):
        top = [(990, 1010, 0, 790)]
        bottom = [(1490, 1510, 810, 1600)]
        boxes = self.find(picture(3000, 1600, top + [(1990, 2010, 0, 790)] + bottom, [(790, 810, 0, 3000)], gutter=15))
        self.assertEqual(len(boxes), 5)

    def test_single_pictures_with_flat_bands_or_edges_are_not_sheets(self):
        sky = picture(3000, 1600)
        sky[:600] = 180
        border = picture(3000, 1600)
        border[:, :40] = 255
        border[:30] = 255
        for pixels in (picture(3000, 1600), sky, border):
            with self.subTest():
                self.assertEqual(self.find(pixels), [])


if __name__ == '__main__':
    unittest.main()
