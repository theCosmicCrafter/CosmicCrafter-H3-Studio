import unittest

from h3_continuity import bridges, dialogue, replacement

from .helpers import box, clip, cue, parse, wav


def swap(before, left, right, **extra):
    return {"before": before, "mode": "replace", "left": left, "right": right, "seed": 7, "prompt": "A turn.", **extra}


def checked(line):
    return {**line, "aligned": dialogue.alignment_key(line)}


def two_boxes(*cues, left=14, right=15, clips=None, observed=None, **extra):
    value = {"version": 1, "cues": list(cues)}
    if observed is not None:
        value["observed"] = observed
    return parse([box("a", 107), box("b", 107, cut=True)], bridges=[swap("b", left, right)],
                 audio_clips=clips or [clip(locked=True, in_full_video=True)], dialogue=value, **extra)


class RecordTest(unittest.TestCase):
    def test_replacement_records_stay_apart_from_insertions(self):
        timeline = parse([box("a", 107), box("b", 107, cut=True), box("c", 107, cut=True)],
                         bridges=[{"before": "b", "frames": 29}, swap("c", 14, 15, review="k", selected="x")],
                         render_bridge="c")
        self.assertEqual([item["before"] for item in timeline.bridges], ["b"])
        self.assertEqual(timeline.replacements, [swap("c", 14, 15, review="k", selected="x")])
        self.assertEqual(set(bridges.splice(timeline, {})), {"b"})
        self.assertEqual(replacement.records(timeline), [{"before": "b", "frames": 29, "seed": timeline.bridges[0]["seed"],
                                                          "prompt": ""}, timeline.replacements[0]])

    def test_rejects_bad_replacements(self):
        boxes = [box("a", 107), box("b", 107, cut=True)]
        for record, fragment in ((swap("b", 15, 15), "12, 29 or 46"), (swap("b", -1, 30), "whole number"),
                                 ({**swap("b", 14, 15), "frames": 29}, "not frames"),
                                 ({"before": "b", "mode": "stretch"}, "insert or replace"),
                                 ({"before": "b"}, "frames must be"),
                                 (swap("b", 14, 15, review=3), "review")):
            with self.assertRaises(ValueError, msg=record) as caught:
                parse(boxes, bridges=[record])
            self.assertIn(fragment, str(caught.exception), record)
        with self.assertRaises(ValueError):
            parse([box("a", 107), box("b", 107)], bridges=[swap("b", 14, 15)])

    def test_prepare_keeps_both_kinds_in_order(self):
        from h3_continuity import timeline_prepare
        records = [{"before": "b", "frames": 29, "seed": 3, "prompt": ""}, swap("c", 14, 15)]
        line = {"version": 1, "prompt": "", "bridges": records,
                "boxes": [box("a", 107), box("b", 107, cut=True), box("c", 107, cut=True)]}
        timeline_prepare.normalize(line)
        self.assertEqual(line["bridges"], records)


class GeometryTest(unittest.TestCase):
    def test_coverage_and_endpoint_windows(self):
        timeline = two_boxes()
        shape = replacement.geometry(timeline, timeline.replacements[0], 39)
        self.assertEqual(shape.problem, "")
        self.assertEqual((shape.join, shape.start, shape.end, shape.frames), (107, 93, 122, 29))
        self.assertEqual((shape.context_frames, shape.ending_frames, shape.generated), (39, 39, 107))
        self.assertEqual(shape.left_window, (0, 54, 39))
        self.assertEqual(shape.right_window, (1, 15, 39))

    def test_continuing_left_box_counts_its_replayed_frames(self):
        timeline = parse([box("a", 107), box("b", 68), box("c", 107, cut=True)], bridges=[swap("c", 14, 15)])
        shape = replacement.geometry(timeline, timeline.replacements[0], 39)
        self.assertEqual(shape.left_window, (1, 54, 39))

    def test_context_shrinks_on_the_grid_to_the_surviving_footage(self):
        timeline = parse([box("a", 39), box("b", 107, cut=True)], bridges=[swap("b", 14, 15)])
        shape = replacement.geometry(timeline, timeline.replacements[0], 39)
        self.assertEqual((shape.context_frames, shape.left_window), (22, (0, 3, 22)))

    def test_insufficient_room(self):
        for frames, left, right, fragment in ((22, 20, 9, "box 1"), (22, 22, 7, "box 1")):
            timeline = parse([box("a", frames), box("b", 107, cut=True)], bridges=[swap("b", left, right)])
            self.assertIn(fragment, replacement.geometry(timeline, timeline.replacements[0], 39).problem)
        timeline = parse([box("a", 107), box("b", 22, cut=True)], bridges=[swap("b", 9, 20)])
        self.assertIn("box 2", replacement.geometry(timeline, timeline.replacements[0], 39).problem)

    def test_overlapping_replacements(self):
        timeline = parse([box("a", 107), box("b", 39, cut=True), box("c", 107, cut=True)],
                         bridges=[swap("b", 0, 29), swap("c", 12, 0)])
        later = replacement.geometry(timeline, timeline.replacements[1], 39)
        self.assertIn("overlaps the replacement before box 2", later.problem)

    def test_trims(self):
        timeline = two_boxes()
        self.assertEqual(replacement.trims(timeline, {"b"}), {0: (0, 14), 1: (15, 0)})
        self.assertEqual(replacement.trims(timeline, set()), {})


class ProtectionTest(unittest.TestCase):
    def problem(self, timeline, takes=None):
        return replacement.check(timeline, timeline.replacements[0], 39, takes)

    def test_visible_speech_inside_the_region(self):
        message = self.problem(two_boxes(checked(cue(start=4.0, end=4.5))))
        self.assertIn("Mara", message)
        self.assertIn("4.00 s", message)
        self.assertIn("unknown portrayal", self.problem(two_boxes(checked(cue(start=4.0, end=4.5, portrayal="unknown")))))

    def test_voiceover_may_continue_over_the_region(self):
        self.assertEqual(self.problem(two_boxes(checked(cue(start=4.0, end=4.5, portrayal="voiceover")))), "")
        self.assertEqual(self.problem(two_boxes(cue(start=1.0, end=2.0, portrayal="voiceover"))), "")

    def test_unchecked_speech_near_the_region(self):
        self.assertIn("check", self.problem(two_boxes(cue(start=1.0, end=2.0))))
        self.assertEqual(self.problem(two_boxes(checked(cue(start=1.0, end=2.0)))), "")
        self.assertEqual(self.problem(two_boxes(cue(start=20.0, end=21.0))), "")

    def test_changed_recording(self):
        timeline = two_boxes(checked(cue(start=1.0, end=2.0)), clips=[clip(file=wav("other.wav"), locked=True,
                                                                            in_full_video=True)])
        self.assertIn("changed", self.problem(timeline))

    def test_observed_protection(self):
        mark = {"id": "o1", "box": "b", "take": "t1", "start": 0, "end": 10, "label": "she turns"}
        self.assertIn("she turns", self.problem(two_boxes(observed=[mark]), {"b": "t1"}))
        self.assertIn("earlier take", self.problem(two_boxes(observed=[mark]), {"b": "t2"}))
        self.assertEqual(self.problem(two_boxes(observed=[{**mark, "box": "a"}]), {"a": "t1"}), "")

    def test_options_and_proposal(self):
        timeline = two_boxes()
        self.assertEqual(replacement.proposal(timeline, 1, 39), (29, 14))
        # Visible speech from box 2's frame 10 keeps the region before sequence frame 117.
        timeline = two_boxes(checked(cue(start=117 / 24, end=137 / 24)))
        options = dict(replacement.options(timeline, 1, 39))
        self.assertEqual(options[29], list(range(19, 30)))
        self.assertEqual(replacement.proposal(timeline, 1, 39), (29, 19))


class KeyTest(unittest.TestCase):
    def test_static_key_follows_the_region_inputs(self):
        line = checked(cue(start=4.6, end=4.8, portrayal="voiceover"))
        base = two_boxes(line)
        key = replacement.static_key(base, base.replacements[0], 39)
        for changed in (two_boxes(line, left=15, right=14),
                        two_boxes(checked({**line, "text": "Other."})),
                        two_boxes(line, clips=[clip(start=0.5, locked=True, in_full_video=True)])):
            self.assertNotEqual(replacement.static_key(changed, changed.replacements[0], 39), key)
        self.assertNotEqual(replacement.static_key(base, base.replacements[0], 22), key)
        reworded = parse([box("a", 107), box("b", 107, cut=True)],
                         bridges=[{**swap("b", 14, 15), "prompt": "Other.", "seed": 9}],
                         audio_clips=[clip(locked=True, in_full_video=True)], dialogue={"version": 1, "cues": [line]})
        self.assertEqual(replacement.static_key(reworded, reworded.replacements[0], 39), key)
        self.assertNotEqual(replacement.recipe(reworded, reworded.replacements[0]),
                            replacement.recipe(base, base.replacements[0]))

    def test_region_key_follows_the_endpoint_takes(self):
        static = "s"
        one = replacement.region_key(static, {"box": "a", "stamp": [1, 2]}, {"box": "b", "stamp": [3, 4]})
        self.assertNotEqual(replacement.region_key(static, {"box": "a", "stamp": [1, 5]}, {"box": "b", "stamp": [3, 4]}), one)
        self.assertEqual(replacement.region_key(static, {"box": "a", "stamp": [1, 2]}, {"box": "b", "stamp": [3, 4]}), one)


if __name__ == "__main__":
    unittest.main()
