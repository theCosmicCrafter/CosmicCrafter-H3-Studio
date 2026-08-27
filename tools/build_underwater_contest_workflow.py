"""Build the underwater bass-reactive H3 workflow for the Comfy H3 Sync Sound Challenge.

Contest constraints this targets (blog.comfy.org, submissions 2026-08-20 .. 09-01):

* "Final video output with **H3-generated synced audio**" - so the soundtrack is
  decoded from H3's own audio latent, not a track muxed in afterwards.  There is
  no ``LoadAudio`` anywhere in this graph.
* 90 seconds maximum.
* Judged partly on "multiple linked passes visible in the workflow structure"
  and "intentional parameter modification" - hence the two-pass design below.
* Judged on "workflow quality (annotated, clean, replicable)" - hence the
  MarkdownNote annotations.

Two linked passes
-----------------
**Pass 1** lets H3 do what it is actually built for: a single-stream DiT whose
packed sequence is ``[text | cond | audio | video]``, so it denoises the
underwater visuals *and* the whale song / sub-bass rumble jointly, attending
across both.  That is where the sync comes from - no external analysis involved.

**Pass 2** then analyses the audio H3 just produced, extracts the **bass** band,
and re-renders the video through a bass-driven latent noise mask while
*preserving the audio latent exactly*.  So the reactive elements are locked to
the very soundtrack that ships with the piece.

Widget values are ordered against the **live** ``/object_info`` schema rather
than hand-counted, because a mis-ordered ``widgets_values`` array is silently
accepted and then mis-read (that is how a settings dict once landed on VHS's
``frame_rate``).

Run from the repo root::

    python tools/build_underwater_contest_workflow.py
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "workflows"
#: ComfyUI moves between ports across restarts (Comfy Desktop and comfy-cli
#: pick different ones), and a bare instance answers on a port with no models
#: loaded.  So probe the candidates and take the first that reports a real
#: catalog rather than hardcoding one.
CANDIDATE_PORTS = (8188, 8189, 8000)


def _probe_server():
    override = os.environ.get("COMFYUI_URL")
    if override:
        return override
    for port in CANDIDATE_PORTS:
        url = f"http://127.0.0.1:{port}"
        try:
            with urllib.request.urlopen(url + "/system_stats", timeout=3):
                return url
        except Exception:
            continue
    raise SystemExit(
        "No ComfyUI reachable on ports " + ", ".join(map(str, CANDIDATE_PORTS))
        + ". Start it, or set COMFYUI_URL.")


SERVER = _probe_server()

#: The only declared types that render as a widget.  A COMBO arrives as a list
#: of options and is also a widget.  EVERYTHING else - MODEL, LATENT, FEATURE,
#: FREQUENCY_RANGE, VHS_BatchManager, any custom pack's own type - is a socket.
#:
#: This is deliberately a deny-list rather than an allow-list of link types: an
#: unrecognised custom type must default to "socket", because guessing "widget"
#: injects a phantom value into widgets_values and silently shifts every later
#: widget by one.
#: A combo arrives either as a literal list of options, or as the string
#: "COMBO" with the options in its options dict - both are widgets.
WIDGET_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO"}

FPS = 24
#: 12.4s at 24fps.  H3 snaps to its 17k+5 grid internally; the trained range is
#: ~124-362 frames.  Well inside the contest's 90s cap - raise for the final cut.
FRAMES = 124
WIDTH, HEIGHT = 672, 384

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
    "counterpoint, and pressure waves ripple the water on every low note.\n\n"
    "Deep resonant whale vocalizations, soothing sub-bass ocean rumble, "
    "ambient crystal glass harmonies, distant sonar pings."
)


def load_schema():
    """Fetch the live node catalog so widget order is derived, not guessed."""
    with urllib.request.urlopen(f"{SERVER}/object_info", timeout=120) as fh:
        return json.load(fh)


def _default_for(decl_type, opts):
    """Placeholder a linked widget keeps in ``widgets_values``."""
    if "default" in opts:
        return opts["default"]
    if isinstance(decl_type, list):
        return decl_type[0] if decl_type else ""
    return {"INT": 0, "FLOAT": 0.0, "BOOLEAN": False, "STRING": ""}.get(decl_type, "")


class Graph:
    """UI-format graph builder that orders widgets from the live schema."""

    def __init__(self, schema):
        self.schema = schema
        self.nodes = []
        self.links = []
        self.groups = []
        self._node_id = 0
        self._link_id = 0
        self._by_id = {}

    def add(self, node_type, pos, values=None, links=None, size=None, title=None,
            color=None, extra_widgets=()):
        """Register a node from ``{input_name: value}`` and ``{input_name: (src, slot)}``.

        Inputs are walked in the schema's own order: a linked input becomes a
        socket, an unlinked widget-typed input contributes its value to
        ``widgets_values`` at the right index.
        """

        values = dict(values or {})
        links = dict(links or {})

        spec = self.schema.get(node_type)
        if spec is None:
            raise KeyError(f"{node_type} is not in the live catalog")

        declared, optional = {}, set()
        declared.update(spec["input"].get("required", {}))
        for name, decl in spec["input"].get("optional", {}).items():
            declared[name] = decl
            optional.add(name)

        unknown = (set(values) | set(links)) - set(declared)
        if unknown:
            raise KeyError(f"{node_type} has no input(s) {sorted(unknown)}")

        self._node_id += 1
        inputs, widgets = [], []
        for name, decl in declared.items():
            decl_type = decl[0]
            opts = decl[1] if len(decl) > 1 and isinstance(decl[1], dict) else {}
            # forceInput inputs are sockets even when their type is a scalar -
            # they have no widget, so they must never contribute a widget value.
            is_widget = isinstance(decl_type, list) or decl_type in WIDGET_TYPES
            is_socket = (not is_widget) or bool(opts.get("forceInput"))

            if name in links:
                slot = {"name": name,
                        "type": decl_type if isinstance(decl_type, str) else "COMBO",
                        "link": None}
                if not is_socket:
                    # A widget converted to an input keeps its widget marker AND
                    # its placeholder value in widgets_values - drop the value and
                    # every later widget silently shifts down one index.
                    slot["widget"] = {"name": name}
                    widgets.append(values.get(name, _default_for(decl_type, opts)))
                    if opts.get("control_after_generate"):
                        widgets.append("fixed")
                inputs.append(slot)
            elif is_socket:
                if name not in optional:
                    raise KeyError(f"{node_type}.{name} is required but not linked")
                # An unlinked optional socket is simply omitted.
            else:
                if name not in values:
                    if name in optional:
                        continue
                    raise KeyError(f"{node_type}.{name} needs a value or a link")
                widgets.append(values[name])
                # The frontend appends a control widget right after a seed, so
                # every later widget index shifts by one if it is omitted.
                if opts.get("control_after_generate"):
                    widgets.append("fixed")

        node = {
            "id": self._node_id,
            "type": node_type,
            "pos": list(pos),
            "size": list(size or [340, 120]),
            "flags": {},
            "order": self._node_id - 1,
            "mode": 0,
            "inputs": inputs,
            "outputs": [
                {"name": n, "type": t, "links": []}
                for n, t in zip(spec["output_name"], spec["output"])
            ],
            "properties": {"Node name for S&R": node_type},
            "widgets_values": widgets,
        }
        # Some nodes grow extra widgets in the frontend that object_info does not
        # declare - VHS appends the chosen format's own settings, for instance.
        # Those are passed explicitly and appended in order.
        node["widgets_values"].extend(extra_widgets)

        if title:
            node["title"] = title
        if color:
            node["color"], node["bgcolor"] = color
        self.nodes.append(node)
        self._by_id[self._node_id] = node

        for name, (src_id, src_slot) in links.items():
            self._connect(src_id, src_slot, self._node_id, name)
        return self._node_id

    def note(self, pos, text, size=(360, 200), title="Note"):
        """A MarkdownNote - the contest scores annotated, replicable workflows."""
        self._node_id += 1
        self.nodes.append({
            "id": self._node_id, "type": "MarkdownNote", "pos": list(pos),
            "size": list(size), "flags": {}, "order": self._node_id - 1,
            "mode": 0, "inputs": [], "outputs": [], "title": title,
            "properties": {}, "widgets_values": [text],
            "color": "#432", "bgcolor": "#653",
        })
        return self._node_id

    def _connect(self, src_id, src_slot, dst_id, dst_name):
        src, dst = self._by_id[src_id], self._by_id[dst_id]
        if src_slot >= len(src["outputs"]):
            raise IndexError(f"{src['type']} has no output slot {src_slot}")
        slot = next((i for i, s in enumerate(dst["inputs"]) if s["name"] == dst_name), None)
        if slot is None:
            raise KeyError(f"{dst['type']} has no input socket {dst_name!r}")

        self._link_id += 1
        link_type = src["outputs"][src_slot]["type"]
        self.links.append([self._link_id, src_id, src_slot, dst_id, slot, link_type])
        src["outputs"][src_slot]["links"].append(self._link_id)
        dst["inputs"][slot]["link"] = self._link_id

    def to_dict(self, title):
        return {
            "id": title, "revision": 0,
            "last_node_id": self._node_id, "last_link_id": self._link_id,
            "nodes": self.nodes, "links": self.links, "groups": self.groups,
            "config": {}, "extra": {}, "version": 0.4,
        }


def validate(graph):
    """Catch the defects that load silently: dangling links, bad slots."""
    problems = []
    ids = {n["id"] for n in graph["nodes"]}
    link_ids = {l[0] for l in graph["links"]}
    by_id = {n["id"]: n for n in graph["nodes"]}

    for lid, src, src_slot, dst, dst_slot, _t in graph["links"]:
        if src not in ids:
            problems.append(f"link {lid} from missing node {src}")
        elif src_slot >= len(by_id[src]["outputs"]):
            problems.append(f"link {lid} bad output slot on {by_id[src]['type']}")
        if dst not in ids:
            problems.append(f"link {lid} to missing node {dst}")
        elif dst_slot >= len(by_id[dst]["inputs"]):
            problems.append(f"link {lid} bad input slot on {by_id[dst]['type']}")

    for node in graph["nodes"]:
        for s in node["inputs"]:
            if s.get("link") is None:
                problems.append(
                    f"node {node['id']} ({node['type']}) input '{s['name']}' unconnected")
            elif s["link"] not in link_ids:
                problems.append(
                    f"node {node['id']} ({node['type']}) input '{s['name']}' dangling")
    return problems


def build(schema):
    g = Graph(schema)

    # ================= PASS 1 - H3 generates video AND audio =================
    g.note((-2180, -760), (
        "## Pass 1 - H3 generates the audio\n\n"
        "No `LoadAudio` anywhere. H3 is a single-stream DiT whose packed "
        "sequence is `[text | cond | audio | video]`, so it denoises the "
        "abyss visuals **and** the whale song jointly, attending across both. "
        "That joint attention is where the sync comes from.\n\n"
        "The contest requires *H3-generated synced audio* - this is it."
    ), size=(420, 260), title="Pass 1 - native AV")

    unet = g.add("UNETLoader", (-2180, -460),
                 {"unet_name": "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
                  "weight_dtype": "default"},
                 size=[420, 82], title="H3 fl2va")

    # Non-default: SolAttn only engages from 20%-90% of the schedule, so the
    # early structure-forming steps stay at full precision.
    sol = g.add("SolAttnPatch", (-2180, -330), {
        "tau": 1.0, "start_percent": 0.2, "end_percent": 0.9, "min_tokens": 4096,
        "int8_qk": True, "sink_conditioning": "exact_kv_and_rows", "morton": False,
        "morton_curve": "2d_frame", "int8_pv": True, "verbose": False,
        "use_tma": False, "dense_blocks": "", "tau_profile": "",
    }, links={"model": (unet, 0)}, size=[420, 330], title="Sol-Attn (20-90%)")

    # H3's two streams run on different schedules; without this shift the audio
    # denoises on the video's timetable and the sync degrades.
    shift = g.add("MiniMaxH3SigmaShift", (-2180, 60),
                  {"shift_video": 12.0, "shift_audio": 3.0},
                  links={"model": (sol, 0)}, size=[420, 82],
                  title="Sigma shift 12 / 3")

    clip = g.add("CLIPLoader", (-2180, 190),
                 {"clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
                  "type": "minimax", "device": "default"},
                 size=[420, 106])
    vvae = g.add("VAELoader", (-2180, 340),
                 {"vae_name": "minimax_h3_video_vae_fp16.safetensors"},
                 size=[420, 58], title="Video VAE")
    avae = g.add("VAELoader", (-2180, 420),
                 {"vae_name": "minimax_h3_audio_vae_fp32.safetensors"},
                 size=[420, 58], title="Audio VAE")

    timing = g.add("CosmicCrafterVideoTiming", (-2180, 520),
                   {"frame_rate": float(FPS), "seconds": 0.0, "frames": FRAMES},
                   size=[420, 106], title="Timing hub")

    i2v = g.add("MiniMaxH3ImageToVideo", (-1700, -460),
                {"prompt": PROMPT, "width": WIDTH, "height": HEIGHT},
                links={"clip": (clip, 0), "vae": (vvae, 0), "length": (timing, 2)},
                size=[460, 420], title="T2V - abyss + whale song")

    neg = g.add("ConditioningZeroOut", (-1700, 60), {},
                links={"conditioning": (i2v, 0)}, size=[300, 46])

    # cfg 5 / 30 steps: H3 needs real guidance for the audio stream to commit to
    # the described sound world rather than drifting to generic ambience.
    ks1 = g.add("KSampler", (-1180, -460), {
        "seed": 262780983686272, "steps": 30, "cfg": 5.0,
        "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0,
    }, links={"model": (shift, 0), "positive": (i2v, 0), "negative": (neg, 0),
              "latent_image": (i2v, 1)}, size=[340, 280], title="Pass 1 sampler")

    sep1 = g.add("LTXVSeparateAVLatent", (-800, -460), {},
                 links={"av_latent": (ks1, 0)}, size=[300, 66],
                 title="Split AV")

    audio = g.add("VAEDecodeAudio", (-800, -340), {},
                  links={"samples": (sep1, 1), "vae": (avae, 0)},
                  size=[300, 46], title="H3-GENERATED AUDIO")

    frames1 = g.add("VAEDecode", (-800, -250), {},
                    links={"samples": (sep1, 0), "vae": (vvae, 0)},
                    size=[300, 46], title="Pass 1 frames")

    # ================= PASS 2 - bass drives a second video pass ==============
    g.note((-800, -120), (
        "## Pass 2 - the bass drives the picture\n\n"
        "`H3 Audio Analyze` reads the soundtrack **H3 just wrote** and pulls the "
        "low band out of it. That curve becomes an animated mask, and the video "
        "is re-rendered through it.\n\n"
        "`audio_mode: preserve` zeroes the audio stream's noise mask, so the "
        "score is carried through pass 2 bit-exact - the reactive picture is "
        "locked to the exact audio that ships with the video.\n\n"
        "Masks are built at the latent's exact shape and **aggregated** per "
        "latent frame (H3 packs 1,4,4,4,4 source frames per 5 tokens), so a "
        "one-frame transient survives instead of being interpolated away."
    ), size=(420, 320), title="Pass 2 - bass reactive")

    analyze = g.add("MiniMaxH3AudioAnalyze", (-360, -460), {
        "clip_start_seconds": 0.0, "beat_decay": 0.22, "sensitivity": 1.3,
    }, links={"audio": (audio, 0), "clip_frames": (timing, 2)},
        size=[340, 190], title="Analyze H3's own audio")

    # bass -> vignette: the abyss squeezes in from the edges on every low note,
    # leaving the whale in the centre readable. gamma 2.0 keeps it to the hits.
    pulse = g.add("MiniMaxH3AudioCurveToMask", (-360, -220), {
        "width": WIDTH, "height": HEIGHT, "spatial_mode": "vignette",
        "gamma": 2.0, "threshold": 0.10, "floor": 0.12, "ceiling": 0.85,
        "invert": False, "softness": 0.45, "feather": 12,
    }, links={"curve": (analyze, 4), "frames": (timing, 2)},
        size=[340, 320], title="Bass -> pressure-wave mask")

    # The mask can only preserve what the latent holds, so re-encode pass 1's
    # frames into the video stream first.  samples carries pass 1's audio through.
    src = g.add("MiniMaxH3SourceToLatent", (60, -460), {"crop": "center"},
                links={"samples": (ks1, 0), "vae": (vvae, 0), "image": (frames1, 0)},
                size=[340, 106], title="Pass 1 video -> latent")

    nmask = g.add("MiniMaxH3LatentNoiseMask", (60, -320), {
        "strength": 0.85, "temporal_aggregate": "max",
        "audio_mode": "preserve", "token_grid": 2,
    }, links={"samples": (src, 0), "mask": (pulse, 0)},
        size=[340, 160], title="H3 latent mask (audio preserved)")

    dd = g.add("DifferentialDiffusion", (60, -120), {"strength": 1.0},
               links={"model": (shift, 0)}, size=[340, 58],
               title="Graded mask -> denoise schedule")

    denoise = g.add("MiniMaxH3AudioReactiveDenoise", (-360, 160), {
        "mode": "peak", "min_strength": 0.35, "max_strength": 0.62, "invert": False,
    }, links={"curve": (analyze, 4)}, size=[340, 150],
        title="Bass -> pass 2 denoise")

    guider = g.add("BasicGuider", (460, -460), {},
                   links={"model": (dd, 0), "conditioning": (i2v, 0)},
                   size=[300, 46])
    sel = g.add("KSamplerSelect", (460, -380), {"sampler_name": "euler"},
                size=[300, 58])
    sched = g.add("BasicScheduler", (460, -290), {"scheduler": "simple", "steps": 30},
                  links={"model": (shift, 0), "denoise": (denoise, 0)},
                  size=[300, 106])
    noise = g.add("RandomNoise", (460, -150), {"noise_seed": 811247}, size=[300, 82])

    ks2 = g.add("SamplerCustomAdvanced", (820, -460), {},
                links={"noise": (noise, 0), "guider": (guider, 0), "sampler": (sel, 0),
                       "sigmas": (sched, 0), "latent_image": (nmask, 0)},
                size=[300, 130], title="Pass 2 sampler")

    sep2 = g.add("LTXVSeparateAVLatent", (1160, -460), {},
                 links={"av_latent": (ks2, 0)}, size=[300, 66])
    frames2 = g.add("VAEDecode", (1160, -350), {},
                    links={"samples": (sep2, 0), "vae": (vvae, 0)},
                    size=[300, 46], title="Final frames")

    g.add("VHS_VideoCombine", (1500, -460), {
        "loop_count": 0, "filename_prefix": "H3_Abyss_BassReactive",
        "format": "video/h264-mp4", "pingpong": False, "save_output": True,
    }, links={"images": (frames2, 0), "audio": (audio, 0),
              "frame_rate": (timing, 0)},
        # The format's own settings (pix_fmt/crf/save_metadata/trim_to_audio)
        # are NOT declared inputs - the frontend adds them per format. Emitting
        # them as trailing widget values spills them onto the optional sockets
        # (meta_batch, vae) during UI->API conversion, so they are left at the
        # format's defaults and set in the UI if needed.
        size=[420, 520], title="Final render (H3 audio)")

    g.note((1500, 120), (
        "## Submission checklist\n\n"
        "- Audio is decoded from H3's own latent - **no external track**\n"
        f"- {FRAMES} frames @ {FPS}fps = {FRAMES/FPS:.1f}s (cap is 90s)\n"
        "- Two linked passes, both visible above\n"
        "- Non-default: Sol-Attn 20-90%, sigma shift 12/3, cfg 5,\n"
        "  mask gamma 2.0 / gate 0.10, denoise band 0.35-0.62\n\n"
        "Submit the **workflow .json** alongside the video."
    ), size=(420, 280), title="Contest checklist")

    return g.to_dict("H3 Abyss - Bass Reactive (Sync Sound Challenge)")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--install-to", default=None)
    ap.add_argument("--no-install", action="store_true")
    args = ap.parse_args(argv)

    graph = build(load_schema())
    problems = validate(graph)
    if problems:
        raise SystemExit("validation failed:\n  " + "\n  ".join(problems))

    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / "H3_Abyss_BassReactive_Contest.json"
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
