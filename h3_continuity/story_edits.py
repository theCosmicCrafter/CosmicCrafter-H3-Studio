"""Faithful revisions: exact patches to existing prompts, published only after validation."""

import copy
import json
import re

from . import h3_prompt_ir, h3_prompt_schema, h3_prompt_validate, llm, story_fast, story_prompts, story_templates
from .timeline import MENTION

HEADERS = re.compile(r"(?m)^\s*(subject_definitions|summary|retention_analysis|detailed_description|"
                     r"integrated_multimodal_description|overall_soundscape|non_diegetic_music):")
REVISE = """Revise the existing H3 story as faithfully as possible, incorporating only the requested change.
Return exact text patches. Each before fragment must appear EXACTLY ONCE in its box's current prompt.
Use sufficient surrounding context to disambiguate. Leave unrelated prompts, shots, actions, dialogue, sound,
timing, tags and section headers byte-for-byte unchanged. Do not rewrite the story from the original idea.
Subject numbers are LOCAL to each box. Match identity using the selected definition and logical image binding.
Update shared direction only if necessary, using a patch with box='shared'. It must not override changed definitions."""
INSTRUCTIONS = REVISE + """
sheet is the minimally updated continuity sheet; outline contains only changed box beats. No new boxes.
Return JSON with changes, sheet and outline."""
WITH_BIBLE = REVISE + """
outline contains only changed box beats. No new boxes.
Return JSON with changes and outline."""
SOURCES = """A box given as "source" instead of "prompt" is the writer's reply as indented JSON; code compiles its
prompt from it and the bible. Patch that text the same way and keep it valid JSON with the same keys: keep every
start_ms and end_ms, each shot's subjects, each line's subject and the subject_updates, and name entities only by
their ids (e1, e2...), which entities maps to their names."""
BIBLE_CHANGE = """This is a bible change: request.entity's wording changed from before to after in each listed box,
and code already writes the new wording into its definition line or its sentence. Patch only other text in those
boxes that still states details the new wording replaces, such as clothing, colours, hair, wetness or held props,
and keep the rest. Return no changes when nothing conflicts."""


def validate(ctx, edit):
    kind = edit.get("kind") if isinstance(edit, dict) else None
    if kind not in ("feedback", "bible"):
        raise ValueError("Choose feedback or bible.")
    if not ctx.boxes or not any(box.prompt.strip() for box in ctx.boxes):
        raise ValueError("Write a story before editing it.")
    if kind == "bible":
        return _bible_edit(ctx, edit)
    if not isinstance(edit.get("box"), str) or edit["box"] not in {box.id for box in ctx.boxes}:
        raise ValueError("Select an existing Timeline box.")
    if not isinstance(edit.get("text"), str) or not edit["text"].strip():
        raise ValueError("Enter feedback first.")
    return dict(edit)


def _bible_edit(ctx, edit):
    """The bible revision `edit` with only its kind, its entity and each listed box's wording before and after."""
    entity = edit.get("entity")
    if ctx.bible is None or not isinstance(entity, str) or entity not in {item["id"] for item in ctx.bible["entities"]}:
        raise ValueError("Choose an entity in the bible.")
    wording, fields, ids = edit.get("wording"), ("box", "before", "after"), {box.id for box in ctx.boxes}
    if not isinstance(wording, list) or not wording or not all(
            isinstance(item, dict) and all(isinstance(item.get(key), str) for key in fields) and item["box"] in ids
            for item in wording) or len({item["box"] for item in wording}) != len(wording):
        raise ValueError("List each box whose wording changed once, with the wording before and after.")
    return {"kind": "bible", "entity": entity, "wording": [{key: item[key] for key in fields} for item in wording]}


def definition_labels(text):
    sections = list(HEADERS.finditer(text))
    for index, section in enumerate(sections):
        if section[1] == "subject_definitions":
            end = sections[index + 1].start() if index + 1 < len(sections) else len(text)
            return re.findall(r"<Subject \d+>", text[section.end():end])
    return []


def _check(ctx, before, after):
    """Raises ValueError when `after`, a revision of the prompt `before`, changes what a revision must keep."""
    if HEADERS.findall(after) != HEADERS.findall(before):
        raise ValueError("A revision changed H3 section headers; the original prompts were kept.")
    if re.findall(r"<d>[\s\S]*?</d>", after, re.I) != re.findall(r"<d>[\s\S]*?</d>", before, re.I):
        raise ValueError("A revision changed exact dialogue; replan its stages to change the words")
    # Dialogue may contain literal labels/time-like text; it is not an H3 syntax channel.
    before_prose = re.sub(r"<d>[\s\S]*?</d>", "", before)
    after_prose = re.sub(r"<d>[\s\S]*?</d>", "", after)
    labels = r"<(?:Subject|Picture|Audio|Video) \d+>"
    if set(re.findall(labels, after_prose)) - set(re.findall(labels, before_prose)):
        raise ValueError("A revision introduced an undefined subject or transport label.")
    if definition_labels(after_prose) != definition_labels(before_prose):
        raise ValueError("A revision changed the existing subject definitions; the original prompts were kept.")
    if re.findall(r"\[Shot \d+\]", after_prose) != re.findall(r"\[Shot \d+\]", before_prose):
        raise ValueError("A revision changed the existing shot labels.")
    clocks = r"(?<![\w:])(\d{2}):(\d{2})\.(\d{3})(?!\d)"
    if re.findall(clocks, after_prose) != re.findall(clocks, before_prose):
        raise ValueError("A revision changed the existing timestamps; the original prompts were kept.")
    unknown = {f"{kind}{int(n)}" for kind, n in MENTION.findall(after)} - story_prompts.mentionable(ctx)
    if unknown:
        raise ValueError("A revision used an unconnected reference: " + ", ".join(sorted(unknown)))


def _skeleton(reply):
    """What a revision keeps of a writer's reply: each shot's start, cut and subjects, its action times, its line times
    and speakers, and the look changes."""
    return ([(shot["start_ms"], shot.get("cut", index > 0), shot["subjects"],
              [(item["start_ms"], item["end_ms"]) for item in shot["actions"]],
              [(line["start_ms"], line["end_ms"], line["subject"]) for line in shot["dialogue"]])
             for index, shot in enumerate(reply["shots"])], reply["subject_updates"])


def _patched_reply(number, before, after, schema):
    """The writer's reply in `after`, a revision of `before`, box `number`'s source reply as indented JSON. Raises
    ValueError unless it is a reply the writer could have given, with the same skeleton and no entity `before`
    didn't name."""
    from . import story_bible_write
    try:
        reply = json.loads(after)
    except ValueError:
        raise ValueError(f"A revision broke box {number}'s source; the original prompts were kept.") from None
    try:
        h3_prompt_validate.shape(reply, schema)
    except ValueError as error:
        raise ValueError(f"A revision broke box {number}'s source: {error}; the original prompts were kept.") from None
    named = lambda text: set(story_bible_write.ENTITY.findall(text))
    if _skeleton(reply) != _skeleton(json.loads(before)) or named(after) - named(before):
        raise ValueError(f"A revision changed box {number}'s shot times, subjects or looks; the original prompts "
                         "were kept.")
    return reply


def _sources(ctx):
    """{box id: its source's reply as indented JSON} for each box whose prompt is what its source compiles to."""
    from . import story_bible_write
    if ctx.bible is None:
        return {}
    ids = [box.id for box in ctx.boxes]
    found = {}
    for index, box in enumerate(ctx.boxes):
        source = ctx.box_fields.get(box.id, {}).get("source")
        made = story_bible_write.compiled({"source": source}, ctx.bible, ids, index)
        if made is not None and made[0] == box.prompt:
            found[box.id] = json.dumps(source["reply"], indent=2, ensure_ascii=False)
    return found


def apply_changes(ctx, changes, sources=None, boxes=None):
    """{box id or "shared": {"before": prompt, "text": new prompt}} for `changes`, published only when every patch
    applies and passes the checks. A box in `sources` ({box id: its source as indented JSON}) is patched in that
    text, which must stay a source the writer could have given; the box recompiles, and its change also has the new
    "source" and "cast". `boxes`, a set of box ids, limits the patches to those boxes, without shared direction."""
    from . import story_bible_write
    if not isinstance(changes, list):
        raise ValueError("The revision needs a list of changes.")
    sources = sources or {}
    original = {box.id: sources.get(box.id, box.prompt) for box in ctx.boxes if boxes is None or box.id in boxes}
    if boxes is None:
        original["shared"] = ctx.shared
    final = dict(original)
    spans = {}
    for change in changes:
        if not isinstance(change, dict):
            raise ValueError("Invalid story change.")
        box, before, after = (change.get(key) for key in ("box", "before", "after"))
        if not isinstance(box, str) or box not in original or not isinstance(before, str) or not before or not isinstance(after, str):
            raise ValueError("A change needs an existing box and before/after text.")
        if original[box].count(before) != 1:
            raise ValueError("A story change must match a unique fragment; the original prompts were kept.")
        start = original[box].index(before)
        end = start + len(before)
        if any(start < right and end > left for left, right, _ in spans.get(box, [])):
            raise ValueError("Story changes overlap; the original prompts were kept.")
        spans.setdefault(box, []).append((start, end, after))
    for box, edits in spans.items():
        for start, end, after in sorted(edits, reverse=True):
            final[box] = final[box][:start] + after + final[box][end:]
        if box not in sources:
            _check(ctx, original[box], final[box])
    ids = [box.id for box in ctx.boxes]
    published = {}
    for key, text in final.items():
        if text == original[key]:
            continue
        if key not in sources:
            published[key] = {"before": original[key], "text": text}
            continue
        index = ids.index(key)
        box, source = ctx.boxes[index], ctx.box_fields[key]["source"]
        reply = _patched_reply(box.number, original[key], text,
                               story_bible_write.source_schema(source, ctx.bible, ids, index))
        if reply == source["reply"]:
            continue
        patched = {"reply": reply, "frame": copy.deepcopy(source["frame"])}
        recompiled, details = story_bible_write.compile_source(patched, ctx.bible, ids, index)
        _check(ctx, box.prompt, recompiled)
        published[key] = {"before": box.prompt, "text": recompiled, "source": patched, "cast": details["cast"]}
    return published


def retained(before, after):
    """`after` with each subject whose definition differs from `before` marked partially preserved."""
    old = story_fast.definition_lines(before)
    for label, line in story_fast.definition_lines(after).items():
        if old.get(label) != line:
            after = re.sub(rf"(?m)^({re.escape(label)}[^\n:]*:[ \t]*)fully_preserved\b[^\r\n]*",
                           lambda match: match[1] + story_fast.PARTIAL, after)
    return after


def revised_plan(plan, result, changes):
    """The saved Story plan after this revision: its beats and sheet, and no stale ending for a changed box."""
    if not isinstance(plan, dict) or not isinstance(plan.get("boxes"), list):
        return None
    plan = copy.deepcopy(plan)
    plan["sheet"] = result["sheet"]
    beats = {item.get("box"): item.get("beat") for item in result["outline"]
             if isinstance(item, dict) and isinstance(item.get("beat"), str)}
    entries = [entry for entry in plan["boxes"] if isinstance(entry, dict)]
    for entry in entries:
        if entry.get("id") in beats:
            entry["beat"] = beats[entry["id"]]
        if entry.get("id") in changes:
            entry.pop("terminal_state", None)
    return plan


async def write(job, edit):
    # Local import keeps the job lifecycle in story_job, including its single-call provider policy.
    from .story_job import Chat
    ctx = job.ctx
    edit = validate(ctx, edit)
    saved = getattr(job, "previous_story", {})
    request, listed = edit, None
    if edit["kind"] == "bible":
        entity = next(item for item in ctx.bible["entities"] if item["id"] == edit["entity"])
        request = {**edit, "entity": {key: entity[key] for key in ("id", "name", "kind")}}
        listed = {item["box"] for item in edit["wording"]}
    shown = [box for box in ctx.boxes if listed is None or box.id in listed]
    sources = {key: text for key, text in _sources(ctx).items() if listed is None or key in listed}
    bible = ctx.bible is not None
    payload = {"request": request, "idea": story_prompts.idea_text(ctx), "guide": ctx.guide,
               **({} if ctx.template is None else {"template": story_templates.block(ctx.template)}), "shared": ctx.shared,
               **({} if bible else {"sheet": saved.get("sheet", "")}), "outline": saved.get("outline", []),
               "reference_descriptions": ctx.descriptions,
               "previous_reference_descriptions": {ref: item["text"] for ref, item in ctx.timeline.reference_descriptions.items()},
               "boxes": [{"id": box.id, **({"source": sources[box.id]} if box.id in sources
                                           else {"prompt": box.prompt}), "seconds": box.frames / 24}
                         for box in shown]}
    if sources:
        payload["entities"] = {item["id"]: item["name"] for item in ctx.bible["entities"]}
    text = {"type": "string"}
    ids = [box.id for box in shown]
    change = h3_prompt_schema.obj({"box": h3_prompt_schema.enum(["shared", *ids] if listed is None else ids),
                                  "before": text, "after": text})
    outline = h3_prompt_schema.obj({"box": h3_prompt_schema.enum(ids), "beat": text})
    schema = h3_prompt_schema.obj({"changes": h3_prompt_schema.array(change), **({} if bible else {"sheet": text}),
                                   "outline": h3_prompt_schema.array(outline)})
    job.report("Incorporating feedback..." if listed is None
               else f"Updating the prose for {request['entity']['name']}...")
    system = ((WITH_BIBLE if bible else INSTRUCTIONS) + ("\n" + SOURCES if sources else "")
              + ("" if listed is None else "\n" + BIBLE_CHANGE)
              + ("" if ctx.template is None else "\n" + story_templates.EDIT_RULE))
    try:
        reply = await Chat(job).ask([{"role": "system", "content": system},
                                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
                                   h3_prompt_schema.reply_format("h3_story_edit", schema))
    except llm.ChatError as error:
        if error.partial:
            job.drafts['revision'] = {'reply': llm.scrub(error.partial, job.key), 'error': str(error)}
        raise
    try:
        data = h3_prompt_ir.parse_json(reply)
        changes = apply_changes(ctx, data.get("changes"), sources, listed)
    except ValueError as error:
        job.drafts['revision'] = {'reply': llm.scrub(reply, job.key), 'error': str(error)}
        raise
    shared = changes.pop("shared", None)
    for key, change in changes.items():
        if key in sources:
            continue
        change["text"] = retained(change["before"], change["text"])
        fields = ctx.box_fields.get(key, {})
        change.update({name: copy.deepcopy(fields[name]) for name in ("cast", "source") if name in fields})
    sheet = saved.get("sheet", "") if bible else data.get("sheet", saved.get("sheet", ""))
    result = {"job": job.id, "revision": True, "title": saved.get("title", ""), "sheet": sheet,
              "outline": copy.deepcopy(saved.get("outline", [])), "suggestions": saved.get("suggestions", []),
              "plan": None, "prompts": changes, "failed": [], "notes": list(job.notes),
              "reference_descriptions": {"before": ctx.timeline.reference_descriptions,
                                         "value": ctx.reference_descriptions}}
    if ctx.idea_images:
        result["idea_descriptions"] = ctx.idea_descriptions
    if ctx.idea_references:
        from .story_idea_refs import used_pictures
        result["pictures"] = used_pictures(ctx, [item["text"] for item in changes.values()])
        result["pictures_before"] = {item["slot"]: ctx.idea_picture_before.get(item["slot"])
                                     for item in result["pictures"]}
    for item in data.get("outline", []):
        if not isinstance(item, dict) or item.get("box") not in {box.id for box in ctx.boxes} or not isinstance(item.get("beat"), str):
            raise ValueError("The revision returned an invalid outline.")
        found = next((beat for beat in result["outline"] if beat["box"] == item["box"]), None)
        if found is not None:
            found["beat"] = item["beat"]
    if not isinstance(result["sheet"], str):
        raise ValueError("The revised continuity sheet must be text.")
    if shared:
        result["shared"] = shared
    result["plan"] = revised_plan(saved.get("plan"), result, changes)
    return result
