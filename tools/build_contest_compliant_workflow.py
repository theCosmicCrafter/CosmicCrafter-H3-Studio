"""Contest-compliant beat reactor: H3 writes the score, the visuals react to it.

The constraint and the way out
------------------------------
The challenge asks for "H3-generated synced audio", so an imported track is out.
But you cannot react to audio that does not exist yet - which looks like a
deadlock until you notice H3 makes both streams *at once*.

    Pass 1  H3 denoises audio and video jointly from the prompt.
            Decode the audio latent -> this IS the H3-generated score.

    Pass 2  Analyse THAT audio, drive the reactive elements from it, and
            re-render the video with `audio_mode: preserve` so the score
            carries through bit-exact.

So the output ships H3's own audio with visuals genuinely locked to it, and the
two-pass shape is also what the contest scores as "multiple linked passes
visible in the workflow structure".

Making H3's audio actually drivable
-----------------------------------
This is the part that decides whether any of it works.  A prompt asking for
"soothing sub-bass rumble, ambient harmonies" makes H3 generate a *pad* - no
transients, so beat detection finds nothing and every downstream reaction sits
flat.  :data:`PROMPT` therefore names **percussive** sound explicitly: sonar
pings on a pulse, concussive booms, clicks.  Ambient texture is still there, but
it is no longer the only thing in the mix.

Run from the repo root::

    python tools/build_contest_compliant_workflow.py
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_underwater_contest_workflow import Graph, load_schema, validate  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "workflows"

START_FRAME = "SolAttn_H3_00005.png"

FPS = 24
FRAMES = 124
#: 672x384, deliberately.  1344x768 x 124 frames x two passes killed the server
#: outright: no traceback, no OOM line, the process just vanished during the
#: VAE decode - an OS-level kill on RAM.  Prove the chain here, then scale.
WIDTH, HEIGHT = 672, 384

#: Percussive on purpose - see the module docstring.  The transients are what
#: the whole reactive chain feeds on.
PROMPT = (
    "Cinematic, hyper-detailed 8K macro-wide view inside a subterranean ocean "
    "abyss. The camera pushes slowly through a field of millions of floating "
    "bioluminescent micro-plankton glowing in soft cyan. A colossal "
    "cyber-organic leviathan whale glides forward from the dark indigo void, "
    "its skin patterned with turquoise and violet neural bioluminescence "
    "channels. On every low pulse the light channels across its throat and "
    "ventral pleats flare hard and volumetric turquoise beams stab through the "
    "water; delicate glass jellyfish flash in counterpoint and pressure rings "
    "ripple outward.\n\n"
    "Audio: a slow, heavy percussive pulse - deep concussive sub-bass booms on "
    "a steady beat, sharp metallic sonar pings echoing between them, sudden "
    "transient clicks and hits, over a bed of resonant whale song and ocean "
    "rumble. Rhythmic and punchy, with clear silence between each strike."
)


def build(schema):
    g = Graph(schema)

    g.note((-2600, -900), (
        "# Contest-compliant beat reactor\n\n"
        "**H3 writes the score.** There is no `LoadAudio` in this graph - the "
        "soundtrack is decoded out of H3's own audio latent, which is what "
        "*'H3-generated synced audio'* asks for.\n\n"
        "The apparent deadlock (you cannot react to audio that does not exist "
        "yet) is resolved by the two passes: H3 makes both streams at once in "
        "pass 1, then pass 2 reacts to what it made.\n\n"
        "The prompt names **percussive** sound on purpose. Ask for 'soothing "
        "ambient rumble' and H3 writes a pad with no transients, beat "
        "detection finds nothing, and every reaction downstream sits flat."
    ), size=(470, 340), title="README - read this first")

    # ---------------- model stack ----------------
    unet = g.add("UNETLoader", (-2600, -520),
                 {"unet_name": "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
                  "weight_dtype": "default"}, size=[420, 82], title="H3 fl2va")
    sol = g.add("SolAttnPatch", (-2600, -390), {
        "tau": 1.0, "start_percent": 0.2, "end_percent": 0.9, "min_tokens": 4096,
        "int8_qk": True, "sink_conditioning": "exact_kv_and_rows", "morton": False,
        "morton_curve": "2d_frame", "int8_pv": True, "verbose": False,
        "use_tma": False, "dense_blocks": "", "tau_profile": "",
    }, links={"model": (unet, 0)}, size=[420, 330], title="Sol-Attn 20-90%")
    shift = g.add("MiniMaxH3SigmaShift", (-2600, 0),
                  {"shift_video": 12.0, "shift_audio": 3.0},
                  links={"model": (sol, 0)}, size=[420, 82], title="Sigma 12 / 3")

    clip = g.add("CLIPLoader", (-2600, 130),
                 {"clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
                  "type": "minimax", "device": "default"}, size=[420, 106])
    vvae = g.add("VAELoader", (-2600, 280),
                 {"vae_name": "minimax_h3_video_vae_fp16.safetensors"},
                 size=[420, 58], title="Video VAE")
    avae = g.add("VAELoader", (-2600, 360),
                 {"vae_name": "minimax_h3_audio_vae_fp32.safetensors"},
                 size=[420, 58], title="Audio VAE")
    timing = g.add("CosmicCrafterVideoTiming", (-2600, 450),
                   {"frame_rate": float(FPS), "seconds": 0.0, "frames": FRAMES},
                   size=[420, 106], title="Timing hub")
    image = g.add("LoadImage", (-2600, 600), {"image": START_FRAME},
                  size=[420, 340], title="Whale start frame")

    # ---------------- pass 1: H3 writes picture AND score ----------------
    i2v = g.add("MiniMaxH3ImageToVideo", (-2120, -520),
                {"prompt": PROMPT, "width": WIDTH, "height": HEIGHT},
                links={"clip": (clip, 0), "vae": (vvae, 0),
                       "length": (timing, 2), "first_frame": (image, 0)},
                size=[460, 460], title="fl2va - percussive prompt")
    neg = g.add("ConditioningZeroOut", (-2120, 0), {},
                links={"conditioning": (i2v, 0)}, size=[300, 46])

    ks1 = g.add("KSampler", (-1620, -520), {
        "seed": 262780983686272, "steps": 30, "cfg": 5.0,
        "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0,
    }, links={"model": (shift, 0), "positive": (i2v, 0), "negative": (neg, 0),
              "latent_image": (i2v, 1)}, size=[340, 280], title="Pass 1")

    sep1 = g.add("LTXVSeparateAVLatent", (-1240, -520), {},
                 links={"av_latent": (ks1, 0)}, size=[300, 66])
    audio = g.add("VAEDecodeAudio", (-1240, -410), {},
                  links={"samples": (sep1, 1), "vae": (avae, 0)},
                  size=[300, 46], title="H3-GENERATED SCORE")
    frames1 = g.add("VAEDecode", (-1240, -320), {},
                    links={"samples": (sep1, 0), "vae": (vvae, 0)},
                    size=[300, 46], title="Pass 1 frames")
    g.add("PreviewAudio", (-1240, -230), {}, links={"audio": (audio, 0)},
          size=[300, 100], title="Listen before committing")

    # ---------------- beat brain, off H3's own score ----------------
    g.note((-760, -900), (
        "## Beat brain - reading what H3 just wrote\n\n"
        "`beat_locations` finds downbeats; `PeakDetector` isolates strikes; "
        "`Smoothing` (exponential, 0.40) gives each a ring-out so the "
        "bioluminescence swells rather than strobing on one frame.\n\n"
        "**Check the PreviewFeature plots.** If they are flat, H3 wrote a pad "
        "and no amount of downstream tuning will help - go back and make the "
        "prompt's audio line more percussive."
    ), size=(440, 280), title="Beat brain")

    beat_raw = g.add("RhythmFeatureExtractor", (-760, -520), {
        "extraction_method": "beat_locations", "frame_rate": float(FPS),
        "frame_count": FRAMES, "width": WIDTH, "height": HEIGHT,
        "time_signature": 4,
    }, links={"audio": (audio, 0)}, size=[340, 190], title="Downbeats")
    peaks = g.add("FeaturePeakDetector", (-760, -290), {
        "prominence": 0.06, "distance": 4, "width": 1, "plateau_size": 1,
        "detect_valleys": False, "invert_output": False,
    }, links={"feature": (beat_raw, 0)}, size=[340, 190], title="Strikes")
    ring = g.add("FeatureSmoothing", (-760, -60), {
        "smoothing_type": "exponential", "window_size": 5, "alpha": 0.40,
        "sigma": 1.0, "invert_output": False,
    }, links={"feature": (peaks, 0)}, size=[340, 170], title="Ring-out")
    beat = g.add("FeatureScaler", (-760, 150), {
        "scale_type": "exponential", "min_output": 0.08, "max_output": 1.0,
        "exponent": 1.7, "invert_output": False,
    }, links={"feature": (ring, 0)}, size=[340, 170], title="BEAT ENVELOPE")
    g.add("PreviewFeature", (-380, 150), {}, links={"feature": (beat, 0)},
          size=[300, 210], title="Beat plot")

    # ---------------- mask emitter -> particles ----------------
    g.note((-380, -900), (
        "## Mask Emitter -> particle sim\n\n"
        "Ryan's particle sim takes its length from whatever MASK it is handed "
        "(`num_frames = masks.shape[0]`). Hand it a `LoadImage` and the entire "
        "simulation collapses to **one frame**, silently, and the audio "
        "modulation feeding it is computed and thrown away.\n\n"
        "`H3 Mask Emitter` is the seed: it emits a batch of a known length, and "
        "with a `latent` connected it takes the count straight from the clip, "
        "so the two can never drift apart."
    ), size=(440, 300), title="Mask emitter")

    emitter_mask = g.add("MiniMaxH3MaskEmitter", (-380, -520), {
        "frames": FRAMES, "width": WIDTH, "height": HEIGHT, "shape": "solid",
        "coverage": 1.0, "softness": 0.35, "ring_width": 0.25,
    }, links={"latent": (ks1, 0)}, size=[340, 300],
        title="Mask Emitter (length from the latent)")

    rate = g.add("EmitterEmissionRateModulation", (-380, -180), {
        "start_frame": 0, "end_frame": 0, "effect_duration": 0,
        "temporal_easing": "linear", "palindrome": False, "random": False,
        "target_emission_rate": 95.0,   # catalog max is 100
    }, links={"feature": (beat, 0)}, size=[340, 230],
        title="Beat -> emission rate")

    emitter = g.add("ParticleEmitter", (60, -520), {
        "emitter_x": 0.5, "emitter_y": 0.5, "particle_direction": 0.0,
        "particle_spread": 360.0, "particle_size": 9.0, "particle_speed": 260.0,
        "emission_rate": 25.0, "color": "(180,240,255)", "initial_plume": 0.1,
        "start_frame": 0, "end_frame": 0, "emission_radius": 0.06,
    }, links={"emitter_modulation": (rate, 0)}, size=[340, 380],
        title="Emitter at the whale (0.5, 0.5)")

    particles = g.add("ParticleEmissionMask", (60, -110), {
        "strength": 1.0, "invert": False, "subtract_original": 0.0,
        "grow_with_blur": 0.0, "particle_count": 600, "particle_lifetime": 2.2,
        "wind_strength": 0.0, "wind_direction": 0.0, "gravity": 0.0,
        "warmup_period": 0, "start_frame": 0, "end_frame": 0,
        "respect_mask_boundary": False, "emission_strength": 1.0,
    }, links={"masks": (emitter_mask, 0), "emitters": (emitter, 0)},
        size=[340, 380], title="Particles off the whale")

    # ---------------- latent reaction ----------------
    combined = g.add("MiniMaxH3MaskComposite", (460, -520), {
        "operation": "screen", "invert_a": False, "invert_b": False,
        "gain": 1.0, "offset": 0.0, "feather": 8, "invert_result": False,
    }, links={"mask_a": (particles, 0), "mask_b": (emitter_mask, 0)},
        size=[340, 230], title="Particles + emitter field")

    src = g.add("MiniMaxH3SourceToLatent", (460, -260), {"crop": "center"},
                links={"samples": (ks1, 0), "vae": (vvae, 0), "image": (frames1, 0)},
                size=[340, 106], title="Pass 1 video -> latent")
    nmask = g.add("MiniMaxH3LatentNoiseMask", (460, -120), {
        "strength": 0.85, "temporal_aggregate": "max",
        "audio_mode": "preserve", "token_grid": 2,
    }, links={"samples": (src, 0), "mask": (combined, 0)},
        size=[340, 160], title="preserve = H3's score kept bit-exact")
    dd = g.add("DifferentialDiffusion", (460, 80), {"strength": 1.0},
               links={"model": (shift, 0)}, size=[340, 58])

    analyze = g.add("MiniMaxH3AudioAnalyze", (460, 170), {
        "clip_start_seconds": 0.0, "beat_decay": 0.18, "sensitivity": 1.4,
    }, links={"audio": (audio, 0), "clip_frames": (timing, 2)},
        size=[340, 190], title="Bass extractor")
    denoise = g.add("MiniMaxH3AudioReactiveDenoise", (460, 400), {
        "mode": "peak", "min_strength": 0.30, "max_strength": 0.58,
        "invert": False,
    }, links={"curve": (analyze, 4)}, size=[340, 150], title="Bass -> denoise")

    guider = g.add("BasicGuider", (860, -520), {},
                   links={"model": (dd, 0), "conditioning": (i2v, 0)}, size=[300, 46])
    sel = g.add("KSamplerSelect", (860, -440), {"sampler_name": "euler"}, size=[300, 58])
    sched = g.add("BasicScheduler", (860, -350), {"scheduler": "simple", "steps": 30},
                  links={"model": (shift, 0), "denoise": (denoise, 0)}, size=[300, 106])
    noise = g.add("RandomNoise", (860, -210), {"noise_seed": 811247}, size=[300, 82])

    ks2 = g.add("SamplerCustomAdvanced", (1220, -520), {},
                links={"noise": (noise, 0), "guider": (guider, 0), "sampler": (sel, 0),
                       "sigmas": (sched, 0), "latent_image": (nmask, 0)},
                size=[300, 130], title="Pass 2")
    sep2 = g.add("LTXVSeparateAVLatent", (1560, -520), {},
                 links={"av_latent": (ks2, 0)}, size=[300, 66])
    frames2 = g.add("VAEDecode", (1560, -410), {},
                    links={"samples": (sep2, 0), "vae": (vvae, 0)},
                    size=[300, 46], title="Final frames")

    bloom = g.add("FlexImageBloom", (1560, -320), {
        "strength": 0.95, "feature_threshold": 0.0, "feature_param": "intensity",
        "feature_mode": "relative", "threshold": 0.55, "blur_amount": 16.0,
        "intensity": 0.5, "num_passes": 4, "color_bleeding": 0.4, "falloff": 1.15,
    }, links={"images": (frames2, 0), "opt_feature": (beat, 0)},
        size=[340, 300], title="Bloom <- beat")
    aberr = g.add("FlexImageChromaticAberration", (1560, 10), {
        "strength": 1.0, "feature_threshold": 0.0, "feature_param": "shift_amount",
        "feature_mode": "relative", "shift_amount": 0.003, "angle": 0.0,
    }, links={"images": (bloom, 0), "opt_feature": (beat, 0)},
        size=[340, 190], title="RGB kick <- beat")

    g.add("VHS_VideoCombine", (1960, -520), {
        "loop_count": 0, "filename_prefix": "H3_Contest_BeatReactor",
        "format": "video/h264-mp4", "pingpong": False, "save_output": True,
    }, links={"images": (aberr, 0), "audio": (audio, 0),
              "frame_rate": (timing, 0)},
        size=[420, 520], title="Final - H3's own audio")

    return g.to_dict("H3 Contest Beat Reactor")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the contest-compliant reactor.")
    ap.add_argument("--install-to", default=None)
    ap.add_argument("--no-install", action="store_true")
    args = ap.parse_args(argv)

    graph = build(load_schema())
    problems = validate(graph)
    if problems:
        raise SystemExit("validation failed:\n  " + "\n  ".join(problems))

    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / "H3_Contest_BeatReactor.json"
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
