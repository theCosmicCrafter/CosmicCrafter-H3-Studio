"""Saved takes of a sequence's boxes and bridges: which one can be used, putting one in place, following the seeds
the Timeline names and deleting them. A take can be used only where it joins both of its neighbours as they are."""

import copy
import datetime
import json
import os
import shutil
import sys

from safetensors import SafetensorError, safe_open

from . import bridges, layers, replacement, store, timeline_node
from . import nodes as continuity
from .timing import tokens_for_frames

TOLERANCE = 1e-3
BUSY = "Wait until this sequence's runs finish."
REQUEST = "H3 Timeline: the takes request must be a JSON object"
SEQUENCE_NODES = ("H3C_Timeline", "H3C_Sequence")
WHY = {"files": "its files are missing", "sources": "the box changed after this take",
       "layout": "the box changed after this take", "settings": "the node's settings changed",
       "remembered": "a box it remembers has another take"}
ERRORS = (AttributeError, KeyError, OverflowError, TypeError, ValueError, OSError)


def _queue():
    """ComfyUI's running and waiting prompts; none outside a running ComfyUI. Its server module is looked up, not
    imported: importing it elsewhere loads all of ComfyUI."""
    instance = getattr(getattr(sys.modules.get("server"), "PromptServer", None), "instance", None)
    if instance is None:
        return [], []
    return instance.prompt_queue.get_current_queue_volatile()


def busy(folder):
    """Whether a running or waiting prompt may render into sequence `folder`: it has an H3 Timeline or H3 Sequence
    node named for the folder, or whose name is linked."""
    running, waiting = _queue()
    for item in [*running, *waiting]:
        for node in item[2].values():
            if not isinstance(node, dict) or node.get("class_type") not in SEQUENCE_NODES:
                continue
            name = (node.get("inputs") or {}).get("name")
            if not isinstance(name, str):
                return True
            try:
                if os.path.normcase(store.sequence_dir(continuity.sequences_root(), name)) == os.path.normcase(folder):
                    return True
            except ValueError:
                continue
    return False


def read_entry(path):
    """The entry saved in latent file `path`'s metadata, or None when it can't be read."""
    try:
        with safe_open(path, framework="pt") as f:
            entry = json.loads((f.metadata() or {})["h3c"])
    except (OSError, KeyError, ValueError, SafetensorError):
        return None
    return entry if isinstance(entry, dict) else None


def saved_takes(folder):
    """The folders under takes/, newest first: {"folder": "takes/<name>", "entry": its saved entry or None,
    "bytes": the size of its files}. Takes saved in the same second come in reverse order of their folders' names,
    which end in a count when they share a second."""
    root = os.path.join(folder, "takes")
    found = []
    for name in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        path = os.path.join(root, name)
        if not os.path.isdir(path):
            continue
        files = [os.path.join(path, item) for item in os.listdir(path)]
        latents = [item for item in files if item.endswith(".safetensors")]
        found.append({"folder": f"takes/{name}", "entry": read_entry(latents[0]) if len(latents) == 1 else None,
                      "bytes": sum(os.path.getsize(item) for item in files if os.path.isfile(item))})
    return sorted(found, key=lambda take: (str((take["entry"] or {}).get("created") or ""), take["folder"]), reverse=True)


def _target(entry):
    """("box", id), ("bridge", id) or ("layer", id): what saved `entry` was rendered for; (None, None) when it doesn't
    say."""
    record = (entry or {}).get("timeline") or {}
    if "bridge" in record:
        return "bridge", record["bridge"]
    if "layer" in record:
        return "layer", record["layer"]
    if "index" in (entry or {}) and "box" in record:
        return "box", record["box"]
    return None, None


def _seed(take):
    return ((take["entry"] or {}).get("timeline") or {}).get("seed")


def _files(directory, entry):
    video = (entry or {}).get("video")
    return (bool(video) and os.path.isfile(os.path.join(directory, video["file"]))
            and store.has_segment_latents(directory, entry))


class _Sequence:
    """One request's Timeline, sequence folder, saved boxes and saved takes."""

    def __init__(self, body):
        if not isinstance(body, dict):
            raise ValueError(REQUEST)
        self.parsed, self.folder, self.known, self.context = timeline_node.read_request(body)
        self.name = os.path.basename(self.folder)
        self.bridge_known = bridges.settings(self.known.get("width"), self.known.get("height"), self.context,
                                             self.known.get("carry_audio"), audio_context_frames=self.known.get('audio_context_frames', 0))
        self.reload()

    def reload(self):
        self.manifest = store.load_manifest(self.folder)
        store.align(self.manifest, [item.id for item in self.parsed.boxes])
        self.entries = {entry["index"]: entry for entry in self.manifest["segments"]}
        self.is_done, _ = timeline_node.status_test(self.parsed, self.folder, self.entries, self.known, self.context)
        self.saved = saved_takes(self.folder)

    def index(self, box_id):
        found = next((number for number, item in enumerate(self.parsed.boxes) if item.id == box_id), None)
        if found is None:
            raise ValueError(f"H3 Timeline: there is no box {box_id!r}")
        return found

    def bridge(self, box_id):
        """The Timeline's bridge before box `box_id`, or None."""
        return next((item for item in self.parsed.bridges if item["before"] == box_id), None)

    def done(self, index):
        entry = self.entries.get(index + 1)
        return entry is not None and self.is_done(index, entry)

    def in_use(self, kind, box_id):
        """The saved entry in place for box `box_id`, or for the bridge before it; None when there is none."""
        if kind == "bridge":
            return bridges.saved(self.manifest, box_id)
        entry = self.entries.get(self.index(box_id) + 1)
        return entry if entry and (entry.get("timeline") or {}).get("box") == box_id else None

    def takes_of(self, kind, box_id):
        return [take for take in self.saved if _target(take["entry"]) == (kind, box_id)]

    def why(self, take):
        """Why `take` can't be used for the box or bridge it was rendered for, or ""."""
        kind, box_id = _target(take["entry"])
        if kind is None:
            return "its files are missing"
        if kind == "layer":
            return layer_fit(self, box_id, take)
        index = next((number for number, item in enumerate(self.parsed.boxes) if item.id == box_id), None)
        if index is None:
            return "its box isn't in the Timeline"
        if kind == "box":
            return box_fit(self, index, take)
        bridge = self.bridge(box_id)
        return bridge_fit(self, bridge, take) if bridge else f"box {index + 1} has no bridge before it"


def box_fit(sequence, index, take):
    """Why `take` can't be box `index` as the Timeline and the saved boxes are now, from the first rule it fails, or ""."""
    entry, directory = take["entry"], os.path.join(sequence.folder, take["folder"])
    if not _files(directory, entry):
        return "its files are missing"
    seed = _seed(take)
    if seed is None:
        return "seed not recorded"
    if entry["index"] != index + 1:
        return f"it was rendered as box {entry['index']}"
    variant = copy.deepcopy(sequence.parsed)
    variant.boxes[index].seed = seed
    problem = timeline_node.box_problem(variant, index, entry, sequence.folder, sequence.entries, sequence.known,
                                        sequence.context, sequence.is_done, files=directory)
    if problem:
        kind, sentence = problem
        return WHY.get(kind) or sentence[:1].lower() + sentence[1:].removesuffix(".")
    return joins(sequence, index, directory, entry)


def joins(sequence, index, directory, entry):
    """"" when box `index`'s take in `directory` joins the saved boxes beside it, else which one changed. A take that
    carried frames must start as the box before ends, and the box after, when it carried frames, must start as the
    take ends, within TOLERANCE."""
    carried = entry.get("context_frames") or 0
    if carried > 0:
        before, tokens = sequence.entries.get(index), tokens_for_frames(carried)
        if (before is None or not store.has_segment_latents(sequence.folder, before)
                or not (_same(_window(directory, entry, tokens, True), _window(sequence.folder, before, tokens, False))
                        or _parent(entry, before))):
            return "the box before changed"
    after = sequence.entries.get(index + 2)
    following = (after or {}).get("context_frames") or 0
    if following > 0 and store.has_segment_latents(sequence.folder, after):
        tokens = tokens_for_frames(following)
        if not (_same(_window(directory, entry, tokens, False), _window(sequence.folder, after, tokens, True))
                or _parent(after, entry)):
            return "the box after changed"
    return ""


def _parent(child, parent):
    """Whether `child` recorded `parent` as the render it continued from. Context noise changes the carried frames,
    so such a child's latents never match its parent's end exactly."""
    return bool(child.get("carried_from")) and child["carried_from"] == parent.get("created")


def _window(folder, entry, tokens, first):
    """The first or last `tokens` video latent frames of saved `entry`."""
    start = 0 if first else max(0, store.video_tokens(folder, entry) - tokens)
    return store.load_video_window(folder, entry, start, tokens)


def _same(one, other):
    return one.shape == other.shape and (one.float() - other.float()).abs().max().item() <= TOLERANCE


def bridge_fit(sequence, bridge, take):
    """Why `take` can't be the Timeline's `bridge` as the saved boxes are now, from the first rule it fails, or ""."""
    entry, directory = take["entry"], os.path.join(sequence.folder, take["folder"])
    if not _files(directory, entry):
        return "its files are missing"
    seed = _seed(take)
    if seed is None:
        return "seed not recorded"
    variant = copy.deepcopy(sequence.parsed)
    chosen = next(item for item in variant.bridges if item["before"] == bridge["before"])
    chosen["seed"] = seed
    trouble = bridges.problem(variant, chosen)
    if trouble:
        return trouble
    index = bridges.position(variant, chosen)
    waiting = [number for number in (index, index + 1) if not sequence.done(number - 1)]
    if waiting:
        return f"render {' and '.join(f'box {number}' for number in waiting)} first"
    return bridges.reason(sequence.folder, entry, bridges.key(variant, chosen, sequence.bridge_known),
                          sequence.entries[index], sequence.entries[index + 1], files=directory)


def layer_fit(sequence, layer_id, take):
    """Why `take` can't be video `layer_id` as the Timeline is now, from the first rule it fails, or ""."""
    entry, directory = take["entry"], os.path.join(sequence.folder, take["folder"])
    if not _files(directory, entry):
        return "its files are missing"
    seed = _seed(take)
    if seed is None:
        return "seed not recorded"
    clip_id = (entry.get("timeline") or {}).get("box")
    index = next((number for number, item in enumerate(sequence.parsed.boxes) if item.id == clip_id), None)
    if index is None:
        return "its clip isn't in the Timeline"
    found = layers.layer_of(sequence.parsed, layer_id)
    if found is None or found[0] != index:
        return "its video isn't in the clip"
    why = layers.reason(directory, sequence.parsed, index, {**found[1], "seed": seed}, entry, sequence.known,
                        sequence.context)
    return why[:1].lower() + why[1:].removesuffix(".")


def warnings(sequence, index):
    """What putting another take in place for box `index` leaves to render again: the later boxes that remember a
    frame of it, then the rendered bridges on either side of it."""
    box_id = sequence.parsed.boxes[index].id
    numbers = [later + 1 for later in range(index + 1, len(sequence.parsed.boxes))
               if sequence.done(later) and any(item.get("box") == box_id for item in
                                               (sequence.entries[later + 1].get("timeline") or {}).get("memories", []))]
    found = []
    if len(numbers) == 1:
        found.append(f"Box {numbers[0]} remembers a frame of box {index + 1} and will need a new render.")
    elif numbers:
        listed = ", ".join(map(str, numbers[:-1])) + f" and {numbers[-1]}"
        found.append(f"Boxes {listed} remember a frame of box {index + 1} and will need a new render.")
    done = {number for number in range(len(sequence.parsed.boxes)) if sequence.done(number)}
    for state in bridges.states(sequence.folder, sequence.parsed, sequence.manifest, done, sequence.bridge_known):
        if state.status == "done" and state.index in (index, index + 1):
            found.append(f"The bridge before box {state.index + 1} will need a new render.")
    for bridge in sequence.parsed.replacements:
        at = replacement.position(sequence.parsed, bridge)
        if at in (index, index + 1) and (bridge.get("review") or bridge.get("selected")):
            found.append(f"The replacement before box {at + 1} reads this box's footage: confirm its region "
                         "again and select a new candidate; until then the full video plays the original cut.")
    return found


MARKS = "takes_marks.json"


def marks(folder):
    """{created: {"rating", "tag"}} for the renders of the sequence in `folder`; {} when none or unreadable."""
    try:
        with open(os.path.join(folder, MARKS), encoding="utf-8") as handle:
            found = json.load(handle).get("takes")
    except (OSError, ValueError, AttributeError):
        return {}
    return found if isinstance(found, dict) else {}


def mark(folder, created, rating, tag):
    """Saves a render's rating (1-5, or 0) and short tag, keyed by when it was rendered; no rating and no tag clears
    the mark."""
    if not isinstance(created, str) or not created:
        raise ValueError("H3 Timeline: a take mark needs the render's time")
    if type(rating) is not int or not 0 <= rating <= 5:
        raise ValueError("H3 Timeline: a take rating is a whole number from 0 to 5")
    if not isinstance(tag, str) or len(tag) > 40:
        raise ValueError("H3 Timeline: a take tag is text of at most 40 characters")
    found = marks(folder)
    if rating or tag.strip():
        found[created] = {"rating": rating, "tag": tag.strip()}
    else:
        found.pop(created, None)
    path = os.path.join(folder, MARKS)
    with open(path + ".tmp", "w", encoding="utf-8") as handle:
        json.dump({"version": 1, "takes": found}, handle, ensure_ascii=False, indent=1)
    os.replace(path + ".tmp", path)


def _marked(created, found):
    record = found.get(created) or {}
    return {"rating": record.get("rating", 0), "tag": record.get("tag", "")}


def _in_use(entry, found):
    if entry is None:
        return None
    return {"created": entry.get("created"), "seed": (entry.get("timeline") or {}).get("seed"),
            "carried_from": entry.get("carried_from"), **_marked(entry.get("created"), found)}


def _listed(sequence, take, why, found):
    entry = take["entry"]
    created, video = entry.get("created"), entry.get("video")
    return {"folder": take["folder"], "created": created, "seed": _seed(take), "usable": not why, "why": why,
            "bytes": take["bytes"], "carried_from": entry.get("carried_from"), **_marked(created, found),
            "video": None if not video else {"filename": video["file"], "type": "output", "v": created,
                                             "subfolder": f"h3_sequences/{sequence.name}/{take['folder']}"}}


def listing(body):
    """{"ok", "busy", "box", "bridge"}: the take in use and the saved takes of box `body["box"]` with the warnings,
    then the same for the bridge before it, or None when it has none."""
    with continuity.SEQUENCE_LOCK:
        try:
            sequence = _Sequence(body)
            box_id = body.get("box")
            index = sequence.index(box_id)
            bridge = sequence.bridge(box_id)
            noted = marks(sequence.folder)
            before = sequence.in_use("box", sequence.parsed.boxes[index - 1].id) if index else None
            found = {"ok": True, "busy": busy(sequence.folder),
                     "box": {"in_use": _in_use(sequence.in_use("box", box_id), noted),
                             "takes": [_listed(sequence, take, box_fit(sequence, index, take), noted)
                                       for take in sequence.takes_of("box", box_id)],
                             "warnings": warnings(sequence, index),
                             "before": {"created": before.get("created")} if before else None},
                     "bridge": None}
            if bridge is not None:
                found["bridge"] = {"in_use": _in_use(sequence.in_use("bridge", box_id), noted),
                                   "takes": [_listed(sequence, take, bridge_fit(sequence, bridge, take), noted)
                                             for take in sequence.takes_of("bridge", box_id)]}
            return found
        except ERRORS as error:
            return {"ok": False, "error": str(error)}


def rate(body):
    """{"ok"} after saving body["rating"] and body["tag"] for the render made at body["created"] in the posted
    Timeline's sequence."""
    with continuity.SEQUENCE_LOCK:
        try:
            sequence = _Sequence(body)
            mark(sequence.folder, body.get("created"), body.get("rating"), body.get("tag", ""))
            return {"ok": True}
        except ERRORS as error:
            return {"ok": False, "error": str(error)}


def _seed_wanted(sequence, kind, box_id):
    """The seed the posted Timeline gives box `box_id`, or the bridge before it."""
    if kind == "box":
        return sequence.parsed.boxes[sequence.index(box_id)].seed
    bridge = sequence.bridge(box_id)
    return bridge["seed"] if bridge else None


def use(body, *, managed_owner=None):
    """Puts saved take `body["take"]` in place for box `body["box"]`, or for the bridge before it with
    `"bridge": true`, once the posted Timeline gives it the take's seed: {"ok": True} or {"ok": False, "error"}. A
    take already in place with the posted `created` and seed answers ok, so a request sent twice moves nothing."""
    with continuity.SEQUENCE_LOCK:
        try:
            from .timeline_api.service import authorize_sequence
            authorize_sequence(body.get("name"), managed_owner, "take_use")
            sequence = _Sequence(body)
            if busy(sequence.folder):
                return {"ok": False, "error": BUSY}
            kind, box_id = "bridge" if body.get("bridge") is True else "box", body.get("box")
            wanted = _seed_wanted(sequence, kind, box_id)
            take = next((item for item in sequence.saved if item["folder"] == body.get("take")), None)
            if take is None:
                current = _in_use(sequence.in_use(kind, box_id), {}) or {}
                if current.get("created") is not None and (current["created"], current["seed"]) == (body.get("created"),
                                                                                               wanted):
                    return {"ok": True}
                return {"ok": False, "error": "This take is no longer saved."}
            if _target(take["entry"]) != (kind, box_id):
                return {"ok": False, "error": "This take belongs to another box."}
            why = sequence.why(take)
            if why:
                return {"ok": False, "error": f"This take can't be used: {why}."}
            if _seed(take) != wanted:
                return {"ok": False, "error": "Send the Timeline with this take's seed."}
            _put_back(sequence, kind, box_id, take)
            return {"ok": True}
        except ERRORS as error:
            return {"ok": False, "error": str(error)}


def _put_back(sequence, kind, box_id, take):
    """Moves `take` into place for the box or bridge, and what was in place to a new folder under takes/, then
    writes the manifest; when it can't be written, the files go back where they were."""
    entry, now = take["entry"], datetime.datetime.now()
    manifest, current = sequence.manifest, None
    if kind == "box":
        index = sequence.index(box_id) + 1
        current = sequence.in_use("box", box_id)
        if any(item["stem"] == entry["stem"] and item is not current for item in manifest["segments"]):
            raise ValueError("H3 Timeline: another box's take uses this take's file names now; regenerate the box "
                             "instead")
        entry = take["entry"] = {**entry, "index": index}
    earlier = None
    if current is not None and current["stem"] != entry["stem"]:
        # The box's take in place has other file names (the box moved since this take): it goes to takes/ first.
        earlier = store.move_take(sequence.folder, current["stem"], now)
    try:
        archived, moves = store.put_back_take(sequence.folder, entry["stem"], take["folder"], now)
    except Exception:
        if earlier:
            store.put_back_take(sequence.folder, current["stem"], earlier, now)
        raise
    try:
        store.write_manifest(sequence.folder, _manifest_with(manifest, kind, box_id, take, archived or earlier, now))
    except Exception:
        store.undo_moves(sequence.folder, moves, archived)
        if earlier:
            store.put_back_take(sequence.folder, current["stem"], earlier, now)
        raise
    sequence.reload()


def _manifest_with(manifest, kind, box_id, take, archived, now):
    """A copy of `manifest` with `take` in place for the box or bridge, what was in place listed under takes as
    `archived` (when anything was), and no full video."""
    entry, manifest = take["entry"], copy.deepcopy(manifest)
    manifest["takes"] = [item for item in manifest.get("takes", []) if item.get("folder") != take["folder"]]
    if archived:
        manifest["takes"].append({**({"bridge": box_id} if kind == "bridge" else {"index": entry["index"]}),
                                  "archived": now.isoformat(timespec="seconds"), "folder": archived})
    if kind == "bridge":
        listed = manifest.setdefault("bridges", [])
        spot = next((number for number, item in enumerate(listed) if item.get("box") == box_id), None)
        if spot is None:
            listed.append(entry)
        else:
            listed[spot] = entry
    else:
        manifest["segments"] = sorted([item for item in manifest["segments"]
                                       if item["index"] != entry["index"] and store.box_of(item) != box_id]
                                      + [entry], key=lambda item: item["index"])
    manifest.pop("full_video", None)
    return manifest


def _put_back_or_skip(sequence, kind, box_id, take):
    try:
        _put_back(sequence, kind, box_id, take)
    except OSError:
        return False
    return True


def follow(body):
    """Where what is in place isn't done, puts back the newest saved take that has the seed the posted Timeline names
    and can be used: box by box in order, then bridge by bridge. Nothing while the sequence renders. Returns what it
    put back, as [{"box" or "bridge": id, "created"}]."""
    with continuity.SEQUENCE_LOCK:
        from .timeline_api.service import authorize_sequence
        authorize_sequence(body.get("name"), None, "take_follow")
        sequence = _Sequence(body)
        if not sequence.saved or busy(sequence.folder):
            return []
        followed = []
        for index, item in enumerate(sequence.parsed.boxes):
            if sequence.done(index):
                continue
            take = next((take for take in sequence.takes_of("box", item.id)
                         if _seed(take) == item.seed and not box_fit(sequence, index, take)), None)
            if take is not None and _put_back_or_skip(sequence, "box", item.id, take):
                followed.append({"box": item.id, "created": take["entry"].get("created")})
        done = {number for number in range(len(sequence.parsed.boxes)) if sequence.done(number)}
        for state in bridges.states(sequence.folder, sequence.parsed, sequence.manifest, done, sequence.bridge_known):
            if state.status not in ("pending", "next"):
                continue
            box_id = state.bridge["before"]
            take = next((take for take in sequence.takes_of("bridge", box_id)
                         if _seed(take) == state.bridge["seed"] and not bridge_fit(sequence, state.bridge, take)), None)
            if take is not None and _put_back_or_skip(sequence, "bridge", box_id, take):
                followed.append({"bridge": box_id, "created": take["entry"].get("created")})
        return followed


def _chosen(sequence, body):
    """The saved takes `body["scope"]` names: "take", the listed folder `body["take"]`; "other", every take of box
    `body["box"]`, or of the bridge before it with `"bridge": true`; "unusable", every take that can't be used."""
    scope = body.get("scope")
    if scope == "take":
        return [take for take in sequence.saved if take["folder"] == body.get("take")]
    if scope == "other":
        return sequence.takes_of("bridge" if body.get("bridge") is True else "box", body.get("box"))
    if scope == "unusable":
        return [take for take in sequence.saved if sequence.why(take)]
    raise ValueError(f"H3 Timeline: there is no takes scope {scope!r}")


def delete(body):
    """{"ok": True, "count", "bytes"} for the takes `body["scope"]` names (see `_chosen`), removed only with
    `"apply": true`. Every folder must sit directly in takes/ before any is removed, and the manifest keeps the
    entries of folders that couldn't be removed."""
    with continuity.SEQUENCE_LOCK:
        try:
            from .timeline_api.service import authorize_sequence
            authorize_sequence(body.get("name"), None, "take_delete")
            sequence = _Sequence(body)
            if busy(sequence.folder):
                return {"ok": False, "error": BUSY}
            chosen = _chosen(sequence, body)
            if body.get("apply") is True and chosen:
                _remove(sequence, chosen)
            return {"ok": True, "count": len(chosen), "bytes": sum(take["bytes"] for take in chosen)}
        except ERRORS as error:
            return {"ok": False, "error": str(error)}


def _remove(sequence, chosen):
    root = os.path.normcase(os.path.realpath(os.path.join(sequence.folder, "takes")))
    paths = [os.path.realpath(os.path.join(sequence.folder, take["folder"])) for take in chosen]
    if any(os.path.normcase(os.path.dirname(path)) != root for path in paths):
        raise ValueError("H3 Timeline: a take to delete is outside takes/")
    removed = []
    try:
        for take, path in zip(chosen, paths):
            shutil.rmtree(path)
            removed.append(take["folder"])
    finally:
        if removed:
            manifest = store.load_manifest(sequence.folder)
            manifest["takes"] = [item for item in manifest.get("takes", []) if item.get("folder") not in removed]
            store.write_manifest(sequence.folder, manifest)
            sequence.reload()


def status(body):
    """The Timeline status for the editor. With `"follow": true` in the body, it follows the Timeline's seeds first
    and lists what it put back as `followed`."""
    followed = []
    if isinstance(body, dict) and body.get("follow") is True:
        try:
            followed = follow(body)
        except ERRORS:
            followed = []
    found = timeline_node.request_status(body)
    if followed and found.get("ok"):
        found["followed"] = followed
    return found
