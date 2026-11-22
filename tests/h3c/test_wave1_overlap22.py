import json
import unittest

import torch

from tests.h3c.continuity_support import enable_comfy_cpu

enable_comfy_cpu()

import comfy.nested_tensor  # noqa: E402
from h3_continuity import latents, timeline, timeline_prepare, timing  # noqa: E402


def av(frames, ticks):
    return {"samples": comfy.nested_tensor.NestedTensor(
        (torch.zeros(1, 24, timing.tokens_for_frames(frames), 4, 6), torch.zeros(1, 32, 2, ticks)))}


class Overlap22Test(unittest.TestCase):
    def test_offered_but_not_default(self):
        self.assertEqual(timing.CONTEXT_OPTIONS, ("22", "39", "90", "141"))
        self.assertEqual(timeline_prepare.setting("context_frames", "22"), 22)
        self.assertEqual(timeline_prepare.setting("context_frames", 22), 22)

    def test_carries_seven_tokens_and_end_aligned_37_ticks(self):
        generator = torch.Generator().manual_seed(0)
        source_video = torch.randn(1, 24, timing.tokens_for_frames(192), 4, 6, generator=generator)
        source_audio = torch.randn(1, 32, 2, 320, generator=generator)
        out, carried_video, carried_audio, ticks = latents.build_continuation(
            av(141, timing.ticks_for_frames(141)), source_video, source_audio, 22, True)
        video, audio = out["samples"].tensors
        video_mask, audio_mask = out["noise_mask"].tensors
        self.assertEqual(ticks, 37)
        self.assertTrue(torch.equal(video[:, :, :7], source_video[:, :, -7:]))
        self.assertTrue(torch.equal(audio[..., :37], source_audio[..., 283:320]))
        self.assertEqual(video_mask[:, :, :7].sum().item(), 0)
        self.assertTrue(bool((video_mask[:, :, 7:] == 1).all()))

    def test_same_new_frames_as_39_with_17_fewer_generated(self):
        parsed = timeline.parse(json.dumps({"version": 1, "boxes": [
            {"id": "a", "frames": 124, "prompt": "A room.", "seed": 1},
            {"id": "b", "frames": 124, "prompt": "The same room.", "seed": 2}]}))
        new39, carried39 = timeline.box_length(parsed, 1, 39)
        new22, carried22 = timeline.box_length(parsed, 1, 22)
        self.assertEqual(new22, new39)
        self.assertEqual((new39 + carried39) - (new22 + carried22), 17)


if __name__ == "__main__":
    unittest.main()
