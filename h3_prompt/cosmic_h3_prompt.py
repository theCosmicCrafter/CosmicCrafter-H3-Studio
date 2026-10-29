"""The H3 prompt nodes.

CosmicH3Promptor        idea -> a validated H3 prompt
CosmicH3VisionAnalyzer  reference images (plus optional forensic evidence) -> the
                        visual context an H3 prompt needs
CosmicH3VideoForensics  a video's frames and track -> timestamped cut / freeze /
                        flash / black frame / sound evidence and a contact sheet,
                        for reverse prompting an existing clip

The promptor returns a `report` string alongside the prompt. That is the point of
this implementation: the prompt is checked against H3's own grammar before it ever
reaches the sampler, and anything the checker could not safely fix is named in
the report instead of being discovered twenty minutes into a render.
"""
from __future__ import annotations

import base64
import importlib.util
import io
import sys
from pathlib import Path

import torch


def _sibling(name):
    """Load a helper from this folder.

    Works whether this file arrives as a real package member (the normal case in
    this repo) or is file-loaded without package context -- the helpers are
    '_'-prefixed so flat node-file scanners never import them on their own."""
    path = Path(__file__).parent / f"_{name}.py"
    mod_name = f"h3_studio.h3_prompt._{name}"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec_ = importlib.util.spec_from_file_location(mod_name, path)
    if spec_ is None or spec_.loader is None:
        raise ImportError(f"Cosmic H3 Promptor: cannot load helper {path}")
    mod = importlib.util.module_from_spec(spec_)
    sys.modules[mod_name] = mod
    spec_.loader.exec_module(mod)
    return mod


spec = _sibling("spec")
validate = _sibling("validate")
providers = _sibling("providers")
forensics = _sibling("forensics")

_MAX_SIDE = 1024
FOCUS_EVENT_CHAIN = "event chain (timestamped)"

_MODEL_BAD = ("", "[offline]", "[empty]", "[no models", "[connection", "querying")


def _clean_model_name(model) -> str:
    """Normalize the model widget value. The dynamic-model JS offers entries
    tagged '[Vision] name' / '[LLM] name' / '[Embed] name', and workflows saved
    against the retired promptor carry the same prefixes; placeholder values
    ('[Offline] ...', 'Querying ...') mean 'pick one for me'."""
    text = (model or "").strip()
    low = text.lower()
    if not text or any(low.startswith(b) for b in _MODEL_BAD):
        return ""
    if text.startswith("[") and "]" in text:
        text = text.split("]", 1)[1].strip()
    return text


def _tensor_to_png_b64(image, index: int = 0) -> str:
    """One IMAGE frame -> base64 PNG, downscaled. Vision endpoints charge by pixel
    and reject large payloads; the analyser only needs to see what is in shot."""
    from PIL import Image
    t = image[index] if image.dim() == 4 else image
    arr = (t.clamp(0, 1) * 255).to(torch.uint8).cpu().numpy()
    im = Image.fromarray(arr, "RGB" if arr.shape[-1] == 3 else "RGBA").convert("RGB")
    if max(im.size) > _MAX_SIDE:
        scale = _MAX_SIDE / max(im.size)
        im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _report(lines, fixed, findings) -> str:
    out = []
    if fixed:
        out.append("REPAIRED: " + "; ".join(fixed))
    if findings:
        out.append(f"{len(findings)} grammar issue(s) H3 will not forgive:")
        out += [f"  - {f}" for f in findings]
    else:
        out.append("Grammar check: clean.")
    return "\n".join(lines + out)


class CosmicH3Promptor:
    """Write a MiniMax-H3 prompt from an idea, then check it against H3's grammar."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "idea": ("STRING", {"multiline": True, "default": "",
                                    "tooltip": "What you want to see. A sentence is enough; "
                                               "the model expands it into the full H3 field "
                                               "structure."}),
                "task": (list(spec.TASK_ORDER), {"default": "Auto",
                         "tooltip": "Auto reads what is wired: nothing = T2VA, first_frame = "
                                    "I2VA, last_frame alone = L2VA, both = FL2VA."}),
                "seconds": ("FLOAT", {"default": 5.0, "min": 1.0, "max": 60.0, "step": 0.5,
                            "tooltip": "Target duration. Cut times are checked against it -- "
                                       "a shot that starts past the end is reported."}),
                "shots": ("INT", {"default": 1, "min": 1, "max": 12,
                          "tooltip": "How many shots to write. FL2VA prefers 1 so the model "
                                     "can interpolate between the two frames."}),
                "provider": (list(providers.PROVIDERS), {"default": "ollama",
                             "tooltip": "Where the writing model runs. ollama and lmstudio are "
                                        "local; the rest need a key."}),
                "model": ("STRING", {"default": "",
                          "tooltip": "Model name as the provider reports it. Leave blank and "
                                     "the node picks the first one it finds."}),
            },
            "optional": {
                "style": (["(from the idea)"] + list(spec.STYLES), {"default": "(from the idea)",
                          "tooltip": "Forces one named look into the brief; the default lets the "
                                     "idea decide."}),
                "dialogue": ("BOOLEAN", {"default": True,
                             "tooltip": "OFF forbids <d> spoken lines entirely -- and the "
                                        "checker enforces it, so a chatty model cannot slip "
                                        "speech back in."}),
                "shot": (list(spec.SHOT_ORDER), {"default": spec.SHOT_NONE,
                         "tooltip": "Camera recipe folded into the brief; "
                                    + spec.shot_seconds_summary(0.5) + "."}),
                "vision_context": ("STRING", {"forceInput": True,
                                   "tooltip": "Output of the Vision Analyzer. Folded into the "
                                              "brief so the prompt matches the references."}),
                "endpoint": ("STRING", {"default": "",
                             "tooltip": "Override the provider's base URL. Blank uses the "
                                        "default (Ollama 11434, LM Studio 1234)."}),
                "api_key": ("STRING", {"default": "",
                            "tooltip": "Cloud providers only. Prefer the environment variable "
                                       "(OPENAI_API_KEY etc.) so keys never enter a workflow."}),
                "temperature": ("FLOAT", {"default": 0.7, "min": 0.0, "max": 2.0, "step": 0.05,
                                "tooltip": "Writing model's temperature. 0.7 varies wording; "
                                           "under 0.4 for repeatable prompts."}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFFFFFFFFFF,
                         "tooltip": "Sent to ollama, lmstudio, openai and gemini for repeatable "
                                    "output; anthropic has no seed, so it only re-runs."}),
                "first_frame": ("IMAGE", {"tooltip": "Opening frame. Alone it makes this I2VA."}),
                "last_frame": ("IMAGE", {"tooltip": "Frame to land on. Alone it is L2VA, with "
                                                    "first_frame it is FL2VA."}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("prompt", "report", "task")
    OUTPUT_TOOLTIPS = ("The H3 prompt, repaired where repair was unambiguous.",
                       "What was fixed, and every grammar issue left over.",
                       "The task type actually used -- useful when task was Auto.")
    FUNCTION = "build"
    CATEGORY = "H3 Studio/Prompt"
    DESCRIPTION = ("Writes a MiniMax-H3 prompt from a one-line idea, then checks it against "
                   "H3's grammar -- shot numbering, cut times, dialogue tags -- and repairs "
                   "what it can. The 14 shot recipes are decoded in the docs page "
                   "(docs/CosmicH3Promptor.md).")

    def build(self, idea, task, seconds, shots, provider, model,
              style="(from the idea)", dialogue=True, vision_context="",
              endpoint="", api_key="", temperature=0.7, seed=0,
              first_frame=None, last_frame=None, shot=spec.SHOT_NONE):
        if not idea.strip() and not vision_context.strip():
            raise ValueError("CosmicH3Promptor: 'idea' is empty and no vision_context is "
                             "connected -- there is nothing to write a prompt from.")

        n_images = (1 if first_frame is not None else 0) + (1 if last_frame is not None else 0)
        resolved = (spec.detect_task(n_images, last_frame is not None, reference_mode=False)
                    if task == "Auto" else task)

        chosen = _clean_model_name(model)
        if not chosen:
            found = providers.list_models(provider, endpoint, api_key)
            if not found:
                raise ValueError(
                    f"CosmicH3Promptor: no model given and {provider} reported none. "
                    f"Start it (Ollama/LM Studio) or set a key, or type a model name.")
            chosen = found[0]

        shot = shot if shot in spec.SHOTS else spec.SHOT_NONE
        sys_prompt = spec.system_prompt(
            resolved, seconds, shots,
            style="" if style == "(from the idea)" else style,
            dialogue=bool(dialogue), shot=shot)
        align = spec.alignment_line(resolved, shots, seconds)
        brief = idea.strip()
        if vision_context.strip():
            brief += "\n\nWhat the reference images show:\n" + vision_context.strip()
        if align:
            brief += ("\n\nBegin the output with exactly this line, then a blank line:\n"
                      + align)

        raw = providers.generate(provider, chosen, sys_prompt, brief,
                                 endpoint=endpoint, api_key=api_key,
                                 temperature=temperature, seed=int(seed))
        prompt, fixed = validate.repair(raw)
        findings = validate.check(prompt, seconds, resolved, expect_dialogue=bool(dialogue))
        header = [f"{resolved} | {provider}:{chosen} | {float(seconds):.2f}s | {shots} shot(s)"
                  + (f" | {shot}" if shot != spec.SHOT_NONE else "")]
        note = spec.shot_note(shot, seconds)
        if note:
            header.append(note)
        report = _report(header, fixed, findings)
        return {"ui": {"text": [prompt]},
                "result": (prompt, report, resolved)}


class CosmicH3VisionAnalyzer:
    """Describe reference images in the terms an H3 prompt needs."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "Reference frames; only the first max_frames "
                                                "are actually sent."}),
                "provider": (list(providers.PROVIDERS), {"default": "ollama",
                             "tooltip": "Must offer a vision model. ollama and lmstudio are "
                                        "local; the rest need a key."}),
                "model": ("STRING", {"default": "",
                          "tooltip": "A VISION model -- llava, qwen2-vl, gpt-4o, "
                                     "claude-*, gemini-*. A text-only model will fail here."}),
            },
            "optional": {
                "focus": (["everything", "subject identity", "wardrobe and props",
                           "lighting and style", "composition and camera",
                           FOCUS_EVENT_CHAIN],
                          {"default": "everything",
                           "tooltip": "everything: all aspects below\n"
                                      "subject identity: face, build, hair\n"
                                      "wardrobe and props: clothes, objects\n"
                                      "lighting and style: light, look\n"
                                      "composition and camera: framing\n"
                                      "event chain: trigger to reaction"}),
                "endpoint": ("STRING", {"default": "",
                             "tooltip": "Override the provider's base URL. Blank uses the "
                                        "default (Ollama 11434, LM Studio 1234)."}),
                "api_key": ("STRING", {"default": "",
                            "tooltip": "Cloud providers only. Prefer the environment variable "
                                       "so keys never enter a workflow."}),
                "max_frames": ("INT", {"default": 2, "min": 1, "max": 8,
                               "tooltip": "How many frames of a batch to look at. Each one "
                                          "costs a round trip and tokens."}),
                "evidence": ("STRING", {"forceInput": True,
                             "tooltip": "Video Forensics output; its timestamped picture and "
                                        "sound lines go to the model."}),
            },
        }

    RETURN_TYPES = ("STRING", "IMAGE")
    RETURN_NAMES = ("vision_context", "images")
    OUTPUT_TOOLTIPS = ("What the references show, written for an H3 prompt.",
                       "The images, passed through unchanged.")
    FUNCTION = "analyze"
    CATEGORY = "H3 Studio/Prompt"
    DESCRIPTION = ("Describes reference images in concrete terms -- subject, wardrobe, "
                   "lighting, framing -- for the Promptor's vision_context input. With the "
                   "event chain focus and Video Forensics evidence it reconstructs an existing "
                   "clip's timeline instead.")

    _FOCUS = {
        "everything": "subject identity, wardrobe, setting, lighting, style and composition",
        "subject identity": "who or what the subject is: age, build, hair, face, distinguishing marks",
        "wardrobe and props": "clothing, colours, materials, and every object the subject holds or wears",
        "lighting and style": "light direction, quality and colour, and the visual style or film stock",
        "composition and camera": "shot size, angle, framing, depth of field and where the subject sits",
    }

    def analyze(self, images, provider, model, focus="everything",
                endpoint="", api_key="", max_frames=2, evidence=""):
        if images is None or images.shape[0] == 0:
            raise ValueError("CosmicH3VisionAnalyzer: no images connected.")
        chosen = _clean_model_name(model)
        if not chosen:
            found = providers.list_models(provider, endpoint, api_key)
            if not found:
                raise ValueError(f"CosmicH3VisionAnalyzer: no model given and {provider} "
                                 "reported none. Name a vision model.")
            chosen = found[0]

        n = max(1, min(int(max_frames), int(images.shape[0])))
        shots = [_tensor_to_png_b64(images, i) for i in range(n)]
        sys_prompt, user = self.messages(focus, n, evidence)
        text = _generate_vision(provider, chosen, sys_prompt, user, shots, endpoint, api_key)
        return (text.strip(), images)

    @classmethod
    def messages(cls, focus, n, evidence=""):
        """The system and user text for one focus. Split out so tests can read what the
        model is told without a model."""
        evidence = (evidence or "").strip()
        several = f"these {n} images" if n > 1 else "this image"
        if focus == FOCUS_EVENT_CHAIN:
            sys_prompt = (
                "You reconstruct what happened in an existing video clip from a timestamped "
                "contact sheet and measured evidence, so it can be re-described as a "
                "video-generation prompt. Write the event chain as trigger -> action -> "
                "reaction, in time order, each step with its mm:ss.mmm time taken from the "
                "frame labels or the evidence lines. Use only what is visible in the frames "
                "or listed in the evidence: no invented backstory, no motives, no off-screen "
                "events. Every hard cut, freeze, flash and black frame in the evidence must "
                "appear at its time, and every listed audio peak must be accounted for by something seen "
                "at or just before that time, or reported as unexplained. Name the sound "
                "verdict (music or field sound) once. Write flat prose, no lists, no "
                "headings.")
            user = (f"Reconstruct the event chain of the clip shown in {several} for a "
                    "MiniMax-H3 prompt, in the order things happen and with their times.")
            if evidence:
                user += "\n\nMeasured evidence for the same clip:\n" + evidence
            else:
                user += ("\n\nNo measured evidence was supplied; take the times from the "
                         "frame labels only and say so.")
            return sys_prompt, user

        sys_prompt = (
            "You describe reference images for a video-generation prompt. Report only what "
            "is visibly there, in concrete physical terms -- no mood words, no interpretation, "
            "no guessing at story. Write flat prose, no lists, no headings. "
            f"Concentrate on {cls._FOCUS.get(focus, cls._FOCUS['everything'])}.")
        user = (f"Describe {several} for a MiniMax-H3 prompt. If there are several, say what "
                "stays the same across them and what changes.")
        if evidence:
            user += ("\n\nMeasured evidence for the clip these frames come from (mention a "
                     "cut, freeze, flash or black frame only if it changes what the frames "
                     "show):\n"
                     + evidence)
        return sys_prompt, user


class CosmicH3VideoForensics:
    """Measure what a clip did (cuts, freezes, flashes, black frames, sound) so a
    prompt can be written from evidence rather than from a vision model's guess."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "Every frame of the clip, in order; a video "
                                                "loader's IMAGE output."}),
                "fps": ("FLOAT", {"default": 24.0, "min": 1.0, "max": 240.0, "step": 0.001,
                        "tooltip": "The clip's frame rate, so frame numbers become "
                                   "timestamps; take it from the loader."}),
            },
            "optional": {
                "audio": ("AUDIO", {"tooltip": "The clip's track; adds level peaks, band "
                                               "energy and a music-or-field verdict."}),
            },
        }

    RETURN_TYPES = ("STRING", "IMAGE")
    RETURN_NAMES = ("evidence", "contact_sheet")
    OUTPUT_TOOLTIPS = ("Timestamped LIVE ACTION and SOUND lines for the Vision Analyzer's "
                       "evidence input.",
                       "Up to 16 evenly spaced, labelled frames in one grid; the Vision "
                       "Analyzer's image.")
    FUNCTION = "measure"
    CATEGORY = "H3 Studio/Prompt"
    DESCRIPTION = ("Finds hard cuts, freezes, flashes and black frames in a frame batch and "
                   "level peaks, band energy and a music-or-field verdict in its audio, all "
                   "timestamped, plus a 16-frame contact sheet. CPU only, 16 frames at a "
                   "time; wire evidence and sheet into the Vision Analyzer's event chain focus.")

    def measure(self, images, fps=24.0, audio=None):
        if images is None or images.dim() != 4 or images.shape[0] == 0:
            raise ValueError("CosmicH3VideoForensics: 'images' must be a non-empty IMAGE batch.")
        evidence, sheet = forensics.run(images, float(fps), audio)
        return (evidence, sheet)


def _generate_vision(provider, model, system, user, images_b64, endpoint, api_key):
    """Vision calls differ enough between vendors to be worth their own branch."""
    base = (endpoint or providers.DEFAULT_ENDPOINTS.get(provider, "")).rstrip("/")
    if provider in ("ollama", "lmstudio", "openai"):
        content = [{"type": "text", "text": user}] + [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b}"}}
            for b in images_b64]
        headers = {}
        if provider == "openai":
            k = providers._key("openai", api_key)
            if not k:
                raise providers.ProviderError("no OpenAI key for the vision call")
            headers = {"Authorization": f"Bearer {k}"}
        data = providers._post(f"{base}/v1/chat/completions", {
            "model": model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": content}],
            "max_tokens": 1024, "stream": False,
        }, headers)
        return data["choices"][0]["message"]["content"]

    if provider == "anthropic":
        k = providers._key("anthropic", api_key)
        if not k:
            raise providers.ProviderError("no Anthropic key for the vision call")
        content = [{"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                "data": b}} for b in images_b64]
        content.append({"type": "text", "text": user})
        data = providers._post(f"{base}/v1/messages", {
            "model": model, "system": system, "max_tokens": 1024,
            "messages": [{"role": "user", "content": content}],
        }, {"x-api-key": k, "anthropic-version": "2023-06-01"})
        return "".join(b.get("text", "") for b in data.get("content", []))

    if provider == "gemini":
        k = providers._key("gemini", api_key)
        if not k:
            raise providers.ProviderError("no Gemini key for the vision call")
        parts = [{"inline_data": {"mime_type": "image/png", "data": b}} for b in images_b64]
        parts.append({"text": user})
        data = providers._post(f"{base}/v1beta/models/{model}:generateContent?key={k}", {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": parts}],
        }, {})
        return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])

    raise providers.ProviderError(f"unknown provider {provider!r}")


# Mappings live here too so this file still registers correctly if it is ever
# loaded flat (spec_from_file_location); the package __init__ re-exports them.
NODE_CLASS_MAPPINGS = {
    "CosmicH3Promptor": CosmicH3Promptor,
    "CosmicH3VisionAnalyzer": CosmicH3VisionAnalyzer,
    "CosmicH3VideoForensics": CosmicH3VideoForensics,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "CosmicH3Promptor": "Cosmic MiniMax-H3 Promptor",
    "CosmicH3VisionAnalyzer": "Cosmic MiniMax-H3 Vision Analyzer",
    "CosmicH3VideoForensics": "Cosmic MiniMax-H3 Video Forensics",
}
