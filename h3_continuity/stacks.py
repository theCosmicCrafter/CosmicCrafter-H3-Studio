"""Stacks: a clip with several videos composited into one, which the full video and "so far" play in its place.

The picture blends the videos by the switch's fade weights at the main video's size and frame rate; the sound follows
the video on screen (or plays one video's sound throughout). A stack is saved as `stack@<clip id>` and rebuilt only
when a video it uses, or the switch, changes."""

import datetime
import hashlib
import json
import os
import re
from fractions import Fraction

import av
import numpy as np
import torch
from comfy_api.latest._input_impl.video_types import set_video_color_properties
from PIL import Image
from safetensors import safe_open

from . import layers, media, store
from . import timeline as rules
from .timing import FPS


def stem(clip_id):
    """The stack's file stem, unique the way bridges.stem is."""
    if re.fullmatch(r"[a-z0-9]{1,40}", clip_id):
        return f"stack@{clip_id}"
    return "stack@_" + hashlib.sha1(clip_id.encode("utf-8")).hexdigest()[:12]


def _switch(timeline, index, switch):
    return timeline.switches[timeline.boxes[index].id] if switch is None else switch


def _used(clip_id, switch):
    """The videos a switch plays, the main one first."""
    sound = [switch["sound"]] if switch["sound"] != "screen" else []
    return list(dict.fromkeys([clip_id, *(cut["to"] for cut in switch["cuts"]), *sound]))


def sources(folder, timeline, index, main_entry, layer_entries, switch=None):
    """Fingerprint of what the stack is made of: each video it plays, by its files, and the switch. None when a video
    has no saved files."""
    switch = _switch(timeline, index, switch)
    clip_id = timeline.boxes[index].id
    entries = {**layer_entries, clip_id: main_entry}
    stamps = []
    for video in _used(clip_id, switch):
        entry = entries.get(video)
        if entry is None or not entry.get("video"):
            return None
        path = os.path.join(folder, entry["video"]["file"])
        if not os.path.isfile(path) or not store.has_segment_latents(folder, entry):
            return None
        stat = os.stat(path)
        stamps.append([video, entry["stem"], entry.get("created"), stat.st_size, stat.st_mtime_ns,
                       store.latent_stamp(folder, entry), entry.get("context_frames", 0), entry["video"].get("fps")])
    return rules._digest({"switch": switch, "played": rules.played_frames(timeline, index), "videos": stamps})


def saved(folder, clip_id):
    """The entry of clip `clip_id`'s saved stack, read from its file, or None. Stacks aren't recorded in the manifest,
    so building one while answering a status request never rewrites it."""
    path = os.path.join(folder, stem(clip_id) + ".safetensors")
    try:
        with safe_open(path, framework="pt") as f:
            entry = json.loads((f.metadata() or {})["h3c"])
    except (OSError, KeyError, ValueError):
        return None
    return entry if entry.get("stack") == clip_id else None


def current(folder, timeline, index, main_entry, layer_entries, switch=None):
    """The saved stack of clip `index` while it is made of these videos and switch and its files exist, or None."""
    entry = saved(folder, timeline.boxes[index].id)
    if entry is None or entry.get("sources") != sources(folder, timeline, index, main_entry, layer_entries, switch):
        return None
    return entry if os.path.isfile(os.path.join(folder, entry["video"]["file"])) else None


def _takes(folder, timeline, manifest, clip_id):
    """({layer id: saved take} of clip `clip_id`'s other videos, ids of those without one)."""
    found, waiting = {}, []
    for item in timeline.layers[clip_id]:
        entry = layers.saved(manifest, item["id"])
        if entry is not None and entry.get("video") and store.has_segment_latents(folder, entry):
            found[item["id"]] = entry
        else:
            waiting.append(item["id"])
    return found, waiting


def waiting(folder, timeline, manifest, count):
    """Notes naming the other videos of the first `count` clips that have no take yet."""
    return [f"Clip {index + 1}'s video {layers.label(timeline, index, video)} has no take yet."
            for index, clip in enumerate(timeline.boxes[:count]) if clip.id in timeline.layers
            for video in _takes(folder, timeline, manifest, clip.id)[1]]


def substitute(folder, timeline, manifest, count, crf, partial=False, make=True):
    """(`manifest` with the placed segment of each stacked clip among the first `count` replaced by the clip's stack,
    the notes of `waiting`). A clip whose videos aren't all rendered keeps its main video, or with `partial` (the
    video so far) is composited from the videos that have takes: its switch drops the swaps to the others, so the
    video before carries on. With `make` False, only a saved stack that is still current is used."""
    if not timeline.layers:
        return manifest, []
    positions = {clip.id: index for index, clip in enumerate(timeline.boxes)}
    segments = []
    for entry in manifest["segments"]:
        clip_id = store.box_of(entry)
        index = positions.get(clip_id)
        if ("stack" in entry or clip_id not in timeline.layers or not entry.get("video")
                or index is None or entry["index"] != index + 1 or index >= count):
            segments.append(entry)
            continue
        found, missing = _takes(folder, timeline, manifest, clip_id)
        if not found or (missing and not partial):
            segments.append(entry)
            continue
        switch = timeline.switches[clip_id]
        if missing:
            switch = {**switch, "cuts": [cut for cut in switch["cuts"] if cut["to"] not in missing],
                      "sound": "screen" if switch["sound"] in missing else switch["sound"]}
        stack = current(folder, timeline, index, entry, found, switch)
        if stack is None and make:
            stack = build(folder, timeline, index, entry, found, crf, switch)
        segments.append(entry if stack is None else {**stack, "index": entry["index"]})
    return {**manifest, "segments": segments}, waiting(folder, timeline, manifest, count)


def restacker(timeline, count, partial=False):
    """`substitute` bound to a Timeline, for nodes.rebuild_full_video: (folder, manifest, crf, make) -> manifest."""
    if timeline.tracks is not None:
        from . import track_output
        return track_output.restacker(timeline)
    return lambda folder, manifest, crf, make=True: substitute(folder, timeline, manifest, count, crf, partial,
                                                               make)[0]


def _frames(path, picks, size, fmt):
    """The frames of the video at `path` at source numbers `picks` (ascending, repeats allowed), at `size`. A pick
    past the end gets the last frame."""
    position, last = 0, None
    with av.open(path) as container:
        for number, frame in enumerate(container.decode(video=0)):
            if position >= len(picks):
                break
            if number < picks[position]:
                continue
            last = frame.reformat(width=size[0], height=size[1], format=fmt).to_ndarray()
            while position < len(picks) and picks[position] == number:
                yield last
                position += 1
    if last is None:
        raise ValueError(f"{os.path.basename(path)} has no frames")
    for _ in range(position, len(picks)):
        yield last


def _warp(plane, x, y, scale, fill):
    height, width = plane.shape
    middle_x, middle_y = width / 2, height / 2
    coefficients = (1 / scale, 0, middle_x - (middle_x + x) / scale, 0, 1 / scale, middle_y - (middle_y + y) / scale)
    return np.asarray(Image.fromarray(plane.astype(np.float32), mode="F").transform(
        (width, height), Image.Transform.AFFINE, coefficients, resample=Image.Resampling.BILINEAR, fillcolor=fill))


def _aligned(array, shift, bits):
    """Packed 4:2:0 `array` ([H * 3 / 2, W], limited range) shifted by x, y pixels and scaled about its centre; the
    uncovered edge is black."""
    if shift is None or (shift["x"], shift["y"], shift["scale"]) == (0, 0, 1):
        return array
    height, width = array.shape[0] * 2 // 3, array.shape[1]
    quarter = height // 2 * width // 2
    chroma = array[height:].reshape(-1)
    black, neutral = 16 << (bits - 8), 128 << (bits - 8)
    planes = [_warp(array[:height], shift["x"], shift["y"], shift["scale"], black).reshape(-1)]
    for part in (chroma[:quarter], chroma[quarter:]):
        planes.append(_warp(part.reshape(height // 2, width // 2), shift["x"] / 2, shift["y"] / 2, shift["scale"],
                            neutral).reshape(-1))
    packed = np.concatenate(planes).reshape(array.shape)
    return np.clip(np.rint(packed), 0, (1 << bits) - 1).astype(array.dtype)


def _sound(folder, clip_id, switch, entries, played):
    """(waveform, sample rate) of the stack, or None when no video it plays has sound."""
    def part(start, end, video):
        entry, carried = entries[video], entries[video].get("context_frames", 0)
        waveform = store.load_waveform(folder, entry)
        return end + carried, start + carried, waveform, entry.get("audio_sample_rate") if waveform is not None else None

    if switch["sound"] != "screen":
        return media.assemble_audio([part(0, played, switch["sound"])])
    spans = [(0, clip_id), *((cut["at"], cut["to"]) for cut in switch["cuts"])]
    return media.assemble_audio([part(start, spans[k + 1][0] if k + 1 < len(spans) else played, video)
                                 for k, (start, video) in enumerate(spans)])


def build(folder, timeline, index, main_entry, layer_entries, crf, switch=None):
    """Writes the stack of clip `index` from its saved videos and returns its entry. `switch` defaults to the clip's
    own."""
    switch = _switch(timeline, index, switch)
    clip_id = timeline.boxes[index].id
    played = rules.played_frames(timeline, index)
    entries = {**layer_entries, clip_id: main_entry}
    main_path = os.path.join(folder, main_entry["video"]["file"])
    codec, _, width, height, rate, space = media._signature(main_path)
    # Blended in the encoder's own 4:2:0 format, so a frame showing one video passes through without a colour
    # conversion and loses only what the re-encode does.
    bits = 10 if space in ("HDR", "HDR PQ") else 8
    fmt = "yuv420p10le" if bits == 10 else "yuv420p"
    count = media.window_at_fps(0, played, main_entry["video"].get("fps"))[1]
    used = _used(clip_id, switch)
    streams = {}
    for video in used:
        entry = entries[video]
        fps = entry["video"].get("fps") or FPS
        picks, _ = media._picks(0, media.window_at_fps(0, played, fps)[1], fps, rate, Fraction(0))
        picks = (picks + picks[-1:] * count)[:count]
        streams[video] = _frames(os.path.join(folder, entry["video"]["file"]), picks, (width, height), fmt)
    align = switch.get("align", {})
    sound = _sound(folder, clip_id, switch, entries, played)
    name = stem(clip_id)
    path, temporary = os.path.join(folder, name + ".mp4"), os.path.join(folder, name + ".tmp.mp4")
    try:
        with av.open(temporary, mode="w") as container:
            stream = media._add_video_stream(container, rate, width, height, crf, space,
                                             media.CODEC_OF_STREAM.get(codec, "H.264"))
            audio_stream = media._add_audio_stream(container, *sound) if sound is not None else None
            for number in range(count):
                arrays = {video: _aligned(next(frames), align.get(video), bits) for video, frames in streams.items()}
                frame_time = number * FPS / float(rate)
                picture = arrays[clip_id]
                for cut in switch["cuts"]:
                    weight = layers.weight(switch, cut, frame_time)
                    if weight <= 0:
                        break
                    incoming = arrays[cut["to"]]
                    picture = incoming if weight >= 1 else picture.astype(np.float32) * (1 - weight) + incoming * weight
                picture = np.clip(np.rint(picture), 0, (1 << bits) - 1).astype(np.uint16 if bits > 8 else np.uint8)
                frame = av.VideoFrame.from_ndarray(picture, format=fmt)
                set_video_color_properties(frame, space)
                container.mux(stream.encode(frame))
            container.mux(stream.encode(None))
            if audio_stream is not None:
                media._mux_audio(container, audio_stream, *sound)
        os.replace(temporary, path)
    except BaseException:
        if os.path.exists(temporary):
            os.remove(temporary)
        raise
    entry = {"stack": clip_id, "stem": name, "frames": played, "context_frames": 0, "played": played,
             "video": {"file": name + ".mp4", "fps": main_entry["video"].get("fps") or FPS, "width": width,
                       "height": height, "frames": count},
             "audio_sample_rate": sound[1] if sound is not None else None,
             "sources": sources(folder, timeline, index, main_entry, layer_entries, switch),
             "created": datetime.datetime.now().isoformat(timespec="seconds"), "timeline": {"box": clip_id}}
    store.save_segment(folder, entry, torch.zeros(1, 1, 1, 1, 1), torch.zeros(1, 1, 1, 1),
                       sound[0] if sound is not None else None)
    return entry
