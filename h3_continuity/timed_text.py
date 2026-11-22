"""Exact transcript import and source/movie clocks for visible text. Pure Python."""

import copy
import hashlib
import json
import math
import re

from .timing import FPS


def _error(field, message):
    return ValueError(f"timed_text.{field} {message}")


def _number(value, field, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise _error(field, "must be a finite number")
    if value < 0 or (positive and value == 0):
        raise _error(field, "must be positive" if positive else "must be nonnegative")
    return value


CONTROL = re.compile(r"</?d>|<\|[^>]*\|>|</?(?:scenetrans|cutoff)>")


def check_literal(text, identity):
    token = CONTROL.search(text)
    if token:
        raise _error(identity, f"contains unsupported literal {token.group(0)!r}")


def validate(value):
    """Validate without text/timing repair; return an independent attachment copy."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise _error("attachment", "must be an object")
    if type(value.get("version")) is not int or value["version"] != 1:
        raise _error("version", "must be 1")
    for key in ("source_name", "direction"):
        if not isinstance(value.get(key), str):
            raise _error(key, "must be text")
    for key in ("source_sha256", "audio_sha256"):
        if key == "audio_sha256" and key not in value:
            continue
        if not isinstance(value.get(key), str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value[key]):
            raise _error(key, "must be a SHA-256 hex digest")
    for key in ("enabled", "sync_audio"):
        if type(value.get(key)) is not bool:
            raise _error(key, "must be a boolean")
    if value.get("audio_slot") not in ("audio1", "audio2", "audio3"):
        raise _error("audio_slot", "must be audio1, audio2 or audio3")
    for key in ("start", "source_start", "duration"):
        _number(value.get(key), key, key == "duration")
    for key in ("cues", "words"):
        if key == "words" and key not in value:
            continue
        if not isinstance(value.get(key), list):
            raise _error(key, "must be a list")
        ids = set()
        for index, item in enumerate(value[key]):
            field = f"{key}[{index}]"
            if not isinstance(item, dict):
                raise _error(field, "must be an object")
            if not isinstance(item.get("id"), str) or not item["id"] or item["id"] in ids:
                raise _error(f"{field}.id", "must be unique nonempty text")
            ids.add(item["id"])
            if not isinstance(item.get("text"), str):
                raise _error(f"{field}.text", "must be text")
            check_literal(item["text"], f"{field} ({item['id']})")
            start = _number(item.get("start"), f"{field}.start")
            end = _number(item.get("end"), f"{field}.end")
            if end <= start:
                raise _error(f"{field}.end", "must be after start")
    return copy.deepcopy(value)


def _items(raw, prefix):
    if not isinstance(raw, list):
        raise _error(prefix, "must be a list")
    result = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise _error(f"{prefix}[{index}]", "must be an object")
        start, end = item.get("start"), item.get("end")
        if "timestamp" in item:
            timestamp = item["timestamp"]
            if not isinstance(timestamp, (list, tuple)) or len(timestamp) != 2:
                raise _error(f"{prefix}[{index}].timestamp", "must contain start and end")
            start, end = timestamp
        text = item.get("word", item.get("text", item.get("value")))
        result.append(dict(id=f"{prefix}{index + 1}", start=start, end=end, text=text))
    return result


def import_whisper(data, source_name, source_sha256):
    """Adapt segment/word, chunk and raw timing arrays without guessing word times."""
    words = []
    if isinstance(data, list):
        cues = _items(data, "cue")
    elif isinstance(data, dict):
        if "words" in data:
            words = _items(data["words"], "word")
        if "segments" in data:
            cues = _items(data["segments"], "cue")
            if "words" not in data:
                nested = []
                for segment in data["segments"]:
                    if "words" in segment:
                        if not isinstance(segment["words"], list):
                            raise _error("words", "must be a list")
                        nested.extend(segment["words"])
                words = _items(nested, "word")
        elif "chunks" in data:
            cues = _items(data["chunks"], "cue")
        elif "words" in data:
            cues = _items(data["words"], "cue")
        else:
            raise _error("import", "needs segments, chunks, words or a timing array")
    else:
        raise _error("import", "must be an object or timing array")
    if not cues and not words:
        raise _error("import", "contains no timed text")
    value = dict(version=1, source_name=source_name, source_sha256=source_sha256,
                 enabled=True, audio_slot="audio1", sync_audio=False, start=0, source_start=0,
                 duration=1, direction="", cues=cues)
    if words:
        value["words"] = words
    value = validate(value)
    value["duration"] = max(item["end"] for item in cues + words)
    return value


def clock(value, audio_clips, placements=None):
    """Resolve by slot presence; absent synced lanes retain their stored independent clock."""
    if value is None:
        return dict(start=0, source_start=0, duration=0, resolved=False)
    source = value
    resolved = True
    if value["sync_audio"]:
        source = next((clip for clip in audio_clips if clip["slot"] == value["audio_slot"]), None)
        resolved = source is not None
        if source is None:
            source = value
    result = dict(start=source['start'], source_start=source['source_start'], duration=source['duration'], resolved=resolved)
    if value['sync_audio'] and 'box_windows' in source:
        result['box_windows'] = copy.deepcopy(source['box_windows'])
        if placements is not None: result['placements'] = [w for w in placements if w['slot']==value['audio_slot']]
    return result


def _ranges(items, effective, source_start, source_end):
    result = []
    for item in items:
        start, end = max(item["start"], source_start), min(item["end"], source_end)
        if start < end:
            result.append(dict(id=item["id"], text=item["text"], source_start=start, source_end=end,
                               movie_start=effective["start"] + (start - effective["source_start"]),
                               movie_end=effective["start"] + (end - effective["source_start"])))
    return result


def _milliseconds(seconds):
    return math.floor(seconds * 1000 + .5)


def project(value, audio_clips, box_start, frames, carried=0, *, placements=None):
    """Clip exact source ranges to audio selection and generated replay/delivered coverage."""
    effective = clock(value, audio_clips)
    origin = box_start - carried / FPS
    result = dict(direction=value["direction"] if value else "", resolved=effective["resolved"],
                  source_start=None, source_end=None, generated_origin=origin,
                  replay_end_ms=_milliseconds(carried / FPS), cues=[], words=[])
    if value is None or not value["enabled"] or not effective["resolved"]:
        return result
    if 'box_windows' in effective:
        if placements is None: raise ValueError('H3 Timeline: bound timed text needs resolved audio windows')
        from . import audio_windows
        windows = audio_windows.coalesce(w for w in placements if w['slot']==value['audio_slot'])
        result['source_windows'] = []
        for window in windows:
            part = project(dict(value, sync_audio=False, **{key:window[key] for key in ('start','source_start','duration')}),
                           [], box_start, frames, carried)
            if part['source_start'] is not None:
                result['source_windows'].append(dict(source_start=part['source_start'],source_end=part['source_end']))
                for key in ('cues','words'): result[key].extend(part[key])
        if result['source_windows']:
            result['source_start']=min(w['source_start'] for w in result['source_windows'])
            result['source_end']=max(w['source_end'] for w in result['source_windows'])
        for key in ('cues','words'): result[key].sort(key=lambda cue:cue['start_ms'])
        return result
    source_start = max(effective["source_start"], effective["source_start"] + (origin - effective["start"]))
    source_end = min(effective["source_start"] + effective["duration"],
                     effective["source_start"] + (box_start + frames / FPS - effective["start"]))
    if source_start >= source_end:
        return result
    result.update(source_start=source_start, source_end=source_end)
    for key in ("cues", "words"):
        selected = _ranges(value.get(key, []), effective, effective["source_start"], effective["source_start"] + effective["duration"])
        for item in selected:
            continuing = item["movie_start"] < box_start < item["movie_end"]
            replay_only = item["movie_end"] <= box_start
            continues_after = item["source_end"] > source_end
            clipped = _ranges([dict(id=item["id"], text=item["text"], start=item["source_start"], end=item["source_end"])], effective, source_start, source_end)
            if not clipped:
                continue
            cue = clipped[0]
            cue.update(start_ms=_milliseconds(max(0, cue["movie_start"] - origin)),
                       end_ms=_milliseconds(max(0, cue["movie_end"] - origin)),
                       continuing=continuing, replay_only=replay_only, continues_after=continues_after)
            result[key].append(cue)
    return result


def active(value, audio_clips, movie_time, *, placements=None):
    """Visible phrase cues at a half-open movie time, with full effective bounds."""
    effective = clock(value, audio_clips)
    if value is None or not value["enabled"] or not effective["resolved"]:
        return []
    if 'box_windows' in effective:
        if placements is None: raise ValueError('H3 Timeline: bound timed text needs resolved audio windows')
        from . import audio_windows
        return [cue for window in audio_windows.coalesce(w for w in placements if w['slot']==value['audio_slot'])
                for cue in active(dict(value,sync_audio=False,**{key:window[key] for key in ('start','source_start','duration')}),[],movie_time)]
    items = _ranges(value["cues"], effective, effective["source_start"], effective["source_start"] + effective["duration"])
    return [item for item in items if item["movie_start"] <= movie_time < item["movie_end"]]


def render_contract(window):
    """Only the lettering actually requested in this generation affects rendered identity."""
    if not window["cues"]:
        return None
    return dict(direction=window["direction"], replay_end_ms=window["replay_end_ms"],
                cues=[dict({key: cue[key] for key in ("text", "start_ms", "end_ms", "continuing", "replay_only")},
                           continues_after=cue.get("continues_after", False)) for cue in window["cues"]])


def insert(prompt, mode, window):
    """Insert exact visible strings after reference rewriting, inside the visual section."""
    if not window["cues"]:
        return prompt
    lines = ["Visible lettering (not speech or lyrics): preserve the exact strings below, including punctuation and spacing."]
    if window.get("direction"):
        check_literal(window["direction"], "direction")
        lines.append("Lettering treatment: " + window["direction"])
    if window.get("static"):
        lines.append("This still shows only the selected frame's active lettering.")
    else:
        lines.append(f"Replay ends at {window['replay_end_ms']} ms; preserve the carried lettering state and do not repeat entrances. Cue boundaries do not create shot cuts.")
    for cue in window["cues"]:
        check_literal(cue["text"], f"cue ({cue['id']})")
        state = ("selected frame" if window.get("static") else
                 "replay only; do not repeat its entrance or show it after replay" if cue["replay_only"] else
                 "continuing; preserve its existing appearance without another entrance" if cue["continuing"] else
                 "enter once at the stated start")
        if cue.get("continues_after") and not window.get("static") and not cue["replay_only"]:
            state += "; keep this exact text visible through the final generated frame without clearing, fading out, exiting, or another entrance at the clipped end"
        interval = "" if window.get("static") else f"{cue['start_ms']}–{cue['end_ms']} ms, "
        lines.append(f'Visible text ({interval}{state}): "' + cue["text"] + '"')
    return insert_block(prompt, mode, "\n" + "\n".join(lines))


def insert_block(prompt, mode, block):
    """`block` at the end of the prompt's visual section, which an unstructured prompt becomes."""
    section = "detailed_description" if mode == "ref2va" else "integrated_multimodal_description"
    header = re.search(r"(?m)^" + section + r":", prompt)
    if header:
        following = re.search(r"(?m)^(?:summary|subject_definitions|retention_analysis|detailed_description|integrated_multimodal_description|overall_soundscape|non_diegetic_music):", prompt[header.end():])
        end = header.end() + following.start() if following else len(prompt)
        end -= int(end > 0 and prompt[end - 1] == "\n")
        return prompt[:end] + block + prompt[end:]
    return section + ": " + prompt + block


def anchor_metadata(value, audio_clips, movie_time, *, placements=None):
    visible = [cue["text"] for cue in active(value, audio_clips, movie_time, placements=placements)]
    contract = dict(direction=value["direction"] if visible else "", visible_text=visible)
    encoded = json.dumps(contract, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return dict(visible_text=visible, text_contract=hashlib.sha256(encoded).hexdigest())


def check_anchor(image, expected, identity):
    if "visible_text" not in image and "text_contract" not in image:
        return
    if any(image.get(key) != expected[key] for key in ("visible_text", "text_contract")):
        raise ValueError(f"H3 Timeline: {identity} timed text changed; restore the text or remove this lettering image")


def snapshot(value, audio_clips, placements=None):
    """Stable source contract for Story concurrency checks; omit unrelated UI metadata."""
    if value is None:
        return dict(timed_text=None, clock=clock(None, audio_clips))
    keys = ("version", "enabled", "audio_slot", "sync_audio", "start", "source_start", "duration", "direction")
    normalized = {key: copy.deepcopy(value[key]) for key in keys}
    for key in ("cues", "words"):
        normalized[key] = [{field: item[field] for field in ("id", "start", "end", "text")}
                           for item in value.get(key, [])]
    return dict(timed_text=normalized, clock=clock(value, audio_clips, placements))
