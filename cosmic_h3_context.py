"""MiniMax H3 Context Extension Nodes for ComfyUI.

Provides:
- CosmicH3SlidingContextWindow: Smoothly blends latents across overlapping temporal window chunks
  using native ComfyUI 0.30.0+ ModelPatcher hooks & comfy.context_windows.
- CosmicH3AutoregressiveFrameExtender: Re-encodes trailing frames of a generated batch via VAE
  as reference initialization and noise-mask prefix for subsequent batches.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple, Union

import torch

logger = logging.getLogger("CosmicNodes.H3Context")

# Attempt native ComfyUI context windows import
try:
    import comfy.context_windows as context_windows
    HAS_COMFY_CONTEXT = True
except ImportError:
    context_windows = None
    HAS_COMFY_CONTEXT = False

class CosmicH3SlidingContextWindow:
    """Smoothly blends latents at seams across overlapping window chunks.

    Uses native ComfyUI 0.30.0+ ModelPatcher hooks & comfy.context_windows.IndexListContextHandler
    when available to enable infinite temporal video generation.
    """

    DESCRIPTION = ("Generates video longer than one context by sampling overlapping temporal "
                   "windows and fusing the seams. Needs ComfyUI 0.30+ for the native handler.")

    CATEGORY = "H3 Studio/Video"
    RETURN_TYPES = ("MODEL",)
    RETURN_NAMES = ("model",)
    FUNCTION = "patch"
    OUTPUT_NODE = False

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": (
                    "MODEL",
                    {"tooltip": "Model to patch; it is cloned, the input is left alone."},
                ),
                "context_size": (
                    "INT",
                    {
                        "default": 16,
                        "min": 2,
                        "max": 128,
                        "step": 1,
                        "tooltip": "Window length in latent frames; 16 covers about 61 output frames.",
                    },
                ),
                "context_overlap": (
                    "INT",
                    {
                        "default": 4,
                        "min": 1,
                        "max": 64,
                        "step": 1,
                        "tooltip": "Latent frames shared by neighbouring windows. 4 is plenty; must be below context_size.",
                    },
                ),
                "fuse_method": (
                    ["pyramid", "overlap-linear", "relative", "flat"],
                    {
                        "default": "pyramid",
                        "tooltip": "pyramid: ComfyUI's native pyramid fuse, the safe default\noverlap-linear: straight cross-fade across the overlap\nrelative, flat: ComfyUI's other native fuses",
                    },
                ),
            },
            "optional": {
                "schedule": (
                    ["standard_static", "standard_uniform", "looped_uniform", "batched"],
                    {
                        "default": "standard_static",
                        "tooltip": "standard_static: fixed window positions, the safe choice\nstandard_uniform: offsets vary per step\nlooped_uniform: wraps end to start for a loop\nbatched: ComfyUI's batched schedule",
                    },
                ),
                "freenoise": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "tooltip": "Aligns noise phase across windows so seams flicker less. Leave on.",
                    },
                ),
                "cond_retain_index": (
                    "STRING",
                    {
                        "default": "0",
                        "tooltip": "Conditioning indices every window keeps; '0' holds the first-frame image.",
                    },
                ),
            },
        }

    def patch(
        self,
        model: Any,
        context_size: int = 16,
        context_overlap: int = 4,
        fuse_method: str = "pyramid",
        schedule: str = "standard_static",
        freenoise: bool = True,
        cond_retain_index: str = "0",
    ) -> Tuple[Any]:
        """Apply sliding context window hook to ModelPatcher."""
        if context_overlap >= context_size:
            raise ValueError("context_overlap must be strictly less than context_size")
        if context_overlap < 1:
            raise ValueError("context_overlap must be at least 1")

        # Clone ModelPatcher if clone method exists
        if hasattr(model, "clone") and callable(model.clone):
            patched = model.clone()
        else:
            patched = model

        # Setup context configuration dictionary for inspection & internal patchers
        options = {
            "context_size": context_size,
            "context_overlap": context_overlap,
            "fuse_method": fuse_method,
            "schedule": schedule,
            "freenoise": freenoise,
            "cond_retain_index": cond_retain_index,
            "h3_sliding_window_active": True,
        }

        # Attach options to model_options dictionary
        if hasattr(patched, "model_options") and isinstance(patched.model_options, dict):
            patched.model_options["h3_context"] = options
        elif isinstance(patched, dict):
            patched["model_options"] = {"h3_context": options}

        # Native ComfyUI 0.30.0+ IndexListContextHandler integration
        if HAS_COMFY_CONTEXT and context_windows is not None:
            try:
                # Map schedule to native ContextSchedule
                sched_name = schedule
                if sched_name == "standard_static":
                    sched_name = context_windows.ContextSchedules.STATIC_STANDARD
                elif sched_name == "standard_uniform":
                    sched_name = context_windows.ContextSchedules.UNIFORM_STANDARD
                elif sched_name == "looped_uniform":
                    sched_name = context_windows.ContextSchedules.UNIFORM_LOOPED
                elif sched_name == "batched":
                    sched_name = context_windows.ContextSchedules.BATCHED

                sched_obj = context_windows.get_matching_context_schedule(sched_name)

                # Map fuse method to native ContextFuseMethod
                fuse_name = fuse_method
                if fuse_name == "pyramid":
                    fuse_name = context_windows.ContextFuseMethods.PYRAMID
                elif fuse_name == "overlap-linear":
                    fuse_name = context_windows.ContextFuseMethods.OVERLAP_LINEAR
                elif fuse_name == "relative":
                    fuse_name = context_windows.ContextFuseMethods.RELATIVE
                elif fuse_name == "flat":
                    fuse_name = context_windows.ContextFuseMethods.FLAT

                fuse_obj = context_windows.get_matching_fuse_method(fuse_name)

                handler = context_windows.IndexListContextHandler(
                    context_schedule=sched_obj,
                    fuse_method=fuse_obj,
                    context_length=context_size,
                    context_overlap=context_overlap,
                    dim=2,  # MiniMax H3 5D temporal dimension (B, C, T, H, W)
                    freenoise=freenoise,
                    cond_retain_index_list=cond_retain_index,
                )

                if hasattr(patched, "model_options") and isinstance(patched.model_options, dict):
                    patched.model_options["context_handler"] = handler

                if hasattr(context_windows, "create_prepare_sampling_wrapper"):
                    context_windows.create_prepare_sampling_wrapper(patched)
                if freenoise and hasattr(context_windows, "create_sampler_sample_wrapper"):
                    context_windows.create_sampler_sample_wrapper(patched)

                logger.info(
                    "[Cosmic H3] Native IndexListContextHandler registered (size=%d, overlap=%d, fuse=%s)",
                    context_size,
                    context_overlap,
                    fuse_name,
                )
            except Exception as e:
                logger.warning(
                    "[Cosmic H3] Failed to attach native IndexListContextHandler: %s", e
                )

        return (patched,)

class CosmicH3AutoregressiveFrameExtender:
    """Re-encodes trailing frames of a generated batch via VAE as reference initialization & noise-mask prefix for subsequent batches."""

    DESCRIPTION = ("Chains the next H3 clip onto the last: re-encodes its tail frames as a "
                   "frozen latent prefix and returns the noise mask that holds them still.")

    CATEGORY = "H3 Studio/Video"
    RETURN_TYPES = ("LATENT", "IMAGE")
    RETURN_NAMES = ("samples", "ref_images")
    FUNCTION = "extend"
    OUTPUT_NODE = False

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "vae": (
                    "VAE",
                    {"tooltip": "VAE used to re-encode the tail frames; use the one that decoded them."},
                ),
                "images": (
                    "IMAGE",
                    {"tooltip": "Frames of the previous clip; only the last overlap_frames are used."},
                ),
                "overlap_frames": (
                    "INT",
                    {
                        "default": 4,
                        "min": 1,
                        "max": 16,
                        "step": 1,
                        "tooltip": "How many tail frames to freeze as the prefix. 4 is enough; more repeats more of the old clip.",
                    },
                ),
                "noise_aug": (
                    "FLOAT",
                    {
                        "default": 0.0,
                        "min": 0.0,
                        "max": 1.0,
                        "step": 0.01,
                        "tooltip": "Loosens the prefix: 0 keeps the tail exact, 0.1-0.2 lets the motion drift.",
                    },
                ),
                "latent_length": (
                    "INT",
                    {
                        "default": 17,
                        "min": 5,
                        "max": 257,
                        "step": 4,
                        "tooltip": "Latent frames in the next clip. Ignored whenever total_frames is non-zero.",
                    },
                ),
            },
            "optional": {
                "total_frames": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "max": 321,
                        "step": 1,
                        "tooltip": "Next clip length in output frames (4k+1); 0 uses latent_length instead.",
                    },
                ),
            },
        }

    def extend(
        self,
        vae: Any,
        images: torch.Tensor,
        overlap_frames: int = 4,
        noise_aug: float = 0.0,
        latent_length: int = 17,
        total_frames: Optional[int] = None,
    ) -> Tuple[Dict[str, torch.Tensor], torch.Tensor]:
        """Re-encodes tail frames and constructs extended latent dictionary with noise mask."""
        if (
            images is None
            or not isinstance(images, torch.Tensor)
            or images.ndim != 4
            or images.shape[0] == 0
        ):
            raise ValueError("Input video images batch is empty")

        num_frames = images.shape[0]
        actual_overlap = min(overlap_frames, num_frames)
        if actual_overlap <= 0:
            actual_overlap = 1

        ref_images = images[-actual_overlap:]

        # VAE Encoding of tail reference frames
        if hasattr(vae, "encode") and callable(vae.encode):
            encoded = vae.encode(ref_images)
            if isinstance(encoded, dict):
                if "samples" in encoded:
                    prefix_latent = encoded["samples"]
                elif "latent" in encoded:
                    prefix_latent = encoded["latent"]
                else:
                    tensor_vals = [v for v in encoded.values() if isinstance(v, torch.Tensor)]
                    if tensor_vals:
                        prefix_latent = tensor_vals[0]
                    else:
                        t_lat = (actual_overlap - 1) // 4 + 1 if actual_overlap > 1 else 1
                        h_lat, w_lat = max(1, ref_images.shape[1] // 8), max(1, ref_images.shape[2] // 8)
                        prefix_latent = torch.zeros(
                            (1, 4, t_lat, h_lat, w_lat),
                            dtype=torch.float32,
                            device=ref_images.device,
                        )
            else:
                prefix_latent = encoded
        else:
            t_lat = (actual_overlap - 1) // 4 + 1 if actual_overlap > 1 else 1
            h_lat, w_lat = max(1, ref_images.shape[1] // 8), max(1, ref_images.shape[2] // 8)
            prefix_latent = torch.zeros(
                (1, 4, t_lat, h_lat, w_lat),
                dtype=torch.float32,
                device=ref_images.device,
            )

        if prefix_latent.ndim == 4:
            prefix_latent = prefix_latent.unsqueeze(2)  # Ensure 5D (B, C, T, H, W)

        b_lat, c_lat, t_prefix, h_lat, w_lat = prefix_latent.shape

        # Use total_frames if passed
        if total_frames is not None and total_frames > 0:
            latent_length = (total_frames - 1) // 4 + 1

        # Allocate full target latent initialized with normal noise
        gen_lat = torch.randn(
            (b_lat, c_lat, latent_length, h_lat, w_lat),
            dtype=prefix_latent.dtype,
            device=prefix_latent.device,
        )

        # Copy prefix latent into beginning, optionally adding noise augmentation
        t_copy = min(t_prefix, latent_length)
        if noise_aug > 0.0:
            noise = torch.randn_like(prefix_latent[:, :, :t_copy, :, :])
            noisy_prefix = (1.0 - noise_aug) * prefix_latent[:, :, :t_copy, :, :] + noise_aug * noise
            gen_lat[:, :, :t_copy, :, :] = noisy_prefix
        else:
            gen_lat[:, :, :t_copy, :, :] = prefix_latent[:, :, :t_copy, :, :]

        # Noise mask: 0.0 for prefix (fixed conditioning), 1.0 for newly generated frames
        noise_mask = torch.ones(
            (b_lat, 1, latent_length, h_lat, w_lat),
            dtype=prefix_latent.dtype,
            device=prefix_latent.device,
        )
        noise_mask[:, :, :t_copy, :, :] = 0.0

        samples_dict = {
            "samples": gen_lat,
            "noise_mask": noise_mask,
        }
        return (samples_dict, ref_images)

NODE_CLASS_MAPPINGS = {
    "CosmicH3SlidingContextWindow": CosmicH3SlidingContextWindow,
    "CosmicH3AutoregressiveFrameExtender": CosmicH3AutoregressiveFrameExtender,
    "CosmicH3AutoregressiveExtender": CosmicH3AutoregressiveFrameExtender,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "CosmicH3SlidingContextWindow": "Cosmic Video | H3 Sliding Context Window",
    "CosmicH3AutoregressiveFrameExtender": "Cosmic Video | H3 Autoregressive Frame Extender",
    "CosmicH3AutoregressiveExtender": "Cosmic Video | H3 Autoregressive Frame Extender",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
