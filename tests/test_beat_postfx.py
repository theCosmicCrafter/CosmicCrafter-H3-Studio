"""Regression tests for the beat-reactive post effects.

These exist because an earlier revision of ``h3_beat_postfx`` averaged the
bloom blur sigma across each chunk.  On a 24 fps render with the default
16-frame chunk that smeared a one-frame kick across 0.67 s - the exact
interpolation failure the H3 mask nodes were built to avoid.  The first two
tests below make that class of bug impossible to reintroduce quietly.
"""

import os
import sys

import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from h3_beat_postfx import (  # noqa: E402
    MiniMaxH3BeatBloom,
    MiniMaxH3BeatChromaticAberration,
)


class _Spike:
    """A FEATURE that fires on exactly one frame."""

    def __init__(self, at):
        self.at = at

    def get_value_at_frame(self, index):
        return 1.0 if index == self.at else 0.0


class _Flat:
    def get_value_at_frame(self, index):
        return 0.0


def _clip(frames=32, height=24, width=32, seed=0):
    torch.manual_seed(seed)
    return torch.rand(frames, height, width, 3)


def _bloom(images, feature, chunk, feature_param="blur_amount", strength=3.0):
    return MiniMaxH3BeatBloom().apply(
        images, 0.5, 10.0, 0.0, 4, 1.2, strength, feature_param,
        "add", chunk, 0.0, feature)[0]


def test_chunk_size_never_changes_bloom_output():
    """chunk_frames bounds memory only - it must not alter a single pixel.

    Spikes are placed mid-chunk, exactly on a boundary, just past one, and on
    the final frame, because a chunk-averaging bug shows up at boundaries.
    """
    images = _clip()
    for spike_at in (5, 16, 17, 31):
        small = _bloom(images, _Spike(spike_at), 4)
        large = _bloom(images, _Spike(spike_at), 64)
        single = _bloom(images, _Spike(spike_at), 1)
        assert torch.equal(small, large), f"chunk 4 != 64 with spike at {spike_at}"
        assert torch.equal(small, single), f"chunk 4 != 1 with spike at {spike_at}"


def test_one_frame_transient_stays_one_frame():
    """A single-frame beat must not bleed into its neighbours."""
    images = _clip()
    spiked = _bloom(images, _Spike(16), 16, feature_param="intensity", strength=1.0)
    flat = _bloom(images, _Flat(), 16, feature_param="intensity", strength=1.0)

    delta = (spiked - flat).abs().mean(dim=(1, 2, 3))
    assert float(delta[16]) > 1e-4, "the spike frame did not react at all"

    neighbours = torch.cat([delta[:16], delta[17:]])
    assert float(neighbours.max()) < 1e-9, (
        f"transient bled into neighbouring frames (max {float(neighbours.max()):.2e})"
    )


def test_zero_baseline_reacts_under_additive_modulation():
    """Authoring 'nothing until the drop' means a base of 0 must still react."""
    images = _clip()
    node = MiniMaxH3BeatChromaticAberration()
    out = node.apply(images, 0.0, 0.0, 0.05, "shift_amount", "add", _Spike(10))[0]
    assert not torch.equal(out[10], images[10]), "add mode inert at a zero base"


def test_zero_baseline_is_inert_under_multiplicative_modulation():
    """The documented contrast: base * (1 + s*v) can never leave zero."""
    images = _clip()
    node = MiniMaxH3BeatChromaticAberration()
    out = node.apply(images, 0.0, 0.0, 0.05, "shift_amount", "multiply", _Spike(10))[0]
    assert torch.equal(out[10], images[10].clamp(0.0, 1.0))


def test_shifts_are_subpixel_not_integer_snapped():
    """Half-pixel steps must survive; np.roll would collapse them to 0 or 1."""
    images = _clip(frames=1, height=64, width=64, seed=1)
    node = MiniMaxH3BeatChromaticAberration()
    outs = [node.apply(images, f / 64.0, 0.0, 0.0, "None", "add")[0]
            for f in (0.0, 0.5, 1.0, 1.5)]
    for a, b in zip(outs, outs[1:]):
        assert float((b - a).abs().mean()) > 1e-6, "shift snapped to whole pixels"


def test_aberration_does_not_wrap_around_the_frame():
    """grid_sample(padding_mode='border') must not bleed one edge onto the other."""
    images = torch.zeros(1, 16, 64, 3)
    images[0, :, :2, 0] = 1.0  # red bar hard against the LEFT edge
    node = MiniMaxH3BeatChromaticAberration()
    out = node.apply(images, 0.2, 0.0, 0.0, "None", "add")[0]
    assert float(out[0, :, -4:, 0].max()) < 1e-5, "red wrapped onto the right edge"


def test_nodes_never_mutate_their_input():
    images = _clip()
    before = images.clone()
    MiniMaxH3BeatChromaticAberration().apply(
        images, 0.01, 30.0, 0.02, "shift_amount", "add", _Spike(3))
    MiniMaxH3BeatBloom().apply(
        images, 0.5, 10.0, 0.0, 4, 1.2, 0.6, "intensity", "add", 8, 0.0, _Spike(3))
    assert torch.equal(images, before)


def test_blur_radius_is_clamped_on_small_canvases():
    """reflect padding requires pad < dimension; a huge sigma must not crash."""
    images = _clip(frames=4, height=5, width=7, seed=2)
    out = MiniMaxH3BeatBloom().apply(
        images, 0.3, 50.0, 1.0, 8, 3.0, 0.0, "None", "add", 4, 0.0)[0]
    assert out.shape == images.shape
    assert bool(torch.isfinite(out).all())


def test_output_stays_in_unit_range():
    images = _clip()
    ca = MiniMaxH3BeatChromaticAberration().apply(
        images, 0.05, 45.0, 0.2, "shift_amount", "add", _Spike(4))[0]
    bl = MiniMaxH3BeatBloom().apply(
        images, 0.1, 20.0, 1.0, 6, 2.0, 1.0, "intensity", "add", 8, 0.0, _Spike(4))[0]
    for name, out in (("aberration", ca), ("bloom", bl)):
        assert float(out.min()) >= 0.0 and float(out.max()) <= 1.0, f"{name} left [0,1]"
