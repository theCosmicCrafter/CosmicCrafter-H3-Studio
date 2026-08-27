"""Beat-reactive post effects that survive video-length clips.

WHY THIS EXISTS
---------------
These are memory-safe reimplementations of two RyanOnTheInside nodes,
``FlexImageBloom`` and ``FlexImageChromaticAberration``.  The upstream pack is
excellent and is left completely untouched - install it, use it, update it
freely.  What these nodes change is *how the frames are accumulated*.

``comfyui_ryanonyheinside/nodes/images/flex_image_base.py`` ends every effect
with::

    result = []
    for i in range(num_frames):
        result.append(self.apply_effect_internal(...))   # N separate arrays
    result_np = np.stack(result)                          # + one contiguous copy
    result_tensor = torch.from_numpy(result_np).float()

``np.stack`` cannot write into the list it is given, so at the moment it
returns, three full-size copies of the clip are alive at once: the input, the
list of per-frame arrays, and the stacked result.  On a 360-frame 768x1344 clip
that is 4.15 GiB x 3, and it fails outright::

    numpy._core._exceptions._ArrayMemoryError: Unable to allocate 4.15 GiB
    for an array with shape (360, 768, 1344, 3) and data type float32

WHAT THESE DO DIFFERENTLY
-------------------------
1. **Preallocate, then fill.**  The output tensor is allocated once and each
   frame is written into its slice, so peak memory is input + output (2 copies)
   rather than input + list + stack (3 copies).
2. **Torch instead of numpy.**  Frames never round-trip through numpy, which
   removes the per-frame ``.cpu().numpy()`` / ``torch.from_numpy`` conversions
   and lets the work stay on whatever device the clip already lives on.
3. **Separable blur.**  Bloom uses two 1-D Gaussian convolutions rather than a
   cached 2-D kernel: O(k) per axis instead of O(k^2), same result to
   floating-point tolerance.
4. **Sub-pixel, non-wrapping aberration.**  Upstream shifts channels with
   ``np.roll`` on integer offsets.  That quantises the shift to whole pixels
   (so a rising beat *steps* 1px -> 2px instead of gliding) and wraps
   out-of-frame pixels around to the opposite edge (red bleeding onto the right
   border, blue onto the left, once the feature drives the shift up).  These
   nodes sample with ``grid_sample(mode="bilinear", padding_mode="border")``
   instead: fractional shifts, clamped edges, no wrap.
5. **Additive modulation by default.**  See ``_modulate`` below - a
   multiplicative-only law cannot start from a resting baseline of zero, which
   is the normal way to author "nothing until the drop".

TEMPORAL FIDELITY IS NON-NEGOTIABLE HERE
----------------------------------------
This pack exists to hit beats frame-accurately, so nothing in these nodes may
average a feature across time.  Every modulated parameter - threshold,
intensity, blur sigma, shift, angle - is evaluated per frame.

Bloom batches its blur passes only across frames that resolve to an *identical*
sigma (see ``sigma_quantum``, default 0.0 = exact match).  Quiet passages where
the feature is flat therefore still batch and stay fast, while a one-frame
transient forms its own group and is blurred with its own sigma.  An earlier
revision of this file averaged sigma across the whole chunk; on a 24 fps render
with the default 16-frame chunk that smeared a single kick across 0.67 s,
turning a snap into a swell that led and lagged the beat.  Do not reintroduce
that: it is the same interpolation failure the H3 mask nodes exist to avoid.

KNOWN DEPARTURES FROM UPSTREAM
------------------------------
- ``color_bleeding`` (a ``FlexImageBloom`` parameter) is **not implemented
  here**.  It is deliberately omitted rather than approximated: reproducing it
  without matching upstream's exact channel-blend maths would make these nodes
  silently disagree with ``FlexImageBloom`` at the same settings, which is
  worse than not offering the control.  If you need colour bleeding, use the
  upstream node at a clip length it can afford.
- ``feature_mode`` is replaced by ``modulation`` ("add"/"multiply"), and
  ``feature_param`` offers only the parameters these workflows actually drive.

Both nodes accept the ``FEATURE`` objects the RyanOnTheInside extractors emit
(the contract is just ``feature.get_value_at_frame(i) -> float``), so they drop
into an existing beat chain without rewiring the modulators.
"""

import math

import torch


def _feature_value(feature, index, default=0.0):
    """Read one frame's value from a RyanOnTheInside FEATURE, defensively."""

    if feature is None:
        return default
    try:
        value = feature.get_value_at_frame(int(index))
    except Exception:
        return default
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    if value != value:  # NaN
        return default
    return value


def _modulate(base, feature_value, strength, low, high, mode="add"):
    """Drive ``base`` with a feature value and clamp into range.

    ``mode="add"`` is the default because it is the only one that works from a
    resting baseline.  Authoring "still until the drop" means setting the base
    parameter to 0 and letting the beat lift it; under the multiplicative law
    ``base * (1 + strength * value)`` that frame is ``0 * anything == 0`` and
    the node is inert no matter how hard the feature hits.  Under ``"add"`` the
    strength is expressed in the parameter's own units, so ``shift_amount=0``
    with ``strength=0.05`` peaks at a 5% shift on a full-scale beat.

    ``mode="multiply"`` keeps the relative-scaling behaviour for cases where a
    non-zero base should be *scaled* rather than offset.
    """

    if mode == "multiply":
        driven = base * (1.0 + strength * feature_value)
    else:
        driven = base + strength * feature_value
    return float(min(max(driven, low), high))


def _gaussian_kernel1d(sigma, radius, device, dtype):
    x = torch.arange(-radius, radius + 1, device=device, dtype=dtype)
    k = torch.exp(-(x * x) / (2.0 * sigma * sigma))
    return k / k.sum()


def _blur_separable(batch, sigma):
    """Gaussian-blur ``[B,H,W,C]`` with two 1-D passes.

    The radius is clamped to the frame so ``reflect`` padding stays legal on
    small canvases (reflect requires pad < dimension).
    """

    if sigma <= 0.0:
        return batch

    height, width = int(batch.shape[1]), int(batch.shape[2])
    radius = max(1, int(round(sigma * 3.0)))
    radius = min(radius, height - 1, width - 1)
    if radius < 1:
        return batch

    k = _gaussian_kernel1d(sigma, radius, batch.device, batch.dtype)
    channels = int(batch.shape[-1])

    x = batch.permute(0, 3, 1, 2)  # [B,C,H,W]
    kh = k.view(1, 1, 1, -1).expand(channels, 1, 1, -1)
    kv = k.view(1, 1, -1, 1).expand(channels, 1, -1, 1)
    x = torch.nn.functional.conv2d(
        torch.nn.functional.pad(x, (radius, radius, 0, 0), mode="reflect"),
        kh, groups=channels)
    x = torch.nn.functional.conv2d(
        torch.nn.functional.pad(x, (0, 0, radius, radius), mode="reflect"),
        kv, groups=channels)
    return x.permute(0, 2, 3, 1)


_GRID_CACHE = {}


def _base_grid(height, width, device, dtype):
    """Identity sampling grid ``[1,H,W,2]`` for ``align_corners=False``."""

    key = (height, width, str(device), str(dtype))
    grid = _GRID_CACHE.get(key)
    if grid is None:
        ys = (torch.arange(height, device=device, dtype=dtype) + 0.5) * (2.0 / height) - 1.0
        xs = (torch.arange(width, device=device, dtype=dtype) + 0.5) * (2.0 / width) - 1.0
        gy, gx = torch.meshgrid(ys, xs, indexing="ij")
        grid = torch.stack((gx, gy), dim=-1).unsqueeze(0)
        if len(_GRID_CACHE) > 8:
            _GRID_CACHE.clear()
        _GRID_CACHE[key] = grid
    return grid


def _shift_plane(plane, dx, dy):
    """Shift a single ``[H,W]`` channel by fractional ``(dx, dy)`` pixels.

    Bilinear sampling with edge clamping - no integer snapping, no wrap-around.
    """

    if dx == 0.0 and dy == 0.0:
        return plane

    height, width = int(plane.shape[0]), int(plane.shape[1])
    grid = _base_grid(height, width, plane.device, plane.dtype)
    # Sampling *back* by the shift moves content *forward* by it.
    offset = torch.tensor(
        (2.0 * dx / width, 2.0 * dy / height),
        device=plane.device, dtype=plane.dtype)
    sample = grid - offset

    out = torch.nn.functional.grid_sample(
        plane.view(1, 1, height, width), sample,
        mode="bilinear", padding_mode="border", align_corners=False)
    return out.view(height, width)


class MiniMaxH3BeatChromaticAberration:
    """Per-channel RGB shift driven by an audio feature.

    Memory-safe, sub-pixel, non-wrapping clone of
    ``FlexImageChromaticAberration`` - see the module docstring.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "Clip to process."}),
                "shift_amount": ("FLOAT", {
                    "default": 0.0, "min": 0.0, "max": 0.5, "step": 0.001,
                    "tooltip": (
                        "Resting shift as a fraction of frame size. Leave at 0 "
                        "and raise strength for an effect that only appears on "
                        "the beat."
                    ),
                }),
                "angle": ("FLOAT", {
                    "default": 0.0, "min": 0.0, "max": 720.0, "step": 1.0,
                    "tooltip": "Direction of the red/blue split, in degrees.",
                }),
                "strength": ("FLOAT", {
                    "default": 0.02, "min": -10.0, "max": 10.0, "step": 0.001,
                    "tooltip": (
                        "In add mode this is the parameter's own units at a "
                        "full-scale feature value: 0.02 peaks at a 2% shift."
                    ),
                }),
                "feature_param": (["shift_amount", "angle", "None"], {
                    "default": "shift_amount",
                    "tooltip": "Which parameter the feature modulates.",
                }),
                "modulation": (["add", "multiply"], {
                    "default": "add",
                    "tooltip": (
                        "add: base + strength*feature (works from a zero base). "
                        "multiply: base*(1+strength*feature) (inert at base 0)."
                    ),
                }),
            },
            "optional": {
                "opt_feature": ("FEATURE", {
                    "tooltip": "Audio/beat feature. Without it the effect is static.",
                }),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "apply"
    CATEGORY = "image/postprocessing/minimax"
    DESCRIPTION = (
        "Beat-reactive chromatic aberration with sub-pixel shifts and clamped "
        "edges. Preallocates its output instead of stacking a per-frame list, "
        "so it survives clip lengths where FlexImageChromaticAberration runs "
        "out of host memory."
    )

    def apply(self, images, shift_amount, angle, strength, feature_param,
              modulation="add", opt_feature=None):
        frames = int(images.shape[0])
        out = torch.empty_like(images)

        for i in range(frames):
            value = _feature_value(opt_feature, i)
            shift, ang = shift_amount, angle
            if feature_param == "shift_amount":
                shift = _modulate(shift_amount, value, strength, 0.0, 0.5, modulation)
            elif feature_param == "angle":
                ang = _modulate(angle, value, strength, 0.0, 720.0, modulation)

            radians = math.radians(ang)
            dx = images.shape[2] * shift * math.cos(radians)
            dy = images.shape[1] * shift * math.sin(radians)

            frame = images[i]
            out[i, ..., 0] = _shift_plane(frame[..., 0], dx, dy)
            out[i, ..., 1] = frame[..., 1]
            out[i, ..., 2] = _shift_plane(frame[..., 2], -dx, -dy)

        return (out.clamp_(0.0, 1.0),)


class MiniMaxH3BeatBloom:
    """Threshold-and-blur bloom driven by an audio feature.

    Memory-safe clone of ``FlexImageBloom`` with strictly per-frame modulation -
    see the module docstring, especially the temporal-fidelity note.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "Clip to process."}),
                "threshold": ("FLOAT", {
                    "default": 0.7, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "Luminance above which a pixel blooms.",
                }),
                "blur_amount": ("FLOAT", {
                    "default": 10.0, "min": 0.0, "max": 50.0, "step": 0.1,
                    "tooltip": "Resting blur radius of the first bloom pass.",
                }),
                "intensity": ("FLOAT", {
                    "default": 0.0, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": (
                        "Resting bloom mix. Leave at 0 and raise strength for "
                        "bloom that only blooms on the beat."
                    ),
                }),
                "num_passes": ("INT", {
                    "default": 4, "min": 1, "max": 8, "step": 1,
                    "tooltip": "Successive wider blurs, each at half the weight.",
                }),
                "falloff": ("FLOAT", {
                    "default": 1.2, "min": 0.1, "max": 3.0, "step": 0.1,
                    "tooltip": "Sigma multiplier between passes.",
                }),
                "strength": ("FLOAT", {
                    "default": 0.6, "min": -10.0, "max": 10.0, "step": 0.01,
                    "tooltip": (
                        "In add mode this is the parameter's own units at a "
                        "full-scale feature value."
                    ),
                }),
                "feature_param": (["intensity", "threshold", "blur_amount", "None"], {
                    "default": "intensity",
                    "tooltip": "Which parameter the feature modulates.",
                }),
                "modulation": (["add", "multiply"], {
                    "default": "add",
                    "tooltip": (
                        "add: base + strength*feature (works from a zero base). "
                        "multiply: base*(1+strength*feature) (inert at base 0)."
                    ),
                }),
                "chunk_frames": ("INT", {
                    "default": 16, "min": 1, "max": 256, "step": 1,
                    "tooltip": (
                        "Frames held in the blur working set at once. Bounds "
                        "transient memory only - it never averages across "
                        "frames, so it cannot blunt a transient."
                    ),
                }),
                "sigma_quantum": ("FLOAT", {
                    "default": 0.0, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": (
                        "0 = blur every distinct per-frame sigma exactly. "
                        "Above 0, frames whose sigma agrees to within this "
                        "value share one blur pass - faster, but do not raise "
                        "it if blur_amount is the beat-driven parameter."
                    ),
                }),
            },
            "optional": {
                "opt_feature": ("FEATURE", {
                    "tooltip": "Audio/beat feature. Without it the effect is static.",
                }),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "apply"
    CATEGORY = "image/postprocessing/minimax"
    DESCRIPTION = (
        "Beat-reactive bloom with strictly per-frame modulation. Preallocates "
        "its output and bounds its blur working set, so it survives clip "
        "lengths where FlexImageBloom exhausts host memory."
    )

    def apply(self, images, threshold, blur_amount, intensity, num_passes,
              falloff, strength, feature_param, modulation="add",
              chunk_frames=16, sigma_quantum=0.0, opt_feature=None):
        frames = int(images.shape[0])
        out = torch.empty_like(images)
        chunk = max(1, int(chunk_frames))
        passes = max(1, int(num_passes))

        for start in range(0, frames, chunk):
            stop = min(start + chunk, frames)
            window = images[start:stop]

            thresholds, sigmas, intensities = [], [], []
            for i in range(start, stop):
                value = _feature_value(opt_feature, i)
                thr, blur, inten = threshold, blur_amount, intensity
                if feature_param == "threshold":
                    thr = _modulate(threshold, value, strength, 0.0, 1.0, modulation)
                elif feature_param == "blur_amount":
                    blur = _modulate(blur_amount, value, strength, 0.0, 50.0, modulation)
                elif feature_param == "intensity":
                    inten = _modulate(intensity, value, strength, 0.0, 1.0, modulation)
                thresholds.append(thr)
                sigmas.append(max(1e-3, blur * 0.1))
                intensities.append(inten)

            # Bright-pass, per frame.
            luma = window.mean(dim=-1, keepdim=True)
            thr_t = torch.tensor(thresholds, device=window.device,
                                 dtype=window.dtype).view(-1, 1, 1, 1)
            bright = window * (luma >= thr_t)
            del luma

            # Blur each frame with ITS OWN sigma. Frames whose sigma matches
            # share a pass; a lone transient gets its own. Nothing is averaged.
            accum = torch.empty_like(bright)
            groups = {}
            for local, sigma in enumerate(sigmas):
                key = sigma if sigma_quantum <= 0.0 else round(sigma / sigma_quantum)
                groups.setdefault(key, []).append(local)

            weights = [1.0 / (2 ** p) for p in range(passes)]
            weight_total = sum(weights)
            for members in groups.values():
                idx = torch.tensor(members, device=bright.device, dtype=torch.long)
                subset = bright.index_select(0, idx)
                sigma = sigmas[members[0]]
                blurred = torch.zeros_like(subset)
                for p, weight in enumerate(weights):
                    blurred += _blur_separable(subset, sigma * (falloff ** p)) * weight
                blurred /= weight_total
                accum.index_copy_(0, idx, blurred)
                del subset, blurred

            inten_t = torch.tensor(intensities, device=window.device,
                                   dtype=window.dtype).view(-1, 1, 1, 1)
            torch.clamp(window + accum * inten_t, 0.0, 1.0, out=out[start:stop])
            del bright, accum

        return (out,)


NODE_CLASS_MAPPINGS = {
    "MiniMaxH3BeatChromaticAberration": MiniMaxH3BeatChromaticAberration,
    "MiniMaxH3BeatBloom": MiniMaxH3BeatBloom,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MiniMaxH3BeatChromaticAberration": "H3 Beat Chromatic Aberration",
    "MiniMaxH3BeatBloom": "H3 Beat Bloom",
}
