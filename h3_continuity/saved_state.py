"""Small, atomic H3 snapshots shared by browsers of this ComfyUI server."""

import hashlib
import json
import os
import tempfile
import threading
import time

import folder_paths


LOCK = threading.RLock()


def path(kind, graph, node):
    if kind not in ("workflow", "job", "library", "deleted", "names") or not all(
            isinstance(value, str) and 0 < len(value) <= 256 for value in (graph, node)):
        raise ValueError("A saved H3 state needs a workflow and node identity.")
    key = hashlib.sha256(json.dumps([kind, graph, node]).encode()).hexdigest()
    return os.path.join(folder_paths.get_system_user_directory("h3c_state"), key + ".json")


def read(kind, graph, node):
    if kind in ("workflow", "job") and deleted(graph):
        return {"revision": 0, "value": None}
    try:
        with open(path(kind, graph, node), encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return {"revision": 0, "value": None}


def write(kind, graph, node, value, revision=None):
    """Compare and replace under one lock; stale browsers get the current value without changing it. An unreadable
    file is never overwritten: it is kept beside the new one as <name>.<time>.corrupt, and the record says where."""
    with LOCK:
        if kind != "deleted" and deleted(graph):
            raise ValueError("This story was permanently deleted. Start a new project to save new work.")
        target = path(kind, graph, node)
        aside = None
        try:
            current = read(kind, graph, node)
            if not isinstance(current, dict) or type(current.get("revision")) is not int:
                raise ValueError("not an H3 saved state")
        except ValueError:
            aside = f"{target}.{time.strftime('%Y%m%d-%H%M%S')}.corrupt"
            os.replace(target, aside)
            current = {"revision": 0, "value": None}
        if revision is not None and current["revision"] != revision:
            return {**current, "conflict": True}
        os.makedirs(os.path.dirname(target), exist_ok=True)
        record = {"revision": current["revision"] + 1, "value": value}
        descriptor, temporary = tempfile.mkstemp(dir=os.path.dirname(target), suffix=".tmp")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(record, handle, ensure_ascii=False, allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return {**record, "set_aside": aside} if aside else record


def deleted(graph):
    return bool(graph) and os.path.isfile(path("deleted", graph, "library"))
