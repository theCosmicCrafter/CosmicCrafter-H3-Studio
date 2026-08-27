"""Integrity checks for the shipped audio-reactive workflows.

The hand-written SAM graphs shipped with dangling link ids (ComfyUI drops those
links silently, so the graph *looks* wired but is not) and routed the audio
pulse through ``SetLatentNoiseMask``, which cannot address H3's nested AV
latent.  These tests fail on both classes of defect.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / "workflows"
NATIVE = WORKFLOW_DIR / "CosmicCrafter_AudioReactive_MusicVideo_Native.json"
PRIMARY = WORKFLOW_DIR / "CosmicCrafter_AudioReactive_SubjectLock.json"
RMBG_VARIANT = WORKFLOW_DIR / "CosmicCrafter_AudioReactive_SubjectLock_RMBG.json"

#: Graphs that composite a locked subject against a reacting background.  The
#: native graph deliberately has none of this machinery.
LOCK_VARIANTS = (PRIMARY, RMBG_VARIANT)


def _lock_workflows():
    return [p for p in LOCK_VARIANTS if p.is_file()]

#: Nodes that can supply the subject cutout, depending on the variant.
#: SAM3_Detect is ComfyUI core; RMBG is ComfyUI-RMBG.
SEGMENTER_NODES = {"SAM3_Detect", "RMBG"}

#: comfyui-sam3's nodes run in an isolated pixi env whose bundled comfy_kitchen
#: can lag the host's, failing on import with
#: "module 'comfy_kitchen' has no attribute 'int8_attention_is_available'".
#: Core's SAM 3 (comfy_extras/nodes_sam3.py) has no such env, so use that.
ISOLATED_ENV_NODES = {"SAM3Grounding", "LoadSAM3Model"}

#: Nodes that cannot address an H3 nested AV latent.  ``SetLatentNoiseMask``
#: stores a bare [N,1,H,W] tensor, so the sampler substitutes an all-ones mask
#: for the audio stream and trilinearly smears the video mask across H3's
#: ~3.4:1 temporal compression - which erases beat transients.
FORBIDDEN_NODES = {"SetLatentNoiseMask"}


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _workflows():
    """Every UI-format graph in workflows/.

    API-format files (a node-id -> {class_type, inputs} map, with no "nodes"
    key) are skipped: they are a different schema, produced for direct
    submission rather than for opening on the canvas, and these checks are all
    about canvas-format defects.
    """
    out = []
    for path in sorted(WORKFLOW_DIR.glob("*.json")):
        try:
            graph = _load(path)
        except json.JSONDecodeError:
            continue
        if isinstance(graph, dict) and "nodes" in graph:
            out.append(path)
    return out


def test_primary_workflow_exists():
    assert PRIMARY.is_file(), (
        "run tools/build_audio_reactive_workflow.py to generate it"
    )


def test_rmbg_variant_exists():
    assert RMBG_VARIANT.is_file(), (
        "run tools/build_audio_reactive_workflow.py to generate it"
    )


def test_no_workflow_uses_the_isolated_sam3_environment():
    for path in _workflows():
        types = {n["type"] for n in _load(path)["nodes"]}
        clash = types & ISOLATED_ENV_NODES
        assert not clash, (
            f"{path.name} depends on comfyui-sam3's isolated env: {sorted(clash)}"
        )


def test_primary_variant_uses_core_sam3():
    types = {n["type"] for n in _load(PRIMARY)["nodes"]}
    assert "SAM3_Detect" in types
    # Text-prompted: the subject is named in a CLIPTextEncode.
    assert "CLIPTextEncode" in types


def test_rmbg_variant_needs_no_sam_checkpoint():
    types = {n["type"] for n in _load(RMBG_VARIANT)["nodes"]}
    assert "RMBG" in types
    assert "SAM3_Detect" not in types


def test_differential_diffusion_sits_between_model_and_guider():
    """A graded mask is only meaningful with Differential Diffusion.

    Without it the sampler blends latents by mask value on every step; with it
    each region starts denoising when the schedule reaches its value, so audio
    intensity maps to amount of change rather than to a per-step blend.
    """
    for path in _lock_workflows():
        graph = _load(path)
        by_id = {n["id"]: n for n in graph["nodes"]}

        diff = [n for n in graph["nodes"] if n["type"] == "DifferentialDiffusion"]
        assert len(diff) == 1, f"{path.name}: expected exactly one DifferentialDiffusion"

        guider = next(n for n in graph["nodes"] if n["type"] == "BasicGuider")
        model_link = guider["inputs"][0]["link"]
        source = next(by_id[l[1]] for l in graph["links"] if l[0] == model_link)
        assert source["type"] == "DifferentialDiffusion", (
            f"{path.name}: BasicGuider takes its model from {source['type']}, "
            "so the graded mask is not scheduled"
        )


def test_video_combine_widgets_are_flat_not_a_settings_dict():
    """VHS reads widgets positionally.

    Handing it a settings dict makes ComfyUI pass the whole dict to frame_rate
    and reject the prompt with 'float() argument must be ... not dict'.
    """
    for path in _workflows():
        for node in _load(path)["nodes"]:
            if node["type"] != "VHS_VideoCombine":
                continue
            widgets = node["widgets_values"]
            assert isinstance(widgets, list), f"{path.name}: widgets must be a list"
            assert not any(isinstance(w, dict) for w in widgets), (
                f"{path.name}: VHS_VideoCombine widgets contain a dict"
            )
            frame_rate, loop_count, prefix, fmt = widgets[:4]
            assert isinstance(frame_rate, (int, float))
            assert isinstance(loop_count, int)
            assert isinstance(prefix, str)
            assert fmt.startswith(("video/", "image/"))


def test_every_workflow_is_valid_json_with_the_expected_shape():
    for path in _workflows():
        graph = _load(path)
        for key in ("nodes", "links", "last_node_id", "last_link_id"):
            assert key in graph, f"{path.name} is missing '{key}'"


def test_no_workflow_has_dangling_links():
    for path in _workflows():
        graph = _load(path)
        node_ids = {n["id"] for n in graph["nodes"]}
        link_ids = {link[0] for link in graph["links"]}

        problems = []
        for link in graph["links"]:
            lid, src, _src_slot, dst, _dst_slot = link[:5]
            if src not in node_ids:
                problems.append(f"link {lid} originates at missing node {src}")
            if dst not in node_ids:
                problems.append(f"link {lid} targets missing node {dst}")

        for node in graph["nodes"]:
            for slot in node.get("inputs") or []:
                if slot.get("link") is not None and slot["link"] not in link_ids:
                    problems.append(
                        f"node {node['id']} ({node['type']}) input "
                        f"'{slot.get('name')}' -> dangling link {slot['link']}"
                    )
            for slot in node.get("outputs") or []:
                for lid in slot.get("links") or []:
                    if lid not in link_ids:
                        problems.append(
                            f"node {node['id']} ({node['type']}) output "
                            f"'{slot.get('name')}' -> dangling link {lid}"
                        )

        assert not problems, f"{path.name}:\n  " + "\n  ".join(problems)


def test_link_endpoints_address_real_slots():
    for path in _workflows():
        graph = _load(path)
        by_id = {n["id"]: n for n in graph["nodes"]}
        for link in graph["links"]:
            lid, src, src_slot, dst, dst_slot = link[:5]
            if src not in by_id or dst not in by_id:
                continue  # covered by the dangling-link test
            src_node, dst_node = by_id[src], by_id[dst]
            assert src_slot < len(src_node.get("outputs") or []), (
                f"{path.name}: link {lid} uses output slot {src_slot} of "
                f"{src_node['type']}, which has fewer outputs"
            )
            assert dst_slot < len(dst_node.get("inputs") or []), (
                f"{path.name}: link {lid} uses input slot {dst_slot} of "
                f"{dst_node['type']}, which has fewer inputs"
            )


def test_primary_workflow_uses_the_h3_aware_latent_mask():
    graph = _load(PRIMARY)
    types = {n["type"] for n in graph["nodes"]}
    assert "MiniMaxH3LatentNoiseMask" in types
    assert not (types & FORBIDDEN_NODES), (
        f"workflow uses H3-incompatible masking nodes: {types & FORBIDDEN_NODES}"
    )


def test_primary_workflow_chains_audio_into_the_latent_mask():
    """beats -> curve-to-mask -> composite -> latent noise mask -> sampler."""
    graph = _load(PRIMARY)
    by_id = {n["id"]: n for n in graph["nodes"]}

    def find(node_type):
        matches = [n for n in graph["nodes"] if n["type"] == node_type]
        assert len(matches) == 1, f"expected exactly one {node_type}"
        return matches[0]

    def source_of(node, slot_index):
        """Return the node feeding ``slot_index`` of ``node``."""
        link_id = node["inputs"][slot_index]["link"]
        assert link_id is not None, (
            f"{node['type']} input {slot_index} is not connected"
        )
        for link in graph["links"]:
            if link[0] == link_id:
                return by_id[link[1]]
        raise AssertionError(f"link {link_id} not found")

    noise_mask = find("MiniMaxH3LatentNoiseMask")
    composite = source_of(noise_mask, 1)          # mask input
    assert composite["type"] == "MiniMaxH3MaskComposite"

    subject = source_of(composite, 0)             # mask_a
    assert subject["type"] in SEGMENTER_NODES

    pulse = source_of(composite, 1)               # mask_b
    assert pulse["type"] == "MiniMaxH3AudioCurveToMask"

    analyze = source_of(pulse, 0)                 # curve
    assert analyze["type"] == "MiniMaxH3AudioAnalyze"
    assert source_of(analyze, 0)["type"] == "LoadAudio"

    # ...and the masked latent is what the sampler actually consumes.
    sampler = find("SamplerCustomAdvanced")
    assert source_of(sampler, 4)["type"] == "MiniMaxH3LatentNoiseMask"


def test_subject_mask_is_inverted_so_the_background_reacts():
    """invert_a must be on: SAM marks the subject, the pulse targets the rest."""
    graph = _load(PRIMARY)
    composite = next(n for n in graph["nodes"]
                     if n["type"] == "MiniMaxH3MaskComposite")
    operation, invert_a = composite["widgets_values"][0], composite["widgets_values"][1]
    assert operation == "multiply"
    assert invert_a is True


def test_sampler_noise_input_is_connected():
    """SamplerCustomAdvanced errors at runtime if NOISE is left dangling."""
    graph = _load(PRIMARY)
    sampler = next(n for n in graph["nodes"]
                   if n["type"] == "SamplerCustomAdvanced")
    assert sampler["inputs"][0]["name"] == "noise"
    assert sampler["inputs"][0]["link"] is not None


def test_pulse_mask_matches_the_generation_canvas():
    """Mask and latent canvas must agree so nothing is resampled en route."""
    graph = _load(PRIMARY)
    pulse = next(n for n in graph["nodes"]
                 if n["type"] == "MiniMaxH3AudioCurveToMask")
    i2v = next(n for n in graph["nodes"] if n["type"] == "MiniMaxH3ImageToVideo")

    pulse_w, pulse_h, pulse_frames = pulse["widgets_values"][:3]
    _prompt, i2v_w, i2v_h, i2v_frames = i2v["widgets_values"][:4]

    assert (pulse_w, pulse_h) == (i2v_w, i2v_h)
    assert pulse_frames == i2v_frames


def test_frame_count_sits_on_the_h3_grid():
    graph = _load(PRIMARY)
    i2v = next(n for n in graph["nodes"] if n["type"] == "MiniMaxH3ImageToVideo")
    frames = i2v["widgets_values"][3]
    assert frames % 17 == 5, f"{frames} is not on H3's 17k+5 frame grid"


def test_analyze_window_matches_the_clip_length():
    graph = _load(PRIMARY)
    analyze = next(n for n in graph["nodes"]
                   if n["type"] == "MiniMaxH3AudioAnalyze")
    i2v = next(n for n in graph["nodes"] if n["type"] == "MiniMaxH3ImageToVideo")
    # clip_frames is the second widget; a mismatch silently misaligns the curve.
    assert analyze["widgets_values"][1] == i2v["widgets_values"][3]


def test_latent_holds_the_source_before_it_is_masked():
    """The subject must be encoded into the latent before masking.

    MiniMaxH3ImageToVideo returns an *empty* AV latent - its still is keyframe
    conditioning, not latent content - so a mask applied straight to it
    preserves zeros and the "locked" subject decodes to flat grey.
    """
    for path in _lock_workflows():
        graph = _load(path)
        by_id = {n["id"]: n for n in graph["nodes"]}

        def source_of(node, slot):
            link_id = node["inputs"][slot]["link"]
            assert link_id is not None, f"{node['type']} input {slot} unconnected"
            return by_id[next(l[1] for l in graph["links"] if l[0] == link_id)]

        noise_mask = next(n for n in graph["nodes"]
                          if n["type"] == "MiniMaxH3LatentNoiseMask")
        upstream = source_of(noise_mask, 0)
        assert upstream["type"] == "MiniMaxH3SourceToLatent", (
            f"{path.name}: the noise mask receives a latent from "
            f"{upstream['type']}, so there is no source content to preserve"
        )

        # ...and it encodes the same image the segmenter looked at.
        image_node = source_of(upstream, 2)
        assert image_node["type"] == "LoadImage", (
            f"{path.name}: source encoder reads from {image_node['type']}"
        )
        # Look the image input up by name: SAM3_Detect takes it at slot 1
        # (after model), RMBG at slot 0.
        segmenter = next(n for n in graph["nodes"]
                         if n["type"] in SEGMENTER_NODES)
        image_slot = next(i for i, s in enumerate(segmenter["inputs"])
                          if s["name"] == "image")
        assert source_of(segmenter, image_slot)["id"] == image_node["id"], (
            f"{path.name}: the mask and the encoded source come from "
            "different images, so the subject would not line up"
        )


#: Input name -> which H3 VAE it must receive.  Swapping these fails at
#: runtime with a shape error at best, and silently wrong output at worst.
VAE_EXPECTATIONS = {
    "audio_vae": "audio",
    "vae": "video",
}

#: Nodes where a plain ``vae`` input means the AUDIO vae, not the video one.
#: VAEDecodeAudio names its input ``vae`` but decodes the audio stream, so the
#: name alone cannot decide which loader is correct.
AUDIO_VAE_NODES = {"VAEDecodeAudio", "VAEEncodeAudio"}


def test_every_vae_input_gets_the_right_h3_vae():
    for path in _workflows():
        graph = _load(path)
        by_id = {n["id"]: n for n in graph["nodes"]}
        links = {link[0]: link for link in graph["links"]}

        checked = 0
        for node in graph["nodes"]:
            for slot in node["inputs"]:
                if slot["type"] != "VAE" or not slot.get("link"):
                    continue
                expected = VAE_EXPECTATIONS.get(slot["name"])
                if node["type"] in AUDIO_VAE_NODES and slot["name"] == "vae":
                    expected = "audio"
                if expected is None:
                    continue
                loader = by_id[links[slot["link"]][1]]
                assert loader["type"] == "VAELoader", (
                    f"{path.name}: {node['type']}.{slot['name']} is fed by "
                    f"{loader['type']}"
                )
                name = loader["widgets_values"][0]
                assert expected in name, (
                    f"{path.name}: {node['type']}.{slot['name']} expects the "
                    f"{expected} VAE but is wired to {name}"
                )
                checked += 1

        assert checked >= 3, f"{path.name}: only {checked} VAE inputs checked"


# ---------------------------------------------------------------------------
# The native graph: H3's own audio conditioning, no masking
# ---------------------------------------------------------------------------

def test_native_workflow_exists():
    assert NATIVE.is_file(), (
        "run tools/build_audio_reactive_workflow.py to generate it"
    )


def test_native_workflow_has_no_masking_machinery():
    """H3 packs [text | cond | audio | video] into one attended sequence, so
    video tokens already read the song.  An external mask can only suppress the
    motion the model produces, so the native graph must carry none of it."""
    types = {n["type"] for n in _load(NATIVE)["nodes"]}
    for node in ("MiniMaxH3LatentNoiseMask", "MiniMaxH3MaskComposite",
                 "MiniMaxH3AudioCurveToMask", "MiniMaxH3SourceToLatent",
                 "DifferentialDiffusion", "SAM3_Detect", "RMBG",
                 "SetLatentNoiseMask"):
        assert node not in types, f"native graph should not contain {node}"


def test_native_workflow_binds_the_real_song_into_the_latent():
    """The song must reach the audio stream, or there is nothing to react to."""
    graph = _load(NATIVE)
    by_id = {n["id"]: n for n in graph["nodes"]}
    links = {link[0]: link for link in graph["links"]}

    song = next(n for n in graph["nodes"]
                if n["type"] == "MiniMaxH3SongMaskedAVContext")
    master = next(i for i in song["inputs"] if i["name"] == "master_audio")
    assert master["link"] is not None, "master_audio is not connected"
    assert by_id[links[master["link"]][1]]["type"] == "LoadAudio"

    # ...and that song-conditioned latent is what the sampler denoises.
    sampler = next(n for n in graph["nodes"]
                   if n["type"] == "SamplerCustomAdvanced")
    latent_in = next(i for i in sampler["inputs"] if i["name"] == "latent_image")
    assert by_id[links[latent_in["link"]][1]]["type"] == "MiniMaxH3SongMaskedAVContext"


def test_native_workflow_still_modulates_denoise_from_energy():
    """The one external control that helps rather than fights the model."""
    graph = _load(NATIVE)
    by_id = {n["id"]: n for n in graph["nodes"]}
    links = {link[0]: link for link in graph["links"]}

    scheduler = next(n for n in graph["nodes"] if n["type"] == "BasicScheduler")
    denoise = next(i for i in scheduler["inputs"] if i["name"] == "denoise")
    assert denoise["link"] is not None
    assert by_id[links[denoise["link"]][1]]["type"] == "MiniMaxH3AudioReactiveDenoise"


def test_every_workflow_connects_the_sampler_noise_input():
    """The shipped UTILITY example left this dangling, so it could never run."""
    for path in _workflows():
        graph = _load(path)
        sampler = next((n for n in graph["nodes"]
                        if n["type"] == "SamplerCustomAdvanced"), None)
        if sampler is None:
            continue
        noise = next(i for i in sampler["inputs"] if i["name"] == "noise")
        assert noise["link"] is not None, f"{path.name}: sampler noise unconnected"
        assert any(n["type"] == "RandomNoise" for n in graph["nodes"]), (
            f"{path.name}: no RandomNoise node"
        )
