import json
import unittest

import torch

from tests.h3c.continuity_support import enable_comfy_cpu

enable_comfy_cpu()

import comfy.nested_tensor  # noqa: E402
from h3_continuity import latents, timeline  # noqa: E402


class AudioFeatherTest(unittest.TestCase):
    def setUp(self):
        generator = torch.Generator().manual_seed(0)
        self.video = torch.randn(1, 24, 57, 4, 6, generator=generator)
        self.audio = torch.randn(1, 32, 2, 320, generator=generator)
        self.target = {"samples": comfy.nested_tensor.NestedTensor((torch.zeros(1, 24, 37, 4, 6), torch.zeros(1, 32, 2, 207)))}

    def build(self, feather):
        return latents.build_continuation(self.target, self.video, self.audio, 39, True, audio_feather=feather)

    def test_zero_keeps_the_audio_frozen(self):
        out, _, carried, ticks = self.build(0)
        self.assertEqual(out["noise_mask"].tensors[1][..., :ticks].sum().item(), 0)
        self.assertEqual(carried.shape[-1], ticks)

    def test_the_last_ticks_rise_to_one_and_leave_the_carried_check(self):
        out, _, carried, ticks = self.build(4)
        mask = out["noise_mask"].tensors[1][0, 0, 0]
        self.assertEqual(mask[:ticks - 4].sum().item(), 0)
        ramp = mask[ticks - 4:ticks]
        self.assertTrue(bool((ramp[1:] > ramp[:-1]).all()))
        self.assertAlmostEqual(ramp[-1].item(), 1.0, places=6)
        self.assertEqual(carried.shape[-1], ticks - 4, "only frozen ticks are checked after sampling")

    def test_never_longer_than_the_carried_audio(self):
        out, _, carried, ticks = self.build(500)
        self.assertEqual(carried.shape[-1], 0)

    def test_timeline_key_and_layout(self):
        boxes = [{"id": "a", "frames": 124, "seed": 1, "prompt": "p"}, {"id": "b", "frames": 124, "seed": 2, "prompt": "q"}]
        plain = timeline.parse(json.dumps({"version": 1, "boxes": boxes}))
        feathered = timeline.parse(json.dumps({"version": 1, "boxes": boxes, "audio_feather": 4}))
        self.assertEqual((plain.audio_feather, feathered.audio_feather), (0, 4))
        self.assertEqual(timeline.layout_key(plain, 0), timeline.layout_key(feathered, 0))
        self.assertNotEqual(timeline.layout_key(plain, 1), timeline.layout_key(feathered, 1))
        for bad in (-1, 17, 1.5, True):
            with self.assertRaises(ValueError):
                timeline.parse(json.dumps({"version": 1, "boxes": boxes, "audio_feather": bad}))


if __name__ == "__main__":
    unittest.main()
