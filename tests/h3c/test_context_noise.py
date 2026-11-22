import json
import unittest

import torch

from tests.h3c.continuity_support import enable_comfy_cpu

enable_comfy_cpu()

from h3_continuity import latents  # noqa: E402


class StubVAE:
    """Each latent step stands for its frames (1, 4, 4, 4, 4 per cycle); pixels are the channel means."""

    def decode(self, video):
        frames = []
        for step in range(video.shape[2]):
            value = video[0, :, step].mean().sigmoid().item()
            frames += [torch.full((8, 8, 3), value)] * (1 if step % 5 == 0 else 4)
        return torch.stack(frames)[None]

    def encode(self, pixels):
        steps, frame = [], 0
        while frame < pixels.shape[0]:
            count = 1 if len(steps) % 5 == 0 else 4
            steps.append(pixels[frame:frame + count].mean())
            frame += count
        return torch.stack(steps).view(1, 1, -1, 1, 1).expand(1, 24, -1, 1, 1).clone()


class ContextNoiseTest(unittest.TestCase):
    def setUp(self):
        self.video = torch.randn(1, 24, 37, 1, 1, generator=torch.Generator().manual_seed(0))

    def test_taper_runs_from_0_4_to_zero(self):
        strengths = latents.context_noise_strengths(39)
        self.assertAlmostEqual(float(strengths[0]), 0.4)
        self.assertEqual(float(strengths[-1]), 0.0)
        self.assertTrue(bool((strengths[1:] <= strengths[:-1]).all()))

    def test_delta_matches_the_carried_tokens_and_is_zero_without_noise(self):
        delta = latents.context_noise_delta(StubVAE(), self.video, 39)
        self.assertEqual(tuple(delta.shape), (1, 24, 12, 1, 1))
        self.assertGreater(float(delta.abs().max()), 0)
        zero = latents.context_noise_delta(StubVAE(), self.video, 39, amplitude=0.0)
        self.assertEqual(float(zero.abs().max()), 0.0)

    def test_the_delta_is_deterministic(self):
        a = latents.context_noise_delta(StubVAE(), self.video, 39)
        b = latents.context_noise_delta(StubVAE(), self.video, 39)
        self.assertTrue(torch.equal(a, b))

    def test_timeline_key_and_layout(self):
        from h3_continuity import timeline
        boxes = [{"id": "a", "frames": 124, "seed": 1, "prompt": "p"}, {"id": "b", "frames": 124, "seed": 2, "prompt": "q"}]
        plain = timeline.parse(json.dumps({"version": 1, "boxes": boxes}))
        noisy = timeline.parse(json.dumps({"version": 1, "boxes": boxes, "context_noise": True}))
        self.assertEqual((plain.context_noise, noisy.context_noise), (False, True))
        self.assertEqual(timeline.layout_key(plain, 0), timeline.layout_key(noisy, 0))
        self.assertNotEqual(timeline.layout_key(plain, 1), timeline.layout_key(noisy, 1))
        with self.assertRaises(ValueError):
            timeline.parse(json.dumps({"version": 1, "boxes": boxes, "context_noise": 1}))


if __name__ == "__main__":
    unittest.main()
