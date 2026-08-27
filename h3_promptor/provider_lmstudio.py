import json
import urllib.request
import urllib.error
from .provider_base import BaseLLMProvider, LLMResponse

class LMStudioProvider(BaseLLMProvider):
    def __init__(self, model="local-model", api_base="http://127.0.0.1:1234/v1", timeout=180):
        self.model = model.replace("[Vision] ", "").replace("[LLM] ", "").replace("[Embed] ", "").replace("[Text] ", "").strip()
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout

    def chat(self, system_prompt: str, user_message: str, base64_images=None, temperature=0.7, max_tokens=4096) -> LLMResponse:
        url = f"{self.api_base}/chat/completions"
        
        messages = [{"role": "system", "content": system_prompt}]
        
        if base64_images:
            cleaned_images = []
            extracted_texts = []
            for item in base64_images:
                if isinstance(item, str):
                    cleaned_images.append(item)
                elif isinstance(item, dict):
                    if "image" in item and isinstance(item["image"], str):
                        cleaned_images.append(item["image"])
                    if "text" in item and isinstance(item["text"], str):
                        extracted_texts.append(item["text"])
            
            final_text = f"{user_message}\n\n" + "\n".join(extracted_texts) if extracted_texts else user_message
            user_content = [{"type": "text", "text": final_text}]
            for b64 in cleaned_images:
                user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
            messages.append({"role": "user", "content": user_content})
        else:
            messages.append({"role": "user", "content": user_message})
            
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "User-Agent": "ComfyUI-CosmicCrafter-H3"}
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                choices = data.get("choices", [])
                if choices:
                    content = choices[0].get("message", {}).get("content", "")
                    return LLMResponse(content=content, model=self.model)
                return LLMResponse(content="", error="No response choices from LM Studio", model=self.model)
        except Exception as e:
            return LLMResponse(content="", error=f"LM Studio Request Error: {str(e)}", model=self.model)

    def is_available(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.api_base}/models", headers={"User-Agent": "ComfyUI-CosmicCrafter-H3"})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                return resp.status == 200
        except Exception:
            return False

