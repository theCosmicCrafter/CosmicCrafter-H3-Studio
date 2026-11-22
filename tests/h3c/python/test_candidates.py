import json
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

import torch

from h3_continuity import bridges, replacement, replacement_candidates as candidates, store

from .helpers import box, clip, cue, document
from h3_continuity import timeline as rules

KNOWN = {"width": 512, "height": 512, "context_frames": 39, "carry_audio": True}


def swap(**extra):
    return {"before": "b", "mode": "replace", "left": 14, "right": 15, "seed": 7, "prompt": "A turn.", **extra}


@mock.patch.object(replacement, "UNAVAILABLE", "")
class CandidateTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="h3c-candidates-")
        self.manifest = {"segments": []}
        for index, box_id in ((1, "a"), (2, "b")):
            self.save_box(index, box_id)

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def save_box(self, index, box_id):
        entry = {"index": index, "stem": store.stem(index), "frames": 107, "context_frames": 0,
                 "timeline": {"box": box_id}}
        store.save_segment(self.folder, entry, torch.zeros(1, 24, 32, 2, 2), torch.zeros(1, 32, 2, 178), None)
        self.manifest["segments"] = [e for e in self.manifest["segments"] if e["index"] != index] + [entry]
        self.manifest["segments"].sort(key=lambda e: e["index"])

    def timeline(self, *cues, **record):
        value = document([box("a", 107), box("b", 107, cut=True)], bridges=[swap(**record)],
                         audio_clips=[clip(locked=True, in_full_video=True)], dialogue={"version": 1, "cues": list(cues)})
        return rules.parse(json.dumps(value))

    def state(self, timeline, done=(0, 1), known=KNOWN):
        [found] = candidates.states(self.folder, timeline, self.manifest, set(done), known, 39)
        return found

    def add_candidate(self, state, recipe=None, video=True):
        cid = candidates.candidate_id("b", "2026-11-03T10:00:00", 7, state.region)
        entry = {"box": "b", "candidate": cid, "stem": candidates.stem("b", cid), "frames": 107, "context_frames": 39,
                 "played": 29, "created": "2026-11-03T10:00:00",
                 "timeline": {"replacement": "b", "candidate": cid, "region": state.region,
                              "recipe": recipe or state.recipe, "left": 14, "right": 15, "played": 29,
                              "settings": KNOWN}}
        if video:
            entry["video"] = {"file": entry["stem"] + ".mp4", "frames": 29, "fps": 24}
            with open(os.path.join(self.folder, entry["video"]["file"]), "wb") as handle:
                handle.write(b"mp4")
        candidates.add(self.manifest, entry)
        return cid

    def test_review_then_render_then_select(self):
        state = self.state(self.timeline())
        self.assertEqual(state.status, "review")
        self.assertIsNotNone(state.region)
        reviewed = self.timeline(review=state.region)
        self.assertEqual(self.state(reviewed).status, "next")
        cid = self.add_candidate(state)
        found = self.state(reviewed)
        self.assertEqual((found.status, found.selected), ("done", "none"))
        self.assertEqual([item["state"] for item in found.candidates], ["current"])
        self.assertEqual(candidates.active([found]), {})
        chosen = self.state(self.timeline(review=state.region, selected=cid))
        self.assertEqual(chosen.selected, "current")
        self.assertEqual(candidates.active([chosen])["b"]["candidate"], cid)

    def test_a_new_recipe_needs_another_candidate_but_keeps_the_selection(self):
        state = self.state(self.timeline())
        cid = self.add_candidate(state)
        reworded = self.state(self.timeline(review=state.region, selected=cid, prompt="Another turn."))
        self.assertEqual((reworded.status, reworded.selected), ("next", "current"))

    def test_a_rerendered_endpoint_makes_review_and_selection_stale(self):
        state = self.state(self.timeline())
        cid = self.add_candidate(state)
        time.sleep(0.02)
        self.save_box(2, "b")
        found = self.state(self.timeline(review=state.region, selected=cid))
        self.assertNotEqual(found.region, state.region)
        self.assertEqual((found.status, found.selected), ("review", "stale"))
        self.assertEqual([item["state"] for item in found.candidates], ["stale"])
        self.assertEqual(candidates.active([found]), {})

    def test_node_settings_compare_only_where_known(self):
        state = self.state(self.timeline())
        cid = self.add_candidate(state)
        reviewed = self.timeline(review=state.region, selected=cid)
        unknown = self.state(reviewed, known={**KNOWN, "width": None, "carry_audio": None})
        self.assertEqual((unknown.region, unknown.status, unknown.selected), (state.region, "done", "current"))
        changed = self.state(reviewed, known={**KNOWN, "carry_audio": False})
        self.assertEqual((changed.region, changed.status, changed.selected), (state.region, "next", "stale"))

    def test_a_selection_plays_only_in_a_reviewed_region(self):
        state = self.state(self.timeline())
        cid = self.add_candidate(state)
        unreviewed = self.state(self.timeline(review="older", selected=cid))
        self.assertEqual((unreviewed.status, unreviewed.selected), ("review", "current"))
        self.assertEqual(candidates.active([unreviewed]), {})

    def test_full_video_plays_current_selections_once_context_is_known(self):
        from h3_continuity import timeline_node
        state = self.state(self.timeline())
        cid = self.add_candidate(state)
        reviewed = self.timeline(review=state.region, selected=cid)
        found, replaced, note = timeline_node.replacement_states(self.folder, reviewed, self.manifest, {0, 1}, KNOWN)
        self.assertEqual(([s.selected for s in found], [e["candidate"] for e in replaced], note), (["current"], [cid], ""))
        unknown = {**KNOWN, "context_frames": None}
        found, replaced, note = timeline_node.replacement_states(self.folder, reviewed, self.manifest, {0, 1}, unknown)
        self.assertEqual((found, replaced), (None, []))
        self.assertIn("context_frames", note)
        unselected = self.timeline(review=state.region)
        self.assertEqual(timeline_node.replacement_states(self.folder, unselected, self.manifest, {0, 1}, unknown),
                         (None, [], ""))

    def test_a_saved_selection_needs_the_takes_it_was_rendered_from(self):
        state = self.state(self.timeline())
        cid = self.add_candidate(state)
        segments = {entry["index"]: entry for entry in self.manifest["segments"]}
        record = self.manifest["replacements"][0]["timeline"]
        record["from"], record["to"] = (bridges.link(self.folder, segments[n]) for n in (1, 2))
        wanted = [{"box": "b", "candidate": cid}]
        self.assertEqual([entry["candidate"] for entry in candidates.selected_entries(self.folder, self.manifest, wanted)],
                         [cid])
        self.assertEqual(candidates.selected_entries(self.folder, self.manifest, [{"box": "b", "candidate": "x"}]), [])
        time.sleep(0.02)
        self.save_box(2, "b")
        self.assertEqual(candidates.selected_entries(self.folder, self.manifest, wanted), [])

    def test_missing_candidate_files(self):
        state = self.state(self.timeline())
        cid = self.add_candidate(state, video=False)
        found = self.state(self.timeline(review=state.region, selected=cid))
        self.assertEqual((found.selected, found.candidates[0]["state"]), ("missing", "missing"))
        self.assertEqual(self.state(self.timeline(review=state.region, selected="gone")).selected, "missing")

    def test_waiting_and_problem(self):
        state = self.state(self.timeline(), done=(0,))
        self.assertEqual(state.status, "waiting")
        self.assertIn("box 2", state.note)
        protected = self.timeline(cue(start=4.0, end=4.5))
        self.assertEqual(self.state(protected).status, "problem")

    def test_nothing_renders_or_plays_while_replacement_is_unavailable(self):
        state = self.state(self.timeline())
        cid = self.add_candidate(state)
        selected = self.timeline(review=state.region, selected=cid)
        with mock.patch.object(replacement, "UNAVAILABLE", "switched off"):
            found = self.state(selected)
            waiting = self.state(self.timeline(), done=(0,))
            protected = self.state(self.timeline(cue(start=4.0, end=4.5)))
        self.assertEqual((found.status, found.note, found.selected), ("unavailable", "switched off", "current"))
        self.assertEqual(candidates.active([found]), {})
        self.assertEqual([waiting.status, protected.status], ["unavailable", "unavailable"])

    def test_adding_a_candidate_keeps_the_others(self):
        state = self.state(self.timeline())
        first = self.add_candidate(state)
        self.manifest["replacements"][0]["created"] = "earlier"
        second = candidates.candidate_id("b", "later", 8, state.region)
        candidates.add(self.manifest, {"box": "b", "candidate": second})
        self.assertEqual([entry["candidate"] for entry in self.manifest["replacements"]], [first, second])
        self.assertNotEqual(first, second)

    def test_stems_never_match_a_bridge_or_another_candidate(self):
        stem = candidates.stem("b", "1a2b3c4d")
        self.assertEqual(stem, "replace@b-1a2b3c4d")
        self.assertFalse(stem.startswith(("bridge@b.", "bridge@b_")))
        self.assertTrue(candidates.stem("Box 1", "1a2b3c4d").startswith("replace@_"))


class EndpointTest(unittest.TestCase):
    def test_candidate_run_reads_the_surviving_footage(self):
        import comfy.nested_tensor
        from .test_latent_window import ChunkVAE, numbers, source
        timeline = rules.parse(json.dumps(document([box("a", 107), box("b", 107, cut=True)], bridges=[swap()])))
        shape = replacement.geometry(timeline, timeline.replacements[0], 39)
        state = candidates.State(timeline.replacements[0], 1, "next", "", shape, "region", "recipe")
        before = source()
        after = tuple(part + 1000 for part in source())
        empty = {"samples": comfy.nested_tensor.NestedTensor((torch.zeros(1, 24, 32, 2, 2), torch.zeros(1, 32, 2, 178)))}
        latent, _, _, segment = candidates.prepare(state, empty, None, None, ("seq", "folder", 2, None), before, after,
                                                   ChunkVAE(), True)
        video, audio = latent["samples"].tensors
        video_mask, audio_mask = latent["noise_mask"].tensors
        self.assertEqual(numbers(video[:, :, :12]), [54, 55, 59, 63, 67, 71, 72, 76, 80, 84, 88, 89])
        self.assertEqual(numbers(video[:, :, 20:]), [1015, 1016, 1020, 1024, 1028, 1032, 1033, 1037, 1041, 1045,
                                                     1049, 1050])
        self.assertEqual(video_mask[0, 0, :, 0, 0].tolist(), [0.0] * 12 + [1.0] * 8 + [0.0] * 12)
        self.assertEqual(audio[0, 0, 0, 0].item(), 90)
        self.assertEqual(audio[0, 0, 0, 113].item(), 1000 + 25)
        self.assertEqual(audio_mask[0, 0, 0, 64:66].tolist(), [0.0, 1.0])
        self.assertEqual((segment.context_frames, segment.frames, segment.preserve_following), (39, 107, True))


if __name__ == "__main__":
    unittest.main()
