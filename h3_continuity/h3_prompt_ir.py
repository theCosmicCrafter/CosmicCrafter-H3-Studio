"""Versioned semantic prompt contract. No model-authored H3 syntax crosses this boundary."""

import dataclasses
import json
import re
from dataclasses import dataclass

from . import timeline
from .timing import FPS

VERSION = 1
GUIDELINE_REVISION = "d21241f0a4b3acbb34c97dae47fa417b7065e438"
PROSE_FIELDS = {"style", "summary", "definition", "detail", "description", "composition", "actions",
                "diegetic_audio", "overall_soundscape", "non_diegetic_music", "delivery"}
SUBJECT_ID = re.compile(r"\bsubject_[1-9][0-9]*\b")
SUBJECT_LABEL = re.compile(r"<\s*subject[\s_]*([1-9][0-9]*)\s*>|\bsubject[ _]([1-9][0-9]*)\b", re.I)
# A subject written by name and ID both, like "Maya (subject_2)", "Maya's (subject_2) hands", "Tom, subject_3,
# waves" or a summary's "uses subject_2 for Maya's appearance", which it writes once.
TWICE = re.compile(r"\b(subject_[1-9][0-9]*)('s)?(?: \(\1('s)?\)|, \1\b(,(?= (?:who|which|whose)\b))?,?|"
                   r" for \1\b(?:'s appearance\b)?(?!'))")
# A subject's ID said again in brackets later in its sentence, like "subject_2, in her coat (subject_2), waves".
AGAIN = re.compile(r"\b(subject_[1-9][0-9]*)\b([^.!?()]*?) \(\1\)")
SPEAKER_LABEL = re.compile(r"<\s*speaker[\s_]*([1-9][0-9]*)\s*>|\bspeaker_([1-9][0-9]*)\b", re.I)
# A reference a description names, by an @mention like @image3 or by its bare name, also as "image_3".
REFERENCE = re.compile(r"(?<![\w@])@?(image|audio|video_audio|video)_?(\d+)(?!\w)", re.I)


def normalize_prose(data, field="", pictured=None, named=None, voiced=None):
    """Fold layout whitespace in descriptions, without changing dialogue, IDs or structure, write a shot named like an
    ID, "shot_1", as "shot 1", and write a subject the model named by label, such as <Subject 2> or Subject 2, by a
    picture that `pictured` maps to it, as @image3 or image3, or by a name that `named` maps to it, also with a number
    like an ID as "biscuit_4", as its ID subject_2 and "Reyes'" as "subject_2's", an ID without an article, and a
    subject written by name and ID both once.
    With `voiced`, a speaker the model named by ID, such as <speaker_1>, becomes the subject `voiced` maps it to, else
    "someone"; "someone" in brackets is left out, and one that opens a sentence is capitalized.

    Models may format a paragraph over several lines. The compiler owns paragraph
    layout; making a model regenerate the story for this cannot improve its content.
    """
    if isinstance(data, dict):
        return {key: normalize_prose(value, key, pictured, named, voiced) for key, value in data.items()}
    if isinstance(data, list):
        return [normalize_prose(value, field, pictured, named, voiced) for value in data]
    if isinstance(data, str) and field in PROSE_FIELDS:
        text = re.sub(r"\s+", " ", data).strip()
        text = SUBJECT_LABEL.sub(lambda match: f"subject_{match.group(1) or match.group(2)}", text)
        text = re.sub(r"\bshot_([1-9][0-9]*)\b", r"shot \1", text, flags=re.I)
        if voiced is not None:
            text = SPEAKER_LABEL.sub(
                lambda match: voiced.get(f"speaker_{match.group(1) or match.group(2)}") or "someone", text)
        if named:
            names = "|".join(re.escape(name) for name in sorted(named, key=len, reverse=True))
            lowered = {name.lower(): value for name, value in named.items()}
            text = re.sub(rf"\b({names})_\d+\b", lambda match: lowered[match.group(1).lower()], text, flags=re.I)
            text = re.sub(rf"\b({names})\b((?<=s)'(?!\w))?",
                          lambda match: named[match.group(1)] + ("'s" if match.group(2) else ""), text)
        text = REFERENCE.sub(lambda match: (pictured or {}).get(
            f"{match.group(1).lower()}{int(match.group(2))}", match.group(0)), text)
        text = re.sub(r"\b(?:the|a|an) (?=subject_[1-9][0-9]*\b)", "", text, flags=re.I)
        text = TWICE.sub(lambda match: match.group(1) + ("'s" if match.group(2) or match.group(3) else "") +
                         (match.group(4) or ""), text.replace(" (someone)", ""))
        text = AGAIN.sub(r"\1\2", text)
        return re.sub(r"(^|[.!?] )someone\b", r"\1Someone", text)
    return data


@dataclass(frozen=True)
class PromptContext:
    mode: str
    slots: timeline.Slots
    generated_frames: int
    carried_frames: int = 0
    image_guidance: tuple = ()

    @property
    def duration_ms(self):
        return round(self.generated_frames * 1000 / FPS)

    @property
    def replayed_ms(self):
        return round(self.carried_frames * 1000 / FPS)

    @property
    def duration(self):
        return self.generated_frames / FPS

    @property
    def references(self):
        return tuple(self.slots.tags)


def resolve(ctx, index, selected):
    """Freeze the actual Timeline transport, including shared mentions and native guides."""
    connected = {ref.name for ref in ctx.references}
    for name in selected:
        if not isinstance(name, str) or not re.fullmatch(r"(?:image|audio|video_audio|video)[1-9][0-9]*", name):
            raise ValueError(f"references.{name} is not a supported image/video/audio slot")
        if name not in connected:
            raise ValueError(f"references.{name} is not connected")
    boxes = list(ctx.timeline.boxes)
    boxes[index] = dataclasses.replace(boxes[index], prompt=" ".join(f"@{name}" for name in selected))
    slots = timeline.box_slots(dataclasses.replace(ctx.timeline, boxes=boxes), index)
    voices = {clip["slot"] for clip in ctx.timeline.voice_clips}
    for name in (*slots.tags, slots.first, slots.last):
        if name and name not in connected and name not in voices:
            raise ValueError(f"references.{name} is not connected")
    if len(slots.image_inputs) > timeline.MAX_REF_IMAGES or len(slots.audio_inputs) > timeline.MAX_REF_AUDIOS:
        raise ValueError("references exceed H3's 9 image / 3 audio limit")
    if slots.mode == "ref2va":
        mode = "Ref2VA"
    elif slots.first and slots.last:
        mode = "FL2VA"
    elif slots.first:
        mode = "I2VA"
    elif slots.last:
        mode = "L2VA"
    else:
        mode = "T2VA"
    box = ctx.boxes[index]
    guides = tuple(name for name in slots.references if name in set(ctx.idea_references.values()))
    return PromptContext(mode, slots, box.frames + box.carried, box.carried, guides)


def parse_json(reply):
    """Accept a JSON object in any transport, optionally fenced, following reasoning or between sentences."""
    text = re.sub(r"<think>.*?</think>", "", reply, flags=re.S | re.I)
    text = re.split(r"</think>", text, flags=re.I)[-1].strip()

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    start = text.find("{")
    if start < 0:
        raise ValueError("reply must be a JSON object")
    decoder = json.JSONDecoder(object_pairs_hook=pairs,
                               parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"invalid JSON {value}")))
    try:
        data, _ = decoder.raw_decode(text, start)
    except json.JSONDecodeError as error:
        raise ValueError(f"reply must be a JSON object ({error.msg})") from None
    return data


def subjects(analysis):
    return [item["id"] for item in analysis["subjects"]] if analysis else []


def targets(analysis):
    if not analysis:
        return []
    return [*subjects(analysis), *(item["reference"] for item in analysis["picture_anchors"]),
            *(item["reference"] for item in analysis.get("video_roles", [])),
            *(item["reference"] for item in analysis["audio_roles"])]
