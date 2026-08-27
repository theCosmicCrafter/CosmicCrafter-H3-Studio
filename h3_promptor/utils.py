import base64
import io
import re
import numpy as np
import logging

logger = logging.getLogger("CosmicCrafter-H3-Promptor")

def log_info(msg: str):
    print(f"\033[34m[Cosmic-H3-Promptor]\033[0m {msg}")

def log_error(msg: str):
    print(f"\033[31m[Cosmic-H3-Promptor ERROR]\033[0m {msg}")

def log_debug(msg: str):
    print(f"\033[90m[Cosmic-H3-Promptor DEBUG]\033[0m {msg}")

def log_warning(msg: str):
    print(f"\033[33m[Cosmic-H3-Promptor WARNING]\033[0m {msg}")

def compute_frame_hash(tensor, salt: str = "") -> str:
    """Computes a lightning-fast content fingerprint of image/video tensors for caching."""
    import hashlib
    if tensor is None:
        return ""
    if hasattr(tensor, "get_components"):
        tensor = tensor.get_components().images
    try:
        arr = tensor.cpu().numpy()
        h = hashlib.sha256()
        h.update(str(arr.shape).encode())
        h.update(salt.encode())
        flat = arr.reshape(-1)
        stride = max(1, len(flat) // 1000)
        h.update(flat[::stride].tobytes())
        return h.hexdigest()
    except Exception:
        return ""

def tensor_to_base64(tensor, max_frames: int = 4, max_dim: int = 768) -> list[str]:
    from PIL import Image
    if hasattr(tensor, "get_components"):
        tensor = tensor.get_components().images

    img_array = tensor.cpu().numpy()
    if img_array.ndim == 3:
        img_array = np.expand_dims(img_array, axis=0)

    batch_size = img_array.shape[0]
    if batch_size > max_frames:
        indices = np.linspace(0, batch_size - 1, max_frames, dtype=int)
    else:
        indices = np.arange(batch_size)

    base64_images = []
    for idx in indices:
        frame_array = img_array[idx]
        frame_array = np.clip(frame_array * 255.0, 0, 255).astype(np.uint8)
        img_pil = Image.fromarray(frame_array)

        # Smart high-quality downscaling: bounds VLM token consumption and accelerates inference 3-5x
        if max(img_pil.size) > max_dim:
            img_pil.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

        buffered = io.BytesIO()
        img_pil.save(buffered, format="JPEG", quality=85)
        base64_images.append(base64.b64encode(buffered.getvalue()).decode("utf-8"))

    return base64_images

def sanitize_llm_output(text: str) -> str:
    if not text:
        return ""

    result = text.strip()
    result = re.sub(r"<think>.*?</think>", "", result, flags=re.DOTALL | re.IGNORECASE).strip()
    
    if "<think>" in result.lower() and "</think>" not in result.lower():
        result = re.sub(r"<think>.*", "", result, flags=re.DOTALL | re.IGNORECASE).strip()

    section_marker = re.search(
        r"(?:^|\n)(\[Shot 1\]|subject_definitions:|integrated_multimodal_description:|detailed_description:|For the target video|How the reference)",
        result,
        re.IGNORECASE
    )
    if section_marker and section_marker.start() > 0:
        preamble = result[:section_marker.start()]
        if any(term in preamble.lower() for term in ["thinking", "thought", "analyze", "drafting", "step 1", "step 2", "constraints", "1.", "2.", "*"]):
            result = result[section_marker.start():].strip()

    fence_match = re.search(r"^```(?:text|json|plaintext|plain|markdown)?\s*\n(.*?)\n```\s*$", result, re.DOTALL)
    if fence_match:
        result = fence_match.group(1).strip()
    else:
        result = re.sub(r"^```[\w]*\s*\n", "", result)
        result = re.sub(r"\n```\s*$", "", result)

    json_match = re.match(r'^\s*\{\s*"(?:prompt|output|result|text)"\s*:\s*"(.*?)"\s*\}\s*$', result, re.DOTALL)
    if json_match:
        result = json_match.group(1).strip().replace("\\n", "\n").replace('\\"', '"')

    preambles = [
        r"^Here(?:'s| is) (?:the|your) (?:generated |rewritten |final )?(?:H3 )?prompt:?\s*\n",
        r"^(?:Sure|Okay|Of course)[!,.]?\s*(?:Here(?:'s| is).*?:)?\s*\n",
        r"^Output:?\s*\n",
    ]
    for preamble in preambles:
        result = re.sub(preamble, "", result, flags=re.IGNORECASE)

    return result.strip()

def _create_provider(provider_key: str, config_manager, api_key_override: str = ""):
    from .provider_ollama import OllamaProvider
    from .provider_lmstudio import LMStudioProvider
    from .provider_openai import OpenAIProvider
    from .provider_claude import ClaudeProvider
    from .provider_gemini import GeminiProvider

    cfg = config_manager.get_provider_config(provider_key)
    if not cfg:
        return OllamaProvider()
    p_type = cfg.get("type", "ollama").lower()
    model = cfg.get("model", "")
    api_key = api_key_override or cfg.get("api_key", "")
    api_base = cfg.get("api_base", "")

    if p_type == "ollama":
        return OllamaProvider(model=model, api_base=api_base or "http://127.0.0.1:11434")
    elif p_type in ("lmstudio", "openai"):
        return OpenAIProvider(model=model, api_base=api_base or "http://127.0.0.1:1234/v1", api_key=api_key)
    elif p_type in ("anthropic", "claude"):
        return ClaudeProvider(model=model, api_base=api_base or "https://api.anthropic.com/v1", api_key=api_key)
    elif p_type == "gemini":
        return GeminiProvider(model=model, api_base=api_base or "https://generativelanguage.googleapis.com/v1beta", api_key=api_key)
    return OllamaProvider(model=model)

def create_dynamic_provider(provider_type: str, model_name: str, config_manager=None):
    from .provider_ollama import OllamaProvider
    from .provider_lmstudio import LMStudioProvider
    from .provider_openai import OpenAIProvider
    from .provider_claude import ClaudeProvider
    from .provider_gemini import GeminiProvider

    prov = provider_type.lower()
    clean_model = model_name.replace("[Vision] ", "").replace("[LLM] ", "").replace("[Embed] ", "").replace("[Text] ", "").strip()




    if "ollama" in prov:
        return OllamaProvider(model=clean_model)
    elif "vllm" in prov:
        return LMStudioProvider(model=clean_model, api_base="http://127.0.0.1:8000/v1")
    elif "lm" in prov or "studio" in prov:
        return LMStudioProvider(model=clean_model)
    elif "openai" in prov:
        api_key = ""
        if config_manager:
            cfg = config_manager.get_provider_config("prov_1720000001")
            api_key = cfg.get("api_key", "")
        return OpenAIProvider(model=clean_model, api_key=api_key)
    elif "claude" in prov or "anthropic" in prov:
        api_key = ""
        if config_manager:
            cfg = config_manager.get_provider_config("prov_1720000002")
            api_key = cfg.get("api_key", "")
        return ClaudeProvider(model=clean_model, api_key=api_key)
    elif "gemini" in prov:
        api_key = ""
        if config_manager:
            cfg = config_manager.get_provider_config("prov_1720000003")
            api_key = cfg.get("api_key", "")
        return GeminiProvider(model=clean_model, api_key=api_key)
    else:
        return OllamaProvider(model=clean_model)
