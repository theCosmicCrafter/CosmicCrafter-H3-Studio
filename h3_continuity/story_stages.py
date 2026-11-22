"""Planned events and exact speech, scheduled once on the box's frame clock."""

import copy
import math
import re

from . import h3_prompt_schema as schema, h3_prompt_validate as validate, story_audio as audio
from .timing import FPS
from .timeline import GRID, MAX_FRAMES

RULES = """Plan stages for every box you write. A stage is one action with any speech happening at the same time,
not necessarily a camera cut. Give each stage duration_ms as a natural duration estimate, cut (false unless
the camera cuts), action (the assigned visible event), and dialogue ([] for silence). The first stage always
has cut=false: the box's own cut/join controls its opening. Only later stages can cut within the box. Each line has speaker
(cast name or bible id), voice (a short voice description), language, text (exact words), voiceover and overlap.
Sequential lines need separate stages; multiple lines in one stage are simultaneous, with overlap=true on
every line after the first, only for requested group speech or interruption. Never overlap a speaker with themself.
Preserve ALL mandatory dialogue verbatim, including its order and repetitions. Assign each occurrence once,
to one stage of one box. Budget at least 400 ms per spoken word and time for the action; do not rush content.
Code allocates stages inside the final box length, after replay. The writer only stages those events and
performs those exact lines; it cannot create timestamps or additional speech. Code copies each action verbatim
into its box's prompt, and H3 renders each box alone. Write each action as one present-tense sentence that reads
alone: who acts (cast name or bible id), what they do, to what, and where; a body part names its owner. A continuous
action may span boxes: each box describes the part it shows in full, never as a continuation (no "continues",
"again" or "already"), without repeating its opening, speech or completed actions."""

WRITER = """Use the supplied stage schedule. Return exactly its stage ids and dialogue ids; code determines their order.
For each stage give visible_people, subjects, composition, camera, action {sound}, and dialogue
{line_id: {delivery}}. Code supplies each stage's cut, timestamps, speakers, language and exact words.
Code also supplies the planned action verbatim. Do not replace or paraphrase it.
Use the typed audio fields for sound and vocal performance; never repeat spoken words there.
The action and speech share that stage's interval and happen together. Describe only its assigned action;
do not add speech in descriptions or change the planned events. No timestamps or durations in descriptions.
The first stage's composition is the clip's opening image, written out in full, because H3 reads nothing
else about it: shot size and camera position, the place and its light, where each subject is, their pose,
what each hand holds and any movement under way with its direction. In a box that opens with replayed frames,
that image is the intended ending of the box before, stated as a present state, and its camera line states
that framing and movement explicitly. Do not restage it as a new event or repeat a completed action.
The ending is a target for this box, not an observation of a rendered clip. Reach it without starting the
next box's event. Keep each named prop the same physical item as it moves. terminal_state records the
intended endpoint.""" + "\n" + audio.RULES


def plan_schema():
    line = schema.obj({"speaker": schema.TEXT, "voice": schema.TEXT, "language": schema.TEXT,
                       "text": schema.TEXT, "voiceover": {"type": "boolean"}, "overlap": {"type": "boolean"}})
    return schema.array(schema.obj({"duration_ms": {"type": "integer", "minimum": 1,
                                                  "maximum": round(MAX_FRAMES * 1000 / FPS)},
                                    "cut": {"type": "boolean"}, "action": schema.TEXT,
                                    "dialogue": schema.array(line, maximum=16)}), 1, 32)


def read(value):
    validate.shape(value, plan_schema(), "stages")
    value = copy.deepcopy(value)
    value[0]["cut"] = False  # The Timeline owns the opening cut, including when there is no replay.
    for stage in value:
        seen = set()
        for index, line in enumerate(stage["dialogue"]):
            who = line["speaker"].casefold()
            if who in seen or index and not line["overlap"]:
                raise ValueError("Sequential dialogue needs separate stages; simultaneous speech needs distinct speakers")
            seen.add(who)
    return value


def speech_frames(text):
    return math.ceil(len(re.findall(r"\S+", text)) * 0.4 * FPS)


def allocate(weights, minimums, frames):
    if sum(minimums) > frames:
        raise ValueError(f"Stages need at least {sum(minimums) / FPS:.3f} new seconds, but this box has "
                         f"{frames / FPS:.3f}; split or replan the box without shortening dialogue")
    active, assigned, left = set(range(len(weights))), {}, frames
    while active:
        total = sum(weights[index] for index in active)
        short = [index for index in active if left * weights[index] / total < minimums[index]]
        if not short:
            shares = {index: left * weights[index] / total for index in active}
            assigned.update({index: math.floor(value) for index, value in shares.items()})
            remainder = frames - sum(assigned.values())
            for index in sorted(active, key=lambda index: (-(shares[index] % 1), index))[:remainder]:
                assigned[index] += 1
            break
        for index in short:
            assigned[index] = minimums[index]
            left -= minimums[index]
            active.remove(index)
    return [assigned[index] for index in range(len(weights))]


def freeze(stages, frames, carried, subjects, ending=""):
    stages = read(stages)
    names = {re.sub(r"^(?:the|a|an)\s+", "", item["name"].casefold()): key for key, item in subjects.items()}
    durations = [stage["duration_ms"] for stage in stages]
    natural = [max(1, round(duration * FPS / 1000)) for duration in durations]
    if sum(natural) > frames + GRID:
        raise ValueError("The planned stages exceed this box's new time; split or replan instead of accelerating the action")
    # Only the Timeline's frame-grid rounding may reduce the planner's natural duration estimates.
    scale = min(1, frames / sum(natural))
    minimums = [max([1, math.floor(length * scale),
                     *(speech_frames(line["text"]) for line in stage["dialogue"])])
                for stage, length in zip(stages, natural)]
    lengths = allocate(durations, minimums, frames)
    result, start = {}, carried
    for index, (stage, length) in enumerate(zip(stages, lengths), 1):
        lines = {}
        for number, line in enumerate(stage["dialogue"], 1):
            who = line["speaker"].casefold()
            subject = who if who in subjects else names.get(re.sub(r"^(?:the|a|an)\s+", "", who), "")
            voice = subjects.get(subject, {}).get("voice") or line["voice"]
            if not subject:
                if re.fullmatch(r"(?:e|subject_)[1-9]\d*", who):
                    raise ValueError(f"Dialogue speaker {line['speaker']} is not scheduled in this box")
                voice = f"{line['speaker']}, {voice}"
            lines[f"line_{number}"] = {"subject": subject, "speaker": voice, "language": line["language"],
                                        "text": line["text"], "voiceover": line["voiceover"],
                                        "overlap": number > 1}
        result[f"stage_{index}"] = {"start_frame": start, "end_frame": start + length,
                                    "cut": index > 1 and stage["cut"], "action": stage["action"],
                                    "action_owned": True, "audio_owned": True, "dialogue": lines}
        start += length
    if ending:
        result[f"stage_{len(stages)}"]["ending"] = ending
    # The writer always writes the opening composition and camera: H3 reads each box alone. A schedule saved
    # with a code-owned "opening" still expands and validates with it.
    return result


def writer_schema(legacy, stages):
    result = copy.deepcopy(legacy)
    shot = result["properties"].pop("shots")["items"]["properties"]
    typed = next(iter(stages.values())).get("audio_owned", False)
    if typed:
        for key, value in audio.fields_schema()['properties'].items():
            if key == 'audio_references':
                result['properties'][key]['items']['properties']['use'] = value['items']['properties']['use']
            else:
                result['properties'][key] = value
        result['properties']['subject_updates']['maxItems'] = 0
    entries = {}
    for key, stage in stages.items():
        action = schema.obj({"sound": audio.effects_schema() if typed else {"type": "string"}}
                            | ({} if stage.get("action_owned") else {"description": schema.TEXT}))
        fields = ("visible_people", "subjects") if stage.get("opening") else ("visible_people", "subjects", "composition", "camera")
        entries[key] = schema.obj({name: shot[name] for name in fields}
                                 | {"action": action, "dialogue": schema.obj({
                                     line: schema.obj({"delivery": audio.delivery_schema() if typed else {"type": "string"}})
                                     for line in stage["dialogue"]})})
    result["properties"]["stages"] = schema.obj(entries)
    result["required"] = ["stages" if key == "shots" else key for key in result["required"]]
    return result


def expand(reply, stages):
    """Canonical stored shots retain existing source/edit/reference consumers; their clocks come only from code."""
    result = {key: copy.deepcopy(value) for key, value in reply.items() if key != "stages"}
    typed = next(iter(stages.values())).get("audio_owned", False)
    if typed:
        if reply['subject_updates']:
            raise ValueError("Appearance is read-only for stage writers; poses belong in terminal_state")
        fields = {key: copy.deepcopy(reply[key]) for key in audio.fields_schema()['properties']}
        result.update(audio.fields(fields))
        next(iter(stages.values()))['audio_fields'] = fields
    result["shots"] = []
    if set(reply["stages"]) != set(stages):
        raise ValueError("Stage ids and order must match the supplied schedule")
    for index, (key, stage) in enumerate(stages.items()):
        value = reply["stages"][key]
        if set(value["dialogue"]) != set(stage["dialogue"]):
            raise ValueError(f"{key}'s dialogue ids and order must match the supplied lines")
        if typed:
            chosen = dict(sound=copy.deepcopy(value['action']['sound']),
                          dialogue={name: copy.deepcopy(item['delivery']) for name, item in value['dialogue'].items()})
            validate.shape(chosen, audio.stage_schema(stage['dialogue']), 'stage audio')
            stage['audio'] = chosen
        else:
            for name, line in stage["dialogue"].items():
                _delivery(line["text"], value["dialogue"][name]["delivery"])
        start, end = (round(stage[name] * 1000 / FPS) for name in ("start_frame", "end_frame"))
        shot = {name: copy.deepcopy(value[name]) for name in ("visible_people", "subjects")}
        shot.update(copy.deepcopy(stage.get("opening") or {name: value[name] for name in ("composition", "camera")}))
        if stage.get('ending'):
            shot['ending_state'] = stage['ending']
        action = dict(value["action"])
        if typed:
            action['sound'] = audio.effects(action['sound'])
        if stage.get("action_owned"):
            action["description"] = stage["action"]
        shot.update(start_ms=0 if index == 0 else start, cut=stage["cut"],
                    actions=[dict(action, start_ms=start, end_ms=end)],
                    dialogue=[dict(line, start_ms=start, end_ms=end,
                                   delivery=audio.delivery(value['dialogue'][name]['delivery']) if typed
                                   else value["dialogue"][name]["delivery"])
                              for name, line in stage["dialogue"].items()])
        result["shots"].append(shot)
    return result


def _delivery(text, delivery):
    if re.search(r"(?<!\w)" + re.escape(text.strip()) + r"(?!\w)", delivery, re.I):
        raise ValueError("Delivery must describe vocal performance without repeating the exact dialogue")


def validate_source(reply, stages, frames=None, carried=None):
    ordered = sorted(stages.values(), key=lambda stage: stage["start_frame"])
    typed = ordered[0].get('audio_owned', False)
    if typed:
        if reply['subject_updates']:
            raise ValueError("Appearance is read-only for stage writers; poses belong in terminal_state")
        if 'audio_fields' not in ordered[0]:
            raise ValueError('The source is missing its typed audio contract')
        if any(reply[key] != value for key, value in audio.fields(ordered[0]['audio_fields']).items()):
            raise ValueError('The source changed code-owned audio fields')
    if frames is not None:
        start = carried
        for stage in ordered:
            if (type(stage["start_frame"]) is not int or type(stage["end_frame"]) is not int
                    or stage["start_frame"] != start or stage["end_frame"] <= start):
                raise ValueError("The stage schedule has a gap, overlap or invalid frame interval")
            start = stage["end_frame"]
        if start != frames:
            raise ValueError("The stage schedule does not match the generated clip length")
    shots = reply["shots"]
    if len(shots) != len(stages):
        raise ValueError("The source must preserve every scheduled stage")
    for index, (shot, stage) in enumerate(zip(shots, ordered)):
        start, end = (round(stage[name] * 1000 / FPS) for name in ("start_frame", "end_frame"))
        if shot["start_ms"] != (0 if index == 0 else start) or shot.get("cut", index > 0) != stage["cut"]:
            raise ValueError("The source changed a code-owned stage boundary or cut")
        if len(shot["actions"]) != 1 or any((item["start_ms"], item["end_ms"]) != (start, end)
                                            for item in shot["actions"] + shot["dialogue"]):
            raise ValueError("Actions and dialogue must share their scheduled stage interval")
        if stage.get("action_owned") and shot["actions"][0]["description"] != stage["action"]:
            raise ValueError("The source changed the planned action")
        if any(shot[key] != value for key, value in stage.get("opening", {}).items()):
            raise ValueError("The source changed the continuation's opening boundary")
        if shot.get('ending_state', '') != stage.get('ending', ''):
            raise ValueError("The source changed the code-owned ending goal")
        if typed:
            if 'audio' not in stage:
                raise ValueError('The source is missing its typed stage audio')
            validate.shape(stage['audio'], audio.stage_schema(stage['dialogue']), 'stage audio')
            if shot['actions'][0]['sound'] != audio.effects(stage['audio']['sound']):
                raise ValueError('The source changed code-owned audio effects')
        if len(shot["dialogue"]) != len(stage["dialogue"]):
            raise ValueError("The source changed the scheduled dialogue")
        lines = [stage["dialogue"][key] for key in sorted(stage["dialogue"], key=lambda key: int(key.removeprefix("line_")))]
        for number, (actual, expected) in enumerate(zip(shot["dialogue"], lines), 1):
            if any(actual[key] != value for key, value in expected.items()):
                raise ValueError("The source changed exact dialogue, its speaker or its order")
            if typed:
                if actual['delivery'] != audio.delivery(stage['audio']['dialogue'][f'line_{number}']):
                    raise ValueError('The source changed code-owned vocal delivery')
            else:
                _delivery(expected["text"], actual["delivery"])


def required_dialogue(stages):
    return [line["text"] for stage in stages for line in stage["dialogue"]]


def from_saved(beat, source, text):
    """Partition a legacy source at its existing event boundaries, without repeating speech or actions."""
    shots = (source or {}).get("reply", {}).get("shots", [])
    frame = (source or {}).get("frame", {})
    if shots and frame:
        start = round(frame["carried"] * 1000 / FPS)
        end = round(frame["frames"] * 1000 / FPS)
        events = [item for shot in shots for item in shot["actions"] + shot["dialogue"]]
        if any(not start <= item["start_ms"] < item["end_ms"] <= end for item in events):
            raise ValueError("The saved source has events inside replay or outside the clip; replan this box")
        lines = [line for shot in shots for line in shot["dialogue"] if line["end_ms"] > start]
        bounds = {start, end, *(shot["start_ms"] for shot in shots),
                  *(value for event in events for value in (event["start_ms"], event["end_ms"]))}
        bounds = sorted(value for value in bounds if start <= value <= end
                        and not any(line["start_ms"] < value < line["end_ms"] for line in lines))
        result = []
        for left, right in zip(bounds, bounds[1:]):
            actions = [item["description"] for shot in shots for item in shot["actions"]
                       if left <= item["start_ms"] < right]
            speech = [line for line in lines if left <= line["start_ms"] < right]
            cut = bool(result) and any(shot["start_ms"] == left and shot.get("cut", index > 0)
                                      for index, shot in enumerate(shots))
            result.append(dict(duration_ms=right-left, cut=cut,
                action=" ".join(actions) or "Preserve the ongoing motion, pose, props and view.",
                dialogue=[dict(speaker=line.get("subject") or line["speaker"],voice=line["speaker"],
                               language=line["language"],text=line["text"],voiceover=line["voiceover"],
                               overlap=index > 0 and line.get("overlap",False)) for index,line in enumerate(speech)]))
        return read(result)
    action = "Continue the existing action and preserve its ending." if validate.SYNTAX.search(beat) else beat
    lines = [dict(text=words, language=language) for language,words in
             re.findall(r"<d>\s*\[([^\]]+)\]\s*(.*?)</d>",text,re.S)]
    return [dict(duration_ms=500,cut=False,action=action if index == 0 else "Preserve the ongoing motion and view.",
                 dialogue=[dict(speaker="the existing speaker",voice="the existing voice",language=line["language"],
                                text=line["text"],voiceover=False,overlap=False)] if line else [])
            for index,line in enumerate(lines or [None])]
