import os
import json
import torch
import numpy as np

try:
    import comfy.model_management as model_management
except Exception:
    model_management = None

from .config_manager import get_config_manager
from .task_detector import TASK_TYPE_OPTIONS, TaskDetector
from .prompt_builder import PromptBuilder, CINEMATIC_STYLES
from .post_processor import PostProcessor
from .utils import log_info, log_error, log_warning, create_dynamic_provider, tensor_to_base64, compute_frame_hash
from .dynamic_discovery import get_ollama_models
from .vision_orchestrator import VisionOrchestrator
from .response_parser import ResponseParser

curr_dir = os.path.dirname(os.path.realpath(__file__))
presets_path = os.path.join(curr_dir, 'vision_prompts.json')
if os.path.exists(presets_path):
    try:
        with open(presets_path, 'r', encoding='utf-8') as f:
            PRESETS = json.load(f)
    except Exception:
        PRESETS = {"image_prompts": {}, "video_prompts": {}}
else:
    PRESETS = {"image_prompts": {}, "video_prompts": {}}

IMAGE_MODES = list(PRESETS.get('image_prompts', {}).keys())
VIDEO_MODES = list(PRESETS.get('video_prompts', {}).keys())
VISION_MODES = ["Auto (Adaptive)"] + (IMAGE_MODES if IMAGE_MODES else ["Subject / Identity", "Comprehensive"]) + ["Bypass Vision"]

PROVIDERS = ["Ollama", "vLLM", "LM Studio", "OpenAI", "Anthropic Claude", "Google Gemini"]
GENERATION_MODES = ["Director (Two-Stage)", "Turbo (Single-Stage)"]
STYLES = list(CINEMATIC_STYLES.keys())

# In-memory LRU cache for visual keyframe analysis (0.00s repeat iterations)
_VISION_CACHE: dict[str, dict] = {}


class H3_Promptor:
    OUTPUT_NODE = True

    def __init__(self):
        self.prompt_builder = PromptBuilder()

    @classmethod
    def INPUT_TYPES(s):
        initial_models = get_ollama_models(filter_type="all")
        
        return {
            "required": {
                "provider": (PROVIDERS, {
                    "default": "Ollama",
                    "tooltip": "LLM provider. Live-queries local system when Ollama or LM Studio is selected."
                }),
                "model": (initial_models, {
                    "default": initial_models[0] if initial_models else "qwen2.5-vl:7b",
                    "tooltip": "Model list automatically populated from the selected provider. [Vision] models support image/video analysis."
                }),
                "task_type": (TASK_TYPE_OPTIONS, {
                    "default": "Auto",
                    "tooltip": "Forces the H3 prompt format. When set to 'Auto', dynamically detects T2VA, I2VA, FL2VA, Ref2VA based on connected images/video."
                }),
                "description": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Your main creative description or scene concept.",
                }),
                "duration": ("FLOAT", {
                    "default": 5.0, "min": 4.0, "max": 15.0, "step": 0.5,
                    "tooltip": "Valid duration for MiniMax H3 is 4-15 seconds.",
                }),
                "reference_videos": (["Auto", "1", "2", "3", "Auto (Adaptive)", ""], {
                    "default": "Auto",
                    "tooltip": "Number of reference videos to announce in MiniMax prompt tags (defaults to Auto)."
                }),
                "reference_audios": (["Auto", "1", "2", "3", "Auto (Adaptive)", ""], {
                    "default": "Auto",
                    "tooltip": "Number of reference audios to announce in MiniMax prompt tags (defaults to Auto)."
                }),
                "reference_images": (["Auto", "1", "2", "3", "4", "5", "6", "7", "8", "9", "Auto (Adaptive)", ""], {
                    "default": "Auto",
                    "tooltip": "Number of reference images to announce in MiniMax prompt tags (defaults to Auto)."
                }),
                "output_language": (["English", "Chinese", "Auto"], {
                    "default": "English",
                    "tooltip": "Language for the generated prompt (English or Simplified Chinese)."
                }),
                "temperature": ("FLOAT", {
                    "default": 0.4, "min": 0.0, "max": 1.0, "step": 0.05,
                    "tooltip": "Creative temperature for the LLM. 0.4 provides optimal compliance with MiniMax cinematic directions."
                }),
                "max_tokens": ("INT", {
                    "default": 4096, "min": 256, "max": 4096, "step": 256,
                    "tooltip": "Maximum token generation budget. 4096 matches the native MiniMax H3 Qwen2.5 text encoder budget."
                }),
                "generation_mode": (GENERATION_MODES, {
                    "default": "Director (Two-Stage)",
                    "tooltip": "Director mode performs deep two-stage blueprinting. Turbo mode produces prompts in a single fast pass."
                }),
                "cinematic_style": (STYLES, {
                    "default": "None (Neutral)",
                    "tooltip": "Injects specialized aesthetic, lighting, and camera direction rules."
                }),
                "vision_mode": (VISION_MODES, {
                    "default": "Auto (Adaptive)",
                    "tooltip": "Vision analysis focus when images or video frames are connected."
                }),
                "custom_vision_prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Optional manual direction for the vision model (e.g. 'Focus on the glowing cybernetic eye and rain effects')."
                }),
            },
            "optional": {
                "images": ("IMAGE", {
                    "tooltip": "Connect a single photo (I2VA), two frames (FL2VA), multiple photos (Ref2VA), or video sequence (auto-subsampled across timeline)."
                }),
                "vision_context": ("STRING", {
                    "multiline": True,
                    "forceInput": True,
                    "default": "",
                    "tooltip": "Optional external text vision context (from external analyzer or previous run).",
                }),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "IMAGE", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("prompt", "vision_context", "task_type", "sampled_frames", "character_memory", "global_soundscape", "non_diegetic_music")
    FUNCTION = "generate_prompt"
    CATEGORY = "CosmicCrafter/H3 Promptor"

    def generate_prompt(
        self,
        provider: str = "Ollama",
        model: str = "qwen2.5-vl:7b",
        task_type: str = "Auto",
        description: str = "",
        duration: float = 5.0,
        reference_videos: str = "Auto",
        reference_audios: str = "Auto",
        reference_images: str = "Auto",
        output_language: str = "English",
        temperature: float = 0.4,
        max_tokens: int = 4096,
        generation_mode: str = "Director (Two-Stage)",
        cinematic_style: str = "None (Neutral)",
        vision_mode: str = "Auto (Adaptive)",
        custom_vision_prompt: str = "",
        images: torch.Tensor | None = None,
        vision_context: str = "",
        **kwargs,
    ):
        try:
            # Handle aliases and None values safely
            ref_imgs = kwargs.get("reference_image", reference_images)
            ref_vids = kwargs.get("reference_video", reference_videos)
            ref_auds = kwargs.get("reference_audio", reference_audios)

            ref_imgs_str = "Auto" if (ref_imgs is None or str(ref_imgs).strip() in ["", "Auto", "Auto (Adaptive)"]) else str(ref_imgs)
            ref_vids_str = "Auto" if (ref_vids is None or str(ref_vids).strip() in ["", "Auto", "Auto (Adaptive)"]) else str(ref_vids)
            ref_auds_str = "Auto" if (ref_auds is None or str(ref_auds).strip() in ["", "Auto", "Auto (Adaptive)"]) else str(ref_auds)

            output_language = "English" if (not output_language or str(output_language).strip() in ["Auto", ""]) else str(output_language)
            try:
                temperature = 0.4 if (temperature is None or str(temperature).strip() in ["", "Auto", "English"]) else float(temperature)
            except (ValueError, TypeError):
                temperature = 0.4

            try:
                max_tokens = 4096 if (max_tokens is None or str(max_tokens).strip() in ["", "Auto", "English"]) else int(max_tokens)
            except (ValueError, TypeError):
                max_tokens = 4096

            try:
                duration = 5.0 if (duration is None or str(duration).strip() in ["", "Auto"]) else float(duration)
            except (ValueError, TypeError):
                duration = 5.0

            task_type = "Auto" if not task_type else str(task_type)
            vision_mode = "Auto (Adaptive)" if not vision_mode else str(vision_mode)
            custom_vision_prompt = "" if custom_vision_prompt is None else str(custom_vision_prompt)

            ui_ref_images = 0 if ref_imgs_str in ["Auto", "Auto (Adaptive)"] else int(ref_imgs_str)
            ui_ref_videos = 0 if ref_vids_str in ["Auto", "Auto (Adaptive)"] else int(ref_vids_str)
            ui_ref_audios = 0 if ref_auds_str in ["Auto", "Auto (Adaptive)"] else int(ref_auds_str)
            
            image_count = ui_ref_images
            has_video = ui_ref_videos > 0
            has_audio = ui_ref_audios > 0

            # ---------------------------------------------------------
            # 1. Ingest & Analyze Images / Video Frames if connected
            # ---------------------------------------------------------
            sampled_frames = None
            vlm_frame_list = []

            if images is not None:
                tensor = images
                if hasattr(tensor, "get_components"):
                    tensor = tensor.get_components().images
                if not isinstance(tensor, torch.Tensor):
                    tensor = torch.as_tensor(tensor, dtype=torch.float32)
                if tensor.ndim == 3:
                    tensor = tensor.unsqueeze(0)

                total_frames = tensor.shape[0]

                if total_frames > 4:
                    # Video sequence (e.g. from VHS_LoadVideo): subsample 4-6 keyframes across the timeline
                    num_samples = min(6, total_frames)
                    indices = np.linspace(0, total_frames - 1, num_samples, dtype=int)
                    sampled_frames = tensor[indices]
                    has_video = True
                    image_count = max(image_count, num_samples)
                    vlm_frame_list = [sampled_frames[i:i+1] for i in range(num_samples)]
                    log_info(f"H3_Promptor: Detected video frame sequence ({total_frames} frames). Subsampled {num_samples} keyframes across timeline.")
                elif total_frames == 2:
                    # First & Last frames (FL2VA)
                    sampled_frames = tensor
                    image_count = max(image_count, 2)
                    vlm_frame_list = [tensor[0:1], tensor[1:2]]
                    log_info("H3_Promptor: Detected two frames (First & Last frame transition).")
                else:
                    # Single frame (I2VA) or 1-4 reference images
                    sampled_frames = tensor
                    image_count = max(image_count, total_frames)
                    vlm_frame_list = [tensor[i:i+1] for i in range(total_frames)]
                    log_info(f"H3_Promptor: Detected {total_frames} reference image(s).")
            else:
                # Default empty 1x64x64x3 dummy tensor for clean pass-through when no images are connected
                sampled_frames = torch.zeros((1, 64, 64, 3), dtype=torch.float32)

            # ---------------------------------------------------------
            # 2. Parse Existing External Text Vision Context (if any)
            # ---------------------------------------------------------
            parsed_vision_dict = None
            available_tags = []

            if vision_context:
                try:
                    parsed_vision_dict = json.loads(vision_context)
                    media_keys = parsed_vision_dict.get("_media_keys", [])
                    img_count = sum(1 for k in media_keys if k.startswith("<Picture"))
                    vid_count = sum(1 for k in media_keys if k.startswith("<Video"))
                    aud_count = sum(1 for k in media_keys if k.startswith("<Audio"))
                    
                    image_count = max(ui_ref_images, img_count)
                    has_video = (ui_ref_videos > 0) or (vid_count > 0)
                    has_audio = (ui_ref_audios > 0) or (aud_count > 0)
                        
                    formatted_context = []
                    for k in media_keys:
                        v = parsed_vision_dict.get(k, "").strip()
                        if v and "failed to analyze" not in v.lower():
                            formatted_context.append(f"{k}: {v}")
                            available_tags.append(k)
                    if has_video: available_tags.append("<Video 1>")
                    if has_audio: available_tags.append("<Audio 1>")
                    vision_context = "\n".join(formatted_context)
                except json.JSONDecodeError:
                    log_error("H3_Promptor: Failed to parse vision_context as JSON. Treating as raw text.")

            # ---------------------------------------------------------
            # 3. Built-in Multi-Modal Vision Analysis (Local Ollama/LMStudio)
            # ---------------------------------------------------------
            config_manager = get_config_manager()
            llm = create_dynamic_provider(provider, model, config_manager)

            # Pre-evict diffusion models from VRAM if invoking a local provider
            if any(p in provider.lower() for p in ["ollama", "lmstudio", "vllm", "local"]):
                try:
                    log_info("H3_Promptor: Evicting resident models from GPU VRAM to ensure headroom for local LLM...")
                    import gc
                    if model_management is not None:
                        # 1. Unload all models across all torch devices
                        if hasattr(model_management, "get_all_torch_devices"):
                            for dev in model_management.get_all_torch_devices():
                                try:
                                    model_management.free_memory(1e32, dev)
                                except Exception:
                                    pass

                        if hasattr(model_management, "unload_all_models"):
                            try:
                                model_management.unload_all_models()
                            except Exception:
                                pass

                        # 2. Explicitly detach any remaining loaded models and move to CPU
                        if hasattr(model_management, "current_loaded_models"):
                            for loaded_model in list(model_management.current_loaded_models):
                                try:
                                    if loaded_model.model is not None:
                                        loaded_model.model.detach(True)
                                        if hasattr(loaded_model.model, "model") and hasattr(loaded_model.model.model, "to"):
                                            loaded_model.model.model.to(torch.device("cpu"))
                                except Exception:
                                    pass
                            model_management.current_loaded_models.clear()

                        # 3. Reset AIMDO cast buffers (releases 16GB buffer!)
                        if hasattr(model_management, "reset_cast_buffers"):
                            try:
                                model_management.reset_cast_buffers()
                            except Exception:
                                pass

                        # 4. Clean up model pins & registrations
                        if hasattr(model_management, "cleanup_models"):
                            try:
                                model_management.cleanup_models()
                            except Exception:
                                pass
                        if hasattr(model_management, "cleanup_models_gc"):
                            try:
                                model_management.cleanup_models_gc()
                            except Exception:
                                pass

                    # 5. Flush PyTorch allocator and sync CUDA streams
                    gc.collect()
                    if model_management is not None and hasattr(model_management, "soft_empty_cache"):
                        try:
                            model_management.soft_empty_cache(force=True)
                        except Exception:
                            pass
                    if torch.cuda.is_available():
                        torch.cuda.synchronize()
                        torch.cuda.empty_cache()
                        if hasattr(torch.cuda, "ipc_collect"):
                            torch.cuda.ipc_collect()

                    log_info("H3_Promptor: VRAM eviction completed successfully.")
                except Exception as e:
                    log_error(f"Pre-prompt VRAM cleanup error: {e}")

            if vlm_frame_list and vision_mode != "Bypass Vision":
                cache_salt = f"{provider}:{model}:{vision_mode}:{custom_vision_prompt}:{output_language}"
                frame_hash = compute_frame_hash(sampled_frames if sampled_frames is not None else images, salt=cache_salt)

                if frame_hash and frame_hash in _VISION_CACHE:
                    cached_data = _VISION_CACHE[frame_hash]
                    parsed_vision_dict = cached_data.get("dict", {})
                    vision_context = cached_data.get("context", "")
                    for k in cached_data.get("tags", []):
                        if k not in available_tags:
                            available_tags.append(k)
                    if has_video and "<Video 1>" not in available_tags:
                        available_tags.append("<Video 1>")
                    if has_audio and "<Audio 1>" not in available_tags:
                        available_tags.append("<Audio 1>")
                    log_info("H3_Promptor: [Vision Cache Hit] Instant reuse of visual analysis (0.00s).")
                else:
                    log_info(f"H3_Promptor: Running integrated vision analysis on {len(vlm_frame_list)} frame(s) with {provider} ({model})...")

                    prompt_builder = self.prompt_builder
                    sys_prompt = prompt_builder.build_vision_system_prompt(output_language)
                    vibe_sys_prompt = prompt_builder.build_vibe_system_prompt()
                    overrides = PromptBuilder.parse_overrides(custom_vision_prompt)

                    orchestrator = VisionOrchestrator(
                        llm=llm,
                        prompt_builder=prompt_builder,
                        response_parser_cls=ResponseParser,
                        system_prompt=sys_prompt,
                        vibe_system_prompt=vibe_sys_prompt,
                        temperature=0.2,  # Low temperature for stable descriptive accuracy
                        max_tokens=max_tokens,
                        model_override=llm.model,
                    )

                    active_img_mode = "Comprehensive" if vision_mode == "Auto (Adaptive)" else vision_mode
                    ref_images_dict = {f"image_{i}": t for i, t in enumerate(vlm_frame_list)}

                    try:
                        final_dict, media_keys = orchestrator.analyze_all(
                            ref_images=ref_images_dict,
                            ref_videos=None,
                            ref_audios=None,
                            presets=PRESETS,
                            overrides=overrides,
                            global_image_mode=active_img_mode,
                            global_video_mode="Comprehensive",
                            output_language=output_language,
                            batch_size=4,
                            provider_label=provider,
                        )

                        if final_dict:
                            parsed_vision_dict = final_dict
                            formatted_context = []
                            for k in media_keys:
                                v = final_dict.get(k, "").strip()
                                if v and "failed to analyze" not in v.lower():
                                    formatted_context.append(f"{k}: {v}")
                                    if k not in available_tags:
                                        available_tags.append(k)
                            if has_video and "<Video 1>" not in available_tags:
                                available_tags.append("<Video 1>")
                            if has_audio and "<Audio 1>" not in available_tags:
                                available_tags.append("<Audio 1>")

                            vision_context = "\n".join(formatted_context)
                            log_info(f"H3_Promptor: Successfully extracted visual context for: {', '.join(media_keys)}")

                            if frame_hash:
                                if len(_VISION_CACHE) > 32:
                                    _VISION_CACHE.pop(next(iter(_VISION_CACHE)))
                                _VISION_CACHE[frame_hash] = {
                                    "dict": parsed_vision_dict,
                                    "context": vision_context,
                                    "tags": list(available_tags)
                                }
                    except Exception as e:
                        log_error(f"H3_Promptor: Integrated vision analysis encountered error: {e}")

            # ---------------------------------------------------------
            # 4. Auto Task Detection
            # ---------------------------------------------------------
            detected_type = TaskDetector.detect(
                image_count=image_count,
                has_video=has_video,
                has_audio=has_audio,
                user_override=task_type
            )
            task_desc = TaskDetector.get_task_description(detected_type)
            log_info(f"H3_Promptor: Configured Task Mode -> {detected_type} ({task_desc})")

            style_prompt = CINEMATIC_STYLES.get(cinematic_style, "")
            effective_desc = f"{description}\n[Cinematic Style Mandate: {style_prompt}]" if style_prompt else description

            try:
                if generation_mode == "Turbo (Single-Stage)":
                    log_info(f"H3_Promptor: Executing Turbo (Single-Stage) direct synthesis for {detected_type}...")
                    turbo_sys = self.prompt_builder.build_system_prompt(detected_type, duration=duration, output_language=output_language)
                    turbo_user = self.prompt_builder.build_turbo_user_message(
                        description=effective_desc,
                        duration=duration,
                        task_type=detected_type,
                        vision_context=vision_context,
                        cinematic_style=style_prompt,
                        output_language=output_language,
                        available_tags=available_tags
                    )
                    res_turbo = llm.chat(
                        system_prompt=turbo_sys,
                        user_message=turbo_user,
                        base64_images=None,
                        temperature=temperature,
                        max_tokens=max_tokens
                    )
                    if not res_turbo.success:
                        err = f"[H3-Promptor Turbo Error] {res_turbo.error}"
                        log_error(err)
                        raise RuntimeError(err)
                    raw_storyboard = res_turbo.content
                else:
                    # ---------------------------------------------------------
                    # 5. STAGE 1: Cinematic Director Blueprint
                    # ---------------------------------------------------------
                    log_info(f"H3_Promptor: Executing Stage 1 (Director Blueprint) for {detected_type}...")
                    stage1_sys = self.prompt_builder.build_blueprint_system_prompt(output_language=output_language)
                    stage1_user = self.prompt_builder.build_blueprint_user_message(
                        description=effective_desc,
                        duration=duration,
                        task_type=detected_type,
                        vision_context=vision_context,
                        output_language=output_language,
                        image_count=image_count,
                        has_video=has_video,
                        parsed_vision_dict=parsed_vision_dict
                    )

                    res_stage1 = llm.chat(
                        system_prompt=stage1_sys,
                        user_message=stage1_user,
                        base64_images=None,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )

                    if not res_stage1.success:
                        err = f"[H3-Promptor Stage 1 Error] {res_stage1.error}"
                        log_error(err)
                        raise RuntimeError(err)

                    blueprint_text = res_stage1.content

                    # ---------------------------------------------------------
                    # 6. STAGE 2: Shot-by-Shot Storyboard Synthesis
                    # ---------------------------------------------------------
                    log_info(f"H3_Promptor: Executing Stage 2 (Storyboard Synthesis) for {detected_type}...")
                    stage2_sys = self.prompt_builder.build_system_prompt(detected_type, duration=duration, output_language=output_language)
                    stage2_user = self.prompt_builder.build_storyboard_user_message(
                        blueprint=blueprint_text,
                        description=effective_desc,
                        duration=duration,
                        task_type=detected_type,
                        output_language=output_language,
                        available_tags=available_tags
                    )

                    res_stage2 = llm.chat(
                        system_prompt=stage2_sys,
                        user_message=stage2_user,
                        base64_images=None,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )

                    if not res_stage2.success:
                        err = f"[H3-Promptor Stage 2 Error] {res_stage2.error}"
                        log_error(err)
                        raise RuntimeError(err)

                    raw_storyboard = res_stage2.content

                # ---------------------------------------------------------
                # 7. Assembly & Official MiniMax H3 Formatting
                # ---------------------------------------------------------
                subject_defs, valid_tags = self.prompt_builder.generate_subject_definitions(
                    image_count, has_video=has_video, has_audio=has_audio, parsed_vision_dict=parsed_vision_dict
                )
                alignment_inst = self.prompt_builder.generate_alignment_instruction(detected_type, duration, image_count)

                cleaned_prompt = PostProcessor.clean(
                    raw_storyboard, 
                    detected_type, 
                    full_task_desc=task_desc,
                    subject_defs=subject_defs,
                    alignment_inst=alignment_inst,
                    duration=duration
                )

                # Extract structured storyboard elements if available
                character_memory = ""
                global_soundscape_out = ""
                non_diegetic_music_out = ""

                if "longvideo" in detected_type.lower():
                    cmem, snd, mus, p_body = PostProcessor.parse_longvideo_sections(raw_storyboard)
                    character_memory = cmem
                    global_soundscape_out = snd
                    non_diegetic_music_out = mus
                    cleaned_prompt = p_body or cleaned_prompt
                else:
                    _, snd, mus = PostProcessor.split_audio_music(raw_storyboard)
                    global_soundscape_out = snd
                    non_diegetic_music_out = mus

                log_info(f"H3_Promptor: Generated valid MiniMax H3 prompt ({len(cleaned_prompt)} chars).")
                return {
                    "ui": {"text": [raw_storyboard if "longvideo" in detected_type.lower() else cleaned_prompt]},
                    "result": (cleaned_prompt, vision_context, detected_type, sampled_frames, character_memory, global_soundscape_out, non_diegetic_music_out),
                }

            finally:
                # Guarantee local model is unloaded from GPU memory before downstream sampler starts
                llm.unload_model()
                if model_management is not None:
                    try:
                        model_management.soft_empty_cache()
                    except Exception:
                        pass

        except Exception as e:
            error_msg = f"[H3-Promptor Error] {str(e)}"
            log_error(str(e))
            raise RuntimeError(error_msg)
