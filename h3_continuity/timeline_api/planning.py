"""Read-only native dependency, reuse and movie-splice planning."""

import copy
import json
from pathlib import Path

from .. import bridges, nodes, replacement, store, timeline as rules, timeline_node
from .assets import contained
from .contracts import APIError, canonical, digest, validate

STUDIO_ONLY = "Replacement regions are reviewed and selected in the Studio."


def media_units(units):
    """The units whose media the full video plays end to end; a replacement overlays them instead."""
    return [unit for unit in units if unit["kind"] != "replacement"]


def splice_ranges(units):
    """([{unit_id, range}], total frames) on the full-video clock. A replacement's range overlays the end of the box
    before its join and the start of the box after it, so it adds no frames."""
    by_id, ranges, offset = {unit["id"]: unit for unit in units}, [], 0
    for unit in [u for u in units if u["kind"] == "box"]:
        bridge = by_id.get("bridge:" + unit["box_id"])
        if bridge is not None:
            ranges.append({"unit_id": bridge["id"], "range": [offset, offset + bridge["frames"]]})
            offset += bridge["frames"]
        swap = by_id.get("replacement:" + unit["box_id"])
        if swap is not None:
            ranges.append({"unit_id": swap["id"], "range": [offset - swap["left"], offset + swap["right"]],
                           "overlay": True, "plays": bool(swap.get("plays"))})
        ranges.append({"unit_id": unit["id"], "range": [offset, offset + unit["frames"]]})
        offset += unit["frames"]
    return ranges, offset


def native_status(body):
    """Native compatibility plus exact manifest/file evidence, under one read lock."""
    with nodes.SEQUENCE_LOCK:
        status = timeline_node.request_status(body, materialize=False)
        if not status.get("ok"):
            raise APIError("native_state_unavailable", "Native Timeline status could not be inspected.", status=409)
        folder = Path(store.sequence_dir(nodes.sequences_root(), body["name"])).resolve()
        manifest = store.load_manifest(folder)
        evidence = {}
        for kind, entries in (("box", manifest["segments"]), ("bridge", manifest.get("bridges", []))):
            for entry in entries:
                box_id = (entry.get("timeline") or {}).get("box") if kind == "box" else entry.get("box")
                if box_id is None: continue
                filenames = [entry["stem"] + ".safetensors", entry["stem"] + "_last.png"]
                if entry.get("video"): filenames.append(entry["video"]["file"])
                stamps = []
                for filename in filenames:
                    path = contained(folder, folder / filename)
                    try:
                        stat = path.stat()
                        stamps.append([filename, stat.st_size, stat.st_mtime_ns])
                    except FileNotFoundError:
                        stamps.append([filename, None])
                evidence[kind + ":" + box_id] = digest({"entry": entry, "files": stamps})
        return {**status, "unit_evidence": evidence,
                "manifest_sha256": digest({"manifest": manifest, "unit_evidence": evidence})}


# Box reuse across project updates.
"""Which project assets belong in every H3 Timeline unit's reuse identity.

Pure functions; no ComfyUI or H3 imports.

Native planning gives each box and bridge an input identity: the profile, the
settings, every bound project asset, and the box's native layout key. Because
every asset was in every unit's identity, replacing one box's guide changed
every unit, and the plan rendered the whole film again.

The bindings below write their asset into the prepared Timeline JSON as a
file named by the asset's SHA-256 (the API re-checks those bytes before every
plan). The native layout key already names that file for each box that reads
it: guides through the guide chain, plates through the plate chain, timed audio
clips, voice clips and Studio pictures (image17 and up) through the files the
box sends, and reference replacements in every box. Those assets therefore
leave the project-wide part of the identity and count only for those boxes.

Everything else stays project-wide, as before: pictures and audio wired into
the Timeline through loader nodes (image1-image16, audio sockets), Whisper
sources and any binding kind this module does not know.
"""

# Bindings whose content-addressed file the native layout key carries per box.
BOX_REUSE_TIMELINE_BINDINGS = frozenset(("guide", "plate", "audio_clip", "voice_clip", "reference_replacement"))
# The Timeline node has 16 wired picture inputs; Studio pictures are saved from image17 up.
BOX_REUSE_WIRED_PICTURES = 16


def box_reuse_studio_slot(slot):
    """A Studio picture saved in the Timeline itself (image17 and up), not a wired loader input."""
    if not isinstance(slot, str) or not slot.startswith("image"):
        return False
    number = slot[len("image"):]
    return number.isdigit() and not number.startswith("0") and int(number) > BOX_REUSE_WIRED_PICTURES


def box_reuse_project_wide(binding):
    """Whether this binding's asset belongs in every unit's identity."""
    kind = binding.get("kind")
    if kind == "candidate":
        return False  # Still candidates never reach a render; native planning already left them out.
    if kind == "picture":
        return not box_reuse_studio_slot(binding.get("slot"))
    return kind not in BOX_REUSE_TIMELINE_BINDINGS


def box_reuse_asset_identity(prepared, project):
    """The project-wide asset part of a unit's identity, shaped like native planning's own list."""
    identity = sorted({item["sha256"] for item in prepared.get("assets", [])
                       if any(box_reuse_project_wide(binding) for binding in item["bindings"])})
    identity += sorted({item["asset_id"] for item in project.get("assets", [])
                        if any(box_reuse_project_wide(binding) for binding in item["bindings"])})
    return identity


class Planner:
    def __init__(self, profiles, assets, native_status):
        self.profiles, self.assets, self.native_status = profiles, assets, native_status

    def _units(self, project, scoped=True):
        prepared = project["prepared"]
        parsed = rules.parse(canonical(prepared["timeline"]).decode("utf-8"))
        if parsed.layers:
            raise APIError("unsupported_timeline", "H3 Timeline API: this Timeline has clips with several videos, which "
                           "managed jobs can't render yet. Render it from the Studio.", status=422, path="/timeline")
        context = int(prepared["settings"]["context_frames"])
        asset_identity = sorted({item["sha256"] for item in prepared.get("assets", [])
                                 if any(binding['kind'] != 'candidate' for binding in item['bindings'])})
        asset_identity += sorted({item["asset_id"] for item in project.get("assets", [])
                                  if any(binding['kind'] != 'candidate' for binding in item['bindings'])})
        if scoped:
            asset_identity = box_reuse_asset_identity(prepared, project)
        identity = {"profile_sha256": project["profile_sha256"], "settings": prepared["settings"], "assets": asset_identity}
        units, by_box = [], {}
        for index in rules.render_order(parsed):
            box=parsed.boxes[index]
            dependencies = []
            if not rules.is_fresh(parsed, index):
                dependencies.append("box:" + parsed.boxes[rules.previous_index(parsed,index)].id)
            dependencies.extend("box:" + parsed.boxes[source].id for source, _, _ in rules.memory_sources(parsed, index))
            length = prepared["boxes"][index]
            unit = {"id": "box:" + box.id, "kind": "box", "box_id": box.id, "index": index + 1,
                    "dependencies": list(dict.fromkeys(dependencies)), "frames": length["frames"],
                    "generated_frames": length["generated"], "carried_frames": length["carried"],
                    "delivered_range": length["delivered_range"], "generated_range": length["generated_range"],
                    "input_sha256": digest({**identity, "layout": rules.layout_key(parsed, index, context)})}
            conflict = rules.carry_conflict(parsed, index, context)
            if conflict: unit["blocked_reason"] = conflict
            by_box[box.id] = unit
            units.append(unit)
        for bridge in parsed.bridges:
            index = bridges.position(parsed, bridge)
            before, after = parsed.boxes[rules.previous_index(parsed,index)].id, bridge["before"]
            carried, frozen = bridges.ends(context, {"frames": by_box[before]["generated_frames"]},
                                           {"frames": by_box[after]["generated_frames"]})
            unit = {"id": "bridge:" + after, "kind": "bridge", "box_id": after,
                    "dependencies": ["box:" + before, "box:" + after], "frames": bridge["frames"],
                    "generated_frames": carried + bridge["frames"] + frozen, "carried_frames": carried,
                    "frozen_frames": frozen, "input_sha256": digest({**identity, "layout": bridges.layout(parsed, bridge),
                        "before": by_box[before]["input_sha256"], "after": by_box[after]["input_sha256"]})}
            conflict = bridges.problem(parsed, bridge)
            if conflict: unit["blocked_reason"] = conflict
            units.append(unit)
        for bridge in parsed.replacements:
            index = replacement.position(parsed, bridge)
            before, after = parsed.boxes[rules.previous_index(parsed,index)].id, bridge["before"]
            units.append({"id": "replacement:" + after, "kind": "replacement", "box_id": after,
                          "dependencies": ["box:" + before, "box:" + after], "left": bridge["left"],
                          "right": bridge["right"], "replaced_frames": bridge["left"] + bridge["right"],
                          "selected": bridge.get("selected"), "input_sha256": digest({**identity, "region": replacement.static_key(parsed, bridge, context),
                              "recipe": replacement.recipe(parsed, bridge), "review": bridge.get("review"),
                              "selected": bridge.get("selected"), "before": by_box[before]["input_sha256"],
                              "after": by_box[after]["input_sha256"]})})
        return units

    def _record(self, project, unit):
        try:
            return self.assets.records.get_blob_record("unit", project["id"] + ":" + unit["id"])
        except APIError as error:
            if error.status != 404: raise
            return None

    def plan(self, project, selection):
        selection = validate("selection", selection)
        prepared = project["prepared"]
        profile = self.profiles.get(project["profile"], project["profile_sha256"])
        # Re-read original/role bytes and native preparation before any reuse.
        resolved = self.assets.resolve(project.get("assets", []), project["authored"]["timeline"], profile)
        fresh = self.profiles.prepare(profile, project["sequence"], project["authored"], resolved)
        if fresh["fingerprint"] != prepared["fingerprint"]:
            raise APIError("prepared_inputs_changed", "Pinned prepared inputs have changed; revise the project.", status=409)
        units = self._units(project)
        # A record verified before this layer holds the stricter whole-project identity; it still proves its unit.
        legacy = {unit["id"]: unit["input_sha256"] for unit in self._units(project, scoped=False)}
        selected = selection.get("ids", [])
        receipt = selection.get("rebuild_continuity")
        if receipt is not None:
            if not selection.get("rerender") or selected != [receipt["box"]]:
                raise APIError("invalid_selection", "Continuity recovery regenerates one selected clip.")
            from .. import regeneration
            check = regeneration.request({"name": project["sequence"],
                                          "timeline": canonical(prepared["timeline"]).decode("utf-8"),
                                          "settings": prepared["settings"], "box": receipt["box"]})
            if not check.get("ok") or check.get("receipt") != receipt:
                raise APIError("regeneration_changed", regeneration.CHANGED, status=409)
        known_boxes = {unit["box_id"] for unit in units if unit["kind"] == "box"}
        if set(selected) - known_boxes:
            raise APIError("invalid_selection", "Selection contains an unknown box.", path="/selection/ids")
        status = self.native_status({"name": project["sequence"], "timeline": canonical(prepared["timeline"]).decode("utf-8"),
                                     "settings": prepared["settings"]})
        native_states = {"box:" + item["id"]: item for item in status["boxes"]}
        native_states.update({("replacement:" if item.get("mode") == "replace" else "bridge:") + item["box"]: item
                              for item in status.get("bridges", [])})
        forced = {"box:" + box_id for box_id in selected} if selection.get("rerender") else set()
        by_id = {}
        for unit in units:
            native = native_states.get(unit["id"], {})
            if unit["kind"] == "replacement":
                reasons = [STUDIO_ONLY] + ([native["note"]] if native.get("note") else [])
                affected = [source for source in unit["dependencies"] if by_id[source]["action"] != "reuse"]
                if affected and unit["selected"]:
                    reasons.append("Rendering " + ", ".join(affected) + " makes the selected candidate stale; the "
                                   "full video plays the original cut until a new candidate is selected in the Studio.")
                unit.update(action="studio", reasons=reasons, plays=bool(native.get("plays")),
                            native_sha256=status.get("unit_evidence", {}).get(unit["id"]))
                by_id[unit["id"]] = unit
                continue
            record = self._record(project, unit)
            evidence = status.get("unit_evidence", {}).get(unit["id"])
            reusable = (native.get("status") == "done" and record and record.get("verified")
                        and record.get("input_sha256") in (unit["input_sha256"], legacy.get(unit["id"]))
                        and evidence and record.get("native_sha256") == evidence)
            reasons = []
            affected = [source for source in unit["dependencies"] if by_id[source]["action"] != "reuse"]
            if unit.get("blocked_reason"):
                action = "blocked"; reasons.append(unit["blocked_reason"])
            elif any(by_id[source]["action"] == "blocked" for source in unit["dependencies"]):
                action = "blocked"; reasons.append("A required dependency is blocked.")
            elif unit["id"] in forced:
                action = "render"; reasons.append("Explicitly selected for a new take.")
            elif affected:
                action = "render"; reasons.append("Required dependency will render: " + ", ".join(affected))
            elif reusable:
                action = "reuse"; reasons.append("Native compatibility and verified API input/media identity match.")
            else:
                action = "render"
                reasons.append(native.get("reason") or native.get("note") or (
                    "Native media lacks matching verified API input identity; conservatively render." if native.get("status") == "done"
                    else "Full video requires this missing or stale unit."))
            if action == "reuse":
                unit["input_sha256"] = record["input_sha256"]  # finalize checks the identity it was verified under
            unit.update(action=action, reasons=reasons, native_sha256=evidence)
            by_id[unit["id"]] = unit
        if receipt is not None:
            # Recovery deliberately leaves missing dependents for the user's later Render remaining action.
            units = [unit for unit in units if unit["id"] == "box:" + receipt["box"]]
            units[0]["rebuild_continuity"] = receipt
        ranges, offset = splice_ranges(units)
        result = {"api_version": 1, "project_id": project["id"], "revision": project["revision"],
                  "profile_sha256": project["profile_sha256"], "fingerprint": prepared["fingerprint"],
                  "assets_sha256": digest(project.get("assets", [])), "manifest_sha256": status.get("manifest_sha256", digest(status)),
                  "selection": selection, "units": units, "total_frames": offset, "fps": 24, "splice_ranges": ranges}
        result["plan_sha256"] = digest(result)
        return result

    def invalidation(self, before, after):
        previous = {unit["id"]: unit for unit in self._units(before)}
        units = self._units(after)
        asset_changed = {asset["asset_id"] for asset in before.get("assets", [])
                         if any(box_reuse_project_wide(binding) for binding in asset['bindings'])} != {
                             asset["asset_id"] for asset in after.get("assets", [])
                             if any(box_reuse_project_wide(binding) for binding in asset['bindings'])}
        changed, result = set(), []
        for unit in units:
            old = previous.get(unit["id"])
            direct = old is None or old["input_sha256"] != unit["input_sha256"]
            dependencies = [item for item in unit["dependencies"] if item in changed]
            if direct or dependencies:
                changed.add(unit["id"])
                result.append({"id": unit["id"], "kind": unit["kind"], "box_id": unit["box_id"],
                               "reasons": [("Asset identity changed; conservative invalidation includes this unit." if asset_changed
                                            else "Prepared input identity changed.") if direct else "Dependency changed: " + ", ".join(dependencies)]})
        result.extend({"id": unit_id, "kind": old["kind"], "box_id": old["box_id"], "reasons": ["Unit removed."]}
                      for unit_id, old in previous.items() if unit_id not in {unit["id"] for unit in units})
        return result

    def selected_graph(self, project, unit):
        graph = copy.deepcopy(project["prepared"]["workflow"]["api"])
        target = project["prepared"]["workflow"]["timeline_node"]
        line = copy.deepcopy(project["prepared"]["timeline"])
        line.pop("render_box", None); line.pop("render_bridge", None)
        line.pop("rebuild_continuity", None)
        if unit.get("rebuild_continuity"):
            line["rebuild_continuity"] = copy.deepcopy(unit["rebuild_continuity"])
        if unit["kind"] == "box":
            try:
                line["render_box"] = next(index + 1 for index, box in enumerate(line["boxes"]) if box["id"] == unit["box_id"])
            except StopIteration:
                raise APIError("invalid_selection", "Render unit box was not found.") from None
        elif unit["kind"] == "bridge":
            line["render_bridge"] = unit["box_id"]
        else:
            raise APIError("invalid_selection", "Render unit kind is invalid.")
        graph[target]["inputs"]["timeline"] = canonical(line).decode("utf-8")
        return graph

# box-reuse-asset-scope-v1
