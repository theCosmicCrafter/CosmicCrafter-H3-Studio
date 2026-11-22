"""H3 Context Windows: ComfyUI's MiniMax H3 context-window node with lengths snapped to H3's 17k+5 frame grid."""

from comfy_api.latest import io

from . import latents, store, timing

CATEGORY = "H3 Continuity"
NEEDS_CORE = ("This ComfyUI has no MiniMax H3 context windows (Comfy-Org/ComfyUI pull request 17425); update ComfyUI "
              "to use H3 Context Windows.")


def _core():
    try:
        from comfy_extras.nodes_context_windows import MiniMaxH3ContextWindowsNode
    except ImportError:
        return None
    return MiniMaxH3ContextWindowsNode


def apply(model, context_length, context_overlap, fuse_method, freenoise, split_conds_to_windows, core=None):
    """(model with windows, settings used); raises RuntimeError when ComfyUI lacks the core node."""
    core = core or _core()
    if core is None:
        raise RuntimeError(NEEDS_CORE)
    length, overlap = timing.window_settings(context_length, context_overlap)
    out = core.execute(model, length, overlap, fuse_method, freenoise, split_conds_to_windows=split_conds_to_windows)
    return out.args[0], {"context_length": length, "context_overlap": overlap}


class H3C_ContextWindows(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="H3C_ContextWindows",
            display_name="H3 Context Windows",
            category=CATEGORY,
            description="Sample a box longer than one window in overlapping H3 context windows. Wraps ComfyUI's "
                        "MiniMax H3 Context Windows, which keeps video, audio, first/last-frame guides and "
                        "references in step per window, and snaps length and overlap to H3's 17k+5 frame grid.",
            inputs=[
                io.Model.Input("model"),
                io.Int.Input("context_length", default=124, min=22, max=1000, step=17,
                             tooltip="Frames sampled together in one window; snapped to 17k+5."),
                io.Int.Input("context_overlap", default=39, min=5, max=1000, step=17,
                             tooltip="Frames shared by neighboring windows; snapped to 17k+5 and kept shorter "
                                     "than the window."),
                io.Combo.Input("fuse_method", options=["pyramid", "relative", "flat", "overlap-linear"],
                               default="pyramid", advanced=True),
                io.Boolean.Input("freenoise", default=True, advanced=True,
                                 tooltip="Shuffle noise per window so neighbors blend better."),
                io.Boolean.Input("split_conds_to_windows", default=False, advanced=True),
            ],
            outputs=[io.Model.Output(), io.String.Output(display_name="info")],
        )

    @classmethod
    def execute(cls, model, context_length, context_overlap, fuse_method, freenoise, split_conds_to_windows=False):
        model, used = apply(model, context_length, context_overlap, fuse_method, freenoise, split_conds_to_windows)
        return io.NodeOutput(model, f"H3 context windows: {used['context_length']} frames, "
                                    f"{used['context_overlap']} overlap")


def chain_latent(folder, manifest, first, last):
    """(nested latent, info) joining saved segments `first`..`last` (0 = the last saved one) of one continuing chain."""
    entries = {entry["index"]: entry for entry in manifest["segments"]}
    last = last or max(entries, default=0)
    if first not in entries or last not in entries or first > last:
        raise ValueError(f"H3 Join Chain: segments {first} to {last} are not all saved in this sequence")
    parts, played = [], 0
    for index in range(first, last + 1):
        entry = entries.get(index)
        if entry is None:
            raise ValueError(f"H3 Join Chain: segment {index} is not saved")
        if index < last and entry["frames"] - entry.get("context_frames", 0) != store.played_frames(entry):
            raise ValueError(f"H3 Join Chain: segment {index} dropped generated frames, so segment {index + 1} "
                             "can't continue it")
        video, audio = store.load_segment_latents(folder, entry)
        parts.append((video, audio, entry.get("context_frames", 0) if index > first else 0))
        played += store.played_frames(entry)
    joined = latents.join_chain(parts)
    return {"samples": joined}, f"H3 Join Chain: segments {first}-{last}, {played} frames"


class H3C_JoinChain(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="H3C_JoinChain",
            display_name="H3 Join Chain",
            category=CATEGORY,
            description="Join saved continuing segments into one H3 audio+video latent, each carried context kept "
                        "once. Refine it by noising it (denoise below 1) and sampling it with H3 Context Windows.",
            inputs=[
                io.String.Input("name", default="timeline", tooltip="Folder under output/h3_sequences."),
                io.Int.Input("first_segment", default=1, min=1),
                io.Int.Input("last_segment", default=0, min=0, tooltip="0 joins through the last saved segment."),
            ],
            outputs=[io.Latent.Output(), io.String.Output(display_name="info")],
        )

    @classmethod
    def execute(cls, name, first_segment, last_segment):
        from .nodes import sequences_root
        folder = store.sequence_dir(sequences_root(), name)
        latent, info = chain_latent(folder, store.load_manifest(folder), first_segment, last_segment)
        return io.NodeOutput(latent, info)
