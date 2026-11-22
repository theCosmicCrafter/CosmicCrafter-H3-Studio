"""Writing with the Story bible: the planner and the writer work from the Timeline's bible, and each box's prompt is
compiled from its stored source and the bible. Timelines with boxes and no bible never come here."""
import copy
import json
import re
from dataclasses import dataclass, field

from . import story_bible, story_fast, story_stages, story_instructions as instructions
from . import story_prompts as prompts, timeline as rules
from . import h3_prompt_compile as compiler, h3_prompt_ir as prompt_ir
from . import h3_prompt_schema as prompt_schema, h3_prompt_validate as validate

ENTITY = re.compile(r"\be[1-9]\d*\b")
# A planner pointing at a picture in a description, like "as shown in image1"; code binds the pictures itself.
PICTURE = re.compile(r",?\s*\b(?:as\s+)?(?:(?:shown|seen|pictured|depicted)\s+)?(?:in|from|on)\s+@?image\d+\b", re.I)

LOOKS = ("Name each look in a few words in every shot that shows its entity with it, where the shot first mentions the "
         "entity, even though its description has it too: the video follows the shots more than the descriptions. "
         "Return no subject update for a look unless this box changes it.")
REASONS = {"continue": "the box continues the one before", "cut": "the box is a cut within the scene",
           "new_scene": "the box starts a new scene"}


@dataclass
class Planned:
    """What a plan does to the bible: the bible with the entities it adds, each box's schedule by box index, the join
    of each box after the first by box index, and what Write changed in the plan's joins."""
    bible: dict
    schedules: dict
    joins: dict
    notes: list


@dataclass
class Work:
    """What the boxes of one Write share."""
    bible: dict                                  # the working bible
    schedules: dict                              # box index: schedule
    joins: dict                                  # box index: join
    fields: dict = field(default_factory=dict)   # box id: the fields Write gives it
    replies: dict = field(default_factory=dict)  # box id: the reply Write compiled for it


def uses_bible(ctx):
    """Whether Write takes the bible path: the Timeline has a bible, or Write plans an empty Timeline."""
    return ctx.bible is not None or ctx.planning


def _sentence(text):
    text = text.strip()
    return text if not text or text.endswith((".", "!", "?")) else text + "."


def _flags(box, join=None):
    return {"cut": box.cut, "new_scene": box.new_scene, "join": join}


def _pictures(slots):
    return f"Pictures: {', '.join('@' + slot for slot in slots)}."


def _entity_line(entity):
    pictures = _pictures(entity["pictures"]) if entity["pictures"] else "No picture."
    voice = (entity.get("voice") or "").strip().rstrip(".")
    return (f"{entity['id']} · {entity['kind']} · {entity['name']}: "
            f"{_sentence(entity['description']) or '(no description)'} {pictures}"
            + (f" Voice: {voice}." if voice else ""))


def _bible_lines(ctx):
    """The bible as the planner reads it: each entity with its looks, the style, and the boxes' saved schedules and
    joins."""
    entities = (ctx.bible or {}).get("entities") or []
    ids = [box.id for box in ctx.boxes]
    names = {entity["id"]: entity["name"] for entity in entities}
    lines = ["Bible:"] if entities else ["Bible: empty; the cast you plan becomes it."]
    for entity in entities:
        lines.append(_entity_line(entity))
        lines += [f"  From box {ids.index(look['from']) + 1}: {look['description'].strip()}"
                  + (f" {_pictures(look['pictures'])}" if look.get("pictures") else "")
                  for look in entity["looks"] if look["from"] in ids]
    if story_bible.style(ctx.bible).strip():
        lines.append(f"Style of every box: {story_bible.style(ctx.bible).strip()}")
    for box in ctx.boxes:
        fields = ctx.box_fields.get(box.id, {})
        if "schedule" in fields:
            who = ", ".join(names[name] for name in fields["schedule"]["entities"]) or "no one"
            place = fields["schedule"].get("place")
            lines.append(f"Box {box.number} keeps its schedule: {who}; place: {names[place] if place else 'none'}.")
        if "join" in fields and box.number > 1:
            kind = story_bible.join_kind(_flags(ctx.timeline.boxes[box.number - 1], fields["join"]))
            note = fields["join"]["note"].strip()
            lines.append(f"Box {box.number} keeps its join: " + (f"{kind}: {_sentence(note)}" if note else f"{kind}."))
    return lines


def plan_messages(ctx):
    """prompts.story_messages(ctx) with the bible path's planner text and the bible after the user text."""
    if ctx.renderer == "image":
        system = instructions.image_planner(ctx.planning, ctx.template, model=ctx.image_model)
    else:
        system = instructions.planner(ctx.planning, ctx.template, styled=bool(story_bible.style(ctx.bible).strip()))
    messages = prompts.story_messages(ctx, system)
    messages[1]["content"] += "\n\n" + "\n".join(_bible_lines(ctx))
    return messages


def plan_format(ctx):
    """prompts.story_format(ctx) without the sheet, which the bible replaces, whose cast members also have kind,
    description and voice, and whose boxes also have place and join."""
    found = copy.deepcopy(prompts.story_format(ctx))
    schema = found["json_schema"]["schema"]
    del schema["properties"]["sheet"]
    schema["required"].remove("sheet")
    properties = schema["properties"]
    member, entry = properties["cast"]["items"], properties["boxes"]["items"]
    member["properties"].update(kind={"type": "string", "enum": list(story_bible.KINDS)},
                                description=dict(prompts.TEXT), voice=dict(prompts.TEXT))
    member["required"] += ["kind", "description", "voice"]
    entry["properties"].update(place=dict(prompts.TEXT), join=prompts._object(
        {"kind": {"type": "string", "enum": list(story_bible.JOINS)}, "note": dict(prompts.TEXT)}))
    entry["required"] += ["place", "join"]
    if ctx.renderer != "image" and not story_bible.style(ctx.bible).strip():
        properties["style"] = dict(prompts.TEXT)
        schema["required"].insert(1, "style")
        schema["properties"] = {key: properties[key] for key in schema["required"]}
    return found


def _text(item, key):
    return item[key].strip() if isinstance(item.get(key), str) else ""


def _add(bible, name, kind, pictures, description, voice=""):
    number = story_bible.next_number(bible)
    entity = {"id": f"e{number}", "kind": kind,
              "name": story_bible.unique_name(name, [item["name"] for item in bible["entities"]]),
              "pictures": pictures, "description": description, "looks": []}
    if voice:
        entity["voice"] = voice
    bible["entities"].append(entity)
    bible["next"] = number + 1


def _add_members(bible, cast, ctx):
    """Adds the planned cast members the bible has no entity for, by whole name, each with the connected pictures
    that no entity has yet."""
    connected, shared = {ref.name for ref in ctx.references}, set(prompts._shared(ctx))
    taken = {slot for item in bible["entities"] for slot in story_bible.owned(item)}
    for item in cast if isinstance(cast, list) else []:
        if not isinstance(item, dict) or not _text(item, "name"):
            continue
        called = prompts._called(item["name"])
        if any(prompts._called(entity["name"]) == called for entity in bible["entities"]):
            continue
        pictures = []
        for ref in item["references"] if isinstance(item.get("references"), list) else []:
            slot = prompts._reference_name(ref)
            if (slot and slot.startswith("image") and slot not in ctx.idea_references.values()
                    and slot in connected and slot not in shared and slot not in taken
                    and slot not in pictures):
                pictures.append(slot)
        taken.update(pictures)
        described = [ctx.descriptions[slot].strip() for slot in pictures if ctx.descriptions.get(slot, "").strip()]
        description = PICTURE.sub("", _text(item, "description")).strip(" ,;") or " ".join(described)
        if pictures and not described and not ctx.pictures:
            # The planner neither saw these pictures nor read about them, so any look it gave is a guess.
            description = re.split(r";|\.\s", compiler.DETAILS.split(description, 1)[0], 1)[0].strip(" ,;")
        _add(bible, item["name"].strip(), item.get("kind") if item.get("kind") in story_bible.KINDS else "character",
             pictures, description, _text(item, "voice"))


def _add_owners(bible, plan, ctx):
    """Adds a character for each picture a box to write lists that no entity has, named as its reference."""
    titles = {ref.name: ref.title for ref in ctx.references}
    for beat in plan.beats:
        for slot in beat.references:
            if (slot.startswith("image") and slot not in ctx.idea_references.values()
                    and not any(slot in story_bible.owned(item) for item in bible["entities"])):
                _add(bible, (titles.get(slot) or "").strip() or slot, "character", [slot],
                     ctx.descriptions.get(slot, "").strip())


def _match(entities, name):
    """The entity `name` calls, as a box's "on_screen" matches the cast, else None."""
    if not isinstance(name, str) or not prompts._called(name):
        return None
    called = {prompts._called(item["name"]): item for item in entities}
    key = prompts._member(called, prompts._called(name))
    return called[key] if key is not None else None


def _schedule(beat, place, entities):
    """The schedule of a planned box: who is on screen and the owners of its other pictures, and where it happens."""
    owners = {slot: item for item in entities for slot in story_bible.owned(item)}
    found = [item for item in (_match(entities, name) for name in beat.on_screen) if item is not None]
    for stage in beat.stages:
        for line in stage["dialogue"]:
            item = next((item for item in entities if item["id"] == line["speaker"].casefold()), None) or _match(entities, line["speaker"])
            if item is not None:
                found.append(item)
    found += [owners[slot] for slot in beat.references if slot in owners]
    named = _match(entities, place)
    places = [item for item in ([named] if named is not None else []) + found if item["kind"] == "place"]
    return {"entities": list(dict.fromkeys(item["id"] for item in found if item["kind"] != "place")),
            "place": places[0]["id"] if places else None}


def _kept_schedule(value, known):
    if not isinstance(value, dict) or not isinstance(value.get("entities"), list):
        return None
    return {"entities": [name for name in value["entities"] if name in known],
            "place": value.get("place") if value.get("place") in known else None}


def _kept_join(value):
    if isinstance(value, dict) and value.get("kind") in story_bible.JOINS and isinstance(value.get("note"), str):
        return value
    return None


def parse_plan(reply, ctx, saved=False):
    """(plan, planned): the StoryPlan prompts.parse_story makes of `reply` with the bible as its cast, and what the
    plan does to the bible. A saved plan (`saved`) adds no entity and keeps its sheet; a fresh one has none."""
    data = prompts.reply_data(reply)
    bible = copy.deepcopy(ctx.bible) if ctx.bible is not None else {"entities": [], "next": 1}
    if not saved:
        data.pop("sheet", None)
        _add_members(bible, data.get("cast"), ctx)
        look = _text(data, "style")
        if look and not story_bible.style(bible).strip():
            bible["style"] = {"look": look}
    cast = [{"name": item["name"], "references": list(item["pictures"])} for item in bible["entities"]
            if item["pictures"]]
    plan = prompts.parse_story(json.dumps(dict(data, cast=cast)), ctx, lenient=True)
    if not saved:
        _add_owners(bible, plan, ctx)
    entities = bible["entities"]
    known = {item["id"] for item in entities}
    kept = data.get("bible_boxes") if saved and isinstance(data.get("bible_boxes"), dict) else {}
    schedules, joins, notes = {}, {}, []
    for index, (beat, entry) in enumerate(zip(plan.beats, data["boxes"])):
        box_id = ctx.boxes[index].id if index < len(ctx.boxes) else None
        fields = ctx.box_fields.get(box_id, {})
        planned = kept.get(box_id) if isinstance(kept.get(box_id), dict) else {}
        schedules[index] = (fields.get("schedule") or _kept_schedule(planned.get("schedule"), known)
                            or _schedule(beat, entry.get("place"), entities))
        if index == 0:
            continue
        if ctx.planning:
            flags = {"cut": plan.cuts[index], "new_scene": plan.scenes[index]}
        else:
            flags = _flags(ctx.timeline.boxes[index])
        join = fields.get("join") or _kept_join(planned.get("join"))
        if join is not None:
            joins[index] = {"kind": story_bible.join_kind(dict(flags, join=join)), "note": join["note"]}
            continue
        wanted = entry.get("join") if isinstance(entry.get("join"), dict) else {}
        kind, note = wanted.get("kind"), _text(wanted, "note")
        given = story_bible.join_kind(dict(flags, join=None))
        if kind not in story_bible.JOINS:
            joins[index] = {"kind": given, "note": ""}
            continue
        if story_bible.join_kind(dict(flags, join={"kind": kind})) != kind:
            notes.append(f"Box {index + 1}'s join said {kind.replace('_', ' ')}, but {REASONS[given]}, so Write used "
                         f"{given.replace('_', ' ')}.")
            kind = given
        joins[index] = {"kind": kind, "note": note}
    return plan, Planned(bible, schedules, joins, notes)


def _scheduled(bible, schedule):
    entities = {item["id"]: item for item in bible["entities"]}
    keys = [*schedule["entities"], *filter(None, [schedule.get("place")])]
    return [entities[key] for key in dict.fromkeys(keys) if key in entities]


def box_references(bible, schedule, listed, room, number, notes, shared=(), connected=None, ids=(), guidance=()):
    """(references, left_out) for box `number` of the box ids `ids`.

    The references are, as far as `room` (images, audios) allows:
    - the pictures in force (`story_bible.pictures_at`) of the scheduled characters in order, then the place's,
      then the props';
    - then the `listed` audios.

    `left_out` lists the scheduled entities none of whose pictures fit. Each picture or audio that doesn't fit adds
    a note. A listed image that no entity owns is left out with a note; any other listed image is left out
    silently, because the schedule and the looks decide. The pictures in `shared` are in every box and take no room;
    with `connected`, a picture outside it doesn't fit."""
    images, audios = room
    references, left_out = [], []
    for entity in sorted(_scheduled(bible, schedule), key=lambda item: story_bible.KINDS.index(item["kind"])):
        fitted = False
        pictures = story_bible.pictures_at(entity, list(ids), number - 1)
        for slot in pictures:
            if slot in shared or slot in references:
                fitted = True
            elif connected is not None and slot not in connected:
                notes.append(f"Box {number} shows {entity['name']}, but {slot} isn't connected, so Write left it out.")
            elif len(references) < images:
                references.append(slot)
                fitted = True
            else:
                notes.append(f"Box {number} shows {entity['name']}, but H3 takes no more images there, so Write left "
                             f"out {slot}.")
        if pictures and not fitted:
            left_out.append(entity["id"])
    owned = {slot for item in bible["entities"] for slot in story_bible.owned(item)}
    for slot in dict.fromkeys(listed):
        if slot in shared or slot in references:
            continue
        if slot in guidance:
            if sum(name.startswith("image") for name in references) < images:
                references.append(slot)
            else:
                notes.append(f"Box {number} lists {slot}, but H3 takes no more images there, so Write left it out.")
            continue
        if slot.startswith("video"):
            kind = re.sub(r"\d+$", "", slot)
            if sum(re.sub(r"\d+$", "", name) == kind for name in references) < 3:
                references.append(slot)
            else:
                notes.append(f"Box {number} lists too many {kind} references; Write left out {slot}.")
            continue
        if slot.startswith("audio"):
            if sum(name.startswith("audio") for name in references) < audios:
                references.append(slot)
            else:
                notes.append(f"Box {number} lists {slot}, but H3 takes no more audios there, so Write left it out.")
        elif slot not in owned:
            notes.append(f"Box {number} lists {slot}, which no bible entry has, so Write left it out; give it to an "
                         "entity on the Cast page.")
    return references, left_out


def box_cast(bible, ids, index, schedule, context, left_out, written=None):
    """(subjects, compile) for box `index` of the box ids `ids`.

    The subjects are keyed by entity id, place last. Each has its name, kind and pictures in the box ("references",
    in Ref2VA only), its plain description, its full "wording" at the box, and its voice. `compile` is the BibleBox.
    `written` ({entity id: wording}) is what the box was written with: an entity whose wording now differs is
    changed, as one whose look in force has no picture of its own is, so its retention reads partially preserved."""
    rendered = set(context.slots.references) if context.mode == "Ref2VA" else set()
    subjects, sentences, voices, changed, clips = {}, {}, {}, set(), {}
    for entity in _scheduled(bible, schedule):
        key, wording = entity["id"], story_bible.wording(entity, ids, index)
        plain, voice = story_fast.plain(wording), (entity.get("voice") or "").strip()
        pictures = [slot for slot in story_bible.pictures_at(entity, ids, index) if slot in rendered]
        subjects[key] = {"name": entity["name"], "kind": entity["kind"], "references": pictures, "description": plain,
                         "wording": wording, "voice": voice}
        if not pictures and key not in left_out and plain:
            sentences[key] = compiler.sentence(f"{entity['name']} is {compiler.clause(plain)}")
        if voice:
            voices[key] = voice
        if entity.get("voice_clip"):
            clips[key] = entity["voice_clip"]
        look = story_bible.look_at(entity, ids, index)
        if (look and not entity["looks"][look - 1].get("pictures")) or (written or {}).get(key, wording) != wording:
            changed.add(key)
    return subjects, story_fast.BibleBox(ENTITY, story_bible.style(bible).strip(), sentences, voices, changed,
                                         story_bible.line, clips)


def frame(ctx, index, context, schedule, left_out, wording):
    """What compiling box `index` needs besides its reply and the bible; `wording` ({entity id: wording}) is what the
    box is written with."""
    slots = context.slots
    return {"mode": context.mode,
            **({"renderer": "image"} if ctx.renderer == "image" else {}),
            **({"image_guidance": list(context.image_guidance)} if context.image_guidance else {}),
            "slots": {"mode": slots.mode, "references": list(slots.references), "audios": list(slots.audios),
                      "first": slots.first, "last": slots.last},
            "frames": context.generated_frames, "carried": context.carried_frames,
            "schedule": copy.deepcopy(schedule), "left_out": list(left_out),
            "audio": [list(entry) for entry in prompts.timeline_audio_entries(ctx, index)], "wording": dict(wording)}


def _framed(source, bible, ids, index):
    """(context, subjects, compile) of box `index` from `source`'s frame and `bible`."""
    shape = source["frame"]
    slots = shape["slots"]
    context = prompt_ir.PromptContext(shape["mode"], rules.Slots(
        slots["mode"], list(slots["references"]), list(slots["audios"]), slots["first"], slots["last"], {}),
        shape["frames"], shape["carried"], tuple(shape.get("image_guidance", [])))
    return context, *box_cast(bible, ids, index, shape["schedule"], context, shape["left_out"], shape.get("wording"))


def compile_source(source, bible, ids, index, notes=None):
    """(text, details): box `index` compiled from `source` and `bible` alone, the Timeline's audio lines included."""
    context, subjects, compile = _framed(source, bible, ids, index)
    if "stages" in source["frame"]:
        story_stages.validate_source(source["reply"], source["frame"]["stages"], context.generated_frames,
                                     context.carried_frames)
    text, details = story_fast.compile_prompt(copy.deepcopy(source["reply"]), None, None, index, context, subjects,
                                              notes, None, compile, image=source["frame"].get("renderer") == "image")
    if source["frame"].get("renderer") == "image":
        return text, details
    return prompts.add_timeline_audio(text, [tuple(entry) for entry in source["frame"]["audio"]]), details


def source_schema(source, bible, ids, index):
    """The schema of the writer's reply for box `index`, for checking a patched `source`."""
    context, subjects, _ = _framed(source, bible, ids, index)
    schema = story_fast.response_schema(context, subjects, "summary" in source["reply"],
                                        any("opening_state" in shot for shot in source["reply"].get("shots", [])), endings=True)
    # Feedback may patch a saved reply written before shots had an explicit cut choice.
    schema["properties"]["shots"]["items"]["required"].remove("cut")
    return schema


def compiled(box, bible, ids, index):
    """compile_source's (text, details) for box `index` of the box ids `ids`, or None when the box has no source or
    its source doesn't compile with `bible`."""
    if box.get("source") is None:
        return None
    try:
        return compile_source(box["source"], bible, ids, index)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        return None


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def named(source):
    """The entity ids `source` names in its reply or its frame. Tolerates a source that doesn't compile."""
    shape = source["frame"]
    texts = [*_strings(source["reply"]), *_strings(shape.get("schedule")), *_strings(shape.get("left_out")),
             *(shape["wording"] if isinstance(shape.get("wording"), dict) else ())]
    return {name for text in texts for name in ENTITY.findall(text)}


def merged_source(source, merged):
    """`source` with each entity id of `merged` ({id: id it merged into}) replaced everywhere: in the reply's text and
    lists, the schedule, the entities left out and the recorded wording, each entity listed once."""
    def swap(value):
        if isinstance(value, str):
            return ENTITY.sub(lambda match: merged.get(match[0], match[0]), value)
        if isinstance(value, dict):
            return {key: item if key == "text" else swap(item) for key, item in value.items()}
        if isinstance(value, list):
            items = [swap(item) for item in value]
            entities = all(isinstance(item, str) and ENTITY.fullmatch(item) for item in items)
            return list(dict.fromkeys(items)) if entities else items
        return value

    result = copy.deepcopy(source)
    result["reply"] = swap(result["reply"])
    shape = result["frame"]
    for key in ("schedule", "left_out", "stages"):
        if key in shape:
            shape[key] = swap(shape[key])
    if isinstance(shape.get("wording"), dict):
        wording = {key: text for key, text in shape["wording"].items() if key not in merged}
        for key, text in shape["wording"].items():
            wording.setdefault(merged.get(key, key), text)
        shape["wording"] = wording
    return result


def refit(source, old_bible, bible, ids, index, shared, notes):
    """`source` with its frame's pictures following each scheduled entity, besides those left out, whose pictures in
    force at box `index` of the box ids `ids` differ between `old_bible` and `bible`. Its old pictures leave, unless
    another scheduled entity has them in force or the shared prompt mentions them (`shared`), and its new ones join,
    in slot order as `timeline.box_slots` gives them. A new picture past H3's images, counting the frame's and the
    shared ones together, is left out with a note in `notes`; one in `shared` takes no room. Returns `source` itself
    when its pictures stay the same."""
    shape = source["frame"]
    if shape["mode"] != "Ref2VA":
        return source
    before = {item["id"]: item for item in old_bible["entities"]}
    scheduled = [item for item in _scheduled(bible, shape["schedule"]) if item["id"] not in shape["left_out"]]
    now = {item["id"]: story_bible.pictures_at(item, ids, index) for item in scheduled}
    references = list(shape["slots"]["references"])
    for entity in scheduled:
        key = entity["id"]
        old = story_bible.pictures_at(before[key], ids, index) if key in before else now[key]
        if old == now[key]:
            continue
        kept = {slot for other, slots in now.items() if other != key for slot in slots} | set(shared) | set(now[key])
        references = [slot for slot in references if slot not in old or slot in kept]
        for slot in now[key]:
            used = {name for name in references if name.startswith("image")} | set(shared)
            if slot in references:
                continue
            if slot in shared or len(used) < rules.MAX_REF_IMAGES:
                references.append(slot)
            else:
                notes.append(f"Box {index + 1} shows {entity['name']}, but H3 takes no more images there, so {slot} "
                             "is left out.")
    if set(references) == set(shape["slots"]["references"]):
        return source
    result = copy.deepcopy(source)
    result["frame"]["slots"]["references"] = sorted(references, key=rules.slot_number)
    return result


def _add_looks(data, bible, box, notes):
    """The reply's look changes as looks from `box` in `bible`; an update for an entity that already has a look from
    the box is dropped from the reply."""
    entities = {item["id"]: item for item in bible["entities"]}
    kept = []
    for update in data["subject_updates"]:
        entity, text = entities.get(update["subject"]), update["description"].strip()
        if entity is None or not text:
            kept.append(update)
        elif any(look["from"] == box.id for look in entity["looks"]):
            notes.append(f"Box {box.number}: Write kept {entity['name']}'s look from this box; edit it on the Cast page "
                         "to change it.")
        else:
            entity["looks"].append({"from": box.id, "description": text})
            notes.append(f"Box {box.number}: {entity['name']} has a new look from this box: {text}")
            kept.append(update)
    data["subject_updates"] = kept


def _dicts(value):
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _ending(reply):
    """The log's ' Ended: …' from a reply's terminal state and ' Said: …' with its dialogue quoted in shot order, each
    left out when the reply has none. A saved reply is only known to be a dict."""
    state = reply.get("terminal_state") if isinstance(reply.get("terminal_state"), dict) else {}
    ended = " ".join(_sentence(state[key]) for key in ("setting", "positions", "props")
                     if isinstance(state.get(key), str) and state[key].strip())
    said = " ".join(f'"{line["text"].strip()}"' for shot in _dicts(reply.get("shots"))
                    for line in _dicts(shot.get("dialogue")) if isinstance(line.get("text"), str) and line["text"].strip())
    return (f" Ended: {ended}" if ended else "") + (f" Said: {said}" if said else "")


def _earlier_boxes(ctx, work, ids, index):
    """The continuity log for box `index`: a line for each earlier box with who and where from its schedule and each
    entity's look there, then how it ended and what was said, from this Write's reply for a box this Write wrote (none
    when it wrote prose), else from the box's saved source."""
    if not index:
        return []
    known = {item["id"]: item for item in work.bible["entities"]}
    lines = ["Earlier boxes:"]
    for number, box_id in enumerate(ids[:index], 1):
        schedule = work.schedules.get(number - 1) or {"entities": [], "place": None}
        place = known.get(schedule.get("place"))
        who = []
        for entity in filter(None, map(known.get, schedule["entities"])):
            look = story_bible.look_at(entity, ids, number - 1)
            since = f" (look from box {ids.index(entity['looks'][look - 1]['from']) + 1})" if look else ""
            who.append(f"{entity['id']} {entity['name']}{since}")
        if box_id in work.fields:
            reply = work.replies.get(box_id)
        else:
            source = (ctx.box_fields.get(box_id) or {}).get("source")
            reply = None
            if source and ctx.boxes[number - 1].prompt.strip():
                made = compiled({"source": source}, work.bible, ids, number - 1)
                if made is not None and made[0] == ctx.boxes[number - 1].prompt:
                    reply = source["reply"]
        line = f"Box {number}" + (f", {place['name']}" if place else "") + (f": {', '.join(who)}." if who else ".")
        lines.append(line + (_ending(reply) if reply else ""))
    return lines


def _box_lines(work, ids, index, schedule):
    names = {item["id"]: item["name"] for item in work.bible["entities"]}
    lines = []
    if schedule.get("place") in names:
        lines.append(f"Place: {schedule['place']} ({names[schedule['place']]}).")
    join = work.joins.get(index)
    if index and join:
        note = join["note"].strip()
        lines.append("Join from the box before: " + (f"{join['kind']}: {_sentence(note)}" if note else f"{join['kind']}."))
    look = story_bible.style(work.bible).strip()
    if look:
        lines.append(f"Style of every box (code inserts it; do not restate): {look}")
    changed = []
    for entity in _scheduled(work.bible, schedule):
        look = story_bible.look_at(entity, ids, index)
        if look:
            start = ids.index(entity["looks"][look - 1]["from"]) + 1
            changed.append(f"{entity['id']} ({entity['name']}) since box {start}")
    if changed:
        lines.append(f"Changed looks: {'; '.join(changed)}. {LOOKS}")
    return lines


async def write_box(chat, ctx, plan, index, final, neighbors, work):
    """Box `index`'s prompt, written with the bible in `work`, and its fields in work.fields."""
    box, beat = ctx.boxes[index], plan.beats[index]
    ids = [item.id for item in ctx.boxes]
    schedule = work.schedules.get(index) or {"entities": [], "place": None}
    references, left_out = box_references(work.bible, schedule, beat.references, prompts._room(ctx), box.number,
                                          chat.job.notes, prompts._shared(ctx), {ref.name for ref in ctx.references},
                                          ids, ctx.idea_references.values())
    context = prompt_ir.resolve(ctx, index, references)
    subjects, compile = box_cast(work.bible, ids, index, schedule, context, left_out)
    shown = {key: {name: value for name, value in item.items() if name != "wording"} for key, item in subjects.items()}
    summary = bool(compile.voice_clips)
    stages = (story_stages.freeze(beat.stages, box.frames, box.carried, subjects, beat.ends)
              if ctx.renderer != "image" else None)
    messages = story_fast.messages(ctx, plan, index, final, context, shown, neighbors, bible=True, summary=summary,
                                   stages=stages)
    messages[1]["content"] += "".join("\n" + line for line in [*_earlier_boxes(ctx, work, ids, index),
                                                                *_box_lines(work, ids, index, schedule)])
    schema = story_fast.response_schema(context, subjects, summary, image=ctx.renderer == "image", stages=stages)
    fields = {"schedule": copy.deepcopy(schedule)}
    join = work.joins.get(index)
    saved = story_bible.saved_join(join["kind"], join["note"]) if join else None
    if saved is not None:
        fields["join"] = saved
    reply = await chat.ask(messages, prompt_schema.reply_format("h3_fast_box", schema))
    data = prompt_ir.parse_json(reply)
    validate.shape(data if stages is not None else validate.shot_cuts(data), schema)
    if stages is not None:
        data = story_stages.expand(data, stages)
    candidate = copy.deepcopy(work.bible)
    _add_looks(data, candidate, box, chat.job.notes)
    written = {item["id"]: story_bible.wording(item, ids, index) for item in _scheduled(candidate, schedule)}
    source = {"reply": data, "frame": frame(ctx, index, context, schedule, left_out, written)}
    if stages is not None:
        source["frame"]["stages"] = stages
    text, details = compile_source(source, candidate, ids, index, chat.job.notes)
    checked = prompts.prompt_text(text, ctx, index, context, None, chat.job.notes)
    work.bible = candidate
    fields["cast"] = details["cast"]
    work.replies[box.id] = data
    if checked == text:
        fields["source"] = source
    neighbors[box.id] = details
    beat.terminal_state, beat.looks, beat.definitions = details["ending"], {}, {}
    names = {item["id"]: item["name"] for item in work.bible["entities"]}
    chat.job.notes.extend(
        f"Box {box.number}: Write gave {names[key]} the bible's wording in place of the line edited in the box; edit "
        f"{names[key]} on the Cast page to change it." for key in ctx.hand_edited.get(box.id, []) if key in names)
    work.fields[box.id] = fields
    return checked
