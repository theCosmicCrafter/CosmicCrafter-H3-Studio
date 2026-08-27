"""TouchDesigner-style beat-reactive H3 workflow.

The shape is TD's: **sources -> modulators -> targets**, except the source is
H3's own generated audio and one of the targets is H3's own latent.

    RhythmFeatureExtractor ─┐
    AudioFeatureExtractor  ─┴─> PeakDetector -> Smoothing -> Scaler   (CHOP math)
                                        │
                    ┌───────────────────┼────────────────────┐
                    ▼                   ▼                    ▼
             FeatureToMask       FlexImage* targets    denoise schedule
                    │             (bloom / RGB split /
                    ▼              kaleidoscope / glitch)
        MiniMaxH3LatentNoiseMask
        (beat drives the LATENT, not just the pixels)

Why this is not just a filter stack
-----------------------------------
Two reaction domains run off the *same* feature graph:

* **Latent domain** - the beat envelope becomes an H3-shaped noise mask, so the
  model re-generates geometry on the hit.  Objects genuinely change, they are
  not warped pixels.
* **Image domain** - Ryan's Flex targets bind the same features to bloom,
  chromatic aberration, kaleidoscope and glitch parameters, which is the
  material/look layer.

Both are driven by audio **H3 generated itself**, so the sync is inherent rather
than a track laid alongside.

Run from the repo root::

    python tools/build_td_beat_workflow.py
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_underwater_contest_workflow import (  # noqa: E402
    Graph, load_schema, validate, PROMPT, WIDTH, HEIGHT, FPS, FRAMES,
)

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "workflows"


def build(schema):
    g = Graph(schema)

    # ---------------- Section 1: H3 generates the AV -----------------------
    g.note((-2600, -820), (
        "# TouchDesigner-style beat reactor for H3\n\n"
        "**Sources -> modulators -> targets**, with H3's own audio as the "
        "source and H3's own latent as one of the targets.\n\n"
        "Nothing here is a track laid alongside the video: pass 1 generates the "
        "picture and the score together (H3 packs `[text | cond | audio | video]` "
        "into one attended sequence), then everything downstream reacts to that "
        "exact audio."
    ), size=(460, 300), title="README")

    unet = g.add("UNETLoader", (-2600, -470),
                 {"unet_name": "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
                  "weight_dtype": "default"}, size=[420, 82], title="H3 fl2va")
    sol = g.add("SolAttnPatch", (-2600, -340), {
        "tau": 1.0, "start_percent": 0.2, "end_percent": 0.9, "min_tokens": 4096,
        "int8_qk": True, "sink_conditioning": "exact_kv_and_rows", "morton": False,
        "morton_curve": "2d_frame", "int8_pv": True, "verbose": False,
        "use_tma": False, "dense_blocks": "", "tau_profile": "",
    }, links={"model": (unet, 0)}, size=[420, 330], title="Sol-Attn 20-90%")
    shift = g.add("MiniMaxH3SigmaShift", (-2600, 50),
                  {"shift_video": 12.0, "shift_audio": 3.0},
                  links={"model": (sol, 0)}, size=[420, 82],
                  title="Sigma shift 12 / 3")

    clip = g.add("CLIPLoader", (-2600, 180),
                 {"clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
                  "type": "minimax", "device": "default"}, size=[420, 106])
    vvae = g.add("VAELoader", (-2600, 330),
                 {"vae_name": "minimax_h3_video_vae_fp16.safetensors"},
                 size=[420, 58], title="Video VAE")
    avae = g.add("VAELoader", (-2600, 410),
                 {"vae_name": "minimax_h3_audio_vae_fp32.safetensors"},
                 size=[420, 58], title="Audio VAE")
    timing = g.add("CosmicCrafterVideoTiming", (-2600, 500),
                   {"frame_rate": float(FPS), "seconds": 0.0, "frames": FRAMES},
                   size=[420, 106], title="Timing hub")

    i2v = g.add("MiniMaxH3ImageToVideo", (-2120, -470),
                {"prompt": PROMPT, "width": WIDTH, "height": HEIGHT},
                links={"clip": (clip, 0), "vae": (vvae, 0), "length": (timing, 2)},
                size=[460, 420], title="T2V - abyss + whale song")
    neg = g.add("ConditioningZeroOut", (-2120, 50), {},
                links={"conditioning": (i2v, 0)}, size=[300, 46])

    ks1 = g.add("KSampler", (-1600, -470), {
        "seed": 262780983686272, "steps": 30, "cfg": 5.0,
        "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0,
    }, links={"model": (shift, 0), "positive": (i2v, 0), "negative": (neg, 0),
              "latent_image": (i2v, 1)}, size=[340, 280], title="Pass 1")

    sep1 = g.add("LTXVSeparateAVLatent", (-1220, -470), {},
                 links={"av_latent": (ks1, 0)}, size=[300, 66])
    audio = g.add("VAEDecodeAudio", (-1220, -360), {},
                  links={"samples": (sep1, 1), "vae": (avae, 0)},
                  size=[300, 46], title="H3-GENERATED AUDIO")
    frames1 = g.add("VAEDecode", (-1220, -270), {},
                    links={"samples": (sep1, 0), "vae": (vvae, 0)},
                    size=[300, 46], title="Pass 1 frames")

    # ---------------- Section 2: the beat brain ----------------------------
    g.note((-1220, -150), (
        "## The beat brain (sources -> CHOP math)\n\n"
        "`RhythmFeatureExtractor` on **beat_locations** gives discrete downbeats "
        "rather than a loudness wobble.\n\n"
        "`PeakDetector` isolates the hits, `Smoothing` (exponential, alpha 0.35) "
        "gives each one a decay tail so objects *ring out* instead of strobing, "
        "and `Scaler` maps it to the working range.\n\n"
        "`rms_energy` runs in parallel as a slow macro for the section-level "
        "moves. Both `PreviewFeature` nodes plot the curve - check those before "
        "committing to a long render."
    ), size=(440, 330), title="Beat brain")

    beat_raw = g.add("RhythmFeatureExtractor", (-720, -470), {
        "extraction_method": "beat_locations", "frame_rate": float(FPS),
        "frame_count": FRAMES, "width": WIDTH, "height": HEIGHT,
        "time_signature": 4,
    }, links={"audio": (audio, 0)}, size=[340, 190], title="Beats (downbeats)")

    peaks = g.add("FeaturePeakDetector", (-720, -240), {
        "prominence": 0.12, "distance": 6, "width": 1, "plateau_size": 1,
        "detect_valleys": False, "invert_output": False,
    }, links={"feature": (beat_raw, 0)}, size=[340, 190], title="Isolate hits")

    # alpha 0.35 = a ~3-frame ring-out at 24fps: long enough to read as a
    # material response, short enough to stay locked to the grid.
    ring = g.add("FeatureSmoothing", (-720, -10), {
        "smoothing_type": "exponential", "window_size": 5, "alpha": 0.35,
        "sigma": 1.0, "invert_output": False,
    }, links={"feature": (peaks, 0)}, size=[340, 170], title="Ring-out tail")

    beat = g.add("FeatureScaler", (-720, 200), {
        "scale_type": "exponential", "min_output": 0.05, "max_output": 1.0,
        "exponent": 1.8, "invert_output": False,
    }, links={"feature": (ring, 0)}, size=[340, 170], title="BEAT ENVELOPE")

    energy_raw = g.add("AudioFeatureExtractor", (-720, 410), {
        "extraction_method": "rms_energy", "frame_rate": float(FPS),
        "frame_count": FRAMES, "width": WIDTH, "height": HEIGHT,
    }, links={"audio": (audio, 0)}, size=[340, 170], title="Energy (macro)")

    energy = g.add("FeatureSmoothing", (-720, 610), {
        "smoothing_type": "gaussian", "window_size": 15, "alpha": 0.3,
        "sigma": 4.0, "invert_output": False,
    }, links={"feature": (energy_raw, 0)}, size=[340, 170], title="ENERGY MACRO")

    g.add("PreviewFeature", (-340, 200), {}, links={"feature": (beat, 0)},
          size=[300, 220], title="Beat curve")
    g.add("PreviewFeature", (-340, 450), {}, links={"feature": (energy, 0)},
          size=[300, 220], title="Energy curve")

    # ---------------- Section 3: latent-domain reaction --------------------
    g.note((-340, -470), (
        "## Latent domain - the beat rebuilds geometry\n\n"
        "`FeatureToMask` turns the beat envelope into an animated mask; "
        "`H3 Latent Noise Mask` writes it at the latent's **exact** shape and "
        "aggregates per latent frame (H3 packs 1,4,4,4,4 source frames per 5 "
        "tokens), so a one-frame hit survives instead of being interpolated "
        "away.\n\n"
        "`audio_mode: preserve` carries the score through untouched.\n\n"
        "This is the part a filter stack cannot do: on the hit the **model** "
        "re-generates, so objects and materials actually change."
    ), size=(440, 320), title="Latent reaction")

    beat_mask = g.add("FeatureToMask", (-340, -130), {},
                      links={"feature": (beat, 0)}, size=[300, 46],
                      title="Beat -> mask")

    src = g.add("MiniMaxH3SourceToLatent", (100, -470), {"crop": "center"},
                links={"samples": (ks1, 0), "vae": (vvae, 0), "image": (frames1, 0)},
                size=[340, 106], title="Pass 1 video -> latent")

    nmask = g.add("MiniMaxH3LatentNoiseMask", (100, -330), {
        "strength": 0.9, "temporal_aggregate": "max",
        "audio_mode": "preserve", "token_grid": 2,
    }, links={"samples": (src, 0), "mask": (beat_mask, 0)},
        size=[340, 160], title="Beat -> H3 latent mask")

    dd = g.add("DifferentialDiffusion", (100, -130), {"strength": 1.0},
               links={"model": (shift, 0)}, size=[340, 58],
               title="Graded mask -> denoise schedule")

    analyze = g.add("MiniMaxH3AudioAnalyze", (100, -40), {
        "clip_start_seconds": 0.0, "beat_decay": 0.22, "sensitivity": 1.3,
    }, links={"audio": (audio, 0), "clip_frames": (timing, 2)},
        size=[340, 190], title="Denoise driver")

    denoise = g.add("MiniMaxH3AudioReactiveDenoise", (100, 190), {
        "mode": "peak", "min_strength": 0.32, "max_strength": 0.60,
        "invert": False,
    }, links={"curve": (analyze, 4)}, size=[340, 150], title="Bass -> denoise")

    guider = g.add("BasicGuider", (500, -470), {},
                   links={"model": (dd, 0), "conditioning": (i2v, 0)}, size=[300, 46])
    sel = g.add("KSamplerSelect", (500, -390), {"sampler_name": "euler"}, size=[300, 58])
    sched = g.add("BasicScheduler", (500, -300),
                  {"scheduler": "simple", "steps": 30},
                  links={"model": (shift, 0), "denoise": (denoise, 0)}, size=[300, 106])
    noise = g.add("RandomNoise", (500, -160), {"noise_seed": 811247}, size=[300, 82])

    ks2 = g.add("SamplerCustomAdvanced", (860, -470), {},
                links={"noise": (noise, 0), "guider": (guider, 0), "sampler": (sel, 0),
                       "sigmas": (sched, 0), "latent_image": (nmask, 0)},
                size=[300, 130], title="Pass 2 (beat-driven)")
    sep2 = g.add("LTXVSeparateAVLatent", (1200, -470), {},
                 links={"av_latent": (ks2, 0)}, size=[300, 66])
    frames2 = g.add("VAEDecode", (1200, -360), {},
                    links={"samples": (sep2, 0), "vae": (vvae, 0)},
                    size=[300, 46], title="Pass 2 frames")

    # ---------------- Section 4: image-domain TD look ----------------------
    g.note((1200, -250), (
        "## Image domain - the material layer\n\n"
        "Ryan's Flex targets bind a feature to **one named parameter** - that is "
        "TouchDesigner parameter-binding.\n\n"
        "- **Bloom** <- beat drives `intensity` (light swells on the hit)\n"
        "- **Chromatic aberration** <- beat drives `shift_amount` (RGB split)\n"
        "- **Kaleidoscope** <- energy drives `rotation` (slow section-level turn)\n"
        "- **Glitch** <- beat drives `intensity`, gated at 0.55 so only the "
        "hardest hits corrupt\n\n"
        "`feature_mode: relative` modulates around the base value; `strength` "
        "scales how far. Reorder freely - it is a stack."
    ), size=(440, 330), title="Material layer")

    bloom = g.add("FlexImageBloom", (1600, -470), {
        "strength": 0.85, "feature_threshold": 0.0, "feature_param": "intensity",
        "feature_mode": "relative", "threshold": 0.62, "blur_amount": 14.0,
        "intensity": 0.45, "num_passes": 4, "color_bleeding": 0.35, "falloff": 1.2,
    }, links={"images": (frames2, 0), "opt_feature": (beat, 0)},
        size=[340, 300], title="Bloom <- beat")

    aberr = g.add("FlexImageChromaticAberration", (1600, -140), {
        "strength": 1.0, "feature_threshold": 0.0, "feature_param": "shift_amount",
        "feature_mode": "relative", "shift_amount": 0.004, "angle": 0.0,
    }, links={"images": (bloom, 0), "opt_feature": (beat, 0)},
        size=[340, 190], title="RGB split <- beat")

    kaleido = g.add("FlexImageKaleidoscope", (1600, 90), {
        "strength": 0.35, "feature_threshold": 0.0, "feature_param": "rotation",
        "feature_mode": "relative", "segments": 6, "center_x": 0.5, "center_y": 0.5,
        "zoom": 1.0, "rotation": 0.0, "precession": 0.0, "speed": 1.0,
    }, links={"images": (aberr, 0), "opt_feature": (energy, 0)},
        size=[340, 280], title="Kaleidoscope <- energy")

    glitch = g.add("FlexImageGlitch", (1600, 410), {
        "strength": 0.7, "feature_threshold": 0.55, "feature_param": "intensity",
        "feature_mode": "relative", "glitch_type": "digital", "intensity": 0.18,
        "block_size": 24, "wave_amplitude": 0.1, "wave_frequency": 5.0,
        "corruption_amount": 0.08, "time_seed": 0,
    }, links={"images": (kaleido, 0), "opt_feature": (beat, 0)},
        size=[340, 300], title="Glitch <- hardest hits only")

    g.add("VHS_VideoCombine", (2000, -470), {
        "loop_count": 0, "filename_prefix": "H3_TD_BeatReactor",
        "format": "video/h264-mp4", "pingpong": False, "save_output": True,
    }, links={"images": (glitch, 0), "audio": (audio, 0),
              "frame_rate": (timing, 0)},
        size=[420, 520], title="Final (H3 audio)")

    return g.to_dict("H3 TouchDesigner Beat Reactor")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the TD-style beat reactor.")
    ap.add_argument("--install-to", default=None)
    ap.add_argument("--no-install", action="store_true")
    args = ap.parse_args(argv)

    graph = build(load_schema())
    problems = validate(graph)
    if problems:
        raise SystemExit("validation failed:\n  " + "\n  ".join(problems))

    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / "H3_TD_BeatReactor.json"
    out.write_text(json.dumps(graph, indent=2), encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)} "
          f"({len(graph['nodes'])} nodes, {len(graph['links'])} links)")

    if args.no_install:
        return out
    from build_audio_reactive_workflow import find_comfyui_workflows, INSTALL_SUBDIR
    target = find_comfyui_workflows(args.install_to)
    if target is None:
        print("ComfyUI workflow dir not found - skipping install")
        return out
    dest = target / INSTALL_SUBDIR
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(out, dest / out.name)
    print(f"installed to {dest / out.name}")
    return out


if __name__ == "__main__":
    main()
