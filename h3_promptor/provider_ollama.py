import json
import urllib.request
import urllib.error
from .provider_base import BaseLLMProvider, LLMResponse

class OllamaProvider(BaseLLMProvider):
    def __init__(self, model="qwen3-vl:8b", api_base="http://127.0.0.1:11434", timeout=300):
        self.model = model.replace("[Vision] ", "").replace("[LLM] ", "").replace("[Embed] ", "").replace("[Text] ", "").strip()
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout

    def chat(self, system_prompt: str, user_message: str, base64_images=None, temperature=0.7, max_tokens=4096, **kwargs) -> LLMResponse:
        url = f"{self.api_base}/api/chat"
        active_model = kwargs.get("model", self.model)
        active_model = str(active_model).replace("[Vision] ", "").replace("[LLM] ", "").replace("[Embed] ", "").replace("[Text] ", "").strip()
        
        messages = [{"role": "system", "content": system_prompt}]
        user_msg = {"role": "user", "content": user_message}
        cleaned_images = []
        if base64_images:
            extracted_texts = []
            for item in base64_images:
                if isinstance(item, str):
                    cleaned_images.append(item)
                elif isinstance(item, dict):
                    if "image" in item and isinstance(item["image"], str):
                        cleaned_images.append(item["image"])
                    if "text" in item and isinstance(item["text"], str):
                        extracted_texts.append(item["text"])
            if extracted_texts:
                extra_t = "\n".join(extracted_texts)
                user_msg["content"] = f"{user_message}\n\n{extra_t}".strip() if user_message else extra_t
            if cleaned_images:
                user_msg["images"] = cleaned_images
        messages.append(user_msg)
        
        # Dynamically size KV cache: 4096 is optimal for text-to-video prompts, 8192 for multi-frame vision analysis
        has_images = bool(cleaned_images or any("images" in m for m in messages))
        ctx_size = 8192 if has_images else 4096

        payload = {
            "model": active_model,
            "messages": messages,
            "stream": False,
            "keep_alive": 0,  # CRITICAL: Release VRAM & RAM back to GPU immediately upon completion
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx": ctx_size,  # Adaptive KV cache prevents allocating unnecessary GBs of VRAM
            }
        }
        
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "User-Agent": "ComfyUI-CosmicCrafter-H3"}
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                content = data.get("message", {}).get("content", "")
                return LLMResponse(content=content, model=self.model)
        except urllib.error.HTTPError as e:
            err_msg = str(e)
            try:
                raw_body = e.read().decode("utf-8", errors="ignore")
                err_json = json.loads(raw_body)
                if "error" in err_json:
                    err_msg = err_json["error"]
                elif raw_body:
                    err_msg = raw_body
            except Exception:
                pass
            self.unload_model()
            return LLMResponse(content="", error=f"Ollama Error: {err_msg}", model=self.model)
        except Exception as e:
            # On error/timeout, force Ollama to instantly unload the model so VRAM is not orphaned
            self.unload_model()
            return LLMResponse(content="", error=f"Ollama Request Error: {str(e)}", model=self.model)
        finally:
            # Always ensure Ollama unloads immediately after inference
            self.unload_model()

    def unload_model(self):
        """Force Ollama to unload the resident model from VRAM/RAM immediately."""
        try:
            url = f"{self.api_base}/api/generate"
            payload = {"model": self.model, "keep_alive": 0}
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "User-Agent": "ComfyUI-CosmicCrafter-H3"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                resp.read()
        except Exception:
            pass

    def is_available(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.api_base}/api/tags", headers={"User-Agent": "ComfyUI-CosmicCrafter-H3"})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                return resp.status == 200
        except Exception:
            return False
