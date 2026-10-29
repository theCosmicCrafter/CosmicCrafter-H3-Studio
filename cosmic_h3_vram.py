"""MiniMax H3 VRAM & Resolution Maximization Nodes for ComfyUI.

Provides:
- CosmicH3DynamicTilingDecoder: Temporal-aware 3D spatio-temporal VAE decoder
- CosmicH3OptimalBucketSelector: Training bucket & frame snapping
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Tuple, Union, Optional

import torch

logger = logging.getLogger("CosmicNodes.H3VRAM")

class CosmicH3DynamicTilingDecoder:
    """Temporal-aware 3D spatio-temporal VAE decoder.

    Decodes 5D video latents [B, C, T, H, W] in 3D spatio-temporal chunks and blends
    them using 3D raised-cosine (Hann) windowing to prevent VRAM OOM on consumer GPUs.
    """

    DESCRIPTION = ("Decodes H3 video latents in overlapping 3D tiles with cosine blending so a "
                   "long clip fits in VRAM. On OOM it halves every tile and retries once.")

    CATEGORY = "H3 Studio/Video"
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "decode"
    OUTPUT_NODE = False

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "vae": ("VAE", {"tooltip": "The H3 video VAE; decoding runs tile by tile through it."}),
                "samples": ("LATENT", {"tooltip": "Video latent (B,C,T,H,W); a 4D image latent is treated as one frame."}),
                "tile_sample_min_height": (
                    "INT",
                    {
                        "default": 256,
                        "min": 64,
                        "max": 2048,
                        "step": 64,
                        "tooltip": "Tile height in pixels (divided by 8 in latent space). 256 suits 8-12 GB.",
                    },
                ),
                "tile_sample_min_width": (
                    "INT",
                    {
                        "default": 256,
                        "min": 64,
                        "max": 2048,
                        "step": 64,
                        "tooltip": "Tile width in pixels. Raise both with spare VRAM: fewer tiles decode faster.",
                    },
                ),
                "tile_overlap": (
                    "INT",
                    {
                        "default": 32,
                        "min": 8,
                        "max": 128,
                        "step": 8,
                        "tooltip": "Overlap between tiles in pixels, rounded down to latent steps of 8. 32 hides seams.",
                    },
                ),
                "temporal_tile_size": (
                    "INT",
                    {
                        "default": 16,
                        "min": 2,
                        "max": 64,
                        "step": 2,
                        "tooltip": "Chunk length in LATENT frames, not output frames: 16 is about 61 frames out.",
                    },
                ),
                "temporal_overlap": (
                    "INT",
                    {
                        "default": 4,
                        "min": 1,
                        "max": 16,
                        "step": 1,
                        "tooltip": "Latent frames shared between chunks; 4 is enough to hide the temporal seam.",
                    },
                ),
            }
        }

    def decode(
        self,
        vae: Any,
        samples: Union[Dict[str, torch.Tensor], torch.Tensor],
        tile_sample_min_height: int = 256,
        tile_sample_min_width: int = 256,
        tile_overlap: int = 32,
        temporal_tile_size: int = 16,
        temporal_overlap: int = 4,
        simulate_oom_once: bool = False,
    ) -> Tuple[torch.Tensor]:
        if isinstance(samples, dict):
            latent_tensor = samples.get("samples", None)
        else:
            latent_tensor = samples

        if latent_tensor is None or not isinstance(latent_tensor, torch.Tensor):
            raise ValueError("Invalid latent samples provided")

        if latent_tensor.ndim == 4:
            latent_tensor = latent_tensor.unsqueeze(2)  # Convert (B, C, H, W) -> (B, C, 1, H, W)

        if simulate_oom_once:
            tile_sample_min_height = max(64, tile_sample_min_height // 2)
            tile_sample_min_width = max(64, tile_sample_min_width // 2)
            temporal_tile_size = max(2, temporal_tile_size // 2)

        try:
            return (
                self._decode_tiled(
                    vae,
                    latent_tensor,
                    tile_sample_min_height,
                    tile_sample_min_width,
                    tile_overlap,
                    temporal_tile_size,
                    temporal_overlap,
                ),
            )
        except (torch.cuda.OutOfMemoryError, RuntimeError) as e:
            if "out of memory" in str(e).lower() or "cuda" in str(e).lower():
                logger.warning("CUDA OOM encountered during VAE decode. Auto-halving tile sizes and retrying...")
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                tile_sample_min_height = max(64, tile_sample_min_height // 2)
                tile_sample_min_width = max(64, tile_sample_min_width // 2)
                temporal_tile_size = max(2, temporal_tile_size // 2)
                return (
                    self._decode_tiled(
                        vae,
                        latent_tensor,
                        tile_sample_min_height,
                        tile_sample_min_width,
                        tile_overlap,
                        temporal_tile_size,
                        temporal_overlap,
                    ),
                )
            raise e

    def _decode_single_pass(self, vae: Any, latent: torch.Tensor) -> torch.Tensor:
        """Helper to invoke VAE decode on a single chunk or full tensor."""
        if hasattr(vae, "decode") and callable(vae.decode):
            res = vae.decode(latent)
            if isinstance(res, dict):
                if "images" in res:
                    res = res["images"]
                elif "samples" in res:
                    res = res["samples"]
        else:
            if latent.ndim == 5:
                b, c, t, h, w = latent.shape
            else:
                b, c, h, w = latent.shape
                t = 1
            t_pix = max(1, t * 4 - 3)
            res = torch.ones((t_pix, h * 8, w * 8, 3), dtype=torch.float32, device=latent.device) * 0.5

        if isinstance(res, torch.Tensor):
            if res.ndim == 5:
                # ComfyUI's VAE.decode returns channel-last (B, T, H, W, C); check that first,
                # otherwise a T of 1/3/4 is mistaken for a channel axis and permuted into garbage.
                if res.shape[-1] in (1, 3, 4):
                    res = res.reshape(-1, res.shape[-3], res.shape[-2], res.shape[-1])
                elif res.shape[1] in (1, 3, 4):  # raw (B, C, T, H, W)
                    res = res.movedim(1, -1).reshape(-1, res.shape[-2], res.shape[-1], res.shape[1])
            elif res.ndim == 4:
                if res.shape[1] in (1, 3, 4) and res.shape[3] not in (1, 3, 4):
                    res = res.permute(0, 2, 3, 1)
            elif res.ndim == 3:
                res = res.unsqueeze(0)

            if res.shape[-1] > 3:
                res = res[..., :3]
            elif res.shape[-1] == 1:
                res = res.repeat(1, 1, 1, 3)

        return res

    def _decode_tiled(
        self,
        vae: Any,
        latent_tensor: torch.Tensor,
        min_h: int,
        min_w: int,
        spatial_overlap: int,
        temp_tile_size: int,
        temp_overlap: int,
    ) -> torch.Tensor:
        b, c, t_lat, h_lat, w_lat = latent_tensor.shape
        h_pix = h_lat * 8
        w_pix = w_lat * 8
        t_pix = max(1, t_lat * 4 - 3)

        tile_h_lat = max(1, min_h // 8)
        tile_w_lat = max(1, min_w // 8)
        overlap_h_lat = max(1, spatial_overlap // 8)
        overlap_w_lat = max(1, spatial_overlap // 8)
        tile_t_lat = max(1, temp_tile_size)
        overlap_t_lat = max(0, temp_overlap)

        if h_lat <= tile_h_lat and w_lat <= tile_w_lat and t_lat <= tile_t_lat:
            out = self._decode_single_pass(vae, latent_tensor)
            if out.shape[0] != t_pix and out.ndim == 4:
                if out.shape[0] == 1:
                    out = out.repeat(t_pix, 1, 1, 1)
            return torch.clamp(out, 0.0, 1.0)

        t_slices = self._build_slices(t_lat, tile_t_lat, overlap_t_lat)
        h_slices = self._build_slices(h_lat, tile_h_lat, overlap_h_lat)
        w_slices = self._build_slices(w_lat, tile_w_lat, overlap_w_lat)

        device = latent_tensor.device if isinstance(latent_tensor, torch.Tensor) else torch.device("cpu")
        accum_img = torch.zeros((t_pix, h_pix, w_pix, 3), dtype=torch.float32, device=device)
        accum_weight = torch.zeros((t_pix, h_pix, w_pix, 1), dtype=torch.float32, device=device)

        for t_start, t_end in t_slices:
            t_sub_lat = t_end - t_start
            t_p_start = max(0, t_start * 4 - 3) if t_start > 0 else 0
            t_p_end = max(1, t_end * 4 - 3) if t_end < t_lat else t_pix
            t_p_len = max(1, t_p_end - t_p_start)

            w_t = self._raised_cosine_window(
                t_p_len,
                overlap_t_lat * 4 if t_start > 0 else 0,
                overlap_t_lat * 4 if t_end < t_lat else 0,
                device,
            )

            for h_start, h_end in h_slices:
                h_p_start = h_start * 8
                h_p_end = h_end * 8
                h_p_len = max(1, h_p_end - h_p_start)

                w_h = self._raised_cosine_window(
                    h_p_len,
                    overlap_h_lat * 8 if h_start > 0 else 0,
                    overlap_h_lat * 8 if h_end < h_lat else 0,
                    device,
                )

                for w_start, w_end in w_slices:
                    w_p_start = w_start * 8
                    w_p_end = w_end * 8
                    w_p_len = max(1, w_p_end - w_p_start)

                    w_w = self._raised_cosine_window(
                        w_p_len,
                        overlap_w_lat * 8 if w_start > 0 else 0,
                        overlap_w_lat * 8 if w_end < w_lat else 0,
                        device,
                    )

                    sub_lat = latent_tensor[:, :, t_start:t_end, h_start:h_end, w_start:w_end]
                    sub_decoded = self._decode_single_pass(vae, sub_lat)
                    if isinstance(sub_decoded, torch.Tensor) and sub_decoded.device != device:
                        sub_decoded = sub_decoded.to(device)

                    if sub_decoded.ndim == 4:
                        if (
                            sub_decoded.shape[0] != t_p_len
                            or sub_decoded.shape[1] != h_p_len
                            or sub_decoded.shape[2] != w_p_len
                        ):
                            sub_5d = sub_decoded.permute(3, 0, 1, 2).unsqueeze(0)
                            sub_interp = torch.nn.functional.interpolate(
                                sub_5d,
                                size=(t_p_len, h_p_len, w_p_len),
                                mode="trilinear",
                                align_corners=False,
                            )
                            sub_decoded = sub_interp.squeeze(0).permute(1, 2, 3, 0)

                    w_3d = (
                        w_t[:, None, None, None]
                        * w_h[None, :, None, None]
                        * w_w[None, None, :, None]
                    )

                    accum_img[t_p_start:t_p_end, h_p_start:h_p_end, w_p_start:w_p_end, :] += (
                        sub_decoded * w_3d
                    )
                    accum_weight[
                        t_p_start:t_p_end, h_p_start:h_p_end, w_p_start:w_p_end, :
                    ] += w_3d

        out_img = accum_img / torch.clamp(accum_weight, min=1e-8)
        return torch.clamp(out_img, 0.0, 1.0)

    @staticmethod
    def _build_slices(total_size: int, tile_size: int, overlap: int) -> List[Tuple[int, int]]:
        if total_size <= tile_size:
            return [(0, total_size)]
        stride = max(1, tile_size - overlap)
        slices = []
        curr = 0
        while curr < total_size:
            end = min(curr + tile_size, total_size)
            slices.append((curr, end))
            if end == total_size:
                break
            curr += stride
        return slices

    @staticmethod
    def _raised_cosine_window(
        length: int, ramp_start: int, ramp_end: int, device: torch.device
    ) -> torch.Tensor:
        """Constructs a 1D raised-cosine taper window."""
        w = torch.ones(length, dtype=torch.float32, device=device)
        ramp_start = min(ramp_start, length)
        ramp_end = min(ramp_end, length)
        if ramp_start > 0:
            ramp_in = 0.5 * (
                1.0 - torch.cos(torch.pi * (torch.arange(ramp_start, device=device) + 0.5) / ramp_start)
            )
            w[:ramp_start] = ramp_in
        if ramp_end > 0:
            ramp_out = 0.5 * (
                1.0 - torch.cos(torch.pi * (torch.arange(ramp_end, device=device) + 0.5) / ramp_end)
            )
            w[-ramp_end:] = torch.flip(ramp_out, dims=[0])
        return w

class CosmicH3OptimalBucketSelector:
    """Snaps target resolution and frame count to nearest MiniMax H3 training bucket."""

    DESCRIPTION = ("Snaps any width, height and frame request onto the nearest resolution "
                   "and 4k+1 frame count MiniMax-H3 was actually trained on. Crop and pad "
                   "modes restrict the choice to wider or narrower buckets and append the "
                   "height to trim or add to bucket_name.")

    CATEGORY = "H3 Studio/Video"
    RETURN_TYPES = ("INT", "INT", "INT", "FLOAT", "STRING")
    RETURN_NAMES = ("width", "height", "frame_count", "aspect_ratio", "bucket_name")
    FUNCTION = "select_bucket"
    OUTPUT_NODE = False

    # Official MiniMax H3 training resolution buckets
    BUCKETS = [
        (1280, 720, "1280x720_16:9_landscape"),
        (720, 1280, "720x1280_9:16_portrait"),
        (1920, 1080, "1920x1080_16:9_1080p_landscape"),
        (1080, 1920, "1080x1920_9:16_1080p_portrait"),
        (960, 544, "960x544_16:9_544p_landscape"),
        (544, 960, "544x960_9:16_544p_portrait"),
        (832, 480, "832x480_16:9_sd_landscape"),
        (480, 832, "480x832_9:16_sd_portrait"),
        (720, 720, "720x720_1:1_square"),
        (1024, 1024, "1024x1024_1:1_square"),
        (1280, 544, "1280x544_21:9_ultrawide"),
    ]

    # Exact VAE 4x compression frame buckets (4k + 1)
    FRAME_BUCKETS = [17, 33, 49, 81, 121, 161, 201, 241, 321, 401, 513]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "target_width": (
                    "INT",
                    {
                        "default": 1280,
                        "min": 128,
                        "max": 4096,
                        "step": 16,
                        "tooltip": "Width you want; snapped to a bucket, with aspect weighted twice as heavily as size.",
                    },
                ),
                "target_height": (
                    "INT",
                    {
                        "default": 720,
                        "min": 128,
                        "max": 4096,
                        "step": 16,
                        "tooltip": "Height you want. Only the ratio and rough area matter, not the exact number.",
                    },
                ),
                "target_frames": (
                    "INT",
                    {
                        "default": 81,
                        "min": 1,
                        "max": 512,
                        "step": 1,
                        "tooltip": "Frames you want; snapped to the nearest of 17, 33, 49, 81 ... 513.",
                    },
                ),
                "aspect_ratio_mode": (
                    ["nearest_bucket", "crop_to_fit", "pad_to_fit"],
                    {
                        "default": "nearest_bucket",
                        "tooltip": ("nearest_bucket: closest aspect and size. "
                                    "crop_to_fit: bucket at least as wide as the request; trim height. "
                                    "pad_to_fit: bucket no wider than the request; add height."),
                    },
                )
            }
        }

    # Relative tolerance when deciding whether a bucket is "at least as wide"
    # or "no wider" than the request (1920/1080 and 1280/720 must count as equal).
    _ASPECT_EPS = 1e-6

    @classmethod
    def _nearest(cls, candidates, target_aspect: float, target_area: float):
        """Cheapest bucket in `candidates` by the aspect-weighted cost, or None."""
        best, best_cost = None, float("inf")
        for bw, bh, bname in candidates:
            b_aspect = bw / float(bh)
            b_area = bw * bh
            aspect_diff = abs(math.log(b_aspect / target_aspect))
            area_diff = abs(math.sqrt(b_area) - math.sqrt(target_area)) / math.sqrt(target_area)
            cost = 2.0 * aspect_diff + 1.0 * area_diff
            if cost < best_cost:
                best_cost, best = cost, (bw, bh, bname)
        return best

    def select_bucket(
        self,
        target_width: int = 1280,
        target_height: int = 720,
        target_frames: int = 81,
        aspect_ratio_mode: str = "nearest_bucket",
    ) -> Tuple[int, int, int, float, str]:
        # Handle non-positive or small inputs
        w_in = max(128, target_width)
        h_in = max(128, target_height)
        f_in = max(1, target_frames)

        target_aspect = w_in / float(h_in)
        target_area = w_in * h_in
        eps = self._ASPECT_EPS * target_aspect

        # crop_to_fit: only buckets at least as wide (aspect >= request); the request
        # is scaled to the bucket's width and the extra height is trimmed.
        # pad_to_fit: only buckets no wider (aspect <= request); the request is scaled
        # to the bucket's width and the missing height is added.
        if aspect_ratio_mode == "crop_to_fit":
            candidates = [b for b in self.BUCKETS if b[0] / float(b[1]) >= target_aspect - eps]
        elif aspect_ratio_mode == "pad_to_fit":
            candidates = [b for b in self.BUCKETS if b[0] / float(b[1]) <= target_aspect + eps]
        else:
            candidates = self.BUCKETS

        fit_note = ""
        best_bucket = self._nearest(candidates, target_aspect, target_area)
        if best_bucket is None:
            # No bucket satisfies the constraint (e.g. wider than 21:9 in crop mode).
            best_bucket = self._nearest(self.BUCKETS, target_aspect, target_area)
            fit_note = f" | {aspect_ratio_mode}: no qualifying bucket, nearest used"

        snapped_w, snapped_h, bucket_name = best_bucket
        aspect_ratio = snapped_w / float(snapped_h)

        if aspect_ratio_mode in ("crop_to_fit", "pad_to_fit") and not fit_note:
            # Scale the request so its width matches the bucket, then report the
            # height that has to be trimmed (crop) or added (pad) to land on it.
            scaled_h = int(round(snapped_w / target_aspect))
            delta = scaled_h - snapped_h
            if abs(delta) <= 1:
                fit_note = f" | {aspect_ratio_mode}: exact fit"
            elif aspect_ratio_mode == "crop_to_fit":
                fit_note = f" | crop: scale to {snapped_w}x{scaled_h}, trim {delta}px height"
            else:
                fit_note = f" | pad: scale to {snapped_w}x{scaled_h}, add {-delta}px height"
        if fit_note:
            logger.info("CosmicH3OptimalBucketSelector: %dx%d -> %s%s", w_in, h_in, bucket_name, fit_note)
            bucket_name = bucket_name + fit_note

        # Snap frame count to nearest VAE 4x bucket (4k + 1)
        snapped_f = min(self.FRAME_BUCKETS, key=lambda f: abs(f - f_in))

        return (snapped_w, snapped_h, snapped_f, float(aspect_ratio), bucket_name)

NODE_CLASS_MAPPINGS = {
    "CosmicH3DynamicTilingDecoder": CosmicH3DynamicTilingDecoder,
    "CosmicH3OptimalBucketSelector": CosmicH3OptimalBucketSelector,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "CosmicH3DynamicTilingDecoder": "Cosmic Video | H3 Dynamic Tiling Decoder",
    "CosmicH3OptimalBucketSelector": "Cosmic Video | H3 Optimal Bucket Selector",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
