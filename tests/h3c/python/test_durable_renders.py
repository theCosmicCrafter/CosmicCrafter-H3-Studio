"""Saved takes stay with their boxes, the full video builds without blocking status, and clips of different formats
join in one format."""

import os
import shutil
import tempfile
import threading
import unittest
from unittest import mock

import av
import torch

from h3_continuity import color, media, nodes, store
from h3_continuity import timeline as rules
from tests.h3c.python.helpers import box, parse
from tests.h3c.python.test_assembly import frames, label


def entry(index, box_id, created="2026-11-06T10:00:00", **extra):
    return {"index": index, "stem": store.stem(index), "frames": 22, "context_frames": 0, "created": created,
            "timeline": {"box": box_id}, **extra}


class AlignTest(unittest.TestCase):
    def test_takes_follow_their_boxes_when_boxes_move(self):
        manifest = {"segments": [entry(1, "a"), entry(2, "b"), entry(3, "c")]}
        self.assertTrue(store.align(manifest, ["a", "new", "b", "c"]))
        self.assertEqual([(store.box_of(e), e["index"], e["stem"]) for e in manifest["segments"]],
                         [("a", 1, "seg_0001"), ("b", 3, "seg_0002"), ("c", 4, "seg_0003")])
        self.assertEqual([store.box_of(e) for e in store.placed(manifest, 4)], ["a", "b", "c"])

    def test_takes_of_removed_boxes_are_kept_after_the_last_box(self):
        manifest = {"segments": [entry(1, "a"), entry(2, "gone"), entry(3, "c")]}
        store.align(manifest, ["a", "c"])
        self.assertEqual([(store.box_of(e), e["index"]) for e in manifest["segments"]], [("a", 1), ("c", 2), ("gone", 3)])
        self.assertEqual(len(store.placed(manifest, 2)), 2)

    def test_the_newest_take_of_a_box_is_in_place(self):
        manifest = {"segments": [entry(1, "a", "2026-11-06T10:00:00"), entry(2, "a", "2026-11-06T11:00:00")]}
        store.align(manifest, ["a"])
        self.assertEqual(manifest["segments"][0]["stem"], "seg_0002")
        self.assertEqual(manifest["segments"][1]["index"], 2)

    def test_aligned_manifest_reports_no_change(self):
        manifest = {"segments": [entry(1, "a"), entry(2, "b")]}
        self.assertFalse(store.align(manifest, ["a", "b"]))

    def test_a_moved_box_never_writes_over_another_boxs_files(self):
        folder = tempfile.mkdtemp(prefix="h3c-stem-")
        try:
            manifest = {"segments": [entry(1, "b")]}
            open(os.path.join(folder, "seg_0001.safetensors"), "w").close()
            self.assertEqual(store.free_stem(folder, manifest, 1), "seg_0001-2")
            self.assertEqual(store.free_stem(folder, manifest, 2), "seg_0002")
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_saving_a_box_archives_only_its_own_take(self):
        folder = tempfile.mkdtemp(prefix="h3c-archive-")
        try:
            manifest = {"segments": [entry(1, "a"), entry(2, "b"), entry(3, "c")]}
            for item in manifest["segments"]:
                open(os.path.join(folder, item["stem"] + ".safetensors"), "w").close()
            import datetime
            moved = store.archive_box(folder, manifest, "b", datetime.datetime(2026, 11, 6, 12))
            self.assertEqual(moved, [2])
            self.assertEqual([store.box_of(e) for e in manifest["segments"]], ["a", "c"])
            self.assertTrue(os.path.exists(os.path.join(folder, "seg_0003.safetensors")))
            self.assertFalse(os.path.exists(os.path.join(folder, "seg_0002.safetensors")))
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class StatusPayloadTest(unittest.TestCase):
    def test_outdated_boxes_keep_their_picture_and_are_not_next(self):
        parsed = parse([box("a", 22), box("b", 22), box("c", 22)])
        segments = [entry(1, "a"), entry(2, "b")]
        status = rules.status_payload("seq", parsed, segments, 2, lambda e: {"filename": e["stem"]}, None, 2.0,
                                      {0}, {1})
        self.assertEqual([item["status"] for item in status["boxes"]], ["done", "outdated", "next"])
        self.assertEqual(status["boxes"][1]["thumb"], {"filename": "seg_0002"})
        self.assertEqual((status["next"], status["outdated"]), (3, 1))

    def test_every_box_with_a_take_needs_no_render(self):
        parsed = parse([box("a", 22), box("b", 22)])
        status = rules.status_payload("seq", parsed, [entry(1, "a"), entry(2, "b")], None, lambda e: None, None, 2.0,
                                      {0}, {1})
        self.assertIsNone(status["next"])
        self.assertIn("1 is outdated", status["message"])


class ColorTest(unittest.TestCase):
    def test_sdr_white_lands_where_bt2408_puts_it(self):
        white = torch.ones(1, 3)
        self.assertAlmostEqual(float(color.convert(white, "sRGB", "HDR")[0, 0]), 0.75, places=3)
        self.assertAlmostEqual(float(color.convert(white, "sRGB", "HDR PQ")[0, 0]), 0.5806, places=3)

    def test_black_stays_black_and_gray_is_neutral(self):
        out = color.convert(torch.tensor([[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]]), "sRGB", "HDR")
        self.assertAlmostEqual(float(out[0].max()), 0.0, places=4)
        self.assertAlmostEqual(float(out[1].max() - out[1].min()), 0.0, places=3)

    def test_target_space_prefers_hdr(self):
        self.assertEqual(color.target_space(["sRGB", "sRGB"]), "sRGB")
        self.assertEqual(color.target_space(["sRGB", "HDR"]), "HDR")
        self.assertEqual(color.target_space(["HDR PQ", "HDR PQ", "HDR"]), "HDR PQ")


class MixedFormatJoinTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="h3c-mixed-")

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def write(self, name, images, fps, **options):
        path = os.path.join(self.folder, name)
        media.write_segment_video(path, images, fps, 16, **options)
        return path

    def test_interpolated_and_native_clips_join_at_the_higher_rate_keeping_time(self):
        native = self.write("a.mp4", frames(12, 0), 24)
        smooth = self.write("b.mp4", frames(24, 2), 48)
        written, note = media.build_full_video(os.path.join(self.folder, "full.mp4"), [native, smooth], None, 16)
        self.assertIsNotNone(written, note)
        self.assertIn("48 fps", note)
        with av.open(written) as container:
            stream = container.streams.video[0]
            self.assertEqual(stream.average_rate, 48)
            decoded = [frame.to_ndarray(format="rgb24") for frame in container.decode(stream)]
        self.assertEqual(len(decoded), 48)  # 0.5 s + 0.5 s at 48 fps
        labels = [label(array) for array in decoded]
        self.assertEqual(labels[:4], [(0, 0), (0, 0), (0, 1), (0, 1)])  # 24 fps frames repeat
        self.assertEqual(labels[24:28], [(2, 0), (2, 1), (2, 2), (2, 3)])

    def test_windows_of_interpolated_clips_keep_their_duration(self):
        native = self.write("a.mp4", frames(12, 0), 24)
        smooth = self.write("b.mp4", frames(24, 2), 48)
        windows = [(native, 2, 6), (smooth, *media.window_at_fps(2, 6, 48))]
        written, _ = media.build_full_video(os.path.join(self.folder, "full.mp4"), windows, None, 16)
        with av.open(written) as container:
            count = sum(1 for _ in container.decode(video=0))
        self.assertEqual(count, 24)  # two 6-frame windows of the 24 fps clock = 0.5 s at 48 fps

    def test_sdr_and_hdr_clips_join_in_hdr(self):
        sdr = self.write("a.mp4", frames(6, 0), 24)
        hdr = self.write("b.mp4", frames(6, 2), 24, color_space="HDR")
        written, note = media.build_full_video(os.path.join(self.folder, "full.mp4"), [sdr, hdr], None, 16)
        self.assertIsNotNone(written, note)
        self.assertIn("converted to HDR", note)
        with av.open(written) as container:
            stream = container.streams.video[0]
            self.assertEqual(media.video_stream_color_space(stream), "HDR")
            self.assertEqual(sum(1 for _ in container.decode(stream)), 12)

    def test_sizes_with_the_same_aspect_ratio_scale_to_the_smallest(self):
        small = self.write("a.mp4", frames(4, 0), 24)
        large = self.write("b.mp4", torch.nn.functional.interpolate(
            frames(4, 2).permute(0, 3, 1, 2), size=(32, 32)).permute(0, 2, 3, 1), 24)
        written, note = media.build_full_video(os.path.join(self.folder, "full.mp4"), [small, large], None, 16)
        self.assertIsNotNone(written, note)
        with av.open(written) as container:
            self.assertEqual((container.streams.video[0].width, container.streams.video[0].height), (16, 16))

    def test_different_aspect_ratios_resize_to_the_smallest_clip_keeping_time(self):
        square = self.write("a.mp4", frames(4, 0), 24)
        wide = self.write("b.mp4", torch.zeros(4, 16, 32, 3), 24)
        written, note = media.build_full_video(os.path.join(self.folder, "full.mp4"), [wide, square], None, 16)
        self.assertIsNotNone(written, note)
        with av.open(written) as container:
            stream = container.streams.video[0]
            self.assertEqual((stream.width, stream.height), (16, 16))
            self.assertEqual(sum(1 for _ in container.decode(stream)), 8)
        self.assertIn("scaled to 16x16", note)


class BackgroundFullVideoTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="h3c-background-")
        self.manifest = {"version": 1, "name": "seq", "segments": [], "takes": []}
        for index, (box_id, channel) in enumerate((("a", 0), ("b", 2)), 1):
            item = entry(index, box_id, video={"file": f"{store.stem(index)}.mp4", "frames": 22, "fps": 24})
            media.write_segment_video(os.path.join(self.folder, item["video"]["file"]), frames(22, channel), 24, 16)
            self.manifest["segments"].append(item)
        store.write_manifest(self.folder, self.manifest)
        patcher = mock.patch("h3_continuity.timeline_api.service.authorize_sequence", lambda *args, **kwargs: None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        nodes.wait_full_video(self.folder, 30)
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_the_encode_runs_without_the_sequence_lock_and_is_recorded(self):
        started, release = threading.Event(), threading.Event()
        real = media.build_full_video

        def slow(*args, **kwargs):
            started.set()
            release.wait(10)
            return real(*args, **kwargs)

        with mock.patch.object(media, "build_full_video", slow):
            note = nodes.rebuild_full_video(self.folder, "seq", store.load_manifest(self.folder), 16, background=True)
            self.assertEqual(note, nodes.BUILDING)
            self.assertTrue(started.wait(10))
            self.assertTrue(nodes.full_video_state(self.folder)["building"])
            # a status request on another thread takes the lock while the encode runs
            taken = nodes.SEQUENCE_LOCK.acquire(timeout=5)
            if taken:
                nodes.SEQUENCE_LOCK.release()
            self.assertTrue(taken)
            release.set()
            nodes.wait_full_video(self.folder, 30)
        state = nodes.full_video_state(self.folder)
        self.assertFalse(state["building"])
        self.assertIsNone(state["error"])
        saved = store.load_manifest(self.folder)
        self.assertIsNotNone(store.current_full_video(self.folder, saved))

    def test_a_build_of_outdated_segments_is_not_recorded(self):
        release = threading.Event()
        real = media.build_full_video

        def slow(*args, **kwargs):
            release.wait(10)
            return real(*args, **kwargs)

        with mock.patch.object(media, "build_full_video", slow):
            nodes.rebuild_full_video(self.folder, "seq", store.load_manifest(self.folder), 16, background=True)
            changed = store.load_manifest(self.folder)
            changed["segments"][1]["description"] = "regenerated"
            store.write_manifest(self.folder, changed)
            release.set()
            nodes.wait_full_video(self.folder, 30)
        self.assertNotIn("full_video", store.load_manifest(self.folder))


if __name__ == "__main__":
    unittest.main()
