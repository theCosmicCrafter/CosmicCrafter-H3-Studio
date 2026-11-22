"""Video layers, end to end on saved takes: a clip with two videos plays as one composited shot in the full video,
the video so far and the Viewer."""

import os
import shutil
import tempfile
import unittest
from unittest import mock

import av
import numpy as np
import torch

from tests.h3c.continuity_support import enable_comfy_cpu

enable_comfy_cpu()

from h3_continuity import layers, media, nodes, stacks, store, timeline_node  # noqa: E402

from .helpers import box, parse  # noqa: E402
from .test_partial_video import RATE, SEGMENT_SIZE, coded, decoded  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fixtures", "video_layers")
AAC_FRAME = 1024


def sound(path):
    """The AAC track of `path` as a stereo 32 kHz waveform [2, samples]."""
    resampler = av.AudioResampler(format="fltp", layout="stereo", rate=32000)
    with av.open(path) as container:
        chunks = [part.to_ndarray() for frame in container.decode(audio=0) for part in resampler.resample(frame)]
    chunks += [part.to_ndarray() for part in resampler.resample(None)]
    return torch.from_numpy(np.concatenate(chunks, axis=1))


def pictures(path):
    with av.open(path) as container:
        return [frame.to_ndarray(format="rgb24").astype(np.float64) for frame in container.decode(video=0)]


def psnr(found, want):
    error = np.mean((found - want) ** 2)
    return float("inf") if error == 0 else 10 * np.log10(255 ** 2 / error)


class Sequence(unittest.TestCase):
    prefix = "h3c-layers-"

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix=self.prefix)
        patcher = mock.patch("h3_continuity.timeline_api.service.authorize_sequence", lambda *args, **kwargs: None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        nodes.wait_full_video(self.folder, 60)
        shutil.rmtree(self.folder, ignore_errors=True)

    def status(self, manifest):
        store.write_manifest(self.folder, {**store.load_manifest(self.folder), **manifest})
        return timeline_node._status("seq", self.folder, self.parsed, store.load_manifest(self.folder),
                                     lambda index, entry: True, materialize=True)

    def built(self, manifest):
        self.status(manifest)
        nodes.wait_full_video(self.folder, 60)
        return self.status(manifest)


class ShotTwoTest(Sequence):
    """Clip b2 (90 frames) with video b2v1 from frame 27, fade 6, sound following the screen."""

    def setUp(self):
        super().setUp()
        layer = {"id": "b2v1", "seed": 7, "prompt": "Close.", "first": "", "last": "", "previews": [],
                 "memory": "off", "memories": [], "dialogue": "cues"}
        self.parsed = parse([box("b2", 90, cut=True, exact=True, layers=[layer],
                                 switch={"cuts": [{"at": 27, "to": "b2v1"}], "fade": 6, "sound": "screen"})],
                            requires=["video-layers-1"])
        self.main = self.take("02a.mp4", store.stem(1), index=1, timeline={"box": "b2"})
        self.layer = self.take("02b.mp4", layers.stem("b2v1"), layer="b2v1", box="b2",
                               timeline={"layer": "b2v1", "box": "b2"})

    def take(self, fixture, stem, **extra):
        shutil.copyfile(os.path.join(FIXTURES, fixture), os.path.join(self.folder, stem + ".mp4"))
        entry = {"stem": stem, "frames": 90, "context_frames": 0, "audio_sample_rate": 32000,
                 "created": "2026-11-13T12:00:00",
                 "video": {"file": stem + ".mp4", "frames": 90, "fps": 24, "width": 288, "height": 160}, **extra}
        store.save_segment(self.folder, entry, torch.zeros(1, 1, 1, 1, 1), torch.zeros(1, 1, 1, 1),
                           sound(os.path.join(FIXTURES, fixture)))
        return entry

    def test_shot_02_rebuilds_from_its_two_videos(self):
        status = self.built({"segments": [self.main], "layers": [self.layer]})
        self.assertIsNotNone(status["full_video"], status.get("export_error"))
        path = os.path.join(self.folder, status["full_video"]["filename"])
        with av.open(path) as container:
            video = container.streams.video[0]
            self.assertEqual(video.average_rate, 24)
        found = pictures(path)
        self.assertEqual(len(found), 90)
        self.assertLessEqual(abs(sound(path).shape[-1] - 3.75 * 32000), AAC_FRAME)
        a, b = pictures(os.path.join(FIXTURES, "02a.mp4")), pictures(os.path.join(FIXTURES, "02b.mp4"))
        wanted = [(1 - w) * a[f] + w * b[f] for f, w in ((f, min(1, max(0, (f - 24) / 6))) for f in range(90))]
        scores = [psnr(found[f], wanted[f]) for f in range(90)]
        for f, score in enumerate(scores):
            self.assertGreaterEqual(score, 36, f"frame {f}")
            for other in (f - 1, f + 1):
                if 0 <= other < 90:
                    self.assertGreater(score, psnr(found[f], wanted[other]), f"frame {f} is closer to frame {other}")
        self.assertGreaterEqual(sum(scores) / 90, 39)
        item = status["boxes"][0]["stack"]
        self.assertEqual((item["file"]["filename"], item["frames"], item["fps"]), ("stack@b2.mp4", 90, 24))
        self.assertEqual(status["full_video_clock"], [[0, 90, 0, 1]])

    def test_full_video_waits_for_every_video(self):
        status = self.built({"segments": [self.main]})
        self.assertIsNone(status["full_video"])
        self.assertIn("Clip 1's video 1b has no take yet.", status["export_error"])
        self.assertNotIn("stack", status["boxes"][0], "with no other video rendered, the clip plays its main video")


class SoFarTest(Sequence):
    """Clips a (22 frames), b (30: main, 2b from 10, 2c from 20, hard cuts) and c (17). a, b and 2b have takes."""

    def setUp(self):
        super().setUp()
        items = [{"id": layer_id, "seed": 7, "prompt": "Close.", "first": "", "last": "", "previews": [],
                  "memory": "off", "memories": [], "dialogue": "cues"} for layer_id in ("bv1", "bv2")]
        self.parsed = parse([box("a", 22), box("b", 30, cut=True, exact=True, layers=items,
                                                switch={"cuts": [{"at": 10, "to": "bv1"}, {"at": 20, "to": "bv2"}],
                                                        "fade": 0, "sound": "screen"}), box("c", 17, cut=True)],
                            requires=["video-layers-1"])
        self.manifest = {"segments": [self.take(store.stem(1), 22, 0, index=1, timeline={"box": "a"}),
                                      self.take(store.stem(2), 30, 1, index=2, timeline={"box": "b"})],
                         "layers": [self.take(layers.stem("bv1"), 30, 2, layer="bv1", box="b",
                                              timeline={"layer": "bv1", "box": "b"})]}

    def take(self, stem, frames, channel, **extra):
        entry = {"stem": stem, "frames": frames, "context_frames": 0, "audio_sample_rate": RATE,
                 "created": "2026-11-13T12:00:00",
                 "video": {"file": stem + ".mp4", "frames": frames, "fps": 24, "width": SEGMENT_SIZE,
                           "height": SEGMENT_SIZE}, **extra}
        media.write_segment_video(os.path.join(self.folder, entry["video"]["file"]),
                                  coded(frames, channel, SEGMENT_SIZE), 24, 16)
        store.save_segment(self.folder, entry, torch.zeros(1, 1, 1, 1, 1), torch.zeros(1, 1, 1, 1),
                           torch.full((1, frames * RATE // 24), 0.1 * (channel + 1)))
        return entry

    def test_so_far_skips_swaps_to_unrendered_videos(self):
        status = self.built(self.manifest)
        so_far = status["preview_video"]
        self.assertEqual((so_far["boxes"], so_far["total"]), (2, 3))
        _, labels = decoded(os.path.join(self.folder, so_far["file"]["filename"]))
        self.assertEqual(labels, [(0, f) for f in range(22)] + [(1, f) for f in range(10)]
                         + [(2, f) for f in range(10, 30)])
        self.assertIn("Clip 2's video 2c has no take yet.", status["preview_error"])
        self.assertEqual(so_far["clock"], [[0, 22, 0, 1], [22, 30, 22, 1]])

    def test_so_far_plays_the_main_video_until_the_layers_render(self):
        self.manifest["layers"] = []
        status = self.built(self.manifest)
        _, labels = decoded(os.path.join(self.folder, status["preview_video"]["file"]["filename"]))
        self.assertEqual(labels, [(0, f) for f in range(22)] + [(1, f) for f in range(30)])
        self.assertFalse(os.path.exists(os.path.join(self.folder, "stack@b.mp4")))

    def test_without_layers_the_full_video_is_unchanged(self):
        plain = parse([box("a", 22), box("b", 30, cut=True)])
        before = store.full_video_fingerprint(self.folder, self.manifest)
        joined, notes = stacks.substitute(self.folder, plain, self.manifest, 2, 16)
        self.assertIs(joined, self.manifest)
        self.assertEqual(notes, [])
        self.assertEqual(store.full_video_fingerprint(self.folder, joined), before)


if __name__ == "__main__":
    unittest.main()
