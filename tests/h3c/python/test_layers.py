"""Video layers: several H3 generations in one clip, sharing its time, with a switch plan saying which is on screen."""

import copy
import json
import unittest

from h3_continuity import layers, timeline as rules
from h3_continuity.timeline_api import contracts
from h3_continuity.timeline_api.contracts import APIError

from .helpers import box, document
from .test_api_replacement import planner, project

FEATURE = ["video-layers-1"]


def layer(layer_id="b2v1", **extra):
    return {"id": layer_id, "seed": 5101, "prompt": "Slow push-in on the lamplighter at the first lamp, now lit.",
            "first": "image4", "last": "", "previews": [], "memory": "off", "memories": [], "dialogue": "cues",
            **extra}


def stacked(box_id="b2", frames=90, videos=None, cuts=None, fade=6, sound="screen", **extra):
    videos = [layer()] if videos is None else videos
    cuts = [{"at": 27, "to": videos[0]["id"]}] if cuts is None else cuts
    return box(box_id, frames, "Slow push-in on the lamplighter at the first lamp.", cut=True, seed=5101,
               first="image3", layers=videos, switch={"cuts": cuts, "fade": fade, "sound": sound}, **extra)


def parse(boxes, requires=FEATURE, **extra):
    return rules.parse(json.dumps(document(boxes, **({"requires": requires} if requires else {}), **extra)))


class ParseTest(unittest.TestCase):
    def refused(self, boxes, message, requires=FEATURE, **extra):
        with self.assertRaises(ValueError) as caught:
            parse(boxes, requires, **extra)
        self.assertIn(message, str(caught.exception))
        return caught.exception

    def test_shot_02_parses(self):
        parsed = parse([stacked()])
        self.assertEqual(parsed.layers["b2"][0]["id"], "b2v1")
        self.assertEqual(parsed.layers["b2"][0]["first"], "image4")
        self.assertEqual(parsed.switches["b2"]["cuts"], [{"at": 27, "to": "b2v1"}])
        self.assertEqual(parsed.switches["b2"]["fade"], 6)
        self.assertEqual(parsed.switches["b2"]["sound"], "screen")
        self.assertEqual(layers.videos(parsed, 0), ["b2", "b2v1"])
        self.assertTrue(layers.stacked(parsed, 0))
        self.assertEqual(layers.layer_of(parsed, "b2v1"), (0, parsed.layers["b2"][0]))
        self.assertIsNone(layers.layer_of(parsed, "b2"))

    def test_layers_need_the_feature(self):
        self.refused([stacked()], "video layers require video-layers-1", requires=None)

    def test_at_most_three_layers(self):
        videos = [layer(f"v{n}") for n in range(4)]
        cuts = [{"at": 10 + 20 * n, "to": f"v{n}"} for n in range(4)]
        self.refused([stacked(videos=videos, cuts=cuts)], "box 1 has 5 videos; a clip holds at most 4")

    def test_layer_fields_are_limited(self):
        self.refused([stacked(videos=[layer(frames=90)])], "box 1 video 2 has frames, which a video takes from its clip")

    def test_ids_are_unique_across_boxes_and_layers(self):
        self.refused([box("b1", 90, cut=True), stacked(videos=[layer("b1")], cuts=[{"at": 27, "to": "b1"}])],
                     "video id 'b1' is already used")
        self.refused([stacked(videos=[layer("v1"), layer("v1")], cuts=[{"at": 20, "to": "v1"}, {"at": 50, "to": "b2"},
                                                                       {"at": 70, "to": "v1"}])],
                     "video id 'v1' is already used")

    def test_switch_must_name_videos_of_its_clip(self):
        self.refused([stacked(cuts=[{"at": 27, "to": "zz"}])],
                     "box 1 switch names 'zz', which is not one of its videos")
        self.refused([stacked(sound="zz")], "box 1 switch names 'zz', which is not one of its videos")
        videos = [layer("v1"), layer("v2")]
        self.refused([stacked(videos=videos, cuts=[{"at": 27, "to": "v1"}])],
                     "box 1 video 3 is never on screen; add a swap to it")

    def test_switch_is_required_with_layers(self):
        raw = stacked()
        del raw["switch"]
        self.refused([raw], "box 1 has several videos, so it needs a switch")

    def test_a_swap_changes_the_video(self):
        self.refused([stacked(cuts=[{"at": 20, "to": "b2v1"}, {"at": 50, "to": "b2v1"}])],
                     "box 1 swap at frame 50 switches to the video already on screen")
        self.refused([stacked(cuts=[{"at": 50, "to": "b2v1"}, {"at": 20, "to": "b2"}])],
                     "box 1 swaps must be in order of their frames")

    def test_switch_outside_the_clip_is_refused(self):
        for at in (2, 88):
            self.refused([stacked(cuts=[{"at": at, "to": "b2v1"}])],
                         f"box 1 swap at frame {at} needs 3 frames of fade before it and 3 after, inside frames 1 to 90")
        self.refused([stacked(cuts=[{"at": 27, "to": "b2v1"}, {"at": 31, "to": "b2"}])],
                     "box 1 swaps at frames 27 and 31 are closer than the 6-frame fade")

    def test_a_hard_cut_still_shows_its_video(self):
        self.refused([stacked(cuts=[{"at": 90, "to": "b2v1"}], fade=0)],
                     "box 1 swap at frame 90 needs 0 frames of fade before it and 0 after, inside frames 1 to 90")
        self.assertEqual(layers.closing(parse([stacked(cuts=[{"at": 89, "to": "b2v1"}], fade=0)]), 0), "b2v1")

    def test_fade_range(self):
        for fade in (13, 2.5, -1, True):
            self.refused([stacked(fade=fade)], "box 1 fade must be a whole number of frames from 0 to 12")

    def test_alignment(self):
        parsed = parse([stacked(**{})])
        self.assertNotIn("align", parsed.switches["b2"])
        raw = stacked()
        raw["switch"]["align"] = {"b2v1": {"x": 4, "y": -2.5, "scale": 1.04}}
        self.assertEqual(parse([raw]).switches["b2"]["align"], {"b2v1": {"x": 4, "y": -2.5, "scale": 1.04}})
        raw["switch"]["align"] = {"b2v1": {"x": 0, "y": 0, "scale": 0}}
        self.refused([raw], "box 1 alignment of 'b2v1' needs numbers x and y and a positive scale")

    def test_layer_dialogue_and_memory(self):
        self.refused([stacked(videos=[layer(dialogue="sung")])], "box 1 video 2 dialogue must be cues or manual")
        self.refused([stacked(videos=[layer(memory="cast")])], "box 1 video 2 memory must be off, scene or selected")

    def test_continue_after_a_stack_is_refused(self):
        error = self.refused([box("a", 90, cut=True), stacked(), box("c", 73)], "Clip 3 continues")
        self.assertEqual(str(error), "H3 Timeline: Clip 3 continues from clip 2. With several videos in clip 2, "
                                     "clip 3 must start with a Cut.")
        parse([box("a", 90, cut=True), stacked(), box("c", 73, cut=True)])

    def test_no_bridge_touches_a_stack(self):
        boxes = [box("a", 90, cut=True), stacked(), box("c", 73, cut=True)]
        error = self.refused(boxes, "bridge 1 leads into box 2, which has several videos",
                             bridges=[{"before": "b2", "frames": 29}])
        self.assertIsInstance(error, rules.BridgeError)
        self.refused(boxes, "bridge 1 leads out of box 2, which has several videos",
                     bridges=[{"before": "c", "mode": "replace", "left": 14, "right": 15}],
                     requires=FEATURE + ["replacement-bridges-1"])

    def test_without_layers_nothing_changes(self):
        parsed = rules.parse(json.dumps(document([box("a", 90, cut=True), box("b", 73)])))
        self.assertEqual(parsed.layers, {})
        self.assertEqual(parsed.switches, {})
        self.assertFalse(layers.stacked(parsed, 0))
        self.assertEqual(layers.videos(parsed, 1), ["b"])
        self.assertEqual(rules.layout_key(parsed, 0), "42ed63529ef158228a8c88aa702654798786e3c1")
        self.assertEqual(rules.layout_key(parsed, 1), "7aaf25c291f0a0302bf7fee4538f48691b9c4fbc")

    def test_the_main_video_is_planned_as_before(self):
        plain = rules.parse(json.dumps(document([box("b2", 90, "Slow push-in on the lamplighter at the first lamp.",
                                                      cut=True, seed=5101, first="image3")])))
        self.assertEqual(rules.layout_key(parse([stacked()]), 0), rules.layout_key(plain, 0))


class SwitchTest(unittest.TestCase):
    def setUp(self):
        self.parsed = parse([stacked()])
        self.switch = self.parsed.switches["b2"]
        self.cut = self.switch["cuts"][0]

    def test_weights_and_screen(self):
        self.assertEqual([layers.weight(self.switch, self.cut, f) for f in (23, 24, 27, 30, 31)], [0, 0, 0.5, 1, 1])
        self.assertEqual(layers.on_screen(self.parsed, 0, 26), "b2")
        self.assertEqual(layers.on_screen(self.parsed, 0, 27), "b2v1")
        self.assertEqual(layers.closing(self.parsed, 0), "b2v1")

    def test_hard_cut(self):
        switch = {**copy.deepcopy(self.switch), "fade": 0}
        self.assertEqual([layers.weight(switch, self.cut, f) for f in (26, 27)], [0, 1])

    def test_odd_fade_is_centred_with_the_extra_frame_after(self):
        switch = {**copy.deepcopy(self.switch), "fade": 5}
        self.assertEqual(layers.weight(switch, self.cut, 25), 0)
        self.assertAlmostEqual(layers.weight(switch, self.cut, 27), 0.4)
        self.assertEqual(layers.weight(switch, self.cut, 30), 1)

    def test_back_to_the_main_video(self):
        parsed = parse([stacked(cuts=[{"at": 27, "to": "b2v1"}, {"at": 60, "to": "b2"}])])
        self.assertEqual([layers.on_screen(parsed, 0, f) for f in (0, 30, 59, 60, 89)], ["b2", "b2v1", "b2v1", "b2", "b2"])
        self.assertEqual(layers.closing(parsed, 0), "b2")


IMAGES = ["image1", "image2", "image3", "image4"]


def three(middle=None, last=None, **extra):
    """A street, then stacked clip b2 continuing it (85 frames, swap at 27), then a cut."""
    middle = {**stacked(frames=85), "cut": False} if middle is None else middle
    return parse([box("a", 107, "Wide street at dusk."), middle, last or box("c", 73, "The lamp burns.", cut=True)],
                 **extra)


class LayerViewTest(unittest.TestCase):
    def test_view_keeps_clock_and_identity(self):
        from h3_continuity import dialogue
        parsed = three(audio_clips=[{"slot": "audio1", "start": 0, "source_start": 0, "duration": 30,
                                     "file": {"type": "input", "filename": "rain.wav", "subfolder": ""}}])
        item = parsed.layers["b2"][0]
        view = layers.view(parsed, 1, item)
        self.assertEqual(rules.box_start(view, 1), rules.box_start(parsed, 1))
        self.assertEqual(rules.audio_box_spans(view), rules.audio_box_spans(parsed))
        self.assertEqual(rules.active_audio_clips(view, 1, 0), rules.active_audio_clips(parsed, 1, 0))
        self.assertEqual(dialogue.box_events(view, 1, 0), dialogue.box_events(parsed, 1, 0))
        self.assertTrue(rules.is_fresh(view, 1))
        self.assertEqual(rules.played_frames(view, 1), 85)
        self.assertEqual((view.boxes[1].id, view.boxes[1].prompt, view.boxes[1].first),
                         ("b2", item["prompt"], "image4"))
        self.assertFalse(layers.stacked(view, 1))
        self.assertEqual(parsed.boxes[1].prompt, "Slow push-in on the lamplighter at the first lamp.")
        self.assertFalse(parsed.boxes[1].cut)

    def test_layer_plan_uses_its_own_prompt_seed_and_first(self):
        parsed = three({**stacked(frames=85, videos=[layer(seed=777)]), "cut": False})
        plan = layers.plan(parsed, 1, parsed.layers["b2"][0], 39, True, 512, 512, 512, IMAGES, [])
        self.assertEqual(plan.slots.first, "image4")
        self.assertEqual(plan.box.seed, 777)
        self.assertEqual(plan.settings["context_frames"], 0)
        self.assertEqual((plan.carried, plan.generated), (0, rules.generated_frames(85, True)))
        self.assertIn("Clip 2 video 2b plays 85 frames; H3 generates 90 and drops the last 5.", plan.notes)
        self.assertEqual(rules.plan_box(parsed, 1, 39, True, 512, 512, 512, IMAGES, []).settings["context_frames"], 39)

    def test_layer_plan_names_the_video_in_its_errors(self):
        parsed = three({**stacked(frames=85, videos=[layer(first="image9")]), "cut": False})
        with self.assertRaises(ValueError) as caught:
            layers.plan(parsed, 1, parsed.layers["b2"][0], 39, True, 512, 512, 512, IMAGES, [])
        self.assertIn("box 2 video 2b uses image9 as its first frame, but image9 is not connected", str(caught.exception))

    def test_layer_key_differs_from_main(self):
        same = layer(prompt="Slow push-in on the lamplighter at the first lamp.", first="image3")
        parsed = parse([stacked(videos=[same])])
        key = layers.layer_key(parsed, 0, parsed.layers["b2"][0], 39)
        self.assertNotEqual(key, rules.layout_key(parsed, 0, 39))
        other = parse([stacked(videos=[{**same, "prompt": "Close on the wick."}])])
        self.assertNotEqual(layers.layer_key(other, 0, other.layers["b2"][0], 39), key)

    def test_stems(self):
        self.assertEqual(layers.stem("b2v1"), "layer@b2v1")
        self.assertRegex(layers.stem("B2 v1"), r"^layer@_[0-9a-f]{12}$")

    def test_labels(self):
        parsed = three()
        self.assertEqual(layers.label(parsed, 1, "b2v1"), "2b")

    def records(self, parsed, layer_entries, index=2):
        from unittest import mock
        from h3_continuity import store, visual_memory
        entries = {2: {"timeline": {"box": "b2"}, "frames": 90, "context_frames": 0, "created": "main"}}
        with mock.patch.object(store, "has_segment_latents", return_value=True), \
                mock.patch.object(store, "latent_stamp", return_value=""), \
                mock.patch.object(store, "played_frames", return_value=90):
            return visual_memory.records(parsed, index, "", entries, lambda source, entry: True,
                                         layer_entries=layer_entries)

    def test_memory_reads_the_video_on_screen(self):
        last = box("c", 73, "The lamp burns.", cut=True, memory="selected",
                   memories=[{"box": "b2", "frame": 26}, {"box": "b2", "frame": 30}])
        parsed = three(stacked(), last)
        entry = {"timeline": {"box": "b2", "layer": "b2v1"}, "frames": 90, "context_frames": 0, "created": "layer"}
        found = self.records(parsed, {"b2v1": entry})
        self.assertEqual([(item.get("layer"), item["frame"], item.get("whole", False)) for item in found],
                         [("b2v1", 0, True), (None, 17, False), ("b2v1", 17, False)])
        self.assertEqual([item["created"] for item in found], ["layer", "main", "layer"])
        with self.assertRaises(ValueError) as caught:
            self.records(parsed, {})
        self.assertIn("memory source box 2's video 2b needs rendering first, or set box 3's Visual memory to Off",
                      str(caught.exception))

    def test_memory_of_a_plain_source_has_no_layer(self):
        from h3_continuity import visual_memory
        parsed = three(stacked(cuts=[{"at": 80, "to": "b2v1"}, {"at": 86, "to": "b2"}]),
                       box("c", 73, "The lamp burns.", cut=True, memory="selected", memories=[{"box": "b2", "frame": 26}]))
        found = self.records(parsed, {})
        self.assertTrue(all("layer" not in item for item in found))
        from unittest import mock
        from h3_continuity import store
        import torch
        entry = {"timeline": {"box": "b2", "layer": "b2v1"}, "frames": 90}
        calls = []
        window = lambda folder, source, start, tokens: calls.append(source) or torch.zeros(1, 24, tokens, 2, 2)
        with mock.patch.object(store, "load_video_window", side_effect=window):
            visual_memory.load("", {2: {"frames": 90}}, [{"index": 2, "frame": 17, "layer": "b2v1"}],
                               layer_entries={"b2v1": entry})
        self.assertEqual(calls, [entry])

    def test_layer_memory_is_checked(self):
        late = {**stacked(videos=[layer(memory="selected", memories=[{"box": "c", "frame": 3}])]), "id": "b2"}
        with self.assertRaises(ValueError) as caught:
            parse([box("a", 107), late, box("c", 73, cut=True)])
        self.assertIn("box 2 video 2b memory must refer to a unique earlier box", str(caught.exception))

    def test_render_layer_target(self):
        self.assertEqual(three(render_layer="b2v1").render_layer, "b2v1")
        self.assertIsNone(three().render_layer)
        for extra, message in (({"render_layer": "zz"}, "render_layer must be the id of one of this Timeline's videos"),
                               ({"render_layer": "b2v1", "render_box": 1}, "a run renders one box, one bridge or one video")):
            with self.assertRaises(ValueError) as caught:
                three(**extra)
            self.assertIn(message, str(caught.exception))


class ApiTest(unittest.TestCase):
    def shot_02(self, **extra):
        return document([box("a1", 48, "The street."), stacked(**extra)], requires=FEATURE)

    def test_schema_accepts_shot_02(self):
        value = self.shot_02()
        self.assertEqual(contracts.validate("timeline", value), value)

    def test_schema_refuses_render_layer(self):
        with self.assertRaises(APIError):
            contracts.validate("timeline", {**self.shot_02(), "render_layer": "b2v1"})

    def test_schema_refuses_a_fifth_video(self):
        videos = [layer(f"b2v{number}") for number in range(1, 5)]
        value = self.shot_02(videos=videos, cuts=[{"at": at, "to": video["id"]} for at, video in zip((18, 36, 54, 72),
                                                                                                  videos)])
        with self.assertRaises(APIError):
            contracts.validate("timeline", value)
        unknown = self.shot_02()
        unknown["boxes"][1]["layers"][0]["frames"] = 90
        with self.assertRaises(APIError, msg="a video has no length of its own"):
            contracts.validate("timeline", unknown)

    def test_managed_jobs_refuse_layers(self):
        with self.assertRaises(ValueError) as caught:
            planner(None)._units(project(self.shot_02()))
        self.assertEqual(str(caught.exception), "H3 Timeline API: this Timeline has clips with several videos, which "
                                                "managed jobs can't render yet. Render it from the Studio.")


if __name__ == "__main__":
    unittest.main()
