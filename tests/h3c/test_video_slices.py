import json
import unittest

import torch

from tests.h3c.continuity_support import enable_comfy_cpu

enable_comfy_cpu()

from h3_continuity import timeline, timeline_node  # noqa: E402

BOXES = [{"id": "a", "frames": 124, "seed": 1, "prompt": "p"}, {"id": "b", "frames": 124, "seed": 2, "prompt": "q"},
         {"id": "c", "frames": 107, "seed": 3, "cut": True, "prompt": "r"}]


def parse(**keys):
    return timeline.parse(json.dumps({"version": 1, "boxes": BOXES, **keys}))


class VideoWindowTest(unittest.TestCase):
    def test_each_box_reads_from_its_start_minus_what_it_carries(self):
        parsed = parse(video_slices=["video1"])
        self.assertEqual(timeline.video_window(parsed, 0, 39), (0, 124))
        # box b plays 119 new frames from 5.17 s and carries 39: 124 - 39 = 85, 39 + 119 generated
        self.assertEqual(timeline.video_window(parsed, 1, 39), (85, 158))
        self.assertEqual(timeline.video_window(parsed, 2, 39), (243, 107))
        self.assertEqual(timeline.video_window(parse(), 1, 22), (102, 141))

    def test_parse(self):
        self.assertEqual(parse().video_slices, [])
        self.assertEqual(parse(video_slices=["video1"]).video_slices, ["video1"])
        for bad in ("video1", ["image1"], ["video1", "video1"], [1]):
            with self.assertRaises(ValueError):
                parse(video_slices=bad)


class SliceTest(unittest.TestCase):
    def test_frames_and_matching_audio_are_cut_to_the_window(self):
        frames = torch.arange(300, dtype=torch.float32).view(300, 1, 1, 1).expand(300, 2, 2, 3)
        audio = {"waveform": torch.arange(300 * 2000, dtype=torch.float32).view(1, 1, -1), "sample_rate": 48000}
        images, audios = timeline_node.slice_videos({"video1": frames, "image1": frames[:1]}, {"video_audio1": audio},
                                                    ["video1"], 85, 158, "box 2")
        self.assertEqual(images["video1"].shape[0], 158)
        self.assertEqual(float(images["video1"][0, 0, 0, 0]), 85.0)
        self.assertEqual(images["image1"].shape[0], 1, "pictures are not sliced")
        self.assertEqual(audios["video_audio1"]["waveform"].shape[-1], 158 * 2000)
        self.assertEqual(float(audios["video_audio1"]["waveform"][0, 0, 0]), 85 * 2000)

    def test_a_short_source_says_how_long_it_is(self):
        frames = torch.zeros(200, 2, 2, 3)
        with self.assertRaisesRegex(ValueError, "video1 has 200 frames"):
            timeline_node.slice_videos({"video1": frames}, {}, ["video1"], 85, 158, "box 2")


if __name__ == "__main__":
    unittest.main()
