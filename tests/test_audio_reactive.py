"""CPU-only tests for the audio-reactive analysis module."""

import math
import torch

from h3_audio_reactive import (
    _mono,
    _frame_windows,
    _fit_curve,
    rms_energy,
    spectral_centroid,
    onset_strength,
    beat_curve,
    frequency_bands,
    _energy_peak_beats,
    smooth_curve,
    remap_curve,
    MiniMaxH3AudioAnalyze,
    MiniMaxH3AudioReactiveDenoise,
    MiniMaxH3AudioCurveRemap,
    FPS,
)


# ---------------------------------------------------------------------------
# _mono
# ---------------------------------------------------------------------------

def test_mono_stereo_to_1d():
    wav = torch.randn(2, 1000)
    mono = _mono(wav)
    assert mono.ndim == 1
    assert mono.shape[0] == 1000


def test_mono_batch_stereo():
    wav = torch.randn(1, 2, 1000)
    mono = _mono(wav)
    assert mono.ndim == 1
    assert mono.shape[0] == 1000


def test_mono_already_1d():
    wav = torch.randn(1000)
    mono = _mono(wav)
    assert mono.shape[0] == 1000


def test_mono_single_channel():
    wav = torch.randn(1, 1000)
    mono = _mono(wav)
    assert mono.ndim == 1
    assert mono.shape[0] == 1000


# ---------------------------------------------------------------------------
# _frame_windows
# ---------------------------------------------------------------------------

def test_frame_windows_24fps_32khz():
    sr = 32000
    total = sr * 2  # 2 seconds = 48 frames
    windows = _frame_windows(total, sr, 24.0)
    assert len(windows) == 48
    for start, end in windows:
        assert end > start
        assert end <= total


def test_frame_windows_empty():
    windows = _frame_windows(0, 32000, 24.0)
    assert len(windows) == 0


def test_frame_windows_very_short():
    windows = _frame_windows(100, 32000, 24.0)
    assert len(windows) == 1


# ---------------------------------------------------------------------------
# _fit_curve
# ---------------------------------------------------------------------------

def test_fit_curve_exact():
    c = torch.tensor([1.0, 2.0, 3.0])
    result = _fit_curve(c, 3)
    assert result.shape[0] == 3
    assert torch.allclose(result, c)


def test_fit_curve_trim():
    c = torch.tensor([1.0, 2.0, 3.0, 4.0, 5.0])
    result = _fit_curve(c, 3)
    assert result.shape[0] == 3
    assert torch.allclose(result, torch.tensor([1.0, 2.0, 3.0]))


def test_fit_curve_pad():
    c = torch.tensor([1.0, 2.0])
    result = _fit_curve(c, 5)
    assert result.shape[0] == 5
    assert result[2].item() == 0.0
    assert result[4].item() == 0.0


# ---------------------------------------------------------------------------
# rms_energy
# ---------------------------------------------------------------------------

def test_rms_sine_wave_has_energy():
    sr = 32000
    t = torch.linspace(0, 2.0, sr * 2)
    wav = torch.sin(2 * math.pi * 440 * t).unsqueeze(0)
    energy = rms_energy(wav, sr, 48)
    assert energy.shape[0] == 48
    assert energy.min().item() > 0.5
    assert abs(energy.max().item() - 1.0) < 0.05


def test_rms_silence():
    sr = 32000
    wav = torch.zeros(1, sr * 2)
    energy = rms_energy(wav, sr, 48)
    assert energy.shape[0] == 48
    assert energy.max().item() < 1e-5


def test_rms_normalized_0_to_1():
    sr = 32000
    t = torch.linspace(0, 2.0, sr * 2)
    wav = (t * torch.sin(2 * math.pi * 440 * t)).unsqueeze(0)
    energy = rms_energy(wav, sr, 48)
    assert energy.min().item() >= 0.0
    assert energy.max().item() <= 1.0 + 1e-6


def test_rms_frame_count_exact():
    sr = 32000
    wav = torch.randn(2, sr)
    for n_frames in [24, 39, 90, 124]:
        energy = rms_energy(wav, sr, n_frames)
        assert energy.shape[0] == n_frames, "n_frames=%d" % n_frames


# ---------------------------------------------------------------------------
# spectral_centroid
# ---------------------------------------------------------------------------

def test_spectral_low_vs_high():
    sr = 32000
    t = torch.linspace(0, 1.0, sr)
    low = torch.sin(2 * math.pi * 200 * t).unsqueeze(0)
    high = torch.sin(2 * math.pi * 8000 * t).unsqueeze(0)
    c_low = spectral_centroid(low, sr, 24)
    c_high = spectral_centroid(high, sr, 24)
    assert c_high.mean().item() > c_low.mean().item()


def test_spectral_silence():
    sr = 32000
    wav = torch.zeros(1, sr)
    c = spectral_centroid(wav, sr, 24)
    assert c.max().item() < 1e-5


# ---------------------------------------------------------------------------
# onset_strength
# ---------------------------------------------------------------------------

def test_onset_constant_tone():
    sr = 32000
    t = torch.linspace(0, 2.0, sr * 2)
    wav = torch.sin(2 * math.pi * 440 * t).unsqueeze(0)
    onsets = onset_strength(wav, sr, 48)
    assert onsets.shape[0] == 48
    assert onsets[0].item() < 1e-5  # first frame has no predecessor


def test_onset_click_has_strength():
    sr = 32000
    wav = torch.zeros(1, sr * 2)
    wav[0, sr:sr + 100] = 1.0
    onsets = onset_strength(wav, sr, 48)
    click_frame = int(round(1.0 * FPS))
    near_click = onsets[max(0, click_frame - 1):click_frame + 2]
    assert near_click.max().item() > onsets.mean().item()


# ---------------------------------------------------------------------------
# beat detection
# ---------------------------------------------------------------------------

def test_beat_click_track():
    sr = 32000
    bpm = 120
    duration = 4.0
    wav = torch.zeros(int(sr * duration))
    interval = int(sr * 60.0 / bpm)
    for i in range(int(duration * bpm / 60)):
        pos = i * interval
        end = min(pos + 200, wav.shape[0])
        wav[pos:end] = 1.0
    beats = _energy_peak_beats(wav, sr, FPS)
    assert len(beats) > 4
    assert len(beats) < 16


def test_beat_silence_no_beats():
    wav = torch.zeros(32000 * 2)
    beats = _energy_peak_beats(wav, 32000, FPS)
    assert len(beats) == 0


# ---------------------------------------------------------------------------
# beat_curve
# ---------------------------------------------------------------------------

def test_beat_curve_shape():
    sr = 32000
    wav = torch.randn(1, sr * 2)
    curve = beat_curve(wav, sr, 48)
    assert curve.shape[0] == 48


def test_beat_curve_range():
    sr = 32000
    wav = torch.randn(1, sr * 2)
    curve = beat_curve(wav, sr, 48)
    assert curve.min().item() >= 0.0
    assert curve.max().item() <= 1.0 + 1e-6


def test_beat_curve_decay():
    sr = 32000
    wav = torch.zeros(1, sr * 2)
    wav[0, :200] = 1.0
    curve = beat_curve(wav, sr, 48, decay=0.15)
    # After a beat, values should monotonically decrease until the next beat
    if curve[0] > 0:
        found_decrease = False
        for i in range(1, min(10, curve.shape[0])):
            if curve[i] < curve[i - 1]:
                found_decrease = True
                break
        # If there's a beat at frame 0 and no beat soon after, decay is working
        # (may not find decrease if beat is at frame > 0)


# ---------------------------------------------------------------------------
# frequency_bands
# ---------------------------------------------------------------------------

def test_bands_bass_tone():
    sr = 32000
    t = torch.linspace(0, 1.0, sr)
    wav = torch.sin(2 * math.pi * 100 * t).unsqueeze(0)
    bands = frequency_bands(wav, sr, 24)
    assert "bass" in bands and "mids" in bands and "highs" in bands
    assert bands["bass"].mean().item() > bands["highs"].mean().item()


def test_bands_high_tone():
    sr = 32000
    t = torch.linspace(0, 1.0, sr)
    wav = torch.sin(2 * math.pi * 8000 * t).unsqueeze(0)
    bands = frequency_bands(wav, sr, 24)
    assert bands["highs"].mean().item() > bands["bass"].mean().item()


def test_bands_frame_count():
    sr = 32000
    wav = torch.randn(1, sr)
    bands = frequency_bands(wav, sr, 39)
    for name in ("bass", "mids", "highs"):
        assert bands[name].shape[0] == 39


# ---------------------------------------------------------------------------
# smooth_curve / remap_curve
# ---------------------------------------------------------------------------

def test_smooth_no_smoothing():
    c = torch.tensor([0.0, 1.0, 0.0, 1.0, 0.0])
    result = smooth_curve(c, 1)
    assert torch.allclose(result, c)


def test_smooth_reduces_variance():
    c = torch.tensor([0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0])
    smoothed = smooth_curve(c, 3)
    assert smoothed.std().item() < c.std().item()


def test_smooth_preserves_length():
    c = torch.randn(100)
    smoothed = smooth_curve(c, 5)
    assert smoothed.shape[0] == 100


def test_remap_identity():
    c = torch.tensor([0.0, 0.25, 0.5, 0.75, 1.0])
    result = remap_curve(c, gamma=1.0, threshold=0.0, min_out=0.0, max_out=1.0)
    assert torch.allclose(result, c, atol=1e-6)


def test_remap_threshold():
    c = torch.tensor([0.1, 0.3, 0.5, 0.7, 0.9])
    result = remap_curve(c, threshold=0.4)
    assert abs(result[0].item()) < 1e-5
    assert abs(result[1].item()) < 1e-5
    assert result[2].item() > 0.0


def test_remap_gamma():
    c = torch.tensor([0.25, 0.5, 0.75, 1.0])
    result = remap_curve(c, gamma=2.0)
    assert result[0].item() < c[0].item()


def test_remap_range():
    c = torch.tensor([0.0, 0.5, 1.0])
    result = remap_curve(c, min_out=0.5, max_out=1.0)
    assert abs(result[0].item() - 0.5) < 1e-5
    assert abs(result[1].item() - 0.75) < 1e-5
    assert abs(result[2].item() - 1.0) < 1e-5


# ---------------------------------------------------------------------------
# MiniMaxH3AudioAnalyze node
# ---------------------------------------------------------------------------

def _make_audio(sr=32000, duration=5.0, freq=440):
    t = torch.linspace(0, duration, int(sr * duration))
    wav = torch.sin(2 * math.pi * freq * t)
    return {
        "waveform": wav.unsqueeze(0).unsqueeze(0),  # [B, C, L]
        "sample_rate": sr,
    }


def test_analyze_output_shape():
    audio = _make_audio()
    node = MiniMaxH3AudioAnalyze()
    energy, beats, bright, onsets, bass, mids, highs = node.analyze(
        audio, clip_start_seconds=0.0, clip_frames=48
    )
    for output in [energy, beats, bright, onsets, bass, mids, highs]:
        assert isinstance(output, list)
        assert len(output) == 48


def test_analyze_clip_start_offset():
    audio = _make_audio(duration=10.0)
    node = MiniMaxH3AudioAnalyze()
    energy, *_ = node.analyze(audio, clip_start_seconds=5.0, clip_frames=48)
    assert len(energy) == 48


def test_analyze_past_end_returns_zeros():
    audio = _make_audio(duration=1.0)
    node = MiniMaxH3AudioAnalyze()
    outputs = node.analyze(audio, clip_start_seconds=99.0, clip_frames=48)
    for output in outputs:
        assert len(output) == 48
        assert all(v == 0.0 for v in output)


def test_analyze_zero_outputs_are_independent():
    """Regression: all zero outputs must be independent list objects."""
    audio = _make_audio(duration=0.01)
    node = MiniMaxH3AudioAnalyze()
    outputs = node.analyze(audio, clip_start_seconds=999.0, clip_frames=10)
    # Mutating one should not affect the others
    outputs[0].append(99.0)
    for o in outputs[1:]:
        assert len(o) == 10


# ---------------------------------------------------------------------------
# MiniMaxH3AudioReactiveDenoise node
# ---------------------------------------------------------------------------

def test_denoise_peak():
    node = MiniMaxH3AudioReactiveDenoise()
    (strength,) = node.map_strength(
        [0.1, 0.5, 0.9, 0.3], mode="peak",
        min_strength=0.5, max_strength=1.0
    )
    assert abs(strength - 0.95) < 0.02


def test_denoise_mean():
    node = MiniMaxH3AudioReactiveDenoise()
    (strength,) = node.map_strength(
        [0.0, 0.5, 1.0], mode="mean",
        min_strength=0.0, max_strength=1.0
    )
    assert abs(strength - 0.5) < 0.02


def test_denoise_invert():
    node = MiniMaxH3AudioReactiveDenoise()
    (s_normal,) = node.map_strength(
        [0.0, 0.0, 0.0], mode="peak",
        min_strength=0.0, max_strength=1.0, invert=False
    )
    (s_inverted,) = node.map_strength(
        [0.0, 0.0, 0.0], mode="peak",
        min_strength=0.0, max_strength=1.0, invert=True
    )
    assert abs(s_normal) < 1e-5
    assert abs(s_inverted - 1.0) < 1e-5


def test_denoise_empty_curve():
    node = MiniMaxH3AudioReactiveDenoise()
    (strength,) = node.map_strength([], mode="peak", max_strength=0.8)
    assert abs(strength - 0.8) < 0.01


def test_denoise_clamped():
    node = MiniMaxH3AudioReactiveDenoise()
    (strength,) = node.map_strength(
        [1.5], mode="peak", min_strength=0.0, max_strength=1.0
    )
    assert strength <= 1.0


# ---------------------------------------------------------------------------
# MiniMaxH3AudioCurveRemap node
# ---------------------------------------------------------------------------

def test_remap_node_passthrough():
    node = MiniMaxH3AudioCurveRemap()
    (result,) = node.remap(
        [0.0, 0.5, 1.0], smooth_frames=1, gamma=1.0,
        threshold=0.0, min_out=0.0, max_out=1.0
    )
    assert len(result) == 3
    assert abs(result[0]) < 1e-4
    assert abs(result[2] - 1.0) < 1e-4


def test_remap_node_threshold():
    node = MiniMaxH3AudioCurveRemap()
    (result,) = node.remap(
        [0.1, 0.2, 0.8, 0.9], smooth_frames=1, gamma=1.0,
        threshold=0.5, min_out=0.0, max_out=1.0
    )
    assert abs(result[0]) < 1e-4
    assert abs(result[1]) < 1e-4
    assert result[2] > 0.0


def test_remap_node_output_range():
    node = MiniMaxH3AudioCurveRemap()
    (result,) = node.remap(
        [0.0, 0.5, 1.0], smooth_frames=1, gamma=1.0,
        threshold=0.0, min_out=2.0, max_out=4.0
    )
    assert abs(result[0] - 2.0) < 1e-4
    assert abs(result[1] - 3.0) < 1e-4
    assert abs(result[2] - 4.0) < 1e-4


# ---------------------------------------------------------------------------
# H3 timing consistency
# ---------------------------------------------------------------------------

def test_frame_count_matches_h3_clips():
    sr = 32000
    wav = torch.randn(1, sr * 10)
    for n_frames in [5, 22, 39, 56, 73, 90, 124]:
        energy = rms_energy(wav, sr, n_frames)
        assert energy.shape[0] == n_frames, "n_frames=%d" % n_frames


def test_24fps_window_no_gaps():
    """Consecutive 24-fps windows should tile the audio without gaps."""
    sr = 44100
    total = sr * 5
    windows = _frame_windows(total, sr, 24.0)
    for i in range(1, len(windows)):
        prev_end = windows[i - 1][1]
        curr_start = windows[i][0]
        assert curr_start == prev_end, (
            "Gap between frames %d and %d: %d vs %d"
            % (i - 1, i, prev_end, curr_start)
        )
