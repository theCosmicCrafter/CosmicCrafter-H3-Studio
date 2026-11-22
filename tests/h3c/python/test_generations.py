import copy
import json
import os
import shutil
import tempfile
from pathlib import Path
import unittest
from unittest import mock

from h3_continuity import generations, nodes, store
from .helpers import box, document


class GenerationsTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="h3c-generations-")
        self.folder = os.path.join(self.root, "seq")
        os.mkdir(self.folder)
        self.body = dict(name="seq", timeline=json.dumps(document([box("a", 107), box("b", 107, cut=True)])),
                         settings=dict(width=64, height=64, context_frames=39))
        self.manifest = dict(version=1, name="seq", segments=[dict(index=1, stem="seg_0001",
            timeline={"box": "a"}, video={"file": "seg_0001.mp4"})], takes=[],
            full_video=dict(file="seq_full.mp4"))
        for file in ("seg_0001.mp4", "seg_0001.safetensors", "seq_full.mp4"):
            with open(os.path.join(self.folder, file), "wb") as handle:
                handle.write(b"original generation bytes")
        store.write_manifest(self.folder, self.manifest)
        self.patches = [mock.patch.object(nodes, "sequences_root", return_value=self.root),
                        mock.patch("h3_continuity.takes.busy", return_value=False)]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_start_has_no_renders_and_keeps_old_files_and_authored_content(self):
        body = copy.deepcopy(self.body)
        before = {name: Path(self.folder, name).read_bytes() for name in os.listdir(self.folder)}
        result = generations.start(body)
        self.assertTrue(result["ok"], result)
        self.assertNotEqual(result["name"], "seq")
        new = store.load_manifest(os.path.join(self.root, result["name"]))
        self.assertEqual(new["segments"], [])
        self.assertEqual(new["takes"], [])
        self.assertEqual(new["generation_history"][0]["timeline"], self.body["timeline"])
        self.assertEqual(new["generation_history"][0]["settings"], self.body["settings"])
        self.assertEqual(body, self.body)
        for name, content in before.items():
            with open(os.path.join(self.folder, name), "rb") as handle:
                self.assertEqual(handle.read(), content)

    def test_history_links_complete_and_incomplete_generations(self):
        first = generations.start(self.body)
        body = {**self.body, "name": first["name"]}
        second = generations.start(body)
        history = generations.history({**self.body, "name": second["name"]})
        self.assertEqual(len(history["generations"]), 2)
        original = next(item for item in history["generations"] if item["name"] == "seq")
        self.assertEqual(original["video"]["filename"], "seq_full.mp4")
        self.assertEqual(original["clips"][0]["file"]["filename"], "seg_0001.mp4")
        self.assertEqual(original["clips"][0]["number"], 1)

    def test_busy_and_write_failure_preserve_old_generation(self):
        with mock.patch("h3_continuity.takes.busy", return_value=True):
            with self.assertRaisesRegex(ValueError, "Finish|finish"):
                generations.start(self.body)
        with mock.patch.object(store, "write_manifest", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                generations.start(self.body)
        self.assertEqual(store.load_manifest(self.folder), self.manifest)
        self.assertTrue(os.path.isfile(os.path.join(self.folder, "seq_full.mp4")))

    def test_missing_media_is_omitted_without_losing_saved_snapshot(self):
        first = generations.start(self.body)
        os.remove(os.path.join(self.folder, "seq_full.mp4"))
        history = generations.history({**self.body, "name": first["name"]})
        self.assertIsNone(history["generations"][0]["video"])
        self.assertEqual(len(history["generations"][0]["clips"]), 1)

    def test_invalid_timeline_cannot_start_a_generation(self):
        with self.assertRaises(ValueError):
            generations.start({**self.body, "timeline": "broken"})
        self.assertEqual(os.listdir(self.root), ["seq"])

    def test_linked_sequence_name_resolves_from_a_static_producer(self):
        body = {**self.body, "name": None, "timeline_node": "1", "workflow": {
            "1": {"inputs": {"name": ["2", 0]}},
            "2": {"class_type": "PrimitiveString", "inputs": {"value": "seq"}}}}
        result = generations.start(body)
        self.assertTrue(result["ok"])
        self.assertEqual(store.load_manifest(os.path.join(self.root, result["name"]))["generation_history"][0]["name"], "seq")
