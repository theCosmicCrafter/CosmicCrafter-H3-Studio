"""Saved replacement candidates: renders of a reviewed region kept beside the boxes, never moved or chosen on their
own. A candidate plays only while the Timeline selects it and its region is still the one it was rendered for."""

import hashlib
import os
from dataclasses import dataclass, field

from . import bridges, dialogue, replacement, store
from . import timeline as rules


@dataclass
class State:
    bridge: dict
    index: int
    # unavailable | problem | waiting | review | pending | next | done
    status: str
    note: str
    geometry: replacement.Geometry
    region: str | None
    recipe: str
    # Each {"entry", "state": current | stale | missing}, oldest first.
    candidates: list = field(default_factory=list)
    # none | current | stale | missing
    selected: str = "none"
    options: list = field(default_factory=list)
    proposal: tuple | None = None


def stem(box_id, candidate):
    return "replace@" + bridges.stem(box_id).removeprefix("bridge@") + "-" + candidate


def candidate_id(box_id, created, seed, region):
    return hashlib.sha1(f"{box_id}\n{created}\n{seed}\n{region}".encode("utf-8")).hexdigest()[:8]


def add(manifest, entry):
    manifest.setdefault("replacements", []).append(entry)


def entries(manifest, box_id):
    return [entry for entry in manifest.get("replacements", []) if entry.get("box") == box_id]


def take_id(folder, entry):
    """A saved box take's identity: its latent file's stamp, or None without one."""
    if entry is None or not store.has_segment_latents(folder, entry):
        return None
    return "-".join(str(value) for value in store.latent_stamp(folder, entry))


def takes(folder, timeline, manifest):
    """{box id: take identity} for the boxes saved at their own position."""
    result = {}
    for entry in manifest["segments"]:
        index = entry["index"] - 1
        if 0 <= index < len(timeline.boxes) and (entry.get("timeline") or {}).get("box") == timeline.boxes[index].id:
            result[timeline.boxes[index].id] = take_id(folder, entry)
    return result


def candidate_state(folder, entry, region, known):
    """missing, current, or stale when its region or a known node setting changed."""
    video = entry.get("video")
    if not video or not os.path.isfile(os.path.join(folder, video["file"])):
        return "missing"
    record = entry.get("timeline") or {}
    current = (region is not None and record.get("region") == region
               and rules.settings_match(record.get("settings") or {}, known))
    return "current" if current else "stale"


def states(folder, timeline, manifest, done, known, context):
    """Each replacement's State in Timeline order; `done` holds the indices of the boxes that are done. The first
    pending replacement is next once every box is done."""
    segments = {entry["index"]: entry for entry in manifest["segments"]}
    current_takes = takes(folder, timeline, manifest)
    found = []
    for bridge in timeline.replacements:
        index = replacement.position(timeline, bridge)
        shape = replacement.geometry(timeline, bridge, context)
        trouble = replacement.check(timeline, bridge, context, current_takes)
        links = [bridges.link(folder, segments.get(n)) for n in (index, index + 1)]
        region = None
        if all(links) and [link["box"] for link in links] == [timeline.boxes[rules.previous_index(timeline,index)].id, timeline.boxes[index].id]:
            region = replacement.region_key(replacement.static_key(timeline, bridge, context), *links)
        recipe = replacement.recipe(timeline, bridge)
        saved = [{"entry": entry, "state": candidate_state(folder, entry, region, known)}
                 for entry in entries(manifest, bridge["before"])]
        chosen = bridge.get("selected")
        selected = "none"
        if chosen:
            match = next((item for item in saved if item["entry"].get("candidate") == chosen), None)
            selected = match["state"] if match else "missing"
        waiting = [n for n in (index, index + 1) if n - 1 not in done]
        if replacement.UNAVAILABLE:
            status, note = "unavailable", replacement.UNAVAILABLE
        elif trouble:
            status, note = "problem", trouble
        elif waiting or region is None:
            status, note = "waiting", f"render {' and '.join(f'box {n}' for n in waiting or (index, index + 1))} first"
        elif bridge.get("review") != region:
            status = "review"
            note = ("confirm the region again: its footage, cues or settings changed since you confirmed it"
                    if bridge.get("review") else "confirm the region before rendering a candidate")
        elif any(item["state"] == "current" and (item["entry"].get("timeline") or {}).get("recipe") == recipe
                 for item in saved):
            status, note = "done", ""
        else:
            status, note = "pending", ""
        found.append(State(bridge, index, status, note, shape, region, recipe, saved, selected))
    if len(done) == len(timeline.boxes):
        upcoming = next((state for state in found if state.status == "pending"), None)
        if upcoming:
            upcoming.status = "next"
    return found


def active(found):
    """{box id: candidate entry} for the replacements whose selected candidate plays in the full video: current, in
    a region that is still the reviewed one."""
    result = {}
    for state in found:
        if state.selected == "current" and state.status not in ("unavailable", "problem", "waiting", "review"):
            result[state.bridge["before"]] = next(item["entry"] for item in state.candidates
                                                  if item["entry"].get("candidate") == state.bridge["selected"])
    return result


def region(timeline, shape):
    """The region in sequence frames, with the frames it covers in each box's own delivered footage."""
    before = timeline.boxes[rules.previous_index(timeline,shape.index)]
    played = rules.played_frames(timeline, rules.previous_index(timeline,shape.index))
    return {"join": shape.join, "start": shape.start, "end": shape.end, "left": shape.left, "right": shape.right,
            "frames": shape.frames, "context_frames": shape.context_frames, "ending_frames": shape.ending_frames,
            "before": [before.id, played - shape.left, played], "after": [timeline.boxes[shape.index].id, 0, shape.right]}


def _listed(entry, state, recipe, view):
    record, created = entry.get("timeline") or {}, entry.get("created", "")
    video, preview = entry.get("video"), entry.get("preview")
    return {"candidate": entry.get("candidate"), "created": created, "seed": record.get("seed"), "state": state,
            "recipe": record.get("recipe") == recipe, "left": record.get("left"), "right": record.get("right"),
            "frames": entry.get("played"), "video": view(video["file"], created) if video else None,
            "preview": None if not preview else {
                "file": view(preview["file"], created), "original": view(preview["original"], created),
                "frames": preview["frames"], "region": preview["region"], "fps": preview["fps"]}}


def item(state, timeline, context, view, takes=None):
    """What the Studio shows for replacement `state`: its exact region, what protects footage near it, the coverage
    the region may take instead, its candidates, and the take each endpoint box is on, which an observed protection
    names. `view(filename, version)` gives a candidate file's /view dict; `takes` maps box ids to their take identity,
    as in `replacement.check`."""
    bridge = state.bridge
    ends = (timeline.boxes[rules.previous_index(timeline,state.index)].id, bridge["before"])
    projected = dialogue.projected(timeline)
    choices = replacement.options(timeline, state.index, context, takes, projected)
    proposal = replacement.proposal(timeline, state.index, context, takes, choices)
    found = {"box": bridge["before"], "mode": "replace", "status": state.status,
             "region": region(timeline, state.geometry), "region_key": state.region,
             "reviewed": state.region is not None and bridge.get("review") == state.region,
             "protected": replacement.protections(timeline, state.index, takes, projected),
             "options": choices, "proposal": list(proposal) if proposal else None,
             "candidates": [_listed(saved["entry"], saved["state"], state.recipe, view) for saved in state.candidates],
             "selected": bridge.get("selected"), "selection": state.selected,
             "plays": bridge["before"] in active([state]),
             "takes": {box_id: (takes or {}).get(box_id) for box_id in ends}}
    if state.note:
        found["note"] = state.note
    return found


def selected_entries(folder, manifest, selections):
    """The candidates `selections` ({box, candidate}) names whose video is saved and whose two boxes are still the
    saved takes they were rendered from."""
    boxes = {(entry.get("timeline") or {}).get("box"): entry for entry in manifest["segments"]}
    segments = {entry["index"]: entry for entry in manifest["segments"]}
    found = []
    for wanted in selections:
        entry = next((item for item in entries(manifest, wanted["box"])
                      if item.get("candidate") == wanted["candidate"]), None)
        after = boxes.get(wanted["box"])
        before = segments.get(after["index"] - 1) if after else None
        if entry is None or before is None or candidate_state(folder, entry, None, {}) == "missing":
            continue
        record = entry.get("timeline") or {}
        if record.get("from") == bridges.link(folder, before) and record.get("to") == bridges.link(folder, after):
            found.append(entry)
    return found


def prepare(state, latent, positive, negative, sequence, before, after, vae, carry_audio, *, audio_context_frames=0):
    """The candidate's `latent` with the surviving footage carried at its start and frozen at its end, and its
    SegmentPlan. `sequence` is (name, folder, index, base entry); `before` and `after` are the two boxes' saved
    (video, audio) latents."""
    from . import latents, nodes as continuity
    shape = state.geometry
    carried = latents.window(*before, shape.left_window[1], shape.context_frames, vae)
    reference = continuity.SequenceRef(*sequence, *carried)
    latent, positive, negative, segment, _ = continuity.prepare_segment(
        reference, latent, shape.context_frames, carry_audio, positive, negative, node="H3 Timeline",
        audio_context_frames=audio_context_frames)
    frozen = latents.window(*after, shape.right_window[1], shape.ending_frames, vae)
    latent, segment.ending_video, segment.ending_audio = latents.build_ending(
        latent, *frozen, shape.ending_frames, carry_audio, segment.context_frames)
    positive, _ = latents.drop_guides_before(positive, 0, segment.frames - shape.ending_frames)
    negative, _ = latents.drop_guides_before(negative, 0, segment.frames - shape.ending_frames)
    segment.preserve_following = True
    return latent, positive, negative, segment


def plan(timeline, state, width, height, context, carry_audio, *, audio_context_frames=0):
    """The run that renders a candidate: T2VA without references, between C' carried and E' frozen frames."""
    bridge, shape = state.bridge, state.geometry
    stand_in = rules.Box(bridge["before"], shape.frames, bridge["prompt"], bridge["seed"], True, "", "")
    settings = bridges.settings(width, height, context, carry_audio, audio_context_frames=audio_context_frames)
    return rules.BoxPlan(state.index, stand_in, False, shape.frames, shape.context_frames, shape.generated,
                         rules.Slots("t2va", [], [], "", "", {}), bridges.prompt(timeline, bridge), state.recipe,
                         settings, [])
