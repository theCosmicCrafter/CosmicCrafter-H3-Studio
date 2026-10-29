"""LLM backends, written from each vendor's own HTTP API.

One function each, one shape out. Nothing here is clever: a provider is a name, a
way to list models, and a way to send a system+user pair and get text back. They
are kept in one small file because the differences between them are three lines
of JSON, and spreading that across five modules hides how similar they are.

Local providers (Ollama, LM Studio) need no key. Cloud providers read their key
from the environment first and the node's field second, so a key never has to be
typed into a workflow that might get shared.

Every call fails LOUDLY with a message naming the provider and what to do about
it. A prompt node that silently returns "" wastes a render.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

TIMEOUT = 180

PROVIDERS = ("ollama", "lmstudio", "openai", "anthropic", "gemini")

DEFAULT_ENDPOINTS = {
    "ollama": "http://127.0.0.1:11434",
    "lmstudio": "http://127.0.0.1:1234",
    "openai": "https://api.openai.com",
    "anthropic": "https://api.anthropic.com",
    "gemini": "https://generativelanguage.googleapis.com",
}
ENV_KEYS = {
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY"),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
}


class ProviderError(RuntimeError):
    pass


def _key(provider: str, supplied: str = "") -> str:
    if supplied.strip():
        return supplied.strip()
    for name in ENV_KEYS.get(provider, ()):
        v = os.environ.get(name, "").strip()
        if v:
            return v
    return ""


def _post(url: str, payload: dict, headers: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:400]
        raise ProviderError(f"HTTP {e.code} from {url}: {body}") from None
    except urllib.error.URLError as e:
        raise ProviderError(f"cannot reach {url} ({e.reason})") from None


def _get(url: str, headers: dict | None = None) -> dict:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        raise ProviderError(f"cannot reach {url} ({e})") from None


# --- model discovery -----------------------------------------------------------
def list_models(provider: str, endpoint: str = "", api_key: str = "") -> list[str]:
    """What this provider actually has, asked at call time. Returns [] rather than
    raising: an empty dropdown is a survivable UI state, an exception at node-scan
    time is not."""
    base = (endpoint or DEFAULT_ENDPOINTS.get(provider, "")).rstrip("/")
    try:
        if provider == "ollama":
            return sorted(m["name"] for m in _get(f"{base}/api/tags").get("models", []))
        if provider == "lmstudio":
            return sorted(m["id"] for m in _get(f"{base}/v1/models").get("data", []))
        if provider == "openai":
            k = _key("openai", api_key)
            if not k:
                return []
            data = _get(f"{base}/v1/models", {"Authorization": f"Bearer {k}"}).get("data", [])
            return sorted(m["id"] for m in data if "gpt" in m["id"] or m["id"].startswith("o"))
        if provider == "anthropic":
            k = _key("anthropic", api_key)
            if not k:
                return []
            data = _get(f"{base}/v1/models",
                        {"x-api-key": k, "anthropic-version": "2023-06-01"}).get("data", [])
            return sorted(m["id"] for m in data)
        if provider == "gemini":
            k = _key("gemini", api_key)
            if not k:
                return []
            data = _get(f"{base}/v1beta/models?key={k}").get("models", [])
            return sorted(m["name"].split("/")[-1] for m in data
                          if "generateContent" in m.get("supportedGenerationMethods", []))
    except ProviderError:
        return []
    return []


# --- generation ----------------------------------------------------------------
def generate(provider: str, model: str, system: str, user: str,
             endpoint: str = "", api_key: str = "",
             temperature: float = 0.7, max_tokens: int = 2048,
             seed: int | None = None) -> str:
    """`seed` goes to every provider that takes one (ollama, lmstudio and openai as
    the chat-completions `seed`, gemini as generationConfig.seed); anthropic has no
    seed parameter, so it is not sent there. None sends nothing."""
    base = (endpoint or DEFAULT_ENDPOINTS.get(provider, "")).rstrip("/")
    if not model.strip():
        raise ProviderError(f"no model selected for {provider}; pick one in the node")

    if provider in ("ollama", "lmstudio", "openai"):
        # All three speak the OpenAI chat shape; only the path and auth differ.
        if provider == "ollama":
            url, headers = f"{base}/v1/chat/completions", {}
        elif provider == "lmstudio":
            url, headers = f"{base}/v1/chat/completions", {}
        else:
            k = _key("openai", api_key)
            if not k:
                raise ProviderError("no OpenAI key: set OPENAI_API_KEY or fill the api_key field")
            url, headers = f"{base}/v1/chat/completions", {"Authorization": f"Bearer {k}"}
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
            "stream": False,
        }
        if seed is not None:
            payload["seed"] = int(seed)
        data = _post(url, payload, headers)
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            raise ProviderError(f"{provider} returned no message: {str(data)[:300]}") from None

    if provider == "anthropic":
        k = _key("anthropic", api_key)
        if not k:
            raise ProviderError("no Anthropic key: set ANTHROPIC_API_KEY or fill the api_key field")
        data = _post(f"{base}/v1/messages", {
            "model": model,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
        }, {"x-api-key": k, "anthropic-version": "2023-06-01"})
        blocks = data.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        if not text:
            raise ProviderError(f"anthropic returned no text: {str(data)[:300]}")
        return text

    if provider == "gemini":
        k = _key("gemini", api_key)
        if not k:
            raise ProviderError("no Gemini key: set GEMINI_API_KEY or fill the api_key field")
        generation_config = {"temperature": float(temperature),
                             "maxOutputTokens": int(max_tokens)}
        if seed is not None:
            # Gemini's seed is an int32; ComfyUI seeds go to 2**64-1, so fold rather than 400
            generation_config["seed"] = int(seed) % (2 ** 31)
        data = _post(f"{base}/v1beta/models/{model}:generateContent?key={k}", {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": generation_config,
        }, {})
        try:
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts)
        except (KeyError, IndexError):
            raise ProviderError(f"gemini returned no text: {str(data)[:300]}") from None

    raise ProviderError(f"unknown provider {provider!r}; expected one of {', '.join(PROVIDERS)}")
