"""The continuity check's results, by box, in the sequence folder's checks.json. A result is for the render it was
made for: the manifest entry's layout key and render time."""

import datetime
import json
import os

FILE = "checks.json"
VERSION = 1


def load(folder):
    """The results by box id; {} for a missing or unreadable file."""
    try:
        with open(os.path.join(folder, FILE), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    boxes = data.get("boxes") if isinstance(data, dict) else None
    if not isinstance(boxes, dict):
        return {}
    return {box_id: record for box_id, record in boxes.items() if isinstance(record, dict)}


def save(folder, box_id, record):
    """Saves box `box_id`'s result, keeping the others'."""
    boxes = load(folder)
    boxes[box_id] = record
    path = os.path.join(folder, FILE)
    with open(path + ".tmp", "w", encoding="utf-8") as handle:
        json.dump({"version": VERSION, "boxes": boxes}, handle, ensure_ascii=False, indent=1)
    os.replace(path + ".tmp", path)


def record(entry, model, problems, drift, error=None, holds=None):
    """The result for the render of manifest entry `entry`. `problems` is None when no Vision model ran or its reply
    couldn't be read, which `error` then says; `drift` is {"box", "words", "texture"} or None; `holds` lists still
    holds ({"start_ms", "frames", "join"}) or is None when they couldn't be measured."""
    made = {"layout": (entry.get("timeline") or {}).get("layout"), "created": entry.get("created"),
            "checked": datetime.datetime.now().isoformat(timespec="seconds"), "model": model or None,
            "problems": problems, "drift": drift}
    if error:
        made["error"] = error
    if holds is not None:
        made["holds"] = holds
    return made


def current(record, entry):
    """Whether `record` is for the render of manifest entry `entry`."""
    return bool(record and entry) and (record.get("layout") == (entry.get("timeline") or {}).get("layout")
                                       and record.get("created") == entry.get("created"))


def status(record, entry):
    """What the Timeline's status shows for a box: its result without the render's key when current, {"stale": True}
    when it was for an earlier render, None without a result or a rendered video."""
    if not record or not entry or not entry.get("video"):
        return None
    if not current(record, entry):
        return {"stale": True}
    return {key: value for key, value in record.items() if key not in ("layout", "created")}
