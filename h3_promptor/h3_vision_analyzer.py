from __future__ import annotations
import os
import json
from pathlib import Path
from PIL import Image
import torch
import numpy as np

try:
    import folder_paths
except ImportError:
    folder_paths = None

try:
    import comfy.model_management as model_management
except Exception:
    model_management = None

try:
    from comfy_api.latest import io
except Exception:
    io = None

from .config_manager import get_config_manager
from .utils import log_info, log_error, create_dynamic_provider
from .dynamic_discovery import get_ollama_models

curr_dir = os.path.dirname(os.path.realpath(__file__))
with open(os.path.join(curr_dir, 'vision_prompts.json'), 'r', encoding='utf-8') as f:
    PRESETS = json.load(f)

IMAGE_MODES = list(PRESETS.get('image_prompts', {}).keys())
VIDEO_MODES = list(PRESETS.get('video_prompts', {}).keys())
PROVIDERS = ["Ollama", "vLLM", "LM Studio", "OpenAI", "Anthropic Claude", "Google Gemini"]

def get_file_path(filename: str, type: str = "input", subfolder: str = "") -> str:
    if type == "input":
        base_dir = folder_paths.get_input_directory()
    elif type == "output":
         base_dir = folder_paths.get_output_directory()
    elif type == "temp":
         base_dir = folder_paths.get_temp_directory()
    else:
        base_dir = folder_paths.get_input_directory()
    
    if subfolder:
        return os.path.join(base_dir, subfolder, filename)
    return os.path.join(base_dir, filename)

def video_path_to_tensor(video_path: str, max_frames: int = 4) -> torch.Tensor:
    import cv2
    cap = cv2.VideoCapture(video_path)
    frames = []
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames > max_frames:
        indices = np.linspace(0, total_frames - 1, max_frames, dtype=int)
    else:
        indices = np.arange(total_frames)
        
    for idx in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if ret:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frames.append(frame)
    cap.release()
    
    if len(frames) == 0:
        raise ValueError(f"Failed to read any frames from video: {video_path}")
        
    frames_np = np.stack(frames).astype(np.float32) / 255.0
    return torch.from_numpy(frames_np)

_BaseNode = io.ComfyNode if io is not None else object

class H3_Vision_Analyzer(_BaseNode):
    """
    MiniMax H3 Vision Analyzer (Dynamic Model Discovery Edition)
    Provides automatic live model probing and exact original-ratio Media outputs.
    """
    OUTPUT_IS_LIST = (False, True)
    
    @classmethod
    def define_schema(cls):
        initial_models = get_ollama_models(filter_type="vision")
        
        return io.Schema(
            node_id="H3_Vision_Analyzer",
            display_name="MiniMax H3 Vision Analyzer",
            category="CosmicCrafter/H3 Promptor",
            inputs=[
                io.Combo.Input("provider", options=PROVIDERS, default="Ollama", tooltip="Vision LLM provider. Live-queries local system when Ollama/LM Studio is selected."),
                io.Combo.Input("model", options=initial_models, default=initial_models[0], tooltip="Live model selection with [Vision] capabilities."),
                io.Combo.Input("global_image_mode", options=IMAGE_MODES, default="Subject / Identity"),
                io.Combo.Input("global_video_mode", options=VIDEO_MODES, default="Comprehensive"),
                io.Float.Input("temperature", default=0.2, min=0.0, max=1.0, step=0.05, optional=True),
                io.Int.Input("max_tokens", default=2048, min=256, max=8192, step=256, optional=True),
                io.Combo.Input("output_language", options=["English", "Chinese"], default="English", optional=True),
                io.String.Input("_media_state", default="", extra_dict={"hidden": True}),
                io.String.Input("custom_prompt_override", multiline=True, default="", optional=True),
            ],
            outputs=[
                io.String.Output("vision_context", display_name="vision_context"),
                io.Image.Output("ref_images", display_name="ref_images"),
            ],
        )
    
    @classmethod
    def execute(
        cls,
        provider: str = "Ollama",
        model: str = "",
        global_image_mode: str = "Subject / Identity",
        global_video_mode: str = "Comprehensive",
        output_language: str = "English",
        custom_prompt_override: str = "",
        temperature: float = 0.2,
        max_tokens: int = 2048,
        _media_state: str = "{}"
    ) -> io.NodeOutput:
        try:
            from .response_parser import ResponseParser
            from .prompt_builder import PromptBuilder
            from .vision_orchestrator import VisionOrchestrator
            
            try:
                media_data = json.loads(_media_state if _media_state else "{}")
            except Exception:
                media_data = {"media": []}
            
            media_list = media_data.get("media", [])
            parsed_images_for_vlm = []
            parsed_videos_for_vlm = []
            parsed_video_paths = []
            parsed_audios_for_vlm = []
            
            for entry in media_list:
                if len(entry) >= 2:
                    slot_name, data = entry[0], entry[1]
                    file_name = data.get("name", "")
                    kind = data.get("kind", "")
                    if not file_name:
                        continue
                    
                    parts = file_name.split('/')
                    filename = parts[-1]
                    subfolder = '/'.join(parts[:-1]) if len(parts) > 1 else ""
                    full_path = get_file_path(filename, "input", subfolder)
                    
                    if not os.path.exists(full_path):
                        continue
                        
                    if kind == "image":
                        try:
                            i = Image.open(full_path)
                            from PIL import ImageOps
                            i = ImageOps.exif_transpose(i)
                            pil_img = i.convert("RGB")
                            orig_array = np.array(pil_img).astype(np.float32) / 255.0
                            orig_tensor = torch.from_numpy(orig_array)[None,]
                            parsed_images_for_vlm.append(orig_tensor)
                        except Exception as e:
                            log_error(f"Failed to load image {full_path}: {e}")
                            
                    elif kind == "video":
                        try:
                            video_tensor = video_path_to_tensor(full_path, 4)
                            parsed_videos_for_vlm.append(video_tensor)
                            parsed_video_paths.append(full_path)
                        except Exception as e:
                            log_error(f"Failed to load video {full_path}: {e}")
                            
                    elif kind == "audio":
                        parsed_audios_for_vlm.append(full_path)
            
            out_images = parsed_images_for_vlm
            
            config_manager = get_config_manager()
            llm = create_dynamic_provider(provider, model, config_manager)
            
            if "ollama" in provider.lower():
                log_info("Unloading models from VRAM for vision inference...")
                model_management.unload_all_models()
                model_management.soft_empty_cache()
                
            prompt_builder = PromptBuilder()
            system_prompt = prompt_builder.build_vision_system_prompt(output_language)
            vibe_system_prompt = prompt_builder.build_vibe_system_prompt()
            overrides = PromptBuilder.parse_overrides(custom_prompt_override)
            
            orchestrator = VisionOrchestrator(
                llm=llm,
                prompt_builder=prompt_builder,
                response_parser_cls=ResponseParser,
                system_prompt=system_prompt,
                vibe_system_prompt=vibe_system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                model_override=llm.model,
            )
            
            ref_images_dict = {f"image_{i}": tensor for i, tensor in enumerate(parsed_images_for_vlm)}
            ref_videos_dict = {f"video_{i}": path for i, path in enumerate(parsed_videos_for_vlm)}
            ref_audios_dict = {f"audio_{i}": path for i, path in enumerate(parsed_audios_for_vlm)}
            
            final_dict, media_keys = orchestrator.analyze_all(
                ref_images=ref_images_dict if len(ref_images_dict) > 0 else None,
                ref_videos=ref_videos_dict if len(ref_videos_dict) > 0 else None,
                ref_audios=ref_audios_dict if len(ref_audios_dict) > 0 else None,
                presets=PRESETS,
                overrides=overrides,
                global_image_mode=global_image_mode,
                global_video_mode=global_video_mode,
                output_language=output_language,
                batch_size=4,
                provider_label=provider,
            )
            
            if not final_dict:
                return io.NodeOutput("{}", out_images)
                
            final_dict["_media_keys"] = media_keys
            final_output = json.dumps(final_dict, indent=4, ensure_ascii=False)
            
            if "ollama" in provider.lower():
                model_management.soft_empty_cache()
                
            return io.NodeOutput(final_output, out_images)
            
        except Exception as e:
            log_error(str(e))
            return io.NodeOutput(f"[Analyzer Exception]: {str(e)}", [])
