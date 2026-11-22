"""Unit tests for the absorbed PixelAI H3 Face Size Fade node.

The node is a faithful port of PixelAIH3FaceSizeFade from
ComfyUI-H3-FaceFix-PixelAILabs (MIT); these tests pin the weight math so a
future edit cannot silently change the fade ramp the shipped workflow relies
on. The module is stdlib-only, so no ComfyUI mocks are needed.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from h3_facefix import PixelAIH3FaceSizeFade, _smoothstep  # noqa: E402


def transform(boxes, src_h=1080, weights=None):
    t = {"boxes": boxes, "src_size": (1920, src_h)}
    if weights is not None:
        t["weights"] = weights
    return t


class TestFaceSizeFade(unittest.TestCase):
    def setUp(self):
        self.node = PixelAIH3FaceSizeFade()

    def run_node(self, t, **overrides):
        kwargs = dict(
            full_fix_below_px=110,
            no_fix_above_px=180,
            crop_factor=2.5,
            reference_height=1080,
        )
        kwargs.update(overrides)
        return self.node.run(t, **kwargs)

    def test_small_faces_get_full_weight(self):
        # face height = box[3] / crop_factor; box[3]=200 -> 80px face < 110 -> f=1
        out, report = self.run_node(transform([[0, 0, 100, 200]]))
        self.assertAlmostEqual(out["weights"][0], 1.0)
        self.assertIn("full fix 1", report)

    def test_large_faces_untouched(self):
        # box[3]=1000 -> 400px face > 180 -> f=0
        out, report = self.run_node(transform([[0, 0, 100, 1000]]))
        self.assertAlmostEqual(out["weights"][0], 0.0)
        self.assertIn("untouched 1", report)

    def test_mid_range_fades_smoothly(self):
        # box[3]=725 -> 290px? no: 725/2.5=290 >180 -> 0. pick box[3]=600 -> 240px still >180.
        # face = 600/2.5 = 240 -> above ramp -> 0. Use box[3]=400 -> 160px, inside 110-180.
        out, _ = self.run_node(transform([[0, 0, 100, 400]]))
        w = out["weights"][0]
        self.assertGreater(w, 0.0)
        self.assertLess(w, 1.0)

    def test_weights_multiply_existing(self):
        out, _ = self.run_node(
            transform([[0, 0, 100, 200], [0, 0, 100, 1000]], weights=[0.5, 0.5])
        )
        self.assertAlmostEqual(out["weights"][0], 0.5)
        self.assertAlmostEqual(out["weights"][1], 0.0)

    def test_missing_weights_default_to_one(self):
        out, _ = self.run_node(transform([[0, 0, 100, 200]]))
        self.assertAlmostEqual(out["weights"][0], 1.0)

    def test_reference_height_scales_ramp(self):
        # 4K source: ramp doubles (220->360), a 160px-equivalent face... box[3]=400 -> face=160
        # at src_h=2160 scale=2 -> ramp 220-360, face 160 < 220 -> full fix
        out, _ = self.run_node(transform([[0, 0, 100, 400]], src_h=2160))
        self.assertAlmostEqual(out["weights"][0], 1.0)
        # same face at 720p: scale=720/1080=0.667 -> ramp ~73-120, face 160 > 120 -> untouched
        out2, _ = self.run_node(transform([[0, 0, 100, 400]], src_h=720))
        self.assertAlmostEqual(out2["weights"][0], 0.0)

    def test_zero_reference_height_uses_source_pixels(self):
        out, _ = self.run_node(transform([[0, 0, 100, 400]], src_h=9999), reference_height=0)
        # ramp stays 110-180 on raw face px: face=160 -> mid fade
        self.assertGreater(out["weights"][0], 0.0)
        self.assertLess(out["weights"][0], 1.0)

    def test_smoothstep_bounds(self):
        self.assertEqual(_smoothstep(-1), 0.0)
        self.assertEqual(_smoothstep(0), 0.0)
        self.assertEqual(_smoothstep(1), 1.0)
        self.assertEqual(_smoothstep(2), 1.0)
        self.assertAlmostEqual(_smoothstep(0.5), 0.5)

    def test_input_schema_shape(self):
        schema = PixelAIH3FaceSizeFade.INPUT_TYPES()
        self.assertIn("transform", schema["required"])
        self.assertEqual(PixelAIH3FaceSizeFade.RETURN_TYPES, ("H3FACEXFORM", "STRING"))


if __name__ == "__main__":
    unittest.main()
