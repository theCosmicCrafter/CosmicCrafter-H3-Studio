"""A clip with several videos composited into one stack: picture blended by the switch, sound following it."""

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import numpy as np
import torch

from tests.h3c.continuity_support import enable_comfy_cpu

enable_comfy_cpu()

from h3_continuity import layers, media, nodes, stacks, store, timeline as rules  # noqa: E402
from h3_continuity.timing import sample_at_frame  # noqa: E402

from .helpers import box, document  # noqa: E402
from .test_partial_video import coded, label  # noqa: E402

RATE = 8000
SIZE = 64


def parse(frames=30, cuts=None, fade=6, sound="screen", **switch):
    item = {"id": "b2", "seed": 7, "prompt": "Close.", "first": "", "last": "", "previews": [], "memory": "off",
            "memories": [], "dialogue": "cues"}
    clip = box("b", frames, "Wide.", cut=True, exact=True, layers=[item],
               switch={"cuts": cuts or [{"at": 12, "to": "b2"}], "fade": fade, "sound": sound, **switch})
    return rules.parse(json.dumps(document([clip], requires=["video-layers-1"])))


class Takes(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="h3c-stacks-")

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def saved(self, stem, images, level, **extra):
        frames = images.shape[0]
        entry = {"stem": stem, "frames": frames, "context_frames": 0, "audio_sample_rate": RATE,
                 "created": "2026-11-13T12:00:00",
                 "video": {"file": stem + ".mp4", "frames": frames, "fps": 24, "width": images.shape[2],
                           "height": images.shape[1]}, **extra}
        media.write_segment_video(os.path.join(self.folder, entry["video"]["file"]), images, 24, 16)
        store.save_segment(self.folder, entry, torch.zeros(1, 1, 1, 1, 1), torch.zeros(1, 1, 1, 1),
                           torch.full((1, sample_at_frame(frames, RATE)), level))
        return entry

    def videos(self, layer_size=SIZE, main_size=SIZE, frames=30):
        main = self.saved("seg_0001", coded(frames, 0, main_size), 0.1, index=1, timeline={"box": "b"})
        layer = self.saved(layers.stem("b2"), coded(frames, 1, layer_size), 0.5, layer="b2", box="b",
                           timeline={"layer": "b2", "box": "b"})
        return main, {"b2": layer}

    def build(self, parsed, main, layer_entries, **kwargs):
        return stacks.build(self.folder, parsed, 0, main, layer_entries, 16, **kwargs)

    def frames(self, entry):
        path = os.path.join(self.folder, entry["video"]["file"])
        return media.read_frames(path, range(entry["video"]["frames"]))


class StackTest(Takes):
    def test_weights_blend_the_videos(self):
        parsed = parse()
        main, layer_entries = self.videos()
        entry = self.build(parsed, main, layer_entries)
        self.assertEqual((entry["stack"], entry["stem"], entry["frames"], entry["played"]), ("b", "stack@b", 30, 30))
        self.assertEqual(entry["timeline"], {"box": "b"})
        found = self.frames(entry)
        self.assertEqual(len(found), 30)
        labels = [label(found[f]) for f in range(30)]
        self.assertEqual(labels[:9], [(0, f) for f in range(9)])
        self.assertEqual(labels[15:], [(1, f) for f in range(15, 30)])
        a = media.read_frames(os.path.join(self.folder, main["video"]["file"]), range(30))
        b = media.read_frames(os.path.join(self.folder, layer_entries["b2"]["video"]["file"]), range(30))
        switch = parsed.switches["b"]
        for f in range(9, 15):
            w = layers.weight(switch, switch["cuts"][0], f)
            want = ((1 - w) * a[f].astype(float) + w * b[f].astype(float)).mean(axis=(0, 1))
            np.testing.assert_allclose(found[f].astype(float).mean(axis=(0, 1)), want, atol=2)

    def test_hard_cut(self):
        main, layer_entries = self.videos()
        found = self.frames(self.build(parse(fade=0), main, layer_entries))
        self.assertEqual([label(found[f]) for f in (11, 12)], [(0, 11), (1, 12)])

    def test_sound_follows_the_screen(self):
        main, layer_entries = self.videos()
        entry = self.build(parse(), main, layer_entries)
        waveform = store.load_waveform(self.folder, entry)
        fade = round(media.CROSSFADE_SECONDS * RATE)
        swap = sample_at_frame(12, RATE)
        self.assertEqual(waveform.shape[-1], sample_at_frame(30, RATE))
        self.assertTrue(torch.allclose(waveform[..., :swap - fade], torch.tensor(0.1)))
        self.assertTrue(torch.allclose(waveform[..., swap:], torch.tensor(0.5)))
        self.assertEqual(entry["audio_sample_rate"], RATE)

    def test_one_videos_sound(self):
        main, layer_entries = self.videos()
        waveform = store.load_waveform(self.folder, self.build(parse(sound="b2"), main, layer_entries))
        self.assertTrue(torch.allclose(waveform, torch.tensor(0.5)))

    def test_layer_at_another_size_is_scaled_to_the_main_video(self):
        main, layer_entries = self.videos(layer_size=64, main_size=32)
        entry = self.build(parse(), main, layer_entries)
        self.assertEqual((entry["video"]["width"], entry["video"]["height"]), (32, 32))
        found = self.frames(entry)
        self.assertEqual(found[20].shape, (32, 32, 3))
        self.assertEqual(label(found[20]), (1, 20))

    def test_alignment_moves_a_video(self):
        main, layer_entries = self.videos()
        found = self.frames(self.build(parse(align={"b2": {"x": 32, "y": 0, "scale": 1}}), main, layer_entries))
        self.assertLess(found[25][:, :28].mean(), 8)
        self.assertGreater(found[25][:, 36:, 1].mean(), 40)

    def test_partial_switch(self):
        main, layer_entries = self.videos()
        parsed = parse()
        entry = self.build(parsed, main, {}, switch={**parsed.switches["b"], "cuts": []})
        self.assertEqual(label(self.frames(entry)[20]), (0, 20))
        self.assertIsNone(stacks.sources(self.folder, parsed, 0, main, {}))
        self.assertIsNotNone(stacks.sources(self.folder, parsed, 0, main, {}, {**parsed.switches["b"], "cuts": []}))

    def test_stack_is_reused_until_a_source_changes(self):
        main, layer_entries = self.videos()
        parsed = parse()
        self.assertIsNone(stacks.current(self.folder, parsed, 0, main, layer_entries))
        entry = self.build(parsed, main, layer_entries)
        self.assertEqual(stacks.current(self.folder, parsed, 0, main, layer_entries), entry)
        self.assertIsNone(stacks.current(self.folder, parse(fade=4), 0, main, layer_entries))
        media.write_segment_video(os.path.join(self.folder, layer_entries["b2"]["video"]["file"]),
                                  coded(30, 2, SIZE), 24, 16)
        self.assertIsNone(stacks.current(self.folder, parsed, 0, main, layer_entries))

    def test_stack_copies_into_the_full_video(self):
        main, layer_entries = self.videos()
        before = self.saved("seg_0000", coded(22, 2, SIZE), 0.3, index=1, timeline={"box": "a"})
        entry = self.build(parse(), main, layer_entries)
        path = os.path.join(self.folder, "full.mp4")
        written, note = media.build_full_video(path, [os.path.join(self.folder, before["video"]["file"]),
                                                      os.path.join(self.folder, entry["video"]["file"])], None, 16)
        self.assertEqual(note, "")
        self.assertEqual(written, path)


class StackOutputTest(Takes):
    def setUp(self):
        super().setUp()
        patcher = mock.patch("h3_continuity.timeline_api.service.authorize_sequence", lambda *args, **kwargs: None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_saving_rebuilds_the_full_video_with_the_stack(self):
        parsed = parse()
        main, layer_entries = self.videos()
        manifest = {"segments": [main], "layers": list(layer_entries.values())}
        store.write_manifest(self.folder, manifest)
        note = nodes.rebuild_full_video(self.folder, "seq", manifest, 16, restack=stacks.restacker(parsed, 1))
        self.assertTrue(note.startswith("Full video:"), note)
        self.assertNotIn("re-encoded", note)
        full = os.path.join(self.folder, store.load_manifest(self.folder)["full_video"]["file"])
        found = media.read_frames(full, range(30))
        self.assertEqual([label(found[f]) for f in (5, 20)], [(0, 5), (1, 20)])
        self.assertTrue(os.path.isfile(os.path.join(self.folder, "stack@b.mp4")))

    def test_substitute_keeps_the_main_video_while_a_video_waits(self):
        parsed = parse()
        main, _ = self.videos()
        manifest = {"segments": [main], "layers": []}
        joined, notes = stacks.substitute(self.folder, parsed, manifest, 1, 16)
        self.assertEqual(joined["segments"], [main])
        self.assertEqual(notes, ["Clip 1's video 1b has no take yet."])

    def test_substitute_places_the_stack_at_its_clips_index(self):
        parsed = parse()
        main, layer_entries = self.videos()
        manifest = {"segments": [main], "layers": list(layer_entries.values())}
        joined, notes = stacks.substitute(self.folder, parsed, manifest, 1, 16)
        (stack,) = joined["segments"]
        self.assertEqual((stack["stack"], stack["index"], notes), ("b", 1, []))
        self.assertEqual(stacks.substitute(self.folder, parsed, joined, 1, 16, make=False)[0], joined)
        self.assertEqual(manifest["segments"], [main], "the saved manifest is left as it was")


if __name__ == "__main__":
    unittest.main()
