"""Move an animated particle mask from a ref_image slot to a ref_video slot.

The bug
-------
``MiniMaxH3ReferenceToVideo`` treats every ``ref_images`` slot as a single
still.  From ``comfy_extras/nodes_minimax_h3.py``::

    resized = _resize(img[:1], tw, th, "disabled")

``img[:1]`` - the first frame, and only the first frame.  So an animated
``ParticleEmissionMask`` batch (particles emitting at a rate driven by the audio)
is collapsed to one static frame before the model ever sees it, and every bit of
the audio reactivity is discarded.

The ``ref_videos`` slots keep the whole batch::

    frames = _resize(video_frames, cw, ch, "disabled")   # no [:1]
    while n % 17 != 5: n -= 1                            # trimmed to H3's grid
    z = vae.encode(frames)

The fix
-------
Re-point the particle output at ``ref_videos.ref_video_0`` and take
``ParticleEmissionMask``'s **IMAGE** output (slot 1) rather than its MASK,
because ``ref_video`` is an image input.

Also raises ``particle_count`` and switches the emitter modulation's easing to
``linear``, so the emission rate tracks the audio curve directly instead of
being eased into a smooth ramp.

Usage::

    python tools/patch_particle_ref_video.py <in.json> [-o <out.json>]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REF2VA = "MiniMaxH3ReferenceToVideo"
PARTICLES = "ParticleEmissionMask"

#: ParticleEmissionMask outputs (MASK, IMAGE); ref_video wants an IMAGE.
PARTICLE_IMAGE_SLOT = 1

#: H3 needs at least 5 reference-video frames and trims to n % 17 == 5.
MIN_REF_VIDEO_FRAMES = 5


def find_nodes(graph, class_type):
    return [nid for nid, n in graph.items() if n.get("class_type") == class_type]


def _find_input(graph, node_id, name):
    """The (source_id, slot) feeding ``name``, or None."""
    val = graph[node_id]["inputs"].get(name)
    if isinstance(val, list) and len(val) == 2:
        return val
    return None


def give_the_sim_real_frames(graph, notes):
    """Feed the particle sim a mask batch, not a single still.

    ``mask_base.py``::

        num_frames = masks_np.shape[0]

    The simulation runs for exactly as many frames as its ``masks`` input has.
    Wired to ``LoadImage`` that is **one** frame, so the sim produces a single
    still and there is no animation to react with - the emission-rate
    modulation is computed and then thrown away.

    ``EmptyMaskFromAudio`` sizes a mask batch from the audio itself, which is
    also exactly the clip length, so the particles run the whole clip.
    """

    par_id = find_nodes(graph, PARTICLES)[0]
    masks_src = _find_input(graph, par_id, "masks")
    if masks_src is None:
        notes.append("particle 'masks' input is not linked - left alone")
        return

    src_class = graph[str(masks_src[0])]["class_type"]
    if src_class != "LoadImage":
        notes.append(f"particle 'masks' already comes from {src_class} - left alone")
        return

    # Reuse the graph's own audio / timing / resolution so the batch lines up.
    audio_id = next((nid for nid in find_nodes(graph, "AudioTrim")), None)
    if audio_id is None:
        audio_id = next((nid for nid in find_nodes(graph, "LoadAudio")), None)
    timing_id = next((nid for nid in find_nodes(graph, "CosmicCrafterVideoTiming")), None)
    res_id = next((nid for nid in find_nodes(graph, "ResolutionSelector")), None)
    if not (audio_id and timing_id and res_id):
        notes.append("could not find audio/timing/resolution nodes - "
                     "particle frame count left as-is")
        return

    new_id = str(max(int(k) for k in graph) + 1)
    graph[new_id] = {
        "inputs": {
            "audio": [audio_id, 0],
            "frame_rate": [timing_id, 0],
            "width": [res_id, 0],
            "height": [res_id, 1],
        },
        "class_type": "EmptyMaskFromAudio",
        "_meta": {"title": "Mask batch sized from the audio"},
    }
    graph[par_id]["inputs"]["masks"] = [new_id, 0]
    notes.append(
        f"added EmptyMaskFromAudio[{new_id}] -> {PARTICLES}[{par_id}].masks "
        "(the sim ran 1 frame off LoadImage; now it runs the whole clip)")


def patch(graph):
    """Returns (graph, [notes]).  Raises if the graph is not the expected shape."""
    notes = []

    ref_ids = find_nodes(graph, REF2VA)
    if not ref_ids:
        raise SystemExit(f"no {REF2VA} node in this graph")
    par_ids = find_nodes(graph, PARTICLES)
    if not par_ids:
        raise SystemExit(f"no {PARTICLES} node in this graph")

    # Fix the frame count FIRST - re-pointing a 1-frame batch at ref_video
    # would just trade a frozen reference for a rejected one (H3 needs >= 5).
    give_the_sim_real_frames(graph, notes)

    ref_id, par_id = ref_ids[0], par_ids[0]
    ref_inputs = graph[ref_id]["inputs"]

    # Every ref_image slot fed by the particle node is a frozen first frame.
    frozen = [
        name for name, val in ref_inputs.items()
        if name.startswith("ref_images.")
        and isinstance(val, list) and len(val) == 2 and str(val[0]) == par_id
    ]
    if not frozen:
        notes.append(
            f"particle node {par_id} was not on a ref_image slot - nothing frozen")
    for name in frozen:
        del ref_inputs[name]
        notes.append(f"removed {name} (was collapsing the batch to frame 0)")

    # Re-point at the first free ref_video slot, taking the IMAGE output.
    used = {n for n in ref_inputs if n.startswith("ref_videos.")}
    slot = next(f"ref_videos.ref_video_{i}" for i in range(3)
                if f"ref_videos.ref_video_{i}" not in used)
    ref_inputs[slot] = [par_id, PARTICLE_IMAGE_SLOT]
    notes.append(f"wired {PARTICLES}[{par_id}] IMAGE output -> {slot}")

    # A ref_video needs real length, and the emission needs to actually move.
    par = graph[par_id]["inputs"]
    if isinstance(par.get("particle_count"), (int, float)) and par["particle_count"] < 400:
        notes.append(f"particle_count {par['particle_count']} -> 600 "
                     "(a ref_video is read as motion, so it needs density)")
        par["particle_count"] = 600

    for mid in find_nodes(graph, "EmitterEmissionRateModulation"):
        mod = graph[mid]["inputs"]
        if mod.get("temporal_easing") not in (None, "linear"):
            notes.append(f"node {mid} temporal_easing "
                         f"{mod['temporal_easing']!r} -> 'linear' "
                         "(easing smooths the audio curve into a ramp)")
            mod["temporal_easing"] = "linear"

    return graph, notes


def check_length(graph, notes):
    """Warn if the clip is too short for a reference video to survive trimming."""
    for nid in find_nodes(graph, REF2VA):
        length = graph[nid]["inputs"].get("length")
        if isinstance(length, (int, float)) and length < MIN_REF_VIDEO_FRAMES:
            notes.append(f"WARNING: {REF2VA}[{nid}] length={length} is below the "
                         f"{MIN_REF_VIDEO_FRAMES}-frame minimum for a ref_video")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("workflow", help="API-format workflow JSON")
    ap.add_argument("-o", "--out", default=None)
    args = ap.parse_args(argv)

    src = Path(args.workflow)
    graph = json.loads(src.read_text(encoding="utf-8"))
    graph, notes = patch(graph)
    check_length(graph, notes)

    out = Path(args.out) if args.out else src.with_name(src.stem + "_refvideo.json")
    out.write_text(json.dumps(graph, indent=2), encoding="utf-8")

    print(f"wrote {out}")
    for n in notes:
        print(f"  - {n}")
    return out


if __name__ == "__main__":
    main()
