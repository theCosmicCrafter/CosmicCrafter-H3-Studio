import urllib.request
import urllib.error
import json
import logging

logger = logging.getLogger("CosmicH3Promptor")

VISION_KEYWORDS = [
    "vision", "vl", "llava", "minicpm-v", "minicpm", "mllama", "llama3.2-vision",
    "qwen-vl", "qwen2.5-vl", "qwen3-vl", "moondream", "pixtral", "internvl",
    "deepseek-vl", "bakllava", "cogvlm", "florence", "paligemma", "gemma3", "gemma-3", "gemma4", "gemma-4", "kimi"
]

def is_vision_model(name: str) -> bool:
    low = name.lower()
    return any(k in low for k in VISION_KEYWORDS)

def check_ollama_model_is_vision(name: str, host: str = "http://127.0.0.1:11434") -> bool:
    if is_vision_model(name):
        return True
    try:
        req = urllib.request.Request(
            f"{host.rstrip('/')}/api/show",
            data=json.dumps({"name": name}).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "ComfyUI-CosmicCrafter-H3/1.0"}
        )
        with urllib.request.urlopen(req, timeout=0.8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            info = data.get("model_info", {})
            for k in info.keys():
                if "vision" in k.lower() or "clip" in k.lower() or "projector" in k.lower():
                    return True
            for fam in data.get("details", {}).get("families", []):
                if "vision" in fam.lower() or "vl" in fam.lower():
                    return True
    except Exception:
        pass
    return False

def get_ollama_models(host="http://127.0.0.1:11434", filter_type="all", timeout=1.5):
    url = f"{host.rstrip('/')}/api/tags"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ComfyUI-CosmicCrafter-H3/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            raw_models = data.get("models", [])
            
            vision_models = []
            text_models = []
            
            for m in raw_models:
                name = m.get("name", "")
                if not name:
                    continue
                if check_ollama_model_is_vision(name, host):
                    vision_models.append(f"[Vision] {name}")
                elif "embed" in name.lower() or "bge" in name.lower() or "bert" in name.lower():
                    text_models.append(f"[Embed] {name}")
                else:
                    text_models.append(f"[LLM] {name}")
                    
            vision_models.sort()
            text_models.sort()
            
            # Put vision models on top, followed by all text LLMs
            res = vision_models + text_models
            return res if res else ["[Empty] No models found in Ollama"]
    except Exception:
        return [f"[Offline] Ollama offline ({host})"]

def get_lmstudio_models(host="http://127.0.0.1:1234", filter_type="all", timeout=1.5):
    url = f"{host.rstrip('/')}/v1/models"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ComfyUI-CosmicCrafter-H3/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            raw_models = data.get("data", [])
            
            vision_models = []
            text_models = []
            
            for m in raw_models:
                m_id = m.get("id", "")
                if not m_id:
                    continue
                if is_vision_model(m_id):
                    vision_models.append(f"[Vision] {m_id}")
                else:
                    text_models.append(f"[LLM] {m_id}")
                    
            vision_models.sort()
            text_models.sort()
            
            if filter_type == "vision":
                res = vision_models if vision_models else text_models
            elif filter_type == "text":
                res = text_models + vision_models
            else:
                res = vision_models + text_models
                
            return res if res else ["[Empty] No models found in LM Studio"]
    except Exception:
        return [f"[Offline] LM Studio offline ({host})"]

def get_vllm_models(host="http://127.0.0.1:8000", filter_type="all", timeout=1.5):
    url = f"{host.rstrip('/')}/v1/models"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ComfyUI-CosmicCrafter-H3/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            raw_models = data.get("data", [])
            vision_models = []
            text_models = []
            for m in raw_models:
                m_id = m.get("id", "")
                if not m_id:
                    continue
                if is_vision_model(m_id):
                    vision_models.append(f"[Vision] {m_id}")
                else:
                    text_models.append(f"[LLM] {m_id}")
            vision_models.sort()
            text_models.sort()
            res = vision_models + text_models
            return res if res else ["[Empty] No models loaded in vLLM"]
    except Exception:
        return [f"[Offline] vLLM offline ({host})"]

def get_cloud_models(provider_name="openai", filter_type="all"):
    if "openai" in provider_name.lower():
        if filter_type == "vision":
            return ["gpt-5", "gpt-4o", "gpt-4o-mini", "gpt-4-turbo"]
        return ["gpt-5", "gpt-4o", "gpt-4o-mini", "o1", "o3-mini", "gpt-4-turbo"]
    elif "claude" in provider_name.lower() or "anthropic" in provider_name.lower():
        return ["claude-3-7-sonnet-latest", "claude-3-5-sonnet-latest", "claude-3-5-haiku-latest", "claude-3-opus-latest"]
    elif "gemini" in provider_name.lower():
        return ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash", "gemini-1.5-pro"]
    return ["default-model"]

def get_models_for_provider(provider: str, filter_type="all"):
    prov = provider.lower()
    if "ollama" in prov:
        return get_ollama_models(filter_type=filter_type)
    elif "vllm" in prov:
        return get_vllm_models(filter_type=filter_type)
    elif "lm" in prov or "studio" in prov:
        return get_lmstudio_models(filter_type=filter_type)
    elif "openai" in prov:
        return get_cloud_models("openai", filter_type=filter_type)
    elif "claude" in prov or "anthropic" in prov:
        return get_cloud_models("claude", filter_type=filter_type)
    elif "gemini" in prov:
        return get_cloud_models("gemini", filter_type=filter_type)
    return ["default-model"]

def init_routes():
    try:
        from server import PromptServer
        from aiohttp import web
        
        if hasattr(PromptServer, "instance") and PromptServer.instance is not None:
            routes = PromptServer.instance.routes
            
            @routes.get("/cosmic_h3/models")
            async def fetch_models_endpoint(request):
                provider = request.rel_url.query.get("provider", "ollama")
                filter_type = request.rel_url.query.get("type", "all")
                models = get_models_for_provider(provider, filter_type=filter_type)
                return web.json_response({"provider": provider, "models": models})

            @routes.post("/cosmic_h3/free_vram")
            async def free_vram_endpoint(request):
                try:
                    import torch, gc
                    from comfy import model_management
                    if hasattr(model_management, "get_all_torch_devices"):
                        for dev in model_management.get_all_torch_devices():
                            try: model_management.free_memory(1e32, dev)
                            except Exception: pass
                    if hasattr(model_management, "unload_all_models"):
                        try: model_management.unload_all_models()
                        except Exception: pass
                    if hasattr(model_management, "current_loaded_models"):
                        for loaded_model in list(model_management.current_loaded_models):
                            try:
                                if loaded_model.model is not None:
                                    loaded_model.model.detach(True)
                                    if hasattr(loaded_model.model, "model") and hasattr(loaded_model.model.model, "to"):
                                        loaded_model.model.model.to(torch.device("cpu"))
                            except Exception: pass
                        model_management.current_loaded_models.clear()
                    if hasattr(model_management, "reset_cast_buffers"):
                        try: model_management.reset_cast_buffers()
                        except Exception: pass
                    if hasattr(model_management, "cleanup_models"):
                        try: model_management.cleanup_models()
                        except Exception: pass
                    if hasattr(model_management, "cleanup_models_gc"):
                        try: model_management.cleanup_models_gc()
                        except Exception: pass
                    gc.collect()
                    if hasattr(model_management, "soft_empty_cache"):
                        try: model_management.soft_empty_cache(force=True)
                        except Exception: pass
                    if torch.cuda.is_available():
                        torch.cuda.synchronize()
                        torch.cuda.empty_cache()
                        if hasattr(torch.cuda, "ipc_collect"):
                            torch.cuda.ipc_collect()
                    return web.json_response({"status": "success", "message": "VRAM fully purged and returned to GPU."})
                except Exception as e:
                    return web.json_response({"status": "error", "error": str(e)}, status=500)

            logger.info("CosmicCrafter-H3-Studio: registered /cosmic_h3/models and /cosmic_h3/free_vram dynamic API routes.")
    except Exception as e:
        logger.warning(f"Could not register PromptServer routes: {e}")

