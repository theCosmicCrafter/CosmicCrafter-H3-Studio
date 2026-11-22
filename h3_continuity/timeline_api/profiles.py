"""Pinned host-configured render graphs and flat editable workflow exports."""

import copy
import json
import os
import re
import uuid
from pathlib import Path

from .. import timeline_prepare
from .contracts import APIError, canonical, digest


# Production size: a configured workflow at another aspect ratio.
"""A saved configured workflow at another aspect ratio, keeping its saved pixel count.

Pure arithmetic over a native profile's API graph; no ComfyUI or H3 imports.
Only width and height change: the first pass takes the requested size, the second pass follows its
aspect at its own saved pixel count, and every other technical value stays as saved.
"""

import copy as production_copy
import math as production_math

# Both passes may differ from their saved pixel counts by at most 5%.
PRODUCTION_SIZE_TOLERANCE = 0.05
# H3 Timeline and the configuration node's size widgets use multiples of 32.
PRODUCTION_SIZE_MULTIPLE = 32
PRODUCTION_SIZE_LIMITS = (32, 16384)
# The configuration node's authoring rule for the two passes.
PRODUCTION_PASS_ASPECT_TOLERANCE = 0.01
PRODUCTION_SIZE_ASPECTS = ("16:9", "9:16", "1:1", "4:3", "3:4", "21:9")
# ComfyUI's core Resolution Selector (comfy_extras/nodes_resolution.py).
# Inputs that mark a node as the one carrying a workflow's configured size.
PRODUCTION_SECOND_PASS_INPUTS = ("second_pass_width", "second_pass_height", "second_pass_multiplier")
PRODUCTION_SELECTOR_RATIOS = {
    "1:1 (Square)": (1, 1), "2:3 (Portrait Photo)": (2, 3), "3:2 (Photo)": (3, 2),
    "3:4 (Portrait Standard)": (3, 4), "4:3 (Standard)": (4, 3),
    "9:16 (Portrait Widescreen)": (9, 16), "16:9 (Widescreen)": (16, 9), "21:9 (Ultrawide)": (21, 9),
}


class ProductionSizeError(ValueError):
    def __init__(self, code, message, *, status=422, path="/settings", details=None):
        super().__init__(message)
        self.code, self.status, self.path, self.details = code, status, path, details or {}


def production_size_at_pixels(pixels, aspect_width, aspect_height, *, larger_than=None, aspect_tolerance=None):
    """The multiple-of-32 size nearest the aspect and pixel count, or None.

    Candidates keep the pixel count within the tolerance. The smallest sum of
    aspect and pixel-count deviation wins, then the smaller aspect deviation.
    """
    step, (low, high) = PRODUCTION_SIZE_MULTIPLE, PRODUCTION_SIZE_LIMITS
    ratio = aspect_width / aspect_height
    ideal_width, ideal_height = production_math.sqrt(pixels * ratio), production_math.sqrt(pixels / ratio)
    best = None
    for width in range((int(ideal_width) // step - 3) * step, (int(ideal_width) // step + 5) * step, step):
        for height in range((int(ideal_height) // step - 3) * step, (int(ideal_height) // step + 5) * step, step):
            if not (low <= width <= high and low <= height <= high):
                continue
            if abs(width * height / pixels - 1) > PRODUCTION_SIZE_TOLERANCE:
                continue
            if larger_than and (width <= larger_than[0] or height <= larger_than[1]):
                continue
            if aspect_tolerance is not None and not production_math.isclose(width / height, ratio, rel_tol=aspect_tolerance):
                continue
            aspect = abs(production_math.log(width / height / ratio))
            score = (aspect + abs(production_math.log(width * height / pixels)), aspect)
            if best is None or score < best[0]:
                best = (score, (width, height))
    return best and best[1]


def nearest_production_size(saved_width, saved_height, aspect_width, aspect_height):
    """For 960x544 at 3:4 this returns (640, 832)."""
    return production_size_at_pixels(saved_width * saved_height, aspect_width, aspect_height)


def _production_scalar(api, value):
    if type(value) is int:
        return value
    if not (isinstance(value, list) and len(value) == 2 and isinstance(value[0], str)
            and type(value[1]) is int and value[0] in api):
        return None
    node = api[value[0]]
    kind, inputs = node.get("class_type"), node.get("inputs", {})
    if kind == "PrimitiveInt" and value[1] == 0 and type(inputs.get("value")) is int:
        return inputs["value"]
    if kind == "ResolutionSelector" and value[1] in (0, 1):
        ratio = PRODUCTION_SELECTOR_RATIOS.get(inputs.get("aspect_ratio"))
        megapixels, multiple = inputs.get("megapixels"), inputs.get("multiple", 8)
        if ratio and type(megapixels) in (int, float) and type(multiple) is int and multiple > 0:
            scale = production_math.sqrt(megapixels * 1024 * 1024 / (ratio[0] * ratio[1]))
            return round(ratio[value[1]] * scale / multiple) * multiple
    return None


def production_saved_size(profile):
    """The saved first-pass, second-pass and output sizes, or ProductionSizeError."""
    workflow = profile.get("workflow") if isinstance(profile, dict) else None
    api = workflow.get("api") if isinstance(workflow, dict) else None
    if not isinstance(api, dict):
        raise ProductionSizeError("immutable_profile", "This saved workflow has no API graph to carry a production size.", status=409)
    timeline = api.get(workflow.get("timeline_node"), {})
    # The configuration node is the one node besides the Timeline that sets width, height and a second pass.
    configs = [key for key, node in api.items() if key != workflow.get("timeline_node") and isinstance(node, dict)
               and isinstance(node.get("inputs"), dict) and {"width", "height"} <= set(node["inputs"])
               and any(name in node["inputs"] for name in PRODUCTION_SECOND_PASS_INPUTS)]
    if len(configs) != 1 or timeline.get("class_type") != "H3C_Timeline":
        raise ProductionSizeError("immutable_profile", "This saved workflow has no single configuration node (width, height and second-pass inputs) to carry a production size; upload a new revision.", status=409)
    config = configs[0]
    inputs = api[config].get("inputs", {})
    first = tuple(_production_scalar(api, inputs.get(key)) for key in ("width", "height"))
    timeline_size = []
    for key, index in (("width", 2), ("height", 3)):
        value = timeline.get("inputs", {}).get(key)
        timeline_size.append(first[index - 2] if value == [config, index] else _production_scalar(api, value))
    if None in first or tuple(timeline_size) != first:
        raise ProductionSizeError("immutable_profile", "The saved size is not a literal or Resolution Selector value that also drives the Timeline; upload a new revision.", status=409)
    if "second_pass_width" in inputs or "second_pass_height" in inputs:
        second = tuple(_production_scalar(api, inputs.get(key)) for key in ("second_pass_width", "second_pass_height"))
        if None in second:
            raise ProductionSizeError("immutable_profile", "The saved second-pass size cannot be read without running its node; upload a new revision.", status=409)
    elif inputs.get("second_pass_multiplier", 1) == 1:
        second = first  # The historic multiplier 1 made both passes the base size.
    else:
        raise ProductionSizeError("immutable_profile", "The captured second-pass multiplier needs its original size; upload a new revision.", status=409)
    output = profile.get("output_geometry")
    output = (output["width"], output["height"]) if isinstance(output, dict) and {"width", "height"} <= set(output) else None
    return {"config_node": config, "first": first, "second": second,
            "second_inputs": "second_pass_width" in inputs or "second_pass_height" in inputs, "output": output,
            "captured": profile.get("captured_api") == 2}


def _production_pass(width, height):
    return {"width": width, "height": height, "pixels": width * height}


def production_size_record(saved, width, height):
    """Derive both passes and the expected output for a requested first pass."""
    (w1, h1), (w2, h2) = saved["first"], saved["second"]
    change = width * height / (w1 * h1) - 1
    if abs(change) > PRODUCTION_SIZE_TOLERANCE:
        nearest = nearest_production_size(w1, h1, width, height)
        hint = f" At {width}:{height} use {nearest[0]}x{nearest[1]}." if nearest else ""
        raise ProductionSizeError(
            "invalid_production_size",
            f"{width}x{height} has {width * height} pixels, {change:+.1%} from this saved workflow's {w1}x{h1} "
            f"({w1 * h1} pixels). Any aspect ratio is allowed within ±{PRODUCTION_SIZE_TOLERANCE:.0%} of the saved pixel count, "
            f"in multiples of {PRODUCTION_SIZE_MULTIPLE}.{hint}",
            details={"saved": _production_pass(w1, h1), "nearest": nearest and _production_pass(*nearest)})
    enabled = w2 > w1 and h2 > h1
    if (width, height) == (w1, h1):
        second = (w2, h2) if enabled else (width, height)  # The saved size renders unchanged.
    elif enabled:
        second = production_size_at_pixels(w2 * h2, width, height, larger_than=(width, height),
                                           aspect_tolerance=PRODUCTION_PASS_ASPECT_TOLERANCE)
        if second is None:
            raise ProductionSizeError("invalid_production_size",
                f"No second-pass size near {w2 * h2} pixels matches {width}x{height} within 1% aspect; choose another size.")
    else:
        second = (width, height)
    record = {
        "tolerance": PRODUCTION_SIZE_TOLERANCE, "multiple": PRODUCTION_SIZE_MULTIPLE, "config_node": saved["config_node"],
        "saved": {**_production_pass(w1, h1), "second_pass": {**_production_pass(w2, h2), "enabled": enabled}},
        "production": {**_production_pass(width, height), "pixel_change": round(change, 4),
                       "second_pass": {**_production_pass(*second), "enabled": enabled,
                                       "pixel_change": round(second[0] * second[1] / (w2 * h2) - 1, 4)}},
    }
    if saved["output"]:
        final_saved, final = ((w2, h2), second) if enabled else ((w1, h1), (width, height))
        record["saved_output_geometry"] = {"width": saved["output"][0], "height": saved["output"][1]}
        record["output_geometry"] = {"width": round(saved["output"][0] * final[0] / final_saved[0]),
                                     "height": round(saved["output"][1] * final[1] / final_saved[1])}
    return record


def production_size(profile, settings):
    """None without a size change, else the rewritten workflow and its record."""
    if not settings:
        return None
    if not isinstance(settings, dict) or set(settings) != {"width", "height"}:
        raise ProductionSizeError(
            "immutable_profile",
            "Technical settings belong to this saved workflow; upload a new revision. Only width and height may change, "
            "together, at the saved pixel count.", status=409)
    width, height = settings["width"], settings["height"]
    for key, value in (("width", width), ("height", height)):
        if (type(value) is not int or value % PRODUCTION_SIZE_MULTIPLE
                or not PRODUCTION_SIZE_LIMITS[0] <= value <= PRODUCTION_SIZE_LIMITS[1]):
            raise ProductionSizeError("invalid_production_size",
                f"settings.{key} must be a multiple of {PRODUCTION_SIZE_MULTIPLE} between 32 and 16384.", path="/settings/" + key)
    saved = production_saved_size(profile)
    if (width, height) == saved["first"]:
        return None
    record = production_size_record(saved, width, height)
    workflow = production_copy.deepcopy(profile["workflow"])
    inputs = workflow["api"][saved["config_node"]]["inputs"]
    inputs["width"], inputs["height"] = width, height
    if saved["second_inputs"]:
        second = record["production"]["second_pass"]
        inputs["second_pass_width"], inputs["second_pass_height"] = second["width"], second["height"]
    return {"workflow": workflow, "record": record}


def production_size_summary(profile):
    """Read-only discovery: the saved size and the size for each common aspect ratio."""
    try:
        if not isinstance(profile, dict) or profile.get("immutable_settings") is not True:
            return {}
        saved = production_saved_size(profile)
        (w1, h1), (w2, h2) = saved["first"], saved["second"]
        by_aspect = {}
        for aspect in PRODUCTION_SIZE_ASPECTS:
            a, b = (int(part) for part in aspect.split(":"))
            nearest = nearest_production_size(w1, h1, a, b)
            try:
                if nearest is None:
                    raise ProductionSizeError("invalid_production_size", "No size at this aspect keeps the saved pixel count.")
                record = production_size_record(saved, *nearest)
                by_aspect[aspect] = {"width": nearest[0], "height": nearest[1],
                                     "second_pass": {key: record["production"]["second_pass"][key] for key in ("width", "height", "enabled")},
                                     **({"output_geometry": record["output_geometry"]} if "output_geometry" in record else {})}
            except ProductionSizeError as error:
                by_aspect[aspect] = {"unavailable": str(error)}
        return {"configured_size": {
            "tolerance": PRODUCTION_SIZE_TOLERANCE, "multiple": PRODUCTION_SIZE_MULTIPLE,
            "saved": {**_production_pass(w1, h1), "second_pass": {**_production_pass(w2, h2), "enabled": w2 > w1 and h2 > h1},
                      **({"output_geometry": {"width": saved["output"][0], "height": saved["output"][1]}} if saved["output"] else {})},
            "by_aspect": by_aspect}}
    except (ProductionSizeError, KeyError, TypeError, ValueError, ZeroDivisionError):
        return {}


class Profiles:
    def __init__(self, root, node_info):
        self.root = Path(root).resolve()
        self.node_info = node_info
        self.shipped = Path(__file__).with_suffix("")
        (self.root / "snapshots").mkdir(parents=True, exist_ok=True)

    def _configured(self):
        files = {p.stem: p for p in self.shipped.glob("*.json")}
        files.update({p.stem: p for p in (self.root / "configured").glob("*.json")})
        return files

    def _read(self, path):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            value.pop("sha256", None)
            canonical(value)
            return value
        except (OSError, ValueError, TypeError):
            raise APIError("profile_unavailable", "Configured profile cannot be read.", status=503) from None

    def _probe(self, profile):
        reasons = []
        workflow = profile.get("workflow", {})
        api, ui = workflow.get("api", {}), workflow.get("ui", {})
        info = self.node_info({node["class_type"] for node in api.values()})
        target = workflow.get("timeline_node")
        saves = [key for key, node in api.items() if node.get("class_type") == "H3C_SaveSegment"]
        captured = profile.get("captured_api") == 2
        selected = workflow.get("save_node") if captured else (saves[0] if len(saves) == 1 else None)
        if target not in api or api[target].get("class_type") != "H3C_Timeline" or selected not in saves:
            return [{"code": "profile_graph", "message": "Profile needs one Timeline and one native Save Segment."}]
        save = api[selected]["inputs"]
        fps = profile.get("output_fps", 24) if captured else 24
        if (type(fps) not in (int, float) or not 1 <= fps <= 240
                or (captured and (not isinstance(workflow.get("execution_outputs"), list)
                    or not 1 <= len(workflow["execution_outputs"]) <= 2
                    or workflow["execution_outputs"][0] != selected
                    or (len(workflow["execution_outputs"]) == 2 and api.get(workflow["execution_outputs"][1], {}).get("class_type") != "SaveVideo")))):
            return [{"code": "profile_graph", "message": "Invalid captured delivery contract."}]
        if save.get("segment") != [target, 3] or save.get("fps") != fps or save.get("write_full_video") is not True:
            reasons.append({"code": "profile_graph", "message": "Save Segment must consume the Timeline and write native 24 fps full video."})
        noise = [node for node in api.values() if node.get("class_type") == "RandomNoise"]
        if (not any(n["inputs"].get("noise_seed") == [target, 4] for n in noise)
                or (not captured and len(noise) != 1)):
            reasons.append({"code": "profile_graph", "message": "RandomNoise must use the Timeline seed."})
        ui_nodes = {str(node["id"]): node for node in ui.get("nodes", [])}
        if set(ui_nodes) != set(api):
            reasons.append({"code": "profile_ui", "message": "Profile UI and API node identities differ."})
        active = set()
        def visit(node_id):
            if node_id in active or node_id not in api: return
            active.add(node_id)
            for value in api[node_id].get("inputs", {}).values():
                if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str): visit(value[0])
        if captured:
            for output in workflow["execution_outputs"]: visit(output)
        for node_id, node in api.items():
            if captured and node_id not in active: continue
            kind = node.get("class_type")
            schema = info.get(kind)
            if schema is None:
                reasons.append({"code": "missing_node", "node": node_id, "class_type": kind})
                continue
            fields = {**schema.get("input", {}).get("required", {}), **schema.get("input", {}).get("optional", {})}
            for name, value in node.get("inputs", {}).items():
                specification = fields.get(name, fields.get(name.split(".")[0]))
                if specification is None and captured and kind == "CustomCombo":
                    values = node["inputs"]
                    index = values.get("index")
                    bound = type(index) is int and index >= 0 and isinstance(values.get("choice"), str) and values.get("choice") == values.get("option" + str(index + 1))
                    if bound and ((name == "index" and type(value) is int) or (re.fullmatch(r"option[1-9]\d*", name) and isinstance(value, str))):
                        specification = ["INT" if name == "index" else "STRING"]
                if specification is None:
                    reasons.append({"code": "input_schema", "node": node_id, "input": name})
                elif not isinstance(value, list) and isinstance(specification[0], list) and value not in specification[0]:
                    reasons.append({"code": "missing_choice", "node": node_id, "input": name,
                                    "message": "Configured choice is not installed."})
            if node_id in ui_nodes:
                outputs = ui_nodes[node_id].get('outputs', [])
                native = list(schema.get('output', []))
                images = outputs[len(native):] if kind == 'H3C_Timeline' else []
                if ([o.get('type') for o in outputs[:len(native)]] != native
                        or (len(outputs) != len(native) and not images)
                        or any(o.get('type') != 'IMAGE' or not re.fullmatch(r'image_[1-9]\d*', o.get('name', '')) for o in images)):
                    reasons.append({"code": "output_schema", "node": node_id, "class_type": kind})
                try:
                    timeline_prepare.ui_connections(ui, ui_nodes[node_id], api, list(node["inputs"]))
                except (ValueError, KeyError, TypeError):
                    reasons.append({"code": "profile_ui", "node": node_id, "message": "UI edges do not match native graph."})
        return reasons

    def _snapshot(self, profile):
        checksum = digest(profile)
        destination = self.root / "snapshots" / (checksum + ".json")
        content = canonical(profile)
        if destination.exists():
            if destination.read_bytes() != content:
                raise APIError("profile_unavailable", "Pinned profile snapshot is damaged.", status=503)
        else:
            temporary = destination.with_suffix("." + uuid.uuid4().hex + ".tmp")
            try:
                with temporary.open("xb") as stream:
                    stream.write(content); stream.flush(); os.fsync(stream.fileno())
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
        return {**profile, "sha256": checksum}

    def list(self):
        result = []
        for profile_id, path in sorted(self._configured().items()):
            try:
                profile = self._snapshot(self._read(path))
                reasons = self._probe(profile)
                result.append({"id": profile_id, "title": profile.get("title", profile_id),
                               "sha256": profile["sha256"], "ready": not reasons, "reasons": reasons,
                               **production_size_summary(profile)})
            except APIError as error:
                result.append({"id": profile_id, "ready": False, "reasons": [{"code": error.code, "message": str(error)}]})
        return result

    def get(self, profile_id, sha256=None):
        if not isinstance(profile_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", profile_id):
            raise APIError("not_found", "Render profile was not found.", status=404)
        if sha256 is not None:
            if not re.fullmatch(r"[a-f0-9]{64}", sha256):
                raise APIError("invalid_request", "Profile digest is invalid.")
            path = self.root / "snapshots" / (sha256 + ".json")
        else:
            path = self._configured().get(profile_id)
        if path is None or not path.is_file():
            raise APIError("not_found", "Render profile was not found.", status=404)
        profile = self._read(path)
        if profile.get("id") != profile_id or (sha256 is not None and digest(profile) != sha256):
            raise APIError("profile_unavailable", "Pinned profile identity does not match its snapshot.", status=503)
        reasons = self._probe(profile)
        if reasons:
            raise APIError("profile_unavailable", "Configured render profile is unavailable on this host.", status=503,
                           details={"profile": profile_id, "reasons": reasons})
        return self._snapshot(profile)

    def prepare(self, profile, sequence, body, resolved_assets):
        production = None
        if profile.get("immutable_settings") is True and body.get("settings"):
            try:
                production = production_size(profile, body["settings"])
            except ProductionSizeError as error:
                raise APIError(error.code, str(error), status=error.status, path=error.path, details=error.details) from None
        request = {"version": 1, "name": sequence, "timeline": copy.deepcopy(body["timeline"]),
                   "settings": copy.deepcopy(body.get("settings", {})), "workflow": production["workflow"] if production else copy.deepcopy(profile["workflow"]),
                   "assets": copy.deepcopy(resolved_assets), "semantic_boxes": copy.deepcopy(body.get("semantic_boxes", {}))}
        prepared = timeline_prepare.prepare(request)
        if not prepared.get("ok"):
            error = prepared["errors"][0]
            pointer = "/" + "/".join(error["path"].split(".")) if error["path"] != "$" else ""
            raise APIError("invalid_timeline", error["message"], path=pointer)
        if production:
            prepared["production_size"] = production["record"]
        return prepared

    def workflow(self, profile, project, *, mode="fork"):
        if mode not in ("fork", "attached"):
            raise APIError("invalid_request", "Workflow mode must be fork or attached.", path="/mode")
        prepared = project["prepared"]
        ui = copy.deepcopy(prepared["workflow"]["ui"])
        target = prepared["workflow"]["timeline_node"]
        node = next(node for node in ui["nodes"] if str(node["id"]) == target)
        node.setdefault("properties", {})["h3c_project"] = {
            "id": project["id"], "revision": project["revision"], "profile_sha256": project["profile_sha256"], "mode": mode}
        # The native widget is already a string, retaining uint64 seed digits.
        node["properties"]["h3c_asset_bindings"] = copy.deepcopy(project.get("assets", []))
        return ui

# static-configuration-interop-v1

# captured-api-delivery-v2

# captured-api-choice-v1

# captured-api-active-outputs-v1

# configured-production-size-v1
