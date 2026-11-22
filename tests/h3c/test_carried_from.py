import unittest
from types import SimpleNamespace
from unittest import mock

import torch

from tests.h3c.continuity_support import enable_comfy_cpu

enable_comfy_cpu()

from h3_continuity import takes  # noqa: E402


def entry(created, context=39, carried_from=None):
    found = {"created": created, "context_frames": context}
    if carried_from:
        found["carried_from"] = carried_from
    return found


class CarriedFromTest(unittest.TestCase):
    """A box rendered with context noise carries changed frames, so its latents never match the box before exactly;
    the recorded parent render says where it came from."""

    def joins(self, take, before, after=None, same=False):
        sequence = SimpleNamespace(folder="f", entries={1: before, 3: after} if after else {1: before})
        window = lambda *args: torch.zeros(1) if same else torch.rand(1)  # noqa: E731
        with mock.patch.object(takes, "_window", window), mock.patch.object(takes.store, "has_segment_latents", lambda *a: True):
            return takes.joins(sequence, 1, "dir", take)

    def test_matching_latents_still_join(self):
        self.assertEqual(self.joins(entry("t"), entry("b", 0), same=True), "")

    def test_a_recorded_parent_joins_when_latents_differ(self):
        self.assertEqual(self.joins(entry("t", carried_from="b"), entry("b", 0)), "")

    def test_another_parent_does_not(self):
        self.assertEqual(self.joins(entry("t", carried_from="old"), entry("b", 0)), "the box before changed")
        self.assertEqual(self.joins(entry("t"), entry("b", 0)), "the box before changed")

    def test_the_box_after_names_this_take_as_its_parent(self):
        self.assertEqual(self.joins(entry("t", carried_from="b"), entry("b", 0), after=entry("a", carried_from="t")), "")
        self.assertEqual(self.joins(entry("t", carried_from="b"), entry("b", 0), after=entry("a", carried_from="x")),
                         "the box after changed")


if __name__ == "__main__":
    unittest.main()
