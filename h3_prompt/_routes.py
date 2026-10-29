"""HTTP routes for the H3 prompt toolkit.

``GET /cosmic_h3/models?provider=<p>&type=<vision|text|all>&endpoint=<url>``
returns ``{"provider": p, "models": [...]}`` for the dynamic-model dropdown in
``js/h3_dynamic_models.js``. Names are tagged ``[Vision]`` / ``[LLM]`` /
``[Embed]``; the node backend strips the tag again before calling the provider,
and workflows saved against the retired promptor carry the same tags.
"""
from __future__ import annotations

import logging

from . import _providers as providers

_LOG = logging.getLogger("h3_prompt")
_REGISTERED = False

# Name-fragment heuristics only; a miss just sorts the model under [LLM], which
# is survivable -- the user can still pick it.
_VISION_HINTS = (
    "vision", "-vl", "_vl", "llava", "minicpm", "mllama", "moondream",
    "pixtral", "internvl", "cogvlm", "paligemma", "florence", "bakllava",
    "qwen2-vl", "qwen2.5-vl", "qwen3-vl", "gemma3", "gemma4", "kimi-vl",
    "llama3.2-vision",
)
_EMBED_HINTS = ("embed", "bge-", "e5-", "bert", "nomic", "gte-")


def _tag(name: str) -> str:
    low = name.lower()
    if any(h in low for h in _EMBED_HINTS):
        return f"[Embed] {name}"
    if any(h in low for h in _VISION_HINTS):
        return f"[Vision] {name}"
    return f"[LLM] {name}"


def models_for(provider: str, kind: str = "all", endpoint: str = "") -> list:
    """Tagged model list for the dropdown, ordered so the likeliest pick is on
    top: vision models first for the analyzer, text/embed first for the writer."""
    names = providers.list_models(provider, endpoint=endpoint) or []
    vision = sorted(_tag(n) for n in names if _tag(n).startswith("[Vision]"))
    llm = sorted(_tag(n) for n in names if _tag(n).startswith("[LLM]"))
    embed = sorted(_tag(n) for n in names if _tag(n).startswith("[Embed]"))
    if kind == "vision":
        ordered = vision + llm + embed
    elif kind == "text":
        ordered = llm + embed + vision
    else:
        ordered = vision + llm + embed
    return ordered or ["[Offline] provider reported no models"]


def init_routes() -> bool:
    """Attach the models route to the running PromptServer. No-ops cleanly in
    standalone/test contexts (no server module, or server not started yet)."""
    global _REGISTERED
    if _REGISTERED:
        return True
    try:
        from aiohttp import web
        from server import PromptServer
    except ImportError as exc:
        _LOG.debug("h3_prompt routes not registered (%s)", exc)
        return False
    if getattr(PromptServer, "instance", None) is None:
        _LOG.debug("h3_prompt routes not registered (PromptServer not started)")
        return False

    @PromptServer.instance.routes.get("/cosmic_h3/models")
    async def _h3_models(request):
        provider = request.rel_url.query.get("provider", "ollama").lower()
        kind = request.rel_url.query.get("type", "all")
        endpoint = request.rel_url.query.get("endpoint", "")
        try:
            models = models_for(provider, kind, endpoint)
        except Exception as exc:  # provider list should never 500 the dropdown
            _LOG.debug("model query failed for %s: %s", provider, exc)
            models = [f"[Offline] {provider} query failed"]
        return web.json_response({"provider": provider, "models": models})

    _REGISTERED = True
    _LOG.info("h3_prompt: registered /cosmic_h3/models")
    return True
