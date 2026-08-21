"""Adversarial and red-team tests for audio-reactive analysis module.

Aggressively attacks edge cases, hostile tensor shapes/dtypes, pathological audio,
numerical extremes (NaN, Inf, zeroes, DC offset), invalid parameter ranges,
and ComfyUI data-type permutations.
"""

import math
import sys
import os
import torch

from h3_audio_reactive import (
    _mono,
    _frame_windows,
    _fit_curve,
    rms_energy,
    spectral_centroid,
    onset_strength,
    beat_curve,
    beat_frames_detect,
    frequency_bands,
    _energy_peak_beats,
    smooth_curve,
    remap_curve,
    MiniMaxH3AudioAnalyze,
    MiniMaxH3AudioReactiveDenoise,
    MiniMaxH3AudioCurveRemap,
    FPS,
)


# ===========================================================================
# 1. Hostile Tensor Shapes & Data Types
# ===========================================================================

def test_mono_integer_tensor():
    """Red-team: integer dtypes (int16/int32/int64) must not crash on mean()."""
    wav_int16 = torch.randint(-32768, 32767, (2, 1000), dtype=torch.int16)
    mono = _mono(wav_int16)
    assert mono.ndim == 1
    assert mono.shape[0] == 1000


def test_mono_high_dimensional():
    """Red-team: 4D or 5D nested tensor must reduce to 1D gracefully."""
    wav_4d = torch.randn(1, 1, 2, 500)
    mono = _mono(wav_4d)
    assert mono.ndim == 1
    assert mono.shape[0] == 500


def test_mono_empty_tensor():
    """Red-team: 0-length waveform."""
    wav_empty = torch.zeros(2, 0)
    mono = _mono(wav_empty)
    assert mono.ndim == 1
    assert mono.shape[0] == 0


def test_mono_single_sample():
    """Red-team: 1-sample waveform."""
    wav_1s = torch.tensor([[0.5], [0.5]])
    mono = _mono(wav_1s)
    assert mono.ndim == 1
    assert mono.shape[0] == 1


# ===========================================================================
# 2. Hostile Parameters & Negative/Zero Frames
# ===========================================================================

def test_analyze_negative_clip_start():
    """Red-team: negative clip_start_seconds must not slice backwards from tensor end."""
    sr = 32000
    duration = 5.0
    t = torch.linspace(0, duration, int(sr * duration))
    # Beginning is loud (1.0), end is silent (0.0)
    wav = torch.sin(2 * math.pi * 440 * t)
    wav[int(sr * 2):] = 0.0  # silence second half
    audio = {
        "waveform": wav.unsqueeze(0).unsqueeze(0),
        "sample_rate": sr,
    }
    node = MiniMaxH3AudioAnalyze()
    # If negative start slices backwards, it would see silence or crash
    energy, *_ = node.analyze(audio, clip_start_seconds=-2.0, clip_frames=24)
    assert len(energy) == 24
    assert all(isinstance(v, float) for v in energy)


def test_analyze_zero_and_negative_clip_frames():
    """Red-team: clip_frames <= 0 must return empty lists without crashing."""
    audio = {
        "waveform": torch.randn(1, 2, 32000),
        "sample_rate": 32000,
    }
    node = MiniMaxH3AudioAnalyze()
    for bad_frames in [0, -1, -100]:
        energy, beats, bright, onsets, bass, mids, highs = node.analyze(
            audio, clip_start_seconds=0.0, clip_frames=bad_frames
        )
        assert len(energy) == 0


def test_analyze_extreme_parameters():
    """Red-team: negative beat_decay or extreme sensitivity."""
    audio = {
        "waveform": torch.randn(1, 2, 32000 * 2),
        "sample_rate": 32000,
    }
    node = MiniMaxH3AudioAnalyze()
    # Negative decay must not blow up to Inf
    energy, beats, bright, onsets, bass, mids, highs = node.analyze(
        audio, clip_start_seconds=0.0, clip_frames=48,
        beat_decay=-10.0, sensitivity=1000.0
    )
    assert all(not math.isnan(v) and not math.isinf(v) for v in beats)
    assert all(not math.isnan(v) and not math.isinf(v) for v in onsets)


# ===========================================================================
# 3. Pathological Audio Signals (NaNs, Infs, DC, Clipping)
# ===========================================================================

def test_signals_with_nan_and_inf():
    """Red-team: audio containing NaNs/Infs must not poison downstream outputs."""
    sr = 32000
    wav = torch.randn(1, sr)
    wav[0, 100:150] = float("nan")
    wav[0, 500:550] = float("inf")
    wav[0, 800:850] = float("-inf")
    audio = {
        "waveform": wav,
        "sample_rate": sr,
    }
    node = MiniMaxH3AudioAnalyze()
    energy, beats, bright, onsets, bass, mids, highs = node.analyze(
        audio, clip_start_seconds=0.0, clip_frames=24
    )
    for name, out in [("energy", energy), ("beats", beats), ("bright", bright),
                      ("onsets", onsets), ("bass", bass), ("mids", mids), ("highs", highs)]:
        for v in out:
            assert not math.isnan(v), f"{name} contains NaN: {v}"
            assert not math.isinf(v), f"{name} contains Inf: {v}"


def test_signals_pure_dc_offset():
    """Red-team: constant non-zero signal (DC offset) has 0 frequency but non-zero energy."""
    sr = 32000
    wav = torch.ones(1, sr) * 0.75
    audio = {
        "waveform": wav,
        "sample_rate": sr,
    }
    node = MiniMaxH3AudioAnalyze()
    energy, beats, bright, onsets, bass, mids, highs = node.analyze(
        audio, clip_start_seconds=0.0, clip_frames=24
    )
    assert max(energy) > 0.0
    # Centroid of pure DC should be very low (0 or close to 0)
    assert max(bright) < 0.1


def test_signals_sub_frame_audio():
    """Red-team: audio shorter than even 1 video frame (e.g. 10 samples)."""
    sr = 32000
    wav = torch.randn(1, 10)
    audio = {
        "waveform": wav,
        "sample_rate": sr,
    }
    node = MiniMaxH3AudioAnalyze()
    energy, beats, bright, onsets, bass, mids, highs = node.analyze(
        audio, clip_start_seconds=0.0, clip_frames=39
    )
    assert len(energy) == 39
    for out in [energy, beats, bright, onsets, bass, mids, highs]:
        assert len(out) == 39
        assert all(isinstance(v, float) for v in out)


def test_signals_extreme_sample_rates():
    """Red-team: very low (8000 Hz) and very high (192000 Hz) sample rates."""
    node = MiniMaxH3AudioAnalyze()
    for sr in [8000, 11025, 48000, 96000, 192000]:
        t = torch.linspace(0, 1.0, sr)
        wav = torch.sin(2 * math.pi * 440 * t)
        audio = {
            "waveform": wav.unsqueeze(0),
            "sample_rate": sr,
        }
        energy, beats, bright, onsets, bass, mids, highs = node.analyze(
            audio, clip_start_seconds=0.0, clip_frames=24
        )
        assert len(energy) == 24
        assert max(energy) > 0.0


# ===========================================================================
# 4. Smoothing & Remapping Edge Cases
# ===========================================================================

def test_smooth_window_larger_than_curve():
    """Red-team: smooth_frames = 100 on a 5-element curve must not crash."""
    c = torch.tensor([1.0, 0.0, 1.0, 0.0, 1.0])
    smoothed = smooth_curve(c, window_size=100)
    assert smoothed.shape[0] == 5
    assert not torch.isnan(smoothed).any()


def test_smooth_zero_and_negative_window():
    """Red-team: smooth_frames <= 0 must return curve unchanged."""
    c = torch.tensor([1.0, 2.0, 3.0])
    for w in [0, -1, -50]:
        res = smooth_curve(c, window_size=w)
        assert torch.allclose(res, c)


def test_remap_extreme_gamma():
    """Red-team: gamma = 0, gamma < 0, gamma = 100."""
    c = torch.tensor([0.0, 0.5, 1.0])
    for g in [0.0, -1.0, 0.001, 100.0]:
        res = remap_curve(c, gamma=g)
        assert res.shape[0] == 3
        assert not torch.isnan(res).any()
        assert not torch.isinf(res).any()


def test_remap_inverted_range():
    """Red-team: min_out > max_out (e.g. min_out=1.0, max_out=0.0)."""
    c = torch.tensor([0.0, 0.5, 1.0])
    res = remap_curve(c, min_out=1.0, max_out=0.0)
    assert abs(res[0].item() - 1.0) < 1e-5
    assert abs(res[2].item() - 0.0) < 1e-5


def test_remap_node_caller_mutation_safety():
    """Red-team: remap node must not mutate the input list/tensor in place."""
    original = [0.1, 0.5, 0.9]
    input_copy = list(original)
    node = MiniMaxH3AudioCurveRemap()
    (res,) = node.remap(input_copy, smooth_frames=3, gamma=2.0, threshold=0.2, min_out=0.0, max_out=5.0)
    assert input_copy == original


# ===========================================================================
# 5. Denoise Node Edge Cases & Type Polymorphism
# ===========================================================================

def test_denoise_nan_inf_safety():
    """Red-team: curve containing NaN/Inf must never produce NaN denoise strength."""
    node = MiniMaxH3AudioReactiveDenoise()
    for bad_curve in [[float("nan")], [float("inf")], [1.0, float("nan"), 0.5]]:
        (strength,) = node.map_strength(bad_curve, mode="peak", min_strength=0.5, max_strength=1.0)
        assert not math.isnan(strength)
        assert not math.isinf(strength)
        assert 0.0 <= strength <= 1.0


def test_denoise_scalar_float_input():
    """Red-team: user wires a single scalar float (e.g. 0.8) into curve."""
    node = MiniMaxH3AudioReactiveDenoise()
    (strength,) = node.map_strength(0.8, mode="peak", min_strength=0.0, max_strength=1.0)
    assert abs(strength - 0.8) < 1e-5


def test_denoise_unknown_mode_fallback():
    """Red-team: unknown reduction mode falls back safely."""
    node = MiniMaxH3AudioReactiveDenoise()
    (strength,) = node.map_strength([0.2, 0.8], mode="quantum_mode", min_strength=0.0, max_strength=1.0)
    assert 0.0 <= strength <= 1.0
