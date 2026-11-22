"""Read-only external Timeline preparation. No media decoding, model or sequence execution."""

import copy
import dataclasses
import hashlib
import json
import ntpath
import os
import re
from pathlib import Path

import folder_paths

from . import timeline as rules, h3_prompt_ir as ir, h3_prompt_compile as compiler, timed_text
from . import reference_replacements, timing
from .story_bible import is_story_source
from .store import validate_name

REVISION = "timeline-prepare-v3"
DEFAULTS = dict(width=1344, height=768, context_frames=39, carry_audio=True, ref_image_size="match", audio_context_frames=0)
WIDGETS = ["name", "width", "height", "context_frames", "carry_audio", "ref_image_size", "timeline", "audio_context_frames"]
PRIMITIVES = {"PrimitiveInt": int, "PrimitiveFloat": float, "PrimitiveBoolean": bool,
              "PrimitiveString": str, "PrimitiveStringMultiline": str}
LOADERS = {"LoadImage": ("image", "image"), "LoadImageOutput": ("image", "image"), "LoadAudio": ("audio", "audio")}


def instructions():
    """Ship maintained public/native bodies, so remote authors need no repository access."""
    from .story_prompts import GUIDE, H3_WRITING_GUIDANCE, TRANSITION_GUIDANCE
    root = Path(__file__).resolve().parent.parent
    guides = [dict(id=key, body=body) for key, body in GUIDE.items()]
    guides.extend([dict(id="prompt-writing", body=H3_WRITING_GUIDANCE),
                   dict(id="transitions", body=TRANSITION_GUIDANCE)])
    for key, filename in (("external-timeline", "EXTERNAL-TIMELINE.md"),
                          ("timeline-text", "TIMELINE-TEXT.md"), ("timeline-audio", "TIMELINE-AUDIO.md"),
                          ("timeline-references", "TIMELINE-REFERENCES.md"),
                          ("native-transitions", "H3-TRANSITIONS.md"), ("timeline-api", "TIMELINE-API.md")):
        guides.append(dict(id=key, body=(root / "docs" / filename).read_text(encoding="utf-8")))
    entry = "h3-continuity-video"
    names = sorted((path.parent.name for path in (root / "skills").glob("*/SKILL.md")), key=lambda name: (name != entry, name))
    skills = [dict(name=name, body=(root / "skills" / name / "SKILL.md").read_text(encoding="utf-8")) for name in names]
    result = dict(ok=True, version=1, instructions_revision="external-instructions-v10",
                  revisions=dict(preparation=REVISION, schema=ir.VERSION, guidance=ir.GUIDELINE_REVISION),
                  skill=skills[0]["body"], skills=skills,
                  guides=guides,
                  examples=[dict(id="whisper-source30", body=json.loads(
                      (root / "examples/whisper-source30.json").read_text(encoding="utf-8")))],
                  client=dict(filename="external_timeline.py", language="python",
                              body=(root / "examples/external_timeline.py").read_text(encoding="utf-8")),
                  clients=[dict(filename="timeline_api.py", language="python", api_version=1,
                                body=(root / "examples/timeline_api.py").read_text(encoding="utf-8"))],
                  limits=dict(fps=24, generated_frame_grid="17k+5", context_frames=[int(c) for c in timing.CONTEXT_OPTIONS],
                              image_slots=rules.IMAGE_SLOTS, saved_picture_slots="image17 and up",
                              exact_frames=dict(fresh=[1, rules.MAX_FRAMES],
                                                continuing=[1, f"{rules.MAX_FRAMES} minus context_frames"]),
                              max_frames=dict(default=rules.MAX_FRAMES, long=rules.LONG_MAX_FRAMES,
                                              note="Timeline field max_frames (17k+5) raises the box limit; boxes "
                                                   "past the default need H3 Context Windows when sampled."),
                              bridge_frames=list(rules.BRIDGE_FRAMES),
                              reference_images_per_box=rules.MAX_REF_IMAGES,
                              reference_audios_per_box=rules.MAX_REF_AUDIOS,
                              reference_videos_per_box=rules.MAX_REF_VIDEOS,
                              reference_video_audios_per_box=rules.MAX_REF_VIDEOS,
                              video_slots=rules.VIDEO_SLOTS, video_audio_slots=rules.VIDEO_AUDIO_SLOTS,
                              modes=["t2va", "flf2va", "ref2va"],
                              geometry=dict(min=32, max=16384, multiple=32), timeline_version=1))
    result["bundle_sha256"] = hashlib.sha256(compact(result).encode("utf-8")).hexdigest()
    return result


class Invalid(ValueError):
    def __init__(self, path, message):
        self.path = path
        super().__init__(message)


def fail(path, message):
    raise Invalid(path, message)


def checked(path, function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except ValueError as error:
        fail(path, str(error))


def object_at(value, path):
    if not isinstance(value, dict):
        fail(path, "must be a JSON object")
    return value


def compact(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def link(value):
    return isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and type(value[1]) is int and value[1] >= 0


def ui_node(ui, node_id, node_type):
    nodes = [node for node in ui["nodes"] if str(node.get("id")) == node_id]
    path = f"workflow.ui.nodes.{node_id}"
    if len(nodes) != 1 or nodes[0].get("type") != node_type:
        fail(path, "must identify exactly one matching API/UI node ID and type")
    return nodes[0]


def ui_connections(ui, node, api, names):
    """Compare owned input edges, including the input pointer and serialized root link record."""
    node_id = str(node["id"])
    inputs = node.get("inputs", [])
    rows = ui.get("links", [])
    if (not isinstance(inputs, list) or any(not isinstance(item, dict) for item in inputs)
            or not isinstance(rows, list) or any(not isinstance(row, list) or len(row) != 6 for row in rows)):
        fail(f"workflow.ui.nodes.{node_id}", "unsupported root input/link format")
    for name in names:
        path = f"workflow.ui.nodes.{node_id}.inputs.{name}"
        matches = [(index, item) for index, item in enumerate(inputs)
                   if item.get("name") == name or isinstance(item.get("widget"), dict) and item["widget"].get("name") == name]
        expected = api[node_id]["inputs"].get(name)
        expected = expected if link(expected) else None
        if len(matches) > 1:
            fail(path, "duplicate UI inputs cannot match the API connection")
        if not matches:
            if expected:
                fail(path, "missing UI input does not match the API connection")
            continue
        index, item = matches[0]
        if item.get("name") != name:
            fail(path, "renamed UI widget input does not match the API input name")
        pointer = item.get("link")
        incoming = [row for row in rows if str(row[3]) == node_id and row[4] == index]
        records = [row for row in rows if str(row[0]) == str(pointer)] if pointer is not None else []
        if pointer is None and not incoming:
            if expected:
                fail(path, "unlinked UI input does not match the API connection")
            continue
        if (expected is None or len(records) != 1 or len(incoming) != 1 or records != incoming
                or type(records[0][2]) is not int or type(records[0][4]) is not int
                or [str(records[0][1]), records[0][2]] != expected):
            fail(path, "UI input/link record must match the API connection")
        row = records[0]
        source = ui_node(ui, expected[0], api[expected[0]]["class_type"])
        outputs = source.get("outputs")
        if (source.get("mode", 0) != 0 or not isinstance(outputs, list) or len(outputs) <= expected[1]
                or not isinstance(outputs[expected[1]], dict)
                or not isinstance(outputs[expected[1]].get("links"), list)
                or sum(str(value) == str(row[0]) for value in outputs[expected[1]]["links"]) != 1):
            fail(path, "UI source output must match the API connection; bypass/muted sources are unsupported")


def widget(node, name, index, value):
    path = f"workflow.ui.nodes.{node['id']}"
    values = node.get("widgets_values")
    named = node.get("widgets_values_named")
    if not isinstance(values, list) or len(values) <= index:
        fail(path, f"unsupported positional widget layout for {name}")
    if named is not None:
        object_at(named, path + ".widgets_values_named")
        if name not in named or named[name] != values[index]:
            fail(path, f"named and positional {name} widgets must agree")
        named[name] = value
    values[index] = value


def scalar(value, api, path):
    if not isinstance(value, list):
        return value, None
    if not link(value) or value[0] not in api:
        fail(path, "cannot resolve setting: expected a direct scalar producer at output 0")
    node = api[value[0]]
    kind = node["class_type"]
    import nodes as comfy_nodes
    provider = getattr(comfy_nodes.NODE_CLASS_MAPPINGS.get(kind), "STATIC_VALUES", None)
    if callable(provider):
        values = provider(**node["inputs"])
        result = values.get(value[1]) if isinstance(values, dict) else None
        if type(result) not in (int, float, str, bool):
            fail(path, "static output must resolve to a scalar without model execution")
        return result, value[0]
    if value[1] != 0:
        fail(path, "cannot resolve typed primitive scalar outside output 0")
    key = "choice" if kind == "CustomCombo" else "value"
    result = node["inputs"].get(key)
    expected = str if kind == "CustomCombo" else PRIMITIVES.get(kind)
    if expected is None or type(result) is not expected:
        fail(path, "cannot resolve setting without executing its producer; use a typed literal primitive")
    return result, value[0]


def setting(key, value):
    path = "settings." + key
    if key in ("width", "height"):
        if type(value) is not int or not 32 <= value <= 16384 or value % 32:
            fail(path, "must be an integer multiple of 32 between 32 and 16384 (cannot resolve another type)")
    elif key == "context_frames":
        if type(value) is str and value in timing.CONTEXT_OPTIONS:
            value = int(value)
        if type(value) is not int or str(value) not in timing.CONTEXT_OPTIONS:
            fail(path, "must be " + ", ".join(timing.CONTEXT_OPTIONS[:-1]) + " or " + timing.CONTEXT_OPTIONS[-1])
    elif key == "carry_audio":
        if type(value) is not bool:
            fail(path, "must be a boolean")
    elif key == 'audio_context_frames':
        if type(value) is not int or value < 0:
            fail(path, 'must be a nonnegative integer; 0 follows video context')
    elif value not in ("match", "max"):
        fail(path, "must be match or max")
    return value


def settings_for(body, workflow, inputs, ui):
    requested = object_at(body.get("settings", {}), "settings")
    bindings = object_at(workflow.get("settings_bindings", {}), "workflow.settings_bindings")
    unknown = set(requested) - DEFAULTS.keys()
    if unknown:
        fail("settings", "unknown settings: " + ", ".join(sorted(unknown)))
    result, writes, demands = {}, {}, {}
    for key, default in DEFAULTS.items():
        path = "settings." + key
        raw = inputs.get(key, default)
        current, source = scalar(raw, workflow["api"], path)
        current = setting(key, current)
        value = setting(key, requested.get(key, current))
        result[key] = value
        if source:
            producer = workflow["api"][source]
            import nodes as comfy_nodes
            if callable(getattr(comfy_nodes.NODE_CLASS_MAPPINGS.get(producer["class_type"]), "STATIC_VALUES", None)):
                if value != current:
                    fail(path, "immutable static configuration output cannot be overridden; save a new workflow")
                continue
            if ui is not None:
                node = ui_node(ui, source, producer["class_type"])
                if producer["class_type"] == "CustomCombo":
                    fail(f"workflow.ui.nodes.{source}", "CustomCombo UI is unsupported in version 1; use API-only or a literal/primitive control")
                ui_connections(ui, node, workflow["api"], ["value"])
            expected = PRIMITIVES.get(producer["class_type"], str)
            literal = str(value) if expected is str and key == "context_frames" else value
            if source in demands and demands[source] != literal:
                fail(path, "conflicting setting values share the same producer")
            demands[source] = literal
            if ui is not None and producer["class_type"] == "PrimitiveInt":
                node = ui_node(ui, source, "PrimitiveInt")
                values = node.get("widgets_values")
                named = object_at(node.get("widgets_values_named", {}), f"workflow.ui.nodes.{source}.widgets_values_named")
                if (not isinstance(values, list) or len(values) != 2 or values[1] != "fixed"
                        or named.get("control_after_generate", "fixed") != "fixed"):
                    fail(f"workflow.ui.nodes.{source}", "PrimitiveInt control_after_generate must be fixed")
            if value == current:
                if ui is not None and producer["class_type"] in PRIMITIVES:
                    node = ui_node(ui, source, producer["class_type"])
                    values = node.get("widgets_values")
                    if not isinstance(values, list) or not values or values[0] != producer["inputs"]["value"]:
                        fail(f"workflow.ui.nodes.{source}", "unchanged primitive UI must match its API value")
                    widget(node, "value", 0, values[0])
                continue
            binding = bindings.get(key)
            if (not isinstance(binding, dict) or binding.get("node") != source or binding.get("input") != "value"
                    or producer["class_type"] not in PRIMITIVES):
                fail(path, "unequal linked override needs workflow.settings_bindings naming the exact primitive value")
            if type(literal) is not expected:
                fail(path, "override must match the linked primitive's literal type")
            if source in writes and writes[source] != literal:
                fail(path, "conflicting setting writes to the same primitive")
            writes[source] = literal
        else:
            inputs[key] = str(value) if key == "context_frames" else value
    for source, value in writes.items():
        producer = workflow["api"][source]
        producer["inputs"]["value"] = value
        if ui is not None:
            widget(ui_node(ui, source, producer["class_type"]), "value", 0, value)
    return result


def descriptor(file, path):
    checked(path, rules.audio_file, file)
    subfolder = file.get("subfolder", "").replace("\\", "/")
    if ntpath.splitdrive(subfolder)[0] or subfolder.startswith("/") or any(part == ".." for part in subfolder.split("/")):
        fail(path, "file must stay inside its ComfyUI folder")
    root = folder_paths.get_directory_by_type(file["type"])
    if not root:
        fail(path, "ComfyUI file root is unavailable")
    root = os.path.realpath(root)
    resolved = os.path.realpath(os.path.join(root, subfolder, file["filename"]))
    try:
        contained = os.path.commonpath((root, resolved)) == root
    except ValueError:
        contained = False
    if not contained:
        fail(path, "file must stay inside its ComfyUI folder")
    if not os.path.isfile(resolved):
        fail(path, "file is missing: " + file["filename"])
    file["subfolder"] = subfolder
    return resolved


def unique(items, key, value, path):
    if not isinstance(items, list):
        fail(path, "selector collection must be a list")
    found = [item for item in items if isinstance(item, dict) and item.get(key) == value]
    if len(found) != 1:
        fail(path, f"selector must identify one unique {key}: {value!r}")
    return found[0]


def assets_for(assets, line, workflow, inputs, ui, context=39):
    if not isinstance(assets, list):
        fail("assets", "must be a list")
    # Verify every byte before applying any caller-owned destination patch.
    for i, asset in enumerate(assets):
        path = f"assets.{i}"
        object_at(asset, path)
        file = asset.get("file")
        resolved = descriptor(file, path + ".file")
        digest = asset.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
            fail(path + ".sha256", "must be a 64 digit SHA-256 hex digest")
        try:
            with open(resolved, "rb") as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
        except OSError:
            fail(path + ".file", "could not read verified asset bytes")
        if actual != digest.lower():
            fail(path + ".sha256", "does not match the staged file bytes")
        asset["sha256"] = actual
        if not isinstance(asset.get("bindings"), list) or not asset["bindings"]:
            fail(path + ".bindings", "must contain at least one explicit destination")
    destinations = set()
    for i, asset in enumerate(assets):
        file = asset["file"]
        for j, binding in enumerate(asset["bindings"]):
            path = f"assets.{i}.bindings.{j}"
            object_at(binding, path)
            kind = binding.get("kind")
            if kind == "loader":
                source, field, slot = binding.get("node"), binding.get("input"), binding.get("slot")
                node = workflow["api"].get(source) if isinstance(source, str) else None
                pair = LOADERS.get(node["class_type"]) if node else None
                if not pair or field != pair[0] or slot not in (rules.IMAGE_SLOTS if pair[1] == "image" else rules.AUDIO_SLOTS):
                    fail(path, "loader requires a supported class/input and matching image/audio slot")
                socket = ("images." if pair[1] == "image" else "audios.") + slot
                if inputs.get(socket) != [source, 0]:
                    fail(path, "slot must link directly to the supplied loader at output 0")
                if isinstance(node["inputs"].get(field), list):
                    fail(path, "loader input must be a literal; cannot detach its link")
                if ui is not None:
                    ui_connections(ui, ui_node(ui, source, node["class_type"]), workflow["api"], [field])
                target, key, identity = node["inputs"], field, (kind, source, field)
                value = "/".join(part for part in (file["subfolder"], file["filename"]) if part) + f" [{file['type']}]"
            elif kind in ("audio_clip", "voice_clip"):
                target = unique(line.get("audio_clips" if kind == "audio_clip" else "voice_clips", []), "slot", binding.get("slot"), path)
                key, identity, value = "file", (kind, binding.get("slot")), copy.deepcopy(file)
            elif kind == "plate":
                checked(path, rules.preview_file, file)
                target = unique(line.get("plates", []), "id", binding.get("id"), path)
                key, identity, value = "image", (kind, binding.get("id")), copy.deepcopy(file)
            elif kind == "guide":
                checked(path, rules.preview_file, file)
                box = unique(line.get("boxes", []), "id", binding.get("box"), path)
                if 'target' in binding:
                    if 'shot' in binding:
                        fail(path, 'guide binding must choose target or legacy shot')
                    selected = checked(path, rules._preview_target, binding['target'], 1)
                    binding['target'] = selected
                    matches = [item for item in box.get('previews', []) if 'target' in item
                               and checked(path, rules._preview_target, item['target'], 1) == selected]
                    if len(matches) != 1:
                        fail(path, 'guide target must identify one saved preview')
                    target = matches[0]
                else:
                    if type(binding.get("shot")) is not int or binding["shot"] < 1:
                        fail(path, "guide shot must be a positive integer")
                    target = unique(box.get("previews", []), "shot", binding["shot"], path)
                    selected = {'kind': 'first'} if binding['shot'] == 1 else {'kind': 'shot', 'shot': binding['shot']}
                if selected['kind'] == 'last':
                    index = line['boxes'].index(box)
                    parsed = checked(path, rules.parse, compact(line))
                    frames, carried = checked(path, rules.box_length, parsed, index, context)
                    if frames - (0 if carried else 1) == 0:
                        selected = {'kind': 'first'}
                key, identity, value = "guide", (kind, binding.get("box"), compact(selected)), copy.deepcopy(file)
            elif kind == 'candidate':
                checked(path, rules.preview_file, file)
                if (not all(isinstance(binding.get(field), str) and binding[field] for field in ('request_id', 'prompt_id'))
                        or type(binding.get('batch_index')) is not int or binding['batch_index'] < 0):
                    fail(path, 'candidate needs request_id, prompt_id and nonnegative batch_index')
                identity = (kind, binding['request_id'], binding['prompt_id'], binding['batch_index'])
                if identity in destinations:
                    fail(path, 'duplicate destination write')
                destinations.add(identity)
                images = [image for box in line.get('boxes', []) for preview in box.get('previews', [])
                          for image in preview.get('images', [])]
                images += [image for receipt in line.get('still_requests', []) for image in receipt.get('images', [])]
                preparation = line.get('reference_preparation') or {}
                images += [image for asset in preparation.get('assets', []) for image in asset.get('candidates', [])]
                images += [image for receipt in preparation.get('requests', []) for image in receipt.get('images', [])]
                matches = [image for image in images if isinstance(image, dict) and all(
                    image.get(field) == binding[field] for field in ('request_id', 'prompt_id', 'batch_index'))]
                if not matches:
                    fail(path, 'candidate must identify saved preview or receipt metadata')
                for image in matches:
                    image['file'] = copy.deepcopy(file)
                continue
            elif kind == "picture":
                slot = binding.get("slot")
                if not rules.is_studio_slot(slot):
                    fail(path, "picture binding needs a saved slot from image17 up")
                pictures = line.setdefault("pictures", [])
                target = next((item for item in pictures if isinstance(item, dict) and item.get("slot") == slot), None)
                if target is None:
                    target = {"slot": slot}
                    pictures.append(target)
                if binding.get("title") is not None:
                    target["title"] = binding["title"]
                key, identity, value = "file", (kind, slot), copy.deepcopy(file)
            elif kind == 'reference_replacement':
                slot = binding.get('slot')
                if not reference_replacements.kind(slot):
                    fail(path, 'reference_replacement needs a canonical reference slot')
                target = line.setdefault('reference_replacements', {}).setdefault(slot, {})
                target.clear()
                key, identity, value = 'file', (kind, slot), dict(file)
            else:
                fail(path, "kind must be loader, audio_clip, voice_clip, plate, guide, candidate, picture or reference_replacement")
            if identity in destinations:
                fail(path, "duplicate destination write")
            destinations.add(identity)
            if kind in ("plate", "guide"):
                old = target.get(key)
                if isinstance(old, dict) and all(old.get(k, "") == value.get(k, "") for k in ("type", "subfolder", "filename")):
                    value = dict(old, **value)
                checked(path, rules.preview_file, value)
            target[key] = value
            if kind == "loader" and ui is not None:
                widget(ui_node(ui, source, node["class_type"]), field, 0, value)
    return assets


def normalize(line):
    text = compact(line)
    try:
        parsed = rules.parse(text)
    except rules.BridgeError as error:
        fail(f"timeline.bridges.{error.index}", str(error))
    except ValueError as error:
        fail("timeline", str(error))
    line["version"], line["prompt"] = 1, parsed.prompt
    for index, (raw, box) in enumerate(zip(line.setdefault("boxes", []), parsed.boxes)):
        if raw.get("source") is not None and not is_story_source(raw["source"]):
            fail(f"timeline.boxes.{index}.source",
                 "source is reserved for what H3's Story wrote for a box; keep your own metadata under another key")
        # The dataclass owns recognized normalization, the dictionary owns opaque consumer fields.
        normalized = dataclasses.asdict(box)
        if not box.flf_refmods:
            normalized.pop("flf_refmods")
            raw.pop("flf_refmods", None)
        raw.update(normalized)
    if parsed.timed_text is not None:
        line["timed_text"] = dict(line["timed_text"], **parsed.timed_text)
    for key in ("plates", "audio_clips", "refmods", "disabled_refs", "reference_descriptions", "bridges"):
        if key in line:
            line[key] = copy.deepcopy(parsed.all_bridges if key == "bridges" else getattr(parsed, key))
    return parsed


def connected(inputs, api, prefix, allowed):
    result = set()
    for key, value in inputs.items():
        if not key.startswith(prefix):
            continue
        slot = key[len(prefix):]
        if slot not in allowed or not link(value) or value[0] not in api:
            fail("workflow.api", f"{key} must be a valid connected flat reference link")
        result.add(slot)
    return result


def verify_text_audio(parsed, assets, inputs, attachment=None):
    if attachment is None and parsed.text_lanes:
        for lane in parsed.text_lanes:
            verify_text_audio(parsed,assets,inputs,lane['attachment'])
        return
    attachment = parsed.timed_text if attachment is None else attachment
    if attachment is None or "audio_sha256" not in attachment:
        return
    slot = attachment["audio_slot"]
    clip = next((clip for clip in parsed.audio_clips if clip["slot"] == slot), {})
    digest = None
    for asset in assets:
        for binding in asset["bindings"]:
            if "file" in clip:
                selected = binding["kind"] == "audio_clip" and binding["slot"] == slot
            else:
                selected = (binding["kind"] == "loader" and binding["input"] == "audio"
                            and inputs.get("audios." + slot) == [binding["node"], 0])
            if selected:
                digest = asset["sha256"]
    path = "timeline.timed_text.audio_sha256"
    if digest is None:
        fail(path, f"cannot verify {slot} source; supply an asset bound to its audio clip or direct LoadAudio source")
    if attachment["audio_sha256"].lower() != digest:
        fail(path, f"does not match the verified {slot} source bytes")


def semantic_for(entries, line, parsed, settings, images, audios):
    object_at(entries, "semantic_boxes")
    for box_id, entry in entries.items():
        path = "semantic_boxes." + box_id
        box = unique(line["boxes"], "id", box_id, path)
        if box["prompt"].strip():
            fail(path, "native box prompt and semantic authoring are mutually exclusive")
        object_at(entry, path)
        if type(entry.get("version")) is not int or entry["version"] != ir.VERSION:
            fail(path + ".version", "must be 1")
        selected = entry.get("references", [])
        if (not isinstance(selected, list) or any(not isinstance(name, str) or name not in images | audios for name in selected)):
            fail(path + ".references", "must name connected image/video/video_audio/audio slots")
        index = line["boxes"].index(box)
        boxes = list(parsed.boxes)
        boxes[index] = dataclasses.replace(boxes[index], prompt=" ".join("@" + name for name in selected))
        slots = rules.box_slots(dataclasses.replace(parsed, boxes=boxes), index)
        frames, carried = checked(path, rules.box_length, parsed, index, settings["context_frames"])
        mode = "Ref2VA" if slots.mode == "ref2va" else "FL2VA" if slots.first and slots.last else "I2VA" if slots.first else "L2VA" if slots.last else "T2VA"
        context = ir.PromptContext(mode, slots, frames + carried, carried)
        box["prompt"] = checked(path + ".prompt", compiler.compile_prompt, entry.get("prompt"), context, entry.get("analysis"))


def fingerprint_input(value):
    """Ignore bookkeeping; creative strings stay verbatim even when they look like paths."""
    if isinstance(value, dict):
        return {key: fingerprint_input(item) for key, item in value.items()
                if key not in ("timestamp", "timestamps", "created_at", "updated_at")
                and not (key in ("path", "local_path", "absolute_path") and isinstance(item, str)
                         and (ntpath.isabs(item) or os.path.isabs(item)))}
    if isinstance(value, list):
        return [fingerprint_input(item) for item in value]
    return value


def _prepare(body):
    object_at(body, "$")
    if type(body.get("version")) is not int or body["version"] != 1:
        fail("version", "must be 1")
    if not isinstance(body.get("name"), str):
        fail("name", "must be a safe sequence name")
    name = checked("name", validate_name, body["name"])
    line = object_at(body.get("timeline"), "timeline")
    for key in ("boxes", "plates", "audio_clips", "pictures"):
        if key in line and not isinstance(line[key], list):
            fail("timeline." + key, "must be a list")
    workflow = object_at(body.get("workflow"), "workflow")
    api = object_at(workflow.get("api"), "workflow.api")
    target = workflow.get("timeline_node")
    if not isinstance(target, str) or target not in api:
        fail("workflow.timeline_node", "must identify an existing API node")
    for node_id, node in api.items():
        object_at(node, "workflow.api." + node_id)
        if not isinstance(node.get("class_type"), str):
            fail("workflow.api." + node_id, "must have class_type")
        object_at(node.get("inputs"), "workflow.api." + node_id + ".inputs")
        for value in node["inputs"].values():
            if link(value) and value[0] not in api:
                fail("workflow.api." + node_id, "link source is missing from API graph")
    if api[target]["class_type"] != "H3C_Timeline":
        fail("workflow.timeline_node", "must identify H3C_Timeline")
    inputs = api[target]["inputs"]
    for key in ("name", "timeline"):
        if isinstance(inputs.get(key), list):
            fail("workflow.api." + target + ".inputs." + key, "must be literal; preparation cannot detach a link")
    ui = workflow.get("ui")
    if ui is not None:
        object_at(ui, "workflow.ui")
        definitions = object_at(ui.get("definitions", {}), "workflow.ui.definitions")
        if (not isinstance(ui.get("nodes"), list) or any(not isinstance(n, dict) for n in ui["nodes"])
                or definitions.get("subgraphs") or ui.get("subgraphs")):
            fail("workflow.ui", "only current root flat workflows are supported; subgraphs are unsupported")
        node = ui_node(ui, target, "H3C_Timeline")
        values = node.get("widgets_values")
        if (not isinstance(values, list) or len(values) not in (7, 8) or not isinstance(values[0], str)
                or type(values[1]) is not int or type(values[2]) is not int or values[3] not in timing.CONTEXT_OPTIONS
                or type(values[4]) is not bool or values[5] not in ("match", "max") or not isinstance(values[6], str)
                or (len(values) == 8 and (type(values[7]) is not int or values[7] < 0))):
            fail(f"workflow.ui.nodes.{target}", "unsupported Timeline widget layout; expected seven widgets or optional audio context")
        if node.get("mode", 0) != 0:
            fail(f"workflow.ui.nodes.{target}", "bypass/muted Timeline UI is unsupported")
        owned = set(WIDGETS) | {key for key in inputs if key.startswith(("images.", "audios.", "videos.", "video_audios."))}
        if isinstance(node.get("inputs", []), list):
            owned.update(item["name"] for item in node.get("inputs", []) if isinstance(item, dict)
                         and isinstance(item.get("name"), str) and item["name"].startswith(("images.", "audios.", "videos.", "video_audios.")))
        ui_connections(ui, node, api, sorted(owned))
    settings = settings_for(body, workflow, inputs, ui)
    assets = assets_for(body.get("assets", []), line, workflow, inputs, ui, settings["context_frames"])
    parsed = normalize(line)
    images = connected(inputs, api, "images.", rules.IMAGE_SLOTS)
    audios = connected(inputs, api, "audios.", rules.AUDIO_SLOTS)
    images |= connected(inputs, api, "videos.", rules.VIDEO_SLOTS)
    audios |= connected(inputs, api, "video_audios.", rules.VIDEO_AUDIO_SLOTS)
    verify_text_audio(parsed, assets, inputs)
    replacements = reference_replacements.effective(parsed)
    sources = {reference_replacements.origin(slot, replacements).get('source') for slot in replacements
               if not rules.reference_disabled(slot, parsed.disabled_refs)}
    for clip in parsed.audio_clips:
        slot = clip["slot"]
        if slot in replacements:
            continue
        if slot in parsed.disabled_refs and slot not in sources:
            continue
        if "file" in clip:
            if slot in audios:
                fail("timeline.audio_clips." + slot, "has both a file and a connected audio socket")
            audios.add(slot)
        elif slot not in audios:
            fail("timeline.audio_clips." + slot, "needs its connected audio socket or a file")
    images |= {picture["slot"] for picture in parsed.pictures}
    audios |= {clip["slot"] for clip in parsed.voice_clips}
    reference_replacements.refmods(parsed)
    for ref in parsed.refmods:
        if ref.get('strength', 1) > 0 and not rules.reference_disabled(ref['slot'], parsed.disabled_refs) and ref['slot'] in images | audios and ref['slot'] not in parsed.reference_replacements:
            fail('timeline.refmods', ref['slot'] + ' has both a RefMod and connected input')
    source_values = {name: name for name in images | audios}
    source_values.update({ref['slot']: ref for ref in parsed.refmods})
    def replacement_file(target, file):
        path = 'timeline.reference_replacements.' + target + '.file'
        resolved = descriptor(file, path)
        with open(resolved, 'rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if not any(asset['file'] == file and asset['sha256'] == digest for asset in assets):
            assets.append(dict(file=dict(file), sha256=digest, bindings=[dict(kind='reference_replacement', slot=target)]))
        return target
    resolved = checked('timeline.reference_replacements', reference_replacements.resolve, parsed, source_values, replacement_file)
    images = {name for name, value in resolved.items() if not isinstance(value, dict) and reference_replacements.kind(name) in ('image', 'video')
              and not rules.reference_disabled(name, parsed.disabled_refs)}
    audios = {name for name, value in resolved.items() if not isinstance(value, dict) and reference_replacements.kind(name) in ('audio', 'video_audio')
              and not rules.reference_disabled(name, parsed.disabled_refs)}
    for ref in parsed.refmods:
        if ref.get("strength", 1) > 0 and ref["slot"] not in parsed.disabled_refs and ref["slot"] in images | audios:
            fail("timeline.refmods", ref["slot"] + " has both a RefMod and connected input")
    semantic_for(body.get("semantic_boxes", {}), line, parsed, settings, images, audios)
    parsed = normalize(line)
    reference_replacements.refmods(parsed)
    boxes = []
    for index, box in enumerate(parsed.boxes):
        path = f"timeline.boxes.{index}"
        guides = checked(path, rules.frame_guides, parsed, index, settings["context_frames"])
        slots = rules.box_slots(parsed, index)
        plates = {slot: plate for slot, plate in rules.effective_plates(parsed, index).items()
                  if slot in slots.references and slot not in (slots.first, slots.last)}
        for plate in plates.values():
            checked(path, timed_text.check_anchor, plate["image"], rules.frame_text(parsed, index, 0, settings["context_frames"]), "plate")
        box_audios = (audios - {clip["slot"] for clip in parsed.audio_clips}) | {
            clip["slot"] for clip in rules.active_audio_clips(parsed, index, settings['context_frames'])}
        plan = checked(path, rules.plan_box, parsed, index, settings["context_frames"], settings["carry_audio"],
                       settings["width"], settings["height"], settings["ref_image_size"], images | set(plates), box_audios,
                       audio_context_frames=settings['audio_context_frames'])
        start = round(rules.box_start(parsed, index) * 24)
        boxes.append(dict(id=box.id, index=index + 1, mode=plan.slots.mode, tags=plan.slots.tags,
                          frames=plan.frames, carried=plan.carried, generated=plan.generated,
                          delivered_range=[start, start + plan.frames],
                          generated_range=[start - plan.carried, start - plan.carried + plan.generated],
                          carry_range=[start - plan.carried, start], effective_prompt=plan.prompt,
                          text_window=plan.text_window, guides=[dict(frame=frame, file=file) for frame, file in guides], notes=plan.notes))
    inputs["name"], inputs["timeline"] = name, compact(line)
    if ui is not None:
        node = ui_node(ui, target, "H3C_Timeline")
        for index, key in enumerate(WIDGETS):
            value = name if key == "name" else inputs["timeline"] if key == "timeline" else settings[key]
            if key == 'audio_context_frames' and isinstance(node.get('widgets_values'), list) and len(node['widgets_values']) == index:
                node['widgets_values'].append(value)
                if node.get('widgets_values_named') is not None:
                    node['widgets_values_named'][key] = value
            widget(node, key, index, str(value) if key == "context_frames" else value)
    revisions = dict(preparation=REVISION, schema=ir.VERSION, guidance=ir.GUIDELINE_REVISION)
    ordered_assets = sorted(assets, key=lambda asset: compact(asset["file"]))
    for asset in ordered_assets:
        asset["bindings"].sort(key=compact)
    video_line = copy.deepcopy(line)
    video_line.pop('still_requests', None)
    for index, box in enumerate(video_line['boxes']):
        previews = [{key: copy.deepcopy(item[key]) for key in ('shot', 'target', 'frame', 'guide') if key in item}
                    for item in rules.resolved_previews(parsed, index, settings['context_frames']) if item.get('guide')]
        if previews: box['previews'] = previews
        else: box.pop('previews', None)
    video_assets = [{**asset, 'bindings': [binding for binding in asset['bindings'] if binding['kind'] != 'candidate']}
                    for asset in ordered_assets if any(binding['kind'] != 'candidate' for binding in asset['bindings'])]
    identity = dict(name=name, timeline=video_line, settings=settings, api=api, assets=video_assets, revisions=revisions)
    identity = fingerprint_input(identity)
    # Timeline is serialized for ComfyUI, but hashed as data so provenance exclusions apply once.
    identity["api"][target]["inputs"]["timeline"] = identity["timeline"]
    fingerprint = hashlib.sha256(compact(identity).encode("utf-8")).hexdigest()
    return dict(ok=True, version=1, name=name, timeline=line, settings=settings, workflow=workflow,
                assets=ordered_assets, boxes=boxes, revisions=revisions, fingerprint=fingerprint)


def prepare(body):
    """Return an owned prepared contract, or precise data errors. This function only reads asset bytes."""
    try:
        # Check the JSON boundary before copying, including nonfinite numeric values.
        compact(body)
        return _prepare(copy.deepcopy(body))
    except Invalid as error:
        return {"ok": False, "errors": [{"path": error.path, "message": str(error)}]}
    except (TypeError, ValueError):
        return {"ok": False, "errors": [{"path": "$", "message": "request must contain valid JSON values"}]}

# static-configuration-interop-v1

# captured-api-delivery-v2
