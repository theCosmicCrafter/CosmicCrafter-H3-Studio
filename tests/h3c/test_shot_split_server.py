"""The renderer reads browser Shot splits and keeps existing frame guides valid."""
import json
import os
import shutil
import subprocess
import unittest

from h3_continuity import timeline

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "Node.js is needed to run the browser edit")
class ShotSplitServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        script = os.path.join(ROOT, "tests", "h3c", "js", "emit_shot_split.mjs")
        cls.data = json.loads(subprocess.run([NODE, script], cwd=ROOT, check=True,
                                            capture_output=True, text=True).stdout)
        cls.context = cls.data["context"]

    def test_shot_split_starts_fresh_and_keeps_renumbered_guides(self):
        parsed = timeline.parse(self.data["shot"])
        self.assertTrue(timeline.is_fresh(parsed, 1))
        self.assertEqual(timeline.box_length(parsed, 1, self.context)[1], 0)
        self.assertEqual([(frame, guide["filename"]) for frame, guide in
                          timeline.frame_guides(parsed, 1, self.context)],
                         [(0, "guide_a.png"), (48, "guide_c.png")])
        self.assertNotIn("pier", parsed.boxes[1].prompt)

    def test_existing_guide_split_keeps_its_continue_join_and_paired_endpoints(self):
        parsed = timeline.parse(self.data["saved"])
        self.assertFalse(timeline.is_fresh(parsed, 1))
        for index, endpoint in [(0, "last"), (1, "first")]:
            self.assertEqual(timeline.accepted_endpoints(parsed, index, self.context)[endpoint]["filename"],
                             "guide_a.png")
            self.assertEqual(timeline.carry_conflict(parsed, index, self.context), "")
        self.assertEqual(parsed.boxes[0].prompt, parsed.boxes[1].prompt)

    def test_interior_guide_without_shots_is_still_a_guide_in_one_box(self):
        parsed = timeline.parse(self.data["unstructured"])
        self.assertEqual(len(parsed.boxes), 1)
        self.assertEqual([(frame, guide["filename"]) for frame, guide in
                          timeline.frame_guides(parsed, 0, self.context)], [(80, "guide_a.png")])
        self.assertFalse(timeline.accepted_endpoints(parsed, 0, self.context))


if __name__ == "__main__":
    unittest.main()
