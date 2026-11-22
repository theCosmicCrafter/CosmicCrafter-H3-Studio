"""Reads the snapshot Write posts (the frontend's API prompt): the story node, its Timeline, the references, the
text inputs, the descriptions and the boxes to write. Puts in the texts that ComfyUI gave for the inputs Write had to
run nodes for."""

import copy
import dataclasses
import hashlib
import json
import os
import re

import folder_paths

from . import nodes as continuity
from . import store, story_bible, story_keys, story_lengths, story_templates, timing, refmods, timed_text, studio_pictures
from . import reference_replacements
from . import story_prompts as prompts
from . import timeline as rules
from .timeline_node import request_status

STORY_TYPE = "H3C_Story"
TIMELINE_TYPE = "H3C_Timeline"
TEXT_TYPES = ("PrimitiveString", "PrimitiveStringMultiline")
CONCAT_TYPE = "StringConcatenate"
CUSTOM_COMBO = "CustomCombo"
PICTURE_TYPES = ("LoadImage", "LoadImageOutput")
MAX_DEPTH = 32
SCOPES = ("empty boxes", "every unrendered box")
THINKING = ("off", "minimal", "low", "medium", "high", "xhigh", "max")
TEXT_INPUTS = ("idea", "guide", "base_url", "model", "thinking", "vision_base_url", "vision_model", "story_thinking",
               "story_model", "story_base_url")
STORY_SETTINGS = ("pictures", "scope", "free_vram", "total_seconds")
TIMELINE_SETTINGS = ("width", "height", "carry_audio", "ref_image_size")
REFERENCE_INPUT = re.compile(r"(?:images\.|audios\.|videos\.|video_audios\.)?(image|audio|video_audio|video)(\d+)")
DESCRIPTION_INPUT = re.compile(r"descriptions\.(image|audio|video_audio|video)(\d+)")
SUBGRAPH = "Move the story node and its Timeline out of the subgraph."
EMPTY = "The description of {label} came back empty, so Write left it out."
TEMPLATE_LINKED = "Choose the template on the Studio's Story page; the story node's template input can't be linked."
TEMPLATE_MISSING = ("The template {id} isn't in the template folder any more. Put it back in {folder}, or choose "
                    "another template on the Story page.")
TEMPLATE_PROBLEM = "The template {id} can't be used. {problem}"
TEMPLATE_NOTE = "Template: {name}, {characters:,} characters."


def _link(value):
    return isinstance(value, list) and len(value) == 2 and isinstance(value[1], int)


def read_text(prompt, value, depth=0):
    """How a text input gets its text: ("text", text) when only Text, Text (Multiline) and Concatenate Text nodes and
    Custom Combo's choice are on the way; ("run", node) at the first other node, Custom Combo's INDEX output
    included, or ("run", None) past MAX_DEPTH nodes; ("muted", None) when a node on the way is muted or bypassed."""
    if isinstance(value, str):
        return "text", value
    if not _link(value):
        return "text", ""
    node = prompt.get(str(value[0]))
    if not isinstance(node, dict):
        return "muted", None
    if depth >= MAX_DEPTH:
        return "run", None
    kind, inputs = node.get("class_type"), node.get("inputs") or {}
    if kind in TEXT_TYPES:
        return read_text(prompt, inputs.get("value", ""), depth + 1)
    if kind == CUSTOM_COMBO and value[1] == 0:
        return read_text(prompt, inputs.get("choice", ""), depth + 1)
    if kind != CONCAT_TYPE:
        return "run", node
    parts = [read_text(prompt, inputs.get(key, ""), depth + 1) for key in ("string_a", "delimiter", "string_b")]
    for way in ("muted", "run"):
        stopped = next((part for part in parts if part[0] == way), None)
        if stopped:
            return stopped
    return "text", "".join(text for _, text in parts)


def resolve_text(prompt, value, what):
    """The text of an input Write reads without running nodes, such as the Timeline's name: a literal, or the output
    of Text, Text (Multiline), Concatenate Text and Custom Combo nodes."""
    if not isinstance(value, str) and not _link(value):
        raise ValueError(f"The {what} must be text.")
    way, found = read_text(prompt, value)
    if way == "muted":
        raise ValueError(f"The {what} comes from a node that is muted or bypassed.")
    if way == "run" and found is None:
        raise ValueError(f"The {what} goes through more than {MAX_DEPTH} text nodes.")
    if way == "run":
        kind = found.get("class_type")
        title = (found.get("_meta") or {}).get("title") or kind
        raise ValueError(f"The {what} comes from '{title}' ({kind}), which Write can't read. Use Text, Text "
                         "(Multiline), Concatenate Text or Custom Combo nodes.")
    return found


def find_nodes(prompt, story_id):
    """(story node, Timeline id, Timeline node) for story node `story_id`."""
    story_id = str(story_id or "")
    if ":" in story_id:
        raise ValueError(SUBGRAPH)
    story = prompt.get(story_id)
    if not isinstance(story, dict) or story.get("class_type") != STORY_TYPE:
        raise ValueError("The story node is muted or bypassed.")
    linked = [node_id for node_id, node in prompt.items()
              if isinstance(node, dict) and node.get("class_type") == TIMELINE_TYPE
              and _link((node.get("inputs") or {}).get("story")) and str(node["inputs"]["story"][0]) == story_id]
    if not linked:
        raise ValueError("Link the story output to a Timeline's story input.")
    if len(linked) > 1:
        raise ValueError("Link this story node to one Timeline only.")
    if ":" in linked[0]:
        raise ValueError(SUBGRAPH)
    return story, linked[0], prompt[linked[0]]


def _saved(state):
    """The story node's state as a dict; a state that isn't a JSON object counts as {}."""
    try:
        data = json.loads(state) if isinstance(state, str) else {}
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def _written(saved):
    """The "written" map of the story node's state."""
    written = saved.get("written")
    if not isinstance(written, dict):
        return {}
    return {box_id: text for box_id, text in written.items() if isinstance(text, str)}


def _idea_images(raw):
    try:
        images = json.loads(raw)
    except (ValueError, TypeError):
        raise ValueError("Idea images must be a JSON list of ComfyUI files.") from None
    if not isinstance(images, list):
        raise ValueError("Idea images must be a JSON list of ComfyUI files.")
    found = []
    for index, item in enumerate(images, 1):
        if not isinstance(item, dict) or "file" not in item:
            raise ValueError(f"Idea image {index} needs a ComfyUI file.")
        file = rules.picture_file(item["file"])
        found.append(prompts.Reference(f"idea{index}", f"Idea image {index} ({file['filename']})",
                                       studio_pictures.path(file), dict(file)))
    return found


def _bible(text):
    """(bible, box fields, hand-edited entities by box id) of the Timeline JSON `text`, as StoryContext keeps them;
    (None, {}, {}) without a bible. Raises ValueError saying why the bible can't be used."""
    data = json.loads(text)
    if not isinstance(data, dict) or data.get("bible") is None:
        return None, {}, {}
    try:
        known = {item["id"] for item in story_bible.entities(data["bible"])}
        story_bible.held_voices(data["bible"], data)
        items = story_bible.boxes(data)
        for number, item in enumerate(items, 1):
            schedule = item.get("schedule") or {}
            for name in [*schedule.get("entities", []), *filter(None, [schedule.get("place")])]:
                if name not in known:
                    raise ValueError(f"Box {number}'s schedule names {name}, which the bible doesn't have.")
        subjects = story_bible.status(data)["subjects"]
    except ValueError as error:
        raise ValueError(f"The Timeline's bible can't be used: {error}") from None
    fields = {item["id"]: {key: copy.deepcopy(item[key]) for key in ("schedule", "join", "cast", "source")
                           if key in item} for item in items}
    edited = {}
    for item in subjects:
        if item["state"] == "differs":
            edited.setdefault(item["box"], []).append(item["entity"])
    return copy.deepcopy(data["bible"]), {key: value for key, value in fields.items() if value}, edited


def writable(prompt, written, scope):
    """Whether Write may fill a box that isn't rendered: an empty prompt, or with scope "every unrendered box" a
    prompt still equal to what Write wrote there."""
    return not prompt.strip() or (scope == SCOPES[1] and written is not None and prompt == written)


def picture_path(node):
    """The file of a Load Image node when it is inside the input, output or temp folder, else None."""
    name = (node.get("inputs") or {}).get("image")
    if node.get("class_type") not in PICTURE_TYPES or not isinstance(name, str) or not name:
        return None
    try:
        path = folder_paths.get_annotated_filepath(name)
    except ValueError:
        return None
    roots = (folder_paths.get_input_directory(), folder_paths.get_output_directory(),
             folder_paths.get_temp_directory())
    if os.path.isfile(path) and any(folder_paths.is_within_directory(root, path) for root in roots):
        return path
    return None


def reference_picture_path(prompt, value, seen=frozenset()):
    """Read X2's original picture for descriptions without executing the detail VAE."""
    if not _link(value) or str(value[0]) in seen:
        return None
    node_id = str(value[0])
    node = prompt.get(node_id) or {}
    inputs = node.get("inputs") or {}
    seen = seen | {node_id}
    if node.get("class_type") == "MiniMaxH3X2DetailedUpscale":
        return reference_picture_path(prompt, inputs.get("images"), seen)
    if node.get("class_type") == "ComfySwitchNode":
        paths = [reference_picture_path(prompt, inputs.get(name), seen) for name in ("on_false", "on_true")]
        return paths[0] if paths[0] and paths[0] == paths[1] else None
    return picture_path(node)


def references(prompt, inputs):
    """The references connected to a Timeline, images first, each in slot order."""
    found = []
    for key, value in inputs.items():
        match = REFERENCE_INPUT.fullmatch(key)
        source = prompt.get(str(value[0])) if match and _link(value) else None
        if not isinstance(source, dict):
            continue
        name = f"{match.group(1)}{int(match.group(2))}"
        title = (source.get("_meta") or {}).get("title") or source.get("class_type") or ""
        found.append(prompts.Reference(name, title, reference_picture_path(prompt, value) if match.group(1) == "image" else None))
    return sorted(found, key=lambda ref: (ref.name.startswith(("audio", "video_audio")), rules.slot_number(ref.name)))


def _descriptions(prompt, inputs, refs, refmod_slots=()):
    """(texts, links, notes) from the story node's `inputs`: `texts` maps reference names to the descriptions Write
    reads at once, `links` maps input names, such as descriptions.image2, to the links of those it runs in ComfyUI
    first, and `notes` says what it left out."""
    labels = {ref.name: ref.label for ref in refs}
    texts, links, notes = {}, {}, []
    found = sorted((match.group(1), int(match.group(2)), key) for key in inputs if (match := DESCRIPTION_INPUT.fullmatch(key)))
    for kind, number, key in found:
        name = f"{kind}{number}"
        if name in refmod_slots:
            continue
        if name not in labels:
            notes.append(f"The Timeline has no {name}, so Write left out its description.")
            continue
        way, text = read_text(prompt, inputs[key])
        if way == "muted":
            notes.append(f"The description of {labels[name]} comes from a node that is muted or bypassed, so Write "
                         "left it out.")
        elif way == "run":
            links[key] = inputs[key]
        elif text.strip():
            texts[name] = text.strip()
    return texts, links, notes


def _choice(text, *, initial=False):
    """The thinking level that `text` names, trimmed and in any case, else None."""
    text = text.strip().lower()
    if initial and text == "same as boxes":
        return text
    if text in ("on", "model default"):
        return "medium"
    return next((choice for choice in THINKING if choice == text), None)


def _template(value):
    """The template the story node's `value` names, from a fresh listing, or None without one; raises ValueError
    when Write can't use it."""
    if not isinstance(value, str):
        raise ValueError(TEMPLATE_LINKED)
    if not value.strip():
        return None
    found = story_templates.find(value)
    if found is None:
        folder = story_templates.EXAMPLES if value.startswith(story_templates.EXAMPLE) else story_templates.folder()
        raise ValueError(TEMPLATE_MISSING.format(id=value, folder=folder))
    if found.problem:
        raise ValueError(TEMPLATE_PROBLEM.format(id=value, problem=found.problem))
    return found


PH3_IMAGE_CLASS = "H3C_PH3ImageStill"
SELF_IMAGE_MODELS = {PH3_IMAGE_CLASS: 'P-H3-Image', 'H3C_MiniMaxH3ImageStill': 'MiniMax H3 Image'}


def still_recipe_node(prompt, timeline_id):
    """Resolve the selected still recipe without executing its generator or switch controls."""
    settings = (prompt.get(str(timeline_id)) or {}).get("inputs") or {}
    link = settings.get("still_recipe")
    if link is None and _link(settings.get("still_image")):
        # The user's own image workflow, connected by its IMAGE output.
        return prompt.get(str(settings["still_image"][0])) or {}
    if not _link(link):
        return {}
    node = prompt.get(str(link[0])) or {}
    switches = set()
    while node.get("class_type") == "LazySwitchKJ":
        if link[1] != 0 or str(link[0]) in switches:
            return {}
        switches.add(str(link[0]))
        inputs = node.get("inputs") or {}
        selected, controls = inputs.get("switch"), set()
        while _link(selected):
            control = prompt.get(str(selected[0])) or {}
            if selected[1] != 0 or control.get("class_type") != "PrimitiveBoolean" or str(selected[0]) in controls:
                return {}
            controls.add(str(selected[0]))
            selected = (control.get("inputs") or {}).get("value")
        if type(selected) is not bool:
            return {}
        link = inputs.get("on_true" if selected else "on_false")
        node = (prompt.get(str(link[0])) or {}) if _link(link) else {}
        if not _link(link) or link[1] != (1 if node.get("class_type") in SELF_IMAGE_MODELS else 0):
            return {}
    if node.get("class_type") in SELF_IMAGE_MODELS:
        # The P-H3-Image node is its own pixel generator; its recipe output is slot 1.
        if link[1] != 1:
            return {}
    else:
        raw = (node.get("inputs") or {}).get("bindings")
        try:
            bindings = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            return {}
        if node.get("class_type") != "H3C_StillRecipe" or not isinstance(bindings, dict) or bindings.get("adapter") != "pixels":
            return {}
    return node


NATIVE_IMAGE_MODELS = {'PH3ImageConditioning': 'P-H3-Image', 'MiniMaxH3ImageConditioning': 'MiniMax H3 Image'}


def still_model_for(prompt, timeline_id):
    node = still_recipe_node(prompt, timeline_id)
    model = SELF_IMAGE_MODELS.get(node.get('class_type'), '')
    image = ((prompt.get(str(timeline_id)) or {}).get("inputs") or {}).get("still_image")
    if model or not node or not _link(image):
        return model
    # A workflow of native nodes names its model by the conditioning node above its image output.
    seen, pending = set(), [str(image[0])]
    while pending:
        key = pending.pop()
        if key in seen:
            continue
        seen.add(key)
        current = prompt.get(key) or {}
        if current.get('class_type') in NATIVE_IMAGE_MODELS:
            return NATIVE_IMAGE_MODELS[current['class_type']]
        pending.extend(str(value[0]) for value in (current.get("inputs") or {}).values() if _link(value))
    return ''


def renderer_for(prompt, timeline_id):
    """A pixel-only Story uses image writing; a video output downstream keeps video writing."""
    if not still_recipe_node(prompt, timeline_id):
        return "video"
    def reaches(key, seen):
        key = str(key)
        if key == str(timeline_id):
            return True
        if key in seen:
            return False
        seen.add(key)
        return any(reaches(value[0], seen) for value in ((prompt.get(key) or {}).get("inputs") or {}).values()
                   if _link(value))
    video_outputs = {"H3C_SaveSegment", "SaveVideo", "VHS_VideoCombine", "SaveAnimatedWEBP", "SaveAnimatedPNG"}
    return "video" if any(node.get("class_type") in video_outputs and reaches(key, set())
                          for key, node in prompt.items() if isinstance(node, dict)) else "image"


def read(prompt, story_id, box_id=None, *, rewrite_all=False):
    """The StoryContext of story node `story_id` in the API prompt `prompt`; raises ValueError saying why Write
    can't start. The inputs Write has to run nodes for are in its links; until settle() their texts are "", and
    thinking is "model default"."""
    if not isinstance(prompt, dict):
        raise ValueError("The Write request has no workflow snapshot.")
    story, timeline_id, timeline = find_nodes(prompt, story_id)
    inputs = story.get("inputs") or {}
    if any(_link(inputs.get(key)) for key in STORY_SETTINGS):
        raise ValueError("Set pictures, scope, free_vram and total_seconds on the story node itself.")
    template = _template(inputs.get("template", ""))
    texts, links = {}, {}
    for name in TEXT_INPUTS:
        way, text = read_text(prompt, inputs.get(name, ""))
        if way == "muted":
            raise ValueError(f"The {name} comes from a node that is muted or bypassed.")
        if way == "run":
            links[name] = inputs[name]
        texts[name] = text if way == "text" else ""
    model = texts["model"].strip()
    if not model and "model" not in links:
        raise ValueError("Enter a model name.")
    base_url = texts["base_url"].strip()
    if "base_url" not in links:
        story_keys.host_of(base_url)
    idea = texts["idea"].strip()
    if not idea and "idea" not in links:
        raise ValueError("Type an idea first.")
    guide = texts["guide"]
    thinking = "medium"
    if "thinking" in inputs and "thinking" not in links:
        thinking = _choice(texts["thinking"])
        if thinking is None:
            raise ValueError("Set thinking to off, minimal, low, medium, high, xhigh or max.")
    story_thinking = "same as boxes"
    if "story_thinking" in inputs and "story_thinking" not in links:
        story_thinking = _choice(texts["story_thinking"], initial=True)
        if story_thinking is None:
            raise ValueError("Set story_thinking to same as boxes, off, minimal, low, medium, high, xhigh or max.")
    scope = inputs.get("scope") if inputs.get("scope") in SCOPES else SCOPES[0]
    total_seconds = inputs.get("total_seconds", 0)
    if (isinstance(total_seconds, bool) or not isinstance(total_seconds, int)
            or not 0 <= total_seconds <= story_lengths.MAX_TOTAL_SECONDS):
        raise ValueError(f"Set total_seconds to a whole number from 0 to {story_lengths.MAX_TOTAL_SECONDS}.")
    saved = _saved(inputs.get("state"))
    written = _written(saved)
    pictures = inputs.get("pictures", True) is not False

    settings = timeline.get("inputs") or {}
    text = settings.get("timeline")
    if not isinstance(text, str):
        raise ValueError("Write can't read the Timeline's boxes; its timeline input must not be linked.")
    parsed = rules.parse(text)
    bible, box_fields, hand_edited = _bible(text)
    context = settings.get("context_frames")
    if _link(context) or str(context) not in timing.CONTEXT_OPTIONS:
        raise ValueError("Set context_frames on the Timeline itself.")
    context = int(context)
    name = resolve_text(prompt, settings.get("name", ""), "Timeline name")
    known = {key: None if _link(settings.get(key)) else settings.get(key) for key in TIMELINE_SETTINGS}
    status = request_status({"name": name, "timeline": text, "settings": dict(known, context_frames=context)})
    if not status.get("ok"):
        raise ValueError(status.get("error") or "Write can't read the Timeline's status.")
    folder = store.sequence_dir(continuity.sequences_root(), name)
    done = {item["id"]: item for item in status["boxes"] if item["status"] == "done"}
    if not isinstance(rewrite_all, bool):
        raise ValueError("rewrite_all must be true or false.")
    statuses = ["rendered" if box.id in done else "write" if writable(box.prompt, written.get(box.id), scope)
                else "kept" for box in parsed.boxes]
    if rewrite_all:
        statuses = ["write"] * len(parsed.boxes)
        done = {}
    elif box_id is not None:
        if not isinstance(box_id, str) or box_id not in {box.id for box in parsed.boxes}:
            raise ValueError("Select an existing Timeline box to write its story.")
        statuses = ["write" if box.id == box_id else "kept" for box in parsed.boxes]
    last_frames = {box_id: os.path.join(folder, item["thumb"]["filename"])
                   for box_id, item in done.items() if item.get("thumb")}
    replacements = reference_replacements.effective(parsed)
    sources = {reference_replacements.origin(slot, replacements).get('source') for slot in replacements
               if not rules.reference_disabled(slot, parsed.disabled_refs)}
    refs = references(prompt, settings)
    for clip in parsed.audio_clips:
        if "file" in clip and any(ref.name == clip["slot"] for ref in refs):
            raise ValueError(f"{clip['slot']} has both an uploaded clip and a connected audio input.")
        if not any(ref.name == clip["slot"] for ref in refs):
            refs.append(prompts.Reference(clip["slot"], clip.get("title") or clip["slot"], None))
    refs.extend(prompts.Reference(picture["slot"], picture.get("title") or picture["file"]["filename"],
                                  studio_pictures.path(picture["file"]))
                for picture in parsed.pictures if picture['slot'] not in parsed.reference_replacements)
    refs.extend(prompts.Reference(clip['slot'], clip.get('title') or clip['file']['filename'], None)
                for clip in parsed.voice_clips if clip['slot'] in sources)
    reference_replacements.refmods(parsed)
    refmods.resolve(parsed, [ref.name for ref in refs if ref.name not in replacements])
    active_mods = [ref for ref in parsed.refmods if ref.get("strength", 1) > 0
                   and (ref['slot'] not in parsed.disabled_refs or ref['slot'] in sources)]
    refs.extend(prompts.Reference(ref["slot"], ref.get('title') or ref['name'], None) for ref in active_mods)
    source_refs = list(refs)
    def replacement_ref(target, file):
        path = reference_replacements.file_path(file, target)
        return prompts.Reference(target, file['filename'], path if target.startswith('image') else None)
    resolved = reference_replacements.resolve(parsed, {ref.name: ref for ref in refs},
                                              replacement_ref)
    refs = [dataclasses.replace(ref, name=name) for name, ref in resolved.items()
            if not rules.reference_disabled(name, parsed.disabled_refs)]
    refs.sort(key=lambda ref: (ref.name.startswith(("audio", "video_audio")), rules.slot_number(ref.name)))
    described, linked, notes = _descriptions(prompt, inputs, [*source_refs, *refs], {ref["slot"] for ref in parsed.refmods})
    for clip in parsed.audio_clips:
        if clip['slot'] not in replacements and clip.get('description', '').strip():
            described.setdefault(clip['slot'], clip['description'].strip())
    for target in replacements:
        source = reference_replacements.origin(target, replacements).get('source')
        if source in described:
            described[target] = described[source]
        else:
            described.pop(target, None)
        if source and 'descriptions.' + source in linked:
            linked['descriptions.' + target] = linked['descriptions.' + source]
    if parsed.disabled_refs:
        notes.append("Disabled references are excluded from Story and generation: " + ", ".join(parsed.disabled_refs) + ".")
    if template is not None:
        notes.append(TEMPLATE_NOTE.format(name=template.name, characters=template.characters))
    described.update({ref["slot"]: (ref.get("description") or "").strip() or ref.get('saved_description', '') for ref in active_mods})
    enabled = {ref.name for ref in refs}
    described = {slot: text for slot, text in described.items() if slot in enabled}
    linked = {key: value for key, value in linked.items() if key.removeprefix('descriptions.') in enabled}
    if texts["vision_base_url"].strip():
        story_keys.host_of(texts["vision_base_url"].strip())
    if texts["story_base_url"].strip():
        story_keys.host_of(texts["story_base_url"].strip())
    links.update(linked)
    ctx = prompts.StoryContext(
        idea=idea, guide=guide, base_url=base_url, model=model, pictures=pictures,
        shared=parsed.prompt, context_frames=context, timeline=parsed,
        boxes=prompts.story_boxes(parsed, context, statuses, last_frames),
        references=refs, timeline_id=timeline_id, story_id=str(story_id),
        free_vram=inputs.get("free_vram", True) is not False, total_seconds=total_seconds, thinking=thinking,
        story_thinking=story_thinking, story_model=texts["story_model"].strip(),
        story_base_url=texts["story_base_url"].strip(), renderer=renderer_for(prompt, timeline_id),
        image_model=still_model_for(prompt, timeline_id),
        descriptions=described, links=links, snapshot=prompt if links else {}, notes=notes,
        vision_base_url=texts["vision_base_url"].strip(), vision_model=texts["vision_model"].strip(),
        reference_descriptions=dict(parsed.reference_descriptions), bible=bible, box_fields=box_fields,
        hand_edited=hand_edited, template=template,
        idea_images=_idea_images(inputs.get("idea_images", "[]")),
        idea_descriptions={name: value for name, value in (saved.get("idea_descriptions") or {}).items()
                           if isinstance(value, dict) and isinstance(value.get("text"), str)
                           and isinstance(value.get("source"), str)}
                          if isinstance(saved.get("idea_descriptions"), dict) else {})
    if not rewrite_all and (box_id is not None or scope == SCOPES[0]):
        ctx.saved_plan = prompts.saved_plan(ctx, saved, required=box_id is not None)
    ctx.regenerate = not rewrite_all and box_id is not None
    if not ctx.planning and not ctx.targets:
        raise ValueError("Nothing to write: every box in scope is rendered or has a prompt.")
    return ctx

def settle(ctx, texts):
    """(context, notes): `ctx` with `texts`, what ComfyUI gave for each of its links by input name, checked as typed
    values are; the notes say which descriptions came back empty. Raises ValueError naming an input whose text fails
    its check."""
    values, described, notes = {}, dict(ctx.descriptions), []
    for name in ctx.links:
        text = texts.get(name, "").strip()
        match = DESCRIPTION_INPUT.fullmatch(name)
        if match:
            ref = f"{match.group(1)}{int(match.group(2))}"
            if text:
                described[ref] = text
            else:
                notes.append(EMPTY.format(label=ctx.label(ref)))
            continue
        if name in ("idea", "model") and not text:
            raise ValueError(f"The {name} input got no text.")
        if name == "base_url" or name in ("vision_base_url", "story_base_url") and text:
            try:
                story_keys.host_of(text)
            except ValueError:
                raise ValueError(f"The {name} input didn't get a URL that starts with http:// or https://.") from None
        if name in ("thinking", "story_thinking"):
            text = _choice(text, initial=name == "story_thinking")
            if text is None:
                extra = "same as boxes, " if name == "story_thinking" else ""
                raise ValueError(f"The {name} input needs {extra}off, minimal, low, medium, high, xhigh or max.")
        values[name] = text
    return dataclasses.replace(ctx, **values, descriptions=described, links={}, snapshot={}), notes


def identity(ctx):
    # Older briefs relied on the full idea being repeated to each writer; replan them on ordinary Write.
    key = ['scheduled-stages-v1' if ctx.renderer != 'image' else 'self-contained-beats-v1',
           ctx.guide, ctx.idea, ctx.shared, ctx.initial_model, ctx.initial_base_url]
    if ctx.renderer == 'image':
        key.append('image-snapshots-v1')
        if ctx.image_model:
            key.append(['still-model-instructions-v1', ctx.image_model])
    if ctx.timeline.timed_text is not None:
        key.append(timed_text.snapshot(ctx.timeline.timed_text, ctx.timeline.audio_clips, rules.resolved_audio(ctx.timeline)))
    if ctx.timeline.reference_replacements:
        key.append(ctx.timeline.reference_replacements)
    if ctx.template is not None:
        key.append(["template", ctx.template.text])
    if ctx.idea_images:
        key.append(["idea-reference-guidance-v1", [(ref.path, ctx.idea_descriptions.get(ref.name)) for ref in ctx.idea_images],
                    [(ref.name, ctx.idea_references.get(ref.name)) for ref in ctx.idea_images],
                    ctx.pictures, ctx.vision_base_url, ctx.vision_model])
    return hashlib.sha256(json.dumps(key, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
