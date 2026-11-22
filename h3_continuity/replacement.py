"""Replacement bridges: a reviewed region around a cut that a generated candidate replaces with exactly as many
frames, so the sequence keeps its duration and a locked recording keeps its place. Pure Python.

A replacement before box B covers sequence frames [J - left, J + right), J being B's first frame. Its run carries
C' frames of the surviving footage before the region and freezes E' frames of the surviving footage after it, each
on H3's 17k+5 grid, so C' + N + E' stays on the grid for N = left + right in 12, 29 or 46."""

from dataclasses import dataclass

from .timing import FPS
from . import dialogue
from . import timeline as rules

GRID = 17
# Why no replacement renders or plays, or "" while they may.
UNAVAILABLE = ("replacement bridges are unavailable because generated candidates still jump at their joins, so the "
               "original cut plays")


@dataclass
class Geometry:
    index: int
    join: int
    left: int
    right: int
    frames: int
    start: int
    end: int
    context_frames: int = 0
    ending_frames: int = 0
    # (box index, first frame in that box's saved run, frames); a run's frame 0 is its first carried frame.
    left_window: tuple | None = None
    right_window: tuple | None = None
    generated: int = 0
    problem: str = ""


def canon_floor(frames):
    """The longest 17k+5 length within `frames`, or None below 5."""
    return None if frames < 5 else GRID * ((frames - 5) // GRID) + 5


def records(timeline):
    """Every bridge record, insertion or replacement, in the Timeline's order."""
    return timeline.all_bridges


def position(timeline, bridge):
    return next(index for index, box in enumerate(timeline.boxes) if box.id == bridge["before"])


def sequence_start(timeline, index):
    return round(rules.box_start(timeline, index) * 24)


def _coverage(timeline):
    return {position(timeline, item): (item["left"], item["right"]) for item in timeline.replacements}


def geometry(timeline, bridge, context):
    """Where the replacement before `bridge["before"]` sits and what its run reads, with `problem` set when the
    surviving footage can't hold it."""
    index = position(timeline, bridge)
    left, right = bridge["left"], bridge["right"]
    join = sequence_start(timeline, index)
    shape = Geometry(index, join, left, right, left + right, join - left, join + right)
    name = f"the replacement before box {index + 1}"
    try:
        played_a, carried_a = rules.box_length(timeline, rules.previous_index(timeline,index), context)
        played_b, _ = rules.box_length(timeline, index, context)
    except ValueError as error:
        shape.problem = str(error).removeprefix("H3 Timeline: ")
        return shape
    coverage = _coverage(timeline)
    taken_a = coverage.get(rules.previous_index(timeline,index), (0, 0))[1]
    taken_b = coverage.get(rules.following_index(timeline,index), (0, 0))[0]
    kept_a, kept_b = played_a - taken_a - left, played_b - right - taken_b
    carried = canon_floor(min(context, carried_a + kept_a))
    frozen = canon_floor(min(context, kept_b))
    for kept, taken, number, neighbour, ends, minimum in (
            (kept_a, taken_a, index, index, carried, "carry"), (kept_b, taken_b, index + 1, index + 2, frozen, "freeze")):
        if kept < 1 and taken:
            shape.problem = (f"{name} overlaps the replacement before box {neighbour}: together they leave no frame "
                             f"of box {number}")
        elif kept < 1:
            shape.problem = f"{name} takes every frame of box {number}; leave at least one"
        elif ends is None:
            shape.problem = (f"{name} leaves {kept} frame{'' if kept == 1 else 's'} of box {number} beside it; H3 "
                             f"needs at least 5 to {minimum}")
        if shape.problem:
            return shape
    shape.context_frames, shape.ending_frames = carried, frozen
    shape.left_window = (rules.previous_index(timeline,index), carried_a + played_a - left - carried, carried)
    shape.right_window = (index, right, frozen)
    shape.generated = carried + shape.frames + frozen
    return shape


def _seconds(frames):
    return f"{frames / FPS:.2f} s"


def _overlaps(mark, span):
    return mark["start"] < span[1] and mark["end"] > span[0]


def protections(timeline, index, takes=None, projected=None):
    """What lies in the two boxes beside box `index`'s join and may keep their footage, in sequence frames, in the
    order `check` reads them: cue speech by portrayal ("on_screen", "voiceover", "unknown"), recordings that
    "changed" under their cues, and "observed" marks, `current` while they were marked on the take in place."""
    join = sequence_start(timeline, index)
    near = (join - rules.played_frames(timeline, rules.previous_index(timeline,index)), join + rules.played_frames(timeline, index))
    found = []
    for item in dialogue.projected(timeline) if projected is None else projected:
        cue = item["cue"]
        base = {"id": cue["id"], "speaker": cue.get("speaker", "").strip() or "A speaker", "text": cue["text"],
                "slot": item["slot"], "checked": item["aligned"]}
        if item["state"] == "changed":
            clip = next(clip for clip in timeline.audio_clips if clip["slot"] == item["slot"])
            found.append({"kind": "changed", "start": dialogue.frame_floor(clip["start"]),
                          "end": dialogue.frame_ceil(clip["start"] + clip["duration"]), **base})
        else:
            found.extend({"kind": portrayal, "start": a, "end": b, **base} for a, b, portrayal in item["segments"])
    positions = {box.id: i for i, box in enumerate(timeline.boxes)}
    for mark in dialogue.observed(timeline):
        if mark["box"] in positions:
            first = sequence_start(timeline, positions[mark["box"]])
            found.append({"kind": "observed", "start": first + mark["start"], "end": first + mark["end"],
                          "id": mark["id"], "label": mark.get("label") or "observed footage", "box": mark["box"],
                          "current": takes is None or takes.get(mark["box"]) == mark["take"]})
    return [mark for mark in found if _overlaps(mark, near)]


def _protection(timeline, shape, takes, projected):
    region = (shape.start, shape.end)
    positions = {box.id: i for i, box in enumerate(timeline.boxes)}
    for mark in protections(timeline, shape.index, takes, projected):
        kind = mark["kind"]
        if kind == "changed":
            return (f"@{mark['slot']} changed since its cues were written: check cue {mark['id']!r} against the "
                    "new recording, or remove it")
        if kind == "observed":
            number = positions[mark["box"]] + 1
            if not mark["current"]:
                return (f"observed protection {mark['label']!r} was marked on an earlier take of box {number}: mark "
                        "it again on this take, or remove it")
            if _overlaps(mark, region):
                return (f"box {number} has observed protection {mark['label']!r} from {_seconds(mark['start'])} to "
                        f"{_seconds(mark['end'])}, inside the region: shorten or move the region")
            continue
        if kind == "voiceover":
            continue
        if _overlaps(mark, region):
            what = "speaks on screen" if kind == "on_screen" else "has a line of unknown portrayal"
            return (f"{mark['speaker']} {what} from {_seconds(mark['start'])} to {_seconds(mark['end'])}, inside the "
                    f"region ({_seconds(shape.start)} to {_seconds(shape.end)}): shorten or move the region, or mark "
                    "that part of the line as off-screen voiceover")
        if not mark["checked"]:
            return (f"check cue {mark['id']!r} ({mark['speaker']}: {mark['text']!r}) against the recording before "
                    "replacing footage near it")
    return ""


def check(timeline, bridge, context, takes=None, projected=None):
    """Why the replacement can't be confirmed or rendered as it stands, or "". `takes` maps box ids to their current
    take identity; without it observed protections count as current."""
    shape = geometry(timeline, bridge, context)
    if shape.problem:
        return shape.problem
    return _protection(timeline, shape, takes, dialogue.projected(timeline) if projected is None else projected)


def stand_in(timeline, index):
    """The replacement record at box `index`'s join, or an uncovered one."""
    box_id = timeline.boxes[index].id
    return next((item for item in timeline.replacements if item["before"] == box_id),
                {"before": box_id, "mode": "replace", "left": 0, "right": 0, "seed": 0, "prompt": ""})


def options(timeline, index, context, takes=None, projected=None):
    """[[N, [left coverage that geometry and protection allow]]] for each replacement length."""
    bridge = stand_in(timeline, index)
    projected = dialogue.projected(timeline) if projected is None else projected
    return [[frames, [left for left in range(frames + 1)
                      if not check(timeline, {**bridge, "left": left, "right": frames - left}, context, takes, projected)]]
            for frames in rules.BRIDGE_FRAMES]


def proposal(timeline, index, context, takes=None, choices=None):
    """(N, left) to suggest: 29 frames before 12 and 46, split as evenly as allowed; None when nothing fits."""
    allowed = dict(choices if choices is not None else options(timeline, index, context, takes))
    for frames in (29, 12, 46):
        if allowed.get(frames):
            return frames, min(allowed[frames], key=lambda left: (abs(left - frames / 2), left))
    return None


def static_key(timeline, bridge, context):
    """Everything a reviewed region depends on except the endpoint takes: its coverage and windows, and the cues,
    protections and recordings around it. Node settings are compared per candidate, where they are known."""
    shape = geometry(timeline, bridge, context)
    span = (shape.start - shape.context_frames, shape.end + shape.ending_frames)
    cues = [{"id": item["id"], "state": item["state"], "key": dialogue.alignment_key(item["cue"]),
             "aligned": item["aligned"], "portrayal": item["cue"]["portrayal"], "segments": item["segments"]}
            for item in dialogue.projected(timeline)
            if item["state"] != "bound" or any(a < span[1] and b > span[0] for a, b, _ in item["segments"])]
    marks = [{key: mark.get(key) for key in ("id", "box", "take", "start", "end")} for mark in dialogue.observed(timeline)]
    clips = [{key: clip.get(key) for key in ("slot", "file", "start", "source_start", "duration", "locked", "in_full_video")}
             for clip in timeline.audio_clips if clip.get("locked") or clip.get("in_full_video")]
    bound = {clip['slot'] for clip in timeline.audio_clips if 'box_windows' in clip}
    for clip in clips:
        if clip['slot'] in bound:
            clip['windows'] = [w for w in rules.resolved_audio(timeline) if w['slot']==clip['slot']]
    return rules._digest({"boxes": [timeline.boxes[rules.previous_index(timeline,shape.index)].id, timeline.boxes[shape.index].id],
                          "join": shape.join, "left": shape.left, "right": shape.right,
                          "windows": [shape.left_window, shape.right_window], "problem": shape.problem,
                          "cues": cues, "observed": marks, "clips": clips})


def region_key(static, before, after):
    """The reviewed region's identity with the saved takes it reads (each {box, stamp} or None)."""
    return rules._digest([static, before, after])


def recipe(timeline, bridge):
    """What tells one candidate render from another of the same region."""
    from . import bridges
    return rules._digest({"prompt": bridges.prompt(timeline, bridge), "seed": bridge["seed"]})


def trims(timeline, active):
    """{box index: (frames cut from its start, frames cut from its end)} for the replacements in `active` (ids)."""
    result = {}
    for item in timeline.replacements:
        if item["before"] not in active:
            continue
        index = position(timeline, item)
        result[rules.previous_index(timeline,index)] = (result.get(rules.previous_index(timeline,index), (0, 0))[0], item["left"])
        result[index] = (item["right"], result.get(index, (0, 0))[1])
    return result
