import copy
import unittest
from unittest import mock

from h3_continuity import dialogue, replacement
from h3_continuity import timeline as rules

from .helpers import box, clip, cue, parse, wav


def cues(*items, observed=None):
    value = {"version": 1, "cues": list(items)}
    if observed is not None:
        value["observed"] = observed
    return value


class PlacementTest(unittest.TestCase):
    def test_source_time_maps_through_the_clip_window(self):
        placed = dialogue.placed(cue(start=12.5, end=14.0), clip(start=2.0, source_start=10.0, duration=30.0))
        self.assertEqual(placed["sequence"], (4.5, 6.0))
        self.assertEqual(placed["frames"], (108, 144))
        self.assertFalse(placed["cut"])

    def test_speech_rounds_outward_to_frames(self):
        placed = dialogue.placed(cue(start=1.01, end=1.02), clip())
        self.assertEqual(placed["frames"], (24, 25))

    def test_a_cue_partly_outside_the_window_is_cut(self):
        placed = dialogue.placed(cue(start=9.0, end=11.0), clip(source_start=10.0, duration=5.0))
        self.assertTrue(placed["cut"])
        self.assertEqual(placed["source"], (10.0, 11.0))
        self.assertEqual(placed["sequence"], (0.0, 1.0))

    def test_a_cue_outside_the_window_is_not_placed(self):
        self.assertIsNone(dialogue.placed(cue(start=1.0, end=2.0), clip(source_start=10.0, duration=5.0)))

    def test_portrayal_spans_project_separately(self):
        line = cue(start=1.0, end=3.0, spans=[{"start": 2.0, "end": 3.0, "portrayal": "voiceover"}])
        placed = dialogue.placed(line, clip(start=1.0))
        self.assertEqual(placed["segments"], [(48, 72, "on_screen"), (72, 96, "voiceover")])


class BindingTest(unittest.TestCase):
    def test_bound_changed_missing_and_disabled(self):
        line = cue()
        timeline = parse([box("a", 107)], audio_clips=[clip()], dialogue=cues(line))
        self.assertEqual(dialogue.binding(line, timeline)[0], "bound")
        timeline = parse([box("a", 107)], audio_clips=[clip(file=wav("other.wav"))], dialogue=cues(line))
        self.assertEqual(dialogue.binding(line, timeline)[0], "changed")
        timeline = parse([box("a", 107)], dialogue=cues(line))
        self.assertEqual(dialogue.binding(line, timeline)[0], "missing")
        timeline = parse([box("a", 107)], audio_clips=[clip()], disabled_refs=["audio1"], dialogue=cues(line))
        self.assertEqual(dialogue.binding(line, timeline)[0], "missing")

    def test_alignment_key_follows_words_interval_and_recording_only(self):
        line = cue()
        key = dialogue.alignment_key(line)
        for change in ({"text": "Hi."}, {"start": 1.5}, {"end": 2.5},
                       {"recording": {"slot": "audio1", "file": wav("other.wav")}}):
            self.assertNotEqual(dialogue.alignment_key({**line, **change}), key, change)
        for change in ({"speaker": "Jon"}, {"portrayal": "voiceover"}, {"origin": "story"}):
            self.assertEqual(dialogue.alignment_key({**line, **change}), key, change)
        self.assertFalse(dialogue.is_aligned(line))
        self.assertTrue(dialogue.is_aligned({**line, "aligned": key}))

    def test_projection_reports_every_cue_state(self):
        timeline = parse([box("a", 107), box("b", 107, cut=True)], audio_clips=[clip(start=1.0, source_start=2.0)],
                         dialogue=cues(cue("c1", 3.0, 4.0), cue("c2", 1.0, 2.5), cue("c3", 0.5, 1.0),
                                       cue("c4", 3.0, 4.0, slot="audio2")))
        states = {item["id"]: item for item in dialogue.projected(timeline)}
        self.assertEqual(states["c1"]["state"], "bound")
        self.assertEqual(states["c1"]["frames"], (48, 72))
        self.assertTrue(states["c2"]["cut"])
        self.assertFalse(states["c3"]["placed"])
        self.assertEqual(states["c4"]["state"], "missing")

    def test_two_locked_recordings_project_independently(self):
        timeline = parse([box("a", 107)],
                         audio_clips=[clip(start=0.0, locked=True, in_full_video=True),
                                      clip("audio2", start=1.0, file=wav("b.wav"), locked=True, in_full_video=True)],
                         dialogue=cues(cue("c1", 1.0, 2.0), cue("c2", 1.0, 2.0, slot="audio2", file=wav("b.wav"))))
        frames = {item["id"]: item["frames"] for item in dialogue.projected(timeline)}
        self.assertEqual(frames, {"c1": (24, 48), "c2": (48, 72)})


class ValidationTest(unittest.TestCase):
    def check_rejected(self, value, fragment):
        with self.assertRaises(ValueError) as caught:
            parse([box("a", 107)], dialogue=value)
        self.assertIn(fragment, str(caught.exception))

    def test_rejects_bad_cues(self):
        self.check_rejected(cues(cue("c1"), cue("c1")), "unique")
        self.check_rejected(cues(cue(start=2.0, end=2.0)), "after its start")
        self.check_rejected(cues(cue(portrayal="maybe")), "on_screen, voiceover or unknown")
        self.check_rejected(cues(cue(text="<d>Hi</d>")), "<d>")
        self.check_rejected(cues(cue(slot="audio4")), "audio1, audio2 or audio3")
        self.check_rejected(cues(cue(start=1.0, end=2.0, spans=[{"start": 0.5, "end": 1.5, "portrayal": "voiceover"}])),
                            "inside its cue")
        self.check_rejected(cues(cue(start=1.0, end=3.0, spans=[{"start": 1.0, "end": 2.0, "portrayal": "voiceover"},
                                                                {"start": 1.5, "end": 2.5, "portrayal": "on_screen"}])),
                            "overlap")
        self.check_rejected(cues(observed=[{"id": "o1", "box": "a", "take": "t", "start": 5, "end": 5, "label": ""}]),
                            "observed")

    def test_a_span_with_a_bad_start_is_a_validation_error(self):
        for start in ("a", None, True, -1.0):
            with self.subTest(start=start):
                self.check_rejected(cues(cue(start=1.0, end=3.0, spans=[
                    {"start": start, "end": 2.0, "portrayal": "voiceover"},
                    {"start": 1.5, "end": 2.5, "portrayal": "on_screen"}])), "span start")

    def test_parse_judges_memory_with_the_audio_lanes_already_read(self):
        seen = []
        real = rules.memory_sources

        def spy(timeline, index):
            seen.append((len(timeline.audio_clips), len(dialogue.cues(timeline))))
            return real(timeline, index)

        with mock.patch.object(rules, "memory_sources", spy):
            parse([box("a", 107), box("b", 107, cut=True, memory="scene")], audio_clips=[clip()],
                  dialogue=cues(cue("c1", 1.0, 2.0)))
        self.assertTrue(seen)
        self.assertTrue(all(item == (1, 1) for item in seen), seen)

    def test_parse_keeps_an_independent_copy(self):
        value = cues(cue(), observed=[{"id": "o1", "box": "a", "take": "t", "start": 1, "end": 5, "label": "nod"}])
        parsed = parse([box("a", 107)], dialogue=value).dialogue
        self.assertEqual(parsed, value)
        parsed["cues"][0]["text"] = "changed"
        self.assertEqual(value["cues"][0]["text"], "Hello there.")

    def test_locked_clip_needs_a_file(self):
        unlocked = {key: value for key, value in clip(locked=True).items() if key != "file"}
        with self.assertRaises(ValueError) as caught:
            parse([box("a", 107)], audio_clips=[unlocked])
        self.assertIn("locked", str(caught.exception))
        with self.assertRaises(ValueError):
            parse([box("a", 107)], audio_clips=[clip(locked="yes")])

    def test_requires_names_known_features_only(self):
        parse([box("a", 107)], requires=["dialogue-cues-1", "replacement-bridges-1"])
        with self.assertRaises(ValueError) as caught:
            parse([box("a", 107)], requires=["dialogue-cues-2"])
        self.assertIn("newer H3 Continuity", str(caught.exception))
        with self.assertRaises(ValueError):
            parse([box("a", 107)], requires="dialogue-cues-1")

    def test_box_dialogue_mode(self):
        timeline = parse([box("a", 107), box("b", 107, cut=True, dialogue="manual")])
        self.assertEqual(timeline.manual_dialogue, [False, True])
        with self.assertRaises(ValueError):
            parse([box("a", 107, dialogue="auto")])


class LockConflictTest(unittest.TestCase):
    def test_no_lock_no_conflict(self):
        timeline = parse([box("a", 107), box("b", 107, cut=True)], audio_clips=[clip()],
                         bridges=[{"before": "b", "frames": 29}])
        self.assertEqual(dialogue.lock_conflicts(timeline), [])

    def test_locked_clip_outside_the_full_video(self):
        timeline = parse([box("a", 107)], audio_clips=[clip(locked=True)])
        [message] = dialogue.lock_conflicts(timeline)
        self.assertIn("audio1", message)
        self.assertIn("full video", message)

    def test_insertion_bridge_inside_a_locked_recording(self):
        boxes = [box("a", 107), box("b", 107, cut=True), box("c", 107, cut=True)]
        timeline = parse(boxes, audio_clips=[clip(start=0.0, duration=6.0, locked=True, in_full_video=True)],
                         bridges=[{"before": "b", "frames": 29}, {"before": "c", "frames": 12}])
        [message] = dialogue.lock_conflicts(timeline)
        self.assertIn("box 2", message)
        self.assertIn("1.21 s", message)
        self.assertTrue(message.endswith("remove the bridge, so the join plays as a cut."))
        with mock.patch.object(replacement, "UNAVAILABLE", ""):
            [message] = dialogue.lock_conflicts(timeline)
        self.assertTrue(message.endswith("replace within the existing duration, or remove the bridge."))

    def test_bridge_before_the_recording_moves_with_it(self):
        boxes = [box("a", 107), box("b", 107, cut=True)]
        timeline = parse(boxes, audio_clips=[clip(start=5.0, duration=3.0, locked=True, in_full_video=True)],
                         bridges=[{"before": "b", "frames": 29}])
        self.assertEqual(dialogue.lock_conflicts(timeline), [])


if __name__ == "__main__":
    unittest.main()
