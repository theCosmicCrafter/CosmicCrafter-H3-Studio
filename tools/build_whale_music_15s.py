"""10-second abyss whale, driven by music H3 writes itself.

Two things changed from the 5-second attempt, both because of measurements
rather than taste.

1. The prompt asks for **music**, not sound design
------------------------------------------------
Measured on the 5.2s renders, H3's own audio:

    prompt          beats   onsets>0.5   bass>0.5
    ambient           3         16          14
    "percussive"      2          1          23

Naming concussive booms and clicks produced *more sustained low end and fewer
transients* - the opposite of the intent.  Describing scene foley gets foley.
So :data:`PROMPT` now asks for an actual score - genre, tempo, instrumentation,
arrangement over time - with the sound design layered on top of it.

2. The driver is the **bass envelope**, not beat detection
----------------------------------------------------------
``beat_locations`` found 2 beats in 5.2s, so everything downstream was riding a
flat curve.  The bass band, by contrast, had real movement (30/124 frames above
0.4, 18 above 0.6).  A lowpass -> rms_energy chain is therefore the primary
driver here.

``RhythmFeatureExtractor`` is still in the graph but **only as a measurement**,
with a ``FeatureInfoNode`` and a preview: at 15s there is finally room for a
couple of bars, so this is the run that answers whether H3 can hold a beat when
given the time.  If it can, promote it to the driver.

Length: 243 frames = 10.125s on H3's 17k+5 grid.  362 frames (15.08s) killed
the server outright, so this backs off; the mask chain also runs at half
resolution now, which is where a lot of the memory was going.

Run from the repo root::

    python tools/build_whale_music_15s.py
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
DOWNLOADS = Path.home() / "Downloads"

START_FRAME = "SolAttn_H3_00005.png"

FPS = 24
#: 243 frames = 10.125s on H3's 17k+5 grid.  362 (15.08s) OS-killed the server,
#: as did 124 frames at 1344x768 - both times silently, mid VAE decode.
FRAMES = 243
WIDTH, HEIGHT = 672, 384

#: Masks run at HALF the video resolution on purpose.  MiniMaxH3LatentNoiseMask
#: resizes any mask down to the latent's own dims (W/16 x H/16 = 42x24) before
#: it is ever used, so rendering the particle sim and radial pulse at full
#: canvas size buys no detail and costs real memory: at 672x384 each [T,H,W]
#: float32 mask is ~250MB at this length, and the chain holds four of them.
#: Half-res is still 8x the latent grid and cuts that to ~63MB apiece.
MASK_W, MASK_H = WIDTH // 2, HEIGHT // 2

#: Everything H3 might need, in one prompt: scene, camera, lighting, the score
#: (genre / tempo / instrumentation / arrangement), the sound design, and how
#: the picture answers the music.
PROMPT = (
    # Structure per the H3 prompt spec (skills/h3-prompt-writing): an I2VA
    # reference line, then THREE named fields in order.  Earlier attempts put a
    # "MUSIC:" paragraph inside integrated_multimodal_description, which is not
    # a field H3 parses - the score request was being read as scene text.
    # non_diegetic_music is the field that actually asks for a soundtrack.
    "For the target video, at 0.00 seconds into the target video, "
    "<Picture 1> (from [Shot 1]) is fully referenced.\n\n"

    "integrated_multimodal_description: [Shot 1] 3D CG, cinematic, the "
    "bioluminescent abyss shown in <Picture 1> continues, preserving the "
    "leviathan whale's position, the turquoise and violet neural light "
    "channels running the length of its body, the field of glowing cyan "
    "micro-plankton, and the dark indigo water. The camera pushes in with "
    "small amplitude at slow speed toward the whale's head as the light "
    "channels across its throat and ventral pleats brighten and dim in a "
    "steady pulse. Glass jellyfish drift through the foreground, their bells "
    "flashing pale cyan. Volumetric turquoise god-rays sweep down through the "
    "water. The whale's tail sweeps once and a pressure ring ripples outward "
    "through the plankton field. [Shot 2] At 00:08.000, the shot cuts to a "
    "tracking shot alongside the whale's flank, following the neural channels "
    "as they surge brighter toward the tail while the plankton streams past "
    "the lens.\n\n"

    "overall_soundscape: Deep resonant whale song calls across the distance "
    "and echoes back, layered over a muffled low-frequency underwater pressure "
    "rumble. Metallic sonar pings ring out at intervals and decay slowly. "
    "Faint crystalline chimes sound as the jellyfish drift past, and the water "
    "surges as the whale's tail sweeps.\n\n"

    # Modelled on 'Obsidian Protocol (Industrial Remix)'.  Measured on that
    # track: 130.9 BPM (0.458s median beat, tight cluster), bass mean 0.417 with
    # 72/243 frames over 0.5, 17 onsets over 0.5 - roughly 3x the bass density
    # and 4x the onsets of our previous render, which is what makes a reaction
    # fire often instead of on a handful of frames.
    # Per the H3 spec this field takes instrumentation, speed, rhythm and
    # dynamics, and no abstract mood words.
    "non_diegetic_music: A dark industrial electronic score at 130 BPM built on "
    "a heavily distorted sub-bass that drops on every downbeat, under a hard "
    "dubstep kick and snare pattern with syncopated fills. Grand chamber "
    "orchestra strings and a classical cello line carry the melody over gritty, "
    "aggressively distorted industrial synth textures, with a harp figure "
    "answering between the drops. The arrangement starts heavy, the sub-bass "
    "drops grow more intense through the middle, and it ends at full weight."
)


def build(schema):
    g = Graph(schema)

    g.note((-2900, -1000), (
        "# Abyss whale - 10s, H3 writes the music\n\n"
        "**No `LoadAudio`.** The score is decoded from H3's own audio latent, "
        "which is what the contest's *'H3-generated synced audio'* asks for.\n\n"
        "The prompt asks for an actual **score** - 80 BPM, 808 on the downbeat, "
        "pads, piano, cello, with an arrangement that builds - because "
        "describing scene foley got foley. Measured on the 5.2s attempts: the "
        "'percussive' prompt produced *1* onset above 0.5, the plain ambient "
        "one produced 16. Naming drums did not make drums.\n\n"
        "**The driver is the bass envelope**, not beat detection: "
        "`beat_locations` found 2 beats in 5.2s. The rhythm extractor is still "
        "here but only as a *measurement* - at 10s there is finally room for a "
        "few bars, so check its preview and `FeatureInfo`. If beats show up, "
        "promote it to the driver."
    ), size=(500, 400), title="README - read this first")

    # ---------------- model stack ----------------
    unet = g.add("UNETLoader", (-2900, -560),
                 {"unet_name": "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
                  "weight_dtype": "default"}, size=[420, 82], title="H3 fl2va")
    sol = g.add("SolAttnPatch", (-2900, -430), {
        "tau": 1.0, "start_percent": 0.2, "end_percent": 0.9, "min_tokens": 4096,
        "int8_qk": True, "sink_conditioning": "exact_kv_and_rows", "morton": False,
        "morton_curve": "2d_frame", "int8_pv": True, "verbose": False,
        "use_tma": False, "dense_blocks": "", "tau_profile": "",
    }, links={"model": (unet, 0)}, size=[420, 330], title="Sol-Attn 20-90%")
    shift = g.add("MiniMaxH3SigmaShift", (-2900, -40),
                  {"shift_video": 12.0, "shift_audio": 3.0},
                  links={"model": (sol, 0)}, size=[420, 82], title="Sigma 12 / 3")

    clip = g.add("CLIPLoader", (-2900, 90),
                 {"clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
                  "type": "minimax", "device": "default"}, size=[420, 106])
    vvae = g.add("VAELoader", (-2900, 240),
                 {"vae_name": "minimax_h3_video_vae_fp16.safetensors"},
                 size=[420, 58], title="Video VAE")
    avae = g.add("VAELoader", (-2900, 320),
                 {"vae_name": "minimax_h3_audio_vae_fp32.safetensors"},
                 size=[420, 58], title="Audio VAE")
    timing = g.add("CosmicCrafterVideoTiming", (-2900, 410),
                   {"frame_rate": float(FPS), "seconds": 0.0, "frames": FRAMES},
                   size=[420, 106], title=f"Timing - {FRAMES}f = {FRAMES/FPS:.2f}s")
    image = g.add("LoadImage", (-2900, 560), {"image": START_FRAME},
                  size=[420, 340], title="Whale start frame")

    # ---------------- pass 1 ----------------
    i2v = g.add("MiniMaxH3ImageToVideo", (-2400, -560),
                {"prompt": PROMPT, "width": WIDTH, "height": HEIGHT},
                links={"clip": (clip, 0), "vae": (vvae, 0),
                       "length": (timing, 2), "first_frame": (image, 0)},
                size=[480, 520], title="fl2va - full music prompt")
    neg = g.add("ConditioningZeroOut", (-2400, 0), {},
                links={"conditioning": (i2v, 0)}, size=[300, 46])

    ks1 = g.add("KSampler", (-1860, -560), {
        "seed": 262780983686272, "steps": 30, "cfg": 5.0,
        "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0,
    }, links={"model": (shift, 0), "positive": (i2v, 0), "negative": (neg, 0),
              "latent_image": (i2v, 1)}, size=[340, 280], title="Pass 1")

    sep1 = g.add("LTXVSeparateAVLatent", (-1480, -560), {},
                 links={"av_latent": (ks1, 0)}, size=[300, 66])
    audio = g.add("VAEDecodeAudio", (-1480, -450), {},
                  links={"samples": (sep1, 1), "vae": (avae, 0)},
                  size=[300, 46], title="H3's SCORE")
    frames1 = g.add("VAEDecode", (-1480, -360), {},
                    links={"samples": (sep1, 0), "vae": (vvae, 0)},
                    size=[300, 46], title="Pass 1 frames")
    g.add("PreviewAudio", (-1480, -270), {}, links={"audio": (audio, 0)},
          size=[300, 100], title="LISTEN to this first")

    # ---------------- bass envelope: the actual driver ----------------
    g.note((-1000, -1000), (
        "## Bass envelope - the driver\n\n"
        "`lowpass 180Hz` -> `rms_energy` gives the 808's own envelope. On the "
        "5.2s test this band had 30/124 frames above 0.4 while beat detection "
        "found 2 beats total, so this is what actually carries signal.\n\n"
        "`Smoothing` (exponential 0.45) gives each hit a ring-out so the "
        "bioluminescence swells and falls instead of strobing one frame."
    ), size=(430, 260), title="Bass envelope")

    lowpass = g.add("FrequencyFilterCustom", (-1000, -700), {
        "filter_type": "lowpass", "order": 4, "cutoff": 180.0,
    }, size=[340, 130], title="lowpass 180Hz")
    bass_audio = g.add("AudioFilter", (-1000, -540), {},
                       links={"audio": (audio, 0), "filters": (lowpass, 0)},
                       size=[340, 66], title="808 band only")
    bass_raw = g.add("AudioFeatureExtractor", (-1000, -440), {
        "extraction_method": "rms_energy", "frame_rate": float(FPS),
        "frame_count": FRAMES, "width": WIDTH, "height": HEIGHT,
    }, links={"audio": (bass_audio, 0)}, size=[340, 170], title="Bass RMS")
    bass_ring = g.add("FeatureSmoothing", (-1000, -240), {
        "smoothing_type": "exponential", "window_size": 5, "alpha": 0.45,
        "sigma": 1.0, "invert_output": False,
    }, links={"feature": (bass_raw, 0)}, size=[340, 170], title="Ring-out")
    bass = g.add("FeatureScaler", (-1000, -40), {
        "scale_type": "linear", "min_output": 0.06, "max_output": 1.0,
        "exponent": 2.0, "invert_output": False,
    }, links={"feature": (bass_ring, 0)}, size=[340, 170], title="BASS ENVELOPE")

    energy_raw = g.add("AudioFeatureExtractor", (-1000, 160), {
        "extraction_method": "rms_energy", "frame_rate": float(FPS),
        "frame_count": FRAMES, "width": WIDTH, "height": HEIGHT,
    }, links={"audio": (audio, 0)}, size=[340, 170], title="Full-mix energy")
    energy = g.add("FeatureSmoothing", (-1000, 360), {
        "smoothing_type": "gaussian", "window_size": 21, "alpha": 0.3,
        "sigma": 5.0, "invert_output": False,   # 5.0 is the catalog max
    }, links={"feature": (energy_raw, 0)}, size=[340, 170], title="ARRANGEMENT MACRO")

    g.add("PreviewFeature", (-620, -40), {}, links={"feature": (bass, 0)},
          size=[300, 200], title="Bass plot")
    g.add("PreviewFeature", (-620, 190), {}, links={"feature": (energy, 0)},
          size=[300, 200], title="Arrangement plot")

    # ---------------- rhythm: MEASUREMENT ONLY ----------------
    g.note((-620, 430), (
        "## Rhythm - measurement, not a driver\n\n"
        "At 5.2s `beat_locations` found **2 beats**, so it drove nothing. "
        "15s finally gives H3 room for a few bars.\n\n"
        "Read `FeatureInfo`'s min/max and the plot. If beats have appeared, "
        "re-point the bloom and emission rate at this instead of the bass "
        "envelope - it will be tighter."
    ), size=(430, 240), title="Does H3 hold a beat at 15s?")

    rhythm = g.add("RhythmFeatureExtractor", (-620, 700), {
        "extraction_method": "beat_locations", "frame_rate": float(FPS),
        "frame_count": FRAMES, "width": WIDTH, "height": HEIGHT,
        "time_signature": 4,
    }, links={"audio": (audio, 0)}, size=[340, 190], title="Beat probe")
    g.add("PreviewFeature", (-240, 700), {}, links={"feature": (rhythm, 0)},
          size=[300, 200], title="Beat plot")
    g.add("FeatureInfoNode", (-240, 930), {}, links={"feature": (rhythm, 0)},
          size=[300, 220], title="Beat stats (read min/max)")

    # ---------------- mask emitter -> particles ----------------
    emitter_mask = g.add("MiniMaxH3MaskEmitter", (-240, -560), {
        "frames": FRAMES, "width": MASK_W, "height": MASK_H, "shape": "solid",
        "coverage": 1.0, "softness": 0.35, "ring_width": 0.25,
    }, size=[340, 300],
        title=f"Mask Emitter - {FRAMES}f at {MASK_W}x{MASK_H}")

    rate = g.add("EmitterEmissionRateModulation", (-240, -220), {
        "start_frame": 0, "end_frame": 0, "effect_duration": 0,
        "temporal_easing": "linear", "palindrome": False, "random": False,
        "target_emission_rate": 95.0,
    }, links={"feature": (bass, 0)}, size=[340, 230], title="Bass -> emission rate")

    emitter = g.add("ParticleEmitter", (160, -560), {
        "emitter_x": 0.5, "emitter_y": 0.5, "particle_direction": 0.0,
        "particle_spread": 360.0, "particle_size": 8.0, "particle_speed": 240.0,
        "emission_rate": 20.0, "color": "(170,235,255)", "initial_plume": 0.1,
        "start_frame": 0, "end_frame": 0, "emission_radius": 0.05,
    }, links={"emitter_modulation": (rate, 0)}, size=[340, 380],
        title="Emitter at the whale")

    particles = g.add("ParticleEmissionMask", (160, -150), {
        "strength": 1.0, "invert": False, "subtract_original": 0.0,
        "grow_with_blur": 0.0, "particle_count": 700, "particle_lifetime": 2.5,
        "wind_strength": 0.0, "wind_direction": 0.0, "gravity": 0.0,
        "warmup_period": 0, "start_frame": 0, "end_frame": 0,
        "respect_mask_boundary": False, "emission_strength": 1.0,
    }, links={"masks": (emitter_mask, 0), "emitters": (emitter, 0)},
        size=[340, 380], title="Plankton pressure rings")

    # ---------------- latent reaction ----------------
    analyze = g.add("MiniMaxH3AudioAnalyze", (560, -560), {
        "clip_start_seconds": 0.0, "beat_decay": 0.18, "sensitivity": 1.4,
    }, links={"audio": (audio, 0), "clip_frames": (timing, 2)},
        size=[340, 190], title="Bass curve (for the radial mask)")

    radial = g.add("MiniMaxH3AudioCurveToMask", (560, -330), {
        "width": MASK_W, "height": MASK_H, "spatial_mode": "radial",
        # gamma 1.0 / gate 0.10 measured best on H3's own bass: 29 frames
        # above 0.4 versus 22 at gamma 1.4.
        "gamma": 1.0, "threshold": 0.10, "floor": 0.10, "ceiling": 0.95,
        "invert": False, "softness": 0.55, "feather": 14,
    }, links={"curve": (analyze, 4), "frames": (timing, 2)},
        size=[340, 320], title="Bass -> radial pulse from whale")

    combined = g.add("MiniMaxH3MaskComposite", (960, -560), {
        "operation": "screen", "invert_a": False, "invert_b": False,
        "gain": 1.0, "offset": 0.0, "feather": 8, "invert_result": False,
    }, links={"mask_a": (particles, 0), "mask_b": (radial, 0)},
        size=[340, 230], title="Particles + radial pulse")

    src = g.add("MiniMaxH3SourceToLatent", (960, -300), {"crop": "center"},
                links={"samples": (ks1, 0), "vae": (vvae, 0), "image": (frames1, 0)},
                size=[340, 106], title="Pass 1 video -> latent")
    nmask = g.add("MiniMaxH3LatentNoiseMask", (960, -160), {
        "strength": 0.88, "temporal_aggregate": "max",
        "audio_mode": "preserve", "token_grid": 2,
    }, links={"samples": (src, 0), "mask": (combined, 0)},
        size=[340, 160], title="preserve = H3's score kept exact")
    dd = g.add("DifferentialDiffusion", (960, 40), {"strength": 1.0},
               links={"model": (shift, 0)}, size=[340, 58])
    denoise = g.add("MiniMaxH3AudioReactiveDenoise", (960, 130), {
        "mode": "peak", "min_strength": 0.30, "max_strength": 0.58,
        "invert": False,
    }, links={"curve": (analyze, 4)}, size=[340, 150], title="Bass -> denoise")

    guider = g.add("BasicGuider", (1360, -560), {},
                   links={"model": (dd, 0), "conditioning": (i2v, 0)}, size=[300, 46])
    sel = g.add("KSamplerSelect", (1360, -480), {"sampler_name": "euler"}, size=[300, 58])
    sched = g.add("BasicScheduler", (1360, -390), {"scheduler": "simple", "steps": 30},
                  links={"model": (shift, 0), "denoise": (denoise, 0)}, size=[300, 106])
    noise = g.add("RandomNoise", (1360, -250), {"noise_seed": 811247}, size=[300, 82])

    ks2 = g.add("SamplerCustomAdvanced", (1720, -560), {},
                links={"noise": (noise, 0), "guider": (guider, 0), "sampler": (sel, 0),
                       "sigmas": (sched, 0), "latent_image": (nmask, 0)},
                size=[300, 130], title="Pass 2 (bass-driven)")
    sep2 = g.add("LTXVSeparateAVLatent", (2060, -560), {},
                 links={"av_latent": (ks2, 0)}, size=[300, 66])
    frames2 = g.add("VAEDecode", (2060, -450), {},
                    links={"samples": (sep2, 0), "vae": (vvae, 0)},
                    size=[300, 46], title="Final frames")

    bloom = g.add("FlexImageBloom", (2060, -360), {
        "strength": 0.95, "feature_threshold": 0.0, "feature_param": "intensity",
        "feature_mode": "relative", "threshold": 0.55, "blur_amount": 16.0,
        "intensity": 0.5, "num_passes": 4, "color_bleeding": 0.4, "falloff": 1.15,
    }, links={"images": (frames2, 0), "opt_feature": (bass, 0)},
        size=[340, 300], title="Bioluminescent flare <- bass")
    aberr = g.add("FlexImageChromaticAberration", (2060, -30), {
        "strength": 1.0, "feature_threshold": 0.0, "feature_param": "shift_amount",
        "feature_mode": "relative", "shift_amount": 0.003, "angle": 0.0,
    }, links={"images": (bloom, 0), "opt_feature": (bass, 0)},
        size=[340, 190], title="Pressure kick <- bass")
    # (FlexImageColorGrade dropped: it requires a lut_file, and none is installed.)

    g.add("VHS_VideoCombine", (2460, -560), {
        "loop_count": 0, "filename_prefix": "H3_Whale_Industrial10s",
        "format": "video/h264-mp4", "pingpong": False, "save_output": True,
    }, links={"images": (aberr, 0), "audio": (audio, 0),
              "frame_rate": (timing, 0)},
        size=[420, 520], title="Final - H3's own score")

    return g.to_dict("H3 Abyss Whale - 10s Music Reactive")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the 10s music-reactive whale.")
    ap.add_argument("--install-to", default=None)
    ap.add_argument("--no-install", action="store_true")
    args = ap.parse_args(argv)

    graph = build(load_schema())
    problems = validate(graph)
    if problems:
        raise SystemExit("validation failed:\n  " + "\n  ".join(problems))

    name = "H3_Whale_Industrial10s.json"
    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / name
    payload = json.dumps(graph, indent=2)
    out.write_text(payload, encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)} "
          f"({len(graph['nodes'])} nodes, {len(graph['links'])} links)")

    # Downloads too - asked for explicitly, and it is the easy place to grab it
    # for the contest submission.
    if DOWNLOADS.is_dir():
        (DOWNLOADS / name).write_text(payload, encoding="utf-8")
        print(f"wrote {DOWNLOADS / name}")

    if args.no_install:
        return out
    from build_audio_reactive_workflow import find_comfyui_workflows, INSTALL_SUBDIR
    target = find_comfyui_workflows(args.install_to)
    if target is None:
        print("ComfyUI workflow dir not found - skipping install")
        return out
    dest = target / INSTALL_SUBDIR
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(out, dest / name)
    print(f"installed to {dest / name}")
    return out


if __name__ == "__main__":
    main()
