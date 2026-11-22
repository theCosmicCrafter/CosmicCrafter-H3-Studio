"""Persistent RefForge image conversions for the opt-in FLF2VA path."""

import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading

import torch

from . import refmods

PROFILE = dict(mode="Compressed Reference", ref_resolution=1024, pool_h=48, pool_w=48,
               latent_frames=1, identity=0, multiplier=1, max_tokens=1536,
               concept_type="generic", merge=False, motion_only=False,
               extraction_preset="manual", budget_policy="error")
LOCK = threading.Lock()


def cached_image(pixels, vae):
    """Load the saved conversion, or encode/save it once; never retain tensors globally."""
    pack, _ = refmods.backend()
    init = getattr(vae.patcher, "cached_patcher_init", None)
    if not init:
        raise ValueError("H3 Timeline: cached RefMods need a file-backed H3 VAE; use VAELoader")
    checkpoint = Path(init[1][0]).resolve()
    stamp = checkpoint.stat()
    pixels = pixels[:1].detach().to(device="cpu", dtype=torch.float32).contiguous()
    content = hashlib.sha256(pixels.numpy().tobytes()).hexdigest()
    source = dict(version=1, image=content, shape=list(pixels.shape), profile=dict(PROFILE),
                  vae=dict(path=str(checkpoint), size=stamp.st_size, modified=stamp.st_mtime_ns,
                           dtype=str(vae.vae_dtype)),
                  extractor={name: hashlib.sha256(Path(pack.__file__).with_name(name).read_bytes()).hexdigest()
                             for name in (Path(pack.__file__).name, "core.py", "common.py")})
    key = hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()
    name = "image_" + key
    base = pack.mod_output_path(name, "h3c-frame-guides")
    file, receipt = Path(base + ".safetensors"), Path(base + ".cache.json")
    with LOCK:
        try:
            saved = json.loads(receipt.read_text(encoding="utf-8"))
            if (isinstance(saved, dict) and saved.get("source") == source
                    and saved.get("sha256") == hashlib.sha256(file.read_bytes()).hexdigest()):
                mod = pack.H3RefMod.load(base)
                if mod.kind == "image" and mod.latent_t == 1:
                    return mod, 1.0
        except (OSError, ValueError):
            # A failed/partial publication or deleted/edited cached file needs a fresh conversion.
            pass
        result = pack.MiniMaxH3RefModExtract.execute(name=name, refs_image={"ref_image_0": pixels},
                                                   vae=vae, save=False, description="", **PROFILE)
        mod, strength = result.args[0][0]
        mod.save(base)  # RefForge publishes safetensors atomically.
        mod.path = base
        saved = dict(source=source, sha256=hashlib.sha256(file.read_bytes()).hexdigest())
        fd, temporary = tempfile.mkstemp(prefix=".h3c-cache-", dir=receipt.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(saved, stream, sort_keys=True)
            os.replace(temporary, receipt)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return mod, strength


def prepare(clip, vae, images, refs, audios=(), audio_vae=None):
    """Present cached images in the compiler's order, then the box's raw audio, then already-selected RefMods.

    Raw audio needs no conversion: it becomes the same reference block native REF2VA builds for it."""
    _, prompt = refmods.backend()
    mods = [cached_image(image, vae) for image in images]
    items, blocks = refmods.prepare_references(prompt, mods + refmods.load(refs), vae)
    if audios:
        if audio_vae is None:
            raise ValueError("H3 Timeline: connect the H3 audio VAE to use audio references with FLF2VA")
        from comfy_extras import nodes_minimax_h3
        encoded = [nodes_minimax_h3._encode_ref_audio(audio_vae, audio) for audio in audios]
        # Cached images always have strength 1, so each has exactly one item and block ahead of the RefMods.
        items[len(mods):len(mods)] = [{"type": "audio"} for _ in encoded]
        blocks[len(mods):len(mods)] = [{"kind": "audio", "ref_audio_t": t, "audio_latent": z} for z, t in encoded]
    return refmods.ReferenceClip(clip, items), blocks
