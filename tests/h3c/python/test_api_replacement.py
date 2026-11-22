import copy
import unittest
from types import SimpleNamespace

from h3_continuity import timeline_prepare
from h3_continuity.timeline_api import contracts, planning
from h3_continuity.timeline_api.contracts import APIError

from .helpers import box, clip, cue, document


def swap(**extra):
    return {"before": "b", "mode": "replace", "left": 14, "right": 15, "seed": 7, "prompt": "A turn.", **extra}


def line(bridges=None, **extra):
    return document([box("a", 107), box("b", 107, cut=True), box("c", 107, cut=True)],
                    bridges=[swap()] if bridges is None else bridges, **extra)


def length(index):
    return {"frames": 107, "generated": 107, "carried": 0, "delivered_range": [index * 107, index * 107 + 107],
            "generated_range": [0, 107]}


def project(timeline):
    return {"id": "p1", "revision": 1, "profile": "native", "profile_sha256": "0" * 64, "sequence": "seq",
            "authored": {"timeline": copy.deepcopy(timeline)}, "assets": [],
            "prepared": {"timeline": timeline, "settings": {"context_frames": 39, "width": 512, "height": 512},
                         "boxes": [length(index) for index in range(len(timeline["boxes"]))], "assets": [],
                         "fingerprint": "f"}}


def missing(*_):
    raise APIError("missing", "No record.", status=404)


def planner(native):
    profiles = SimpleNamespace(get=lambda *_: {}, prepare=lambda *_: {"fingerprint": "f"})
    assets = SimpleNamespace(resolve=lambda *_: [], records=SimpleNamespace(get_blob_record=missing))
    return planning.Planner(profiles, assets, lambda body: native)


class SchemaTest(unittest.TestCase):
    def test_accepts_replacement_records_and_dialogue_fields(self):
        value = line(bridges=[swap(review="r", selected="s"), {"before": "c", "frames": 12}],
                     audio_clips=[clip(locked=True, in_full_video=True)], requires=["replacement-bridges-1"],
                     dialogue={"version": 1, "cues": [cue()]})
        value["boxes"][1]["dialogue"] = "manual"
        self.assertEqual(contracts.validate("timeline", value), value)

    def test_rejects_malformed_records(self):
        bad = [line(bridges=[swap(frames=29)]), line(bridges=[swap(left=-1)]),
               line(bridges=[{"before": "b", "mode": "replace", "left": 14}]),
               line(bridges=[{"before": "b", "seed": 1}]), line(bridges=[{"before": "b", "mode": "insert", "left": 1}]),
               line(audio_clips=[clip(locked="yes")]), line(requires=[1]), line(dialogue=[])]
        manual = line()
        manual["boxes"][0]["dialogue"] = "other"
        for value in [*bad, manual]:
            with self.assertRaises(APIError, msg=value):
                contracts.validate("timeline", value)

    def test_native_preparation_owns_the_coverage_lengths(self):
        with self.assertRaises(timeline_prepare.Invalid) as raised:
            timeline_prepare.normalize(line(bridges=[swap(left=15)]))
        self.assertEqual(raised.exception.path, "timeline.bridges.0")
        self.assertIn("12, 29 or 46", str(raised.exception))
        kept = line(bridges=[swap(review="r", selected="s")])
        timeline_prepare.normalize(kept)
        self.assertEqual(kept["bridges"], [swap(review="r", selected="s")])


class PlanTest(unittest.TestCase):
    def native(self, **replacement):
        return {"ok": True, "boxes": [{"id": box_id, "status": "done"} for box_id in "abc"],
                "bridges": [{"box": "b", "mode": "replace", "status": "review", "note": "confirm the region",
                             "plays": False, **replacement}],
                "unit_evidence": {}, "manifest_sha256": "1" * 64}

    def test_replacement_units_cover_frames_without_adding_them(self):
        [unit] = [unit for unit in planner(None)._units(project(line())) if unit["kind"] == "replacement"]
        self.assertEqual({key: unit[key] for key in ("id", "box_id", "dependencies", "left", "right", "replaced_frames")},
                         {"id": "replacement:b", "box_id": "b", "dependencies": ["box:a", "box:b"],
                          "left": 14, "right": 15, "replaced_frames": 29})
        self.assertNotIn("frames", unit)

    def test_a_selection_changes_the_replacement_identity_only(self):
        before = {unit["id"]: unit["input_sha256"] for unit in planner(None)._units(project(line()))}
        after = {unit["id"]: unit["input_sha256"]
                 for unit in planner(None)._units(project(line(bridges=[swap(selected="s")])))}
        self.assertEqual([key for key in before if before[key] != after[key]], ["replacement:b"])
        changes = planner(None).invalidation(project(line()), project(line(bridges=[swap(selected="s")])))
        self.assertEqual([item["id"] for item in changes], ["replacement:b"])

    def test_splice_ranges_overlay_replacements(self):
        units = planner(None)._units(project(line(bridges=[swap(), {"before": "c", "frames": 12, "seed": 1}])))
        for unit in units:
            unit["plays"] = unit["kind"] == "replacement"
        ranges, total = planning.splice_ranges(units)
        self.assertEqual(total, 333)
        self.assertEqual(ranges, [{"unit_id": "box:a", "range": [0, 107]},
                                  {"unit_id": "replacement:b", "range": [93, 122], "overlay": True, "plays": True},
                                  {"unit_id": "box:b", "range": [107, 214]},
                                  {"unit_id": "bridge:c", "range": [214, 226]},
                                  {"unit_id": "box:c", "range": [226, 333]}])
        self.assertEqual(sum(unit["frames"] for unit in planning.media_units(units)), 333)

    def test_plans_never_render_or_block_on_a_replacement(self):
        plan = planner(self.native()).plan(project(line()), {"kind": "all"})
        unit = next(unit for unit in plan["units"] if unit["kind"] == "replacement")
        self.assertEqual(unit["action"], "studio")
        self.assertEqual(unit["reasons"][0], "Replacement regions are reviewed and selected in the Studio.")
        self.assertIn("confirm the region", unit["reasons"][1])
        self.assertEqual((unit["plays"], plan["total_frames"]), (False, 321))
        self.assertFalse(any(item["action"] == "blocked" for item in plan["units"]))

    def test_a_rerendered_endpoint_warns_that_the_selection_goes_stale(self):
        native = self.native(plays=True, status="done", note="")
        native["boxes"][1]["status"] = "pending"
        plan = planner(native).plan(project(line(bridges=[swap(selected="s")])), {"kind": "all"})
        unit = next(unit for unit in plan["units"] if unit["kind"] == "replacement")
        self.assertEqual(unit["action"], "studio")
        self.assertTrue(unit["plays"])
        self.assertIn("box:b", unit["reasons"][-1])
        self.assertIn("original cut", unit["reasons"][-1])


if __name__ == "__main__":
    unittest.main()
