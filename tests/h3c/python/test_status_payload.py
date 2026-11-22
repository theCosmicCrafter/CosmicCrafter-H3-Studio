import json
import os
import shutil
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock

import torch

from h3_continuity import replacement, replacement_candidates as candidates, store, takes, timeline_node
from h3_continuity import timeline as rules

from .helpers import box, clip, cue, document

KNOWN = {"width": 512, "height": 512, "context_frames": 39, "carry_audio": True}


def swap(**extra):
    return {"before": "b", "mode": "replace", "left": 14, "right": 15, "seed": 7, "prompt": "A turn.", **extra}


def view(filename, version):
    return {"filename": filename, "v": version}


class SavedBoxes(unittest.TestCase):
    """Three 107-frame boxes saved in a temporary sequence folder."""

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="h3c-status-")
        self.manifest = {"segments": []}
        for index, box_id in ((1, "a"), (2, "b"), (3, "c")):
            self.save_box(index, box_id)

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def save_box(self, index, box_id):
        entry = {"index": index, "stem": store.stem(index), "frames": 107, "context_frames": 0,
                 "created": f"2026-11-03T10:0{index}:00", "timeline": {"box": box_id}}
        store.save_segment(self.folder, entry, torch.zeros(1, 24, 32, 2, 2), torch.zeros(1, 32, 2, 178), None)
        self.manifest["segments"] = [e for e in self.manifest["segments"] if e["index"] != index] + [entry]
        self.manifest["segments"].sort(key=lambda e: e["index"])

    def value(self, *cues, bridges=None, boxes=None, clips=None, **record):
        return document(boxes or [box("a", 107), box("b", 107, cut=True), box("c", 107, cut=True)],
                        bridges=[swap(**record)] if bridges is None else bridges,
                        audio_clips=[clip(locked=True, in_full_video=True)] if clips is None else clips,
                        dialogue={"version": 1, "cues": list(cues)})

    def timeline(self, *cues, **extra):
        return rules.parse(json.dumps(self.value(*cues, **extra)))

    def state(self, timeline, known=KNOWN):
        found = candidates.states(self.folder, timeline, self.manifest, {0, 1, 2}, known, 39)
        return next(state for state in found if state.bridge["before"] == "b")

    def item(self, timeline):
        return candidates.item(self.state(timeline), timeline, 39, view,
                               candidates.takes(self.folder, timeline, self.manifest))

    def add_candidate(self, state, preview=True):
        cid = candidates.candidate_id("b", "2026-11-03T11:00:00", 7, state.region)
        entry = {"box": "b", "candidate": cid, "stem": candidates.stem("b", cid), "frames": 107, "context_frames": 39,
                 "played": 29, "created": "2026-11-03T11:00:00",
                 "video": {"file": candidates.stem("b", cid) + ".mp4", "frames": 29, "fps": 24},
                 "timeline": {"replacement": "b", "candidate": cid, "region": state.region, "recipe": state.recipe,
                              "left": 14, "right": 15, "played": 29, "seed": 7, "settings": KNOWN}}
        if preview:
            entry["preview"] = {"file": entry["stem"] + "_preview.mp4", "original": entry["stem"] + "_original.mp4",
                                "frames": 125, "region": [48, 77], "fps": 24}
        with open(os.path.join(self.folder, entry["video"]["file"]), "wb") as handle:
            handle.write(b"mp4")
        candidates.add(self.manifest, entry)
        return cid

    def status(self, timeline, known=KNOWN):
        return timeline_node._status("seq", self.folder, timeline, self.manifest, lambda index, entry: True,
                                     known=known)


@mock.patch.object(replacement, "UNAVAILABLE", "")
class ReplacementItemTest(SavedBoxes):
    def test_an_unconfirmed_region_shows_its_exact_coverage_and_choices(self):
        item = self.item(self.timeline())
        self.assertEqual((item["box"], item["mode"], item["status"], item["reviewed"]), ("b", "replace", "review", False))
        self.assertEqual(item["region"], {"join": 107, "start": 93, "end": 122, "left": 14, "right": 15, "frames": 29,
                                          "context_frames": 39, "ending_frames": 39,
                                          "before": ["a", 93, 107], "after": ["b", 0, 15]})
        self.assertEqual(item["region_key"], self.state(self.timeline()).region)
        self.assertEqual(item["options"], [[12, list(range(13))], [29, list(range(30))], [46, list(range(47))]])
        self.assertEqual(item["proposal"], [29, 14])
        self.assertEqual((item["protected"], item["candidates"]), ([], []))
        self.assertEqual((item["selected"], item["selection"], item["plays"]), (None, "none", False))
        self.assertIn("confirm the region", item["note"])

    def test_names_the_take_each_endpoint_box_is_on(self):
        timeline = self.timeline()
        current = candidates.takes(self.folder, timeline, self.manifest)
        self.assertIsNotNone(current["a"])
        self.assertEqual(self.item(timeline)["takes"], {"a": current["a"], "b": current["b"]})

    def test_protected_speech_is_listed_and_removes_choices(self):
        from h3_continuity import dialogue
        speech = cue(start=4.6, end=5.0)
        speech["aligned"] = dialogue.alignment_key(speech)
        item = self.item(self.timeline(speech))
        self.assertEqual(item["protected"], [{"kind": "on_screen", "start": 110, "end": 120, "id": "c1",
                                              "speaker": "Mara", "text": "Hello there.", "slot": "audio1",
                                              "checked": True}])
        self.assertEqual(item["status"], "problem")
        allowed = dict(item["options"])
        self.assertEqual((allowed[12], allowed[29], allowed[46]), ([9, 10, 11, 12], [26, 27, 28, 29], [43, 44, 45, 46]))
        self.assertEqual(item["proposal"], [29, 26])

    def test_voiceover_and_observed_marks_are_listed_without_blocking(self):
        from h3_continuity import dialogue
        line = cue(start=4.0, end=4.5, portrayal="voiceover")
        line["aligned"] = dialogue.alignment_key(line)
        value = self.value(line)
        take = candidates.takes(self.folder, rules.parse(json.dumps(value)), self.manifest)["b"]
        value["dialogue"]["observed"] = [{"id": "o1", "box": "b", "take": take, "start": 40, "end": 50,
                                          "label": "door slam"}]
        item = self.item(rules.parse(json.dumps(value)))
        self.assertEqual([mark["kind"] for mark in item["protected"]], ["voiceover", "observed"])
        self.assertEqual(item["protected"][1], {"kind": "observed", "start": 147, "end": 157, "id": "o1",
                                                "label": "door slam", "box": "b", "current": True})
        self.assertEqual(item["status"], "review")

    def test_a_selected_candidate_lists_its_videos_and_plays(self):
        state = self.state(self.timeline())
        cid = self.add_candidate(state)
        item = self.item(self.timeline(review=state.region, selected=cid))
        self.assertEqual((item["status"], item["reviewed"], item["selected"], item["selection"], item["plays"]),
                         ("done", True, cid, "current", True))
        [listed] = item["candidates"]
        self.assertEqual(listed["candidate"], cid)
        self.assertEqual((listed["state"], listed["recipe"], listed["left"], listed["right"], listed["frames"]),
                         ("current", True, 14, 15, 29))
        self.assertEqual(listed["video"], {"filename": f"replace@b-{cid}.mp4", "v": "2026-11-03T11:00:00"})
        self.assertEqual(listed["preview"]["file"]["filename"], f"replace@b-{cid}_preview.mp4")
        self.assertEqual(listed["preview"]["original"]["filename"], f"replace@b-{cid}_original.mp4")
        self.assertEqual((listed["preview"]["frames"], listed["preview"]["region"]), (125, [48, 77]))

    def test_a_reworded_prompt_keeps_the_selection_but_marks_the_candidate(self):
        state = self.state(self.timeline())
        cid = self.add_candidate(state, preview=False)
        item = self.item(self.timeline(review=state.region, selected=cid, prompt="Another turn."))
        self.assertEqual((item["status"], item["plays"], item["candidates"][0]["recipe"]), ("next", True, False))
        self.assertIsNone(item["candidates"][0]["preview"])

    def test_a_stale_selection_does_not_play(self):
        state = self.state(self.timeline())
        cid = self.add_candidate(state)
        time.sleep(0.02)
        self.save_box(2, "b")
        item = self.item(self.timeline(review=state.region, selected=cid))
        self.assertEqual((item["status"], item["selection"], item["plays"], item["reviewed"]),
                         ("review", "stale", False, False))
        self.assertEqual(item["candidates"][0]["state"], "stale")


class StatusTest(SavedBoxes):
    def test_bridges_list_insertions_and_replacements_in_timeline_order(self):
        insertion = {"before": "c", "frames": 12, "seed": 3, "prompt": "A pan."}
        status = self.status(self.timeline(bridges=[swap(), insertion], clips=[]))
        self.assertEqual([(item["box"], item["mode"]) for item in status["bridges"]], [("b", "replace"), ("c", "insert")])
        self.assertEqual(status["bridges"][0]["region"]["frames"], 29)

    def test_replacements_never_add_seconds(self):
        status = self.status(self.timeline())
        self.assertEqual(status["seconds"], round(321 / 24, 2))

    def test_unknown_context_waits_without_planning(self):
        status = self.status(self.timeline(), known={**KNOWN, "context_frames": None})
        [item] = status["bridges"]
        self.assertEqual((item["box"], item["mode"], item["status"]), ("b", "replace", "waiting"))
        self.assertIn("context_frames", item["note"])
        self.assertNotIn("region", item)

    @mock.patch.object(replacement, "UNAVAILABLE", "")
    def test_a_reviewed_pending_replacement_is_announced_as_next(self):
        state = self.state(self.timeline())
        status = self.status(self.timeline(review=state.region))
        self.assertEqual(status["bridges"][0]["status"], "next")
        self.assertIn("The replacement candidate before box 2 is next.", status["message"])
        self.assertNotIn("replacement_unavailable", status)

    def test_replacements_ship_unavailable_and_keep_the_cut(self):
        with mock.patch.object(replacement, "UNAVAILABLE", ""):
            state = self.state(self.timeline())
            cid = self.add_candidate(state)
        status = self.status(self.timeline(review=state.region, selected=cid))
        self.assertTrue(replacement.UNAVAILABLE)
        self.assertEqual(status["replacement_unavailable"], replacement.UNAVAILABLE)
        [item] = status["bridges"]
        self.assertEqual((item["status"], item["note"], item["selection"], item["plays"]),
                         ("unavailable", replacement.UNAVAILABLE, "current", False))
        self.assertNotIn("replacement candidate", status["message"])

    def test_dialogue_cues_report_their_binding_and_position(self):
        moved = cue("c2", start=1.0, end=2.0, file={"type": "input", "filename": "old.wav", "subfolder": ""})
        status = self.status(self.timeline(cue(start=4.0, end=4.5), moved))
        first, second = status["dialogue"]["cues"]
        self.assertEqual(first, {"id": "c1", "slot": "audio1", "state": "bound", "aligned": False, "placed": True,
                                 "cut": False, "sequence": [4.0, 4.5], "frames": [96, 108],
                                 "segments": [[96, 108, "on_screen"]]})
        self.assertEqual((second["id"], second["state"], second["placed"], second["frames"]), ("c2", "changed", False, None))

    def test_timing_conflicts_name_locks_that_drift(self):
        insertion = {"before": "c", "frames": 12, "seed": 3, "prompt": "A pan."}
        status = self.status(self.timeline(bridges=[insertion], clips=[clip(locked=True)]))
        self.assertEqual(len(status["timing_conflicts"]), 2)
        self.assertIn("isn't in the full video", status["timing_conflicts"][0])
        self.assertIn("the bridge before box 3 inserts 0.50 s", status["timing_conflicts"][1])
        self.assertEqual(self.status(self.timeline())["timing_conflicts"], [])

    def test_boxes_report_dialogue_they_cannot_compile(self):
        boxes = [box("a", 107), box("b", 107, prompt="<d>Hi.</d> A quiet street.", cut=True), box("c", 107, cut=True)]
        status = self.status(self.timeline(cue(start=5.0, end=5.5), boxes=boxes))
        self.assertIn("typed <d> dialogue", status["boxes"][1]["dialogue_problem"])
        self.assertNotIn("dialogue_problem", status["boxes"][0])

    def test_an_insertion_item_keeps_its_shape(self):
        insertion = {"before": "c", "frames": 12, "seed": 3, "prompt": "A pan."}
        [item] = self.status(self.timeline(bridges=[insertion], clips=[]))["bridges"]
        self.assertEqual(item, {"box": "c", "mode": "insert", "status": "next"})


class TakesTest(SavedBoxes):
    def sequence(self, timeline):
        entries = {entry["index"]: entry for entry in self.manifest["segments"]}
        return SimpleNamespace(parsed=timeline, folder=self.folder, manifest=self.manifest, entries=entries,
                               context=39, bridge_known={**KNOWN, "audio_context_frames": 0},
                               done=lambda index: index + 1 in entries)

    def test_switching_an_endpoint_take_warns_about_its_replacement(self):
        state = self.state(self.timeline())
        reviewed = self.timeline(review=state.region)
        for index in (0, 1):
            self.assertIn("The replacement before box 2 reads this box's footage", " ".join(
                takes.warnings(self.sequence(reviewed), index)))
        self.assertEqual(takes.warnings(self.sequence(reviewed), 2), [])
        self.assertEqual(takes.warnings(self.sequence(self.timeline()), 1), [])

    def test_a_replacement_has_no_bridge_takes(self):
        body = {"name": "seq", "timeline": json.dumps(self.value()), "settings": KNOWN, "box": "b"}
        root = os.path.dirname(self.folder)
        with mock.patch("h3_continuity.nodes.sequences_root", return_value=root), \
                mock.patch("h3_continuity.store.sequence_dir", return_value=self.folder):
            store.write_manifest(self.folder, self.manifest)
            found = takes.listing(body)
        self.assertTrue(found["ok"], found)
        self.assertIsNone(found["bridge"])


if __name__ == "__main__":
    unittest.main()
