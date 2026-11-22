"""Incompatible joins need scoped consent; recovery preserves every old take on failure."""

import copy
import datetime
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import torch

from h3_continuity import regeneration, store, timeline as rules, timing
from .helpers import box, document


KNOWN = dict(width=64, height=64, context_frames=39, carry_audio=True, ref_image_size="match",
             audio_context_frames=0)


class RegenerationTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="h3c-regeneration-")
        self.line = document([box("a", 107), box("b", 102), box("c", 102),
                              box("independent", 107, cut=True),
                              box("memory", 107, cut=True, memory="selected",
                                  memories=[dict(box="a", frame=0, label="coat")]),
                              box("tail", 102)])
        self.manifest = dict(version=1, name="seq", segments=[], takes=[])
        for index, item in enumerate(self.line["boxes"], 1):
            carried = 0 if index in (1, 4, 5) else 39
            entry = dict(index=index, stem=store.stem(index), frames=141 if carried else 107,
                         context_frames=carried, latent_width=64, latent_height=64,
                         created=f"2026-11-06T10:0{index}:00", timeline={"box": item["id"]})
            self.manifest["segments"].append(entry)
            self.write(entry)
        store.write_manifest(self.folder, self.manifest)

    def tearDown(self):
        shutil.rmtree(self.folder)

    def write(self, entry):
        store.save_segment(self.folder, entry,
                           torch.zeros(1, 24, timing.tokens_for_frames(entry["frames"]), 4, 4),
                           torch.zeros(1, 32, 2, timing.ticks_for_frames(entry["frames"])), None)

    def inspect(self, known=KNOWN):
        return regeneration.inspect(self.folder, rules.parse(json.dumps(self.line)), known, "a")

    def incompatible(self):
        self.manifest["segments"][1]["context_frames"] = 0
        store.write_manifest(self.folder, self.manifest)
        return self.inspect()

    def test_compatible_join_needs_no_confirmation(self):
        result = self.inspect()
        self.assertFalse(result["needs_rebuild"])
        self.assertIsNone(result["receipt"])

    def test_linked_settings_do_not_block_no_join_or_deferred_compatible_checks(self):
        parsed = rules.parse(json.dumps(self.line))
        unknown = {key: None for key in KNOWN}
        result = regeneration.inspect(self.folder, parsed, unknown, "tail")
        self.assertFalse(result["needs_rebuild"])
        result = self.inspect(unknown)
        self.assertFalse(result["needs_rebuild"])
        self.assertTrue(result["deferred"])

    def test_preflight_resolves_typed_linked_settings_without_execution(self):
        from h3_continuity import nodes
        graph = {"1": {"inputs": {"width": ["2", 0]}},
                 "2": {"class_type": "PrimitiveInt", "inputs": {"value": 64}}}
        with mock.patch.object(nodes, "sequences_root", return_value=os.path.dirname(self.folder)):
            result = regeneration.request(dict(name=os.path.basename(self.folder), timeline=json.dumps(self.line),
                settings={**KNOWN, "width": None}, workflow=graph, timeline_node="1", box="a"))
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["needs_rebuild"])
        self.assertFalse(result.get("deferred"))

    def test_saved_editor_changes_while_sampling_reject_consent_but_seed_change_is_allowed(self):
        from h3_continuity import nodes, saved_state
        self.incompatible()
        values = {"1/H3C_Timeline/timeline": json.dumps(self.line), "1/H3C_Timeline/name": "seq",
                  **{f"1/H3C_Timeline/{key}": value for key, value in KNOWN.items()}}
        with mock.patch.object(nodes, "sequences_root", return_value=os.path.dirname(self.folder)), \
                mock.patch.object(saved_state, "read", side_effect=lambda *_: {"value": values, "revision": 5}):
            result = regeneration.request(dict(name=os.path.basename(self.folder), timeline=json.dumps(self.line),
                settings=KNOWN, box="a", editor={"graph": "g", "node": "1"}))
            self.assertIn("editor", result["receipt"])
            self.line["boxes"][0]["seed"] = 99
            values["1/H3C_Timeline/timeline"] = json.dumps(self.line)
            regeneration.validate(self.folder, rules.parse(json.dumps(self.line)), KNOWN, "a", result["receipt"])
            queued = rules.parse(json.dumps(self.line))
            self.line["boxes"][1]["cut"] = True
            values["1/H3C_Timeline/timeline"] = json.dumps(self.line)
            with self.assertRaisesRegex(ValueError, "changed.*confirm"):
                regeneration.validate(self.folder, queued, KNOWN, "a", result["receipt"])

    def test_prior_cut_and_memory_dependency_closure(self):
        before = store.manifest_fingerprint(self.folder)
        result = self.incompatible()
        self.assertTrue(result["needs_rebuild"])
        self.assertIn("overlap", result["reason"])
        self.assertEqual([item["id"] for item in result["affected"]], ["b", "c", "memory", "tail"])
        self.assertEqual([item["number"] for item in result["affected"]], [2, 3, 5, 6])
        self.assertNotEqual(before, store.manifest_fingerprint(self.folder))
        after = store.manifest_fingerprint(self.folder)
        self.inspect()
        self.assertEqual(after, store.manifest_fingerprint(self.folder))
        self.assertFalse(os.path.exists(os.path.join(self.folder, "takes")))

    def test_missing_latents_and_resolution_have_specific_reasons(self):
        self.assertIn("resolution", self.inspect({**KNOWN, "width": 128})["reason"])
        os.remove(os.path.join(self.folder, "seg_0002.safetensors"))
        self.assertIn("missing", self.inspect()["reason"])

    def test_too_short_to_pin_both_ends_offers_rebuild_without_length_changes(self):
        self.line["boxes"][0]["frames"] = 22
        result = self.inspect()
        self.assertTrue(result["needs_rebuild"])
        self.assertIn("short", result["reason"])
        self.assertEqual(self.line["boxes"][0]["frames"], 22)

    def test_consent_allows_only_target_seed_changes(self):
        result = self.incompatible()
        self.line["boxes"][0]["seed"] = 999
        parsed = rules.parse(json.dumps(self.line))
        self.assertEqual(regeneration.validate(self.folder, parsed, KNOWN, "a", result["receipt"]), self.inspect())
        self.line["boxes"][2]["prompt"] = "Different."
        with self.assertRaisesRegex(ValueError, "changed.*confirm"):
            regeneration.validate(self.folder, rules.parse(json.dumps(self.line)), KNOWN, "a", result["receipt"])

    def test_consent_rejects_manifest_file_and_setting_changes(self):
        result = self.incompatible()
        parsed = rules.parse(json.dumps(self.line))
        with self.assertRaisesRegex(ValueError, "changed.*confirm"):
            regeneration.validate(self.folder, parsed, {**KNOWN, "width": 128}, "a", result["receipt"])
        self.manifest["segments"][2]["created"] = "new"
        store.write_manifest(self.folder, self.manifest)
        with self.assertRaisesRegex(ValueError, "changed.*confirm"):
            regeneration.validate(self.folder, parsed, KNOWN, "a", result["receipt"])
        result = self.inspect()
        with open(os.path.join(self.folder, "seg_0003.safetensors"), "ab") as handle:
            handle.write(b"changed")
        with self.assertRaisesRegex(ValueError, "changed.*confirm"):
            regeneration.validate(self.folder, parsed, KNOWN, "a", result["receipt"])

    def recovery(self):
        result = self.incompatible()
        return dict(timeline=copy.deepcopy(self.line), settings=KNOWN, box="a", receipt=result["receipt"])

    def replacement(self):
        entry = {**copy.deepcopy(self.manifest["segments"][0]), "stem": "seg_0001-2", "created": "new"}
        self.write(entry)
        return entry

    def test_success_archives_only_target_and_dependent_takes(self):
        recovery = self.recovery()
        entry = self.replacement()
        saved = regeneration.commit(self.folder, entry, recovery, datetime.datetime.now())
        self.assertEqual([store.box_of(item) for item in saved["segments"]], ["a", "independent"])
        self.assertEqual(len(saved["takes"]), 5)
        for take in saved["takes"]:
            path = os.path.join(self.folder, take["folder"])
            self.assertTrue(any(file.endswith(".safetensors") for file in os.listdir(path)))
        self.assertTrue(os.path.isfile(os.path.join(self.folder, "seg_0004.safetensors")))
        self.assertEqual(store.load_manifest(self.folder), saved)

    def test_manifest_failure_restores_every_old_file_and_manifest(self):
        recovery = self.recovery()
        before = store.load_manifest(self.folder)
        with mock.patch.object(store, "write_manifest", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                regeneration.commit(self.folder, self.replacement(), recovery, datetime.datetime.now())
        self.assertEqual(store.load_manifest(self.folder), before)
        for item in before["segments"]:
            self.assertTrue(store.has_segment_latents(self.folder, item))

    def test_partial_archive_failure_restores_previous_moves(self):
        recovery = self.recovery()
        entry = self.replacement()
        original = store._move
        calls = []

        def fail_second(source, target, moves):
            calls.append(source)
            if len(calls) == 2:
                raise OSError("move failed")
            return original(source, target, moves)

        with mock.patch.object(store, "_move", fail_second):
            with self.assertRaisesRegex(OSError, "move failed"):
                regeneration.commit(self.folder, entry, recovery, datetime.datetime.now())
        for item in self.manifest["segments"]:
            self.assertTrue(store.has_segment_latents(self.folder, item))

    def test_commit_rejects_changed_state_before_archiving(self):
        recovery = self.recovery()
        entry = self.replacement()
        self.manifest["segments"][2]["created"] = "changed while sampling"
        store.write_manifest(self.folder, self.manifest)
        with self.assertRaisesRegex(ValueError, "changed.*confirm"):
            regeneration.commit(self.folder, entry, recovery, datetime.datetime.now())
        self.assertFalse(os.path.exists(os.path.join(self.folder, "takes")))

    def save(self, recovery, guide_frames=None):
        from h3_continuity import nodes, latents
        sequence = nodes.SequenceRef("seq", self.folder, 1, None, None, None)
        segment = nodes.SegmentPlan(sequence, 0, 0, 107, (4, 4), None, None,
                                    timeline={"box": "a"}, box_order=[item["id"] for item in self.line["boxes"]])
        segment.regeneration = recovery
        video = torch.ones(1, 24, timing.tokens_for_frames(107), 4, 4)
        audio = torch.ones(1, 32, 2, timing.ticks_for_frames(107))
        with mock.patch.object(latents, "split_h3_latent", return_value=(video, audio)), \
                mock.patch("h3_continuity.timeline_api.service.authorize_sequence", return_value=None):
            return nodes.H3C_SaveSegment.execute(segment, {}, 24, False, 16, guide_frames=guide_frames)

    def test_recovery_preserves_first_pass_guide_frames(self):
        self.save(self.recovery(), torch.ones(107, 64, 64, 3))
        entry = store.load_manifest(self.folder)["segments"][0]
        self.assertTrue(os.path.isfile(os.path.join(self.folder, entry["stem"] + "_guide.png")))

    def test_guide_write_failure_does_not_archive_existing_renders(self):
        recovery = self.recovery()
        before = store.load_manifest(self.folder)
        with mock.patch.object(store, "save_guide_frame", side_effect=OSError("guide write failed")):
            with self.assertRaisesRegex(OSError, "guide write failed"):
                self.save(recovery, torch.ones(107, 64, 64, 3))
        self.assertEqual(store.load_manifest(self.folder), before)
        for item in before["segments"]:
            self.assertTrue(store.has_segment_latents(self.folder, item))

    def test_consent_detects_changes_to_native_continuation_guides(self):
        receipt = self.incompatible()["receipt"]
        with open(os.path.join(self.folder, "seg_0001_guide.png"), "wb") as handle:
            handle.write(b"a changed native continuation guide")
        with self.assertRaisesRegex(ValueError, "changed.*confirm"):
            regeneration.validate(self.folder, rules.parse(json.dumps(self.line)), KNOWN, "a", receipt)

    def test_save_node_applies_recovery_only_after_writing_new_media(self):
        recovery = self.recovery()
        self.save(recovery)
        saved = store.load_manifest(self.folder)
        self.assertEqual([store.box_of(item) for item in saved["segments"]], ["a", "independent"])
        self.assertEqual(len(saved["takes"]), 5)

    def test_save_node_write_failure_keeps_old_renders_and_full_video(self):
        recovery = self.recovery()
        self.manifest["full_video"] = {"file": "seq_full.mp4"}
        store.write_manifest(self.folder, self.manifest)
        before = store.load_manifest(self.folder)
        with mock.patch.object(store, "save_segment", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                self.save(recovery)
        self.assertEqual(store.load_manifest(self.folder), before)
        for item in before["segments"]:
            self.assertTrue(store.has_segment_latents(self.folder, item))

    def test_project_plan_scopes_recovery_and_transports_receipt(self):
        from h3_continuity import nodes
        from tests.h3c.python.test_api_replacement import planner, project
        receipt = self.incompatible()["receipt"]
        value = project(self.line)
        value["sequence"] = os.path.basename(self.folder)
        value["prepared"]["settings"] = KNOWN
        value["prepared"]["workflow"] = {"timeline_node": "1", "api": {"1": {"inputs": {}}}}
        selection = dict(kind="boxes", ids=["a"], rerender=True, rebuild_continuity=receipt)
        native = {"boxes": [{"id": box["id"], "status": "outdated"} for box in self.line["boxes"]]}
        service = planner(native)
        with mock.patch.object(nodes, "sequences_root", return_value=os.path.dirname(self.folder)):
            plan = service.plan(value, selection)
        self.assertEqual([(unit["id"], unit["action"]) for unit in plan["units"]], [("box:a", "render")])
        self.assertEqual(plan["units"][0]["rebuild_continuity"], receipt)
        graph = service.selected_graph(value, plan["units"][0])
        line = json.loads(graph["1"]["inputs"]["timeline"])
        self.assertEqual(line["rebuild_continuity"], receipt)
        self.assertNotIn("rebuild_continuity", value["prepared"]["timeline"])
        self.assertEqual(plan["total_frames"], 107)

    def test_project_recovery_requires_single_selected_rerender(self):
        from h3_continuity.timeline_api.contracts import APIError
        from tests.h3c.python.test_api_replacement import planner, project
        receipt = self.incompatible()["receipt"]
        for selection in (dict(kind="boxes", ids=["a", "b"], rerender=True),
                          dict(kind="boxes", ids=["b"], rerender=True),
                          dict(kind="boxes", ids=["a"])):
            with self.subTest(selection=selection), self.assertRaises(APIError):
                planner({"boxes": []}).plan(project(self.line), {**selection, "rebuild_continuity": receipt})

    def test_selected_renderer_checks_consent_before_conditioning(self):
        from h3_continuity import conditioning, nodes, timeline_node
        receipt = self.incompatible()["receipt"]
        line = {**self.line, "render_box": 1}
        with mock.patch.object(nodes, "sequences_root", return_value=os.path.dirname(self.folder)), \
                mock.patch("h3_continuity.timeline_api.service.authorize_sequence", return_value=None), \
                mock.patch.object(conditioning, "encode") as encode:
            with self.assertRaisesRegex(ValueError, "confirm rebuilding"):
                timeline_node.H3C_Timeline.execute(clip=object(), vae=object(), name=os.path.basename(self.folder),
                    width=64, height=64, timeline=json.dumps(line))
            encode.assert_not_called()
            line["rebuild_continuity"] = receipt
            self.manifest["segments"][2]["created"] = "changed"
            store.write_manifest(self.folder, self.manifest)
            with self.assertRaisesRegex(ValueError, "changed.*confirm"):
                timeline_node.H3C_Timeline.execute(clip=object(), vae=object(), name=os.path.basename(self.folder),
                    width=64, height=64, timeline=json.dumps(line))
            encode.assert_not_called()

    def test_confirmed_renderer_prepares_an_unfrozen_end_and_defers_archival(self):
        from h3_continuity import conditioning, nodes, timeline_node, latents
        receipt = self.incompatible()["receipt"]
        line = {**self.line, "render_box": 1, "rebuild_continuity": receipt}
        sequence = nodes.SequenceRef("seq", self.folder, 1, None, None, None)
        segment = nodes.SegmentPlan(sequence, 0, 0, 107, (4, 4), None, None)
        before = store.load_manifest(self.folder)
        with mock.patch.object(nodes, "sequences_root", return_value=os.path.dirname(self.folder)), \
                mock.patch("h3_continuity.timeline_api.service.authorize_sequence", return_value=None), \
                mock.patch.object(conditioning, "encode", return_value=([], {})), \
                mock.patch.object(nodes, "prepare_segment", return_value=({}, [], None, segment, 0)), \
                mock.patch.object(timeline_node, "_status", return_value={}), \
                mock.patch.object(latents, "build_ending") as ending:
            timeline_node.H3C_Timeline.execute(clip=object(), vae=object(), name=os.path.basename(self.folder),
                width=64, height=64, timeline=json.dumps(line))
        ending.assert_not_called()
        self.assertEqual(segment.regeneration["receipt"], receipt)
        self.assertFalse(segment.timeline_complete)
        self.assertNotIn("rebuild_continuity", segment.timeline)
        self.assertEqual(store.load_manifest(self.folder), before)

    def test_saved_bridges_are_archived_but_replacement_candidates_are_kept(self):
        self.line["bridges"] = [{"before": "memory", "frames": 12, "seed": 1, "prompt": "Move."}]
        bridge = dict(box="memory", stem="bridge_memory", frames=107, context_frames=0,
                      timeline={"bridge": "memory"})
        self.write(bridge)
        self.manifest["bridges"] = [bridge]
        self.manifest["replacements"] = [dict(box="memory", stem="candidate_old", timeline={})]
        result = self.incompatible()
        self.assertEqual(result["bridges"], [{"id": "memory", "number": 5}])
        self.assertEqual(result["replacements"], [{"id": "memory", "number": 5}])
        recovery = dict(timeline=self.line, settings=KNOWN, box="a", receipt=result["receipt"])
        saved = regeneration.commit(self.folder, self.replacement(), recovery, datetime.datetime.now())
        self.assertEqual(saved["bridges"], [])
        self.assertEqual(saved["replacements"], self.manifest["replacements"])
        self.assertTrue(any(take.get("bridge") == "memory" for take in saved["takes"]))

    def test_recovery_job_finalizes_the_clip_without_requiring_full_video(self):
        from types import SimpleNamespace
        from h3_continuity.timeline_api.artifacts import Artifacts
        service = object.__new__(Artifacts)
        unit = dict(id="box:a", kind="box", frames=107, input_sha256="inputs")
        service.records = SimpleNamespace(get_blob_record=lambda *_: dict(
            verified=True, input_sha256="inputs", native_sha256="media"))
        service._body = lambda *_: {}
        service._unit = lambda *_: {"filename": "new.mp4"}
        service.snapshot = lambda *_, **__: {"id": "new-clip"}
        native = mock.Mock()
        with mock.patch("h3_continuity.timeline_api.artifacts.native_status", return_value={
                "unit_evidence": {"box:a": "media"}}):
            artifacts = service.finalize({"id": "p"}, {"plan": {"units": [unit]},
                "selection": {"rebuild_continuity": {"box": "a"}}}, native)
        self.assertEqual(artifacts, [{"id": "new-clip"}])
        native.status.assert_not_called()
