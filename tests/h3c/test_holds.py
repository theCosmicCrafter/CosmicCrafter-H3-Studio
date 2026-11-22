import unittest

import numpy as np

from h3_continuity import check_frames


def moving(count, hold_at=None, hold=0, seed=0):
    """`count` frames of a pattern sliding 2 px per frame; `hold` extra repeats of frame `hold_at`."""
    rng = np.random.default_rng(seed)
    base = rng.integers(0, 255, (136, 400), dtype=np.uint8)
    frames = [np.repeat(base[:, 2 * i:2 * i + 240, None], 3, axis=2) for i in range(count)]
    if hold_at is not None:
        frames[hold_at + 1:hold_at + 1] = [frames[hold_at]] * hold
    return frames


class HoldsTest(unittest.TestCase):
    def test_repeated_frames_in_motion_are_one_hold(self):
        self.assertEqual(check_frames.holds(moving(40, hold_at=10, hold=2)), [(10, 3)])

    def test_a_single_repeat_is_not_a_hold(self):
        self.assertEqual(check_frames.holds(moving(40, hold_at=10, hold=1)), [])

    def test_a_static_shot_reports_nothing(self):
        frame = moving(1)[0]
        self.assertEqual(check_frames.holds([frame] * 30), [])

    def test_hold_at_the_start_and_end(self):
        self.assertEqual(check_frames.holds(moving(40, hold_at=0, hold=2)), [(0, 3)])
        self.assertEqual(check_frames.holds(moving(40, hold_at=39, hold=3)), [(39, 4)])


class HoldWordsTest(unittest.TestCase):
    def test_records_hold_times_from_the_join(self):
        self.assertEqual(check_frames.hold_records([(0, 3), (101, 12)], joined=True),
                         [{"start_ms": 0, "frames": 3, "join": True}, {"start_ms": 4167, "frames": 12, "join": False}])
        self.assertEqual(check_frames.hold_records([(24, 3)], joined=False),
                         [{"start_ms": 1000, "frames": 3, "join": False}])


if __name__ == "__main__":
    unittest.main()
