"""Merge a run of continuing boxes into one long box, so a windowed sample replaces the carried-context seams."""

import copy
import json

from . import timeline as rules


def _error(message):
    return ValueError(f"H3 Timeline: {message}")


def merge_continuing(text, first_id, last_id):
    """Timeline JSON text with the boxes from `first_id` to `last_id` merged into one box that keeps `first_id`.

    Every box after the first must continue the one before it (not a cut) and play its generated frames exactly, so
    the merged box is the same movie time on the 17k+5 grid. Prompts join in order; picture previews and plate
    changes move by the frames played before them; the Timeline's `max_frames` rises to hold the box."""
    parsed = rules.parse(text)
    data = json.loads(text)
    ids = [box.id for box in parsed.boxes]
    if first_id not in ids or last_id not in ids or ids.index(first_id) >= ids.index(last_id):
        raise _error("merge needs two box ids, the first earlier than the last")
    start, end = ids.index(first_id), ids.index(last_id)
    owners = set(ids[start:end + 1])
    if any(owners.intersection(clip.get('box_windows', {}).get('by_box', {})) for clip in parsed.audio_clips):
        raise _error('unlock box-bound audio before merging its boxes')
    for index in range(start, end + 1):
        if rules.is_exact(parsed, index):
            raise _error(f"box {index + 1} has an exact length; turn Exact length off before merging")
        if index > start and rules.is_fresh(parsed, index):
            raise _error(f"box {index + 1} is a cut, not a continuation of box {index}; only continuing boxes merge")
        if index > start and parsed.boxes[index].first:
            raise _error(f"box {index + 1} has a first frame, which a continuing box does not use; clear it to merge")
    played = [rules.played_frames(parsed, index) for index in range(start, end + 1)]
    total = sum(played)
    if total > rules.LONG_MAX_FRAMES:
        raise _error(f"the merged box would be {total} frames; the most a Timeline allows is {rules.LONG_MAX_FRAMES}")
    raw = data["boxes"]
    merged = copy.deepcopy(raw[start])
    merged["frames"] = total
    merged.pop("seconds", None)
    merged["prompt"] = "\n\n".join(parsed.boxes[index].prompt.strip() for index in range(start, end + 1)
                                   if parsed.boxes[index].prompt.strip())
    merged["last"] = raw[end].get("last", "")
    offset = 0
    for position, index in enumerate(range(start, end + 1)):
        if position:
            for key in ("previews", "plate_changes"):
                for item in raw[index].get(key, []):
                    merged.setdefault(key, []).append({**item, "frame": item["frame"] + offset})
        offset += played[position]
    data["boxes"] = raw[:start] + [merged] + raw[end + 1:]
    data["max_frames"] = max(data.get("max_frames", rules.MAX_FRAMES), total)
    result = json.dumps(data)
    rules.parse(result)
    return result


def seam_count(timeline):
    """Continuing boxes in `timeline`: each one is a seam a windowed merge could remove."""
    return sum(1 for index in range(len(timeline.boxes)) if not rules.is_fresh(timeline, index))
