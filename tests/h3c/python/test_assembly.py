import os
import shutil
import tempfile
import unittest
from unittest import mock

import av
import torch

from h3_continuity import audio_tracks, media, nodes, store

RATE = 8000


def frames(count, channel):
    """Frame i is a flat colour in `channel` of level 10 * (i + 2), so the source and index survive H.264."""
    images = torch.zeros(count, 16, 16, 3)
    for index in range(count):
        images[index, :, :, channel] = (index + 2) * 10 / 255
    return images


def label(array):
    """(channel, index) of a frame written by `frames`."""
    means = array.reshape(-1, 3).mean(axis=0)
    channel = int(means.argmax())
    return channel, round(means[channel] / 10) - 2


class AssemblyTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="h3c-assembly-")
        self.manifest = {"segments": []}
        for index, (box_id, channel) in enumerate((("a", 0), ("b", 2)), 1):
            entry = {"index": index, "stem": store.stem(index), "frames": 22, "context_frames": 0,
                     "timeline": {"box": box_id}, "video": {"file": f"{store.stem(index)}.mp4", "frames": 22, "fps": 24}}
            media.write_segment_video(os.path.join(self.folder, entry["video"]["file"]), frames(22, channel), 24, 16)
            self.manifest["segments"].append(entry)

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def candidate(self, left, right):
        entry = {"box": "b", "candidate": "c1", "stem": "replace@b-c1", "frames": left + right + 10,
                 "context_frames": 5, "played": left + right,
                 "timeline": {"replacement": "b", "left": left, "right": right},
                 "video": {"file": "replace@b-c1.mp4", "frames": left + right, "fps": 24}}
        media.write_segment_video(os.path.join(self.folder, entry["video"]["file"]), frames(left + right, 1), 24, 16)
        return entry

    def build(self, replaced):
        parts = nodes.ordered_parts(self.manifest, (), replaced)
        path = os.path.join(self.folder, "full.mp4")
        written, note = media.build_full_video(
            path, [(os.path.join(self.folder, entry["video"]["file"]), first, count) for entry, first, count, _ in parts],
            None, 16)
        decoded = media.read_frames(written, range(60))
        return parts, [label(decoded[i]) for i in range(len(decoded))], note

    def test_candidate_replaces_both_sides_without_changing_duration(self):
        parts, labels, note = self.build([self.candidate(6, 6)])
        self.assertEqual([(entry["stem"], first, count, inserted) for entry, first, count, inserted in parts],
                         [(store.stem(1), 0, 16, False), ("replace@b-c1", 0, 12, False), (store.stem(2), 6, 16, False)])
        self.assertIn("re-encoded", note)
        expected = [(0, i) for i in range(16)] + [(1, i) for i in range(12)] + [(2, i) for i in range(6, 22)]
        self.assertEqual(labels[:44], expected)

    def test_re_encoded_frames_play_at_the_frame_rate(self):
        self.build([self.candidate(6, 6)])
        with av.open(os.path.join(self.folder, "full.mp4")) as container:
            stream = container.streams.video[0]
            times = [frame.time for frame in container.decode(stream)]
            self.assertEqual(stream.average_rate, 24)
        self.assertEqual(len(times), 44)
        for index, time in enumerate(times):
            self.assertAlmostEqual(time, index / 24, places=3)

    def test_trims_at_the_end_only_still_copy_packets(self):
        parts, labels, note = self.build([self.candidate(12, 0)])
        self.assertNotIn("re-encoded", note)
        expected = [(0, i) for i in range(10)] + [(1, i) for i in range(12)] + [(2, i) for i in range(22)]
        self.assertEqual(labels[:44], expected)

    def test_previews_compare_the_candidate_with_the_footage_it_replaces(self):
        candidate = self.candidate(6, 6)
        with mock.patch.object(nodes, "PREVIEW_FRAMES", 4):
            self.assertEqual(nodes.write_previews(self.folder, self.manifest, candidate, 16), "")
        preview = candidate["preview"]
        self.assertEqual((preview["frames"], preview["region"]), (20, [4, 16]))

        def labels(file):
            path = os.path.join(self.folder, file)
            with av.open(path) as container:
                self.assertEqual(sum(1 for _ in container.decode(video=0)), 20)
            decoded = media.read_frames(path, range(20))
            return [label(decoded[i]) for i in range(20)]

        self.assertEqual(labels(preview["file"]), [(0, i) for i in range(12, 16)] + [(1, i) for i in range(12)]
                         + [(2, i) for i in range(6, 10)])
        self.assertEqual(labels(preview["original"]), [(0, i) for i in range(12, 22)] + [(2, i) for i in range(10)])

    def test_previews_hear_the_soundtrack_at_the_same_moments(self):
        candidate = self.candidate(6, 6)
        ramp = torch.arange(44 * RATE // 24, dtype=torch.float32).unsqueeze(0)
        heard = []
        with mock.patch.object(nodes, "PREVIEW_FRAMES", 4), \
                mock.patch.object(audio_tracks, "soundtrack_audio", return_value=(ramp, RATE)) as placed, \
                mock.patch.object(media, "build_full_video",
                                  side_effect=lambda path, videos, audio, crf: (heard.append(audio), (path, ""))[1]):
            self.assertEqual(nodes.write_previews(self.folder, self.manifest, candidate, 16, soundtrack=["clip"]), "")
        self.assertEqual(placed.call_args.args[1], [dict(frames=16,coverage=[dict(box='a',first=0,frames=16)]),
            dict(frames=12,coverage=[dict(box='a',first=16,frames=6),dict(box='b',first=0,frames=6)]),
            dict(frames=16,coverage=[dict(box='b',first=6,frames=16)])])
        expected = ramp[:, 12 * RATE // 24:round(32 * RATE / 24)]
        for waveform, rate in heard:
            self.assertEqual(rate, RATE)
            self.assertTrue(torch.equal(waveform, expected))
        self.assertEqual(len(heard), 2)

    def test_without_a_candidate_the_original_coverage_plays(self):
        parts, labels, _ = self.build([])
        self.assertEqual([(first, count) for _, first, count, _ in parts], [(0, 22), (0, 22)])

    def test_insertion_bridges_still_insert(self):
        bridge = {"box": "b", "stem": "bridge@b", "frames": 22, "context_frames": 5, "played": 12,
                  "video": {"file": "bridge@b.mp4", "frames": 12, "fps": 24}}
        parts = nodes.ordered_parts(self.manifest, [bridge], [self.candidate(6, 6)])
        self.assertEqual([(entry["stem"], count, inserted) for entry, _, count, inserted in parts],
                         [(store.stem(1), 16, False), ("bridge@b", 12, True), ("replace@b-c1", 12, False),
                          (store.stem(2), 16, False)])

    def test_generated_audio_follows_the_windows(self):
        ramp = torch.arange(22 * RATE // 24, dtype=torch.float32).unsqueeze(0) / 1e5
        waves = {"a": ramp, "b": ramp + 1, "c1": torch.full((1, 22 * RATE // 24), 3.0)}
        parts = nodes.ordered_parts(self.manifest, (), [self.candidate(6, 6)])
        pieces = [(entry["context_frames"] + first + count, entry["context_frames"] + first,
                   waves[(entry.get("timeline") or {}).get("box") or entry["candidate"]], RATE)
                  for entry, first, count, _ in parts]
        wave, _ = media.assemble_audio(pieces, crossfade_seconds=0)
        self.assertEqual(wave.shape[-1], round(44 * RATE / 24))
        self.assertEqual(wave[0, 16 * RATE // 24 + 10].item(), 3.0)
        # Box 2 resumes at its own frame 6.
        self.assertAlmostEqual(wave[0, 28 * RATE // 24 + 100].item(), 1 + (6 * RATE // 24 + 100) / 1e5, places=4)


class SoundtrackTest(unittest.TestCase):
    def test_replacement_parts_keep_the_recording_clock(self):
        clip = {"slot": "audio1", "start": 0.25, "source_start": 0.5, "duration": 1.5}
        sources = {"audio1": {"waveform": torch.randn(1, 2, 3 * RATE), "sample_rate": RATE}}
        def parts(items): return [dict(frames=count,coverage=[] if inserted else [dict(box='a',first=0,frames=count)]) for count,inserted in items]
        replaced, _ = audio_tracks.place([clip], sources, parts([(16, False), (12, False), (16, False)]))
        whole, _ = audio_tracks.place([clip], sources, parts([(44, False)]))
        self.assertTrue(torch.equal(replaced, whole))
        inserted, _ = audio_tracks.place([clip], sources, parts([(22, False), (12, True), (22, False)]))
        self.assertEqual(inserted.shape[-1], whole.shape[-1] + 12 * RATE // 24)


class FingerprintTest(unittest.TestCase):
    def test_selection_changes_the_full_video_sources(self):
        folder = tempfile.mkdtemp(prefix="h3c-fingerprint-")
        try:
            entries = []
            for stem in ("seg_a", "replace@b-c1"):
                with open(os.path.join(folder, stem + ".mp4"), "wb") as handle:
                    handle.write(b"x")
                entries.append({"stem": stem, "video": {"file": stem + ".mp4"}})
            manifest = {"segments": [entries[0]]}
            self.assertNotEqual(store.full_video_fingerprint(folder, manifest, [entries[1]]),
                                store.full_video_fingerprint(folder, manifest, []))
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class WindowFpsTest(unittest.TestCase):
    def test_interpolated_segments_scale_windows(self):
        self.assertEqual(media.window_at_fps(0, 100, 24), (0, 100))
        self.assertEqual(media.window_at_fps(0, 100, None), (0, 100))
        self.assertEqual(media.window_at_fps(0, 100, 48), (0, 200))
        self.assertEqual(media.window_at_fps(10, 5, 48), (20, 10))
        start, count = media.window_at_fps(3, 7, 60)
        self.assertEqual((start, start + count), (8, 25))


if __name__ == "__main__":
    unittest.main()
