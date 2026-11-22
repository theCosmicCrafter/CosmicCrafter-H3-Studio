"""One semantic completion per box, with local H3 layout and reference bindings."""

import dataclasses
import json
import re

from . import h3_prompt_schema as schema, h3_prompt_validate as validate
from . import h3_prompt_compile as compiler, story_instructions, story_prompts as prompts, story_templates, story_stages
from .h3_prompt_ir import SUBJECT_ID
from .timeline import MAX_REF_AUDIOS
from . import timeline as rules


INSTRUCTIONS = """Write ONE clip as JSON. Follow the current creative Guide over conflicting beat details.
Apply per-shot rules to every shot; film opening/ending rules only at the relevant film boundary.
Preserve conditions, exceptions, frequency and exact dialogue. Examples are not required events.
Stage only this box's beat. Fit action complexity and shot count to its NEW time, excluding replay;
allow natural speech, reactions and requested holds. About two spoken words/second TOTAL is a planning
allowance, not a quota; use fewer words during actions and pauses. Never rush mandatory dialogue to fit it.
subject_updates: for each subject modified by the idea, Guide, shared direction or beat, return its ID
and a complete revised description in plain words without IDs or tags. RefMod descriptions are source appearance,
not immutable output. Preserve identity and unchanged traits; replace conflicting clothing, hair,
accessories, colors or other attributes. Put these changes in the subject description, not only a shot.
Use [] if unchanged. Keep timed transformations in shots; describe their starting state in the subject.
Source bindings stay fixed. Appearance/style references are not automatic opening frames; use native frames
in their stated roles. Code supplies H3 labels/tags/bindings. Descriptions are English plain text with subject IDs,
not section headers, @mentions or markup; dialogue, lyrics and quoted visible text keep their original language.
For each shot (one per action stage or view, even with a static camera):
- start_ms: 0 then increasing; clip clock includes replay.
- cut: true for cuts; false for first/continuous sections.
- visible_people: everyone visible, even partial bodies/reflections/arrivals; exclude off-screen voices.
  Respect the Guide's cast limit separately per shot. A box's cast need not appear together.
- subjects: only referenced people/environments/styles used here. Mention each by its supplied ID (subject_1, etc.)
  in composition/actions/camera where it affects the scene. Unreferenced people use ordinary descriptions.
- composition: opening image; actions: new events after replay, with start_ms < end_ms inside this shot.
  Put timing only in numeric fields; do not repeat speech in actions. State simultaneous action explicitly
  within its interval. Camera describes movement/stops. Persistent appearance belongs in subject descriptions.
- dialogue: subject binds the speaker even off-screen (empty if unreferenced); text is verbatim speech,
  without IDs. speaker describes the voice as the continuity sheet describes it; delivery describes how it
  sounds. Use [] for silence.
  Keep lines sequential. Only an explicitly requested interruption/group speech uses overlap=true for
  different speakers. Each line fits inside this shot and its start_ms/end_ms allow natural delivery.
  Keep speaker identity stable; visible speech has matching mouth movement, voiceover does not.
- action.sound: sounds synchronized with permitted actions; do not imply an extra unseen event.
  Continuous ambience goes in overall_soundscape;
  audience-only music or N/A goes in non_diegetic_music. Keep 'No music' out of scene descriptions.
H3 never sees the previous box: write its ending out in full as this clip's opening composition. A cut within
the same scene keeps its place, light, look, ambience and appearances, but adds no extra cast or events to repeat.
Start new events after replay; do not repeat spoken lines or enact the next box. terminal_state records only
the reached location, positions/poses and prop states.
Return the scene, without a compliance report or self-review."""


def earlier_looks(plan, index):
    """The latest description the boxes before box `index` gave each changed subject, by subject name."""
    return {name: text for beat in plan.beats[:index] for name, text in beat.looks.items()}


PARTIAL = "partially_preserved - its identity is retained; its definition replaces conflicting reference attributes."
DEFINITION = re.compile(r"(?m)^(<Subject [1-9]\d*>)\s+is\s+(.+?)\s*$")


def definition(label, description, references):
    """The subject_definitions line Fast writes: `label` is `description`, bound to its pictures."""
    return compiler.sentence(f"{label} is " + compiler.defined(compiler.clause(description),
                                                               {"@" + ref: ["appearance"] for ref in references}))


def definition_lines(prompt):
    """{label: the text after "is"} for each subject line in a prompt's subject_definitions."""
    section = re.search(r"(?ms)^\s*subject_definitions:\s*(.*?)(?=^\s*\w+:|\Z)", prompt or "")
    return dict(DEFINITION.findall(section.group(1))) if section else {}


def edited_definitions(ctx, plan, index):
    """The definitions in box `index` the user changed since Fast wrote them, by subject name. Rewriting the box keeps
    them."""
    current = definition_lines(ctx.boxes[index].prompt)
    return {name: current[item["label"]] for name, item in plan.beats[index].definitions.items()
            if item["label"] in current and (item["edited"] or current[item["label"]] != item["line"])}


def plain(line):
    """A kept definition as writer text, or "" when it is only a picture binding; code supplies the bindings."""
    text = re.sub(r",?\s+(?:in|from)\s+@\w+|@\w+", "", line).strip()
    return text if re.search(r"\w", text) else ""


def follow_pictures(plan, index, kept):
    """`plan` for writing box `index`: a cast member whose kept definition shows one different picture is bound to
    it here, and the box uses that picture instead of the planned one. Other boxes keep the saved cast."""
    cast, beat = dict(plan.cast), plan.beats[index]
    for key, (name, refs) in plan.cast.items():
        new = list(dict.fromkeys(f"{kind}{int(n)}" for kind, n in prompts.rules.MENTION.findall(kept.get(name, ""))
                                 if kind == "image"))
        if len(new) == 1 and len(refs) == 1 and refs != new:
            cast[key] = (name, new)
            swapped = [new[0] if ref == refs[0] else ref for ref in beat.references]
            beat.references = list(dict.fromkeys(swapped if refs[0] in beat.references else swapped + new))
    return dataclasses.replace(plan, cast=cast)


def bindings(ctx, plan, index, context, kept=None):
    """Use existing cast/source metadata; no new image-analysis request or guessed source remapping. A subject keeps
    the definition the user edited in this box, else the look an earlier box gave it."""
    kept = kept or {}
    looks = earlier_looks(plan, index)
    images = set(context.slots.references)
    images.difference_update(context.image_guidance)
    items, covered = [], set()
    for name, refs in plan.cast.values():
        refs = [ref for ref in refs if ref in images]
        if refs:
            items.append((name, refs))
            covered.update(refs)
    items += [(ref.title or ref.name, [ref.name]) for ref in ctx.references
              if ref.name in images - covered and ref.name not in rules.VIDEO_SLOTS]
    return {f"subject_{i}": {"name": name, "references": refs,
                            "description": (plain(kept[name]) if name in kept else looks.get(name))
                                           or " ".join(ctx.descriptions[ref] for ref in refs if ctx.descriptions.get(ref))
                                           or name}
            for i, (name, refs) in enumerate(items, 1)}


def response_schema(context, subjects, summary=False, image=False, stages=None, endings=False):
    """The schema of the writer's reply for a box, with the summary in Ref2VA or when asked for it (`summary`)."""
    text = {"type": "string"}
    clock = {"type": "integer", "minimum": 0, "maximum": context.duration_ms}
    action = schema.obj({"start_ms": clock, "end_ms": clock, "description": schema.TEXT, "sound": text})
    line = schema.obj({"start_ms": clock, "end_ms": clock, "subject": schema.enum(["", *subjects]),
                       "speaker": schema.TEXT, "language": schema.TEXT, "text": schema.TEXT,
                       "delivery": text, "voiceover": {"type": "boolean"}, "overlap": {"type": "boolean"}})
    shot = schema.obj({"start_ms": {"type": "integer", "minimum": 0, "maximum": context.duration_ms - 1},
                       "cut": {"type": "boolean"},
                       "visible_people": schema.array(text), "subjects": schema.choice_array(subjects),
                       "composition": schema.TEXT, "actions": schema.array(action), "camera": text,
                       "dialogue": schema.array(line)})
    if image:
        shot["properties"].update(opening_state=schema.TEXT, ending_state=schema.TEXT, viewpoint=text)
        shot["required"] += ["opening_state", "ending_state", "viewpoint"]
    elif endings:
        shot['properties']['ending_state'] = schema.TEXT
    audio = schema.obj({"reference": schema.enum(context.slots.audios) if context.slots.audios else text,
                        "use": schema.TEXT})
    update = schema.obj({"subject": schema.enum(subjects) if subjects else text, "description": schema.TEXT})
    properties = {"subject_updates": schema.array(update, maximum=len(subjects)),
                  "style": text, "shots": schema.array(shot, 1),
                  "overall_soundscape": text, "non_diegetic_music": text,
                  "audio_references": schema.array(audio, maximum=len(context.slots.audios)),
                  "terminal_state": schema.obj({"setting": text, "positions": text, "props": text})}
    if context.mode == "Ref2VA" or summary:
        properties["summary"] = schema.TEXT
    videos = context.slots.video_inputs
    if videos:
        properties["video_references"] = schema.array(schema.obj({"reference": schema.enum(videos), "use": schema.TEXT}),
                                                       maximum=len(videos))
    if context.image_guidance:
        properties["image_guidance"] = schema.array(schema.obj({
            "reference": schema.enum(context.image_guidance), "use": schema.TEXT}),
            maximum=len(context.image_guidance))
    legacy = schema.obj(properties)
    return story_stages.writer_schema(legacy, stages) if stages is not None else legacy


def messages(ctx, plan, index, final, context, subjects, neighbors, bible=False, summary=False, stages=None):
    """One local beat, its bindings and boundaries, with the current idea's subject direction. With `bible`, the bible
    path's instructions, and no continuity sheet, which the bible replaces; with `summary` too, they ask for the
    summary in any mode."""
    box, beat, slots = ctx.boxes[index], plan.beats[index], context.slots
    lines = [prompts.guide_direction(ctx), f"Story: {plan.title}", *([] if bible else ["Continuity sheet:", plan.sheet]),
             f"Write box {box.number} of {len(ctx.boxes)}: {beat.beat}",
             f"Planned cast across separate shots: {', '.join(beat.on_screen)}", f"End on: {beat.ends}",
             prompts.clock_line(box), f"Clip duration: {context.duration_ms} ms; new events from {context.replayed_ms} ms.",
             "Appearance descriptions (read-only; poses belong in stage/ending state):" if stages is not None else
             story_instructions.SCHEDULED if bible else
             "Subject descriptions so far (revise requested attributes; source bindings stay fixed):",
             json.dumps(subjects, ensure_ascii=False),
             "Original idea (preserve the fixed appearance and assigned events):" if stages is not None else
             story_instructions.IDEA if bible else
             "Original idea (apply subject changes relevant to this box; do not add its other events):", prompts.idea_text(ctx)]
    for role, name in (("first", slots.first), ("last", slots.last)):
        if name:
            lines.append(f"Native {role} frame @{name}: {ctx.descriptions.get(name, ctx.label(name))}")
    audios = [prompts._reference(ctx, ref) for ref in ctx.references if ref.name in slots.audios]
    if audios:
        lines += ["Available audio references:", *audios]
    videos = [prompts._reference(ctx, ref) for ref in ctx.references if ref.name in slots.video_inputs]
    if videos:
        lines += [*prompts.video_guidance(ctx), "Available video references:", *videos,
                  "Use video_references to describe whole-video motion or structure; a visible subject from a "
                  "video still uses its subject binding. Use audio_references for selected video soundtracks."]
    direction = prompts.text_direction(ctx, index)
    if direction:
        lines.append(direction)
    direction = prompts.audio_direction(ctx, index)
    if direction:
        lines.append(direction)
    if index > 0:
        before = ctx.boxes[index - 1]
        previous = (neighbors or {}).get(before.id)
        where = "before the cut to this one" if box.fresh else "just before this one"
        lines += [f"Box {before.number}, {where}, has this intended ending (not a rendered observation): " +
                  (previous["ending"] if previous else plan.beats[index - 1].ends),
                  "Previously spoken lines (do not repeat):",
                  *(previous["said"] if previous else prompts.said_in(final.get(before.id, ""))),
                  f"H3 never sees box {before.number}: state what this box keeps of that ending (place, light, "
                  "looks, poses, props, movement) explicitly, without referring to it."]
    if index + 1 < len(ctx.boxes):
        lines.append(f"Next box (not events for this clip): {plan.beats[index + 1].beat}")
    if ctx.regenerate:
        lines += ["Regenerate only this box. The storyline is fixed: preserve events, dialogue, cast and both boundaries.",
                  "Current prompt:", box.prompt or "(not written yet)"]
        for neighbor in ctx.boxes[max(0, index - 1):index + 2]:
            if neighbor.id != box.id:
                lines += [f"Fixed prompt of box {neighbor.number}:", final.get(neighbor.id) or "(not written yet)"]
    if ctx.shared.strip():
        lines += ["Shared direction (inserted by code; do not repeat):", ctx.shared.strip()]
    if ctx.renderer == "image":
        system = story_instructions.image_writer(ctx.template, model=ctx.image_model)
    elif bible:
        system = story_instructions.writer(context.mode == "Ref2VA" or summary, ctx.template, staged=stages is not None)
    else:
        instructions = INSTRUCTIONS if stages is None else ("Write one box as JSON. Preserve supplied identities, "
                       "references and user-edited appearance. Use English descriptions; dialogue keeps its language.\n"
                       + story_stages.WRITER + "\nstyle: the visual medium and look. "
                       "terminal_state: setting, positions and props.")
        if context.mode == "Ref2VA":
            instructions += ("\nsummary: one or two sentences covering the main action's progression and reached state "
                             "across ALL shots, using supplied subject IDs. Do not repeat the opening composition "
                             "or quote dialogue. Code supplies the task type.")
        system = instructions + "\n\n" + prompts.H3_WRITING_GUIDANCE + "\n\n" + prompts.TRANSITION_GUIDANCE
        if ctx.template is not None:
            system += "\n\n" + story_templates.write_rule(False) + "\n\n" + story_templates.block(ctx.template)
    if context.image_guidance:
        from .story_idea_refs import GUIDANCE
        system += "\n\n" + GUIDANCE
        lines += ["Available guide-only image references:",
                  *(f"@{name}: {ctx.descriptions.get(name, ctx.label(name))}" for name in context.image_guidance)]
    if stages is not None:
        lines.append("Code-owned stages (frame clock; actions and assigned speech happen together):\n"
                     + json.dumps(stages, ensure_ascii=False))
    return [{"role": "system", "content": system},
            {"role": "user", "content": "\n".join(lines),
             "pictures": prompts._box_pictures(ctx, index, slots) if ctx.pictures else []}]


def aliases(subjects):
    """Full names and unambiguous names without a trailing parenthesized description."""
    owners = {}
    for key, item in subjects.items():
        name = item["name"].strip()
        for alias in {name, re.sub(r"\s*\([^()]*\)\s*$", "", name).strip()} - {""}:
            owners.setdefault(alias.casefold(), set()).add(key)
    return {name: next(iter(keys)) for name, keys in owners.items() if len(keys) == 1}


def _interval(event, start, end):
    if not start <= event["start_ms"] < event["end_ms"] <= end:
        raise ValueError(f"action/dialogue interval {event['start_ms']}–{event['end_ms']} ms must be inside "
                         f"its shot ({start}–{end} ms), with end_ms after start_ms")


NO_MUSIC = re.compile(r"(?:no (?:background |non-diegetic )?(?:music|score|soundtrack)|without music)[.!]?", re.I)
PROSE_TIME = re.compile(r"\b\d{1,2}:\d{2}(?:\.\d+)?\b|\b\d+(?:\.\d+)?\s*(?:ms|milliseconds?|seconds?)\b|"
                        r"\b\d+(?:\.\d+)?\s+s\b|\b(?:at|after|before|until|from|to|for|over|during|within)\s+"
                        r"\d+(?:\.\d+)?s\b|\b(?:at|from|to|until)\s+\d+:\d+(?:\.\d+)?\b", re.I)


@dataclasses.dataclass
class BibleBox:
    """How compile_prompt writes a box from the bible."""
    ids: re.Pattern     # entity ids in the reply's prose, like e1
    style: str          # the bible's style line; "" keeps the reply's
    sentences: dict     # entity id: its sentence, for each entity without a picture in the box
    voices: dict        # entity id: voice
    changed: set        # entity ids whose look in force has no picture of its own, or whose wording changed since Write
    line: object        # (label, wording, pictures): the definition line, as story_bible.line
    voice_clips: dict = dataclasses.field(default_factory=dict)  # entity id: the slot of its voice clip


def _voices(data, context, subjects, bible, index):
    """(sent, notes) for box `index`: the voiced characters it sends, as (entity id, slot) in the order of their first
    line, within the audios its frame leaves, and a note for each one it can't send."""
    order = []
    for shot in data["shots"]:
        for line in sorted(shot["dialogue"], key=lambda item: item["start_ms"]):
            if line["subject"] in bible.voice_clips and line["subject"] not in order:
                order.append(line["subject"])
    room = max(0, MAX_REF_AUDIOS - sum(name.startswith("audio") for name in context.slots.audios))
    sent = [(key, bible.voice_clips[key]) for key in order[:room]]
    notes = [f"Box {index + 1}: {subjects[key]['name']} speaks, but H3 takes no more audios there, so "
             f"{subjects[key]['name']}'s voice (@{bible.voice_clips[key]}) isn't sent." for key in order[room:]]
    if sent and context.mode != "Ref2VA" and "summary" not in data:
        notes[:0] = [f"Box {index + 1} was written without a summary, so it can't send {subjects[key]['name']}'s voice; "
                     "write it again to add it." for key, _ in sent]
        sent = []
    return sent, notes


def compile_prompt(data, ctx, plan, index, context, subjects, notes=None, kept=None, bible=None, image=False):
    """Compile validated structured text; contradictory timing is never renderable. With `bible`, the subjects
    are bible entities: only those with pictures get labels, the bible gives the wording, style, sentences and
    voices, and the text comes back without prompts.prompt_text."""
    data = validate.shot_cuts(data)
    image = image or (ctx is not None and ctx.renderer == "image")
    snapshots = any("opening_state" in shot for shot in data.get("shots", []))
    validate.shape(data, response_schema(context, subjects, bible is not None and "summary" in data, snapshots,
                                        endings=True))
    ref2va = context.mode == "Ref2VA"
    sent, voice_notes = _voices(data, context, subjects, bible, index) if bible and bible.voice_clips else ([], [])
    if sent and not ref2va:
        context, ref2va = dataclasses.replace(context, mode="Ref2VA"), True
    updates = {item["subject"]: item["description"].strip() for item in data["subject_updates"]}
    if len(updates) != len(data["subject_updates"]) or any(not text for text in updates.values()):
        raise ValueError("subject_updates must contain one nonempty description per updated subject")
    warnings = []
    starts = [shot["start_ms"] for shot in data["shots"]]
    if starts[0] != 0 or any(b <= a for a, b in zip(starts, starts[1:])):
        raise ValueError("shots must start at zero and have strictly increasing start_ms")
    named = aliases(subjects)
    # A bible box's pictured place is the setting of every shot, listed or not.
    settings = {key for key, item in subjects.items() if bible and item["kind"] == "place" and item["references"]}
    shown = [set(shot["subjects"]) | settings | {named[person.casefold()] for person in shot["visible_people"]
                                               if person.casefold() in named} for shot in data["shots"]]
    voiced = {line["subject"] for shot in data["shots"] for line in shot["dialogue"] if line["subject"]}
    used = set().union(*shown, voiced)
    prose = [data["style"], data["overall_soundscape"], data["non_diegetic_music"]]
    prose += [item["description"] for item in data["subject_updates"]]
    prose += list(data["terminal_state"].values())
    if ref2va:
        prose.append(data["summary"])
    for shot in data["shots"]:
        prose += [shot["composition"], shot["camera"]]
        prose += [shot['ending_state']] if shot.get('ending_state') else []
        prose += [action[key] for action in shot["actions"] for key in ("description", "sound")]
        prose += [line[key] for line in shot["dialogue"] for key in ("speaker", "delivery")]
    if any(PROSE_TIME.search(re.sub(r'"[^"]*"', "", text)) for text in prose):
        raise ValueError("Descriptions or delivery contain timestamps or durations; use the code-owned stage schedule")
    relative = prompts.relative_wording(prose)
    if relative:
        warnings.append("its descriptions say " + ", ".join(f'"{word}"' for word in relative[:4])
                        + ", which assumes H3 saw another moment; H3 renders each box alone, so state it explicitly")
    ids = bible.ids if bible else SUBJECT_ID
    mentioned = set(ids.findall(" ".join(prose)))
    if mentioned - subjects.keys():
        raise ValueError("description names undefined subjects: " + ", ".join(sorted(mentioned - subjects.keys())))
    labels = {name: f"<Subject {i}>" for i, name in enumerate(
        (s for s in subjects if s in used and (bible is None or subjects[s]["references"])), 1)}
    if bible and ref2va:
        warnings += [f"no shot lists {item['name']} in its subjects, so its picture was left out" for key, item in
                     subjects.items() if item["references"] and key not in used]
    alias = "|".join(re.escape(name) for name in sorted(named, key=len, reverse=True))
    # Writers often give a name and its id together, like "Maya (e1)", "Maya's (e1)" or "e1 (Maya)": that is one mention.
    paired = re.compile(rf"(?<!\w)(?:(?:{alias})(?P<s>['’]s)?\s*\((?P<id>{ids.pattern})\)|(?P<key>{ids.pattern})\s*\("
                        rf"(?:{alias})\))(?!\w)", re.I) if named else None

    def called(key):
        return labels.get(key) or subjects[key]["name"]

    def words(text, selected=()):
        if paired:
            text = paired.sub(lambda match: match["key"] or match["id"] + (match["s"] or ""), text)
        # Naming someone as absent or off-screen must not attach their visual reference to this shot.
        names = {name: key for name, key in named.items() if key in selected and key in labels}
        if names:
            text = re.sub(r"(?<!\w)(" + "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)) + r")(?!\w)",
                          lambda m: labels[names[m[0].casefold()]], text, flags=re.I)
        return ids.sub(lambda m: labels[m[0]] if m[0] in selected and m[0] in labels
                       else subjects.get(m[0], {}).get("name", m[0]), text)

    shots, speakers, said = [], {}, []
    music = data["non_diegetic_music"].strip()
    if validate.NOTHING.fullmatch(music) or NO_MUSIC.fullmatch(music):
        music = "N/A"

    def sound(text):
        parts = re.split(r"(?<=[.!?])\s+", text.strip())
        if any(NO_MUSIC.fullmatch(part) for part in parts):
            if music.casefold() != "n/a":
                warnings.append("shot sound says no music but non_diegetic_music specifies a score")
            else:
                parts = [part for part in parts if not NO_MUSIC.fullmatch(part)]
        text = " ".join(parts)
        if re.search(r"\b(?:audience-only|non-diegetic)\b", text, re.I):
            warnings.append("audience-only score belongs in non_diegetic_music, not shot sound")
        return text

    style = bible.style if bible and bible.style else data["style"]
    # A definition the user edited outranks the writer's update for that subject.
    verbatim = {key: kept[item["name"]] for key, item in subjects.items()
                if ref2va and kept and item["name"] in kept}
    updates = {key: text for key, text in updates.items() if key not in verbatim}
    for i, shot in enumerate(data["shots"], 1):
        selected = shown[i - 1]
        end = starts[i] if i < len(starts) else context.duration_ms
        composition = words(shot["composition"], selected)
        cut = f"At {compiler.clock(shot['start_ms'])}, the camera cuts to"
        if i == 1:
            parts = ["[Shot 1]", *([compiler.CONTINUATION] if context.carried_frames else []), composition]
            if context.slots.first:
                # Ref2VA makes every mentioned image a reference picture, and a native guide is not one.
                parts.append("The opening matches the supplied first-frame guide." if ref2va
                             else f"The opening matches @{context.slots.first}.")
        elif not shot["cut"]:
            parts = [f"[Shot {i}] At {compiler.clock(shot['start_ms'])}, the view continues without a cut.", composition]
        elif compiler.FRAMING.match(composition):
            parts = [f"[Shot {i}] {cut} a new shot.", composition]
        else:
            parts = [f"[Shot {i}] " + compiler.sentence(f"{cut} {compiler.clause(composition)}")]
        lead = len(parts)
        parts.append(words(shot["camera"], selected))
        events = []
        for action in shot["actions"]:
            _interval(action, max(shot["start_ms"], context.replayed_ms), end)
            text = words(action["description"], selected).strip()
            noise = words(sound(action["sound"]), selected)
            if noise.strip():
                text = (text + (" " if text[-1:] in ".!?" else ". ") if text else "") + compiler.sentence(noise)
            events.append((action["start_ms"], action["end_ms"], text))
        active = []
        for line in sorted(shot["dialogue"], key=lambda item: item["start_ms"]):
            _interval(line, max(shot["start_ms"], context.replayed_ms), end)
            subject = line["subject"]
            if subject and not line["voiceover"] and subject not in selected:
                raise ValueError(f"shot {i}: on-screen dialogue subject {subject} is missing from the shot's subjects")
            speaker = bible.voices[subject] if bible and subject in bible.voices else words(line["speaker"], used)
            identity = subject or speaker.casefold()
            sid = speakers.setdefault(identity, f"S{len(speakers) + 1}")
            active = [(who, until) for who, until in active if until > line["start_ms"]]
            if any(who == identity for who, _ in active) or (active and not line["overlap"]):
                raise ValueError(f"shot {i}: dialogue intervals overlap without distinct, explicitly simultaneous speakers")
            active.append((identity, line["end_ms"]))
            voice = called(subject) if subject else speaker
            description = (re.sub(rf"^{re.escape(voice)}(?:\s*[,;:-]\s*|\s+|$)", "", speaker).strip().rstrip(".,")
                           if subject else "")
            modifiers = [part for part in (description, words(line["delivery"], used).strip().rstrip(".,")) if part]
            cue = "says in an off-screen voiceover" if line["voiceover"] else "says"
            delivery = f", {', '.join(modifiers)}," if modifiers else ""
            spoken = f"{voice} ({sid}){delivery} {cue}: <d>[{line['language']}] {line['text']}</d>"
            if line["voiceover"] and (subject in selected or not subject):
                spoken += (f" while {voice}'s lips remain completely closed." if subject
                           else " while the corresponding on-screen character's lips remain completely closed.")
            if active[:-1]:
                spoken = "Overlapping the preceding speech, " + spoken
            events.append((line["start_ms"], line["end_ms"], spoken))
            said.append(line["text"])
        simultaneous = {}
        for start, stop, text in sorted(events, key=lambda event: event[0]):
            simultaneous.setdefault((start, stop), []).append(text)
        parts += [f"From {compiler.clock(start)} to {compiler.clock(stop)}: "
                  + " At the same time, ".join(compiler.sentence(text) for text in texts)
                  for (start, stop), texts in simultaneous.items()]
        if not image and shot.get('ending_state'):
            parts.append(f"By {compiler.clock(end)}, end this action with: "
                         + compiler.sentence(words(shot['ending_state'], selected))
                         + " Keep that reached state; do not begin a later action.")
        # A place the box defines or describes in its own sentence needs no naming in the shots set there.
        missing = [subject for subject in selected if called(subject) not in " ".join(parts) + words(style, used)
                   and subject not in settings
                   and not (bible and subjects[subject]["kind"] == "place" and subject in bible.sentences)]
        if missing:
            warnings.append(f"shot {i}: describe each selected subject where it appears; unused: " + ", ".join(sorted(missing)))
        # H3 ties a picture to a shot only through its label in the shot's text.
        unnamed = [label for key, label in labels.items() if key in missing]
        if unnamed:
            parts.insert(lead, compiler.sentence(f"{compiler.listing(unnamed)} {'is' if len(unnamed) == 1 else 'are'} "
                                                 "in this shot"))
        if i == len(data["shots"]) and context.slots.last:
            parts.append("The final composition converges on the supplied last-frame guide." if ref2va
                         else f"The final composition converges on @{context.slots.last}.")
        shots.append(" ".join(part for part in parts if part.strip()))
    props = [called(key) for key in subjects if key in used and subjects[key].get('kind') == 'prop']
    inventory = []
    if not image and props and any(shot.get('ending_state') for shot in data['shots']):
        inventory = ["Named prop identities: " + compiler.listing(props) + ". Each name denotes the single item "
                     "or defined group described above. Every mention refers to that same physical instance, "
                     "including when it moves; no additional copy appears at its destination."]
    visual = (words(style, used) + "\n" + "\n".join([*(bible.sentences.values() if bible else []), *inventory, *shots])).strip()
    fields = []
    if ref2va:
        audios = {item["reference"]: compiler.sentence(words(item["use"], used)) for item in data["audio_references"]}
        videos = {item["reference"]: compiler.sentence(words(item["use"], used)) for item in data.get("video_references", [])}
        if bible:
            definitions = [bible.line(label, subjects[name]["wording"] or subjects[name]["name"],
                                      subjects[name]["references"]) for name, label in labels.items()]
        else:
            definitions = [f"{label} is {verbatim[name]}" if name in verbatim else
                           definition(label, updates.get(name, subjects[name]["description"]), subjects[name]["references"])
                           for name, label in labels.items()]
        definitions += [f"@{name} is an audio reference: {use}" for name, use in audios.items()]
        definitions += [f"@{name} is a video reference: {use}" for name, use in videos.items()]
        definitions += [f"@{slot} is the voice-timbre reference for {called(key)} ({speakers[key]})." for key, slot in sent]
        guide_groups, seen_guides = {}, set()
        for item in data.get("image_guidance", []):
            if item["reference"] in seen_guides:
                raise ValueError("image_guidance repeats an image reference")
            seen_guides.add(item["reference"])
            use = compiler.sentence(words(item["use"], used))
            guide_groups.setdefault(use, []).append("@" + item["reference"])
        guide_lines = []
        for number, (use, pictures) in enumerate(guide_groups.items(), len(labels) + 1):
            label = f"<Subject {number}>"
            definitions.append(f"{label} is visual guidance from {compiler.listing(pictures)}: {use} "
                               "Do not reproduce the source images, their layouts, depicted people, objects or text.")
            guide_lines.append((label, use))
        if guide_lines:
            visual = " ".join(f"Apply {label} only for its stated visual attributes."
                              for label, _ in guide_lines) + "\n" + visual
        if bible:
            changed = set(bible.changed)
        else:
            looks = earlier_looks(plan, index)
            changed = set(updates) | set(verbatim) | {name for name, item in subjects.items() if item["name"] in looks}
        retention = []
        for name, label in labels.items():
            where = ", ".join(f"[Shot {number}]" for number, chosen in enumerate(shown, 1) if name in chosen)
            retention.append(f"{label}{f' (appears in {where})' if where else ''}: " + (
                PARTIAL if name in changed else "fully_preserved - the appearance shown in its reference is retained."))
        retention += [f"@{name}: reference - {use}" for name, use in audios.items()]
        retention += [f"@{name}: weak_reference - {use}" for name, use in videos.items()]
        retention += [f"@{slot}: reference - {called(key)} ({speakers[key]}) follows @{slot}'s voice timbre and measured "
                      "delivery without copying the original signal." for key, slot in sent]
        retention += [f"{label}: weak_reference - {use} The source scene does not appear in the video."
                      for label, use in guide_lines]
        tasks = (["keyframe completion"] if context.slots.first or context.slots.last else []) + ["reference generation"]
        if audios or sent:
            tasks.append("audio reference")
        fields += [("subject_definitions", "\n".join(definitions)),
                   ("summary", f"[{' + '.join(tasks)}] " + words(data["summary"], used)
                    + (" Visual attributes are guided by " + compiler.listing([label for label, _ in guide_lines])
                       + "; the source images do not appear." if guide_lines else "")),
                   ("retention_analysis", "\n".join(retention)),
                   ("detailed_description", visual)]
    else:
        fields.append(("integrated_multimodal_description", visual))
    fields += [("overall_soundscape", words(sound(data["overall_soundscape"]), used) or "N/A"),
               ("non_diegetic_music", words(music, used))]
    line = compiler.alignment(context, len(shots))
    text = (line + "\n\n" if line else "") + "\n\n".join(f"{key}:\n{value}" for key, value in fields if value)
    if bible is None:
        text = prompts.prompt_text(text, ctx, index, context, plan, notes)
    lines = definition_lines(text) if ref2va else {}
    recorded = {subjects[key]["name"]: {"label": label, "line": lines[label], "edited": key in verbatim}
                for key, label in labels.items() if label in lines}
    state = {**{key: words(value) for key, value in data["terminal_state"].items()}, "look": words(style),
             "ambience": words(data["overall_soundscape"])}
    if notes is not None:
        notes.extend(f"Box {index + 1}: Warning: {warning}. Prompt kept; edit it in the Timeline."
                     for warning in dict.fromkeys(warnings))
        notes.extend(voice_notes)
    details = {"ending": json.dumps(state, ensure_ascii=False), "said": said,
               "looks": {subjects[name]["name"]: description for name, description in updates.items()},
               "definitions": recorded}
    if bible:
        details["cast"] = {label: key for key, label in labels.items()}
    if voice_notes:
        details["voice_notes"] = voice_notes
    if image:
        text = image_prompt(data, subjects, bible)
    return text, details


def image_prompt(data, subjects, bible=None):
    """Static storyboard display text; retain the unmodified temporal source for video compilation."""
    ids = bible.ids if bible else SUBJECT_ID
    def words(value):
        def replace(match):
            entity = subjects.get(match[0])
            if entity is None:
                return match[0]
            pictures = ["@" + slot for slot in entity["references"] if slot.startswith("image")]
            return entity["name"] + (" from " + ", ".join(pictures) if pictures else "")
        return ids.sub(replace, value).strip()
    parts = [words(bible.style if bible and bible.style else data["style"])]
    for number, shot in enumerate(data["shots"], 1):
        # These markers belong to the storyboard editor; frame projection removes them before image submission.
        ms = shot["start_ms"]
        marker = f"[Shot {number}] At {ms // 60000:02}:{ms // 1000 % 60:02}.{ms % 1000:03},"
        parts.append(marker + " " + words(shot.get("opening_state", shot["composition"])) + " " + words(shot.get("viewpoint", "")))
    return "\n\n".join(part for part in parts if part)
