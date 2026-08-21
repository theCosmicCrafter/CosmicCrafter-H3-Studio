"""Audio-reactive analysis for MiniMax H3 music-video workflows.

Extracts per-frame energy, beat, spectral, and onset signals from a master
song waveform so they can drive visual generation parameters (denoise
strength, prompt weights, reference blending, etc.).

All analysis functions operate on PyTorch tensors and align to H3's native
24 fps video grid.  ``librosa`` is used for beat tracking when available;
everything else is pure PyTorch with no additional dependencies.
"""

import logging
import math

import torch

_LOG = logging.getLogger("h3_motion_context.audio_reactive")

FPS = 24.0

# ---------------------------------------------------------------------------
# Optional librosa import — used only for beat tracking
# ---------------------------------------------------------------------------

try:
    import librosa
except ImportError:
    librosa = None

try:
    import numpy as np
except ImportError:
    np = None


# ---------------------------------------------------------------------------
# Core analysis helpers
# ---------------------------------------------------------------------------

def _mono(waveform):
    """Reduce arbitrary audio tensor to 1D mono float32 [L]."""
    if not isinstance(waveform, torch.Tensor):
        waveform = torch.tensor(waveform)

    # Ensure floating-point before any reduction math (int16/int32 mean() fails in torch)
    if not waveform.is_floating_point():
        waveform = waveform.float()

    # Squeeze extra leading singleton dimensions (e.g. [1, 1, 2, L] -> [2, L])
    while waveform.ndim > 2:
        if waveform.shape[0] == 1:
            waveform = waveform.squeeze(0)
        else:
            waveform = waveform[0]  # Take first batch item

    if waveform.ndim == 2:
        if waveform.shape[0] == 0 or waveform.shape[1] == 0:
            return torch.zeros(0, dtype=torch.float32, device=waveform.device)
        waveform = waveform.mean(dim=0)

    if waveform.ndim == 0:
        return torch.zeros(0, dtype=torch.float32, device=waveform.device)

    # Sanitize NaNs and Infs to clean numbers
    waveform = torch.nan_to_num(waveform, nan=0.0, posinf=1.0, neginf=-1.0)
    return waveform


def _frame_windows(total_samples, sr, fps=FPS):
    """Return (start, end) sample indices for each video frame."""
    total_samples = max(0, int(total_samples))
    if total_samples == 0:
        return []
    sr = max(1.0, float(sr))
    fps = max(0.001, float(fps))
    hop = sr / fps

    frames = []
    i = 0
    while True:
        start = int(round(i * hop))
        end = int(round((i + 1) * hop))
        if start >= total_samples:
            break
        end = min(end, total_samples)
        frames.append((start, max(start, end)))
        i += 1
    return frames


def _fit_curve(curve, n_frames):
    """Pad or trim a 1-D curve to exactly n_frames, returning float32 tensor."""
    n = max(0, int(n_frames))
    if n == 0:
        return torch.zeros(0, dtype=torch.float32)

    if not isinstance(curve, torch.Tensor):
        curve = torch.tensor(curve, dtype=torch.float32)
    else:
        curve = curve.float()

    if curve.ndim == 0:
        curve = curve.unsqueeze(0)
    elif curve.ndim > 1:
        curve = curve.flatten()

    curve = torch.nan_to_num(curve, nan=0.0, posinf=1.0, neginf=0.0)

    have = int(curve.shape[0])
    if have == n:
        return curve
    if have > n:
        return curve[:n]
    return torch.nn.functional.pad(curve, (0, n - have))


def rms_energy(waveform, sr, n_frames, fps=FPS):
    """Per-frame RMS energy, normalized to 0–1.

    Parameters
    ----------
    waveform : Tensor [C, L] or [B, C, L]
    sr : int or float — sample rate
    n_frames : int — exact number of output frames
    fps : float

    Returns
    -------
    Tensor [n_frames] float32, range [0, 1]
    """
    n_frames = max(0, int(n_frames))
    if n_frames == 0:
        return torch.zeros(0, dtype=torch.float32)

    mono = _mono(waveform)
    windows = _frame_windows(int(mono.shape[0]), sr, fps)
    energies = []
    for start, end in windows:
        if start >= end:
            energies.append(0.0)
        else:
            chunk = mono[start:end]
            val = torch.sqrt(torch.mean(chunk * chunk)).item()
            energies.append(val if not math.isnan(val) and not math.isinf(val) else 0.0)

    curve = torch.tensor(energies, dtype=torch.float32, device=mono.device)
    curve = _fit_curve(curve, n_frames)
    if curve.numel() > 0:
        peak = curve.max()
        if peak > 0:
            curve = curve / peak
    return curve.cpu()


def spectral_centroid(waveform, sr, n_frames, fps=FPS, n_fft=2048):
    """Per-frame spectral centroid (brightness), normalized to 0–1.

    Higher values = brighter / more treble content.
    """
    n_frames = max(0, int(n_frames))
    if n_frames == 0:
        return torch.zeros(0, dtype=torch.float32)

    mono = _mono(waveform)
    sr = max(1.0, float(sr))
    windows = _frame_windows(int(mono.shape[0]), sr, fps)

    # Pre-allocate frequencies and Hann window
    n_fft = max(64, int(n_fft))
    freqs = torch.linspace(0, sr / 2.0, n_fft // 2 + 1, device=mono.device)
    window = torch.hann_window(n_fft, device=mono.device)

    centroids = []
    for start, end in windows:
        if end - start < 2:
            centroids.append(0.0)
            continue
        chunk = mono[start:end]
        if chunk.shape[0] < n_fft:
            chunk = torch.nn.functional.pad(chunk, (0, n_fft - chunk.shape[0]))
        else:
            chunk = chunk[:n_fft]

        spec = torch.fft.rfft(chunk * window).abs()
        total = spec.sum()
        if total > 1e-8:
            centroid = (freqs * spec).sum() / total
            # Normalize against Nyquist (sr / 2) so output is physical brightness [0, 1]
            val = (centroid / (sr / 2.0)).item()
            centroids.append(max(0.0, min(1.0, val)) if not math.isnan(val) and not math.isinf(val) else 0.0)
        else:
            centroids.append(0.0)

    curve = torch.tensor(centroids, dtype=torch.float32, device=mono.device)
    curve = _fit_curve(curve, n_frames)
    return curve.cpu()


def onset_strength(waveform, sr, n_frames, fps=FPS, n_fft=2048):
    """Per-frame onset/transient strength via spectral flux, normalized to 0–1."""
    n_frames = max(0, int(n_frames))
    if n_frames == 0:
        return torch.zeros(0, dtype=torch.float32)

    mono = _mono(waveform)
    windows = _frame_windows(int(mono.shape[0]), sr, fps)

    n_fft = max(64, int(n_fft))
    window = torch.hann_window(n_fft, device=mono.device)

    onsets = []
    prev_spec = None

    for start, end in windows:
        if end - start < 2:
            spec = torch.zeros(n_fft // 2 + 1, device=mono.device)
        else:
            chunk = mono[start:end]
            if chunk.shape[0] < n_fft:
                chunk = torch.nn.functional.pad(chunk, (0, n_fft - chunk.shape[0]))
            else:
                chunk = chunk[:n_fft]
            spec = torch.fft.rfft(chunk * window).abs()

        if prev_spec is None:
            onsets.append(0.0)
        else:
            diff = spec - prev_spec
            flux = torch.clamp(diff, min=0.0).sum().item()
            onsets.append(flux if not math.isnan(flux) and not math.isinf(flux) else 0.0)
        prev_spec = spec

    curve = torch.tensor(onsets, dtype=torch.float32, device=mono.device)
    curve = _fit_curve(curve, n_frames)
    if curve.numel() > 0:
        peak = curve.max()
        if peak > 0:
            curve = curve / peak
    return curve.cpu()


def beat_frames_detect(waveform, sr, fps=FPS):
    """Detect beat frame indices.

    Uses librosa when available for musically-aware beat tracking.
    Falls back to energy-peak detection otherwise.
    """
    mono = _mono(waveform)
    if mono.shape[0] == 0:
        return []

    sr = max(1.0, float(sr))
    fps = max(0.001, float(fps))

    if librosa is not None and np is not None:
        try:
            audio_np = mono.cpu().numpy().astype(np.float32)
            _tempo, beat_samples = librosa.beat.beat_track(
                y=audio_np, sr=int(round(sr)), units="samples"
            )
            frames = []
            for s in beat_samples:
                f = int(round(float(s) / sr * fps))
                frames.append(f)
            return sorted(set(frames))
        except Exception as e:
            _LOG.warning("librosa beat_track failed (%s), falling back to energy peak", e)

    return _energy_peak_beats(mono, sr, fps)


def _energy_peak_beats(mono, sr, fps, min_interval_frames=4):
    """Energy-based beat detection fallback using frame windows."""
    windows = _frame_windows(int(mono.shape[0]), sr, fps)
    if not windows:
        return []

    energies = []
    for start, end in windows:
        if start >= end:
            energies.append(0.0)
        else:
            chunk = mono[start:end]
            val = torch.sqrt(torch.mean(chunk * chunk)).item()
            energies.append(val if not math.isnan(val) and not math.isinf(val) else 0.0)

    energies = torch.tensor(energies, dtype=torch.float32)
    if energies.numel() < 3 or energies.max() <= 1e-8:
        return []

    std = energies.std().item()
    threshold = energies.mean().item() + 0.5 * (std if not math.isnan(std) else 0.0)

    beats = []
    for i in range(1, int(energies.shape[0]) - 1):
        val = energies[i].item()
        if val > threshold:
            if val >= energies[i - 1].item() and val >= energies[i + 1].item():
                if not beats or (i - beats[-1]) >= min_interval_frames:
                    beats.append(i)
    return beats


def beat_curve(waveform, sr, n_frames, fps=FPS, decay=0.15):
    """Beat pulse curve: 1.0 at each beat, exponential decay between.

    Parameters
    ----------
    decay : float — decay rate per frame. Higher = faster fade.
    """
    n_frames = max(0, int(n_frames))
    if n_frames == 0:
        return torch.zeros(0, dtype=torch.float32)

    beat_indices = beat_frames_detect(waveform, sr, fps)
    curve = torch.zeros(n_frames, dtype=torch.float32)
    for b in beat_indices:
        if 0 <= b < n_frames:
            curve[b] = 1.0

    # Ensure decay rate is non-negative to avoid exponential runaway
    decay_rate = max(0.0, float(decay))
    decay_factor = math.exp(-decay_rate)

    # Forward exponential decay
    for i in range(1, n_frames):
        if curve[i] < curve[i - 1]:
            decayed = curve[i - 1] * decay_factor
            curve[i] = max(curve[i], min(1.0, decayed))

    return curve


def frequency_bands(waveform, sr, n_frames, fps=FPS, n_fft=2048,
                    band_edges=None):
    """Per-frame energy in frequency bands, each normalized to 0–1."""
    n_frames = max(0, int(n_frames))
    sr = max(1.0, float(sr))
    nyquist = sr / 2.0

    if band_edges is None:
        band_edges = [
            ("bass", 20.0, min(250.0, nyquist)),
            ("mids", min(250.0, nyquist), min(4000.0, nyquist)),
            ("highs", min(4000.0, nyquist), nyquist),
        ]

    if n_frames == 0:
        return {name: torch.zeros(0, dtype=torch.float32) for name, _, _ in band_edges}

    mono = _mono(waveform)
    windows = _frame_windows(int(mono.shape[0]), sr, fps)

    n_fft = max(64, int(n_fft))
    freq_bins = torch.linspace(0, nyquist, n_fft // 2 + 1, device=mono.device)
    window = torch.hann_window(n_fft, device=mono.device)

    # Precompute masks for each band
    masks = {}
    for name, low, high in band_edges:
        low_val = max(0.0, float(low))
        high_val = min(nyquist, max(low_val, float(high)))
        masks[name] = (freq_bins >= low_val) & (freq_bins <= high_val)

    band_curves = {name: [] for name, _, _ in band_edges}

    for start, end in windows:
        if end - start < 2:
            for name in masks:
                band_curves[name].append(0.0)
            continue
        chunk = mono[start:end]
        if chunk.shape[0] < n_fft:
            chunk = torch.nn.functional.pad(chunk, (0, n_fft - chunk.shape[0]))
        else:
            chunk = chunk[:n_fft]

        spec = torch.fft.rfft(chunk * window).abs()
        for name, mask in masks.items():
            energy_sum = spec[mask].sum().item()
            band_curves[name].append(energy_sum if not math.isnan(energy_sum) and not math.isinf(energy_sum) else 0.0)

    result = {}
    for name, _, _ in band_edges:
        curve = torch.tensor(band_curves[name], dtype=torch.float32, device=mono.device)
        curve = _fit_curve(curve, n_frames)
        if curve.numel() > 0:
            peak = curve.max()
            if peak > 1e-5:
                curve = curve / peak
        result[name] = curve.cpu()

    return result


# ---------------------------------------------------------------------------
# Curve utilities
# ---------------------------------------------------------------------------

def smooth_curve(curve, window_size):
    """Moving-average smoothing on a 1-D curve."""
    if not isinstance(curve, torch.Tensor):
        curve = torch.tensor(curve, dtype=torch.float32)
    else:
        curve = curve.float()

    if curve.ndim == 0:
        return curve
    if curve.numel() <= 1:
        return curve

    w = max(1, int(window_size))
    if w <= 1:
        return curve

    # Clamp window size to curve length to avoid invalid padding
    w = min(w, int(curve.numel()))
    if w <= 1:
        return curve

    kernel = torch.ones(1, 1, w, dtype=curve.dtype, device=curve.device) / float(w)
    padded = torch.nn.functional.pad(
        curve.unsqueeze(0).unsqueeze(0),
        (w // 2, w - w // 2 - 1),
        mode="replicate",
    )
    return torch.nn.functional.conv1d(padded, kernel).squeeze(0).squeeze(0)


def remap_curve(curve, gamma=1.0, threshold=0.0, min_out=0.0, max_out=1.0):
    """Apply power-law, threshold, and range remapping to a 0–1 curve."""
    if not isinstance(curve, torch.Tensor):
        curve = torch.tensor(curve, dtype=torch.float32)
    else:
        curve = curve.float()

    c = torch.nan_to_num(curve.clone(), nan=0.0, posinf=1.0, neginf=0.0)

    # Apply threshold noise gate
    thresh = float(threshold)
    if thresh > 0.0:
        c = torch.where(c < thresh, torch.zeros_like(c), c)

    # Apply power law shaping safely
    g = max(0.01, float(gamma))
    if abs(g - 1.0) > 1e-4:
        c = torch.pow(c.clamp(min=0.0, max=1.0), g)

    # Linear range mapping
    min_v = float(min_out)
    max_v = float(max_out)
    c = min_v + c * (max_v - min_v)
    return torch.nan_to_num(c, nan=min_v, posinf=max_v, neginf=min_v)


# ---------------------------------------------------------------------------
# ComfyUI node classes
# ---------------------------------------------------------------------------

class MiniMaxH3AudioAnalyze:
    """Extract per-frame audio features from a master song for reactive generation."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "audio": ("AUDIO", {
                    "tooltip": "Master song or clip audio to analyze."
                }),
                "clip_start_seconds": ("FLOAT", {
                    "default": 0.0, "min": 0.0, "max": 99999.0, "step": 0.001,
                    "tooltip": "Start of the analysis window in the master timeline (seconds)."
                }),
                "clip_frames": ("INT", {
                    "default": 124, "min": 0, "max": 99999,
                    "tooltip": "Number of output frames (should match the H3 target clip frame count)."
                }),
                "beat_decay": ("FLOAT", {
                    "default": 0.15, "min": 0.0, "max": 2.0, "step": 0.01,
                    "tooltip": "Exponential decay rate for the beat pulse curve. Higher = faster fade between beats."
                }),
                "sensitivity": ("FLOAT", {
                    "default": 1.0, "min": 0.0, "max": 5.0, "step": 0.1,
                    "tooltip": "Onset detection sensitivity multiplier. Higher = more sensitive to transients."
                }),
            },
        }

    RETURN_TYPES = ("FLOAT", "FLOAT", "FLOAT", "FLOAT", "FLOAT", "FLOAT", "FLOAT")
    RETURN_NAMES = ("energy", "beats", "brightness", "onsets", "bass", "mids", "highs")
    FUNCTION = "analyze"
    CATEGORY = "conditioning/minimax"
    DESCRIPTION = (
        "Extract per-frame audio features from a master song: RMS energy, "
        "beat pulse, spectral brightness, onset strength, and bass/mids/highs "
        "frequency bands.  Each output is a list of floats with one value per "
        "frame at 24 fps, suitable for wiring into denoise, prompt weight, "
        "or other per-frame parameters."
    )

    def analyze(self, audio, clip_start_seconds=0.0, clip_frames=124,
                beat_decay=0.15, sensitivity=1.0):
        n_frames = max(0, int(clip_frames))
        if n_frames == 0:
            return tuple([] for _ in range(7))

        if not isinstance(audio, dict) or "waveform" not in audio or "sample_rate" not in audio:
            return tuple([0.0] * n_frames for _ in range(7))

        waveform = audio["waveform"]
        sr = max(1.0, float(audio["sample_rate"]))

        # Sanitize start time: clamp to non-negative to avoid backwards indexing
        start_sec = max(0.0, float(clip_start_seconds))
        start_sample = int(round(start_sec * sr))
        end_sample = int(round((start_sec + n_frames / FPS) * sr))

        if not isinstance(waveform, torch.Tensor):
            waveform = torch.tensor(waveform)

        # Ensure 2D [C, L]
        if waveform.ndim == 3:
            wav = waveform[0]
        else:
            wav = waveform

        total_samples = int(wav.shape[-1]) if wav.ndim > 0 else 0
        start_sample = min(start_sample, total_samples)
        end_sample = min(max(start_sample, end_sample), total_samples)

        if end_sample <= start_sample or total_samples == 0:
            return tuple([0.0] * n_frames for _ in range(7))

        clip_wav = wav[..., start_sample:end_sample]

        # Run analysis
        energy = rms_energy(clip_wav, sr, n_frames)
        bright = spectral_centroid(clip_wav, sr, n_frames)
        onsets = onset_strength(clip_wav, sr, n_frames)
        beats = beat_curve(clip_wav, sr, n_frames, decay=max(0.0, float(beat_decay)))
        bands = frequency_bands(clip_wav, sr, n_frames)

        # Apply sensitivity to onsets
        sens = max(0.0, float(sensitivity))
        if sens != 1.0:
            onsets = (onsets * sens).clamp(0.0, 1.0)

        # Convert to lists for ComfyUI FLOAT output
        return (
            energy.tolist(),
            beats.tolist(),
            bright.tolist(),
            onsets.tolist(),
            bands["bass"].tolist(),
            bands["mids"].tolist(),
            bands["highs"].tolist(),
        )


class MiniMaxH3AudioReactiveDenoise:
    """Map an audio curve to a denoise strength scalar."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "curve": ("FLOAT", {
                    "forceInput": True,
                    "tooltip": "Per-frame audio curve from H3 Audio Analyze (or scalar float)."
                }),
                "mode": (["peak", "mean", "median"], {
                    "default": "peak",
                    "tooltip": "How to reduce the per-frame curve to a single value. "
                               "peak = maximum value, mean = average, median = middle value."
                }),
                "min_strength": ("FLOAT", {
                    "default": 0.7, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "Denoise strength at the quietest point of the curve."
                }),
                "max_strength": ("FLOAT", {
                    "default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "Denoise strength at the loudest point of the curve."
                }),
                "invert": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "Flip the mapping: quiet sections get high denoise, loud sections get low."
                }),
            },
        }

    RETURN_TYPES = ("FLOAT",)
    RETURN_NAMES = ("denoise_strength",)
    FUNCTION = "map_strength"
    CATEGORY = "conditioning/minimax"
    DESCRIPTION = (
        "Map any per-frame audio curve to a single denoise strength value. "
        "Wire the output into a sampler's denoise input to make generation "
        "intensity react to the music."
    )

    def map_strength(self, curve, mode="peak", min_strength=0.7,
                     max_strength=1.0, invert=False):
        if isinstance(curve, (int, float)):
            t = torch.tensor([float(curve)], dtype=torch.float32)
        elif isinstance(curve, (list, tuple)):
            t = torch.tensor(curve, dtype=torch.float32)
        elif isinstance(curve, torch.Tensor):
            t = curve.float()
        else:
            t = torch.tensor([float(curve)], dtype=torch.float32)

        t = torch.nan_to_num(t.flatten(), nan=0.0, posinf=1.0, neginf=0.0)

        if t.numel() == 0:
            return (max(0.0, min(1.0, float(max_strength))),)

        if mode == "peak":
            value = t.max().item()
        elif mode == "mean":
            value = t.mean().item()
        elif mode == "median":
            value = t.median().item()
        else:
            value = t.max().item()

        value = max(0.0, min(1.0, float(value)))

        if bool(invert):
            value = 1.0 - value

        min_s = float(min_strength)
        max_s = float(max_strength)
        strength = min_s + value * (max_s - min_s)
        strength = max(0.0, min(1.0, strength))
        return (strength,)


class MiniMaxH3AudioCurveRemap:
    """General-purpose curve remapping: smooth, shape, threshold, rescale."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "curve": ("FLOAT", {
                    "forceInput": True,
                    "tooltip": "Per-frame audio curve from H3 Audio Analyze."
                }),
                "smooth_frames": ("INT", {
                    "default": 3, "min": 1, "max": 120, "step": 1,
                    "tooltip": "Moving-average smoothing window in frames. 1 = no smoothing."
                }),
                "gamma": ("FLOAT", {
                    "default": 1.0, "min": 0.01, "max": 5.0, "step": 0.05,
                    "tooltip": "Power-law curve shaping. >1 compresses quiet values, <1 expands them."
                }),
                "threshold": ("FLOAT", {
                    "default": 0.0, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "Gate: values below this become 0."
                }),
                "min_out": ("FLOAT", {
                    "default": 0.0, "min": -10.0, "max": 10.0, "step": 0.01,
                    "tooltip": "Output range floor."
                }),
                "max_out": ("FLOAT", {
                    "default": 1.0, "min": -10.0, "max": 10.0, "step": 0.01,
                    "tooltip": "Output range ceiling."
                }),
            },
        }

    RETURN_TYPES = ("FLOAT",)
    RETURN_NAMES = ("curve",)
    FUNCTION = "remap"
    CATEGORY = "conditioning/minimax"
    DESCRIPTION = (
        "Remap any per-frame audio curve with smoothing, power-law shaping, "
        "thresholding, and range scaling.  Chain multiple instances for "
        "complex reactive behaviors."
    )

    def remap(self, curve, smooth_frames=3, gamma=1.0, threshold=0.0,
              min_out=0.0, max_out=1.0):
        if isinstance(curve, (int, float)):
            t = torch.tensor([float(curve)], dtype=torch.float32)
        elif isinstance(curve, (list, tuple)):
            t = torch.tensor(curve, dtype=torch.float32)
        elif isinstance(curve, torch.Tensor):
            t = curve.float().clone()
        else:
            t = torch.tensor([float(curve)], dtype=torch.float32)

        t = torch.nan_to_num(t.flatten(), nan=0.0, posinf=1.0, neginf=0.0)

        if t.numel() == 0:
            return ([],)

        t = smooth_curve(t, int(smooth_frames))
        t = remap_curve(t, gamma=float(gamma), threshold=float(threshold),
                        min_out=float(min_out), max_out=float(max_out))

        return (t.tolist(),)
