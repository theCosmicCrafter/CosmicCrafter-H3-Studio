import unittest

import torch

from tests.h3c.continuity_support import enable_comfy_cpu

enable_comfy_cpu()

from h3_continuity import nodes  # noqa: E402

SIGMAS = torch.tensor([1.0, 0.99, 0.97, 0.94, 0.89, 0.81, 0.63, 0.40, 0.0])


def segment(carried):
    return nodes.SegmentPlan(sequence=None, context_frames=39, carried_ticks=0, frames=124, latent_size=(34, 60),
                             carried_video=torch.zeros(1) if carried else None, carried_audio=None)


def tail(sigmas=SIGMAS, steps=3, strength=0.5, plan=None):
    return nodes.H3C_SigmasTail.execute(sigmas=sigmas, tail_steps=steps, strength=strength, segment=plan).args[0]


class SigmasTailTest(unittest.TestCase):
    def test_zero_strength_and_fresh_boxes_pass_the_schedule_through(self):
        self.assertTrue(torch.equal(tail(strength=0.0), SIGMAS))
        self.assertTrue(torch.equal(tail(plan=segment(False)), SIGMAS))

    def test_only_the_tail_moves_and_order_holds(self):
        out = tail(plan=segment(True))
        self.assertTrue(torch.equal(out[:5], SIGMAS[:5]), "levels above the tail stay")
        self.assertEqual(float(out[-1]), 0.0)
        self.assertTrue(bool((out[5:8] > SIGMAS[5:8]).all()), "positive strength lifts the tail")
        self.assertTrue(bool((out[1:] < out[:-1]).all()))
        anchor = float(SIGMAS[4])
        self.assertAlmostEqual(float(out[7]), anchor * (0.40 / anchor) ** (1 / 1.5), places=5)

    def test_negative_strength_lowers_the_tail(self):
        self.assertTrue(bool((tail(strength=-0.5)[5:8] < SIGMAS[5:8]).all()))

    def test_without_a_segment_every_box_is_reshaped(self):
        self.assertFalse(torch.equal(tail(), SIGMAS))

    def test_registered(self):
        import asyncio
        from h3_continuity.extension import H3ContinuityExtension
        self.assertIn(nodes.H3C_SigmasTail, asyncio.run(H3ContinuityExtension().get_node_list()))


if __name__ == "__main__":
    unittest.main()
