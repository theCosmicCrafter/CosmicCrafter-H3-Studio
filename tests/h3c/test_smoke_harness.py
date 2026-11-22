import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))
import smoke  # noqa: E402

SCENE = {"name": "t", "settings": {"context_frames": 39, "carry_audio": True},
         "timeline": {"version": 1, "boxes": [{"id": "a", "frames": 124, "seed": 1, "prompt": "p"},
                                              {"id": "b", "frames": 124, "seed": 2, "prompt": "q"}]}}
GRAPH = {"1": {"class_type": "H3C_Timeline", "inputs": {"width": 960}}, "2": {"class_type": "X", "inputs": {}}}


class MergeTest(unittest.TestCase):
    def test_recursive_merge_replace_and_delete(self):
        self.assertEqual(smoke.merge({"a": {"x": 1, "y": 2}, "b": 1}, {"a": {"y": 3, "x": None}, "c": [1]}),
                         {"a": {"y": 3}, "b": 1, "c": [1]})

    def test_arm_scene_patches_settings_timeline_and_boxes_by_id(self):
        scene = smoke.arm_scene(SCENE, {"settings": {"context_frames": 22}, "timeline": {"prompt": "shared"},
                                        "boxes": {"b": {"seed": 9, "memory": "off"}}})
        self.assertEqual(scene["settings"], {"context_frames": 22, "carry_audio": True})
        self.assertEqual(scene["timeline"]["prompt"], "shared")
        self.assertEqual(scene["timeline"]["boxes"][1], {"id": "b", "frames": 124, "seed": 9, "prompt": "q", "memory": "off"})
        self.assertEqual(SCENE["timeline"]["boxes"][1]["seed"], 2, "the base scene is not mutated")

    def test_unknown_box_id_fails(self):
        with self.assertRaises(ValueError):
            smoke.arm_scene(SCENE, {"boxes": {"zz": {"seed": 1}}})

    def test_arm_graph_adds_patches_and_deletes_nodes(self):
        graph = smoke.arm_graph(GRAPH, {"graph": {"1": {"inputs": {"width": 640}}, "2": None,
                                                  "9": {"class_type": "Y", "inputs": {}}}})
        self.assertEqual(graph, {"1": {"class_type": "H3C_Timeline", "inputs": {"width": 640}},
                                 "9": {"class_type": "Y", "inputs": {}}})


class FullVideoTest(unittest.TestCase):
    def test_last_full_video_view_resolves_under_output_root(self):
        root = Path(tempfile.mkdtemp())
        (root / "h3_sequences" / "p").mkdir(parents=True)
        (root / "h3_sequences" / "p" / "full.mp4").write_bytes(b"x")
        records = [{"timeline": [{"full_video": None}]},
                   {"timeline": [{"full_video": {"filename": "full.mp4", "subfolder": "h3_sequences/p", "type": "output"}}]}]
        self.assertEqual(smoke.full_video(root, records), root / "h3_sequences" / "p" / "full.mp4")
        self.assertIsNone(smoke.full_video(root, records[:1]))


class RunTest(unittest.TestCase):
    def test_two_arms_render_copy_probe_and_summarise(self):
        root, out = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        seen = []

        def render(server, graph, scene, project, cap):
            seen.append((project, scene["settings"]["context_frames"], graph["1"]["inputs"]["width"]))
            folder = root / "h3_sequences" / project
            folder.mkdir(parents=True)
            (folder / "full.mp4").write_bytes(project.encode())
            yield {"seconds": 1.5, "status": "success", "info": [], "timeline": [
                {"next": None, "full_video": {"filename": "full.mp4", "subfolder": f"h3_sequences/{project}", "type": "output"}}]}

        spec = {"scene": SCENE, "arms": {"base": {}, "c22": {"settings": {"context_frames": 22}}}}
        summary = smoke.run(spec, GRAPH, "s2", out, root, server="http://x", cap=60, render=render,
                            probe=lambda path: {"duration": 9.9, "frames": 238, "audio": True},
                            compose=lambda clips, labels, path: Path(path).write_bytes(b"sbs"))
        self.assertEqual(seen, [("ps-s2-base", 39, 960), ("ps-s2-c22", 22, 960)])
        self.assertEqual((out / "c22.mp4").read_bytes(), b"ps-s2-c22")
        self.assertTrue((out / "side_by_side.mp4").is_file())
        self.assertEqual(summary["arms"]["c22"]["runs"], [{"seconds": 1.5, "status": "success"}])
        self.assertEqual(summary["arms"]["base"]["probe"], {"duration": 9.9, "frames": 238, "audio": True})
        self.assertEqual(json.loads((out / "summary.json").read_text(encoding="utf-8")), summary)

    def test_arm_without_full_video_is_reported_not_composed(self):
        out = Path(tempfile.mkdtemp())

        def render(server, graph, scene, project, cap):
            yield {"seconds": 0.2, "status": "error", "info": ["boom"], "timeline": []}

        composed = []
        summary = smoke.run({"scene": SCENE, "arms": {"base": {}, "on": {}}}, GRAPH, "s1", out, out, server="x",
                            cap=1, render=render, probe=lambda p: {}, compose=lambda *a: composed.append(a))
        self.assertIsNone(summary["arms"]["on"]["video"])
        self.assertEqual(summary["arms"]["on"]["info"], ["boom"])
        self.assertEqual(composed, [])


class RejectedArmTest(unittest.TestCase):
    def test_a_rejected_prompt_is_recorded_and_the_batch_goes_on(self):
        import io
        import urllib.error
        out = Path(tempfile.mkdtemp())
        rendered = []

        def render(server, graph, scene, project, cap):
            rendered.append(project)
            if project.endswith("bad"):
                raise urllib.error.HTTPError("http://x/prompt", 400, "Bad Request", {}, io.BytesIO(b'{"error": "missing node"}'))
            yield {"seconds": 1.0, "status": "success", "info": [], "timeline": []}

        summary = smoke.run({"scene": SCENE, "arms": {"bad": {}, "good": {}}}, GRAPH, "s9", out, out, server="x", cap=1,
                            render=render, probe=lambda p: {}, compose=lambda *a: None)
        self.assertEqual(rendered, ["ps-s9-bad", "ps-s9-good"])
        self.assertIn("HTTP 400", summary["arms"]["bad"]["info"][0])
        self.assertIn("missing node", summary["arms"]["bad"]["info"][0])


class ScenarioFilesTest(unittest.TestCase):
    def test_every_smoke_spec_names_a_scene_whose_timeline_parses(self):
        here = Path(__file__).resolve().parents[2]
        specs = sorted((here / "examples" / "prefixstream_scenes" / "smoke").glob("*.json"))
        self.assertTrue(specs)
        sys.path.insert(0, str(here))
        from h3_continuity import timeline
        for path in specs:
            spec = json.loads(path.read_text(encoding="utf-8"))
            scene = smoke.load_scene(spec, here)
            for name, arm in spec["arms"].items():
                with self.subTest(spec=path.name, arm=name):
                    timeline.parse(json.dumps(smoke.arm_scene(scene, arm)["timeline"]))


if __name__ == "__main__":
    unittest.main()
