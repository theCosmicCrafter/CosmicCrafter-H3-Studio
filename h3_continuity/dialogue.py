"""Dialogue cues bound to the Timeline's recordings: identity, source and sequence clocks, and what a locked
recording means for the picture. Pure Python.

A cue's times belong to its recording's source; the clip placement maps them onto the sequence, as
`sequence = clip.start + source - clip.source_start`."""

import copy
import hashlib
import json
import math

from .timing import FPS
from . import timed_text

VERSION = 1
PORTRAYALS = ("on_screen", "voiceover", "unknown")
ORIGINS = ("manual", "transcript", "story")
RECORDING_SLOTS = ("audio1", "audio2", "audio3")
# Clip and cue times are decimal seconds; a frame edge within this of a time is that edge.
EPSILON = 1e-6


def _error(message):
    return ValueError(f"H3 Timeline: dialogue {message}")


def _seconds(value, what):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise _error(f"{what} must be a nonnegative number of seconds")
    return value


def _same_file(one, other):
    if not isinstance(one, dict) or not isinstance(other, dict):
        return False
    return all(one.get(key, "") == other.get(key, "") for key in ("type", "subfolder", "filename"))


def validate(value):
    """An independent copy of the Timeline's `dialogue`, or None; raises naming the problem."""
    if value is None:
        return None
    from . import timeline as rules
    if not isinstance(value, dict) or value.get("version") != VERSION:
        raise _error(f"must be an object with version {VERSION}")
    if not isinstance(value.get("cues", []), list) or not isinstance(value.get("observed", []), list):
        raise _error("cues and observed must be lists")
    ids = set()
    for n, cue in enumerate(value.get("cues", []), 1):
        if not isinstance(cue, dict) or not isinstance(cue.get("id"), str) or not cue["id"] or cue["id"] in ids:
            raise _error(f"cue {n} needs a unique nonempty id")
        ids.add(cue["id"])
        name = f"cue {cue['id']!r}"
        recording = cue.get("recording")
        if not isinstance(recording, dict) or recording.get("slot") not in RECORDING_SLOTS:
            raise _error(f"{name} needs a recording on audio1, audio2 or audio3")
        rules.audio_file(recording.get("file"))
        start, end = _seconds(cue.get("start"), f"{name} start"), _seconds(cue.get("end"), f"{name} end")
        if end <= start:
            raise _error(f"{name} must end after its start")
        if not isinstance(cue.get("text"), str) or not cue["text"].strip():
            raise _error(f"{name} needs its exact words")
        token = timed_text.CONTROL.search(cue["text"])
        if token:
            raise _error(f"{name} contains {token.group(0)!r}; write only the spoken words")
        for key in ("speaker", "language", "aligned"):
            if key in cue and not isinstance(cue[key], str):
                raise _error(f"{name} {key} must be text")
        if cue.get("portrayal") not in PORTRAYALS:
            raise _error(f"{name} portrayal must be on_screen, voiceover or unknown")
        if cue.get("origin", "manual") not in ORIGINS:
            raise _error(f"{name} origin must be manual, transcript or story")
        spans = cue.get("spans", [])
        if not isinstance(spans, list):
            raise _error(f"{name} spans must be a list")
        previous = start
        for span in spans:
            if not isinstance(span, dict) or span.get("portrayal") not in PORTRAYALS:
                raise _error(f"{name} spans need an on_screen, voiceover or unknown portrayal")
            _seconds(span.get("start"), f"{name} span start")
        for span in sorted(spans, key=lambda item: item["start"]):
            low, high = _seconds(span.get("start"), f"{name} span start"), _seconds(span.get("end"), f"{name} span end")
            if not start <= low < high <= end:
                raise _error(f"{name} spans must lie inside its cue")
            if low < previous - EPSILON:
                raise _error(f"{name} spans overlap")
            previous = high
    observed_ids = set()
    for n, item in enumerate(value.get("observed", []), 1):
        if (not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]
                or item["id"] in observed_ids or not isinstance(item.get("box"), str)
                or not isinstance(item.get("take"), str) or not isinstance(item.get("label", ""), str)
                or type(item.get("start")) is not int or type(item.get("end")) is not int
                or not 0 <= item["start"] < item["end"]):
            raise _error(f"observed protection {n} needs a unique id, a box, its take and a frame range")
        observed_ids.add(item["id"])
    return copy.deepcopy(value)


def cues(timeline):
    return (timeline.dialogue or {}).get("cues", [])


def observed(timeline):
    return (timeline.dialogue or {}).get("observed", [])


def binding(cue, timeline):
    """("bound" | "missing" | "changed", clip or None): whether the cue's recording still plays from its slot."""
    from . import reference_replacements
    slot = cue["recording"]["slot"]
    clip = next((item for item in timeline.audio_clips if item["slot"] == slot), None)
    if clip is None or slot in timeline.disabled_refs:
        return "missing", None
    if not _same_file(reference_replacements.file_for(timeline, slot), cue["recording"]["file"]):
        return "changed", clip
    return "bound", clip


def alignment_key(cue):
    """What a user checks against the recording: its words, its source interval and the recording itself."""
    file = cue["recording"]["file"]
    value = [cue["recording"]["slot"], [file.get(key, "") for key in ("type", "subfolder", "filename")],
             cue["start"], cue["end"], cue["text"]]
    return hashlib.sha1(json.dumps(value, separators=(",", ":")).encode("utf-8")).hexdigest()


def is_aligned(cue):
    return cue.get("aligned") == alignment_key(cue)


def frame_floor(seconds):
    return math.floor(seconds * FPS + EPSILON)


def frame_ceil(seconds):
    return math.ceil(seconds * FPS - EPSILON)


def _segments(cue):
    """(source start, source end, portrayal) covering the cue; spans override its portrayal."""
    result, cursor = [], cue["start"]
    for span in sorted(cue.get("spans", []), key=lambda item: item["start"]):
        if span["start"] > cursor:
            result.append((cursor, span["start"], cue["portrayal"]))
        result.append((span["start"], span["end"], span["portrayal"]))
        cursor = span["end"]
    if cursor < cue["end"]:
        result.append((cursor, cue["end"], cue["portrayal"]))
    return result


def placed(cue, clip):
    """The cue through its clip's placed window, or None when the window leaves none of it. `frames` and
    `segments` round speech outward to whole sequence frames."""
    low, high = clip["source_start"], clip["source_start"] + clip["duration"]
    start, end = max(cue["start"], low), min(cue["end"], high)
    if end - start <= EPSILON:
        return None

    def sequence(seconds):
        return clip["start"] + seconds - low

    segments = []
    for first, last, portrayal in _segments(cue):
        first, last = max(first, start), min(last, end)
        if last - first > EPSILON:
            segments.append((frame_floor(sequence(first)), frame_ceil(sequence(last)), portrayal))
    return {"source": (start, end), "sequence": (sequence(start), sequence(end)),
            "frames": (frame_floor(sequence(start)), frame_ceil(sequence(end))),
            "cut": start > cue["start"] + EPSILON or end < cue["end"] - EPSILON, "segments": segments}


def projected(timeline):
    """Every cue with its binding state and, when bound and placed, its sequence position."""
    result = []
    for cue in cues(timeline):
        state, clip = binding(cue, timeline)
        if state == 'bound' and 'box_windows' in clip:
            from . import audio_windows, timeline as rules
            positions = audio_windows.coalesce(audio_windows.resolve(clip,rules.audio_box_spans(timeline)))
            places = [where for window in positions if (where := placed(cue,window)) is not None]
        else:
            places = [placed(cue, clip) if state == 'bound' else None]
        for where in places or [None]:
            result.append({"id": cue["id"], "cue": cue, "state": state, "slot": cue["recording"]["slot"],
                       "aligned": is_aligned(cue), "placed": where is not None,
                       "cut": bool(where and where["cut"]), "sequence": where and where["sequence"],
                       "frames": where and where["frames"], "segments": where["segments"] if where else []})
    return result


def summary(timeline):
    """What the Studio shows of each cue beyond what it wrote: its binding, check and sequence position."""
    return [{"id": item["id"], "slot": item["slot"], "state": item["state"], "aligned": item["aligned"],
             "placed": item["placed"], "cut": item["cut"],
             "sequence": list(item["sequence"]) if item["sequence"] else None,
             "frames": list(item["frames"]) if item["frames"] else None,
             "segments": [list(segment) for segment in item["segments"]]} for item in projected(timeline)]


def _milliseconds(seconds):
    return math.floor(seconds * 1000 + .5)


def _clock(ms):
    return f"{ms // 60000:02d}:{ms % 60000 // 1000:02d}.{ms % 1000:03d}"


def _window(timeline, index, context):
    """(generation origin, delivered start, delivered end) of box `index` in sequence seconds."""
    from . import timeline as rules
    frames, carried = rules.box_length(timeline, index, context)
    start = rules.box_start(timeline, index)
    return start - carried / FPS, start, start + frames / FPS


def _covering(timeline, index, context):
    """Projected bound cues whose placed interval overlaps the frames box `index` delivers."""
    _, start, end = _window(timeline, index, context)
    return [item for item in projected(timeline) if item["placed"]
            and item["sequence"][1] > start + EPSILON and item["sequence"][0] < end - EPSILON]


def box_events(timeline, index, context):
    """Bound cues on box `index`'s generation clock, in time order; [] for a manual-dialogue box."""
    if not cues(timeline) or (index < len(timeline.manual_dialogue) and timeline.manual_dialogue[index]):
        return []
    origin, _, end = _window(timeline, index, context)
    events = []
    for item in sorted(_covering(timeline, index, context), key=lambda item: (item["sequence"][0], item["id"])):
        cue, (first, last) = item["cue"], item["sequence"]
        low, high = max(first, origin), min(last, end)
        segments = []
        for a, b, portrayal in item["segments"]:
            a, b = max(a / FPS, low), min(b / FPS, high)
            if b - a > EPSILON:
                segments.append((_milliseconds(a - origin), _milliseconds(b - origin), portrayal))
        events.append({"id": cue["id"], "speaker": cue.get("speaker", ""), "text": cue["text"],
                       "language": cue.get("language", ""),
                       "start_ms": _milliseconds(low - origin), "end_ms": _milliseconds(high - origin),
                       "continuing": first < origin - EPSILON, "continues_after": last > end + EPSILON,
                       "segments": segments})
    return events


def speaks(timeline, index):
    """Whether box `index` asks H3 for speech someone may say on screen: typed <d>, or a bound cue over its frames
    that isn't all voiceover. Independent of carried context, so the Studio can show the same answer."""
    from . import timeline as rules
    if "<d>" in timeline.prompt or "<d>" in timeline.boxes[index].prompt:
        return True
    if index < len(timeline.manual_dialogue) and timeline.manual_dialogue[index]:
        return False
    start = round(rules.box_start(timeline, index) * 24)
    end = start + rules.played_frames(timeline, index)
    return any(portrayal != "voiceover" and first < end and last > start
               for item in projected(timeline) for first, last, portrayal in item["segments"])


def _speech(event, number):
    speaker = event["speaker"].strip() or "A speaker"
    who = f"{speaker} (S{number})"
    portrayals = {portrayal for _, _, portrayal in event["segments"]}
    if event["continuing"]:
        return (f"{who} finishes the line already in progress (\"{event['text']}\"); its words started before this "
                "clip, so don't start a new line.")
    language = f"[{event['language']}] " if event["language"] else ""
    if portrayals == {"voiceover"}:
        spoken = (f"{who} says in an off-screen voiceover: <d>{language}{event['text']}</d>; no on-screen "
                  "character's lips move with it.")
    else:
        spoken = f"{who} says: <d>{language}{event['text']}</d>"
        parts = [f"from {_clock(a)} to {_clock(b)}" for a, b, portrayal in event["segments"] if portrayal == "voiceover"]
        if parts:
            spoken += f" (off-screen voiceover {' and '.join(parts)})"
    if event["continues_after"]:
        spoken += " The line is still being spoken at the final frame; don't finish it early."
    return spoken


def block(events):
    """The prompt lines for `events`: exact words at exact times, one line per spoken event."""
    if not events:
        return ""
    lines = ["Dialogue from the recording: speak only these exact words at these times; add no other speech."]
    speakers, previous_end = {}, None
    for event in events:
        number = speakers.setdefault((event["speaker"].strip() or "").casefold(), len(speakers) + 1)
        line = f"From {_clock(event['start_ms'])} to {_clock(event['end_ms'])}: {_speech(event, number)}"
        if previous_end is not None and event["start_ms"] < previous_end:
            line = line.replace(": ", ": Overlapping the preceding speech, ", 1)
        previous_end = max(previous_end or 0, event["end_ms"])
        lines.append(line)
    return "\n" + "\n".join(lines)


def insert(prompt, mode, events):
    return timed_text.insert_block(prompt, mode, block(events)) if events else prompt


def digest(events):
    """Identity of what box dialogue asks H3 for; alignment checks don't change it."""
    value = [{key: event[key] for key in ("speaker", "text", "language", "start_ms", "end_ms", "continuing",
                                          "continues_after", "segments")} for event in events]
    return hashlib.sha1(json.dumps(value, separators=(",", ":")).encode("utf-8")).hexdigest()


def box_problem(timeline, index, context, prompt):
    """Why box `index` can't compile its dialogue, or ""; `prompt` is its assembled text."""
    n = index + 1
    if not cues(timeline) or (index < len(timeline.manual_dialogue) and timeline.manual_dialogue[index]):
        return ""
    covering = _covering(timeline, index, context)
    for item in covering:
        if item["cut"]:
            return (f"box {n}: cue {item['id']!r} is cut by @{item['slot']}'s placed window; review it: extend the "
                    "clip, or edit the cue to the words the clip keeps")
    if covering and "<d>" in prompt:
        return (f"box {n} has typed <d> dialogue and dialogue cues from the recording also cover it: remove the typed "
                "dialogue, or set the box to manual dialogue to keep your prompt and leave the cues out")
    return ""


def locked_clips(timeline):
    return [clip for clip in timeline.audio_clips if clip.get("locked") is True and clip["slot"] not in timeline.disabled_refs]


def lock_conflicts(timeline):
    """Why a locked recording and the picture would not stay together in the full video; [] when they do."""
    from . import replacement, timeline as rules
    advice = ("remove the bridge, so the join plays as a cut" if replacement.UNAVAILABLE
              else "replace within the existing duration, or remove the bridge")
    messages = []
    positions = {box.id: index for index, box in enumerate(timeline.boxes)}
    for clip in locked_clips(timeline):
        slot = clip["slot"]
        if clip.get("in_full_video") is not True:
            messages.append(f"@{slot} is locked to the sequence clock but isn't in the full video: turn on "
                            "In the full video, or unlock it.")
        if 'box_windows' in clip:
            from . import audio_windows
            windows=audio_windows.resolve(clip,rules.audio_box_spans(timeline))
            if not windows: continue
            start,end=min(w['start'] for w in windows),max(w['start']+w['duration'] for w in windows)
        else:
            start, end = clip['start'], clip['start'] + clip['duration']
        for bridge in timeline.bridges:
            index = positions[bridge["before"]]
            join = rules.box_start(timeline, index)
            if start < join < end:
                messages.append(f"@{slot} is locked to the sequence clock, but the bridge before box {index + 1} "
                                f"inserts {bridge['frames'] / FPS:.2f} s inside it, so the picture after it drifts "
                                f"from the recording: {advice}.")
    return messages
