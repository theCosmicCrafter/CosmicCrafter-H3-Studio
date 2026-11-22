"""The Story bible: a Timeline's characters, places and props, their looks over time, and the subject lines they give.

The bible is the Timeline's top-level "bible" object; each box's "cast" maps its subject labels to entity ids. Only
`apply`, `recompile` and `assign` change prompts: `apply` for boxes whose prompt is still what their source compiled
to and for subjects whose line is still what the bible gave them, `recompile` only for the boxes it is asked for, and
`assign` by adding one entity's subject line to one box.
Nothing here calls a model."""
import copy
import json
import re

from . import story_edits, story_fast, timeline as rules

KINDS = ("character", "place", "prop")
JOINS = ("continue", "transition", "cut", "new_scene")
ENTITY_ID = re.compile(r"e[1-9]\d*")
SECTION = re.compile(r"(?ms)^\s*subject_definitions:\s*(.*?)(?=^\s*\w+:|\Z)")
# Another lowercase name heads a section when it is snake_case or alone on its line; "note: ..." stays prose.
HEADER = re.compile(r"(?m)^[ \t]*(summary|[a-z]+_[a-z_]*|[a-z]+(?=:[ \t]*\r?$)):")
LABEL = re.compile(r"<Subject [1-9]\d*>")
NOT_WRITTEN = "it isn't written as “<Subject N> is …”"
REPEATED = "an earlier line in this box has this label"
NOT_REPRODUCED = "the bible can't reproduce this line exactly"
NO_MATCH = "no entity matches it"
NOTHING = ("No box has a subject definition and the Story has no saved cast, so there is nothing to build. "
           "Nothing changed.")


def entities(bible):
    """The bible's entities, checked. Raises ValueError naming the first problem."""
    if not isinstance(bible, dict) or not isinstance(bible.get("entities"), list):
        raise ValueError("The bible must be an object with an entities list.")
    seen, clips = set(), {}
    for number, item in enumerate(bible["entities"], 1):
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not ENTITY_ID.fullmatch(item["id"]):
            raise ValueError(f"Entity {number} needs an id like e1.")
        name = item["id"]
        if name in seen:
            raise ValueError(f"Entity id {name} is used twice.")
        seen.add(name)
        if item.get("kind") not in KINDS:
            raise ValueError(f"Entity {name}'s kind must be character, place or prop.")
        if not isinstance(item.get("name"), str) or not item["name"].strip():
            raise ValueError(f"Entity {name} needs a name.")
        if not isinstance(item.get("pictures"), list) or not all(map(rules.is_picture_slot, item["pictures"])):
            raise ValueError(f"Entity {name}'s pictures must be image slots like image1.")
        if not isinstance(item.get("description"), str):
            raise ValueError(f"Entity {name}'s description must be text.")
        if "voice" in item and not isinstance(item["voice"], str):
            raise ValueError(f"Entity {name}'s voice must be text.")
        if "voice_clip" in item:
            slot = item["voice_clip"]
            if item["kind"] != "character" or not rules.is_voice_slot(slot):
                raise ValueError(f"Entity {name}'s voice clip must be a slot from audio4 up, on a character.")
            if slot in clips:
                raise ValueError(f"{clips[slot]} and {item['name']} can't share the voice clip @{slot}.")
            clips[slot] = item["name"]
        looks = item.get("looks")
        if not isinstance(looks, list) or not all(isinstance(look, dict) and isinstance(look.get("from"), str)
                                                  and isinstance(look.get("description"), str) for look in looks):
            raise ValueError(f"Entity {name}'s looks must each name a box and give a description.")
        if not all(isinstance(look.get("pictures", []), list)
                   and all(map(rules.is_picture_slot, look.get("pictures", []))) for look in looks):
            raise ValueError(f"Entity {name}'s look pictures must be image slots like image1.")
        starts = [look["from"] for look in looks]
        for box in starts:
            if starts.count(box) > 1:
                raise ValueError(f"Entity {name} has more than one look from box {box}.")
        pins = item.get("pins", [])
        if not isinstance(pins, list) or not all(
                isinstance(pin, dict) and isinstance(pin.get("box"), str) and pin["box"]
                and type(pin.get("frame")) is int and pin["frame"] >= 0 for pin in pins):
            raise ValueError(f"Entity {name}'s pins must each name a box and a frame from 0.")
    if "next" in bible and (type(bible["next"]) is not int or bible["next"] < 1):
        raise ValueError("The bible's next id must be a whole number above 0.")
    if "style" in bible and not (isinstance(bible["style"], dict) and isinstance(bible["style"].get("look"), str)):
        raise ValueError('The bible\'s style must be {"look": text}.')
    return bible["entities"]


def held_voices(bible, timeline):
    """Raises ValueError naming the first character whose voice clip the Timeline (its JSON object) doesn't hold."""
    clips = timeline.get("voice_clips")
    held = {clip.get("slot") for clip in clips if isinstance(clip, dict)} if isinstance(clips, list) else set()
    for item in entities(bible):
        if "voice_clip" in item and item["voice_clip"] not in held:
            raise ValueError(f"{item['name']}'s voice clip @{item['voice_clip']} isn't in the Timeline.")


def style(bible):
    """The look of the bible's style, or "" without one."""
    return ((bible or {}).get("style") or {}).get("look", "")


def _entity_id(value):
    return isinstance(value, str) and ENTITY_ID.fullmatch(value) is not None


def valid_schedule(schedule):
    """True for a box schedule: {"entities": [entity ids], "place": an entity id or None}."""
    return (isinstance(schedule, dict) and isinstance(schedule.get("entities"), list)
            and all(_entity_id(item) for item in schedule["entities"])
            and (schedule.get("place") is None or _entity_id(schedule["place"])))


def boxes(timeline):
    """The Timeline's boxes, checked: each has a string id and prompt, and a cast, schedule, join or source, if any,
    has its shape."""
    if not isinstance(timeline, dict) or not isinstance(timeline.get("boxes"), list):
        raise ValueError("The Timeline must be an object with a boxes list.")
    for number, box in enumerate(timeline["boxes"], 1):
        if not isinstance(box, dict) or not isinstance(box.get("id"), str) or not isinstance(box.get("prompt"), str):
            raise ValueError(f"Box {number} needs an id and a prompt.")
        cast = box.get("cast")
        if cast is not None and (not isinstance(cast, dict) or not all(
                isinstance(label, str) and isinstance(target, str) for label, target in cast.items())):
            raise ValueError(f"Box {number}'s cast must map subject labels to entity ids.")
        schedule = box.get("schedule")
        if schedule is not None and not valid_schedule(schedule):
            raise ValueError(f"Box {number}'s schedule must list entity ids and give a place id or null.")
        join = box.get("join")
        if join is not None and not (isinstance(join, dict) and join.get("kind") in JOINS
                                     and isinstance(join.get("note"), str)):
            raise ValueError(f"Box {number}'s join needs a kind (continue, transition, cut or new_scene) and a note.")
        source = box.get("source")
        if source is not None and not is_story_source(source):
            raise ValueError(f"Box {number}'s source isn't one H3's Story wrote; H3 keeps the Story's record of a box "
                             "there, so keep other metadata under another key.")
    return timeline["boxes"]


def is_story_source(source):
    """Whether a box's `source` has the shape of the Story's record of what it wrote: a reply and a frame."""
    return isinstance(source, dict) and isinstance(source.get("reply"), dict) and isinstance(source.get("frame"), dict)


def join_kind(box):
    """The box's join kind: its join's kind when the flags allow it, else the kind its flags give (continue without
    a cut, cut, or new_scene)."""
    flags = ("new_scene" if box.get("new_scene") else "cut") if box.get("cut") else "continue"
    kind = (box.get("join") or {}).get("kind")
    return kind if kind == flags or (kind == "transition" and flags == "continue") else flags


def saved_join(kind, note):
    """The join to save for `kind` and `note`: {"kind", "note"} with the note trimmed, or None unless it is a
    transition or has a note."""
    text = (note or "").strip()
    return {"kind": kind, "note": text} if kind == "transition" or text else None


def look_at(entity, ids, index):
    """0 for the entity's description, or k for looks[k-1]: its latest look starting at or before box `index` of the
    box ids `ids`. A look whose box is missing has no effect."""
    position = {box: number for number, box in enumerate(ids)}
    chosen, start = 0, -1
    for number, look in enumerate(entity["looks"], 1):
        at = position.get(look["from"])
        if at is not None and start < at <= index:
            chosen, start = number, at
    return chosen


def wording(entity, ids, index):
    """The entity's wording at box `index` of the box ids `ids`."""
    look = look_at(entity, ids, index)
    return entity["looks"][look - 1]["description"] if look else entity["description"]


def pictures_at(entity, ids, index):
    """The entity's pictures at box `index` of the box ids `ids`: those of its latest look starting at or before the
    box that has pictures, else its own. A look whose box is missing has no effect."""
    position = {box: number for number, box in enumerate(ids)}
    chosen, start = entity["pictures"], -1
    for look in entity["looks"]:
        at = position.get(look["from"])
        if look.get("pictures") and at is not None and start < at <= index:
            chosen, start = look["pictures"], at
    return list(chosen)


def owned(entity):
    """Every picture of the entity: its own, then each look's, each once."""
    looks = (slot for look in entity["looks"] for slot in look.get("pictures", []))
    return list(dict.fromkeys([*entity["pictures"], *looks]))


def line(label, wording, pictures):
    """The subject line for `label`: the wording as written when it names a picture, otherwise as Fast words it,
    bound to `pictures`. None for an empty wording."""
    text = re.sub(r"\s*\n\s*", " ", wording or "").strip()
    if not text:
        return None
    if any(kind == "image" for kind, _ in rules.mentions(text)):
        return f"{label} is {text}"
    return story_fast.definition(label, text, pictures)


def subject_lines(prompt):
    """{label: (start, end, text after "is")} for each `<Subject N> is …` line in the prompt's subject_definitions;
    the first line for a label wins."""
    section = SECTION.search(prompt or "")
    if not section:
        return {}
    found = {}
    for match in story_fast.DEFINITION.finditer(section.group(1)):
        found.setdefault(match[1], (section.start(1) + match.start(1), section.start(1) + match.end(2), match[2]))
    return found


def section_lines(prompt):
    """[(label, line, text after "is" or None)] for each line of the prompt's subject_definitions that starts with a
    subject label, in order; None without that section."""
    section = SECTION.search(prompt or "")
    if not section:
        return None
    found = []
    for raw in section.group(1).splitlines():
        current = raw.rstrip()
        label = LABEL.match(current)
        if label:
            match = story_fast.DEFINITION.fullmatch(current)
            found.append((label[0], current, match[2] if match else None))
    return found


def compile_box(prompt, lines):
    """`prompt` with each {label: line} definition line replaced, and each changed subject marked partially preserved.
    Nothing else changes."""
    found = subject_lines(prompt)
    result = prompt
    for label in sorted((label for label in lines if label in found), key=lambda label: -found[label][0]):
        start, end, _ = found[label]
        result = result[:start] + lines[label] + result[end:]
    return story_edits.retained(prompt, result)


def opening_name(text, pictures):
    """A name from a line's opening words: up to the first comma, without pictures, a final stop or a leading
    article. "Subject from @imageN" when no words are left."""
    words = re.sub(r"[.!?…]+$", "", story_fast.plain(text.split(",", 1)[0])).strip()
    words = re.sub(r"^(?:a|an|the)\s+", "", words, flags=re.IGNORECASE)
    if words:
        return words[0].upper() + words[1:]
    return f"Subject from @{pictures[0]}" if pictures else "Subject"


def unique_name(name, taken):
    """`name`, or `name 2`, `name 3`… when another entity has it (compared in lowercase)."""
    used = {item.lower() for item in taken}
    number, result = 1, name
    while result.lower() in used:
        number += 1
        result = f"{name} {number}"
    return result


def pictures_of(text):
    return [slot for kind, slot in rules.mentions(text) if kind == "image"]


def next_number(bible):
    highest = max((int(item["id"][1:]) for item in bible["entities"]), default=0)
    return max(bible.get("next", 1), highest + 1)


def plan_cast(plan):
    """[(name, image slots)] of the saved plan's cast members, in order."""
    members = plan.get("cast") if isinstance(plan, dict) else None
    return [(member["name"].strip(), list(dict.fromkeys(slot for slot in member["references"] if rules.is_picture_slot(slot))
                                          if isinstance(member.get("references"), list) else []))
            for member in (members if isinstance(members, list) else [])
            if isinstance(member, dict) and isinstance(member.get("name"), str) and member["name"].strip()]


def recorded(plan, box_id, label, text):
    """The cast member name the plan's record for this box gives `label`, while the recorded line is `text` or names
    the same pictures; otherwise None."""
    entries = plan.get("boxes") if isinstance(plan, dict) else None
    for entry in entries if isinstance(entries, list) else []:
        if isinstance(entry, dict) and entry.get("id") == box_id and isinstance(entry.get("definitions"), dict):
            for name, item in entry["definitions"].items():
                if isinstance(item, dict) and item.get("label") == label and isinstance(item.get("line"), str) and (
                        item["line"] == text or set(pictures_of(item["line"])) == set(pictures_of(text))):
                    return name.strip()
    return None


def summary(made, linked_boxes):
    if not made:
        return NOTHING
    counted = "1 entity" if len(made) == 1 else f"{len(made)} entities"
    where = "1 box" if linked_boxes == 1 else f"{linked_boxes} boxes"
    looks = "".join(f" {item['name']} has {len(item['looks']) + 1} looks." for item in made if item["looks"])
    return f"{counted} from {where}.{looks} Nothing that renders changed."


def build(timeline, plan=None):
    """A faithful first bible from the Timeline's subject lines and the linked Story's saved plan: the bible (None
    when there is nothing to build), every box's cast, a summary and the unlinked subjects with their reasons."""
    items = boxes(timeline)
    if timeline.get("bible") is not None:
        raise ValueError("This Timeline already has a bible.")
    members, groups, made = {}, {}, []
    for name, pictures in plan_cast(plan):
        entity = {"kind": "character", "name": unique_name(name, [item["name"] for item in made]), "pictures": pictures,
                  "description": "", "looks": []}
        members.setdefault(name.lower(), entity)
        made.append(entity)
    cast_members = list(made)
    ids = [box["id"] for box in items]
    casts, unlinked, linked_boxes = {}, [], 0
    for index, box in enumerate(items):
        found = section_lines(box["prompt"])
        if found is None:
            continue
        cast, seen = {}, set()
        for label, current, text in found:
            unlink = lambda why: unlinked.append({"box": box["id"], "label": label, "line": current, "why": why})
            repeated = label in seen
            seen.add(label)
            if repeated or text is None:
                unlink(REPEATED if repeated else NOT_WRITTEN)
                continue
            pictures = pictures_of(text)
            entity, key = members.get((recorded(plan, box["id"], label, text) or "").lower()), None
            if entity is None and pictures:
                owners = [item for item in cast_members if set(item["pictures"]) & set(pictures)]
                entity = owners[0] if len(owners) == 1 else None
            if entity is None:
                key = ("pictures", frozenset(pictures)) if pictures else ("words", opening_name(text, pictures).lower())
                entity = groups.get(key)
            if entity is not None and any(other is entity for other in cast.values()):
                unlink(f"another subject in this box is already {entity['name']}")
                continue
            if line(label, text, entity["pictures"] if entity is not None else pictures) != current:
                unlink(NOT_REPRODUCED)
                continue
            if entity is None:
                entity = {"kind": "character", "name": unique_name(opening_name(text, pictures), [item["name"] for item in made]),
                          "pictures": pictures, "description": "", "looks": []}
                groups[key] = entity
                made.append(entity)
            if not entity["description"]:
                entity["description"] = text
            elif text != wording(entity, ids, index):
                entity["looks"].append({"from": box["id"], "description": text})
            cast[label] = entity
        casts[box["id"]] = cast
        linked_boxes += bool(cast)
    if not made:
        return {"bible": None, "casts": {}, "summary": NOTHING, "unlinked": unlinked}
    for number, entity in enumerate(made, 1):
        entity["id"] = f"e{number}"
    bible = {"entities": [{field: item[field] for field in ("id", "kind", "name", "pictures", "description", "looks")}
                          for item in made], "next": len(made) + 1}
    return {"bible": bible, "casts": {box: {label: item["id"] for label, item in cast.items()} for box, cast in casts.items()},
            "summary": summary(made, linked_boxes), "unlinked": unlinked}


def link(timeline, plan, box_ids):
    """Casts for the given boxes, linking their subjects to existing entities by the plan's record, then by a picture
    exactly one entity has. Creates no entity; every given box gets a cast, even an empty one."""
    items = boxes(timeline)
    if timeline.get("bible") is None:
        raise ValueError("This Timeline has no bible yet; use Build bible first.")
    known = entities(timeline["bible"])
    if not isinstance(box_ids, list) or not all(isinstance(box, str) for box in box_ids):
        raise ValueError("Boxes must be a list of box ids.")
    named = {}
    for entity in known:
        named.setdefault(entity["name"].strip().lower(), []).append(entity)
    casts, unlinked = {}, []
    for box in items:
        if box["id"] not in box_ids:
            continue
        cast, seen = {}, set()
        for label, current, text in section_lines(box["prompt"]) or []:
            unlink = lambda why: unlinked.append({"box": box["id"], "label": label, "line": current, "why": why})
            repeated = label in seen
            seen.add(label)
            if repeated or text is None:
                unlink(REPEATED if repeated else NOT_WRITTEN)
                continue
            pictures = pictures_of(text)
            matches = named.get((recorded(plan, box["id"], label, text) or "").lower(), [])
            entity = matches[0] if len(matches) == 1 else None
            if entity is None and pictures:
                owners = [item for item in known if set(owned(item)) & set(pictures)]
                entity = owners[0] if len(owners) == 1 else None
            if entity is None:
                unlink(NO_MATCH)
            elif entity["id"] in cast.values():
                unlink(f"another subject in this box is already {entity['name']}")
            else:
                cast[label] = entity["id"]
        casts[box["id"]] = cast
    return {"casts": casts, "unlinked": unlinked}


def status(timeline):
    """Each linked or unlinked subject of every box with a cast, the boxes without a cast that have subject lines,
    each entity's look at every box, and "sources": {box id: "compiled" or "edited"} for each box whose source
    compiles, "compiled" when its prompt is what the source compiles to. Every subject of a compiled box is in step."""
    from . import story_bible_write
    items = boxes(timeline)
    known = {item["id"]: item for item in entities(timeline["bible"])} if timeline.get("bible") is not None else {}
    ids = [box["id"] for box in items]
    subjects, unlinked, sources = [], [], {}
    for index, box in enumerate(items):
        made = story_bible_write.compiled(box, timeline["bible"], ids, index) if known else None
        if made is not None:
            sources[box["id"]] = "compiled" if made[0] == box["prompt"] else "edited"
        found = subject_lines(box["prompt"])
        if box.get("cast") is None:
            if found:
                unlinked.append(box["id"])
            continue
        for label, (start, end, text) in found.items():
            current = box["prompt"][start:end]
            entity = known.get(box["cast"].get(label))
            item = {"box": box["id"], "label": label, "entity": None, "look": None, "state": "unlinked",
                    "line": current, "text": text}
            if entity is not None:
                look = look_at(entity, ids, index)
                expected = line(label, wording(entity, ids, index), pictures_at(entity, ids, index))
                in_step = sources.get(box["id"]) == "compiled" or expected is None or expected == current
                item.update(entity=entity["id"], look=look, state="in_step" if in_step else "differs")
            subjects.append(item)
    in_force = {name: [look_at(entity, ids, index) for index in range(len(items))] for name, entity in known.items()}
    return {"subjects": subjects, "unlinked_boxes": unlinked, "in_force": in_force, "sources": sources}


def recompile(timeline, box_ids):
    """{"prompts", "casts"}: what the boxes `box_ids` get when compiled from their sources and the Timeline's bible,
    for those that change. Raises ValueError without a bible, for an unknown box, and for a box without a source that
    compiles."""
    from . import story_bible_write
    items = boxes(timeline)
    if timeline.get("bible") is None:
        raise ValueError("The Timeline has no bible to compile from.")
    held_voices(timeline["bible"], timeline)
    ids = [box["id"] for box in items]
    if not isinstance(box_ids, list) or not box_ids or not all(isinstance(key, str) and key in ids for key in box_ids):
        raise ValueError("List the boxes to recompile by id.")
    prompts, casts = {}, {}
    for key in dict.fromkeys(box_ids):
        index = ids.index(key)
        made = story_bible_write.compiled(items[index], timeline["bible"], ids, index)
        if made is None:
            raise ValueError(f"Box {index + 1} has no source to recompile.")
        text, details = made
        if text != items[index]["prompt"]:
            prompts[key] = text
        if details["cast"] != items[index].get("cast"):
            casts[key] = details["cast"]
    return {"prompts": prompts, "casts": casts}


def apply(timeline, bible, links=None, force=(), merged=None):
    """The prompts and casts that change when `bible` replaces the Timeline's bible, with `links` ({box id: {label:
    entity id, None to unlink, or "new"}}) and `force` ([[box id, label], ...]) applied.

    A box whose prompt is what its source compiled to recompiles whole from it; links and force don't apply to it.
    First its frame follows the pictures in force (`story_bible_write.refit`). The source of a box edited by hand
    follows them too, so that Recompile from source binds them. A source that names an entity of the
    old bible that `bible` lacks names the entity it went into instead, when `merged` ({id: id it merged into})
    covers every such entity, and is dropped otherwise. In other boxes, a subject gets its new line when its line is
    what the old bible gave it, or when forced; otherwise it is left alone and, if the edit would have changed it,
    listed in "differs". The answer adds "sources": {box id: its new source, or None where it was dropped};
    "reworded": {entity id: [{"box", "before", "after"}, ...]}, in the bible's order, for each box with a prompt
    where the edit changes the wording of an entity its cast links or its source names, unless the entity's line
    there is left alone; and "notes", one for each picture a box's frame had no room for."""
    from . import story_bible_write
    items = boxes(timeline)
    old_bible = timeline.get("bible")
    old = {item["id"]: item for item in entities(old_bible)} if old_bible is not None else {}
    bible = copy.deepcopy(bible)
    known = {item["id"]: item for item in entities(bible)}
    held_voices(bible, timeline)
    if links is not None and (not isinstance(links, dict) or not all(isinstance(given, dict) for given in links.values())):
        raise ValueError("Links must map box ids to {label: entity id} objects.")
    if merged is not None and not (isinstance(merged, dict) and all(
            isinstance(name, str) and isinstance(into, str) and into in known for name, into in merged.items())):
        raise ValueError("Merged must map entity ids to entities the bible keeps.")
    try:
        forced = {(box, label) for box, label in force or ()}
    except (TypeError, ValueError):
        raise ValueError("Force must list [box id, label] pairs.") from None
    ids = [box["id"] for box in items]
    removed = set(old) - set(known)
    voiced = lambda found: {item["id"]: item["voice_clip"] for item in found if item.get("voice_clip")}
    revoiced = voiced(old.values()) != voiced(known.values())
    shared = pictures_of(timeline["prompt"] if isinstance(timeline.get("prompt"), str) else "")
    prompts, casts, differs, sources, naming, notes = {}, {}, [], {}, {}, []
    for index, box in enumerate(items):
        given = (links or {}).get(box["id"], {})
        made = story_bible_write.compiled(box, old_bible, ids, index) if old_bible is not None else None
        if made is not None:
            naming[box["id"]] = story_bible_write.named(box["source"])
            source, lost = box["source"], naming[box["id"]] & removed
            if lost:
                source = story_bible_write.merged_source(source, merged) if lost <= set(merged or {}) else None
                sources[box["id"]] = source
            remade = None
            if source is not None and made[0] == box["prompt"]:
                found = []
                fitted = story_bible_write.refit(source, old_bible, bible, ids, index, shared, found)
                remade = story_bible_write.compiled(dict(box, source=fitted), bible, ids, index)
                if remade is not None:
                    notes += found + (remade[1].get("voice_notes", []) if revoiced else [])
                    if fitted is not source:
                        sources[box["id"]] = fitted
            elif source is not None:
                fitted = story_bible_write.refit(source, old_bible, bible, ids, index, shared, notes)
                if fitted is not source:
                    sources[box["id"]] = fitted
            if remade is not None:
                if remade[0] != box["prompt"]:
                    prompts[box["id"]] = remade[0]
                if remade[1]["cast"] != box.get("cast"):
                    casts[box["id"]] = remade[1]["cast"]
                continue
        if box.get("cast") is None and not given:
            continue
        found = subject_lines(box["prompt"])
        cast = dict(box.get("cast") or {})
        for label, target in given.items():
            if target is None:
                cast.pop(label, None)
            elif target == "new" and label in found:
                text = found[label][2]
                pictures = pictures_of(text)
                made = {"id": f"e{next_number(bible)}", "kind": "character",
                        "name": unique_name(opening_name(text, pictures), [item["name"] for item in bible["entities"]]),
                        "pictures": pictures, "description": text, "looks": []}
                bible["entities"].append(made)
                bible["next"] = int(made["id"][1:]) + 1
                known[made["id"]] = made
                cast[label] = made["id"]
            elif target != "new":
                cast[label] = target
        cast = {label: target for label, target in cast.items() if target in known and label in found}
        lines = {}
        for label, target in cast.items():
            start, end, _ = found[label]
            current = box["prompt"][start:end]
            previous = old.get((box.get("cast") or {}).get(label))
            before = line(label, wording(previous, ids, index), pictures_at(previous, ids, index)) if previous else None
            after = line(label, wording(known[target], ids, index), pictures_at(known[target], ids, index))
            if after is None or after == current:
                continue
            if current == before or (box["id"], label) in forced:
                lines[label] = after
            elif before != after:
                differs.append({"box": box["id"], "label": label, "entity": target, "line": current})
        if lines:
            prompts[box["id"]] = compile_box(box["prompt"], lines)
        if cast != box.get("cast"):
            casts[box["id"]] = cast
    left = {(item["box"], item["entity"]) for item in differs}
    reworded = {}
    for entity in bible["entities"]:
        previous = old.get(entity["id"])
        if previous is None:
            continue
        for index, box in enumerate(items):
            before, after = wording(previous, ids, index), wording(entity, ids, index)
            linked = entity["id"] in (casts.get(box["id"], box.get("cast")) or {}).values()
            if before != after and box["prompt"].strip() and (box["id"], entity["id"]) not in left and (
                    linked or entity["id"] in naming.get(box["id"], ())):
                reworded.setdefault(entity["id"], []).append({"box": box["id"], "before": before, "after": after})
    return {"bible": bible, "prompts": prompts, "casts": casts, "differs": differs, "sources": sources,
            "reworded": reworded, "notes": notes}


def assign(timeline, box_id, entity_id):
    """A deterministic proposal adding one bible identity; the caller applies all three changes atomically."""
    items = boxes(timeline)
    known = {item['id']: item for item in entities(timeline.get('bible'))}
    index = next((i for i, box in enumerate(items) if box['id'] == box_id), None)
    if index is None or entity_id not in known:
        raise ValueError('Choose an existing clip and Cast entity.')
    box, entity = items[index], known[entity_id]
    found = subject_lines(box['prompt'])
    for label, target in (box.get('cast') or {}).items():
        if target == entity_id and label in found:
            return {'prompts': {}, 'casts': {}, 'schedules': {}, 'subject': label, 'changed': False}
    ids = [item['id'] for item in items]
    pictures = pictures_at(entity, ids, index)
    if any(slot in timeline.get('disabled_refs', []) for slot in pictures):
        raise ValueError('Enable this Cast entry’s pictures before adding it to the clip.')
    description = wording(entity, ids, index).strip()
    if not description and not pictures:
        raise ValueError('Add a description or picture to this entry in Cast first.')
    text = box['prompt']
    headers = list(HEADER.finditer(text))
    keys = [h[1] for h in headers]
    if len(keys) != len(set(keys)) or ('detailed_description' in keys and 'integrated_multimodal_description' in keys):
        raise ValueError('Resolve duplicate prompt sections in Raw text before adding Cast.')
    used = ' '.join([timeline.get('prompt', ''), text, *(box.get('cast') or {})])
    number = max([int(n) for n in re.findall(r'<Subject ([1-9]\d*)>', used)] or [0]) + 1
    label = f'<Subject {number}>'
    definition = line(label, description or entity['name'], pictures)
    if 'subject_definitions' in keys:
        header = headers[keys.index('subject_definitions')]
        end = headers[keys.index('subject_definitions') + 1].start() if keys.index('subject_definitions') + 1 < len(headers) else len(text)
        at = len(text[:end].rstrip())
        text = text[:at] + '\n' + definition + text[at:]
    else:
        if 'integrated_multimodal_description' in keys:
            header = headers[keys.index('integrated_multimodal_description')]
            text = text[:header.start(1)] + 'detailed_description' + text[header.end(1):]
        elif not headers and text.strip():
            text = 'detailed_description:\n' + text
        text = 'subject_definitions:\n' + definition + ('\n\n' + text if text else '')
    cast = {**(box.get('cast') or {}), label: entity_id}
    if box.get('schedule'):
        schedule = copy.deepcopy(box['schedule'])
    else:
        linked = [known[target] for target in (box.get('cast') or {}).values() if target in known]
        schedule = {'entities': list(dict.fromkeys(e['id'] for e in linked if e['kind'] != 'place')),
                    'place': next((e['id'] for e in linked if e['kind'] == 'place'), None)}
    if entity['kind'] == 'place':
        schedule['place'] = entity_id
    elif entity_id not in schedule['entities']:
        schedule['entities'].append(entity_id)
    trial = copy.deepcopy(timeline)
    trial['boxes'][index]['prompt'] = text
    slots = rules.box_slots(rules.parse(json.dumps(trial)), index)
    if ((slots.mode == 'ref2va' and len(slots.image_inputs) > rules.MAX_REF_IMAGES)
            or len(slots.audio_inputs) > rules.MAX_REF_AUDIOS or len(slots.video_inputs) > rules.MAX_REF_VIDEOS):
        raise ValueError('Adding this Cast entry exceeds H3’s reference limit.')
    return {'prompts': {box_id: text}, 'casts': {box_id: cast}, 'schedules': {box_id: schedule},
            'subject': label, 'changed': True}


def handle(body):
    """The answer to a bible request: {"ok": True, **result} or {"ok": False, "error": message}."""
    try:
        if not isinstance(body, dict):
            raise ValueError("The request must be a JSON object.")
        action, timeline = body.get("action"), body.get("timeline")
        if action == "assign":
            result = assign(timeline, body.get('box'), body.get('entity'))
        elif action == "build":
            result = build(timeline, body.get("plan"))
        elif action == "link":
            result = link(timeline, body.get("plan"), body.get("boxes"))
        elif action == "apply":
            result = apply(timeline, body.get("bible"), body.get("links"), body.get("force") or (), body.get("merged"))
        elif action == "status":
            result = status(timeline)
        elif action == "recompile":
            result = recompile(timeline, body.get("boxes"))
        else:
            raise ValueError(f"Unknown bible action {action!r}; use build, link, apply, status, recompile or assign.")
    except ValueError as error:
        return {"ok": False, "error": str(error)}
    return {"ok": True, **result}
