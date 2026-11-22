"""A dependency on a box (a remembered moment, a plate change, a bridge) never asks for that box's length to change."""
import unittest

from h3_continuity import bridges, timeline as rules

from .helpers import box, parse


class KeepLengthsTest(unittest.TestCase):
    def test_a_memory_past_its_source_names_the_moments_it_can_choose(self):
        boxes = [box("a", 90, exact=True), box("b", 56, cut=True),
                 box("c", 56, cut=True, memory="selected", memories=[{"box": "a", "frame": 120, "label": "the dock"}])]
        with self.assertRaises(ValueError) as caught:
            parse(boxes)
        message = str(caught.exception)
        self.assertIn("box 3 remembers frame 120 of box 1, which plays 90 frames: choose a moment before frame 90",
                      message)
        self.assertNotIn("lengthen", message)
        boxes[2]["memories"][0]["frame"] = 89
        self.assertEqual(rules.played_frames(parse(boxes), 0), 90)

    def test_a_plate_change_past_its_end_is_moved_not_the_box_lengthened(self):
        document = [box("a", 56, plate_changes=[{"slot": "image1", "frame": 80, "revision": ""}])]
        with self.assertRaises(Exception) as caught:
            parse(document)
        self.assertIn("move the change earlier or remove it", str(caught.exception))
        self.assertNotIn("lengthen", str(caught.exception))

    def test_length_fixes_say_they_move_later_boxes(self):
        timeline = parse([box("a", 30, exact=True), box("b", 51)])
        with self.assertRaises(Exception) as caught:
            rules.box_length(timeline, 1, 39)
        self.assertIn("make box 2 a cut", str(caught.exception))
        self.assertTrue(str(caught.exception).endswith("which moves every later box"))
        bridged = parse([box("a", 30, exact=True), box("b", 56, cut=True)],
                        bridges=[{"before": "b", "frames": 29, "seed": 1, "prompt": "The camera rises."}])
        problem = bridges.problem(bridged, bridged.bridges[0])
        self.assertIn("use a replacement bridge", problem)
        self.assertTrue(problem.endswith("which moves every later box"))


if __name__ == "__main__":
    unittest.main()
