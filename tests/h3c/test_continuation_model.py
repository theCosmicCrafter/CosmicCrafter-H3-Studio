import unittest

import torch

from tests.h3c.continuity_support import enable_comfy_cpu

enable_comfy_cpu()

from h3_continuity import nodes  # noqa: E402


def plan(carried):
    return nodes.SegmentPlan(sequence=None, context_frames=39 if carried else 0, carried_ticks=0, frames=124,
                             latent_size=(34, 60), carried_video=torch.zeros(1) if carried else None, carried_audio=None)


def pick(segment, continuation_model=None):
    return nodes.H3C_ContinuationModel.execute(model="base", segment=segment,
                                               continuation_model=continuation_model).args[0]


class ContinuationModelTest(unittest.TestCase):
    def test_a_fresh_box_keeps_the_model(self):
        self.assertEqual(pick(plan(False), "continuing"), "base")

    def test_a_continuing_box_takes_the_continuation_model(self):
        self.assertEqual(pick(plan(True), "continuing"), "continuing")

    def test_without_a_continuation_model_every_box_keeps_the_model(self):
        self.assertEqual(pick(plan(True)), "base")

    def test_registered(self):
        import asyncio
        from h3_continuity.extension import H3ContinuityExtension
        self.assertIn(nodes.H3C_ContinuationModel, asyncio.run(H3ContinuityExtension().get_node_list()))


if __name__ == "__main__":
    unittest.main()
