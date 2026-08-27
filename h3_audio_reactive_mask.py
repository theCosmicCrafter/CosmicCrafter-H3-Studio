"""Native audio-reactive masking for MiniMax H3.

This module closes the gap that forced earlier workflows to borrow
``FeatureToMask`` / ``MaskComposite`` / ``SetLatentNoiseMask`` from other packs:

* :class:`MiniMaxH3AudioCurveToMask` turns a per-frame audio curve (from
  ``MiniMaxH3AudioAnalyze``) into an animated ``MASK`` sequence.
* :class:`MiniMaxH3MaskComposite` combines that pulse with a subject mask (SAM,
  matting, anything producing a ``MASK``) with the broadcasting rules a
  1-frame subject mask against a T-frame audio mask actually needs.
* :class:`MiniMaxH3LatentNoiseMask` writes the result onto an H3 AV latent as a
  correctly-shaped nested noise mask.

Why the third node exists
-------------------------
Stock ``SetLatentNoiseMask`` stores a bare ``[N,1,H,W]`` tensor.  For H3 the
sampler then has to reconcile that against a *nested* latent whose streams are
video ``[B,24,T,H/16,W/16]`` and audio ``[B,32,2,T40]``.  It does so by
**trilinear interpolation** down to ``T`` and by substituting an all-ones mask
for the audio stream.

Interpolation is point-sampling: H3 compresses ~3.4 source frames into one
latent frame, so a one-frame beat spike lands between samples and is averaged
into nothing.  The percussive detail that makes a mask read as "audio-reactive"
is exactly what gets destroyed.

So this module **aggregates instead of interpolating** - each latent frame takes
the max (or mean) over every source frame that VAE-encodes into it, and the
masks are emitted at the latent's exact shape so the sampler's own
``reshape_mask`` becomes a no-op.  A single-frame transient survives at full
amplitude.
"""

import logging
import math

import torch

_LOG = logging.getLogger("h3_motion_context.audio_reactive_mask")

FPS = 24.0
AUDIO_LATENT_FPS = 40.0

#: H3 encodes video at 1/16 spatially; each 17 source frames become 5 latent frames.
FRAME_GROUP = 17
LATENT_GROUP = 5

#: Source frames carried by each video latent step, cycling every 5 steps.
#: The VAE is causal, so a group's first token holds a single frame and the
#: next four hold four apiece - 1+4+4+4+4 = 17 frames per 5 latent steps.
FRAME_PER_TOKEN = (1, 4, 4, 4, 4)

#: H3's DiT patchifies the video latent at ``(1, 2, 2)`` - see
#: ``comfy/ldm/minimax/model.py``, ``patchify_video(latent, patch_size=(1,2,2))``.
#: One token therefore spans a 2x2 block of latent pixels and is denoised as a
#: unit, so a mask that varies inside a block asks for something the model
#: cannot express.  Masks are snapped to this grid before they reach the sampler.
TOKEN_GRID = 2


# ---------------------------------------------------------------------------
# H3 temporal geometry
# ---------------------------------------------------------------------------

def align_frame_count(n):
    """Snap ``n`` up to H3's ``17k + 5`` frame grid."""
    n = int(n)
    while n % FRAME_GROUP != 5:
        n += 1
    return n


def video_latent_t(frame_count):
    """Latent frame count H3's video VAE produces for ``frame_count`` frames."""
    frame_count = int(frame_count)
    if frame_count <= 5:
        return 2
    return ((frame_count - 5) // FRAME_GROUP) * LATENT_GROUP + 2


def audio_latent_t(frame_count, fps=FPS):
    """Audio latent length (40 Hz) matching ``frame_count`` video frames."""
    return int(round(int(frame_count) / float(fps) * AUDIO_LATENT_FPS))


def pixel_frames(latent_t):
    """Source frames covered by ``latent_t`` video latent steps."""
    return sum(FRAME_PER_TOKEN[k % LATENT_GROUP] for k in range(max(0, int(latent_t))))


def latent_frame_windows(frame_count, latent_t):
    """Map each video latent index to the exact source frame range it encodes.

    Uses H3's real token geometry (:data:`FRAME_PER_TOKEN`) rather than an even
    split, so each window is exactly the set of frames that VAE-encode into that
    latent step.  Aggregating over these windows is what preserves beat
    transients that interpolation would smear away.

    Returns a list of ``(lo, hi)`` half-open source-frame ranges, one per latent
    index, clamped to ``frame_count``.
    """

    frame_count = max(1, int(frame_count))
    latent_t = max(1, int(latent_t))

    windows = []
    cursor = 0
    for k in range(latent_t):
        span = FRAME_PER_TOKEN[k % LATENT_GROUP]
        lo = min(cursor, frame_count - 1)
        hi = min(cursor + span, frame_count)
        windows.append((lo, max(hi, lo + 1)))
        cursor += span

    # A latent longer than the frame budget (or vice versa) still yields one
    # window per latent step; trailing steps re-read the final frame.
    return windows


def audio_latent_windows(audio_t, frame_count, fps=FPS):
    """Map each audio latent step to the source video frame range it covers."""
    audio_t = max(1, int(audio_t))
    frame_count = max(1, int(frame_count))
    windows = []
    for i in range(audio_t):
        lo = int(math.floor(i / AUDIO_LATENT_FPS * fps))
        hi = int(math.ceil((i + 1) / AUDIO_LATENT_FPS * fps))
        lo = min(max(0, lo), frame_count - 1)
        hi = min(max(hi, lo + 1), frame_count)
        windows.append((lo, hi))
    return windows


def aggregate_frames(values, windows, mode="max"):
    """Reduce a per-frame tensor over ``windows`` along dim 0.

    ``values`` is ``[T, ...]``; the result is ``[len(windows), ...]``.  ``max``
    keeps transients, ``mean`` smooths them, ``min`` keeps only sustained
    regions.
    """

    if values.shape[0] == 0:
        raise ValueError("h3_audio_reactive_mask: cannot aggregate an empty sequence")

    total = values.shape[0]
    out = []
    for lo, hi in windows:
        lo = min(max(0, lo), total - 1)
        hi = min(max(hi, lo + 1), total)
        chunk = values[lo:hi]
        if mode == "mean":
            out.append(chunk.mean(dim=0))
        elif mode == "min":
            out.append(chunk.amin(dim=0))
        else:
            out.append(chunk.amax(dim=0))
    return torch.stack(out, dim=0)


# ---------------------------------------------------------------------------
# Curve helpers
# ---------------------------------------------------------------------------

def curve_to_tensor(curve, n_frames):
    """Coerce a FLOAT list / tensor / scalar to a ``[n_frames]`` float tensor."""
    n_frames = max(1, int(n_frames))

    if curve is None:
        return torch.zeros(n_frames)
    if isinstance(curve, (int, float)):
        return torch.full((n_frames,), float(curve))
    if isinstance(curve, torch.Tensor):
        values = curve.detach().to(torch.float32).flatten()
    else:
        try:
            values = torch.tensor([float(v) for v in curve], dtype=torch.float32)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "h3_audio_reactive_mask: curve must be a number or a sequence of numbers"
            ) from exc

    if values.numel() == 0:
        return torch.zeros(n_frames)
    if values.numel() == n_frames:
        return values

    # Resample to the requested length so a curve analysed at a different clip
    # length still lines up with the target frame count.
    resampled = torch.nn.functional.interpolate(
        values.reshape(1, 1, -1), size=n_frames, mode="linear", align_corners=True
    )
    return resampled.reshape(-1)


def shape_curve(values, gamma=1.0, threshold=0.0, floor=0.0, ceiling=1.0, invert=False):
    """Apply gate -> gamma -> range remap to a normalised curve."""
    out = values.clamp(0.0, 1.0)

    threshold = float(threshold)
    if threshold > 0.0:
        # Gate below the threshold, then rescale the survivors back to 0..1 so
        # gating does not also dim the peaks.
        out = (out - threshold).clamp(min=0.0)
        span = max(1e-6, 1.0 - threshold)
        out = out / span

    gamma = float(gamma)
    if gamma > 0 and gamma != 1.0:
        out = out.clamp(min=0.0) ** gamma

    if invert:
        out = 1.0 - out

    floor = float(floor)
    ceiling = float(ceiling)
    return (floor + out * (ceiling - floor)).clamp(0.0, 1.0)


# ---------------------------------------------------------------------------
# Spatial mask fields
# ---------------------------------------------------------------------------

def _coord_grid(height, width, device=None):
    ys = torch.linspace(-1.0, 1.0, steps=max(1, height), device=device).reshape(-1, 1)
    xs = torch.linspace(-1.0, 1.0, steps=max(1, width), device=device).reshape(1, -1)
    return ys, xs


def render_curve_mask(values, width, height, spatial_mode="uniform",
                      softness=0.25, bars=16):
    """Render a per-frame curve into a ``[T, H, W]`` mask sequence.

    ``uniform`` fills the frame with the curve value - the right choice when a
    subject mask supplies the shape and the audio only supplies intensity.  The
    other modes give the pulse its own geometry.
    """

    height = max(1, int(height))
    width = max(1, int(width))
    frames = int(values.shape[0])
    softness = max(1e-3, float(softness))

    values = values.reshape(frames, 1, 1)

    if spatial_mode == "uniform":
        return values.expand(frames, height, width).clone()

    ys, xs = _coord_grid(height, width, device=values.device)

    if spatial_mode == "radial":
        # Disc that grows with the curve; sqrt keeps area (not radius) linear.
        radius = torch.sqrt(ys * ys + xs * xs).reshape(1, height, width)
        edge = (values.reshape(frames, 1, 1) ** 0.5) * math.sqrt(2.0)
        return ((edge - radius) / softness + 0.5).clamp(0.0, 1.0)

    if spatial_mode == "vignette":
        # Inverse of radial: the frame edges pulse, the centre stays calm.
        radius = torch.sqrt(ys * ys + xs * xs).reshape(1, height, width)
        edge = math.sqrt(2.0) * (1.0 - values.reshape(frames, 1, 1)) ** 0.5
        return ((radius - edge) / softness + 0.5).clamp(0.0, 1.0)

    if spatial_mode == "horizontal_sweep":
        # A soft vertical bar whose x position tracks the curve.
        pos = values.reshape(frames, 1, 1) * 2.0 - 1.0
        band = (1.0 - (xs.reshape(1, 1, width) - pos).abs() / softness).clamp(0.0, 1.0)
        return band.expand(frames, height, width).clone()

    if spatial_mode == "vertical_bars":
        # Spectrum-analyser columns: each bar rises from the bottom.
        bars = max(1, int(bars))
        col = torch.arange(width, device=values.device)
        bar_index = (col * bars // max(1, width)).clamp(max=bars - 1)
        # Stagger bars across the curve so they do not all move in lockstep.
        offsets = torch.linspace(0.0, 1.0, steps=bars, device=values.device)
        phase = offsets[bar_index].reshape(1, 1, width)
        level = values.reshape(frames, 1, 1) * (0.6 + 0.4 * torch.cos(phase * math.pi * 2.0))
        # Height above the bottom edge, broadcast across every column.
        depth = ((1.0 - ys) / 2.0).reshape(1, height, 1)
        return ((level - depth) / softness + 0.5).clamp(0.0, 1.0).expand(
            frames, height, width).clone()

    raise ValueError(f"h3_audio_reactive_mask: unknown spatial_mode {spatial_mode!r}")


# ---------------------------------------------------------------------------
# Mask utilities
# ---------------------------------------------------------------------------

def normalize_mask(mask):
    """Coerce any accepted MASK layout to ``[T, H, W]`` float."""
    if not isinstance(mask, torch.Tensor):
        raise ValueError("h3_audio_reactive_mask: expected a MASK tensor")

    out = mask.detach().to(torch.float32)
    if out.ndim == 2:
        return out.unsqueeze(0)
    if out.ndim == 3:
        return out
    if out.ndim == 4:
        # [B,C,H,W] or [B,1,H,W] -> collapse the channel dim
        if out.shape[1] == 1:
            return out[:, 0]
        return out.mean(dim=1)
    raise ValueError(
        f"h3_audio_reactive_mask: unsupported mask shape {tuple(mask.shape)}"
    )


def resize_mask(mask, height, width, mode="bilinear"):
    """Resize a ``[T,H,W]`` mask to ``[T,height,width]``."""
    height = max(1, int(height))
    width = max(1, int(width))
    if mask.shape[-2] == height and mask.shape[-1] == width:
        return mask
    resized = torch.nn.functional.interpolate(
        mask.unsqueeze(1), size=(height, width),
        mode=mode, align_corners=False if mode != "nearest" else None,
    )
    return resized[:, 0]


def match_frames(mask, frames):
    """Broadcast or resample a ``[T,H,W]`` mask to ``frames`` frames.

    A single-frame mask (the usual SAM subject cutout) is *repeated*, never
    interpolated - a still subject must stay identical on every frame.
    """

    frames = max(1, int(frames))
    have = int(mask.shape[0])
    if have == frames:
        return mask
    if have == 1:
        return mask.expand(frames, -1, -1).clone()
    if have == 0:
        return torch.zeros(frames, mask.shape[-2], mask.shape[-1])

    # Nearest-neighbour in time keeps hard mask edges hard.
    idx = (torch.arange(frames, dtype=torch.float32) * have / frames).long().clamp(max=have - 1)
    return mask[idx]


def snap_to_token_grid(mask, token=TOKEN_GRID, mode="max"):
    """Give every ``token`` x ``token`` block of latent pixels a single value.

    H3 denoises one 2x2 latent patch as a single token, so a mask that varies
    inside a block cannot be honoured - the token is either denoised or it is
    not.  Snapping first means the mask the sampler sees is one the model can
    actually act on, and mask edges land on token boundaries instead of
    fringing.

    ``mask`` is ``[T, h, w]`` at *latent* resolution.  Edges are replicate-padded
    so a latent dimension that is not a multiple of ``token`` keeps its border
    block rather than fading toward zero.
    """

    token = int(token)
    if token <= 1:
        return mask

    frames, height, width = mask.shape
    padded = torch.nn.functional.pad(
        mask.unsqueeze(1),
        (0, -width % token, 0, -height % token),
        mode="replicate",
    )

    if mode == "mean":
        pooled = torch.nn.functional.avg_pool2d(padded, token)
    elif mode == "min":
        pooled = -torch.nn.functional.max_pool2d(-padded, token)
    else:
        pooled = torch.nn.functional.max_pool2d(padded, token)

    expanded = pooled.repeat_interleave(token, dim=-2).repeat_interleave(token, dim=-1)
    return expanded[:, 0, :height, :width]


def feather_mask(mask, radius):
    """Box-blur a ``[T,H,W]`` mask spatially by ``radius`` pixels."""
    radius = int(radius)
    if radius <= 0:
        return mask
    kernel = radius * 2 + 1
    blurred = torch.nn.functional.avg_pool2d(
        mask.unsqueeze(1), kernel_size=kernel, stride=1, padding=radius,
        count_include_pad=False,
    )
    return blurred[:, 0].clamp(0.0, 1.0)


MASK_OPERATIONS = ("multiply", "add", "subtract", "maximum", "minimum",
                   "screen", "difference", "overwrite")


def composite_masks(mask_a, mask_b, operation="multiply"):
    """Combine two aligned ``[T,H,W]`` masks."""
    if operation == "multiply":
        return mask_a * mask_b
    if operation == "add":
        return mask_a + mask_b
    if operation == "subtract":
        return mask_a - mask_b
    if operation == "maximum":
        return torch.maximum(mask_a, mask_b)
    if operation == "minimum":
        return torch.minimum(mask_a, mask_b)
    if operation == "screen":
        return 1.0 - (1.0 - mask_a) * (1.0 - mask_b)
    if operation == "difference":
        return (mask_a - mask_b).abs()
    if operation == "overwrite":
        return mask_b
    raise ValueError(f"h3_audio_reactive_mask: unknown operation {operation!r}")


# ---------------------------------------------------------------------------
# Latent inspection
# ---------------------------------------------------------------------------

def split_av_latent(latent):
    """Return ``(video, audio)`` tensors from an H3 AV latent dict.

    ``audio`` is ``None`` for a video-only latent, so the nodes can degrade to
    plain video masking instead of failing.
    """

    if not isinstance(latent, dict) or "samples" not in latent:
        raise ValueError("h3_audio_reactive_mask: expected a LATENT dict")

    samples = latent["samples"]
    if getattr(samples, "is_nested", False):
        streams = list(samples.unbind())
        if not streams:
            raise ValueError("h3_audio_reactive_mask: AV latent contains no streams")
        video = streams[0]
        audio = streams[1] if len(streams) > 1 else None
        return video, audio

    if not isinstance(samples, torch.Tensor):
        raise ValueError(
            "h3_audio_reactive_mask: latent samples must be a tensor or NestedTensor"
        )
    return samples, None


def frames_from_video_latent(video):
    """Recover the source frame count encoded in a video latent ``[B,C,T,h,w]``."""
    if video.ndim != 5:
        raise ValueError(
            "h3_audio_reactive_mask: expected video latent [B,C,T,H,W], got "
            f"{tuple(video.shape)}"
        )
    return pixel_frames(int(video.shape[2]))


# ---------------------------------------------------------------------------
# Latent-space mask construction
# ---------------------------------------------------------------------------

def build_video_noise_mask(mask, video, temporal_aggregate="max", strength=1.0,
                           token_grid=TOKEN_GRID):
    """Build a ``[B,1,T,h,w]`` denoise mask matching ``video`` exactly.

    Emitting the latent's exact shape means the sampler's ``reshape_mask`` is an
    identity op, so the aggregation done here is what actually reaches the
    denoiser.  The mask is reduced spatially, snapped to H3's 2x2 token grid,
    then aggregated over each latent frame's source frames.
    """

    batch, _channels, latent_t, lat_h, lat_w = video.shape
    frame_count = frames_from_video_latent(video)

    mask = normalize_mask(mask)
    mask = match_frames(mask, frame_count)
    # Downscale spatially first so the temporal reduction runs on small maps.
    mask = resize_mask(mask, lat_h, lat_w)
    # Then align to the patch the DiT actually denoises as a unit.
    mask = snap_to_token_grid(mask, token_grid, mode=temporal_aggregate)

    windows = latent_frame_windows(frame_count, latent_t)
    reduced = aggregate_frames(mask, windows, mode=temporal_aggregate)

    strength = float(strength)
    if strength != 1.0:
        # strength blends toward "denoise everything"; 0 disables the mask.
        reduced = 1.0 - (1.0 - reduced) * strength

    reduced = reduced.clamp(0.0, 1.0)
    out = reduced.reshape(1, 1, latent_t, lat_h, lat_w)
    if batch > 1:
        out = out.expand(batch, 1, latent_t, lat_h, lat_w).clone()
    return out.to(dtype=torch.float32)


def build_audio_noise_mask(audio, curve=None, frame_count=None, value=1.0,
                           temporal_aggregate="max"):
    """Build a ``[B,1,2,T40]`` denoise mask for the audio stream.

    With no curve the stream is filled with ``value`` - 1.0 leaves the audio
    fully denoised (the default, and what stock ``SetLatentNoiseMask`` silently
    forces), lower values progressively preserve the incoming audio latent.
    """

    batch = int(audio.shape[0])
    pair = int(audio.shape[2])
    audio_t = int(audio.shape[3])

    if curve is None:
        column = torch.full((audio_t,), float(value))
    else:
        frame_count = int(frame_count or audio_t)
        values = curve_to_tensor(curve, frame_count)
        windows = audio_latent_windows(audio_t, frame_count)
        column = aggregate_frames(values.reshape(frame_count, 1), windows,
                                  mode=temporal_aggregate).reshape(-1)

    column = column.clamp(0.0, 1.0)
    out = column.reshape(1, 1, 1, audio_t).expand(1, 1, pair, audio_t).clone()
    if batch > 1:
        out = out.expand(batch, 1, pair, audio_t).clone()
    return out.to(dtype=torch.float32)


def attach_noise_mask(latent, video_mask, audio_mask=None):
    """Return a copy of ``latent`` carrying a correctly-nested noise mask.

    When the latent has an audio stream the sampler expects a *nested* mask; a
    bare tensor would make it invent an all-ones audio mask instead of using
    ``audio_mask``.
    """

    out = latent.copy()
    if audio_mask is None:
        out["noise_mask"] = video_mask
        return out

    try:
        import comfy.nested_tensor
    except ImportError:
        # Without ComfyUI we can still hand back the video mask; the audio
        # stream then falls back to the sampler's all-ones default.
        _LOG.debug("comfy.nested_tensor unavailable; attaching video mask only")
        out["noise_mask"] = video_mask
        return out

    out["noise_mask"] = comfy.nested_tensor.NestedTensor((video_mask, audio_mask))
    return out


# ---------------------------------------------------------------------------
# Source content
# ---------------------------------------------------------------------------

def fit_frames(image, frame_count):
    """Turn an IMAGE batch into exactly ``frame_count`` frames.

    A single still is repeated; a longer or shorter clip is sampled by nearest
    index so hard cuts stay hard.
    """

    if not isinstance(image, torch.Tensor) or image.ndim != 4:
        raise ValueError(
            "h3_audio_reactive_mask: expected an IMAGE batch [B,H,W,C], got "
            f"{tuple(getattr(image, 'shape', ()))}"
        )

    frame_count = max(1, int(frame_count))
    have = int(image.shape[0])
    if have == frame_count:
        return image
    if have == 1:
        # A broadcast view, deliberately not cloned: at video lengths that copy
        # is hundreds of MB of float32 that nothing needs, because
        # encode_video_frames reads its source one chunk at a time.  Callers
        # must treat the result as read-only.
        return image.expand(frame_count, -1, -1, -1)

    idx = (torch.arange(frame_count, dtype=torch.float32) * have / frame_count)
    idx = idx.long().clamp(max=have - 1)
    return image[idx]


def fit_to_canvas(image, width, height, crop="center"):
    """Resize an IMAGE batch ``[B,H,W,C]`` to ``height`` x ``width``.

    Uses ComfyUI's ``common_upscale`` when available so the result matches every
    other encode path in the pack; falls back to a torch implementation (with
    the same cover-crop semantics) when the pack is imported standalone.
    """

    width, height = max(1, int(width)), max(1, int(height))

    # Fast path: re-encoding a decoded pass hands us frames already at the
    # canvas size, and a full-clip movedim/interpolate round trip costs several
    # hundred MB per copy at video lengths.  Skip it when there is nothing to do.
    if (image.shape[-3] == height and image.shape[-2] == width
            and image.shape[-1] == 3):
        return image

    samples = image[..., :3].movedim(-1, 1)  # [B,C,H,W]

    try:
        import comfy.utils
    except ImportError:
        src_h, src_w = samples.shape[-2:]
        if crop == "center":
            # Cover the canvas preserving aspect, then trim the overflow.
            scale = max(width / src_w, height / src_h)
            mid_w, mid_h = max(width, round(src_w * scale)), max(height, round(src_h * scale))
            samples = torch.nn.functional.interpolate(
                samples, size=(mid_h, mid_w), mode="bilinear", align_corners=False)
            top, left = (mid_h - height) // 2, (mid_w - width) // 2
            samples = samples[..., top:top + height, left:left + width]
        else:
            samples = torch.nn.functional.interpolate(
                samples, size=(height, width), mode="bilinear", align_corners=False)
    else:
        samples = comfy.utils.common_upscale(samples, width, height, "lanczos", crop)

    return samples.movedim(1, -1)


def replace_video_stream(latent, video):
    """Return a copy of ``latent`` whose video stream is ``video``."""
    out = latent.copy()
    samples = latent["samples"]

    if getattr(samples, "is_nested", False):
        streams = list(samples.unbind())
        streams[0] = video
        out["samples"] = type(samples)(streams)
    else:
        out["samples"] = video
    return out


def _has_stock_process_input(vae):
    """True when ``vae.process_input`` is ComfyUI's stock ``x * 2 - 1`` map."""

    proc = getattr(vae, "process_input", None)
    if proc is None:
        return False
    try:
        probe = proc(torch.tensor([0.0, 0.5, 1.0]))
    except Exception:
        return False
    return (isinstance(probe, torch.Tensor) and tuple(probe.shape) == (3,)
            and torch.allclose(probe.to(torch.float32),
                               torch.tensor([-1.0, 0.0, 1.0]), atol=1e-4))


def encode_video_frames(vae, pixels, chunk=17):
    """VAE-encode ``pixels`` ``[B,H,W,C]`` without a whole-clip temporary.

    ComfyUI's ``VAE.encode`` normalizes the entire clip in a single expression
    (``comfy/sd.py``: ``self.process_input(pixel_samples[...]).to(vae_dtype)``).
    For a video VAE the tensor has already been permuted to ``[1,C,T,H,W]``, so
    ``shape[0]`` is 1, the batch loop runs exactly once, and ``x * 2 - 1``
    materializes two more float32 copies of the *whole* video - before the H3
    VAE, which streams 17-frame clips to the GPU itself, has seen a byte.  At
    243x384x672 that is ~2.2 GB of transient host memory in one step, and it
    faulted the process on this machine.

    Do the same arithmetic a chunk at a time into one ``vae_dtype`` buffer and
    lend the VAE an identity ``process_input``, so the numbers reaching the
    model are unchanged while peak memory drops to a single buffer.  Tiling is
    not an alternative here: the H3 VAE sets ``handles_tiling``, whose path
    calls ``process_input`` on the full tensor too.
    """

    if not isinstance(pixels, torch.Tensor) or pixels.ndim != 4:
        return vae.encode(pixels)
    if not _has_stock_process_input(vae):
        return vae.encode(pixels)

    dtype = getattr(vae, "vae_dtype", None)
    if not isinstance(dtype, torch.dtype):
        dtype = pixels.dtype

    frames = int(pixels.shape[0])
    try:
        buffer = torch.empty((frames,) + tuple(pixels.shape[1:]),
                             dtype=dtype, device="cpu")
    except (RuntimeError, MemoryError):
        return vae.encode(pixels)

    chunk = max(1, int(chunk))
    for start in range(0, frames, chunk):
        stop = min(start + chunk, frames)
        # torch.mul allocates, so the source is never written to - important
        # because fit_frames hands us a read-only broadcast view for a still.
        window = torch.mul(pixels[start:stop].to(torch.float32), 2.0)
        window.sub_(1.0)
        buffer[start:stop].copy_(window)
        del window

    original = vae.process_input
    vae.process_input = lambda image: image
    try:
        return vae.encode(buffer)
    finally:
        vae.process_input = original


class MiniMaxH3SourceToLatent:
    """VAE-encode source frames into an H3 AV latent's video stream.

    A denoise mask can only *preserve* content the latent already holds.
    ``MiniMaxH3ImageToVideo`` and friends hand back an **empty** AV latent - the
    still they take is attached as keyframe conditioning, not as latent content
    - so masking a subject on that latent preserves zeros, and the locked region
    decodes to flat grey mush instead of the subject.

    Insert this between the latent's creation and the noise mask so the locked
    region contains the real subject.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "samples": ("LATENT", {"tooltip": "H3 AV latent whose video stream should be filled."}),
                "vae": ("VAE", {"tooltip": "MiniMax H3 video VAE."}),
                "image": ("IMAGE", {"tooltip": "Source still (repeated) or clip (resampled) to encode."}),
                "crop": (["disabled", "center"], {
                    "default": "center",
                    "tooltip": "How the source is fitted to the latent canvas. center preserves aspect ratio.",
                }),
            },
        }

    RETURN_TYPES = ("LATENT",)
    RETURN_NAMES = ("latent",)
    FUNCTION = "apply"
    CATEGORY = "conditioning/minimax"
    DESCRIPTION = (
        "Fill an H3 AV latent's video stream with encoded source frames so a "
        "noise mask has real content to preserve. Without this, masking an "
        "empty latent locks in blank latent space, not the subject."
    )

    def apply(self, samples, vae, image, crop="center"):
        video, _audio = split_av_latent(samples)
        batch, _channels, latent_t, lat_h, lat_w = video.shape
        frame_count = frames_from_video_latent(video)
        width, height = lat_w * 16, lat_h * 16

        frames = fit_frames(image, frame_count)
        pixels = fit_to_canvas(frames, width, height, crop)
        # A full clip is hundreds of MB per copy; drop our references before the
        # VAE allocates its own working set.
        if frames is not image and frames is not pixels:
            del frames

        encoded = encode_video_frames(vae, pixels)
        del pixels
        if getattr(encoded, "ndim", 0) != 5:
            raise ValueError(
                "h3_audio_reactive_mask: video VAE returned "
                f"{tuple(getattr(encoded, 'shape', ()))}; expected [B,C,T,H,W]"
            )
        if int(encoded.shape[2]) != latent_t:
            raise RuntimeError(
                f"h3_audio_reactive_mask: {frame_count} frames encoded to "
                f"{int(encoded.shape[2])} latent steps but the target latent has "
                f"{latent_t}; the clip length is off H3's 17k+5 grid"
            )
        if encoded.shape[-2:] != video.shape[-2:]:
            raise RuntimeError(
                "h3_audio_reactive_mask: encoded source is "
                f"{tuple(encoded.shape[-2:])} but the target latent is "
                f"{tuple(video.shape[-2:])}"
            )

        if int(encoded.shape[0]) != batch:
            encoded = encoded.expand(batch, -1, -1, -1, -1).clone()

        return (replace_video_stream(samples, encoded.to(video.dtype)),)


class MiniMaxH3MaskEmitter:
    """Emit a MASK batch of an explicit length, optionally audio-driven.

    Particle sims and other temporal mask nodes take their frame count from
    whatever MASK they are handed - ``num_frames = masks.shape[0]``.  Wire one
    to a ``LoadImage`` and the whole simulation collapses to a single frame,
    silently, and any audio modulation feeding it is computed and discarded.

    This is the seed for those chains: it emits ``frames`` frames at a known
    size.  ``latent`` derives the count from an H3 AV latent instead, so the
    emitted batch cannot drift out of sync with the clip it is driving; a
    ``curve`` makes the emitted shape breathe with the audio.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "frames": ("INT", {
                    "default": 124, "min": 1, "max": 99999,
                    "tooltip": "How many frames to emit. Ignored when a latent is connected.",
                }),
                "width": ("INT", {"default": 1344, "min": 8, "max": 8192, "step": 8}),
                "height": ("INT", {"default": 768, "min": 8, "max": 8192, "step": 8}),
                "shape": (["solid", "radial", "ring", "vignette", "vertical_bars",
                           "horizontal_sweep"], {
                    "default": "solid",
                    "tooltip": "solid fills the frame (the usual seed for a particle sim); the rest give the emission its own geometry.",
                }),
                "coverage": ("FLOAT", {
                    "default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "Mask value with no curve connected; also the ceiling the curve scales to.",
                }),
                "softness": ("FLOAT", {
                    "default": 0.35, "min": 0.001, "max": 2.0, "step": 0.01,
                    "tooltip": "Edge softness for the shaped modes.",
                }),
                "ring_width": ("FLOAT", {
                    "default": 0.25, "min": 0.01, "max": 1.0, "step": 0.01,
                    "tooltip": "Thickness of the ring in 'ring' mode, as a fraction of the radius.",
                }),
            },
            "optional": {
                "latent": ("LATENT", {
                    "tooltip": "H3 AV latent to take the frame count and canvas from, so the batch matches the clip exactly.",
                }),
                "curve": ("FLOAT", {
                    "forceInput": True,
                    "tooltip": "Per-frame audio curve. Drives the emitted shape's size/intensity.",
                }),
            },
        }

    RETURN_TYPES = ("MASK", "INT")
    RETURN_NAMES = ("mask", "frame_count")
    FUNCTION = "emit"
    CATEGORY = "conditioning/minimax"
    DESCRIPTION = (
        "Emit a MASK batch of a set length to seed particle systems and other "
        "temporal mask nodes, which otherwise inherit their frame count from "
        "whatever mask they are given - a single still collapses the whole "
        "simulation to one frame. Connect a latent to lock the count to the "
        "clip, or a curve to make it audio-reactive."
    )

    def emit(self, frames, width, height, shape="solid", coverage=1.0,
             softness=0.35, ring_width=0.25, latent=None, curve=None):
        if latent is not None:
            video, _audio = split_av_latent(latent)
            frames = frames_from_video_latent(video)
            # Latent dims are /16; emit at the pixel canvas it decodes to.
            width, height = int(video.shape[-1]) * 16, int(video.shape[-2]) * 16

        frames = max(1, int(frames))
        coverage = float(coverage)

        if curve is None:
            values = torch.full((frames,), coverage)
        else:
            values = curve_to_tensor(curve, frames).clamp(0.0, 1.0) * coverage

        if shape == "solid":
            mask = values.reshape(frames, 1, 1).expand(
                frames, max(1, int(height)), max(1, int(width))).clone()
        elif shape == "ring":
            mask = self._ring(values, int(width), int(height), softness, ring_width)
        else:
            mask = render_curve_mask(values, int(width), int(height),
                                     spatial_mode=shape, softness=softness)

        return (mask.clamp(0.0, 1.0), frames)

    @staticmethod
    def _ring(values, width, height, softness, ring_width):
        """An expanding annulus - a shockwave leaving the centre on each hit."""
        height, width = max(1, height), max(1, width)
        ys, xs = _coord_grid(height, width, device=values.device)
        radius = torch.sqrt(ys * ys + xs * xs).reshape(1, height, width)

        frames = int(values.shape[0])
        edge = (values.reshape(frames, 1, 1) ** 0.5) * math.sqrt(2.0)
        half = max(1e-3, float(ring_width)) * math.sqrt(2.0) * 0.5
        # Distance from the ring's own radius, softened into a band.
        band = 1.0 - ((radius - edge).abs() - half).clamp(min=0.0) / max(1e-3, float(softness))
        return band.clamp(0.0, 1.0)


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

SPATIAL_MODES = ["uniform", "radial", "vignette", "vertical_bars", "horizontal_sweep"]
AGGREGATE_MODES = ["max", "mean", "min"]


class MiniMaxH3AudioCurveToMask:
    """Render an audio feature curve into an animated mask sequence."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "curve": ("FLOAT", {
                    "forceInput": True,
                    "tooltip": "Per-frame curve from H3 Audio Analyze (energy, beats, bass, ...).",
                }),
                "width": ("INT", {
                    "default": 768, "min": 8, "max": 8192, "step": 8,
                    "tooltip": "Mask width in pixels. Match your target canvas.",
                }),
                "height": ("INT", {
                    "default": 768, "min": 8, "max": 8192, "step": 8,
                    "tooltip": "Mask height in pixels. Match your target canvas.",
                }),
                "frames": ("INT", {
                    "default": 124, "min": 1, "max": 99999,
                    "tooltip": "Output frame count. Match the H3 clip length.",
                }),
                "spatial_mode": (SPATIAL_MODES, {
                    "default": "uniform",
                    "tooltip": "uniform = flat intensity (pair with a subject mask); the rest give the pulse its own shape.",
                }),
                "gamma": ("FLOAT", {
                    "default": 1.0, "min": 0.05, "max": 8.0, "step": 0.05,
                    "tooltip": "Contrast curve. >1 sharpens peaks, <1 lifts quiet passages.",
                }),
                "threshold": ("FLOAT", {
                    "default": 0.0, "min": 0.0, "max": 0.99, "step": 0.01,
                    "tooltip": "Gate: values below this are pushed to zero, survivors rescaled to full range.",
                }),
                "floor": ("FLOAT", {
                    "default": 0.0, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "Mask value at curve minimum.",
                }),
                "ceiling": ("FLOAT", {
                    "default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "Mask value at curve maximum.",
                }),
                "invert": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "Flip the curve so loud passages darken the mask.",
                }),
                "softness": ("FLOAT", {
                    "default": 0.25, "min": 0.001, "max": 2.0, "step": 0.01,
                    "tooltip": "Edge softness for the shaped spatial modes.",
                }),
                "feather": ("INT", {
                    "default": 0, "min": 0, "max": 128,
                    "tooltip": "Box-blur radius in pixels applied after rendering.",
                }),
            },
        }

    RETURN_TYPES = ("MASK", "FLOAT")
    RETURN_NAMES = ("mask", "shaped_curve")
    FUNCTION = "render"
    CATEGORY = "conditioning/minimax"
    DESCRIPTION = (
        "Turn a per-frame audio curve into an animated MASK. Replaces the "
        "external FeatureToMask dependency and keeps the shaped curve available "
        "for reuse on denoise or audio-stream masking."
    )

    def render(self, curve, width, height, frames, spatial_mode="uniform",
               gamma=1.0, threshold=0.0, floor=0.0, ceiling=1.0, invert=False,
               softness=0.25, feather=0):
        values = curve_to_tensor(curve, frames)
        values = shape_curve(values, gamma=gamma, threshold=threshold,
                             floor=floor, ceiling=ceiling, invert=invert)
        mask = render_curve_mask(values, width, height,
                                 spatial_mode=spatial_mode, softness=softness)
        mask = feather_mask(mask, feather)
        return (mask, values.tolist())


class MiniMaxH3MaskComposite:
    """Combine a subject mask with an audio-reactive mask."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mask_a": ("MASK", {"tooltip": "Base mask, e.g. the inverted SAM subject cutout."}),
                "operation": (list(MASK_OPERATIONS), {
                    "default": "multiply",
                    "tooltip": "multiply = audio pulse confined to the background region.",
                }),
                "invert_a": ("BOOLEAN", {"default": False, "tooltip": "Invert mask_a before compositing (SAM subject -> background)."}),
                "invert_b": ("BOOLEAN", {"default": False, "tooltip": "Invert mask_b before compositing."}),
                "gain": ("FLOAT", {
                    "default": 1.0, "min": 0.0, "max": 8.0, "step": 0.05,
                    "tooltip": "Multiplier applied to the composited result. Boost to make the reaction more violent.",
                }),
                "offset": ("FLOAT", {
                    "default": 0.0, "min": -1.0, "max": 1.0, "step": 0.01,
                    "tooltip": "Constant added after gain. Raise to keep a baseline hallucination between beats.",
                }),
                "feather": ("INT", {
                    "default": 0, "min": 0, "max": 128,
                    "tooltip": "Box-blur radius in pixels, applied last. Softens the subject cutout edge.",
                }),
                "invert_result": ("BOOLEAN", {"default": False, "tooltip": "Invert the final mask."}),
            },
            "optional": {
                "mask_b": ("MASK", {"tooltip": "Second mask, e.g. the audio pulse from H3 Audio Curve To Mask."}),
            },
        }

    RETURN_TYPES = ("MASK",)
    RETURN_NAMES = ("mask",)
    FUNCTION = "composite"
    CATEGORY = "conditioning/minimax"
    DESCRIPTION = (
        "Composite two MASK streams with automatic frame/resolution matching. "
        "A 1-frame subject mask is repeated across the audio mask's frames "
        "rather than interpolated, so a still subject stays locked."
    )

    def composite(self, mask_a, operation="multiply", invert_a=False, invert_b=False,
                  gain=1.0, offset=0.0, feather=0, invert_result=False, mask_b=None):
        a = normalize_mask(mask_a)
        if invert_a:
            a = 1.0 - a

        if mask_b is None:
            out = a
        else:
            b = normalize_mask(mask_b)
            if invert_b:
                b = 1.0 - b

            # Align on the longer clip and the larger canvas so neither input
            # silently loses temporal or spatial detail.
            frames = max(a.shape[0], b.shape[0])
            height = max(a.shape[-2], b.shape[-2])
            width = max(a.shape[-1], b.shape[-1])

            a = resize_mask(match_frames(a, frames), height, width)
            b = resize_mask(match_frames(b, frames), height, width)
            out = composite_masks(a, b, operation)

        out = out * float(gain) + float(offset)
        out = out.clamp(0.0, 1.0)
        out = feather_mask(out, feather)
        if invert_result:
            out = 1.0 - out
        return (out.clamp(0.0, 1.0),)


class MiniMaxH3LatentNoiseMask:
    """Apply a mask to an H3 AV latent as a correctly-shaped nested noise mask."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "samples": ("LATENT", {"tooltip": "H3 AV latent from Reference/Image to Video or Motion Context."}),
                "mask": ("MASK", {"tooltip": "Pixel-space mask. White = denoise (hallucinate), black = preserve."}),
                "strength": ("FLOAT", {
                    "default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "Blend toward full denoise. 1.0 = mask applied as-is, 0.0 = mask disabled.",
                }),
                "temporal_aggregate": (AGGREGATE_MODES, {
                    "default": "max",
                    "tooltip": "How source frames reduce into each latent frame. max preserves single-frame beat hits; mean smooths.",
                }),
                "audio_mode": (["denoise", "preserve", "follow_curve"], {
                    "default": "denoise",
                    "tooltip": "denoise = regenerate audio normally; preserve = keep the incoming audio latent; follow_curve = drive it from audio_curve.",
                }),
                "token_grid": ("INT", {
                    "default": TOKEN_GRID, "min": 1, "max": 8,
                    "tooltip": "Latent pixels per DiT token on each axis; the block is unified so the mask matches what the model can act on. 2 for H3 (patch 1x2x2). 1 disables snapping.",
                }),
            },
            "optional": {
                "audio_curve": ("FLOAT", {
                    "forceInput": True,
                    "tooltip": "Per-frame curve used when audio_mode is follow_curve.",
                }),
            },
        }

    RETURN_TYPES = ("LATENT", "MASK")
    RETURN_NAMES = ("latent", "latent_mask_preview")
    FUNCTION = "apply"
    CATEGORY = "conditioning/minimax"
    DESCRIPTION = (
        "H3-aware replacement for SetLatentNoiseMask. Builds the mask directly "
        "at the latent's exact video and audio shapes, aggregating source "
        "frames per latent frame instead of interpolating, so single-frame "
        "beat transients survive H3's ~3.4:1 temporal compression."
    )

    def apply(self, samples, mask, strength=1.0, temporal_aggregate="max",
              audio_mode="denoise", token_grid=TOKEN_GRID, audio_curve=None):
        video, audio = split_av_latent(samples)

        video_mask = build_video_noise_mask(
            mask, video, temporal_aggregate=temporal_aggregate, strength=strength,
            token_grid=token_grid,
        )

        audio_mask = None
        if audio is not None:
            frame_count = frames_from_video_latent(video)
            if audio_mode == "preserve":
                audio_mask = build_audio_noise_mask(audio, value=0.0)
            elif audio_mode == "follow_curve":
                if audio_curve is None:
                    raise ValueError(
                        "h3_audio_reactive_mask: audio_mode 'follow_curve' requires audio_curve"
                    )
                audio_mask = build_audio_noise_mask(
                    audio, curve=audio_curve, frame_count=frame_count,
                    temporal_aggregate=temporal_aggregate,
                )
            else:
                audio_mask = build_audio_noise_mask(audio, value=1.0)

        out = attach_noise_mask(samples, video_mask, audio_mask)

        # Preview the mask the sampler will actually see, as [T,h,w].
        preview = video_mask[0, 0].clone()
        return (out, preview)


NODE_CLASS_MAPPINGS = {
    "MiniMaxH3MaskEmitter": MiniMaxH3MaskEmitter,
    "MiniMaxH3SourceToLatent": MiniMaxH3SourceToLatent,
    "MiniMaxH3AudioCurveToMask": MiniMaxH3AudioCurveToMask,
    "MiniMaxH3MaskComposite": MiniMaxH3MaskComposite,
    "MiniMaxH3LatentNoiseMask": MiniMaxH3LatentNoiseMask,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MiniMaxH3MaskEmitter": "H3 Mask Emitter",
    "MiniMaxH3SourceToLatent": "H3 Source To Latent (AV)",
    "MiniMaxH3AudioCurveToMask": "H3 Audio Curve To Mask",
    "MiniMaxH3MaskComposite": "H3 Mask Composite",
    "MiniMaxH3LatentNoiseMask": "H3 Latent Noise Mask (AV)",
}
