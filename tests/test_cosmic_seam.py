# -*- coding: utf-8 -*-
"""Unit and regression tests for cosmic_h3_seam.py seam protection and harmonization."""

from __future__ import annotations

import math
import pytest
import torch

from cosmic_h3_seam import (
    rgb_luminance,
    estimate_luminance_gain,
    apply_luminance_gain_fade,
    blend_seam_images,
    audio_equal_power_crossfade,
    fit_audio_length_with_microfade,
    trim_prefix_latent,
    pixel_frames_to_latent_steps,
    MiniMaxH3SeamProtector,
    MiniMaxH3TrimPrefixLatent,
)


def test_rgb_luminance():
    # Pure red: 0.2126, pure green: 0.7152, pure blue: 0.0722
    img = torch.tensor([
        [[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
         [[0.0, 0.0, 1.0], [1.0, 1.0, 1.0]]]
    ], dtype=torch.float32)
    luma = rgb_luminance(img)
    assert luma.shape == (1, 2, 2)
    assert math.isclose(float(luma[0, 0, 0]), 0.2126, rel_tol=1e-3)
    assert math.isclose(float(luma[0, 0, 1]), 0.7152, rel_tol=1e-3)
    assert math.isclose(float(luma[0, 1, 0]), 0.0722, rel_tol=1e-3)
    assert math.isclose(float(luma[0, 1, 1]), 1.0, rel_tol=1e-3)


def test_estimate_luminance_gain():
    # Previous context at 0.50, next context at 0.40 (ratio 1.25, but clamped to limit)
    prev = torch.full((4, 16, 16, 3), 0.50, dtype=torch.float32)
    nxt = torch.full((4, 16, 16, 3), 0.40, dtype=torch.float32)

    # With default 10% limit, 1.25 is clamped to 1.10
    gain_10 = estimate_luminance_gain(prev, nxt, max_correction_percent=10.0)
    assert math.isclose(gain_10, 1.10, abs_tol=1e-3)

    # With 30% limit, 1.25 is within limit
    gain_30 = estimate_luminance_gain(prev, nxt, max_correction_percent=30.0)
    assert math.isclose(gain_30, 1.25, abs_tol=1e-3)

    # Identical contexts return 1.0
    assert math.isclose(estimate_luminance_gain(prev, prev), 1.0, abs_tol=1e-4)


def test_apply_luminance_gain_fade():
    imgs = torch.full((20, 8, 8, 3), 0.4, dtype=torch.float32)
    faded = apply_luminance_gain_fade(imgs, gain=1.2, fade_frames=10)
    assert faded.shape == imgs.shape
    # Frame 0 should have the full gain applied (0.4 * 1.2 = 0.48)
    assert math.isclose(float(faded[0, 0, 0, 0]), 0.48, abs_tol=1e-3)
    # Frame 10+ should be back to original 0.4
    assert math.isclose(float(faded[10, 0, 0, 0]), 0.40, abs_tol=1e-3)
    assert math.isclose(float(faded[-1, 0, 0, 0]), 0.40, abs_tol=1e-3)


def test_blend_seam_images():
    tail = torch.full((12, 16, 16, 3), 0.5, dtype=torch.float32)
    head = torch.full((12, 16, 16, 3), 0.4, dtype=torch.float32)
    blended, remainder = blend_seam_images(tail, head, overlap_frames=6, match_luminance=True)
    assert blended.shape == (6, 16, 16, 3)
    assert remainder.shape == (6, 16, 16, 3)
    # Values should stay strictly within [0.0, 1.0]
    assert blended.min() >= 0.0 and blended.max() <= 1.0


def test_audio_equal_power_crossfade():
    # 2 channels, 1000 samples each
    wave1 = torch.ones((1, 2, 1000), dtype=torch.float32)
    wave2 = torch.full((1, 2, 1000), 2.0, dtype=torch.float32)
    cf_samples = 200
    out = audio_equal_power_crossfade(wave1, wave2, crossfade_samples=cf_samples)
    assert out.shape == (1, 2, 1000 + 1000 - cf_samples)
    # Start matches wave1, end matches wave2
    assert torch.allclose(out[..., :800], wave1[..., :800])
    assert torch.allclose(out[..., -800:], wave2[..., -800:])


def test_fit_audio_length_with_microfade():
    # Test padding with DC offset micro-fade
    dc_wave = torch.ones((1, 2, 100), dtype=torch.float32)
    padded = fit_audio_length_with_microfade(dc_wave, target_samples=150, fade_len=16)
    assert padded.shape == (1, 2, 150)
    # The tail of original wave should ease down smoothly to 0 before the pad
    assert float(padded[0, 0, 99]) < 0.1
    # Padded samples should be 0.0
    assert torch.all(padded[..., 100:] == 0.0)


def test_pixel_frames_to_latent_steps():
    assert pixel_frames_to_latent_steps(0) == 0
    assert pixel_frames_to_latent_steps(5) == 2   # 1 + 4
    assert pixel_frames_to_latent_steps(22) == 7  # 5 + 17 -> 2 + 5 = 7
    assert pixel_frames_to_latent_steps(39) == 12 # 22 + 17 -> 7 + 5 = 12


def test_trim_prefix_latent():
    # Mock joint H3 AV latent: video [1, 24, 20, 16, 16], audio [1, 32, 2, 100]
    v = torch.randn(1, 24, 20, 16, 16)
    a = torch.randn(1, 32, 2, 100)
    latent = {"samples": [v, a]}
    # Trim 39 frames (12 video steps, 65 audio ticks)
    trimmed = trim_prefix_latent(latent, trim_frames=39, fps=24.0)
    tv, ta = trimmed["samples"]
    assert tv.shape == (1, 24, 20 - 12, 16, 16)
    assert ta.shape == (1, 32, 2, 100 - 65)


def test_seam_protector_node_execution():
    node = MiniMaxH3SeamProtector()
    prev_imgs = torch.full((10, 32, 32, 3), 0.5, dtype=torch.float32)
    next_imgs = torch.full((10, 32, 32, 3), 0.4, dtype=torch.float32)
    prev_aud = {"waveform": torch.ones(1, 2, 2000), "sample_rate": 44100}
    next_aud = {"waveform": torch.full((1, 2, 2000), 0.8), "sample_rate": 44100}

    out_imgs, out_aud = node.protect_seam(
        previous_images=prev_imgs,
        next_images=next_imgs,
        overlap_frames=4,
        match_luminance=True,
        previous_audio=prev_aud,
        next_audio=next_aud,
    )
    assert out_imgs.ndim == 4
    assert out_imgs.shape[0] == 10 + 10 - 4  # 16 frames
    assert out_aud is not None
    assert "waveform" in out_aud


def test_trim_prefix_latent_node_execution():
    node = MiniMaxH3TrimPrefixLatent()
    v = torch.randn(1, 24, 20, 16, 16)
    a = torch.randn(1, 32, 2, 100)
    imgs = torch.randn(50, 32, 32, 3)
    aud = {"waveform": torch.randn(1, 2, 88200), "sample_rate": 44100}

    out_lat, out_imgs, out_aud = node.trim(
        trim_frames=39,
        fps=24.0,
        latent={"samples": [v, a]},
        images=imgs,
        audio=aud,
    )
    assert out_imgs.shape[0] == 50 - 39  # 11 frames
    assert out_aud["waveform"].shape[-1] == 88200 - 71662
    assert out_lat["samples"][0].shape[2] == 20 - 12
