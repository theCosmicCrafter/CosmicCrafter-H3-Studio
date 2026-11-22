import unittest

import numpy as np

from h3_continuity import check_frames

H, W = 136, 240


def gray(values):
    return np.repeat(np.clip(values, 0, 255).astype(np.uint8)[..., None], 3, axis=2)


def flat():
    return gray(np.full((H, W), 120.0))


def gradient():
    y, x = np.mgrid[0:H, 0:W]
    return gray(60 + 0.5 * x + 0.3 * y)


def noisy(amplitude=20.0, seed=0):
    rng = np.random.default_rng(seed)
    base = np.full((H, W), 120.0)
    # 3 px blocks put the energy in the 2-8 px band
    blocks = rng.normal(0, amplitude, (H // 3 + 1, W // 3 + 1)).repeat(3, 0).repeat(3, 1)[:H, :W]
    return gray(base + blocks)


def blurred(image):
    out = image.astype(np.float64)
    for axis in (0, 1):
        out = (np.roll(out, 1, axis) + out + np.roll(out, -1, axis)) / 3
    return out.astype(np.uint8)


class TextureTest(unittest.TestCase):
    def test_flat_and_linear_gradient_have_almost_no_texture(self):
        for image in (flat(), gradient()):
            self.assertLess(check_frames.texture(image).max(), 0.05)

    def test_fine_noise_lands_in_the_fine_band(self):
        fine, middle, coarse = check_frames.texture(noisy())
        self.assertGreater(fine, 3 * coarse)
        self.assertGreater(fine, middle)

    def test_blur_lowers_the_fine_band(self):
        image = noisy()
        self.assertLess(check_frames.texture(blurred(image))[0], 0.8 * check_frames.texture(image)[0])

    def test_texture_mean_averages_frames(self):
        a, b = noisy(seed=1), noisy(seed=2)
        np.testing.assert_allclose(check_frames.texture_mean([a, b]),
                                   (check_frames.texture(a) + check_frames.texture(b)) / 2)


class WordsTest(unittest.TestCase):
    lab = np.array([50.0, 0.0, 0.0])

    def words(self, fine, lab=None):
        return check_frames.drift_words(self.lab if lab is None else lab, self.lab,
                                        np.array([fine, 1.0, 1.0]), np.array([1.0, 1.0, 1.0]))

    def test_grainier_above_the_step_only(self):
        self.assertEqual(self.words(1.30), "30% grainier")
        self.assertEqual(self.words(1.20), "")
        self.assertEqual(self.words(0.60), "", "a softer box is not named: motion blur lowers the band too")

    def test_combines_with_colour_words(self):
        self.assertEqual(self.words(1.30, np.array([50.0, 0.0, 9.0])), "warmer and 30% grainier")

    def test_colour_only_callers_are_unchanged(self):
        self.assertEqual(check_frames.drift_words(np.array([50.0, 0.0, 9.0]), self.lab), "warmer")


class CheckDriftTest(unittest.TestCase):
    def test_drift_record_carries_texture_ratios_and_words(self):
        from types import SimpleNamespace
        from h3_continuity import story_check
        boxes = [SimpleNamespace(id="a", cut=False, new_scene=False), SimpleNamespace(id="b", cut=False, new_scene=False)]
        ctx = SimpleNamespace(timeline=SimpleNamespace(boxes=boxes))
        firsts = {}
        self.assertIsNone(story_check._drift(ctx, 0, [noisy(10.0)], firsts))
        drift = story_check._drift(ctx, 1, [noisy(20.0)], firsts)
        self.assertEqual(drift["box"], "a")
        self.assertGreater(drift["texture"][0], 1.5)
        self.assertIn("grainier", drift["words"])


if __name__ == "__main__":
    unittest.main()
