"""Sequence folders: manifest, segment files and archived takes."""

import hashlib
import json
import os
import re
import shutil

import numpy as np
import torch
from PIL import Image
from safetensors import safe_open
from safetensors.torch import save_file

from .timing import seconds

MANIFEST = "manifest.json"
_NAME = re.compile(r"[A-Za-z0-9_\-. ]{1,64}")


def validate_name(name):
    name = name.strip()
    if not _NAME.fullmatch(name) or name.startswith(".") or name.endswith("."):
        raise ValueError(f"H3 Sequence: invalid name {name!r}; use 1-64 letters, digits, spaces, '_', '-' or '.', "
                         "not starting or ending with '.'")
    return name


def sequence_dir(root, name):
    return os.path.join(root, validate_name(name))


def stem(index):
    return f"seg_{index:04d}"


def empty_manifest(name):
    return {"version": 1, "name": name, "segments": [], "takes": []}


def load_manifest(folder):
    path = os.path.join(folder, MANIFEST)
    if not os.path.exists(path):
        return empty_manifest(os.path.basename(folder))
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_manifest(folder, manifest):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, MANIFEST)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    os.replace(path + ".tmp", path)


def manifest_fingerprint(folder):
    path = os.path.join(folder, MANIFEST)
    if not os.path.exists(path):
        return "none"
    with open(path, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()


def full_video_fingerprint(folder, manifest, bridges=(), soundtrack_sources=()):
    """Version the ordered delivered videos and their saved audio sources, then those of the spliced `bridges`, then
    the `soundtrack_sources` of the clips the full video plays instead of their audio."""
    sources = []
    for entry in [*manifest["segments"], *bridges]:
        if not entry.get("video"):
            return None
        files = [entry["video"]["file"]]
        if entry.get("audio_sample_rate"):
            files.append(entry["stem"] + ".safetensors")
        stamps = []
        for filename in files:
            try:
                stat = os.stat(os.path.join(folder, filename))
            except FileNotFoundError:
                return None
            stamps.append([filename, stat.st_mtime_ns, stat.st_size])
        sources.append([entry, stamps])
    if sources and soundtrack_sources:
        sources.append(["soundtrack", list(soundtrack_sources)])
    return hashlib.sha1(json.dumps(["smallest-clip-size-1", sources], sort_keys=True).encode("utf-8")).hexdigest() if sources else None


def current_full_video(folder, manifest, bridges=(), soundtrack_sources=(), key="full_video"):
    """The saved video recorded under `key` ("full_video", or "preview_video" for the video so far) while its sources
    are the ones it was built from, else None."""
    record = manifest.get(key)
    if (record and os.path.basename(record["file"]) == record["file"]
            and record["sources"] == full_video_fingerprint(folder, manifest, bridges, soundtrack_sources)
            and os.path.isfile(os.path.join(folder, record["file"]))):
        return record
    return None


def played_frames(entry):
    """The frames a saved segment adds to the movie; a segment that dropped generated frames records them."""
    return entry["played"] if "played" in entry else entry["frames"] - entry.get("context_frames", 0)


def sequence_seconds(manifest, bridges=()):
    return seconds(sum(played_frames(e) for e in [*manifest["segments"], *bridges]))


def resolve_base(manifest, continue_from):
    """Return (entry of the segment this run continues or None, index this run writes)."""
    segments = manifest["segments"]
    if continue_from == 0:
        return None, 1
    if continue_from == -1:
        base = segments[-1] if segments else None
    else:
        base = next((e for e in segments if e["index"] == continue_from), None)
        if base is None:
            raise ValueError(f"H3 Sequence: continue_from is {continue_from}, but the sequence has {len(segments)} segments")
    return base, (base["index"] + 1 if base else 1)


def _latent_path(folder, entry):
    return os.path.join(folder, entry["stem"] + ".safetensors")


def save_segment(folder, entry, video, audio, waveform):
    tensors = {"video": video.contiguous().cpu(), "audio": audio.contiguous().cpu()}
    if waveform is not None:
        tensors["waveform"] = waveform.float().contiguous().cpu()
    # A crash mid-write must not leave a truncated file where a finished segment is expected.
    path = _latent_path(folder, entry)
    save_file(tensors, path + ".tmp", metadata={"h3c": json.dumps(entry)})
    os.replace(path + ".tmp", path)


def _open_segment(folder, entry):
    path = _latent_path(folder, entry)
    if not os.path.exists(path):
        what = f"segment {entry['index']}" if "index" in entry else f"the bridge before box {entry['box']!r}"
        raise ValueError(f"H3 Sequence: {what} is missing its latent file {path}")
    return safe_open(path, framework="pt")


def load_segment_latents(folder, entry):
    # clones, so no tensor keeps the file mapped and the segment can still be moved to takes/ on Windows
    with _open_segment(folder, entry) as f:
        return f.get_tensor("video").clone(), f.get_tensor("audio").clone()


def load_waveform(folder, entry):
    with _open_segment(folder, entry) as f:
        return f.get_tensor("waveform").clone() if "waveform" in f.keys() else None


def load_video_window(folder, entry, start, tokens):
    """`tokens` video latent frames from `start`, read without loading the whole segment."""
    with _open_segment(folder, entry) as f:
        return f.get_slice("video")[:1, :, start:start + tokens].clone()


def video_tokens(folder, entry):
    """How many video latent frames saved segment `entry` holds."""
    with _open_segment(folder, entry) as f:
        return f.get_slice("video").get_shape()[2]


def latent_stamp(folder, entry):
    stat = os.stat(_latent_path(folder, entry))
    return [stat.st_mtime_ns, stat.st_size]


def box_of(entry):
    """The Timeline box id saved segment `entry` was rendered for, or None (H3 Sequence segments)."""
    return (entry.get("timeline") or {}).get("box")


def align(manifest, box_ids):
    """Number the saved segments by the Timeline's box order `box_ids`: the segment of the box at position i gets index
    i + 1, wherever it was saved. Segments of boxes the Timeline no longer has (or without a box id) keep their files
    and follow, numbered after the last box, so they can come back with their box. When a box has several segments the
    newest is in place. Returns whether any index changed; `manifest` is changed in place."""
    if box_ids is None:
        return False
    positions = {box_id: number for number, box_id in enumerate(box_ids)}
    chosen, rest = {}, []
    for entry in manifest["segments"]:
        box_id = box_of(entry)
        if box_id in positions:
            held = chosen.get(box_id)
            if held is None or str(entry.get("created", "")) >= str(held.get("created", "")):
                if held is not None:
                    rest.append(held)
                chosen[box_id] = entry
                continue
        rest.append(entry)
    before = [(entry["stem"], entry["index"]) for entry in manifest["segments"]]
    placed = [chosen[box_id] for box_id in box_ids if box_id in chosen]
    for entry in placed:
        entry["index"] = positions[box_of(entry)] + 1
    rest.sort(key=lambda entry: entry["index"])
    for number, entry in enumerate(rest):
        entry["index"] = len(box_ids) + number + 1
    manifest["segments"] = sorted(placed, key=lambda entry: entry["index"]) + rest
    return before != [(entry["stem"], entry["index"]) for entry in manifest["segments"]]


def placed(manifest, count):
    """The saved segments in place for the first `count` boxes, in order (an aligned manifest's leading segments)."""
    return [entry for entry in manifest["segments"] if 1 <= entry["index"] <= count]


def free_stem(folder, manifest, index):
    """`seg_{index}`, or `seg_{index}-2`, `-3`... when files or another saved segment already use that name, so a
    box that moved never writes over the files of the box that was there."""
    used = {entry["stem"] for entry in manifest["segments"]}
    names = os.listdir(folder) if os.path.isdir(folder) else []
    candidate, number = stem(index), 1
    while candidate in used or any(name.startswith((candidate + ".", candidate + "_")) for name in names):
        number += 1
        candidate = f"{stem(index)}-{number}"
    return candidate


def archive_box(folder, manifest, box_id, now):
    """Move the saved segments of box `box_id` (only those) into takes/; returns their indices."""
    kept, moved = [], []
    for entry in manifest["segments"]:
        if box_id is None or box_of(entry) != box_id:
            kept.append(entry)
            continue
        relative = move_take(folder, entry["stem"], now)
        manifest.setdefault("takes", []).append(
            {"index": entry["index"], "archived": now.isoformat(timespec="seconds"), "folder": relative})
        moved.append(entry["index"])
    manifest["segments"] = kept
    return moved


def archive_from(folder, manifest, index, now, only=False):
    """Move segment `index` and later ones into takes/ (only `index` when requested)."""
    kept, moved = [], []
    for entry in manifest["segments"]:
        if entry["index"] < index or (only and entry["index"] != index):
            kept.append(entry)
            continue
        relative = move_take(folder, entry["stem"], now)
        manifest.setdefault("takes", []).append(
            {"index": entry["index"], "archived": now.isoformat(timespec="seconds"), "folder": relative})
        moved.append(entry["index"])
    manifest["segments"] = kept
    return moved


def _stem_files(folder, stem):
    return [name for name in os.listdir(folder) if name.startswith((stem + ".", stem + "_"))]


def _take_folder(folder, stem, now):
    """Makes a new, empty folder under takes/ for the files of `stem`; returns it relative to `folder`."""
    stamp = now.strftime("%Y%m%d-%H%M%S")
    relative = f"takes/{stem}_{stamp}"
    suffix = 1
    while os.path.exists(os.path.join(folder, relative)):
        suffix += 1
        relative = f"takes/{stem}_{stamp}-{suffix}"
    os.makedirs(os.path.join(folder, relative))
    return relative


def move_take(folder, stem, now):
    """Moves the files named `stem.*` and `stem_*` into a new folder under takes/; returns that folder."""
    relative = _take_folder(folder, stem, now)
    for name in _stem_files(folder, stem):
        shutil.move(os.path.join(folder, name), os.path.join(folder, relative, name))
    return relative


def put_back_take(folder, stem, relative, now):
    """Moves the files of `stem` into a new folder under takes/, when there are any, then the files of the take in
    folder `relative` into their place, and removes that folder. Returns (the new folder or None, the moves as
    (from, to) paths). When anything fails, the moves made are undone and the error raised."""
    moves, archived = [], None
    try:
        names = _stem_files(folder, stem)
        if names:
            archived = _take_folder(folder, stem, now)
        for name in names:
            _move(os.path.join(folder, name), os.path.join(folder, archived, name), moves)
        source = os.path.join(folder, relative)
        for name in os.listdir(source):
            _move(os.path.join(source, name), os.path.join(folder, name), moves)
        os.rmdir(source)
    except OSError:
        undo_moves(folder, moves, archived)
        raise
    return archived, moves


def _move(source, target, moves):
    shutil.move(source, target)
    moves.append((source, target))


def undo_moves(folder, moves, archived):
    """Moves each (from, to) of `moves` back, the last first, recreating the folders they left; then removes the
    takes/ folder `archived` once it is empty."""
    for source, target in reversed(moves):
        os.makedirs(os.path.dirname(source), exist_ok=True)
        shutil.move(target, source)
    if archived and os.path.isdir(os.path.join(folder, archived)) and not os.listdir(os.path.join(folder, archived)):
        os.rmdir(os.path.join(folder, archived))


def _save_frame(path, image):
    array = (image[..., :3].clamp(0, 1) * 255).round().to(torch.uint8).cpu().numpy()
    Image.fromarray(array).save(path)


def _load_frame(path):
    if not os.path.exists(path):
        return None
    with Image.open(path) as image:
        array = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    return torch.from_numpy(array)[None]


def save_last_frame(folder, entry, image):
    _save_frame(os.path.join(folder, entry["stem"] + "_last.png"), image)


def load_last_frame(folder, entry):
    return _load_frame(os.path.join(folder, entry["stem"] + "_last.png"))


def save_guide_frame(folder, entry, image):
    """The last played frame of the latent the next box carries, before any upscale or grade."""
    _save_frame(os.path.join(folder, entry["stem"] + "_guide.png"), image)


def load_continuation_frame(folder, entry):
    """The image a continuing box is guided to start from: the saved guide frame, else the finished last frame."""
    guide = _load_frame(os.path.join(folder, entry["stem"] + "_guide.png"))
    return guide if guide is not None else load_last_frame(folder, entry)


def has_segment_latents(folder, entry):
    return os.path.exists(_latent_path(folder, entry))
