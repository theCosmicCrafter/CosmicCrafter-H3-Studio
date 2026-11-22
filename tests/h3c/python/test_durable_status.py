"""Timeline status keeps every saved take with its box: boxes that move, boxes that changed, and the full video."""

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import torch

from h3_continuity import nodes, store, timeline_node
from h3_continuity import timeline as rules

from .helpers import box, document

KNOWN = {"width": 64, "height": 64, "context_frames": 39, "carry_audio": True}


class DurableStatusTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="h3c-durable-")
        self.folder = os.path.join(self.root, "seq")
        os.makedirs(self.folder)
        patches = [mock.patch.object(nodes, "sequences_root", lambda: self.root),
                   mock.patch("h3_continuity.timeline_api.service.authorize_sequence", lambda *args, **kwargs: None)]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        boxes = [box("a", 107), box("b", 107, cut=True), box("c", 107, cut=True)]
        parsed = rules.parse(json.dumps(document(boxes)))
        manifest = {"version": 1, "name": "seq", "segments": [], "takes": []}
        for index, item in enumerate(boxes):
            entry = {"index": index + 1, "stem": store.stem(index + 1), "frames": 107, "context_frames": 0,
                     "created": f"2026-11-06T10:0{index}:00", "latent_width": 64, "latent_height": 64,
                     "timeline": {"box": item["id"], "layout": rules.layout_key(parsed, index, 39),
                                  "settings": rules.box_settings(True, "t2va", 64, 64, 39, True, "match")}}
            store.save_segment(self.folder, entry, torch.zeros(1, 1, 1, 1, 1), torch.zeros(1, 1, 1, 1), None)
            open(os.path.join(self.folder, entry["stem"] + "_last.png"), "wb").close()
            manifest["segments"].append(entry)
        store.write_manifest(self.folder, manifest)
        self.boxes = boxes

    def tearDown(self):
        nodes.wait_full_video(self.folder, 30)
        shutil.rmtree(self.root, ignore_errors=True)

    def status(self, boxes, materialize=False):
        return timeline_node.request_status({"name": "seq", "timeline": json.dumps(document(boxes)), "settings": KNOWN},
                                            materialize=materialize)

    def test_saved_boxes_are_rendered(self):
        status = self.status(self.boxes)
        self.assertTrue(status["ok"], status)
        self.assertEqual([item["status"] for item in status["boxes"]], ["done", "done", "done"])

    def test_a_new_box_does_not_hide_the_boxes_after_it(self):
        boxes = [self.boxes[0], box("new", 107, cut=True), *self.boxes[1:]]
        status = self.status(boxes, materialize=True)
        self.assertEqual([item["status"] for item in status["boxes"]], ["done", "next", "done", "done"])
        self.assertEqual(status["next"], 2)
        saved = store.load_manifest(self.folder)
        self.assertEqual([(store.box_of(e), e["index"]) for e in saved["segments"]], [("a", 1), ("b", 3), ("c", 4)])

    def test_a_changed_box_keeps_its_take_as_outdated(self):
        boxes = [self.boxes[0], {**self.boxes[1], "prompt": "Another street."}, self.boxes[2]]
        status = self.status(boxes)
        item = status["boxes"][1]
        self.assertEqual(item["status"], "outdated")
        self.assertIn("thumb", item)
        self.assertIn("changed", item["reason"])
        self.assertIsNone(status["next"])  # Render has nothing to do; the outdated box regenerates on request
        self.assertEqual(status["outdated"], 1)

    def test_a_removed_box_keeps_its_files(self):
        status = self.status([self.boxes[0], self.boxes[2]], materialize=True)
        self.assertEqual([item["status"] for item in status["boxes"]], ["done", "done"])
        self.assertTrue(os.path.exists(os.path.join(self.folder, "seg_0002.safetensors")))
        status = self.status(self.boxes)
        self.assertEqual([item["status"] for item in status["boxes"]], ["done", "done", "done"])

    def test_status_answers_while_the_full_video_builds(self):
        started = []

        def busy(plan):
            started.append(plan)
            return nodes.BUILDING

        with mock.patch.object(nodes, "_plan_full_video", return_value=({"folder": self.folder, "fingerprint": "x"}, "")), \
                mock.patch.object(nodes, "_start_full_video", busy), \
                mock.patch.object(nodes, "full_video_state", return_value={"building": True}):
            status = self.status(self.boxes, materialize=True)
        self.assertEqual(len(started), 1)
        self.assertTrue(status.get("full_video_building"))
        self.assertNotIn("export_error", status)
        self.assertEqual([item["status"] for item in status["boxes"]], ["done", "done", "done"])


if __name__ == "__main__":
    unittest.main()
