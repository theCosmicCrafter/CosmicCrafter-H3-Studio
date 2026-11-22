"""Video layers render right after their clip, save beside the segments and show in the status."""

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import torch

from h3_continuity import layers, store, timing

from .helpers import box, document

KNOWN = dict(width=64, height=64, context_frames=39, carry_audio=True, ref_image_size="match", audio_context_frames=0)


def video(layer_id, prompt="Another angle."):
    return {"id": layer_id, "seed": 7, "prompt": prompt, "first": "", "last": "", "previews": [], "memory": "off",
            "memories": [], "dialogue": "cues"}


def line(**extra):
    stacked = box("b", 90, "The lamp.", cut=True, exact=True, layers=[video("b2"), video("b3")],
                  switch={"cuts": [{"at": 30, "to": "b2"}, {"at": 60, "to": "b3"}], "fade": 6, "sound": "screen"})
    return document([box("a", 107), stacked, box("c", 73, "After.", cut=True)], requires=["video-layers-1"], **extra)


def write(folder, entry):
    store.save_segment(folder, entry, torch.zeros(1, 24, timing.tokens_for_frames(entry["frames"]), 4, 4),
                       torch.zeros(1, 32, 2, timing.ticks_for_frames(entry["frames"])), None)


class LayerRenderTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="h3c-layers-")
        self.manifest = dict(version=1, name="seq", segments=[], takes=[])
        store.write_manifest(self.folder, self.manifest)

    def tearDown(self):
        shutil.rmtree(self.folder)

    def save_box(self, index, box_id, frames):
        entry = dict(index=index, stem=store.stem(index), frames=frames, context_frames=0, latent_width=64,
                     latent_height=64, created=f"2026-11-13T10:0{index}:00", timeline={"box": box_id})
        write(self.folder, entry)
        self.manifest["segments"].append(entry)
        store.write_manifest(self.folder, self.manifest)

    def save_layer(self, layer_id, clip_id="b"):
        entry = dict(layer=layer_id, box=clip_id, stem=layers.stem(layer_id), frames=90, context_frames=0,
                     latent_width=64, latent_height=64, created="2026-11-13T11:00:00",
                     timeline={"layer": layer_id, "box": clip_id, "layout": "old"})
        write(self.folder, entry)
        self.manifest.setdefault("layers", []).append(entry)
        store.write_manifest(self.folder, self.manifest)

    def run_timeline(self, timeline):
        from h3_continuity import conditioning, nodes, timeline_node
        sequence = nodes.SequenceRef("seq", self.folder, 1, None, None, None)
        segment = nodes.SegmentPlan(sequence, 0, 0, 90, (4, 4), None, None)
        with mock.patch.object(nodes, "sequences_root", return_value=os.path.dirname(self.folder)), \
                mock.patch("h3_continuity.timeline_api.service.authorize_sequence", return_value=None), \
                mock.patch.object(conditioning, "encode", return_value=([], {})), \
                mock.patch.object(nodes, "prepare_segment", return_value=({}, [], None, segment, 0)), \
                mock.patch.object(timeline_node, "_status", return_value={}):
            timeline_node.H3C_Timeline.execute(clip=object(), vae=object(), name=os.path.basename(self.folder),
                                               width=64, height=64, timeline=json.dumps(timeline))
        return segment

    def test_layers_render_right_after_their_clip(self):
        self.save_box(1, "a", 107)
        self.save_box(2, "b", 90)
        segment = self.run_timeline(line())
        self.assertEqual((segment.timeline["layer"], segment.timeline["box"]), ("b2", "b"))
        self.assertEqual(segment.timeline["layer_ids"], ["b2", "b3"])
        self.assertEqual(segment.timeline["seed"], 7)
        self.assertEqual(segment.timeline["settings"]["context_frames"], 0)
        self.assertFalse(segment.timeline_complete)
        self.save_layer("b2")
        self.assertEqual(self.run_timeline(line()).timeline["layer"], "b3")
        self.save_layer("b3")
        segment = self.run_timeline(line())
        self.assertEqual(segment.timeline["box"], "c")
        self.assertNotIn("layer", segment.timeline)
        self.assertTrue(segment.timeline_complete)

    def test_the_last_video_completes_the_timeline(self):
        self.save_box(1, "a", 107)
        self.save_box(2, "b", 90)
        self.save_box(3, "c", 73)
        self.save_layer("b2")
        segment = self.run_timeline(line())
        self.assertEqual(segment.timeline["layer"], "b3")
        self.assertTrue(segment.timeline_complete)

    def test_a_clip_is_not_complete_without_its_videos(self):
        self.save_box(1, "a", 107)
        segment = self.run_timeline(line())
        self.assertEqual(segment.timeline["box"], "b")
        self.save_box(2, "b", 90)
        self.save_layer("b2")
        self.save_layer("b3")
        self.manifest["segments"] = self.manifest["segments"][:1]
        store.write_manifest(self.folder, self.manifest)
        timeline = line()
        timeline["boxes"] = timeline["boxes"][:2]
        self.assertTrue(self.run_timeline(timeline).timeline_complete)
        self.manifest["layers"] = self.manifest["layers"][:1]
        store.write_manifest(self.folder, self.manifest)
        self.assertFalse(self.run_timeline(timeline).timeline_complete)

    def test_render_layer_waits_for_its_clip(self):
        self.save_box(1, "a", 107)
        with self.assertRaisesRegex(ValueError, r"^H3 Timeline: render clip 2 first; its video 2b plays inside it$"):
            self.run_timeline(line(render_layer="b2"))

    def test_render_layer_renders_that_video_again(self):
        self.save_box(1, "a", 107)
        self.save_box(2, "b", 90)
        self.save_layer("b2")
        self.assertEqual(self.run_timeline(line(render_layer="b2")).timeline["layer"], "b2")

    def test_save_layer_keeps_segments(self):
        from h3_continuity import latents, nodes
        self.save_box(1, "a", 107)
        self.save_layer("b2")
        self.save_layer("gone")
        before = store.load_manifest(self.folder)["segments"]
        sequence = nodes.SequenceRef("seq", self.folder, 2, None, None, None)
        segment = nodes.SegmentPlan(sequence, 0, 0, 90, (4, 4), None, None, box_order=["a", "b", "c"],
                                    timeline={"layer": "b2", "box": "b", "layout": "new", "layer_ids": ["b2", "b3"],
                                              "seed": 7})
        latent_video = torch.ones(1, 24, timing.tokens_for_frames(90), 4, 4)
        latent_audio = torch.ones(1, 32, 2, timing.ticks_for_frames(90))
        with mock.patch.object(latents, "split_h3_latent", return_value=(latent_video, latent_audio)), \
                mock.patch("h3_continuity.timeline_api.service.authorize_sequence", return_value=None):
            nodes.H3C_SaveSegment.execute(segment, {}, 24, False, 16, images=torch.rand(90, 64, 64, 3))
        saved = store.load_manifest(self.folder)
        self.assertEqual(saved["segments"], before)
        self.assertEqual([entry["layer"] for entry in saved["layers"]], ["b2"])
        entry = saved["layers"][0]
        self.assertEqual((entry["box"], entry["stem"], entry["timeline"]["layout"]), ("b", "layer@b2", "new"))
        self.assertNotIn("layer_ids", entry["timeline"])
        self.assertTrue(os.path.isfile(os.path.join(self.folder, "layer@b2.mp4")))
        self.assertTrue(store.has_segment_latents(self.folder, entry))
        self.assertEqual(sorted(take["layer"] for take in saved["takes"]), ["b2", "gone"])
        self.assertFalse(os.path.exists(os.path.join(self.folder, "layer@gone.safetensors")))

    def status(self, timeline):
        from h3_continuity import bridges, timeline as rules, timeline_node
        parsed = rules.parse(json.dumps(timeline))
        known = bridges.settings(64, 64, 39, True)
        with mock.patch("h3_continuity.timeline_api.service.authorize_sequence", return_value=None):
            return timeline_node._status("seq", self.folder, parsed, store.load_manifest(self.folder),
                                         lambda index, entry: True, known=known)

    def test_status_lists_videos(self):
        self.save_box(1, "a", 107)
        self.save_box(2, "b", 90)
        status = self.status(line())
        self.assertEqual(status["boxes"][1]["videos"], [{"id": "b2", "status": "next"}, {"id": "b3", "status": "pending"}])
        self.assertNotIn("videos", status["boxes"][0])
        self.assertEqual((status["layers_remaining"], status["done_layers"]), (2, []))
        self.assertEqual(status["message"], "Clip 2's video 2b is next.")

    def test_status_names_waiting_and_saved_videos(self):
        self.save_box(1, "a", 107)
        status = self.status(line())
        self.assertEqual([item["status"] for item in status["boxes"][1]["videos"]], ["waiting", "waiting"])
        self.assertEqual(status["boxes"][1]["videos"][0]["reason"], "render clip 2 first; its video 2b plays inside it")
        self.assertEqual(status["message"], "Box 2 is next.")
        self.save_box(2, "b", 90)
        self.save_layer("b2")
        item = self.status(line())["boxes"][1]["videos"][0]
        self.assertEqual(item["status"], "outdated")
        self.assertEqual(item["reason"], "Its prompt or settings changed since it was rendered.")

    def test_without_layers_status_is_unchanged(self):
        self.save_box(1, "a", 107)
        status = self.status(document([box("a", 107), box("c", 73, cut=True)]))
        for key in ("done_layers", "layers_remaining"):
            self.assertNotIn(key, status)
        self.assertTrue(all("videos" not in item for item in status["boxes"]))


class LayerBookkeepingTest(unittest.TestCase):
    def setUp(self):
        from h3_continuity import timeline as rules
        self.root = tempfile.mkdtemp(prefix="h3c-layer-books-")
        self.folder = os.path.join(self.root, "seq")
        os.makedirs(self.folder)
        self.parsed = rules.parse(json.dumps(line()))
        self.manifest = dict(version=1, name="seq", segments=[], takes=[])
        for index, (box_id, frames) in enumerate((("a", 107), ("b", 90)), 1):
            entry = dict(index=index, stem=store.stem(index), frames=frames, context_frames=0, latent_width=64,
                         latent_height=64, created=f"2026-11-13T10:0{index}:00", timeline={"box": box_id})
            write(self.folder, entry)
            self.manifest["segments"].append(entry)
        store.write_manifest(self.folder, self.manifest)

    def tearDown(self):
        shutil.rmtree(self.root)

    def layer_entry(self, layer_id="b2", seed=7):
        item = next(item for item in self.parsed.layers["b"] if item["id"] == layer_id)
        stem = layers.stem(layer_id)
        entry = dict(layer=layer_id, box="b", stem=stem, frames=90, context_frames=0, latent_width=64,
                     latent_height=64, created="2026-11-13T11:00:00",
                     video={"file": stem + ".mp4", "frames": 90, "fps": 24},
                     timeline={"layer": layer_id, "box": "b", "seed": seed,
                               "layout": layers.layer_key(self.parsed, 1, {**item, "seed": seed}, 39),
                               "settings": layers.settings(self.parsed, 1, item, KNOWN, 39)})
        write(self.folder, entry)
        with open(os.path.join(self.folder, entry["video"]["file"]), "wb") as handle:
            handle.write(b"video")
        return entry

    def archived(self, entry):
        import datetime
        self.manifest.setdefault("layers", []).append(entry)
        layers.archive(self.folder, self.manifest, entry, datetime.datetime(2026, 11, 13, 12))
        store.write_manifest(self.folder, self.manifest)

    def sequence(self):
        from h3_continuity import nodes, takes
        with mock.patch.object(nodes, "sequences_root", return_value=self.root):
            return takes._Sequence({"name": "seq", "timeline": json.dumps(line()), "settings": KNOWN})

    def test_layer_take_is_usable(self):
        from h3_continuity import takes
        self.archived(self.layer_entry(seed=99))
        sequence = self.sequence()
        [take] = sequence.takes_of("layer", "b2")
        self.assertEqual(takes._target(take["entry"]), ("layer", "b2"))
        self.assertEqual(sequence.why(take), "")
        self.assertEqual(takes.layer_fit(sequence, "b2", take), "")

    def test_layer_take_names_what_changed(self):
        from h3_continuity import takes
        entry = self.layer_entry()
        entry["timeline"]["layout"] = "old"
        write(self.folder, entry)
        self.archived(entry)
        sequence = self.sequence()
        [take] = sequence.takes_of("layer", "b2")
        self.assertEqual(sequence.why(take), "its prompt or settings changed since it was rendered")
        take["entry"] = {**take["entry"], "timeline": {**take["entry"]["timeline"], "layer": "zz"}}
        self.assertEqual(sequence.why(take), "its video isn't in the clip")
        take["entry"]["timeline"] = {**take["entry"]["timeline"], "box": "gone"}
        self.assertEqual(sequence.why(take), "its clip isn't in the Timeline")

    def test_delete_unusable_keeps_layer_takes(self):
        from h3_continuity import nodes, takes
        self.archived(self.layer_entry())
        with mock.patch.object(nodes, "sequences_root", return_value=self.root), \
                mock.patch("h3_continuity.timeline_api.service.authorize_sequence", return_value=None):
            found = takes.delete({"name": "seq", "timeline": json.dumps(line()), "settings": KNOWN,
                                  "scope": "unusable"})
        self.assertEqual((found["ok"], found["count"]), (True, 0))

    def fingerprint(self, manifest):
        from h3_continuity import regeneration
        seen = []
        dumps = json.dumps

        def capture(value, **kwargs):
            seen.append(value)
            return dumps(value, **kwargs)

        with mock.patch.object(regeneration.json, "dumps", side_effect=capture):
            digest = regeneration._fingerprint(self.folder, self.parsed, KNOWN, manifest, 0)
        return digest, seen[-1]

    def test_fingerprint_without_layers_is_unchanged(self):
        import dataclasses
        from h3_continuity import timeline as rules
        plain = rules.parse(json.dumps(document([box("a", 107), box("b", 90, cut=True)])))
        self.parsed = plain
        _, value = self.fingerprint(store.load_manifest(self.folder))
        fields = {field.name for field in dataclasses.fields(rules.Timeline)} - {"layers", "switches", "render_layer"}
        self.assertEqual(set(value[1]), fields)
        self.assertEqual(set(value[3]), {"segments", "bridges", "replacements"})

    def test_fingerprint_follows_layer_files(self):
        entry = self.layer_entry()
        manifest = {**store.load_manifest(self.folder), "layers": [entry]}
        before, value = self.fingerprint(manifest)
        self.assertIn("layers", value[1])
        self.assertEqual(value[3]["layers"], [entry])
        with open(os.path.join(self.folder, entry["video"]["file"]), "wb") as handle:
            handle.write(b"a longer video")
        self.assertNotEqual(self.fingerprint(manifest)[0], before)

    def test_export_preflight_sees_layer_files(self):
        from h3_continuity import generations
        entry = self.layer_entry()
        manifest = {**store.load_manifest(self.folder), "layers": [entry]}
        store.write_manifest(self.folder, manifest)
        archive = {"format": generations.FORMAT, "version": 1, "story": {}, "assets": [], "timeline": json.dumps(line()),
                   "takes": {"sequence": "seq", "manifest": manifest, "files": []}}
        with mock.patch.object(generations, "_root", return_value=os.path.realpath(self.root)):
            with self.assertRaisesRegex(ValueError, "missing required sidecar: seg_0001.safetensors"):
                generations.preflight_generation(archive)
            manifest["segments"] = []
            store.write_manifest(self.folder, manifest)
            with self.assertRaisesRegex(ValueError, "missing required sidecar: layer@b2.safetensors"):
                generations.preflight_generation(archive)


if __name__ == "__main__":
    unittest.main()
