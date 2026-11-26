import torch
import torch.nn.functional as F
import math


def _pixel_to_h3_latent_frames(pixel_frames: int) -> int:
    """Convert pixel frame count to MiniMax H3 (1,4,4,4,4) latent steps."""
    if pixel_frames <= 0:
        return 0
    clips, rem = divmod(int(pixel_frames), 17)
    if rem == 0:
        tail = 0
    elif rem == 1:
        tail = 1
    else:
        tail = 1 + (rem - 1 + 3) // 4
    return clips * 5 + tail


class CosmicH3AdaptiveNoiseRecoupling:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",
                          {"tooltip": "Model to patch; the noise is added back in a post-CFG hook."}),
                "noise_strength": ("FLOAT", {"default": 0.08, "min": 0.0, "max": 0.5, "step": 0.01,
                                   "tooltip": "How much noise goes back in each step. Past 0.15 it reads as grain."}),
                "recouple_ratio": ("FLOAT", {"default": 0.35, "min": 0.0, "max": 1.0, "step": 0.05,
                                   "tooltip": "Second multiplier on that noise, before the schedule. 0 disables the node."}),
                "decay_power": ("FLOAT", {"default": 2.0, "min": 0.5, "max": 4.0, "step": 0.1,
                                "tooltip": "Exponent on sigma in power_decay mode; linear and cosine ignore it."}),
                "highpass_cutoff": ("FLOAT", {"default": 0.1, "min": 0.01, "max": 0.5, "step": 0.01,
                                    "tooltip": "Discards noise coarser than this, keeping the grain fine rather than blotchy."}),
                "lowpass_cutoff": ("FLOAT", {"default": 0.8, "min": 0.1, "max": 1.0, "step": 0.05,
                                   "tooltip": "Discards noise finer than this; 0.8 keeps nearly everything above highpass_cutoff."}),
                "schedule_mode": (["linear", "cosine", "power_decay"],
                                  {"tooltip": "linear: the same amount at every step\ncosine: cos of sigma normalised to the model's range, 0 at the first step rising to full at the last\npower_decay: sigma^decay_power, strongest early"}),
            }
        }
    
    RETURN_TYPES = ("MODEL",)
    FUNCTION = "patch"
    CATEGORY = "H3 Studio/Video"
    DESCRIPTION = ("Adds band-passed noise back after every CFG step, restoring fine texture "
                   "that H3 loses over a long clip. Meant to be subtle.")

    @staticmethod
    def _sigma_range(model_sampling):
        """(sigma_min, sigma_max) of the model, or (0, 1) when it does not say."""
        try:
            lo = float(model_sampling.sigma_min)
            hi = float(model_sampling.sigma_max)
        except (AttributeError, TypeError, ValueError):
            return 0.0, 1.0
        if not (hi > lo):
            return 0.0, 1.0
        return lo, hi

    def patch(self, model, noise_strength, recouple_ratio, decay_power, highpass_cutoff, lowpass_cutoff, schedule_mode):
        m = model.clone()
        # cosine needs sigma in [0, 1]; read the model's own range (flow models say 1.0,
        # EPS models say ~14.6) instead of assuming one
        sigma_lo, sigma_hi = self._sigma_range(getattr(getattr(model, "model", None), "model_sampling", None))
        mask_cache = {}

        def _recouple_5d(video_den: torch.Tensor, video_lat: torch.Tensor, sigma: torch.Tensor) -> torch.Tensor:
            _, _, _, h, w = video_lat.shape
            noise = torch.randn_like(video_lat)
            fft_noise = torch.fft.fft2(noise, dim=(-2, -1))
            fft_shift = torch.fft.fftshift(fft_noise, dim=(-2, -1))

            cache_key = (h, w, float(highpass_cutoff), float(lowpass_cutoff), video_lat.device)
            mask = mask_cache.get(cache_key)
            if mask is None:
                fy = torch.linspace(-0.5, 0.5, h, device=video_lat.device).unsqueeze(1)
                fx = torch.linspace(-0.5, 0.5, w, device=video_lat.device).unsqueeze(0)
                radius = torch.sqrt(fx**2 + fy**2)
                mask = ((radius >= highpass_cutoff) & (radius <= lowpass_cutoff)).float().view(1, 1, 1, h, w)
                mask_cache[cache_key] = mask

            filtered_shift = fft_shift * mask
            filtered_noise = torch.fft.ifft2(
                torch.fft.ifftshift(filtered_shift, dim=(-2, -1)), dim=(-2, -1)
            ).real

            step_ratio = float(sigma.mean().item())
            alpha = recouple_ratio
            if schedule_mode == "power_decay":
                alpha *= step_ratio**decay_power
            elif schedule_mode == "cosine":
                # was cos(raw sigma): negative whenever sigma > 1, so the hook subtracted noise
                sigma_norm = (step_ratio - sigma_lo) / (sigma_hi - sigma_lo)
                sigma_norm = min(1.0, max(0.0, sigma_norm))
                alpha *= math.cos(sigma_norm * math.pi / 2)

            added_noise = (noise_strength * alpha * filtered_noise).to(video_den.dtype)
            return video_den + added_noise

        def sampler_post_cfg_hook(args):
            denoised = args["denoised"]
            latent = args["input"]
            sigma = args["sigma"]

            if isinstance(latent, torch.Tensor) and not getattr(latent, "is_nested", False):
                if latent.dim() != 5:
                    return denoised
                return _recouple_5d(denoised, latent, sigma)

            # Support ComfyUI NestedTensor / [video_latent, audio_latent] used by joint H3 AV sampling
            if hasattr(latent, "unbind") and callable(latent.unbind) and hasattr(denoised, "unbind"):
                lat_parts = list(latent.unbind())
                den_parts = list(denoised.unbind())
                if lat_parts and isinstance(lat_parts[0], torch.Tensor) and lat_parts[0].dim() == 5:
                    den_parts[0] = _recouple_5d(den_parts[0], lat_parts[0], sigma)
                    try:
                        return type(denoised)(den_parts)
                    except Exception:
                        return den_parts
            elif isinstance(latent, (list, tuple)) and isinstance(denoised, (list, tuple)) and len(latent) > 0:
                if isinstance(latent[0], torch.Tensor) and latent[0].dim() == 5:
                    new_first = _recouple_5d(denoised[0], latent[0], sigma)
                    if isinstance(denoised, tuple):
                        return (new_first, *denoised[1:])
                    return [new_first, *denoised[1:]]

            return denoised

        m.set_model_sampler_post_cfg_function(sampler_post_cfg_hook)
        return (m,)

class FlowProjectionLayer(torch.nn.Module):
    def __init__(self, in_channels=2, out_channels=1536, seed=0): 
        super().__init__()
        self.conv = torch.nn.Conv2d(in_channels, out_channels, kernel_size=3, padding=1)
        self.act = torch.nn.Tanh()
        # Deterministic weight initialization so optical flow guidance is reproducible across sessions
        gen = torch.Generator()
        gen.manual_seed(int(seed))
        with torch.no_grad():
            torch.nn.init.kaiming_uniform_(self.conv.weight, a=math.sqrt(5), generator=gen)
            if self.conv.bias is not None:
                fan_in, _ = torch.nn.init._calculate_fan_in_and_fan_out(self.conv.weight)
                bound = 1 / math.sqrt(fan_in) if fan_in > 0 else 0
                self.conv.bias.uniform_(-bound, bound, generator=gen)
        self.requires_grad_(False)
        
    def forward(self, flow_latent):
        return self.act(self.conv(flow_latent))

class CosmicH3OpticalFlowMotionBucket:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",
                          {"tooltip": "H3 model to patch; flow is injected inside its double blocks."}),
                "flow_images": ("IMAGE",
                                {"tooltip": "Flow as an IMAGE batch: red is x motion, green is y. Frame count must divide the token grid (or match pixel frames)."}),
                "guidance_strength": ("FLOAT", {"default": 1.5, "min": 0.0, "max": 5.0, "step": 0.1,
                                      "tooltip": "How hard the flow pushes motion. Past about 3 it overrides the prompt."}),
                "motion_bucket_id": ("INT", {"default": 127, "min": 1, "max": 255, "step": 1,
                                     "tooltip": "Scales guidance by id/127, so 127 is neutral and 255 doubles it."}),
                "flow_downscale_method": (["bilinear", "bicubic", "area_average"],
                                          {"tooltip": "How flow is resized to the token grid; area_average for heavy downscales."}),
                "inject_layer_range": ("STRING", {"default": "6-24",
                                       "tooltip": "Inclusive double-block range like '6-24', or one index. Every block listed gets the flow."}),
            }
        }
    
    RETURN_TYPES = ("MODEL",)
    FUNCTION = "patch"
    CATEGORY = "H3 Studio/Video"
    DESCRIPTION = ("Injects an optical-flow sequence into H3's double blocks to steer where the "
                   "motion goes. The flow frame count must divide the block's token count (or match pixel frame count).")

    @staticmethod
    def _parse_layer_range(inject_layer_range):
        if isinstance(inject_layer_range, int):
            return [inject_layer_range]
        parts = str(inject_layer_range).strip().split("-", 1)
        try:
            start = int(parts[0])
            end = int(parts[1]) if len(parts) == 2 else start
        except ValueError as exc:
            raise ValueError("inject_layer_range must be an integer or inclusive range such as '6-24'") from exc
        if start < 0 or end < start:
            raise ValueError("inject_layer_range must contain non-negative ascending layer indexes")
        return list(range(start, end + 1))

    def patch(self, model, flow_images, guidance_strength, motion_bucket_id, flow_downscale_method, inject_layer_range):
        if not isinstance(flow_images, torch.Tensor) or flow_images.ndim != 4 or flow_images.shape[-1] < 2:
            raise ValueError("flow_images must be an IMAGE tensor with shape [frames, height, width, channels]")

        m = model.clone()
        flow_projection = {}

        def block_flow_hook(args, extra_options):
            original_block = extra_options.get("original_block")
            if not callable(original_block):
                raise ValueError("ComfyUI block replacement did not provide original_block")

            result = original_block(args)
            hidden_states = result.get("img") if isinstance(result, dict) else result
            if not isinstance(hidden_states, torch.Tensor) or hidden_states.ndim != 3:
                raise ValueError("H3 block must return an image sequence tensor shaped [batch, tokens, channels]")

            batch, seq_len, d_model = hidden_states.shape
            raw_frames = flow_images.shape[0]
            if raw_frames < 1:
                raise ValueError("flow frame count must divide the H3 block token count")

            target_frames = raw_frames
            if seq_len % target_frames != 0:
                # Check if flow_images was supplied at pixel frame rate while seq_len is in H3 (1,4,4,4,4) or 4k+1 latent tokens
                lat_h3 = _pixel_to_h3_latent_frames(raw_frames)
                lat_4k1 = max(1, (raw_frames - 1) // 4 + 1)
                if lat_h3 > 0 and seq_len % lat_h3 == 0:
                    target_frames = lat_h3
                elif lat_4k1 > 0 and seq_len % lat_4k1 == 0:
                    target_frames = lat_4k1
                else:
                    raise ValueError("flow frame count must divide the H3 block token count")

            spatial_seq = seq_len // target_frames
            source_height, source_width = flow_images.shape[1:3]
            aspect = source_width / max(source_height, 1)
            spatial_height = max(1, round(math.sqrt(spatial_seq / aspect)))
            spatial_width = max(1, round(spatial_height * aspect))
            if spatial_height * spatial_width != spatial_seq:
                raise ValueError("H3 token count does not form a valid flow frame grid")

            with torch.no_grad():
                projection = flow_projection.get((d_model, hidden_states.device))
                if projection is None:
                    projection = FlowProjectionLayer(2, d_model).to(hidden_states.device)
                    flow_projection[(d_model, hidden_states.device)] = projection

                flow_vecs = flow_images[..., :2].permute(0, 3, 1, 2).float().to(hidden_states.device)
                if target_frames != raw_frames:
                    # Resample temporally from pixel frames to latent frames: [1, 2, T, H, W]
                    flow_5d = flow_vecs.permute(1, 0, 2, 3).unsqueeze(0)
                    flow_5d = F.interpolate(
                        flow_5d,
                        size=(target_frames, source_height, source_width),
                        mode="trilinear",
                        align_corners=False,
                    )
                    flow_vecs = flow_5d.squeeze(0).permute(1, 0, 2, 3)

                mode = "area" if flow_downscale_method == "area_average" else flow_downscale_method
                resize_kwargs = {} if mode == "area" else {"align_corners": False}
                flow_down = F.interpolate(flow_vecs, size=(spatial_height, spatial_width), mode=mode, **resize_kwargs)
                projected = projection(flow_down).permute(0, 2, 3, 1).reshape(1, seq_len, d_model)
                bucket_scale = motion_bucket_id / 127.0
                delta = (guidance_strength * bucket_scale * projected).to(hidden_states.dtype)

            # keep the block's dtype: float32 projection + bf16 hidden states would promote to float32
            injected = hidden_states + delta

            if isinstance(result, dict):
                result = dict(result)
                result["img"] = injected
                return result
            return injected

        for layer_index in self._parse_layer_range(inject_layer_range):
            m.set_model_patch_replace(block_flow_hook, "dit", "double_block", layer_index)
        return (m,)

NODE_CLASS_MAPPINGS = {
    "CosmicH3AdaptiveNoiseRecoupling": CosmicH3AdaptiveNoiseRecoupling,
    "CosmicH3OpticalFlowMotionBucket": CosmicH3OpticalFlowMotionBucket,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "CosmicH3AdaptiveNoiseRecoupling": "Cosmic H3 Adaptive Noise Recoupling",
    "CosmicH3OpticalFlowMotionBucket": "Cosmic H3 Optical Flow Injector",
}
