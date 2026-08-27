"""Generate the CosmicCrafter audio-reactive workflows.

Hand-edited workflow JSON drifts: the earlier SAM graphs shipped with dangling
link ids and wired the audio pulse through ``SetLatentNoiseMask``, which cannot
address an H3 nested AV latent.  Building the graph from a description keeps
node ids, link ids and slot indices consistent by construction.

Run from the repo root::

    python tools/build_audio_reactive_workflow.py

The graphs are written to ``workflows/`` and also **installed** into ComfyUI's
own workflow directory so they appear in its sidebar.  ComfyUI only lists
workflows under ``<install>/user/default/workflows``; a file sitting in this
repo is invisible to it and has to be opened through a file dialog.

Override the destination with ``--install-to DIR``, or ``--no-install`` to skip.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "workflows"

#: Where ComfyUI lists workflows, relative to an install root.
USER_WORKFLOWS = Path("user") / "default" / "workflows"

#: Sub-directory the installed graphs land in, so they group in the sidebar and
#: never collide with the user's own files.
INSTALL_SUBDIR = "CosmicCrafter"

#: Candidate ComfyUI roots, tried in order.  The pack is usually symlinked into
#: custom_nodes, so ``__file__`` resolves back to the dev folder and cannot be
#: used to locate the install.
CANDIDATE_ROOTS = (
    # sol-engine is the instance comfy-cli actually launches (see `comfy env`),
    # so it comes first - installing into a different one looks like a silent
    # no-op from the sidebar.
    Path(r"F:\Comfy-Desktop\ComfyUI-Installs\sol-engine\ComfyUI"),
    Path(r"F:\Comfy-Desktop\ComfyUI-Installs\ComfyUI\ComfyUI"),
    Path(r"F:\ComfyUI-Easy-Install\ComfyUI-Easy-Install\ComfyUI"),
    Path.home() / "ComfyUI",
)


def find_comfyui_workflows(explicit=None):
    """Locate ComfyUI's workflow directory, or ``None`` if it cannot be found.

    ``$COMFYUI_USER_WORKFLOWS`` wins, then ``--install-to``, then the known
    install roots.  Accepts either the workflows directory itself or an install
    root, and returns the directory ComfyUI actually lists.
    """

    for candidate in (os.environ.get("COMFYUI_USER_WORKFLOWS"), explicit):
        if candidate:
            path = Path(candidate)
            if (path / USER_WORKFLOWS).is_dir():
                return path / USER_WORKFLOWS
            return path

    for root in CANDIDATE_ROOTS:
        target = root / USER_WORKFLOWS
        if target.is_dir():
            return target
    return None

# Model filenames as installed.  Keep these in sync with the ComfyUI models dir;
# a name that does not resolve shows up as a red loader node on the canvas.
UNET = "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
CLIP = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
VIDEO_VAE = "minimax_h3_video_vae_fp16.safetensors"
AUDIO_VAE = "minimax_h3_audio_vae_fp32.safetensors"
#: SAM 3 lives in ComfyUI core (comfy_extras/nodes_sam3.py) and loads as a plain
#: checkpoint - no isolated env, so none of comfyui-sam3's comfy_kitchen skew.
SAM3_CKPT = r"sam3.1\sam3.1_multiplex_fp16.safetensors"

#: Prompt for the native graph.  H3 reads the song out of the packed token
#: sequence, so the prompt's job is to tell it *how* to move to what it hears -
#: name the camera, the cutting, and what responds on the beat.  Do not describe
#: the music itself; the model already has it.
NATIVE_PROMPT = (
    "integrated_multimodal_description:\n"
    "A music video that moves with the track.\n\n"
    "The camera pushes and drifts in time with the rhythm, holding on the "
    "downbeat and gliding through the phrase.\n\n"
    "Light pulses with the percussion - practical lamps, reflections and haze "
    "flare on the hits and fall back between them.\n\n"
    "The subject performs to the music: weight shifting, head and shoulders "
    "answering the beat, hair and fabric carrying the motion.\n\n"
    "Cinematic, shallow depth of field, volumetric light, film grain."
)

#: Prompt for the subject-lock graphs, where the mask pins the subject and only
#: the background is free to change.
SUBJECT_LOCK_PROMPT = (
    "integrated_multimodal_description:\n"
    "A cinematic portrait held perfectly still while the world behind it "
    "erupts in time with the music.\n\n"
    "The subject stays sharp, centred and unchanged.\n\n"
    "Behind them, the environment tears apart and reassembles on every "
    "beat - neon light, drifting embers, collapsing architecture."
)

FRAMES = 124  # H3's 17k+5 grid; ~5.2s at 24fps
FPS = 24
# H3's 768-short-edge canvas, rounded to /32.  The mask nodes render at the
# same size so nothing is resampled on the way into the latent.
WIDTH, HEIGHT = 1344, 768


class Graph:
    """Minimal ComfyUI graph builder with consistent ids and slots."""

    def __init__(self):
        self.nodes = []
        self.links = []
        self._node_id = 0
        self._link_id = 0
        self._by_id = {}

    def add(self, node_type, pos, widgets=None, inputs=(), outputs=(), size=None,
            title=None):
        """Register a node.

        ``inputs``/``outputs`` are ``(name, type)`` pairs in slot order - the
        order must match the node's declared schema, because links address slots
        by index.
        """

        self._node_id += 1
        node = {
            "id": self._node_id,
            "type": node_type,
            "pos": list(pos),
            "size": list(size or [300, 120]),
            "flags": {},
            "order": self._node_id - 1,
            "mode": 0,
            "inputs": [{"name": n, "type": t, "link": None} for n, t in inputs],
            "outputs": [{"name": n, "type": t, "links": []} for n, t in outputs],
            "properties": {"Node name for S&R": node_type},
        }
        if widgets is not None:
            node["widgets_values"] = widgets
        if title:
            node["title"] = title
        self.nodes.append(node)
        self._by_id[self._node_id] = node
        return self._node_id

    def link(self, src_id, src_slot, dst_id, dst_slot):
        src = self._by_id[src_id]
        dst = self._by_id[dst_id]
        if src_slot >= len(src["outputs"]):
            raise ValueError(f"{src['type']} has no output slot {src_slot}")
        if dst_slot >= len(dst["inputs"]):
            raise ValueError(f"{dst['type']} has no input slot {dst_slot}")

        self._link_id += 1
        link_type = src["outputs"][src_slot]["type"]
        self.links.append([self._link_id, src_id, src_slot, dst_id, dst_slot, link_type])
        src["outputs"][src_slot]["links"].append(self._link_id)
        dst["inputs"][dst_slot]["link"] = self._link_id
        return self._link_id

    def to_dict(self, title):
        return {
            "id": title,
            "revision": 0,
            "last_node_id": self._node_id,
            "last_link_id": self._link_id,
            "nodes": self.nodes,
            "links": self.links,
            "groups": [],
            "config": {},
            "extra": {},
            "version": 0.4,
        }


def validate(graph_dict):
    """Fail loudly on the defects the hand-written graphs actually shipped."""
    problems = []
    ids = {n["id"] for n in graph_dict["nodes"]}
    link_ids = {link[0] for link in graph_dict["links"]}

    for link in graph_dict["links"]:
        lid, src, src_slot, dst, dst_slot, _type = link
        if src not in ids:
            problems.append(f"link {lid} originates at missing node {src}")
        if dst not in ids:
            problems.append(f"link {lid} targets missing node {dst}")

    for node in graph_dict["nodes"]:
        for slot in node.get("inputs") or []:
            if slot["link"] is not None and slot["link"] not in link_ids:
                problems.append(
                    f"node {node['id']} ({node['type']}) input "
                    f"'{slot['name']}' -> dangling link {slot['link']}"
                )
        for slot in node.get("outputs") or []:
            for lid in slot.get("links") or []:
                if lid not in link_ids:
                    problems.append(
                        f"node {node['id']} ({node['type']}) output "
                        f"'{slot['name']}' -> dangling link {lid}"
                    )
    return problems


def build_graph(segmenter="sam3", subject_lock=True):
    """Reference image + song -> an audio-reactive H3 clip.

    ``subject_lock`` chooses how the reactivity is produced:

    * ``False`` (**native**) - no masking at all.  The real song is written into
      the AV latent's audio stream and protected, and H3 generates the *whole
      frame* conditioned on it.  H3 is a single-stream packed-token DiT whose
      sequence is ``[text | cond | audio | video]``, so video tokens attend to
      audio tokens at every layer - the model was trained to move to the music
      and does the synchronisation itself.  This renders an actual video rather
      than compositing a still against a reacting background.
    * ``True`` (**subject lock**) - additionally pins a segmented subject with a
      latent noise mask so only the background reacts.  This is a compositing
      effect: it necessarily *suppresses* the model's own motion wherever the
      mask holds, so use it when a locked subject is the point.

    ``segmenter`` selects how the subject is isolated (ignored when
    ``subject_lock`` is False):

    * ``"sam3"`` - SAM 3 text-prompted detection via **ComfyUI core**
      (``SAM3_Detect``), loaded as a plain checkpoint. Name the subject in a
      ``CLIPTextEncode`` and it is segmented. This is the default: it is more
      precise than matting and, being core, avoids the isolated pixi env that
      the ``comfyui-sam3`` custom pack runs in (whose bundled ``comfy_kitchen``
      can lag the host's and fail on import).
    * ``"rmbg"`` - ComfyUI-RMBG's ``RMBG`` node. Needs no prompt and no SAM
      checkpoint; use it when the subject is simply "the foreground".
    """
    if segmenter not in ("rmbg", "sam3"):
        raise ValueError(f"unknown segmenter {segmenter!r}")
    g = Graph()

    # ---- loaders -------------------------------------------------------
    unet = g.add("UNETLoader", (-1900, -520), [UNET, "default"],
                 outputs=[("MODEL", "MODEL")], size=[400, 82])
    clip = g.add("CLIPLoader", (-1900, -400), [CLIP, "minimax", "default"],
                 outputs=[("CLIP", "CLIP")], size=[400, 106])
    vvae = g.add("VAELoader", (-1900, -260), [VIDEO_VAE],
                 outputs=[("VAE", "VAE")], size=[400, 58],
                 title="Video VAE")
    avae = g.add("VAELoader", (-1900, -180), [AUDIO_VAE],
                 outputs=[("VAE", "VAE")], size=[400, 58],
                 title="Audio VAE")
    image = g.add("LoadImage", (-1900, -80), ["test_image.jpg", "image"],
                  outputs=[("IMAGE", "IMAGE"), ("MASK", "MASK")], size=[400, 330])
    audio = g.add("LoadAudio", (-1900, 300), ["test_audio.mp3", None],
                  outputs=[("AUDIO", "AUDIO")], size=[400, 130])

    # ---- subject isolation ---------------------------------------------
    subject = subject_mask_slot = subject_preview_slot = None
    if not subject_lock:
        pass
    elif segmenter == "sam3":
        sam_ckpt = g.add("CheckpointLoaderSimple", (-1420, -140), [SAM3_CKPT],
                         outputs=[("MODEL", "MODEL"), ("CLIP", "CLIP"), ("VAE", "VAE")],
                         size=[380, 98], title="SAM3 checkpoint")
        sam_text = g.add("CLIPTextEncode", (-1420, 0), ["person"],
                         inputs=[("clip", "CLIP")],
                         outputs=[("CONDITIONING", "CONDITIONING")],
                         size=[380, 110], title="What to isolate")
        g.link(sam_ckpt, 1, sam_text, 0)

        subject = g.add(
            "SAM3_Detect", (-1420, 150), [0.5, 2, False],
            inputs=[("model", "MODEL"), ("image", "IMAGE"),
                    ("conditioning", "CONDITIONING"), ("bboxes", "BOUNDING_BOX"),
                    ("positive_coords", "STRING"), ("negative_coords", "STRING")],
            outputs=[("masks", "MASK"), ("bboxes", "BOUNDING_BOX")],
            size=[380, 190], title="SAM3 - isolate the subject",
        )
        g.link(sam_ckpt, 0, subject, 0)
        g.link(image, 0, subject, 1)
        g.link(sam_text, 0, subject, 2)
        subject_mask_slot = 0      # masks
        subject_preview_slot = None  # no image preview output
    else:
        # RMBG outputs (IMAGE, MASK, MASK_IMAGE); the MASK is the subject.
        # mask_blur 4 / mask_offset 2 soften and slightly grow the cutout so the
        # reacting background does not crawl along the subject's edge.
        subject = g.add(
            "RMBG", (-1420, 60),
            ["RMBG-2.0", 1.0, 1024, 4, 2, False, False, "Alpha", "#222222"],
            inputs=[("image", "IMAGE")],
            outputs=[("IMAGE", "IMAGE"), ("MASK", "MASK"), ("MASK_IMAGE", "IMAGE")],
            size=[330, 260], title="RMBG - isolate the subject",
        )
        g.link(image, 0, subject, 0)
        subject_mask_slot = 1      # MASK
        subject_preview_slot = 2   # MASK_IMAGE

    # ---- audio analysis ------------------------------------------------
    analyze = g.add(
        "MiniMaxH3AudioAnalyze", (-1420, 320), [0.0, FRAMES, 0.15, 1.0],
        inputs=[("audio", "AUDIO"), ("clip_start_seconds", "FLOAT"),
                ("clip_frames", "INT"), ("beat_decay", "FLOAT"),
                ("sensitivity", "FLOAT")],
        outputs=[("energy", "FLOAT"), ("beats", "FLOAT"), ("brightness", "FLOAT"),
                 ("onsets", "FLOAT"), ("bass", "FLOAT"), ("mids", "FLOAT"),
                 ("highs", "FLOAT")],
        size=[330, 190],
    )
    g.link(audio, 0, analyze, 0)

    # beats -> animated pulse mask.  gamma 1.6 and a 0.12 gate keep the pulse
    # percussive instead of a constant wash; floor 0.15 leaves a little drift
    # between hits so the background never fully freezes.
    #
    # Only the subject-lock graph needs this: in the native graph H3 reads the
    # song directly out of the packed token sequence, so an external mask would
    # only fight the motion the model is already producing.
    composite = None
    if subject_lock:
      pulse = g.add(
          "MiniMaxH3AudioCurveToMask", (-1020, 320),
          [WIDTH, HEIGHT, FRAMES, "uniform", 1.6, 0.12, 0.15, 1.0, False, 0.25, 0],
          inputs=[("curve", "FLOAT")],
          outputs=[("mask", "MASK"), ("shaped_curve", "FLOAT")],
          size=[340, 300], title="Beats -> pulse mask",
      )
      g.link(analyze, 1, pulse, 0)  # slot 1 = beats

      # subject mask inverted, multiplied by the pulse: the subject stays locked
      # while the background is free to hallucinate on every hit.
      composite = g.add(
          "MiniMaxH3MaskComposite", (-620, 60),
          ["multiply", True, False, 1.0, 0.0, 6, False],
          inputs=[("mask_a", "MASK"), ("mask_b", "MASK")],
          outputs=[("mask", "MASK")],
          size=[330, 220], title="Lock subject, free background",
      )
      g.link(subject, subject_mask_slot, composite, 0)
      g.link(pulse, 0, composite, 1)

    # ---- H3 conditioning + latent --------------------------------------
    i2v = g.add(
        "MiniMaxH3ImageToVideo", (-1020, -520),
        [SUBJECT_LOCK_PROMPT if subject_lock else NATIVE_PROMPT,
         WIDTH, HEIGHT, FRAMES],
        inputs=[("clip", "CLIP"), ("vae", "VAE"), ("first_frame", "IMAGE"),
                ("last_frame", "IMAGE")],
        outputs=[("positive", "CONDITIONING"), ("LATENT", "LATENT")],
        size=[420, 400],
    )
    g.link(clip, 0, i2v, 0)
    g.link(vvae, 0, i2v, 1)
    g.link(image, 0, i2v, 2)

    # Bind the master song into the AV latent so the audio stream is the real
    # track rather than something the model invents.
    song = g.add(
        "MiniMaxH3SongMaskedAVContext", (-560, -520), [0.0, 0],
        inputs=[("latent", "LATENT"), ("audio_vae", "VAE"), ("master_audio", "AUDIO"),
                ("vae", "VAE"), ("source_frames", "IMAGE"), ("source_latent", "LATENT"),
                ("clip_start_seconds", "FLOAT"), ("context_frames", "INT")],
        outputs=[("LATENT", "LATENT")], size=[380, 240],
    )
    g.link(i2v, 1, song, 0)
    g.link(avae, 0, song, 1)
    g.link(audio, 0, song, 2)

    # ---- put the subject INTO the latent -------------------------------
    # Only for the subject-lock graph.  MiniMaxH3ImageToVideo hands back an
    # *empty* AV latent: the still it takes is attached as keyframe
    # conditioning, not as latent content.  A denoise mask can only preserve
    # what the latent already holds, so masking that empty latent locks in blank
    # latent space and the "protected" subject decodes to flat grey.
    #
    # The native graph wants the opposite - the whole frame regenerated - so it
    # feeds the song-conditioned latent straight to the sampler.
    sampler_latent = song
    if subject_lock:
        source = g.add(
            "MiniMaxH3SourceToLatent", (-560, -220), ["center"],
            inputs=[("samples", "LATENT"), ("vae", "VAE"), ("image", "IMAGE")],
            outputs=[("latent", "LATENT")],
            size=[340, 120], title="Encode subject into the latent",
        )
        g.link(song, 0, source, 0)
        g.link(vvae, 0, source, 1)
        g.link(image, 0, source, 2)

        # ---- the H3-aware latent mask ----------------------------------
        # audio_mode "preserve" freezes the audio latent so the song plays back
        # untouched while only the video stream reacts.
        noise_mask = g.add(
            "MiniMaxH3LatentNoiseMask", (-140, -300), [1.0, "max", "preserve", 2],
            inputs=[("samples", "LATENT"), ("mask", "MASK"), ("audio_curve", "FLOAT")],
            outputs=[("latent", "LATENT"), ("latent_mask_preview", "MASK")],
            size=[340, 180], title="H3 latent noise mask (beat-accurate)",
        )
        g.link(source, 0, noise_mask, 0)
        g.link(composite, 0, noise_mask, 1)
        sampler_latent = noise_mask

    # ---- sampling -------------------------------------------------------
    denoise = g.add(
        "MiniMaxH3AudioReactiveDenoise", (-1020, 660), ["peak", 0.75, 1.0, False],
        inputs=[("curve", "FLOAT"), ("mode", "ENUM"), ("min_strength", "FLOAT"),
                ("max_strength", "FLOAT"), ("invert", "BOOLEAN")],
        outputs=[("denoise_strength", "FLOAT")], size=[330, 150],
    )
    g.link(analyze, 0, denoise, 0)  # slot 0 = energy

    # Differential Diffusion reinterprets the *graded* part of the mask: instead
    # of blending latents by mask value on every step, each region begins
    # denoising when the schedule reaches its value.  So the pulse's floor
    # (0.15) becomes "changes only near the end" and its peak (1.0) becomes
    # "fully regenerated" - audio intensity maps to amount of change, not to a
    # per-step blend ratio, which is what keeps quiet passages from turning to
    # mush.  It reads the mask after packing, so H3's nested latent is fine.
    guider_model = unet
    if subject_lock:
        diff = g.add("DifferentialDiffusion", (-140, -520), [1.0],
                     inputs=[("model", "MODEL")],
                     outputs=[("MODEL", "MODEL")], size=[300, 60],
                     title="Graded mask -> per-region denoise schedule")
        g.link(unet, 0, diff, 0)
        guider_model = diff

    guider = g.add("BasicGuider", (260, -520), None,
                   inputs=[("model", "MODEL"), ("conditioning", "CONDITIONING")],
                   outputs=[("GUIDER", "GUIDER")], size=[260, 60])
    g.link(guider_model, 0, guider, 0)
    g.link(i2v, 0, guider, 1)

    sampler = g.add("KSamplerSelect", (260, -420), ["euler"],
                    outputs=[("SAMPLER", "SAMPLER")], size=[260, 58])
    scheduler = g.add("BasicScheduler", (260, -320), ["simple", 20, 1.0],
                      inputs=[("model", "MODEL"), ("denoise", "FLOAT")],
                      outputs=[("SIGMAS", "SIGMAS")], size=[260, 110])
    g.link(unet, 0, scheduler, 0)
    g.link(denoise, 0, scheduler, 1)

    noise = g.add("RandomNoise", (260, -180), [0, "fixed"],
                  outputs=[("NOISE", "NOISE")], size=[260, 82])

    adv = g.add("SamplerCustomAdvanced", (580, -520), None,
                inputs=[("noise", "NOISE"), ("guider", "GUIDER"), ("sampler", "SAMPLER"),
                        ("sigmas", "SIGMAS"), ("latent_image", "LATENT")],
                outputs=[("output", "LATENT"), ("denoised_output", "LATENT")],
                size=[300, 130])
    g.link(noise, 0, adv, 0)
    g.link(guider, 0, adv, 1)
    g.link(sampler, 0, adv, 2)
    g.link(scheduler, 0, adv, 3)
    g.link(sampler_latent, 0, adv, 4)

    decode = g.add("VAEDecode", (920, -520), None,
                   inputs=[("samples", "LATENT"), ("vae", "VAE")],
                   outputs=[("IMAGE", "IMAGE")], size=[220, 58])
    g.link(adv, 0, decode, 0)
    g.link(vvae, 0, decode, 1)

    combine = g.add(
        "VHS_VideoCombine", (1200, -520),
        # VHS reads widgets positionally: the six required widgets first, then
        # the format-specific ones h264-mp4 appends (pix_fmt, crf,
        # save_metadata, trim_to_audio).  Passing a settings dict here makes
        # ComfyUI hand the whole dict to frame_rate and fail validation.
        [FPS, 0, "CosmicCrafter_AudioReactive", "video/h264-mp4", False, True,
         "yuv420p", 19, True, False],
        inputs=[("images", "IMAGE"), ("audio", "AUDIO")],
        outputs=[("Filenames", "VHS_FILENAMES")], size=[420, 500],
    )
    g.link(decode, 0, combine, 0)
    g.link(audio, 0, combine, 1)

    # Preview of the mask the sampler actually receives - the fastest way to
    # tell whether the reaction is landing before spending a full sample.
    if subject is None:
        return g.to_dict("CosmicCrafter Audio-Reactive Music Video")

    preview = g.add("PreviewImage", (260, 60), None,
                    inputs=[("images", "IMAGE")], size=[300, 260],
                    title="Subject mask check")
    if subject_preview_slot is not None:
        g.link(subject, subject_preview_slot, preview, 0)
    else:
        # SAM3_Detect returns masks only; render the mask to view it.
        to_image = g.add("MaskToImage", (60, 60), None,
                         inputs=[("mask", "MASK")],
                         outputs=[("IMAGE", "IMAGE")], size=[200, 40])
        g.link(subject, subject_mask_slot, to_image, 0)
        g.link(to_image, 0, preview, 0)

    return g.to_dict("CosmicCrafter Audio-Reactive Subject Lock")


#: Segmenter -> output filename.  Core SAM 3 is the default; the RMBG variant is
#: the fallback for when you would rather not load a 1.7 GB SAM checkpoint.
#: name -> (segmenter, subject_lock).  The native graph comes first: it renders
#: a whole video driven by H3's own audio conditioning.  The subject-lock graphs
#: are the compositing effect, which suppresses that motion where the mask holds.
VARIANTS = {
    "MusicVideo_Native": ("sam3", False),
    "SubjectLock": ("sam3", True),
    "SubjectLock_RMBG": ("rmbg", True),
}


def variant_filename(name):
    """Filename a variant is written under, in the repo and in ComfyUI alike."""
    return f"CosmicCrafter_AudioReactive_{name}.json"


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate and install the CosmicCrafter audio-reactive workflows.")
    parser.add_argument("--install-to", default=None,
                        help="ComfyUI install root, or its user/default/workflows dir")
    parser.add_argument("--no-install", action="store_true",
                        help="only write to workflows/, do not install into ComfyUI")
    args = parser.parse_args(argv)

    OUT_DIR.mkdir(exist_ok=True)
    written = []
    for name, (segmenter, subject_lock) in VARIANTS.items():
        filename = variant_filename(name)
        graph = build_graph(segmenter, subject_lock=subject_lock)

        problems = validate(graph)
        if problems:
            raise SystemExit(
                f"{filename} validation failed:\n  " + "\n  ".join(problems)
            )

        out = OUT_DIR / filename
        out.write_text(json.dumps(graph, indent=2), encoding="utf-8")
        written.append(out)
        print(f"wrote {out.relative_to(ROOT)} "
              f"({len(graph['nodes'])} nodes, {len(graph['links'])} links)")

    if args.no_install:
        return

    target = find_comfyui_workflows(args.install_to)
    if target is None:
        print("\nComfyUI workflow directory not found - skipping install.")
        print("Pass --install-to <ComfyUI root> or set $COMFYUI_USER_WORKFLOWS "
              "to have these appear in ComfyUI's sidebar.")
        return

    dest = target / INSTALL_SUBDIR
    dest.mkdir(parents=True, exist_ok=True)
    for path in written:
        shutil.copy2(path, dest / path.name)
    print(f"\ninstalled {len(written)} workflow(s) to {dest}")
    print(f"ComfyUI lists them under Workflows -> {INSTALL_SUBDIR} "
          "(refresh the browser to pick up new files).")


if __name__ == "__main__":
    main()
