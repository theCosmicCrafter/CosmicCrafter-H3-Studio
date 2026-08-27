"""Abyss whale, bass-reactive — built around the supplied start frame and track.

Assets
------
* Start frame: ``SolAttn_H3_00005.png`` (1344x768, whale centred) -> fl2va
  ``first_frame``, so the generation begins from the exact image.
* Track: ``Voltage Bow (Heavier 808 Bass).m4a``.  Measured over the first 124
  frames: bass mean 0.354, 26/124 frames above 0.5, only 3 above 0.8 - the 808
  hits are **discrete**, which is what the gate/threshold values below are set
  against.

"Activity coming off the whale"
------------------------------
The whale is centre-frame, so the reaction is **radial from centre**: the bass
curve drives a radial mask whose disc grows on each 808 hit, which means H3
re-generates outward from the whale rather than uniformly.  The bioluminescent
flare is the image-domain half - bloom bound to the beat envelope.

Audio routing
-------------
The real track is written into H3's audio latent by
``CosmicCrafterSongMaskedAVContext`` and protected, so H3 generates the video
*conditioned on the actual 808s* (video tokens attend to audio tokens in H3's
packed sequence) and the track plays back bit-exact.

NOTE: the contest asks for "H3-generated synced audio".  This graph syncs to a
supplied track instead.  ``--h3-audio`` builds the variant where H3 writes the
score itself, if that reading of the rule matters.

Run from the repo root::

    python tools/build_whale_beat_workflow.py
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
TRACK = "Voltage Bow (Heavier 808 Bass).m4a"

FPS = 24
FRAMES = 124                     # 5.2s; H3's grid is 17k+5, trained to ~362
WIDTH, HEIGHT = 1344, 768        # H3's native canvas, and the start frame's size

PROMPT = (
    "Cinematic, hyper-detailed 8K macro-wide view inside a subterranean ocean "
    "abyss. The camera pushes in with slow, steady amplitude through a field of "
    "millions of floating bioluminescent micro-plankton glowing in soft cyan. A "
    "colossal cyber-organic leviathan whale glides forward from the dark indigo "
    "void, its skin patterned with intricate turquoise and violet neural "
    "bioluminescence channels. As the whale emits a deep harmonic song, the "
    "light channels across its throat and ventral pleats flare with intense "
    "pulse-reactive brightness, casting volumetric turquoise light beams through "
    "the crystalline water. Delicate glass jellyfish flash in rhythmic "
    "counterpoint. Deep resonant whale vocalizations, soothing sub-bass ocean "
    "rumble, ambient crystal glass harmonies."
)


def build(schema, h3_audio=False):
    g = Graph(schema)
    seconds = FRAMES / FPS

    g.note((-2600, -880), (
        "# Abyss whale - bass reactive\n\n"
        "Start frame `SolAttn_H3_00005.png`, track "
        "`Voltage Bow (Heavier 808 Bass)`.\n\n"
        "**Whale is centre-frame, so the reaction is radial from centre.** The "
        "808 drives a growing disc, so H3 re-generates *outward from the whale* "
        "instead of uniformly - that is the 'activity coming off it'.\n\n"
        "Measured on this track's first 124 frames: bass mean 0.354, 26 frames "
        "over 0.5, 3 over 0.8. The hits are discrete, so the gates below are "
        "set low (0.06) and the ring-out carries them."
    ), size=(460, 330), title="README")

    # ---------------- model stack ----------------
    unet = g.add("UNETLoader", (-2600, -500),
                 {"unet_name": "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
                  "weight_dtype": "default"}, size=[420, 82], title="H3 fl2va")
    sol = g.add("SolAttnPatch", (-2600, -370), {
        "tau": 1.0, "start_percent": 0.2, "end_percent": 0.9, "min_tokens": 4096,
        "int8_qk": True, "sink_conditioning": "exact_kv_and_rows", "morton": False,
        "morton_curve": "2d_frame", "int8_pv": True, "verbose": False,
        "use_tma": False, "dense_blocks": "", "tau_profile": "",
    }, links={"model": (unet, 0)}, size=[420, 330], title="Sol-Attn 20-90%")
    shift = g.add("MiniMaxH3SigmaShift", (-2600, 20),
                  {"shift_video": 12.0, "shift_audio": 3.0},
                  links={"model": (sol, 0)}, size=[420, 82], title="Sigma 12 / 3")

    clip = g.add("CLIPLoader", (-2600, 150),
                 {"clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
                  "type": "minimax", "device": "default"}, size=[420, 106])
    vvae = g.add("VAELoader", (-2600, 300),
                 {"vae_name": "minimax_h3_video_vae_fp16.safetensors"},
                 size=[420, 58], title="Video VAE")
    avae = g.add("VAELoader", (-2600, 380),
                 {"vae_name": "minimax_h3_audio_vae_fp32.safetensors"},
                 size=[420, 58], title="Audio VAE")
    timing = g.add("CosmicCrafterVideoTiming", (-2600, 470),
                   {"frame_rate": float(FPS), "seconds": 0.0, "frames": FRAMES},
                   size=[420, 106], title="Timing hub")

    # ---------------- assets ----------------
    image = g.add("LoadImage", (-2600, 620), {"image": START_FRAME},
                  size=[420, 340], title="Whale start frame")

    if h3_audio:
        track = None
    else:
        loaded = g.add("LoadAudio", (-2600, 1000), {"audio": TRACK},
                       size=[420, 130], title="Voltage Bow (808)")
        track = g.add("TrimAudioDuration", (-2600, 1160),
                      {"start_index": 0.0, "duration": seconds},
                      links={"audio": (loaded, 0)}, size=[420, 106],
                      title=f"Trim to {seconds:.2f}s")

    # ---------------- H3 conditioning + latent ----------------
    i2v = g.add("MiniMaxH3ImageToVideo", (-2120, -500),
                {"prompt": PROMPT, "width": WIDTH, "height": HEIGHT},
                links={"clip": (clip, 0), "vae": (vvae, 0),
                       "length": (timing, 2), "first_frame": (image, 0)},
                size=[460, 440], title="fl2va from the whale frame")
    neg = g.add("ConditioningZeroOut", (-2120, 20), {},
                links={"conditioning": (i2v, 0)}, size=[300, 46])

    if h3_audio:
        sampler_latent_src, audio_out, audio_slot = (i2v, 1), None, None
    else:
        # Writes the real track into the audio latent and protects it, so H3
        # generates the picture *conditioned on the actual 808s*.
        song = g.add("CosmicCrafterSongMaskedAVContext", (-2120, 100), {
            "clip_start_seconds": 0.0, "context_length": 0,
            "source_fps": float(FPS), "crop": "disabled",
        }, links={"latent": (i2v, 1), "audio_vae": (avae, 0),
                  "master_audio": (track, 0)},
            size=[420, 220], title="Bind the 808 track into the AV latent")
        sampler_latent_src = (song, 0)

    ks1 = g.add("KSampler", (-1620, -500), {
        "seed": 262780983686272, "steps": 30, "cfg": 5.0,
        "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0,
    }, links={"model": (shift, 0), "positive": (i2v, 0), "negative": (neg, 0),
              "latent_image": sampler_latent_src}, size=[340, 280], title="Pass 1")

    sep1 = g.add("LTXVSeparateAVLatent", (-1240, -500), {},
                 links={"av_latent": (ks1, 0)}, size=[300, 66])
    frames1 = g.add("VAEDecode", (-1240, -390), {},
                    links={"samples": (sep1, 0), "vae": (vvae, 0)},
                    size=[300, 46], title="Pass 1 frames")

    if h3_audio:
        audio_node = g.add("VAEDecodeAudio", (-1240, -300), {},
                           links={"samples": (sep1, 1), "vae": (avae, 0)},
                           size=[300, 46], title="H3-GENERATED AUDIO")
        audio_src = (audio_node, 0)
    else:
        audio_src = (track, 0)

    # ---------------- beat brain, off the real 808s ----------------
    g.note((-1240, -200), (
        "## Beat brain\n\n"
        "`beat_locations` gives discrete downbeats, not a loudness wobble. "
        "`PeakDetector` isolates the 808 hits; `Smoothing` (exponential, alpha "
        "0.40) gives each a ~2-3 frame ring-out so the bioluminescence *swells "
        "and falls* rather than strobing on one frame.\n\n"
        "`rms_energy` runs in parallel, heavily gaussian-smoothed, as the "
        "section-level macro.\n\n"
        "Watch both `PreviewFeature` plots before a long render."
    ), size=(440, 300), title="Beat brain")

    beat_raw = g.add("RhythmFeatureExtractor", (-760, -500), {
        "extraction_method": "beat_locations", "frame_rate": float(FPS),
        "frame_count": FRAMES, "width": WIDTH, "height": HEIGHT,
        "time_signature": 4,
    }, links={"audio": audio_src}, size=[340, 190], title="808 downbeats")

    peaks = g.add("FeaturePeakDetector", (-760, -270), {
        "prominence": 0.06, "distance": 4, "width": 1, "plateau_size": 1,
        "detect_valleys": False, "invert_output": False,
    }, links={"feature": (beat_raw, 0)}, size=[340, 190], title="Isolate hits")

    ring = g.add("FeatureSmoothing", (-760, -40), {
        "smoothing_type": "exponential", "window_size": 5, "alpha": 0.40,
        "sigma": 1.0, "invert_output": False,
    }, links={"feature": (peaks, 0)}, size=[340, 170], title="Ring-out")

    beat = g.add("FeatureScaler", (-760, 170), {
        "scale_type": "exponential", "min_output": 0.08, "max_output": 1.0,
        "exponent": 1.7, "invert_output": False,
    }, links={"feature": (ring, 0)}, size=[340, 170], title="BEAT ENVELOPE")

    energy_raw = g.add("AudioFeatureExtractor", (-760, 380), {
        "extraction_method": "rms_energy", "frame_rate": float(FPS),
        "frame_count": FRAMES, "width": WIDTH, "height": HEIGHT,
    }, links={"audio": audio_src}, size=[340, 170], title="Energy")
    energy = g.add("FeatureSmoothing", (-760, 580), {
        "smoothing_type": "gaussian", "window_size": 15, "alpha": 0.3,
        "sigma": 4.0, "invert_output": False,
    }, links={"feature": (energy_raw, 0)}, size=[340, 170], title="ENERGY MACRO")

    g.add("PreviewFeature", (-380, 170), {}, links={"feature": (beat, 0)},
          size=[300, 210], title="Beat curve")
    g.add("PreviewFeature", (-380, 410), {}, links={"feature": (energy, 0)},
          size=[300, 210], title="Energy curve")

    # ---------------- radial reaction from the whale ----------------
    g.note((-380, -500), (
        "## Radial reaction - outward from the whale\n\n"
        "`H3 Audio Analyze` -> **bass** band -> `Audio Curve To Mask` in "
        "`radial` mode. The disc is centred, which is where the whale is, so "
        "each 808 pushes a growing circle of regeneration outward from it.\n\n"
        "`floor 0.10` keeps a little constant drift in the plankton between "
        "hits; `gamma 2.2` keeps the swell on the hits themselves.\n\n"
        "`H3 Latent Noise Mask` writes this at the latent's exact shape and "
        "aggregates per latent frame (1,4,4,4,4 frames per 5 tokens), so a "
        "one-frame 808 is not interpolated away. `audio_mode: preserve` carries "
        "the track through untouched."
    ), size=(440, 340), title="Radial reaction")

    analyze = g.add("MiniMaxH3AudioAnalyze", (-380, -140), {
        "clip_start_seconds": 0.0, "beat_decay": 0.18, "sensitivity": 1.4,
    }, links={"audio": audio_src, "clip_frames": (timing, 2)},
        size=[340, 190], title="Bass extractor")

    radial = g.add("MiniMaxH3AudioCurveToMask", (-380, 90), {
        "width": WIDTH, "height": HEIGHT, "spatial_mode": "radial",
        # Tuned against this track, not guessed. Measured over its first 124
        # frames, gamma 2.2 crushed the bass (mean 0.354 -> ~0.10) and left only
        # 8 frames above 0.4, so the disc barely moved: 17% -> 34% coverage.
        # gamma 1.4 / gate 0.08 gives 25 active frames and a 20% -> 49% -> 98%
        # breathing range, which reads as a pulse instead of a wobble.
        "gamma": 1.4, "threshold": 0.08, "floor": 0.12, "ceiling": 0.95,
        "invert": False, "softness": 0.55, "feather": 16,
    }, links={"curve": (analyze, 4), "frames": (timing, 2)},
        size=[340, 320], title="Bass -> radial pulse from whale")

    src = g.add("MiniMaxH3SourceToLatent", (60, -500), {"crop": "center"},
                links={"samples": (ks1, 0), "vae": (vvae, 0), "image": (frames1, 0)},
                size=[340, 106], title="Pass 1 video -> latent")
    nmask = g.add("MiniMaxH3LatentNoiseMask", (60, -360), {
        "strength": 0.88, "temporal_aggregate": "max",
        "audio_mode": "preserve", "token_grid": 2,
    }, links={"samples": (src, 0), "mask": (radial, 0)},
        size=[340, 160], title="Radial mask -> H3 latent")
    dd = g.add("DifferentialDiffusion", (60, -160), {"strength": 1.0},
               links={"model": (shift, 0)}, size=[340, 58],
               title="Graded mask -> denoise schedule")
    denoise = g.add("MiniMaxH3AudioReactiveDenoise", (60, -70), {
        "mode": "peak", "min_strength": 0.30, "max_strength": 0.58,
        "invert": False,
    }, links={"curve": (analyze, 4)}, size=[340, 150], title="Bass -> denoise")

    guider = g.add("BasicGuider", (460, -500), {},
                   links={"model": (dd, 0), "conditioning": (i2v, 0)}, size=[300, 46])
    sel = g.add("KSamplerSelect", (460, -420), {"sampler_name": "euler"}, size=[300, 58])
    sched = g.add("BasicScheduler", (460, -330), {"scheduler": "simple", "steps": 30},
                  links={"model": (shift, 0), "denoise": (denoise, 0)}, size=[300, 106])
    noise = g.add("RandomNoise", (460, -190), {"noise_seed": 811247}, size=[300, 82])

    ks2 = g.add("SamplerCustomAdvanced", (820, -500), {},
                links={"noise": (noise, 0), "guider": (guider, 0), "sampler": (sel, 0),
                       "sigmas": (sched, 0), "latent_image": (nmask, 0)},
                size=[300, 130], title="Pass 2 (bass-driven)")
    sep2 = g.add("LTXVSeparateAVLatent", (1160, -500), {},
                 links={"av_latent": (ks2, 0)}, size=[300, 66])
    frames2 = g.add("VAEDecode", (1160, -390), {},
                    links={"samples": (sep2, 0), "vae": (vvae, 0)},
                    size=[300, 46], title="Pass 2 frames")

    # ---------------- bioluminescent flare ----------------
    g.note((1160, -290), (
        "## Bioluminescent flare\n\n"
        "Bloom bound to the beat envelope's `intensity` - the light channels on "
        "the whale swell on each 808. `threshold 0.55` keeps it on the bright "
        "bioluminescence and off the dark water.\n\n"
        "Chromatic aberration is deliberately tiny (0.003) - enough to feel a "
        "pressure kick, not enough to read as a broken video.\n\n"
        "Glitch is gated at 0.68 so only the 3 hardest hits in this window "
        "touch it. No kaleidoscope: it would destroy the whale's silhouette."
    ), size=(440, 300), title="Material layer")

    bloom = g.add("FlexImageBloom", (1560, -500), {
        "strength": 0.95, "feature_threshold": 0.0, "feature_param": "intensity",
        "feature_mode": "relative", "threshold": 0.55, "blur_amount": 16.0,
        "intensity": 0.5, "num_passes": 4, "color_bleeding": 0.4, "falloff": 1.15,
    }, links={"images": (frames2, 0), "opt_feature": (beat, 0)},
        size=[340, 300], title="Bloom <- beat")

    aberr = g.add("FlexImageChromaticAberration", (1560, -170), {
        "strength": 1.0, "feature_threshold": 0.0, "feature_param": "shift_amount",
        "feature_mode": "relative", "shift_amount": 0.003, "angle": 0.0,
    }, links={"images": (bloom, 0), "opt_feature": (beat, 0)},
        size=[340, 190], title="RGB kick <- beat")

    glitch = g.add("FlexImageGlitch", (1560, 60), {
        "strength": 0.6, "feature_threshold": 0.68, "feature_param": "intensity",
        "feature_mode": "relative", "glitch_type": "digital", "intensity": 0.14,
        "block_size": 28, "wave_amplitude": 0.1, "wave_frequency": 5.0,
        "corruption_amount": 0.06, "time_seed": 0,
    }, links={"images": (aberr, 0), "opt_feature": (beat, 0)},
        size=[340, 300], title="Glitch <- hardest hits only")

    g.add("VHS_VideoCombine", (1960, -500), {
        "loop_count": 0,
        "filename_prefix": "H3_Whale_Bass_Tuned" + ("_H3Audio" if h3_audio else ""),
        "format": "video/h264-mp4", "pingpong": False, "save_output": True,
    }, links={"images": (glitch, 0), "audio": audio_src,
              "frame_rate": (timing, 0)},
        size=[420, 520], title="Final render")

    return g.to_dict("H3 Abyss Whale - Bass Reactive")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the whale bass-reactive graph.")
    ap.add_argument("--h3-audio", action="store_true",
                    help="let H3 write the score instead of using the supplied track")
    ap.add_argument("--install-to", default=None)
    ap.add_argument("--no-install", action="store_true")
    args = ap.parse_args(argv)

    graph = build(load_schema(), h3_audio=args.h3_audio)
    problems = validate(graph)
    if problems:
        raise SystemExit("validation failed:\n  " + "\n  ".join(problems))

    OUT_DIR.mkdir(exist_ok=True)
    name = "H3_Whale_BassReactive" + ("_H3Audio" if args.h3_audio else "") + ".json"
    out = OUT_DIR / name
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
