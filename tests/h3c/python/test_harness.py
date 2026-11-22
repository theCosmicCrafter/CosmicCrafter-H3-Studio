import unittest

from h3_continuity import timeline, timing


class HarnessTest(unittest.TestCase):
    def test_grid_helpers(self):
        self.assertEqual(timeline.snap_frames(100, True), 107)
        self.assertEqual(timing.tokens_for_frames(39), 12)


if __name__ == "__main__":
    unittest.main()
