"""Bridges: a few generated frames on a cut between two rendered boxes, outside the boxes' Timeline time.

A bridge carries the end of the box before it and freezes the start of its own box, so H3 generates only the move
between them. It is saved beside the boxes and spliced into the full video; no box, segment or box time changes."""

import hashlib
import os
import re
from dataclasses import dataclass

from . import store
from . import timeline as rules


@dataclass
class State:
    bridge: dict
    index: int
    status: str
    note: str = ""
    entry: dict | None = None


def stem(box_id):
    """The bridge's file stem. Sequence names never have `@`, and plain ids never have `_` or capitals, so no two
    stems, and no stem and full video, share a name or the start that moving a take matches, even ignoring case."""
    if re.fullmatch(r"[a-z0-9]{1,40}", box_id):
        return f"bridge@{box_id}"
    return "bridge@_" + hashlib.sha1(box_id.encode("utf-8")).hexdigest()[:12]


def position(timeline, bridge):
    """The index of the bridge's box, the one it leads into."""
    return next(index for index, box in enumerate(timeline.boxes) if box.id == bridge["before"])


def prompt(timeline, bridge):
    """The prompt H3 gets. A bridge sends no reference, so every mention reads as the described subject or sound."""
    parts = [part.strip() for part in (timeline.prompt, bridge["prompt"])]
    slots = [slot for part in parts for _, slot in rules.mentions(part)]
    return rules.join_prompts(*(rules.without_disabled_refs(part, slots) for part in parts))


def problem(timeline, bridge):
    """Why the bridge can't render whatever is saved, or ""."""
    index = position(timeline, bridge)
    dropped = rules.dropped_frames(timeline, rules.previous_index(timeline,index))
    if dropped:
        return (f"box {index} drops {dropped} frames, so the bridge before box {index + 1} can't start from its "
                f"last frame: use a replacement bridge, or give box {index} a length on the grid, which moves every "
                "later box")
    if not prompt(timeline, bridge):
        return f"the bridge before box {index + 1} has no prompt"
    return ""


def layout(timeline, bridge):
    return rules._digest({"prompt": prompt(timeline, bridge), "frames": bridge["frames"], "seed": bridge["seed"]})


def settings(width, height, context, carry_audio, *, audio_context_frames=0):
    """The node settings that change a bridge's render; None where they are unknown."""
    result = rules.box_settings(False, 't2va', width, height, context, carry_audio, None,
                                audio_context_frames=audio_context_frames)
    result.pop('ref_image_size')
    return result


def _source_settings(known, before):
    """A budget covering the bridge's entire bounded head is the default pin."""
    result = dict(known)
    budget, context = result.get('audio_context_frames', 0), result.get('context_frames')
    if budget is not None and context is not None and budget >= min(context, before['frames']):
        result.pop('audio_context_frames', None)
    return result


def key(timeline, bridge, known):
    """What a saved bridge must match: its layout, and the node settings that are known."""
    return {"layout": layout(timeline, bridge),
            "settings": {name: value for name, value in known.items() if value is not None or name == 'audio_context_frames'}}


def splice(timeline, known):
    """Every bridge's key by its box id, for H3 Save Segment."""
    return {bridge["before"]: key(timeline, bridge, known) for bridge in timeline.bridges}


def ends(context, before, after):
    """(C, E): the frames carried from the whole saved segment before, and frozen from the start of the next one."""
    return min(context, before["frames"]), min(context, after["frames"])


def link(folder, entry):
    """The saved segment a bridge is rendered from: its box id and latent stamp, or None."""
    if entry is None or not store.has_segment_latents(folder, entry):
        return None
    return {"box": (entry.get("timeline") or {}).get("box"), "stamp": store.latent_stamp(folder, entry)}


def saved(manifest, box_id):
    return next((entry for entry in manifest.get("bridges", []) if entry.get("box") == box_id), None)


def archive(folder, manifest, entry, now):
    """Moves saved bridge `entry` to takes/ and out of the manifest."""
    relative = store.move_take(folder, entry["stem"], now)
    manifest.setdefault("takes", []).append(
        {"bridge": entry["box"], "archived": now.isoformat(timespec="seconds"), "folder": relative})
    manifest["bridges"] = [other for other in manifest["bridges"] if other is not entry]


def keep(folder, manifest, ids, now):
    """Moves the saved bridges whose box isn't in `ids` to takes/; returns how many moved."""
    gone = [entry for entry in manifest.get("bridges", []) if entry["box"] not in ids]
    for entry in gone:
        archive(folder, manifest, entry, now)
    return len(gone)


def spliced(folder, manifest, keys):
    """The saved bridges the full video plays, in segment order: those whose box is in `keys`, between the two
    saved segments they were rendered from, and current."""
    segments = {entry["index"]: entry for entry in manifest["segments"]}
    boxes = {(entry.get("timeline") or {}).get("box"): entry for entry in manifest["segments"]}
    found = []
    for entry in manifest.get("bridges", []):
        after = boxes.get(entry["box"])
        before = boxes.get((entry.get("timeline") or {}).get("from", {}).get("box")) if after else None
        if entry["box"] in keys and before is not None and not reason(folder, entry, keys[entry["box"]], before, after):
            found.append((after["index"], entry))
    return [entry for _, entry in sorted(found, key=lambda item: item[0])]


def reason(folder, entry, wanted, before, after, files=None):
    """Why saved bridge `entry` needs a render, against `wanted` and the segments it joins, or "" when it is current.
    Its video and latent are looked for in `files`, or in `folder`."""
    record = entry.get("timeline") or {}
    recorded = record.get("settings") or {}
    if record.get("layout") != wanted["layout"]:
        return "its prompt, length or seed changed"
    if not rules.settings_match(_source_settings(recorded, before), _source_settings(wanted['settings'], before)):
        return "the node's width, height, context or audio changed"
    if record.get("from") != link(folder, before):
        return f"box {before['index']} rendered again"
    if record.get("to") != link(folder, after):
        return f"box {after['index']} rendered again"
    video, files = entry.get("video"), files or folder
    if not video or not os.path.isfile(os.path.join(files, video["file"])) or not store.has_segment_latents(files, entry):
        return "its saved files are missing"
    return ""


def states(folder, timeline, manifest, done, known):
    """Each bridge's State, in Timeline order; `done` holds the indices of the boxes that are done. The first
    pending bridge is next once every box is done."""
    segments = {entry["index"]: entry for entry in manifest["segments"]}
    found = []
    for bridge in timeline.bridges:
        index = position(timeline, bridge)
        entry = saved(manifest, bridge["before"])
        trouble = problem(timeline, bridge)
        waiting = [n for n in (rules.previous_index(timeline,index)+1, index+1) if n-1 not in done]
        if trouble:
            found.append(State(bridge, index, "problem", trouble, entry))
        elif waiting:
            found.append(State(bridge, index, "waiting", f"render {' and '.join(f'box {n}' for n in waiting)} first", entry))
        else:
            why = reason(folder, entry, key(timeline, bridge, known), segments[rules.previous_index(timeline,index)+1], segments[index+1]) if entry else ""
            found.append(State(bridge, index, "done" if entry and not why else "pending", why, entry))
    if len(done) == len(timeline.boxes):
        upcoming = next((state for state in found if state.status == "pending"), None)
        if upcoming:
            upcoming.status = "next"
    return found


def plan(timeline, bridge, context, carry_audio, width, height, before, after, *, audio_context_frames=0):
    """The run that renders the bridge: T2VA without references, between C carried and E frozen frames."""
    carried, frozen = ends(context, before, after)
    stand_in = rules.Box(bridge["before"], bridge["frames"], bridge["prompt"], bridge["seed"], True, "", "")
    return rules.BoxPlan(position(timeline, bridge), stand_in, False, bridge["frames"], carried,
                         carried + bridge["frames"] + frozen, rules.Slots("t2va", [], [], "", "", {}),
                         prompt(timeline, bridge), layout(timeline, bridge),
                         _source_settings(settings(width, height, context, carry_audio,
                                                   audio_context_frames=audio_context_frames), before), [])
