"""Read-only join preflight and consent-scoped archival after a replacement has been written."""

import copy
import hashlib
import json
import os
from dataclasses import asdict

from safetensors import SafetensorError

from . import store, timing, timeline as rules

CHANGED = "H3 Timeline: saved renders or settings changed; confirm regeneration again."


def _settings(known):
    result = dict(known)
    for key in ("width", "height", "context_frames"):
        try:
            result[key] = int(result[key])
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"H3 Timeline: resolve {key} before regenerating a clip") from None
    result.setdefault("carry_audio", True)
    result.setdefault("ref_image_size", "match")
    result.setdefault("audio_context_frames", 0)
    return result


def _reason(folder, parsed, known, index, following):
    after=rules.following_index(parsed,index)
    if after is None or rules.is_fresh(parsed,after) or following is None:
        return ""
    number = after + 1
    if not store.has_segment_latents(folder, following):
        return f"Clip {number}'s saved starting frames are missing."
    if (following.get("latent_width"), following.get("latent_height")) != (known["width"], known["height"]):
        return f"Clip {number}'s saved resolution differs from the current render resolution."
    ending = following.get("context_frames", 0)
    if ending not in tuple(map(int, timing.CONTEXT_OPTIONS)):
        return f"Clip {number} has no saved continuation overlap (it may have been rendered as a Cut)."
    frames, carried = rules.box_length(parsed, index, known["context_frames"])
    generated = frames + carried + rules.dropped_frames(parsed, index)
    if (timing.tokens_for_frames(carried) if carried else 0) + timing.tokens_for_frames(ending) >= timing.tokens_for_frames(generated):
        return "This clip is too short to preserve both its saved neighbors while generating new frames."
    try:
        with store._open_segment(folder, following) as handle:
            video = handle.get_slice("video").get_shape()
            audio = handle.get_slice("audio").get_shape()
        if video[3:] != [known["height"] // 16, known["width"] // 16]:
            return f"Clip {number}'s saved starting frames have a different latent resolution."
        if video[2] < timing.tokens_for_frames(ending):
            return f"Clip {number}'s saved video is shorter than its continuation overlap."
        if known["carry_audio"]:
            ticks = timing.ticks_for_frames(ending)
            total = timing.ticks_for_frames(generated)
            start = timing.audio_tail_start(generated, total, ending)
            if audio[-1] < ticks or start < timing.ticks_for_frames(carried):
                return f"Clip {number}'s saved audio overlap cannot fit this render."
    except (OSError, KeyError, ValueError, SafetensorError):
        return f"Clip {number}'s saved starting frames cannot be read."
    return ""


def _fingerprint(folder, parsed, known, manifest, index):
    timeline = asdict(parsed)
    timeline["render_box"] = timeline["render_bridge"] = None
    timeline.pop("render_layer")
    if not timeline["layers"]:
        del timeline["layers"], timeline["switches"]
    # The editor randomizes the requested take's seed after confirmation, before queueing.
    timeline["boxes"][index]["seed"] = 0
    records = {key: manifest.get(key, []) for key in ("segments", "bridges", "replacements")}
    records.update({key: manifest[key] for key in ("layers", "stacks") if key in manifest})
    stamps = []
    for entries in records.values():
        for entry in entries:
            files = [entry["stem"] + ".safetensors", entry["stem"] + "_last.png", entry["stem"] + "_guide.png"]
            if entry.get("video"):
                files.append(entry["video"]["file"])
            for file in files:
                try:
                    stat = os.stat(os.path.join(folder, file))
                    stamps.append([file, stat.st_size, stat.st_mtime_ns])
                except FileNotFoundError:
                    stamps.append([file, None])
    value = [os.path.normcase(os.path.abspath(folder)), timeline, known, records, stamps]
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def inspect(folder, parsed, known, box_id):
    """Describe incompatible overlap and every dependent saved clip, without changing disk."""
    index = next((i for i, box in enumerate(parsed.boxes) if box.id == box_id), None)
    if index is None:
        raise ValueError("H3 Timeline: the requested clip is no longer in the Timeline")
    manifest = store.load_manifest(folder)
    store.align(manifest, [box.id for box in parsed.boxes])
    entries = {store.box_of(entry): entry for entry in manifest["segments"]}
    after=rules.following_index(parsed,index)
    following = entries.get(parsed.boxes[after].id) if after is not None else None
    result = dict(ok=True, box=box_id, number=index + 1, needs_rebuild=False, reason="",
                  affected=[], bridges=[], replacements=[], receipt=None)
    if following is None or rules.is_fresh(parsed,after):
        return result
    if any(known.get(key) is None for key in ("width", "height", "context_frames", "carry_audio", "ref_image_size")):
        # Producers without static scalar outputs resolve at execution; the renderer still checks the actual join.
        return {**result, "deferred": True}
    known = _settings(known)
    reason = _reason(folder, parsed, known, index, following)
    result.update(needs_rebuild=bool(reason), reason=reason)
    if not reason:
        return result
    changed = {box_id}
    for later in rules.render_order(parsed):
        if later==index: continue
        box = parsed.boxes[later]
        dependencies = {parsed.boxes[source].id for source, _, _ in rules.memory_sources(parsed, later)}
        if not rules.is_fresh(parsed, later):
            dependencies.add(parsed.boxes[rules.previous_index(parsed,later)].id)
        dependencies.update(item["box"] for item in (entries.get(box.id, {}).get("timeline") or {}).get("memories", []))
        if dependencies & changed:
            changed.add(box.id)
            if box.id in entries:
                result["affected"].append(dict(id=box.id, number=later + 1))
    for later in range(len(parsed.boxes)):
        box = parsed.boxes[later]
        previous=rules.previous_index(parsed,later)
        if previous is None or not {box.id, parsed.boxes[previous].id} & changed:
            continue
        for key in ("bridges", "replacements"):
            if any(entry["box"] == box.id for entry in manifest.get(key, [])):
                result[key].append(dict(id=box.id, number=later + 1))
    result["receipt"] = dict(box=box_id, fingerprint=_fingerprint(folder, parsed, known, manifest, index))
    return result


def validate(folder, parsed, known, box_id, receipt):
    result = inspect(folder, parsed, known, box_id)
    if not isinstance(receipt, dict) or not result["needs_rebuild"] or result["receipt"] != {
            key: value for key, value in receipt.items() if key != "editor"}:
        raise ValueError(CHANGED)
    if receipt.get("editor"):
        editor = receipt["editor"]
        if _editor_fingerprint(editor, box_id) != editor.get("fingerprint"):
            raise ValueError(CHANGED)
    return result


def _editor_fingerprint(editor, box_id):
    from . import saved_state
    with saved_state.LOCK:
        record = saved_state.read("workflow", editor["graph"], "workflow")
        prefix = str(editor["node"]) + "/H3C_Timeline/"
        values = {key.removeprefix(prefix): value for key, value in (record.get("value") or {}).items()
                  if key.startswith(prefix)}
    if not values.get("timeline"):
        raise ValueError(CHANGED)
    line = json.loads(values["timeline"])
    for box in line.get("boxes", []):
        if box.get("id") == box_id:
            box["seed"] = 0
    values["timeline"] = line
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def request(body):
    from . import nodes, timeline_node
    try:
        with nodes.SEQUENCE_LOCK:
            parsed, folder, known, _ = timeline_node.read_request(body)
            known = dict(known)
            graph = body.get("workflow") or {}
            inputs = graph.get(str(body.get("timeline_node")), {}).get("inputs", {})
            for key, value in known.items():
                if value is None and key in inputs:
                    from . import timeline_prepare
                    try:
                        known[key], _ = timeline_prepare.scalar(inputs[key], graph, "settings." + key)
                    except ValueError:
                        pass
            result = inspect(folder, parsed, known, body.get("box"))
            if result["receipt"] is not None and body.get("editor"):
                editor = {key: body["editor"][key] for key in ("graph", "node")}
                editor["fingerprint"] = _editor_fingerprint(editor, body["box"])
                result["receipt"]["editor"] = editor
            return result
    except (ValueError, OSError) as error:
        return dict(ok=False, error=str(error))


def commit(folder, entry, recovery, now):
    from . import saved_state
    with saved_state.LOCK:
        return _commit(folder, entry, recovery, now)


def _commit(folder, entry, recovery, now):
    """Install already-written replacement media; roll back archived files if commit fails.

    Caller holds SEQUENCE_LOCK. Existing media stays active until all replacement files exist.
    """
    parsed = rules.parse(json.dumps(recovery["timeline"]))
    result = validate(folder, parsed, recovery["settings"], recovery["box"], recovery["receipt"])
    manifest = store.load_manifest(folder)
    store.align(manifest, [box.id for box in parsed.boxes])
    ids = {recovery["box"], *(item["id"] for item in result["affected"])}
    bridge_ids = {item["id"] for item in result["bridges"]}
    moves, folders = [], []
    try:
        for key in ("segments", "bridges"):
            removed = []
            for old in manifest.get(key, []):
                if (store.box_of(old) in ids if key == "segments" else old["box"] in bridge_ids):
                    relative = store._take_folder(folder, old["stem"], now)
                    folders.append(relative)
                    for file in store._stem_files(folder, old["stem"]):
                        store._move(os.path.join(folder, file), os.path.join(folder, relative, file), moves)
                    manifest.setdefault("takes", []).append({
                        "index" if key == "segments" else "bridge": old["index"] if key == "segments" else old["box"],
                        "archived": now.isoformat(timespec="seconds"), "folder": relative})
                    removed.append(old)
            manifest[key] = [old for old in manifest.get(key, []) if old not in removed]
        manifest["segments"].append(copy.deepcopy(entry))
        manifest["segments"].sort(key=lambda item: item["index"])
        for key in ("full_video", "preview_video", "partial_video"):
            manifest.pop(key, None)
        store.write_manifest(folder, manifest)
    except Exception:
        store.undo_moves(folder, moves, None)
        for relative in reversed(folders):
            path = os.path.join(folder, relative)
            if not os.listdir(path):
                os.rmdir(path)
        raise
    return manifest
