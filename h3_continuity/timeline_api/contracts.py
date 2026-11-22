"""JSON boundaries and public schemas; native preparation owns technical semantics."""

import copy
import hashlib
import json
import math
from types import SimpleNamespace

from jsonschema import Draft202012Validator

from .. import h3_prompt_schema, timing

API_VERSION = 1


class APIError(ValueError):
    def __init__(self, code, message, *, status=400, path="", details=None):
        super().__init__(message)
        self.code, self.status, self.path = code, status, path
        self.details = copy.deepcopy(details or {})

    def response(self):
        return {"api_version": API_VERSION, "ok": False, "error": {
            "code": self.code, "message": str(self), "path": self.path, "details": copy.deepcopy(self.details)}}


def _json(value):
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is list:
        for item in value:
            _json(item)
        return
    if type(value) is dict and all(type(key) is str for key in value):
        for item in value.values():
            _json(item)
        return
    raise APIError("invalid_request", "Request must contain finite JSON values and string object keys.")


def canonical(value):
    _json(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _object(properties, required=(), *, extra=False):
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": extra}


def _array(item, **limits):
    return {"type": "array", "items": item, **limits}


TEXT = {"type": "string"}
ID = {"type": "string", "minLength": 1, "maxLength": 256}
REVISION = {"type": "integer", "minimum": 1}
SHA = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
SEED = {"type": "integer", "minimum": 0, "maximum": 18446744073709551615}
BOOL = {"type": "boolean"}
FRAME = {"type": "integer", "minimum": 0}
POSITIVE = {"type": "number", "exclusiveMinimum": 0}
NONNEGATIVE = {"type": "number", "minimum": 0}
IMAGE = {"type": "string", "pattern": "^image[1-9][0-9]*$"}
REFMOD_SLOT = {"type": "string", "pattern": "^(image|audio)[1-9][0-9]*$"}
SLOT = {"type": "string", "pattern": "^(image|audio|video|video_audio)[1-9][0-9]*$"}
FILE = _object({"type": {"enum": ["input", "output", "temp"]}, "subfolder": TEXT,
                "filename": {"type": "string", "pattern": r"^[^/\\:]+$"}}, ("type", "filename"), extra=True)


def _semantic_schema():
    # Structural composition uses maintained prompt schemas. Actual reference,
    # subject, duration and mode constraints are resolved by the native compiler.
    slots = SimpleNamespace(references=["image1", "video1"], audios=["audio1", "video_audio1"],
                            tags={"image1": "<Picture 1>", "video1": "<Video 1>"})
    context = SimpleNamespace(mode="Ref2VA", slots=slots, references=["image1"], duration_ms=10**12)
    analysis = h3_prompt_schema.analysis_schema(context)
    prompt = h3_prompt_schema.prompt_schema(context)
    plain = h3_prompt_schema.prompt_schema(SimpleNamespace(mode="T2VA", references=["image1"], duration_ms=10**12))

    def broaden(value):
        if isinstance(value, dict):
            choices = value.get("enum", [])
            if choices and all(isinstance(item, str) and item.startswith(("image", "audio", "video")) for item in choices):
                value.pop("enum"); value["pattern"] = SLOT["pattern"]
            for child in value.values(): broaden(child)
        elif isinstance(value, list):
            for child in value: broaden(child)

    for value in (analysis, prompt, plain): broaden(value)
    analysis["properties"]["picture_anchors"]["maxItems"] = 9
    analysis["properties"]["audio_roles"]["maxItems"] = 6
    analysis["properties"]["video_roles"]["maxItems"] = 3
    for value in (prompt, plain):
        value["properties"]["speakers"]["items"]["properties"]["subject"] = {
            "type": "string", "pattern": r"^(subject_[1-9][0-9]*)?$"}
    use = _object({"target": ID, "detail": h3_prompt_schema.TEXT}, ("target", "detail"))
    for value in (prompt, plain):
        # Saved/public semantic prompts predate the explicit internal cut choice.
        value["properties"]["shots"]["items"]["required"].remove("cut")
        value["properties"]["shots"]["items"]["properties"]["references"] = _array(use, maxItems=32)
    retention = _object({"relationship": {"enum": list(h3_prompt_schema.VISUAL_RELATIONS + h3_prompt_schema.AUDIO_RELATIONS)},
                         "detail": h3_prompt_schema.TEXT}, ("relationship", "detail"))
    prompt["properties"]["retention"] = {"type": "object", "additionalProperties": retention}
    for key in ("soundscape_references", "music_references"):
        prompt["properties"][key] = _array({"type": "string", "pattern": "^(audio|video_audio)[1-9][0-9]*$"}, maxItems=6)
    entry = _object({"version": {"type": "integer", "const": 1}, "references": _array(SLOT, uniqueItems=True),
                     "analysis": analysis, "prompt": {"anyOf": [plain, prompt]}}, ("version", "prompt"))
    return {"type": "object", "additionalProperties": entry}


def _schemas():
    settings = _object({"width": {"type": "integer", "minimum": 32, "maximum": 16384, "multipleOf": 32},
                        "height": {"type": "integer", "minimum": 32, "maximum": 16384, "multipleOf": 32},
                        "context_frames": {"type": "integer", "enum": [int(c) for c in timing.CONTEXT_OPTIONS]},
                        "carry_audio": BOOL, "ref_image_size": {"enum": ["match", "max"]},
                        'audio_context_frames': {'type': 'integer', 'minimum': 0}})
    target = {"oneOf": [
        _object({"kind": {"enum": ["first", "last"]}}, ("kind",)),
        _object({"kind": {"const": "shot"}, "shot": REVISION}, ("kind", "shot"))]}
    stamp = _array(FRAME, minItems=2, maxItems=2)
    pin = _object({"sequence": ID, "box": ID, "take": ID, "created": {}, "layout": {},
                   "latent_stamp": {"anyOf": [stamp, {"type": "null"}]}, "moment": FRAME, "pixel_stamp": stamp},
                  ("sequence", "box", "take", "created", "layout", "latent_stamp", "moment"))
    source = {"anyOf": [pin, {"type": "null"}]}
    candidate = _object({"file": FILE, "request_id": ID, "prompt_id": ID, "batch_index": FRAME,
                         "prompt": TEXT, "seed": SEED, "recipe_sha256": SHA, "source": source}, ("file",), extra=True)
    preview = _object({"shot": REVISION, "target": target, "frame": FRAME, "guide": FILE,
                       "still_source": source, "still_prompt": TEXT, "still_seed": SEED,
                       "images": _array(candidate)}, ("frame",), extra=True)
    preview["oneOf"] = [{"required": ["target"], "not": {"required": ["shot"]}},
                         {"required": ["shot"], "not": {"required": ["target"]}}]
    receipt = _object({"request_id": ID, "prompt_id": ID, "box": ID, "target": target,
                       "state": {"enum": ["submitting", "queued", "running", "complete", "failed", "cancelled", "unknown"]},
                       "provenance": {"type": "object"}, "images": _array(candidate), "error": {}},
                      ("request_id", "prompt_id", "box", "target", "state", "provenance"), extra=True)
    change = _object({"slot": IMAGE, "frame": FRAME, "revision": TEXT}, ("slot", "frame", "revision"), extra=True)
    moment = _object({"box": ID, "frame": FRAME, "label": TEXT}, ("box", "frame"), extra=True)
    endpoint = {"anyOf": [IMAGE, {"const": ""}]}
    # A clip's other videos: up to three more H3 generations of its time. Native parsing checks the swaps.
    layer = _object({"id": ID, "seed": SEED, "prompt": TEXT, "first": endpoint, "last": endpoint,
                     "previews": _array(preview), "memory": {"enum": ["off", "scene", "selected", "cast"]},
                     "memories": _array(moment, maxItems=3), "dialogue": {"enum": ["cues", "manual"]}}, ("id",))
    switch = _object({"cuts": _array(_object({"at": FRAME, "to": ID}, ("at", "to")), minItems=1),
                      "fade": {"type": "integer", "minimum": 0, "maximum": 12}, "sound": ID,
                      "align": {"type": "object"}}, ("cuts", "fade", "sound"))
    box = _object({"track": ID, "start": FRAME, "id": ID, "frames": POSITIVE, "seconds": POSITIVE, "seed": SEED, "prompt": TEXT,
                   "cut": BOOL, "new_scene": BOOL, "exact": BOOL, "first": {"anyOf": [IMAGE, {"const": ""}]},
                   "last": {"anyOf": [IMAGE, {"const": ""}]}, "previews": _array(preview),
                   "plate_changes": _array(change), "memory": {"enum": ["off", "scene", "selected", "cast"]},
                   "memories": _array(moment, maxItems=3), "schedule": {}, "source": {}, "cast": {"type": "object"},
                   "dialogue": {"enum": ["cues", "manual"]}, "layers": _array(layer, maxItems=3), "switch": switch},
                  extra=True)
    box["anyOf"] = [{"required": ["frames"]}, {"required": ["seconds"]}]
    insertion = _object({"before": ID, "mode": {"const": "insert"}, "frames": {"type": "integer", "enum": [12, 29, 46]},
                         "seed": SEED, "prompt": TEXT}, ("before", "frames"), extra=True)
    # Native preparation checks that left + right is 12, 29 or 46.
    coverage = {"type": "integer", "minimum": 0, "maximum": 46}
    replacing = _object({"before": ID, "mode": {"const": "replace"}, "left": coverage, "right": coverage,
                         "seed": SEED, "prompt": TEXT, "review": TEXT, "selected": TEXT},
                        ("before", "mode", "left", "right"), extra=True)
    replacing["not"] = {"required": ["frames"]}
    bridge = {"oneOf": [insertion, replacing]}
    audio_window = _object({'offset': NONNEGATIVE, 'source_start': NONNEGATIVE, 'duration': POSITIVE},
                           ('offset', 'source_start', 'duration'))
    box_windows = _object({'version': {'const': 1, 'type': 'integer'}, 'source': {'type': 'object'},
                           'placement': _object({'start': NONNEGATIVE, 'source_start': NONNEGATIVE, 'duration': POSITIVE},
                                                ('start', 'source_start', 'duration')),
                           'by_box': {'type': 'object', 'additionalProperties': audio_window}},
                          ('version', 'source', 'placement', 'by_box'))
    audio = _object({"track": ID, "slot": {"enum": ["audio1", "audio2", "audio3"]}, "file": FILE, "start": NONNEGATIVE,
                     "source_start": NONNEGATIVE, "duration": POSITIVE, "source_duration": POSITIVE, "description": TEXT,
                     "layer": {"enum": ["music", "soundscape", "shot"]}, "in_full_video": BOOL, "locked": BOOL,
                     'box_windows': box_windows},
                    ("slot", "start", "source_start", "duration"), extra=True)
    line = _object({"version": {"type": "integer", "const": 1}, "prompt": TEXT, "boxes": _array(box, minItems=1),
                    "requires": _array({"type": "string", "minLength": 1}, uniqueItems=True),
                    "tracks": _array(_object({"id": ID, "type": {"enum": ["video", "audio", "text"]}, "name": TEXT}, ("id", "type", "name"))),
                    "text_lanes": _array(_object({"track": ID, "attachment": {"type": "object"}}, ("track", "attachment"))),
                    "overlap_switches": _array(_object({"id": ID, "from": ID, "to": ID, "at": FRAME,
                        "fade": {"type": "integer", "minimum": 0, "maximum": 12}, "sound": ID},
                        ("id", "from", "to", "at", "fade", "sound"))),
                    "dialogue": {"type": ["object", "null"]},
                    "bridges": _array(bridge), "still_requests": _array(receipt), "audio_clips": _array(audio, maxItems=3),
                    "pictures": _array(_object({"slot": IMAGE, "file": FILE, "title": TEXT}, ("slot",), extra=True)),
                    "voice_clips": _array(_object({"slot": REFMOD_SLOT, "file": FILE}, ("slot",), extra=True)),
                    "plates": _array(_object({"id": ID, "slot": IMAGE, "image": FILE}, ("id", "slot"), extra=True)),
                    "refmods": _array(_object({"slot": REFMOD_SLOT, "name": ID, "kind": {"enum": ["image", "video", "audio"]},
                                               "member": {"type": "integer", "minimum": -1},
                                               "strength": {"type": "number", "minimum": 0, "maximum": 1}, "description": TEXT},
                                              ("slot", "name", "kind"), extra=True)),
                    "reference_descriptions": {"type": "object"}, "disabled_refs": _array(SLOT),
                    "reference_replacements": {"type": "object", "propertyNames": SLOT, "additionalProperties": {
                        "oneOf": [_object({"source": SLOT}, ("source",)), _object({"file": FILE}, ("file",))]}},
                    "timed_text": {"type": ["object", "null"]}, "bible": {},
                    "context_noise": BOOL, "continuation_guide": BOOL,
                    "audio_feather": {"type": "integer", "minimum": 0, "maximum": 16},
                    "video_slices": _array({"type": "string", "pattern": "^video[1-9][0-9]*$"}, uniqueItems=True)},
                   ("boxes",), extra=True)
    line["not"] = {"anyOf": [{"required": ["render_box"]}, {"required": ["render_bridge"]},
                              {"required": ["render_layer"]}, {"required": ["rebuild_continuity"]}]}
    binding = {"oneOf": [
        _object({"kind": {"const": "reference_replacement"}, "slot": SLOT}, ("kind", "slot")),
        _object({"kind": {"const": "picture"}, "slot": IMAGE,
                 "title": TEXT}, ("kind", "slot")),
        _object({"kind": {"const": "audio_clip"}, "slot": {"enum": ["audio1", "audio2", "audio3"]}}, ("kind", "slot")),
        _object({"kind": {"const": "voice_clip"}, "slot": {"type":"string","pattern":r"^audio([4-9]|[1-9][0-9]+)$"}}, ("kind", "slot")),
        _object({"kind": {"const": "plate"}, "id": ID, "visible_text": {}, "text_contract": {}}, ("kind", "id")),
        _object({"kind": {"const": "guide"}, "box": ID, "shot": REVISION, "visible_text": {}, "text_contract": {}}, ("kind", "box", "shot")),
        _object({"kind": {"const": "guide"}, "box": ID, "target": target, "visible_text": {}, "text_contract": {}}, ("kind", "box", "target")),
        _object({"kind": {"const": "candidate"}, "request_id": ID, "prompt_id": ID, "batch_index": FRAME},
                ("kind", "request_id", "prompt_id", "batch_index")),
        _object({"kind": {"const": "whisper"}, "source_sha256": SHA}, ("kind", "source_sha256"))]}
    assets = _array(_object({"asset_id": {"type": "string", "pattern": "^asset_[a-f0-9]{64}$"},
                             "bindings": _array(binding, minItems=1)}, ("asset_id", "bindings")))
    semantic = _semantic_schema()
    creative = {"name": {"type": "string", "minLength": 1, "maxLength": 1024}, "settings": settings,
                "timeline": line, "assets": assets, "consumer": {"type": "object"}, "semantic_boxes": semantic}
    selection = {"oneOf": [
        _object({"kind": {"const": "all"}}, ("kind",)),
        _object({"kind": {"const": "boxes"}, "ids": _array(ID, minItems=1, uniqueItems=True), "rerender": BOOL,
                 "rebuild_continuity": _object({"box": ID, "fingerprint": SHA}, ("box", "fingerprint"))}, ("kind", "ids"))]}
    version = {"api_version": {"type": "integer", "const": 1}}
    responses = {
        "asset": _object({**version, "id": ID, "sha256": SHA, "kind": TEXT, "kinds": _array(TEXT), "size": FRAME,
                           "download_url": TEXT}, ("api_version", "id", "sha256"), extra=True),
        "artifact": _object({**version, "id": ID, "sha256": SHA, "kind": TEXT, "frames": FRAME, "fps": {"type": "number", "minimum": 1, "maximum": 240},
                              "project_id": ID, "revision": REVISION, "download_url": TEXT},
                             ("api_version", "id", "sha256", "kind", "download_url"), extra=True),
        "project": _object({**version, "id": ID, "revision": REVISION, "name": TEXT, "profile": ID,
                             "profile_sha256": SHA, "sequence": ID, "timeline": line, "settings": settings,
                             "assets": assets, "consumer": {"type": "object"}, "active_job": {"type": ["string", "null"]}},
                            ("api_version", "id", "revision", "timeline", "profile_sha256"), extra=True),
        "plan": _object({**version, "project_id": ID, "revision": REVISION, "plan_sha256": SHA,
                          "selection": selection, "units": _array({"type": "object"})},
                         ("api_version", "project_id", "revision", "plan_sha256", "units"), extra=True),
        "job": _object({**version, "id": ID, "project_id": ID, "revision": REVISION, "plan_sha256": SHA,
                         "state": {"enum": ["accepted", "queued", "running", "needs_reconciliation", "succeeded", "failed"]},
                         "progress": _object({"completed": FRAME, "total": FRAME}, ("completed", "total"), extra=True),
                         "attempts": _array({"type": "object"}), "artifacts": _array({"type": "object"}),
                         "blocked_by": {"type": ["object", "null"]}},
                        ("api_version", "id", "project_id", "revision", "state"), extra=True),
        "capabilities": _object({**version, "schemas": {"type": "object"}, "profiles": _array({"type": "object"}),
                                  "limits": {"type": "object"}, "operations": _array(TEXT)},
                                 ("api_version", "schemas", "profiles", "limits", "operations"), extra=True),
        "error": _object({**version, "ok": {"const": False}, "error": _object({"code": ID, "message": TEXT,
                            "path": TEXT, "details": {"type": "object"}}, ("code", "message", "path", "details"))},
                          ("api_version", "ok", "error"))}
    result = {**responses, "timeline": line, "semantic_boxes": semantic, "binding": binding,
              "project_create": _object({**creative, "profile": ID}, ("name", "profile", "timeline")),
              "project_update": _object({**creative, "expected_revision": REVISION}, ("expected_revision", "timeline")),
              "selection": selection,
              "plan_create": _object({"expected_revision": REVISION, "selection": selection}, ("expected_revision", "selection")),
              "job_create": _object({"expected_revision": REVISION, "selection": selection, "plan_sha256": SHA},
                                    ("expected_revision", "selection", "plan_sha256")),
              "job_abandon": _object({"reason": {"type": "string", "minLength": 1, "maxLength": 2000},
                                      "confirm_prompt_id": {"type": ["string", "null"], "maxLength": 256}},
                                     ("reason", "confirm_prompt_id")),
              "take_use": _object({"expected_revision": REVISION, "kind": {"enum": ["box", "bridge"]},
                                   "box": ID, "take_id": ID}, ("expected_revision", "kind", "box", "take_id"))}
    for value in result.values(): value["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    return result


_SCHEMAS = _schemas()
_VALIDATORS = {key: Draft202012Validator(value) for key, value in _SCHEMAS.items()}


def schemas():
    return copy.deepcopy(_SCHEMAS)


def validate(kind, value):
    canonical(value)
    if kind not in _VALIDATORS:
        raise APIError("invalid_request", "Unknown contract type.")
    error = next(_VALIDATORS[kind].iter_errors(value), None)
    if error is not None:
        pointer = "/" + "/".join(str(item).replace("~", "~0").replace("/", "~1") for item in error.absolute_path)
        # Avoid echoing arbitrary request values (which may include host paths).
        raise APIError("invalid_request", "Value does not satisfy " + error.validator + " constraint.",
                       path=pointer if pointer != "/" else "", details={"constraint": error.validator})
    return copy.deepcopy(value)

# static-configuration-interop-v1

# captured-api-delivery-v2
