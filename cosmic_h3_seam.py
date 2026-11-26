# -*- coding: utf-8 -*-
"""cosmic_h3_seam.py — Seam Protection, Luminance Matching & Audiovisual Handover

Provides sample-accurate and pixel-consistent boundary harmonization for MiniMax H3:
1. Relative ITU-R BT.709 luminance gain estimation and S-curve gain fading to prevent
   exposure jumps between sequential clips.
2. Equal-power cosine/sine audio crossfading to eliminate energy dips and transient clicks.
3. Micro-fading on waveform boundaries to prevent DC offset popping.
4. Harmonized prefix trimming across H3 AV latents, pixel frames, and audio streams.
5. Standalone node implementations: CosmicCrafterSeamProtector and CosmicCrafterTrimPrefixLatent.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, Optional, Tuple, Union

import torch
import torch.nn.functional as F

_LOG = logging.getLogger("cosmic_crafter.seam")
FPS = 24.0
AUDIO_HZ = 40.0
FRAME_PER_TOKEN = (1, 4, 4, 4, 4)


# ============================================================================
# 1. Luminance Matching Math
# ============================================================================

def rgb_luminance(images: torch.Tensor) -> torch.Tensor:
    """Calculates ITU-R BT.709 relative luminance from RGB channels:
    Y = 0.2126 R + 0.7152 G + 0.0722 B
    """
    rgb = images[..., :3].float()
    return rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722


def estimate_luminance_gain(
    previous_context: torch.Tensor,
    next_context: torch.Tensor,
    max_correction_percent: float = 10.0,
) -> float:
    """Estimates conservative global RGB gain between time-overlapping frames.
    
    Subsamples spatial resolution for performance and filters out extreme highlights
    and shadows (valid midtones: 0.04 < luma < 0.96) to prevent bias from blown-out
    specular highlights or crushed blacks.
    """
    if getattr(previous_context, "ndim", 0) != 4 or getattr(next_context, "ndim", 0) != 4:
        return 1.0
    if previous_context.shape != next_context.shape or previous_context.shape[0] == 0:
        return 1.0

    # Subsample spatially (every 4th pixel) for speed
    prev_luma = rgb_luminance(previous_context)[:, ::4, ::4]
    next_luma = rgb_luminance(next_context.to(previous_context.device))[:, ::4, ::4]

    ratios = []
    for i in range(previous_context.shape[0]):
        a = prev_luma[i]
        b = next_luma[i]
        valid = (a > 0.04) & (a < 0.96) & (b > 0.04) & (b < 0.96)
        if valid.sum() < max(4, int(valid.numel() * 0.01)):
            continue
        a_mean = float(a[valid].mean().item())
        b_mean = float(b[valid].mean().item())
        if b_mean > 1e-6:
            ratios.append(a_mean / b_mean)

    if not ratios:
        return 1.0

    measured = float(torch.tensor(ratios, dtype=torch.float32).median().item())
    limit = max(0.0, float(max_correction_percent)) / 100.0
    return min(1.0 + limit, max(max(0.01, 1.0 - limit), measured))


def apply_luminance_gain_fade(
    images: torch.Tensor,
    gain: float,
    fade_frames: int = 12,
) -> torch.Tensor:
    """Smoothly transitions luminance gain across frames using a cosine S-curve.
    
    Over fade_frames, gain transitions from the calculated factor back to 1.0,
    ensuring seamless color consistency at the cut without affecting the long-term
    color grade of the rest of the clip.
    """
    if images is None or images.shape[0] == 0 or abs(gain - 1.0) < 1e-4:
        return images

    out = images.clone().float()
    n_frames = int(out.shape[0])
    fade_len = min(n_frames, max(1, int(fade_frames)))

    t = torch.linspace(0.0, math.pi, fade_len, device=out.device, dtype=torch.float32)
    # Cosine S-curve: 1.0 at start down to 0.0 at end of fade window
    fade_curve = 0.5 * (1.0 + torch.cos(t)).view(-1, 1, 1, 1)

    cur_gain = 1.0 + (gain - 1.0) * fade_curve
    out[:fade_len] = (out[:fade_len] * cur_gain).clamp(0.0, 1.0)
    return out.to(images.dtype)


def blend_seam_images(
    tail: torch.Tensor,
    head: torch.Tensor,
    overlap_frames: int,
    match_luminance: bool = True,
    max_gain_percent: float = 10.0,
) -> Tuple[torch.Tensor, torch.Tensor]:
    """Blends overlapping image tails and heads with luminance compensation.
    
    Returns (blended_overlap, remaining_head).
    """
    ov = min(int(overlap_frames), int(tail.shape[0]), int(head.shape[0]))
    if ov <= 0:
        return torch.empty((0, *tail.shape[1:]), dtype=tail.dtype, device=tail.device), head

    tail_overlap = tail[-ov:].clone().float()
    head_overlap = head[:ov].clone().float()
    remainder_head = head[ov:].clone()

    if match_luminance:
        gain = estimate_luminance_gain(tail_overlap, head_overlap, max_gain_percent)
        if abs(gain - 1.0) > 1e-4:
            head_overlap = (head_overlap * gain).clamp(0.0, 1.0)
            if remainder_head.shape[0] > 0:
                remainder_head = apply_luminance_gain_fade(
                    remainder_head, gain, fade_frames=max(12, ov)
                )

    # Cosine equal-energy crossfade curve across the overlap frames
    t = torch.linspace(0.0, 1.0, ov + 2, device=tail.device, dtype=torch.float32)[1:-1].view(-1, 1, 1, 1)
    blended = tail_overlap * (1.0 - t) + head_overlap * t
    return blended.clamp(0.0, 1.0).to(tail.dtype), remainder_head


# ============================================================================
# 2. Equal-Power Audio Crossfade & Microfade Math
# ============================================================================

def fit_audio_length_with_microfade(
    waveform: torch.Tensor,
    target_samples: int,
    fade_len: int = 32,
) -> torch.Tensor:
    """Pads or truncates audio waveform to exact target samples without DC clicks.
    
    Applies a smooth cosine micro fade-out on the tail before truncating or zero-padding.
    """
    target = max(0, int(target_samples))
    current = int(waveform.shape[-1])
    if current == target:
        return waveform
    if current > target:
        # Micro fade-out before truncation
        f_len = min(target, fade_len)
        if f_len > 0:
            out = waveform[..., :target].clone()
            t = torch.linspace(0.0, math.pi, f_len, device=out.device, dtype=out.dtype)
            fade = 0.5 * (1.0 + torch.cos(t))
            while fade.ndim < out.ndim:
                fade = fade.unsqueeze(0)
            out[..., -f_len:] = out[..., -f_len:] * fade
            return out
        return waveform[..., :target]

    if target == 0:
        return waveform[..., :0]
    if current == 0:
        shape = list(waveform.shape)
        shape[-1] = target
        return torch.zeros(shape, dtype=waveform.dtype, device=waveform.device)

    # Micro fade-out before zero padding
    f_len = min(current, fade_len)
    wave_copy = waveform.clone()
    if f_len > 0:
        t = torch.linspace(0.0, math.pi, f_len, device=wave_copy.device, dtype=wave_copy.dtype)
        fade = 0.5 * (1.0 + torch.cos(t))
        while fade.ndim < wave_copy.ndim:
            fade = fade.unsqueeze(0)
        wave_copy[..., -f_len:] = wave_copy[..., -f_len:] * fade

    pad_shape = list(waveform.shape)
    pad_shape[-1] = target - current
    zero_pad = torch.zeros(pad_shape, dtype=waveform.dtype, device=waveform.device)
    return torch.cat((wave_copy, zero_pad), dim=-1)


def audio_equal_power_crossfade(
    wave1: torch.Tensor,
    wave2: torch.Tensor,
    crossfade_samples: int = 1600,
) -> torch.Tensor:
    """Concatenates two audio waveforms using an equal-power cosine/sine crossfade.
    
    fade_out = cos(t), fade_in = sin(t), where t in [0, pi/2].
    Preserves total acoustic RMS energy across the blend without a center volume dip.
    """
    if crossfade_samples <= 0:
        return torch.cat([wave1, wave2], dim=-1)

    c = min(int(crossfade_samples), int(wave1.shape[-1]), int(wave2.shape[-1]))
    if c <= 0:
        return torch.cat([wave1, wave2], dim=-1)

    device = wave1.device
    dtype = wave1.dtype

    t = torch.linspace(0.0, math.pi / 2.0, c, device=device, dtype=dtype)
    fade_out = torch.cos(t)
    fade_in = torch.sin(t)

    while fade_out.ndim < wave1.ndim:
        fade_out = fade_out.unsqueeze(0)
        fade_in = fade_in.unsqueeze(0)

    tail1 = wave1[..., -c:] * fade_out
    head2 = wave2[..., :c] * fade_in
    blended = tail1 + head2

    return torch.cat([wave1[..., :-c], blended, wave2[..., c:]], dim=-1)


# ============================================================================
# 3. Latent Prefix Trimming Math
# ============================================================================

def pixel_frames_to_latent_steps(pixel_frames: int) -> int:
    """Converts pixel frames to MiniMax H3 video latent steps using (1, 4, 4, 4, 4)."""
    if pixel_frames <= 0:
        return 0
    k, covered = 0, 0
    while covered < pixel_frames:
        covered += FRAME_PER_TOKEN[k % 5]
        k += 1
    return max(1, k)


def trim_prefix_latent(
    latent: Dict[str, Any],
    trim_frames: int,
    fps: float = 24.0,
) -> Dict[str, Any]:
    """Trims leading context frames from an H3 joint AV latent."""
    if trim_frames <= 0 or latent is None or "samples" not in latent:
        return latent

    samples = latent["samples"]
    if hasattr(samples, "unbind"):
        parts = list(samples.unbind())
    elif isinstance(samples, (tuple, list)):
        parts = list(samples)
    else:
        return latent

    if len(parts) < 2:
        return latent

    video, audio = parts[0], parts[1]

    # Calculate video steps to trim
    video_trim_steps = pixel_frames_to_latent_steps(trim_frames)
    if video_trim_steps >= video.shape[2]:
        video_trimmed = video[:, :, -1:]
    else:
        video_trimmed = video[:, :, video_trim_steps:]

    # Calculate audio ticks to trim (40 Hz grid)
    audio_hz = 40.0
    audio_trim_ticks = int(round(float(trim_frames) * audio_hz / float(fps)))
    if audio_trim_ticks >= audio.shape[-1]:
        audio_trimmed = audio[..., -1:]
    else:
        audio_trimmed = audio[..., audio_trim_ticks:]

    out_latent = dict(latent)
    # Check if nested tensor type is available
    try:
        import comfy.nested_tensor
        out_latent["samples"] = comfy.nested_tensor.NestedTensor([video_trimmed, audio_trimmed])
    except (ImportError, AttributeError):
        out_latent["samples"] = [video_trimmed, audio_trimmed]

    # Also trim noise_mask if present
    if "noise_mask" in latent and latent["noise_mask"] is not None:
        mask = latent["noise_mask"]
        if hasattr(mask, "unbind"):
            m_parts = list(mask.unbind())
            if len(m_parts) >= 2:
                mv, ma = m_parts[0], m_parts[1]
                mv_t = mv[:, :, video_trim_steps:] if video_trim_steps < mv.shape[2] else mv[:, :, -1:]
                ma_t = ma[..., audio_trim_ticks:] if audio_trim_ticks < ma.shape[-1] else ma[..., -1:]
                try:
                    import comfy.nested_tensor
                    out_latent["noise_mask"] = comfy.nested_tensor.NestedTensor([mv_t, ma_t])
                except (ImportError, AttributeError):
                    out_latent["noise_mask"] = [mv_t, ma_t]
        elif getattr(mask, "ndim", 0) >= 3 and mask.shape[1] > video_trim_steps:
            out_latent["noise_mask"] = mask[:, video_trim_steps:]

    return out_latent


# ============================================================================
# 4. Custom Node Classes
# ============================================================================

class MiniMaxH3SeamProtector:
    """CosmicCrafter Seam Protector & Harmonizer.
    
    Seamlessly concatenates two video/audio clips with:
    1. Automatic ITU-R BT.709 luminance gain matching to prevent exposure flicker.
    2. S-curve crossfading across the overlap boundary.
    3. Equal-power cosine audio crossfading with anti-click micro-fade.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "previous_images": ("IMAGE",),
                "next_images": ("IMAGE",),
                "overlap_frames": ("INT", {
                    "default": 12, "min": 0, "max": 120, "step": 1,
                    "tooltip": "Number of overlapping transition frames to blend."
                }),
                "match_luminance": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Measure and compensate average midtone luminance differences across the seam."
                }),
                "max_gain_percent": ("FLOAT", {
                    "default": 10.0, "min": 0.0, "max": 50.0, "step": 0.5,
                    "tooltip": "Maximum exposure adjustment allowed (e.g. 10.0 = ±10% gain adjustment)."
                }),
                "audio_crossfade_ms": ("FLOAT", {
                    "default": 50.0, "min": 0.0, "max": 500.0, "step": 1.0,
                    "tooltip": "Duration of equal-power audio crossfade in milliseconds."
                }),
                "fps": ("FLOAT", {
                    "default": 24.0, "min": 1.0, "max": 120.0, "step": 0.001
                }),
            },
            "optional": {
                "previous_audio": ("AUDIO",),
                "next_audio": ("AUDIO",),
            },
        }

    RETURN_TYPES = ("IMAGE", "AUDIO")
    RETURN_NAMES = ("images", "audio")
    FUNCTION = "protect_seam"
    CATEGORY = "H3 Studio/Assembly"
    DESCRIPTION = (
        "Seamlessly joins two clips with automatic luminance gain matching across the cut "
        "and equal-power cosine audio crossfading."
    )

    def protect_seam(
        self,
        previous_images: torch.Tensor,
        next_images: torch.Tensor,
        overlap_frames: int = 12,
        match_luminance: bool = True,
        max_gain_percent: float = 10.0,
        audio_crossfade_ms: float = 50.0,
        fps: float = 24.0,
        previous_audio: Optional[Dict[str, Any]] = None,
        next_audio: Optional[Dict[str, Any]] = None,
    ):
        if getattr(previous_images, "ndim", 0) != 4 or getattr(next_images, "ndim", 0) != 4:
            raise ValueError("MiniMaxH3SeamProtector requires 4D [B, H, W, C] image tensors")

        prev_frames = int(previous_images.shape[0])
        next_frames = int(next_images.shape[0])
        ov = min(int(overlap_frames), prev_frames, next_frames)

        if ov > 0:
            tail_head = previous_images[:-ov]
            tail_overlap = previous_images[-ov:]
            blended_overlap, remainder_next = blend_seam_images(
                previous_images,
                next_images,
                overlap_frames=ov,
                match_luminance=match_luminance,
                max_gain_percent=max_gain_percent,
            )
            out_images = torch.cat([tail_head, blended_overlap, remainder_next], dim=0)
        else:
            # Hard cut, but still apply luminance gain fade to the start of next_images if requested
            if match_luminance and prev_frames > 0 and next_frames > 0:
                gain = estimate_luminance_gain(previous_images[-1:], next_images[:1], max_gain_percent)
                if abs(gain - 1.0) > 1e-4:
                    next_images = apply_luminance_gain_fade(next_images, gain, fade_frames=12)
            out_images = torch.cat([previous_images, next_images], dim=0)

        # Audio assembly
        out_audio = None
        if previous_audio is not None and next_audio is not None:
            sr = int(previous_audio.get("sample_rate", 44100))
            w1 = previous_audio["waveform"]
            w2 = next_audio["waveform"]

            # Resample w2 if sample rates differ
            sr2 = int(next_audio.get("sample_rate", sr))
            if sr2 != sr:
                try:
                    import torchaudio.transforms as T
                    resampler = T.Resample(sr2, sr)
                    w2 = resampler(w2)
                except Exception:
                    pass

            cf_samples = int(round(float(audio_crossfade_ms) * float(sr) / 1000.0))
            blended_wave = audio_equal_power_crossfade(w1, w2, crossfade_samples=cf_samples)
            out_audio = {"waveform": blended_wave, "sample_rate": sr}
        elif previous_audio is not None:
            out_audio = previous_audio
        elif next_audio is not None:
            out_audio = next_audio

        return (out_images, out_audio)


class MiniMaxH3TrimPrefixLatent:
    """CosmicCrafter Trim Prefix Latent & Media.
    
    Removes leading overlap context frames from generated latents and/or decoded
    images and audio streams according to H3's exact temporal frame progression.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "trim_frames": ("INT", {
                    "default": 39, "min": 0, "max": 243, "step": 1,
                    "tooltip": "Number of prefix frames to trim (standard H3 seam is 39 frames)."
                }),
                "fps": ("FLOAT", {"default": 24.0, "min": 1.0, "max": 120.0, "step": 0.001}),
            },
            "optional": {
                "latent": ("LATENT",),
                "images": ("IMAGE",),
                "audio": ("AUDIO",),
            },
        }

    RETURN_TYPES = ("LATENT", "IMAGE", "AUDIO")
    RETURN_NAMES = ("trimmed_latent", "trimmed_images", "trimmed_audio")
    FUNCTION = "trim"
    CATEGORY = "H3 Studio/Conditioning"
    DESCRIPTION = (
        "Trims redundant prefix context from generated H3 latents, decoded video frames, "
        "and audio streams with exact clock synchronization."
    )

    def trim(
        self,
        trim_frames: int = 39,
        fps: float = 24.0,
        latent: Optional[Dict[str, Any]] = None,
        images: Optional[torch.Tensor] = None,
        audio: Optional[Dict[str, Any]] = None,
    ):
        tf = max(0, int(trim_frames))
        out_latent = None
        out_images = None
        out_audio = None

        if latent is not None:
            out_latent = trim_prefix_latent(latent, tf, fps=fps)

        if images is not None:
            if getattr(images, "ndim", 0) == 4 and images.shape[0] > tf:
                out_images = images[tf:].clone()
            else:
                out_images = images

        if audio is not None and "waveform" in audio:
            wave = audio["waveform"]
            sr = int(audio.get("sample_rate", 44100))
            audio_trim_samples = int(round(float(tf) / float(fps) * float(sr)))
            if wave.shape[-1] > audio_trim_samples:
                trimmed_wave = wave[..., audio_trim_samples:].clone()
            else:
                trimmed_wave = wave[..., :0].clone()
            out_audio = {"waveform": trimmed_wave, "sample_rate": sr}

        return (out_latent, out_images, out_audio)
