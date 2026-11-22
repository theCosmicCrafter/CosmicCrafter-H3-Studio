"""Operations on MiniMax H3 audio+video latents."""

import torch

import comfy.nested_tensor

from .timing import (AUDIO_TICKS_PER_SECOND, FPS, GRID_STEP, audio_context_window, audio_tail_start,
                     frames_for_tokens, ticks_for_frames, tokens_for_frames)


def split_h3_latent(latent, node):
    samples = latent["samples"]
    if (not getattr(samples, "is_nested", False) or len(samples.tensors) != 2 or samples.tensors[0].ndim != 5
            or samples.tensors[0].shape[1] != 24 or samples.tensors[1].ndim != 4):
        raise ValueError(f"{node} expects a MiniMax H3 audio+video latent")
    return samples.tensors[0], samples.tensors[1]


def pixel_size(video):
    return video.shape[4] * 16, video.shape[3] * 16


def context_noise_strengths(count, amplitude=0.4):
    """Pixel-noise strength per carried frame: a cosine from `amplitude` down to 0 at the last frame."""
    if count <= 1:
        return torch.zeros(count)
    return amplitude / 2 * (1 + torch.cos(torch.pi * torch.arange(count) / (count - 1)))


def context_noise_delta(vae, source_video, context_frames, amplitude=0.4, seed=0):
    """E(noisy) - E(clean) of the source's last `context_frames` decoded frames, after PrefixStream's paired context
    noise: adding it to the carried latent changes it by the noise's effect alone, without the VAE's round-trip error.
    The noise is seeded, so the same source gives the same delta."""
    images = vae.decode(source_video[:1])
    clean = images.reshape(-1, *images.shape[-3:])[-context_frames:, ..., :3].float()
    noise = torch.randn(clean.shape, generator=torch.Generator().manual_seed(seed)).to(clean)
    strengths = context_noise_strengths(clean.shape[0], amplitude).to(clean).view(-1, 1, 1, 1)
    noisy = (clean + strengths * noise).clamp(0, 1)
    delta = vae.encode(noisy).float() - vae.encode(clean).float()
    expected = tokens_for_frames(context_frames)
    if delta.shape[2] != expected or tuple(delta.shape[3:]) != tuple(source_video.shape[3:]):
        raise ValueError(f"context noise needs the H3 video VAE: got {tuple(delta.shape)} for {expected} carried steps")
    return delta


def build_continuation(latent, source_video, source_audio, context_frames, carry_audio, node="H3 Continue", *, audio_context_frames=0,
                       noise_vae=None, audio_feather=0):
    """Write the source's last `context_frames` frames into the start of `latent` and freeze them.

    Returns (latent, carried_video, carried_audio, carried_ticks); carried_audio is None and
    carried_ticks is 0 when `carry_audio` is off. With `noise_vae`, the carried video gets the paired context noise.
    `audio_feather` lets the last carried audio ticks regenerate, rising by cosine to fully free; the returned
    carried_audio then holds only the frozen ticks.
    """
    video, audio = split_h3_latent(latent, node)
    if "noise_mask" in latent:
        raise ValueError(f"{node}: the incoming latent already has a noise mask; combining masks is not supported")
    if source_video.shape[3:] != video.shape[3:]:
        raise ValueError("{}: resolution changed: the previous segment is {}x{}, this latent is {}x{}".format(
            node, *pixel_size(source_video), *pixel_size(video)))
    source_frames = frames_for_tokens(source_video.shape[2])
    frames = frames_for_tokens(video.shape[2])
    if context_frames > source_frames:
        raise ValueError(f"{node}: context_frames ({context_frames}) is longer than the previous segment ({source_frames} frames)")
    if context_frames >= frames:
        raise ValueError(f"{node}: this run has {frames} frames; it must be longer than context_frames ({context_frames})")

    tokens = tokens_for_frames(context_frames)
    carried_video = source_video[:1, :, -tokens:].to(device=video.device, dtype=video.dtype)
    if noise_vae is not None:
        delta = context_noise_delta(noise_vae, source_video, context_frames)
        carried_video = (carried_video.float() + delta.to(carried_video.device)).to(video.dtype)
    video = video.clone()
    video[:, :, :tokens] = carried_video
    video_mask = torch.ones((1, 1) + tuple(video.shape[2:]), device=video.device)
    video_mask[:, :, :tokens] = 0

    audio_mask = torch.ones((1, 1) + tuple(audio.shape[2:]), device=audio.device)
    carried_audio, ticks = None, 0
    if carry_audio:
        start, target_start, ticks = audio_context_window(source_frames, source_audio.shape[-1], context_frames, audio_context_frames)
        end = target_start + ticks
        if audio.shape[-1] < end:
            raise ValueError(f"{node}: this latent has {audio.shape[-1]} audio ticks, fewer than the {end} to carry")
        carried_audio = source_audio[:1, ..., start:start + ticks].to(device=audio.device, dtype=audio.dtype)
        if carried_audio.shape[-1] != ticks:
            raise ValueError(f"{node}: the previous segment has only {source_audio.shape[-1]} audio ticks")
        audio = audio.clone()
        audio[..., target_start:end] = carried_audio
        audio_mask[..., target_start:end] = 0
        feather = min(int(audio_feather), ticks)
        if feather:
            ramp = torch.arange(1, feather + 1, device=audio_mask.device, dtype=audio_mask.dtype)
            audio_mask[..., end - feather:end] = 0.5 - 0.5 * torch.cos(torch.pi * ramp / feather)
            carried_audio = carried_audio[..., :ticks - feather]

    out = dict(latent)
    out["samples"] = comfy.nested_tensor.NestedTensor((video, audio))
    out["noise_mask"] = comfy.nested_tensor.NestedTensor((video_mask, audio_mask))
    return out, carried_video, carried_audio, ticks


def build_ending(latent, source_video, source_audio, context_frames, carry_audio, start_frames=0):
    """Freeze the next segment's opening overlap at this segment's end, keeping its start mask."""
    node = "H3 Timeline"
    video, audio = split_h3_latent(latent, node)
    if source_video.shape[3:] != video.shape[3:]:
        raise ValueError(f"{node}: the next box has a different resolution; render it at this resolution first")
    tokens = tokens_for_frames(context_frames)
    start_tokens = tokens_for_frames(start_frames) if start_frames else 0
    if source_video.shape[2] < tokens:
        raise ValueError(f"{node}: the next box is shorter than its saved overlap")
    if start_tokens + tokens >= video.shape[2]:
        raise ValueError(f"{node}: this box is too short to keep both neighbors and generate new frames; lengthen it")
    masks = latent.get("noise_mask")
    if masks is None:
        video_mask = torch.ones((1, 1) + tuple(video.shape[2:]), device=video.device)
        audio_mask = torch.ones((1, 1) + tuple(audio.shape[2:]), device=audio.device)
    else:
        video_mask, audio_mask = (mask.clone() for mask in masks.tensors)
    ending_video = source_video[:1, :, :tokens].to(device=video.device, dtype=video.dtype)
    video = video.clone()
    video[:, :, -tokens:] = ending_video
    video_mask[:, :, -tokens:] = 0
    ending_audio = None
    if carry_audio:
        ticks = ticks_for_frames(context_frames)
        start = audio_tail_start(frames_for_tokens(video.shape[2]), audio.shape[-1], context_frames)
        if source_audio.shape[-1] < ticks or audio.shape[-1] < ticks:
            raise ValueError(f"{node}: not enough audio ticks to keep the next box's opening")
        if start < ticks_for_frames(start_frames):
            raise ValueError(f"{node}: this box is too short to keep both neighbors' audio; lengthen it")
        ending_audio = source_audio[:1, ..., :ticks].to(device=audio.device, dtype=audio.dtype)
        audio = audio.clone()
        audio[..., start:start + ticks] = ending_audio
        audio_mask[..., start:start + ticks] = 0
    out = dict(latent)
    out["samples"] = comfy.nested_tensor.NestedTensor((video, audio))
    out["noise_mask"] = comfy.nested_tensor.NestedTensor((video_mask, audio_mask))
    return out, ending_video, ending_audio


def window(video, audio, start, frames, vae=None):
    """`frames` frames of a saved run from frame `start`, as a run of their own: (video latent, audio ticks).

    A run's latent restarts its temporal grid every 17 frames, so a window starting on such a boundary is an exact
    token slice. Any other start has no latent of its own: the covering chunks are decoded, the window is cut from the
    frames and encoded again with `vae`. The audio ticks are cut at the window's own position."""
    tokens = tokens_for_frames(frames)
    total = frames_for_tokens(video.shape[2])
    if start < 0 or start + frames > total:
        raise ValueError(f"H3 Timeline: frames {start}-{start + frames} are outside the saved run's {total} frames")
    ticks = ticks_for_frames(frames)
    if audio.shape[-1] < ticks:
        raise ValueError(f"H3 Timeline: the saved run has {audio.shape[-1]} audio ticks, fewer than the {ticks} needed")
    tick = max(0, min(round(start * AUDIO_TICKS_PER_SECOND / FPS), audio.shape[-1] - ticks))
    audio_window = audio[:1, ..., tick:tick + ticks]
    if start % GRID_STEP == 0:
        first = start // GRID_STEP * 5
        return video[:1, :, first:first + tokens], audio_window
    if vae is None:
        raise ValueError("H3 Timeline: a window off the 17-frame grid needs the VAE to encode it again")
    chunk = start // GRID_STEP
    spans = max(0, -(-(start + frames - chunk * GRID_STEP - 5) // GRID_STEP))
    covering = video[:1, :, chunk * 5:chunk * 5 + spans * 5 + 2]
    pixels = vae.decode(covering)
    pixels = pixels.reshape(-1, *pixels.shape[-3:])
    offset = start - chunk * GRID_STEP
    encoded = vae.encode(pixels[offset:offset + frames, ..., :3])
    if encoded.ndim == 4:
        encoded = encoded.unsqueeze(0)
    if encoded.shape[2] != tokens or encoded.shape[3:] != video.shape[3:]:
        raise ValueError(f"H3 Timeline: the VAE encoded the {frames}-frame window as {tuple(encoded.shape)}, "
                         f"not {tokens} latent frames of {tuple(video.shape[3:])}")
    return encoded[:1].to(device=video.device, dtype=video.dtype), audio_window


def drop_guides_before(conditioning, frame, end_frame=None):
    """Remove guides in frozen start/end frames; returns (conditioning, count removed)."""
    if conditioning is None:
        return None, 0
    out, removed = [], 0
    for embedding, meta in conditioning:
        keyframes = meta.get("minimax_keyframes")
        if keyframes:
            kept = [kf for kf in keyframes if kf["resolved_frame_index"] >= frame
                    and (end_frame is None or kf["resolved_frame_index"] < end_frame)]
            removed = max(removed, len(keyframes) - len(kept))
            # the model treats any keyframe list as present, so an empty one must go entirely
            meta = {k: v for k, v in meta.items() if k != "minimax_keyframes"}
            if kept:
                meta["minimax_keyframes"] = kept
        out.append([embedding, meta])
    return out, removed


def carried_difference(video, audio, carried_video, carried_audio, at_end=False, *, audio_start=None):
    """Largest absolute change of the carried rows between H3 Continue and the sampler output."""
    if carried_video is None:
        return 0.0
    tokens = carried_video.shape[2]
    part = video[:1, :, -tokens:] if at_end else video[:1, :, :tokens]
    diff = (part.float().cpu() - carried_video.float().cpu()).abs().max().item()
    if carried_audio is not None:
        ticks = carried_audio.shape[-1]
        start = audio_start
        if start is None:
            start = audio_tail_start(frames_for_tokens(video.shape[2]), audio.shape[-1], frames_for_tokens(tokens)) if at_end else 0
        diff = max(diff, (audio[:1, ..., start:start + ticks].float().cpu() - carried_audio.float().cpu()).abs().max().item())
    return diff


def join_chain(parts):
    """One H3 audio+video latent for a run of continuing segments: `parts` are (video, audio, context_frames) in
    order. Each segment after the first loses the leading latents it carried, so the result is the movie once, on
    the 5k+2 latent grid that windowed sampling needs."""
    if not parts:
        raise ValueError("a chain needs at least one segment")
    videos, audios = [], []
    for position, (video, audio, context) in enumerate(parts):
        if position and not context:
            raise ValueError(f"segment {position + 1} is a cut, not a continuation; only continuing segments join")
        if position == 0 and context:
            raise ValueError("the first segment of a chain must start fresh")
        tokens = tokens_for_frames(context) if context else 0
        ticks = ticks_for_frames(context)
        if video.shape[3:] != parts[0][0].shape[3:]:
            raise ValueError("resolution changed inside the chain")
        videos.append(video[:1, :, tokens:])
        audios.append(audio[:1, ..., ticks:])
    return comfy.nested_tensor.NestedTensor((torch.cat(videos, dim=2), torch.cat(audios, dim=-1)))
