"""ComfyUI nodes: H3 Sequence, H3 Continue, H3 Continuation Model and H3 Save Segment."""

import copy
import datetime
import json
import os
import threading
from dataclasses import dataclass

import torch

import folder_paths
from comfy_api.latest import io, ui

from . import audio_tracks, bridges, latents, media, store, timing

CATEGORY = "H3 Continuity"
SequenceType = io.Custom("H3C_SEQUENCE")
SegmentType = io.Custom("H3C_SEGMENT")
# ponytail: serialize local saves/exports; use per-sequence locks if concurrent exports become common.
SEQUENCE_LOCK = threading.RLock()
# The Timeline hands H3 Save these record keys for this save only; saved entries never hold them.
UNSAVED = ("splice", "replace", "soundtrack", "export_error", "layer_ids")
# Frames of footage a candidate's previews show on each side of it.
PREVIEW_FRAMES = 48


def sequences_root():
    return os.path.join(folder_paths.get_output_directory(), "h3_sequences")


@dataclass
class SequenceRef:
    name: str
    folder: str
    index: int
    base: dict | None
    video: torch.Tensor | None
    audio: torch.Tensor | None


@dataclass
class SegmentPlan:
    sequence: SequenceRef
    context_frames: int
    carried_ticks: int
    frames: int
    latent_size: tuple
    carried_video: torch.Tensor | None
    carried_audio: torch.Tensor | None
    description: str = ""
    timeline: dict | None = None
    preserve_following: bool = False
    ending_video: torch.Tensor | None = None
    ending_audio: torch.Tensor | None = None
    timeline_complete: bool = False
    carried_audio_start: int = 0
    # The Timeline's box ids in order: saving numbers every saved segment by its box (store.align).
    box_order: list | None = None
    # One queued regeneration's consent, never persisted into a take's metadata.
    regeneration: dict | None = None
    # A Timeline with several videos in a clip: puts each clip's stack in its segment's place (stacks.restacker).
    restack: object = None


def _plural(count, word):
    return f"{word}{'s' if count != 1 else ''}"


def prepare_segment(sequence, latent, context_frames, carry_audio, positive=None, negative=None, node="H3 Continue", *, audio_context_frames=0,
                    noise_vae=None, audio_feather=0):
    """Carries the end of the previous segment into `latent`. Returns the latent, the conditionings
    without guides inside the carried frames, the SegmentPlan for H3 Save Segment and the number of
    removed guides. Without a previous latent nothing is carried and `latent` is returned as is."""
    video, _ = latents.split_h3_latent(latent, node)
    frames = timing.frames_for_tokens(video.shape[2])
    size = tuple(video.shape[3:])
    if sequence.video is None:
        return latent, positive, negative, SegmentPlan(sequence, 0, 0, frames, size, None, None), 0
    context = int(context_frames)
    out, carried_video, carried_audio, ticks = latents.build_continuation(
        latent, sequence.video, sequence.audio, context, carry_audio, node=node, audio_context_frames=audio_context_frames,
        noise_vae=noise_vae, audio_feather=audio_feather)
    positive, removed_positive = latents.drop_guides_before(positive, context)
    negative, removed_negative = latents.drop_guides_before(negative, context)
    plan = SegmentPlan(sequence, context, ticks, frames, size, carried_video, carried_audio)
    plan.carried_audio_start = timing.ticks_for_frames(context) - ticks if ticks else 0
    return out, positive, negative, plan, max(removed_positive, removed_negative)


class H3C_Sequence(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="H3C_Sequence",
            hidden=[io.Hidden.extra_pnginfo],
            display_name="H3 Sequence",
            category=CATEGORY,
            description="Deprecated: use H3 Timeline. Picks the long-video sequence and the segment this run "
                        "continues. Connect sequence to H3 Continue and last_frame to your first-frame, reference "
                        "or prompt nodes.",
            is_deprecated=True,
            inputs=[
                io.String.Input("name", default="sequence", tooltip="Folder under output/h3_sequences."),
                io.Int.Input("continue_from", default=-1, min=-1, max=9999,
                             tooltip="-1 continues the latest segment. N continues segment N; saving replaces "
                                     "N+1 and later, keeping the old takes in takes/. 0 starts over as segment 1."),
                io.Image.Input("start_image", optional=True,
                               tooltip="Returned as last_frame when there is no previous segment, so segment 1 "
                                       "can use the same wiring."),
            ],
            outputs=[
                SequenceType.Output(display_name="sequence"),
                io.Image.Output(display_name="last_frame"),
                io.String.Output(display_name="previous_description"),
                io.String.Output(display_name="info"),
            ],
        )

    @classmethod
    def fingerprint_inputs(cls, name, continue_from, **kwargs):
        try:
            folder = store.sequence_dir(sequences_root(), name)
        except (AttributeError, ValueError):
            # a linked name arrives as None, so the manifest is unknown: always run rather than reuse a stale sequence
            return float("nan")
        return f"{store.manifest_fingerprint(folder)}:{continue_from}"

    @classmethod
    def execute(cls, name, continue_from, start_image=None) -> io.NodeOutput:
        from .timeline_api.service import authorize_sequence, sequence_owner
        authorize_sequence(name, sequence_owner(cls), "sequence")
        folder = store.sequence_dir(sequences_root(), name)
        name = os.path.basename(folder)
        manifest = store.load_manifest(folder)
        base, index = store.resolve_base(manifest, continue_from)
        video = audio = None
        description = ""
        if base is None:
            last_frame = start_image if start_image is not None else torch.zeros(1, 64, 64, 3)
        else:
            video, audio = store.load_segment_latents(folder, base)
            last_frame = store.load_last_frame(folder, base)
            if last_frame is None:
                width, height = latents.pixel_size(video)
                last_frame = torch.zeros(1, height, width, 3)
            description = base.get("description", "")
        count = len(manifest["segments"])
        info = f"sequence '{name}': "
        info += f"{count} {_plural(count, 'segment')}, {store.sequence_seconds(manifest):.1f} s. " if count else "new. "
        info += f"This run writes segment {index}" + (f", continuing from segment {base['index']}." if base else ".")
        if index <= count:
            moved = f"segments {index}-{count}" if count > index else f"segment {index}"
            info += f" Saving it moves {moved} to takes/."
        return io.NodeOutput(SequenceRef(name, folder, index, base, video, audio), last_frame, description, info)


class H3C_Continue(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="H3C_Continue",
            display_name="H3 Continue",
            category=CATEGORY,
            description="Deprecated: use H3 Timeline. Place between the H3 conditioning node and the sampler. "
                        "Copies the end of the previous segment's latent (video and audio) into the start of this "
                        "run and freezes it, so the new segment continues the motion and sound. On the first "
                        "segment it changes nothing.",
            is_deprecated=True,
            inputs=[
                SequenceType.Input("sequence"),
                io.Latent.Input("latent", tooltip="This run's H3 audio+video latent, e.g. from MiniMax H3 Image to "
                                                  "Video or Reference to Video."),
                io.Combo.Input("context_frames", options=list(timing.CONTEXT_OPTIONS), default="39",
                               tooltip="Frames carried from the previous segment: 22 = 0.9 s, 39 = 1.6 s, 90 = 3.75 s, "
                                       "141 = 5.9 s. Longer carries more memory but leaves fewer new frames."),
                io.Boolean.Input("carry_audio", default=True,
                                 tooltip="Also carry and freeze the matching audio. Off: the whole soundtrack "
                                         "is generated fresh."),
                io.Conditioning.Input("positive", optional=True,
                                      tooltip="Guides that land inside the carried frames are removed."),
                io.Conditioning.Input("negative", optional=True),
                io.Int.Input('audio_context_frames', optional=True, default=0, min=0,
                             tooltip='Incoming audio context in 24 fps frames; 0 follows video. Longer requests are bounded to the video context. Ending pins stay full length.'),
            ],
            outputs=[
                io.Latent.Output(display_name="latent"),
                io.Conditioning.Output(display_name="positive"),
                io.Conditioning.Output(display_name="negative"),
                SegmentType.Output(display_name="segment"),
                io.String.Output(display_name="info"),
            ],
        )

    @classmethod
    def execute(cls, sequence, latent, context_frames, carry_audio, positive=None, negative=None, audio_context_frames=0) -> io.NodeOutput:
        out, positive, negative, plan, removed = prepare_segment(
            sequence, latent, context_frames, carry_audio, positive, negative, audio_context_frames=audio_context_frames)
        frames = plan.frames
        if sequence.video is None:
            info = (f"Segment {sequence.index}: first segment, nothing carried; "
                    f"{frames} frames ({timing.seconds(frames):.2f} s).")
            return io.NodeOutput(out, positive, negative, plan, info)
        context, ticks = plan.context_frames, plan.carried_ticks
        new = frames - context
        info = (f"Segment {sequence.index}: carrying the last {context} frames ({timing.seconds(context):.2f} s)"
                + (f" and {ticks} audio ticks" if ticks else ", video only")
                + f" of segment {sequence.base['index']}; {new} new frames ({timing.seconds(new):.2f} s).")
        if removed:
            info += f" Removed {removed} {_plural(removed, 'guide')} inside the carried frames."
        if plan.carried_audio_start:
            info += f" Audio frozen at target ticks {plan.carried_audio_start}–{plan.carried_audio_start + ticks}."
        return io.NodeOutput(out, positive, negative, plan, info)


class H3C_ContinuationModel(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="H3C_ContinuationModel",
            display_name="H3 Continuation Model",
            category=CATEGORY,
            description="Samples boxes that continue the box before (and bridges) with continuation_model, for "
                        "example the model with a LoRA trained for continuations, and every other box with model.",
            inputs=[
                io.Model.Input("model", tooltip="The model for boxes that start fresh or cut."),
                SegmentType.Input("segment", tooltip="From H3 Timeline or H3 Continue."),
                io.Model.Input("continuation_model", optional=True,
                               tooltip="The model for continuing boxes. Unconnected: every box uses model."),
            ],
            outputs=[io.Model.Output(display_name="model")],
        )

    @classmethod
    def execute(cls, model, segment, continuation_model=None) -> io.NodeOutput:
        continues = segment.carried_video is not None
        return io.NodeOutput(continuation_model if continues and continuation_model is not None else model)


class H3C_SigmasTail(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="H3C_SigmasTail",
            display_name="H3 Sigmas Tail",
            category=CATEGORY,
            description="Experimental. Raises (or lowers) the last noise levels before zero, so a distilled model "
                        "settles less fine detail in its final step. With segment, only continuing boxes change.",
            inputs=[
                io.Sigmas.Input("sigmas"),
                io.Int.Input("tail_steps", default=3, min=1, max=20, tooltip="Levels before the final zero to move."),
                io.Float.Input("strength", default=0.5, min=-0.9, max=3.0, step=0.05,
                               tooltip="Above 0 raises the tail toward the level before it; 0 changes nothing."),
                SegmentType.Input("segment", optional=True,
                                  tooltip="From H3 Timeline: fresh and cut boxes keep their schedule."),
            ],
            outputs=[io.Sigmas.Output(display_name="sigmas")],
        )

    @classmethod
    def execute(cls, sigmas, tail_steps, strength, segment=None) -> io.NodeOutput:
        values = [float(value) for value in sigmas]
        end = len(values) - 1 if values and values[-1] == 0 else len(values)
        start = max(1, end - int(tail_steps))
        if not strength or (segment is not None and segment.carried_video is None) or start >= end:
            return io.NodeOutput(sigmas)
        # each moved level keeps its ratio to the level above the tail, raised to 1 / (1 + strength)
        anchor = values[start - 1]
        for index in range(start, end):
            values[index] = min(anchor * (values[index] / anchor) ** (1 / (1 + strength)),
                                values[index - 1] * 0.999)
        return io.NodeOutput(torch.tensor(values, dtype=sigmas.dtype, device=sigmas.device))


class H3C_SaveSegment(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="H3C_SaveSegment",
            hidden=[io.Hidden.extra_pnginfo],
            display_name="H3 Save Segment",
            category=CATEGORY,
            description="Saves this run as the next segment of the sequence: the latent for the next run and the "
                        "finished video without the repeated frames. Then rebuilds the full video.",
            is_output_node=True,
            inputs=[
                SegmentType.Input("segment"),
                io.Latent.Input("latent", tooltip="The sampler's output latent."),
                io.Image.Input("images", optional=True,
                               tooltip="Finished frames of this run, after any upscaling or grading. Needed for "
                                       "the segment and full videos."),
                io.Audio.Input("audio", optional=True, tooltip="Decoded audio of this run."),
                io.Float.Input("fps", default=24.0, min=1.0, max=240.0, step=0.001,
                               tooltip="Frame rate of images: 24 unless you interpolate."),
                io.String.Input("description", optional=True, force_input=True,
                                tooltip="Text stored with the segment and returned by H3 Sequence as "
                                        "previous_description, such as the prompt."),
                io.Boolean.Input("write_full_video", default=True,
                                 tooltip="Rebuild after each H3 Sequence segment. H3 Timeline exports when all current boxes finish."),
                io.Int.Input("crf", default=16, min=0, max=51,
                             tooltip="Quality of the saved videos (H.264 or HEVC CRF); lower is better and larger."),
                io.Combo.Input("color_space", options=["sRGB", "HDR", "HDR PQ"], default="sRGB", optional=True,
                               tooltip="Colorspace of the finished frames. HDR videos use 10-bit BT.2020."),
                io.Combo.Input("codec", options=list(media.CODECS), default="H.264", optional=True,
                               tooltip="Codec of the saved videos. H.264 plays everywhere. HEVC (10-bit for HDR) is "
                                       "what phones decode in hardware for HDR and what Apple players need for HLG; "
                                       "a browser without HEVC support can't play it in the Studio. The full video "
                                       "keeps the codec of its segments."),
                io.Image.Input("guide_frames", optional=True,
                               tooltip="The sampler's latent decoded as is (24 fps, before any second pass, upscale "
                                       "or grade). When connected, the next H3 Timeline box is guided from this "
                                       "run's last frame as it is in the latent it carries, not as finished, so a "
                                       "change to the finishing steps does not change the next box's first pass."),
            ],
            outputs=[io.String.Output(display_name="info")],
        )

    @classmethod
    def execute(cls, segment, latent, fps, write_full_video, crf, images=None, audio=None, description="", color_space="sRGB",
                codec="H.264", guide_frames=None) -> io.NodeOutput:
        sequence = segment.sequence
        from .timeline_api.service import authorize_sequence, sequence_owner
        authorize_sequence(sequence.name, sequence_owner(cls), "save_segment")
        video, audio_latent = latents.split_h3_latent(latent, "H3 Save Segment")
        frames = timing.frames_for_tokens(video.shape[2])
        if frames != segment.frames or tuple(video.shape[3:]) != segment.latent_size:
            raise ValueError(f"H3 Save Segment: this latent ({frames} frames) does not match the one H3 Continue or "
                             f"H3 Timeline prepared ({segment.frames} frames). Connect the output of the sampler that "
                             "received its latent.")
        notes = []
        if video.shape[0] > 1:
            notes.append(f"Batch of {video.shape[0]}: saved the first item only.")
        video, audio_latent = video[:1], audio_latent[:1]
        drift = latents.carried_difference(video, audio_latent, segment.carried_video, segment.carried_audio,
                                          audio_start=segment.carried_audio_start)
        drift = max(drift, latents.carried_difference(video, audio_latent, segment.ending_video,
                                                    segment.ending_audio, at_end=True))
        if drift > 1e-3:
            notes.append(f"Warning: the carried frames changed during sampling (max difference {drift:.3g}). "
                         "Make sure the sampler gets its latent from H3 Continue or H3 Timeline.")
        waveform = sample_rate = None
        if audio is not None:
            waveform, sample_rate = audio["waveform"][0, :2].float().cpu(), int(audio["sample_rate"])
        if "bridge" in (segment.timeline or {}):
            return cls.save_bridge(segment, video, audio_latent, frames, fps, crf, images, waveform, sample_rate,
                                   description, notes, color_space, codec)
        if "replacement" in (segment.timeline or {}):
            return cls.save_replacement(segment, video, audio_latent, frames, fps, crf, images, waveform, sample_rate,
                                        description, notes, color_space, codec)
        if "layer" in (segment.timeline or {}):
            return cls.save_layer(segment, video, audio_latent, frames, fps, crf, images, waveform, sample_rate,
                                  description, notes, color_space, codec)

        with SEQUENCE_LOCK:
            authorize_sequence(sequence.name, sequence_owner(cls), "save_segment")
            now = datetime.datetime.now()
            folder = sequence.folder
            os.makedirs(folder, exist_ok=True)
            manifest = store.load_manifest(folder)
            if segment.regeneration:
                from . import regeneration, timeline as rules
                recovery = segment.regeneration
                approved = regeneration.validate(folder, rules.parse(json.dumps(recovery["timeline"])),
                                                 recovery["settings"], recovery["box"], recovery["receipt"])
                archived = []
                stem = store.free_stem(folder, manifest, sequence.index)
            elif segment.box_order is not None:
                # A Timeline box replaces only its own earlier take; every other box keeps its saved segment.
                store.align(manifest, segment.box_order)
                archived = store.archive_box(folder, manifest, (segment.timeline or {}).get("box"), now)
                stem = store.free_stem(folder, manifest, sequence.index)
            else:
                archived = store.archive_from(folder, manifest, sequence.index, now, only=segment.preserve_following)
                stem = store.stem(sequence.index)
            context = segment.context_frames
            width, height = latents.pixel_size(video)
            entry = {
                "index": sequence.index, "stem": stem, "frames": frames,
                "context_frames": context, "carried_audio": segment.carried_ticks > 0,
                "latent_width": width, "latent_height": height, "video": None, "audio_sample_rate": sample_rate,
                "description": description or segment.description or "", "created": now.isoformat(timespec="seconds"),
            }
            if segment.carried_audio_start:
                entry['audio_pin'] = {'start_tick': segment.carried_audio_start, 'ticks': segment.carried_ticks}
            if segment.carried_video is not None and (sequence.base or {}).get("created"):
                # the render this box continued, for takes and lineage
                entry["carried_from"] = sequence.base["created"]
            if segment.timeline:
                entry["timeline"] = {key: value for key, value in segment.timeline.items() if key not in UNSAVED}
            # A box that drops generated frames plays only its first `played` new frames; its latent keeps them all.
            played = (segment.timeline or {}).get("played")
            if played is not None:
                entry["played"] = played
            try:
                if images is not None:
                    _write_video(folder, entry, images, fps, crf, waveform, sample_rate, notes, color_space, codec)
                if guide_frames is not None:
                    store.save_guide_frame(folder, entry, guide_frame(guide_frames, entry))
                store.save_segment(folder, entry, video, audio_latent, waveform)
                if segment.regeneration:
                    manifest = regeneration.commit(folder, entry, segment.regeneration, now)
                    archived = [sequence.index, *(item["number"] for item in approved["affected"])]
            except Exception:
                if segment.regeneration:
                    # This stem was free before the save; only this failed attempt's files can use it.
                    for file in store._stem_files(folder, stem):
                        os.remove(os.path.join(folder, file))
                raise
            if not segment.regeneration:
                manifest.pop("full_video", None)
                manifest["segments"].append(entry)
                manifest["segments"].sort(key=lambda e: e["index"])
            # The Timeline lists its bridges in `splice`; a Timeline record without it lists none.
            keys = (segment.timeline or {}).get("splice", {})
            if segment.timeline and not segment.regeneration:
                bridges.keep(folder, manifest, keys, now)
            if not segment.regeneration:
                store.write_manifest(folder, manifest)
            spliced = bridges.spliced(folder, manifest, keys) if keys else []

            new = store.played_frames(entry)
            count = len(manifest["segments"])
            info = (f"Saved segment {sequence.index} of '{sequence.name}': {new} new frames ({timing.seconds(new):.2f} s). "
                    f"Sequence: {count} {_plural(count, 'segment')}, {store.sequence_seconds(manifest, spliced):.1f} s.")
            if archived:
                info += f" Moved {_plural(len(archived), 'segment')} {', '.join(map(str, archived))} to takes/."
            if (write_full_video and not segment.timeline) or segment.timeline_complete:
                joined = (manifest if segment.box_order is None
                          else {**manifest, "segments": store.placed(manifest, len(segment.box_order))})
                info += " " + ((segment.timeline or {})['export_error'] if (segment.timeline or {}).get('export_error') else
                               rebuild_full_video(folder, sequence.name, joined, crf, spliced,
                                                 (segment.timeline or {}).get("soundtrack", ()), managed_owner=sequence_owner(cls),
                                                 replaced=_replaced(folder, manifest, segment.timeline),
                                                 background=segment.timeline is not None, restack=segment.restack))
            if notes:
                info += " " + " ".join(notes)
            return io.NodeOutput(info, ui=ui.PreviewText(info))

    @classmethod
    def save_bridge(cls, segment, video, audio_latent, frames, fps, crf, images, waveform, sample_rate, description,
                    notes, color_space="sRGB", codec="H.264"):
        """Saves a bridge run beside the segments, moving only the bridge's own earlier take."""
        sequence, record = segment.sequence, segment.timeline
        from .timeline_api.service import authorize_sequence, sequence_owner
        keys = record.get("splice", {})
        with SEQUENCE_LOCK:
            authorize_sequence(sequence.name, sequence_owner(cls), "save_segment")
            now = datetime.datetime.now()
            folder = sequence.folder
            os.makedirs(folder, exist_ok=True)
            manifest = store.load_manifest(folder)
            manifest.pop("full_video", None)
            store.align(manifest, segment.box_order)
            earlier = bridges.saved(manifest, record["bridge"])
            if earlier is not None:
                bridges.archive(folder, manifest, earlier, now)
            width, height = latents.pixel_size(video)
            entry = {
                "box": record["bridge"], "stem": bridges.stem(record["bridge"]), "frames": frames,
                "context_frames": segment.context_frames, "carried_audio": segment.carried_ticks > 0,
                "latent_width": width, "latent_height": height, "video": None, "audio_sample_rate": sample_rate,
                "description": description or segment.description or "", "created": now.isoformat(timespec="seconds"),
                "timeline": {key: value for key, value in record.items() if key not in UNSAVED}, "played": record["played"],
            }
            if segment.carried_audio_start:
                entry['audio_pin'] = {'start_tick': segment.carried_audio_start, 'ticks': segment.carried_ticks}
            if images is not None:
                _write_video(folder, entry, images, fps, crf, waveform, sample_rate, notes, color_space, codec)
            store.save_segment(folder, entry, video, audio_latent, waveform)
            manifest.setdefault("bridges", []).append(entry)
            bridges.keep(folder, manifest, keys, now)
            store.write_manifest(folder, manifest)

            played = entry["played"]
            info = (f"Saved the bridge before box {sequence.index} of '{sequence.name}': {played} new frames "
                    f"({timing.seconds(played):.2f} s).")
            if earlier is not None:
                info += " Moved its earlier take to takes/."
            if segment.timeline_complete:
                info += " " + (record['export_error'] if record.get('export_error') else
                               rebuild_full_video(folder, sequence.name, manifest if segment.box_order is None else
                                                  {**manifest, "segments": store.placed(manifest, len(segment.box_order))},
                                                  crf, bridges.spliced(folder, manifest, keys),
                                                 record.get("soundtrack", ()), managed_owner=sequence_owner(cls),
                                                 replaced=_replaced(folder, manifest, record), background=True,
                                                 restack=segment.restack))
            if notes:
                info += " " + " ".join(notes)
            return io.NodeOutput(info, ui=ui.PreviewText(info))


    @classmethod
    def save_layer(cls, segment, video, audio_latent, frames, fps, crf, images, waveform, sample_rate, description,
                   notes, color_space="sRGB", codec="H.264"):
        """Saves a clip's other video beside the segments, moving only that video's earlier take and the videos the
        Timeline no longer has."""
        from . import layers
        sequence, record = segment.sequence, segment.timeline
        from .timeline_api.service import authorize_sequence, sequence_owner
        keys = record.get("splice", {})
        with SEQUENCE_LOCK:
            authorize_sequence(sequence.name, sequence_owner(cls), "save_segment")
            now = datetime.datetime.now()
            folder = sequence.folder
            os.makedirs(folder, exist_ok=True)
            manifest = store.load_manifest(folder)
            manifest.pop("full_video", None)
            store.align(manifest, segment.box_order)
            earlier = layers.saved(manifest, record["layer"])
            if earlier is not None:
                layers.archive(folder, manifest, earlier, now)
            width, height = latents.pixel_size(video)
            entry = {
                "layer": record["layer"], "box": record["box"], "stem": layers.stem(record["layer"]), "frames": frames,
                "context_frames": segment.context_frames, "latent_width": width, "latent_height": height,
                "video": None, "audio_sample_rate": sample_rate,
                "description": description or segment.description or "", "created": now.isoformat(timespec="seconds"),
                "timeline": {key: value for key, value in record.items() if key not in UNSAVED},
            }
            if "played" in record:
                entry["played"] = record["played"]
            if images is not None:
                _write_video(folder, entry, images, fps, crf, waveform, sample_rate, notes, color_space, codec)
            store.save_segment(folder, entry, video, audio_latent, waveform)
            manifest.setdefault("layers", []).append(entry)
            layers.keep(folder, manifest, set(record.get("layer_ids", [record["layer"]])), now)
            store.write_manifest(folder, manifest)

            played = store.played_frames(entry)
            info = (f"Saved video {record['layer']} of clip {sequence.index} of '{sequence.name}': {played} frames "
                    f"({timing.seconds(played):.2f} s).")
            if earlier is not None:
                info += " Moved its earlier take to takes/."
            if segment.timeline_complete:
                info += " " + (record['export_error'] if record.get('export_error') else
                               rebuild_full_video(folder, sequence.name, manifest if segment.box_order is None else
                                                  {**manifest, "segments": store.placed(manifest, len(segment.box_order))},
                                                  crf, bridges.spliced(folder, manifest, keys) if keys else [],
                                                  record.get("soundtrack", ()), managed_owner=sequence_owner(cls),
                                                  replaced=_replaced(folder, manifest, record), background=True,
                                                  restack=segment.restack))
            if notes:
                info += " " + " ".join(notes)
            return io.NodeOutput(info, ui=ui.PreviewText(info))

    @classmethod
    def save_replacement(cls, segment, video, audio_latent, frames, fps, crf, images, waveform, sample_rate,
                         description, notes, color_space="sRGB", codec="H.264"):
        """Saves a replacement candidate beside the earlier ones; nothing is moved and nothing is selected."""
        from . import replacement_candidates
        sequence, record = segment.sequence, segment.timeline
        from .timeline_api.service import authorize_sequence, sequence_owner
        with SEQUENCE_LOCK:
            authorize_sequence(sequence.name, sequence_owner(cls), "save_segment")
            now = datetime.datetime.now()
            folder = sequence.folder
            os.makedirs(folder, exist_ok=True)
            manifest = store.load_manifest(folder)
            box = record["replacement"]
            taken = {entry.get("candidate") for entry in replacement_candidates.entries(manifest, box)}
            salt, candidate = 0, None
            while candidate is None or candidate in taken:
                candidate = replacement_candidates.candidate_id(box, f"{now.isoformat()}#{salt}", record["seed"],
                                                                record["region"])
                salt += 1
            width, height = latents.pixel_size(video)
            entry = {
                "box": box, "candidate": candidate, "stem": replacement_candidates.stem(box, candidate),
                "frames": frames, "context_frames": segment.context_frames, "carried_audio": segment.carried_ticks > 0,
                "latent_width": width, "latent_height": height, "video": None, "audio_sample_rate": sample_rate,
                "description": description or segment.description or "", "created": now.isoformat(timespec="seconds"),
                "timeline": {**{key: value for key, value in record.items() if key not in UNSAVED},
                             "candidate": candidate},
                "played": record["played"],
            }
            if segment.carried_audio_start:
                entry['audio_pin'] = {'start_tick': segment.carried_audio_start, 'ticks': segment.carried_ticks}
            if images is not None:
                _write_video(folder, entry, images, fps, crf, waveform, sample_rate, notes, color_space, codec)
            store.save_segment(folder, entry, video, audio_latent, waveform)
            if images is not None:
                try:
                    note = write_previews(folder, manifest, entry, crf,
                                          bridges.spliced(folder, manifest, record["splice"]) if record.get("splice") else [],
                                          record.get("soundtrack", ()))
                except (OSError, ValueError, RuntimeError) as error:
                    note = f"No preview: {error}"
                if note:
                    notes.append(note)
            replacement_candidates.add(manifest, entry)
            store.write_manifest(folder, manifest)
            info = (f"Saved replacement candidate {candidate} before box {sequence.index} of '{sequence.name}': "
                    f"{entry['played']} frames ({timing.seconds(entry['played']):.2f} s) in place of the same number. "
                    "Select it in the Studio to play it in the full video.")
            if images is None:
                info += " No images were connected, so it has no video to review or play."
            if notes:
                info += " " + " ".join(notes)
            return io.NodeOutput(info, ui=ui.PreviewText(info))


def guide_frame(frames, entry):
    """The last frame `entry` plays, from `frames`: every frame of its latent decoded at 24 fps, carried ones first."""
    if frames.shape[0] != entry["frames"]:
        raise ValueError(f"H3 Save Segment: guide_frames has {frames.shape[0]} frames, but this run's latent decodes to "
                         f"{entry['frames']}. Connect the sampler's latent decoded as is, before any interpolation.")
    played = entry.get("played")
    return frames[entry["context_frames"] + played - 1 if played is not None else entry["frames"] - 1]


def _write_video(folder, entry, images, fps, crf, waveform, sample_rate, notes, color_space="sRGB", codec="H.264"):
    """Writes the video of the entry's new frames, without the carried ones, and its last frame."""
    context, frames, played = entry["context_frames"], entry["frames"], entry.get("played")
    trim = timing.frames_at_fps(context, fps)
    if images.shape[0] <= trim:
        raise ValueError(f"H3 Save Segment: got {images.shape[0]} images, but the first {trim} repeat the "
                         "previous segment. Connect all frames of this run.")
    expected = timing.frames_at_fps(frames - context, fps)
    new_images = images[trim:]
    if new_images.shape[0] != expected:
        fix = "repeated the last frame" if new_images.shape[0] < expected else "dropped the extra frames"
        notes.append(f"{new_images.shape[0]} new images for {expected} frames: {fix}.")
        new_images = media.fit_frame_count(new_images, expected)
    last_image = images[-1]
    end_sample = None
    if played is not None:
        expected = max(1, timing.frames_at_fps(played, fps))
        new_images = new_images[:expected]
        last_image = new_images[-1]
        if waveform is not None:
            end_sample = timing.sample_at_frame(context + played, sample_rate)
    segment_audio = None
    if waveform is not None:
        segment_audio = (waveform[:, timing.sample_at_frame(context, sample_rate):end_sample], sample_rate)
    file = entry["stem"] + ".mp4"
    encoded = media.write_segment_video(os.path.join(folder, file), new_images, fps, crf, segment_audio,
                                        color_space=color_space, codec=codec)
    store.save_last_frame(folder, entry, last_image)
    entry["video"] = {"file": file, "fps": fps, "width": encoded[0], "height": encoded[1], "frames": expected,
                      "color_space": color_space, "codec": codec}


def _replaced(folder, manifest, record):
    """The selected candidates a Timeline record lists that still play after this save."""
    if not (record or {}).get("replace"):
        return []
    from . import replacement_candidates
    return replacement_candidates.selected_entries(folder, manifest, record["replace"])


def _not_rebuilt(error):
    return f"Full video not rebuilt: {str(error).removeprefix('H3 Timeline: ').rstrip('.')}."


def ordered_parts(manifest, spliced=(), replaced=()):
    """The full video's parts in order, each (entry, first frame, frames, inserts time): every saved segment, each
    `spliced` bridge before the segment of its box, and each `replaced` candidate at its box's join in place of the
    frames it covers on both sides."""
    segments = manifest["segments"]
    by_box = {(entry.get("timeline") or {}).get("box"): entry for entry in segments}
    leading = {entry["box"]: entry for entry in spliced}
    candidates = {entry["box"]: entry for entry in replaced}
    cuts = {}
    for candidate in replaced:
        after = by_box.get(candidate["box"])
        before = next((entry for entry in segments if after and entry["index"] == after["index"] - 1), None)
        if before is None:
            raise ValueError(f"H3 Timeline: replacement candidate {candidate.get('candidate')} has no saved boxes "
                             "on both sides")
        record = candidate["timeline"]
        cuts[after["index"]] = (record["right"], cuts.get(after["index"], (0, 0))[1])
        cuts[before["index"]] = (cuts.get(before["index"], (0, 0))[0], record["left"])
    parts = []
    for entry in segments:
        box_id = (entry.get("timeline") or {}).get("box")
        if box_id in leading:
            parts.append((leading[box_id], 0, store.played_frames(leading[box_id]), True))
        if box_id in candidates:
            parts.append((candidates[box_id], 0, store.played_frames(candidates[box_id]), False))
        start, end = cuts.get(entry["index"], (0, 0))
        count = store.played_frames(entry) - start - end
        if count < 1:
            raise ValueError(f"H3 Timeline: replacements leave no frame of segment {entry['index']}")
        parts.append((entry, start, count, False))
    return parts


def audio_parts(manifest, ordered):
    """Delivered box ownership of every assembled frame, including replacement regions."""
    segments = manifest['segments']
    result = []
    for entry, first, count, inserted in ordered:
        coverage = []
        record = entry.get('timeline') or {}
        if not inserted:
            if entry.get('candidate') and 'left' in record and 'right' in record:
                after = next(e for e in segments if (e.get('timeline') or {}).get('box') == entry['box'])
                before = next(e for e in segments if e['index'] == after['index']-1)
                original = [dict(box=before['timeline']['box'],first=store.played_frames(before)-record['left'],frames=record['left']),
                            dict(box=after['timeline']['box'],first=0,frames=record['right'])]
            else:
                original = [dict(box=record.get('box'),first=0,frames=store.played_frames(entry))]
            cursor = 0
            for span in original:
                left,right=max(first,cursor),min(first+count,cursor+span['frames'])
                if right>left: coverage.append(dict(box=span['box'],first=span['first']+left-cursor,frames=right-left))
                cursor += span['frames']
        result.append(dict(frames=count,coverage=coverage))
    return result


def _generated_audio(folder, parts):
    """The parts' own audio, each window from its saved waveform."""
    return media.assemble_audio([(e["context_frames"] + first + count, e["context_frames"] + first,
                                  store.load_waveform(folder, e) if e.get("audio_sample_rate") else None,
                                  e.get("audio_sample_rate")) for e, first, count, *_ in parts])


def _video_windows(folder, parts):
    return [(os.path.join(folder, e["video"]["file"]), *media.window_at_fps(first, count, e["video"].get("fps")))
            for e, first, count, *_ in parts]


def write_previews(folder, manifest, candidate, crf, spliced=(), soundtrack=()):
    """Writes the candidate between up to PREVIEW_FRAMES of the footage on each side (`{stem}_preview.mp4`) and the
    same moments as they play without it (`{stem}_original.mp4`), both with the same soundtrack, and records them in
    the candidate's entry as `preview`. Returns why they weren't written, or ""."""
    try:
        ordered = ordered_parts(manifest, spliced, [candidate])
    except ValueError as error:
        return f"No preview: {str(error).removeprefix('H3 Timeline: ')}."
    at = next(i for i, part in enumerate(ordered) if part[0] is candidate)
    (before, before_first, before_count, _), (after, after_first, after_count, _) = ordered[at - 1], ordered[at + 1]
    if not before.get("video") or not after.get("video"):
        return "No preview: a box beside it has no saved frames."
    lead, tail = min(PREVIEW_FRAMES, before_count), min(PREVIEW_FRAMES, after_count)
    record, played = candidate["timeline"], store.played_frames(candidate)
    start = before_first + before_count - lead
    versions = {"preview": [(before, start, lead), (candidate, 0, played), (after, after_first, tail)],
                "original": [(before, start, lead + record["left"]),
                             (after, after_first - record["right"], record["right"] + tail)]}
    heard = None
    if soundtrack:
        try:
            waveform, rate = audio_tracks.soundtrack_audio(soundtrack, audio_parts(manifest,ordered))
        except ValueError as error:
            return f"No preview: {str(error).removeprefix('H3 Timeline: ').rstrip('.')}."
        offset = sum(count for _, _, count, _ in ordered[:at - 1]) + before_count - lead
        heard = (waveform[:, timing.sample_at_frame(offset, rate):
                          timing.sample_at_frame(offset + lead + played + tail, rate)], rate)
    files = {}
    for kind, windows in versions.items():
        file = f"{candidate['stem']}_{kind}.mp4"
        written, note = media.build_full_video(os.path.join(folder, file), _video_windows(folder, windows),
                                               heard if soundtrack else _generated_audio(folder, windows), crf)
        if written is None:
            return f"No preview: {note}"
        files[kind] = file
    candidate["preview"] = {"file": files["preview"], "original": files["original"], "frames": lead + played + tail,
                            "region": [lead, lead + played], "fps": candidate["video"]["fps"]}
    return ""


def rebuild_full_video(folder, name, manifest, crf, spliced=(), soundtrack=(), *, managed_owner=None, replaced=(),
                       background=False, kind="full", restack=None):
    """Joins the saved segments, each `spliced` bridge before the segment of its box and each `replaced` candidate in
    place of the frames it covers. With `soundtrack` clips (`audio_tracks.marked`), it plays them instead of the
    segments' audio, on the Timeline's clock: only spliced bridges add time.
    `manifest["segments"]` are the segments joined, in order (a Timeline passes the segments of its boxes only).
    The segments are read and checked under SEQUENCE_LOCK, then encoded without it (unless the caller holds it), so
    status requests never wait for an encode. With `background`, the encode runs on its own thread and this returns at
    once; `full_video_state(folder)` says whether it is still building. The result is recorded only when the saved
    segments are still the ones it joined.
    `kind` "preview" joins the first boxes rendered so far (the caller passes only those) into the video so far, which
    is saved and recorded apart from the full video and builds on its own thread.
    `restack` (stacks.restacker) puts each stacked clip's stack in its segment's place, building it when missing."""
    with SEQUENCE_LOCK:
        from .timeline_api.service import authorize_sequence
        authorize_sequence(name, managed_owner, "full_video")
        if restack is not None:
            manifest = restack(folder, manifest, crf)
        if manifest.get('_track_timeline') is not None:
            from . import track_output
            record,building,note=track_output.ensure(folder,name,manifest['_track_timeline'],manifest,crf,
                                                     'full' if kind=='full' else 'so_far')
            return BUILDING if building else (f"Full video: {record['file']}" if record else note)
        plan, note = _plan_full_video(folder, name, manifest, crf, spliced, soundtrack, replaced)
        if plan is not None:
            plan["kind"] = kind
            plan["restack"] = restack
        if plan is None:
            return note
        if background:
            return _start_full_video(plan)
    return _finish_full_video(plan)


# Background builds by (sequence folder, kind): {"fingerprint", "thread", "error"}. One build of each kind per folder
# at a time. Each kind is (the manifest key that records it, its file's suffix).
_BUILDS = {}
_BUILDS_LOCK = threading.Lock()
BUILDING = "The full video is being built in the background."
VIDEO_KINDS = {"full": ("full_video", "_full.mp4"), "preview": ("preview_video", "_sofar.mp4")}


def full_video_state(folder, kind="full"):
    """{"building": bool, "fingerprint": the sources being built or last failed, "error": why the last build failed
    or None} for sequence `folder`'s video of `kind`."""
    with _BUILDS_LOCK:
        build = _BUILDS.get((os.path.normcase(folder), kind)) or {}
        thread = build.get("thread")
        return {"building": bool(thread and thread.is_alive()), "fingerprint": build.get("fingerprint"),
                "error": build.get("error")}


def wait_full_video(folder, timeout=None):
    """Waits for the background builds of `folder`, if any (tests and shutdown)."""
    with _BUILDS_LOCK:
        threads = [(_BUILDS.get((os.path.normcase(folder), kind)) or {}).get("thread") for kind in VIDEO_KINDS]
    from . import track_output
    with track_output._LOCK:
        threads.extend(job.get('thread') for key,job in track_output._JOBS.items() if key[0]==os.path.normcase(folder))
    for thread in threads:
        if thread is not None:
            thread.join(timeout)


def _start_full_video(plan):
    key = (os.path.normcase(plan["folder"]), plan.get("kind", "full"))
    with _BUILDS_LOCK:
        build = _BUILDS.get(key) or {}
        thread = build.get("thread")
        if thread is not None and thread.is_alive():
            return BUILDING
        if build.get("error") and build.get("fingerprint") == plan["fingerprint"]:
            return build["error"]  # the same segments failed already; a change to them tries again

        def run():
            try:
                note = _finish_full_video(plan)
                error = None if note.startswith("Full video:") else note
            except Exception as failure:  # an encode error must not kill ComfyUI's server thread
                error = f"Full video could not be saved: {failure}"
            with _BUILDS_LOCK:
                _BUILDS[key] = {"fingerprint": plan["fingerprint"], "thread": None, "error": error}
            _notify(plan["name"])

        thread = threading.Thread(target=run, name=f"h3c-{plan.get('kind', 'full')}-video-{plan['name']}", daemon=True)
        _BUILDS[key] = {"fingerprint": plan["fingerprint"], "thread": thread, "error": None}
        thread.start()
    return BUILDING


def _notify(name):
    """Tells open Studios that a sequence's full video changed, so they ask for status again."""
    import sys
    instance = getattr(getattr(sys.modules.get("server"), "PromptServer", None), "instance", None)
    if instance is not None:
        try:
            instance.send_sync("h3c-full-video", {"name": name})
        except Exception:
            pass


def _plan_full_video(folder, name, manifest, crf, spliced, soundtrack, replaced):
    """(what to encode, None), or (None, why the full video can't be built). Holds no files open."""
    segments = manifest["segments"]
    if not segments:
        return None, "Full video not rebuilt: no segments are saved."
    if [e["index"] for e in segments] != list(range(1, len(segments) + 1)):
        return None, "Full video not rebuilt: generate the missing earlier boxes first."
    missing = [str(e["index"]) for e in segments if not e.get("video")]
    if missing:
        return None, (f"Full video not rebuilt: {_plural(len(missing), 'segment')} {', '.join(missing)} "
                      f"{'has' if len(missing) == 1 else 'have'} no saved frames (connect images).")
    try:
        sources = audio_tracks.soundtrack_sources(soundtrack)
    except ValueError as error:
        return None, _not_rebuilt(error)
    fingerprint = store.full_video_fingerprint(folder, manifest, [*spliced, *replaced], sources)
    if fingerprint is None:
        return None, "Full video not rebuilt: a segment video or audio source is missing."
    try:
        ordered = ordered_parts(manifest, spliced, replaced)
    except ValueError as error:
        return None, _not_rebuilt(error)
    if soundtrack:
        try:
            audio = audio_tracks.soundtrack_audio(soundtrack, audio_parts(manifest,ordered))
        except ValueError as error:
            return None, _not_rebuilt(error)
    else:
        audio = _generated_audio(folder, ordered)
    return {"folder": folder, "name": name, "manifest": manifest, "segments": copy.deepcopy(segments),
            "bridges": [copy.deepcopy(entry) for entry in [*spliced, *replaced]], "sources": sources,
            "fingerprint": fingerprint, "windows": _video_windows(folder, ordered), "audio": audio, "crf": crf,
            "heard": audio_tracks.named(soundtrack) if soundtrack else ""}, ""


def _finish_full_video(plan):
    folder, name = plan["folder"], plan["name"]
    key, suffix = VIDEO_KINDS[plan.get("kind", "full")]
    temporary = os.path.join(folder, f"{name}{suffix.removesuffix('.mp4')}.{threading.get_ident()}.tmp.mp4")
    written, note = media.build_full_video(os.path.join(folder, f"{name}{suffix}"), plan["windows"], plan["audio"],
                                           plan["crf"], temporary=temporary)
    if written is None:
        return note
    record = {"file": os.path.basename(written), "sources": plan["fingerprint"]}
    if key == "preview_video":
        record["boxes"] = len(plan["segments"])
    with SEQUENCE_LOCK:
        latest = store.load_manifest(folder)
        restack = plan.get("restack")
        view = restack(folder, latest, plan["crf"], make=False) if restack is not None else latest
        joined = [entry for entry in view["segments"] if 1 <= entry["index"] <= len(plan["segments"])]
        if (joined != plan["segments"] or store.full_video_fingerprint(
                folder, {**view, "segments": joined}, plan["bridges"], plan["sources"]) != plan["fingerprint"]):
            return "Full video not recorded: the saved boxes changed while it was built; it is built again from them."
        latest[key] = record
        store.write_manifest(folder, latest)
        plan["manifest"][key] = record
    if key == "preview_video":
        # A video so far written beside a playing one (Windows keeps it open) gets a dated name; every earlier one is
        # removed once nothing holds it, so only the recorded one is kept.
        stem = f"{name}{suffix.removesuffix('.mp4')}"
        for file in os.listdir(folder):
            if file != record["file"] and (file == f"{stem}.mp4" or (file.startswith(f"{stem}_") and file.endswith(".mp4"))):
                try:
                    os.remove(os.path.join(folder, file))
                except OSError:
                    pass
    heard = f", with the soundtrack from {plan['heard']}" if plan["heard"] else ""
    return f"Full video: {written}{heard}." + (f" {note}" if note else "")
