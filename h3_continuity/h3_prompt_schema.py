"""Small strict JSON schemas selected for the current box, shared by server and local checks."""

from .h3_prompt_ir import subjects, targets

TEXT = {"type": "string", "minLength": 1}
CAMERAS = ("Zoom In", "Zoom Out", "Push In", "Pull Out", "Pan Left", "Pan Right", "Truck Left", "Truck Right",
           "Tilt Up", "Tilt Down", "Pedestal Up", "Pedestal Down", "Arc Shot", "Tracking Shot", "Static Shot",
           "Shake Slightly", "Shake Strongly", "POV", "Roll Clockwise", "Roll Counterclockwise")
IMAGE_ROLES = ("appearance", "environment", "clothing", "style", "object", "pose")
ANCHOR_ROLES = ("composition", "first_frame", "last_frame", "keyframe", "storyboard")
AUDIO_ROLES = ("voice_timbre", "dialogue", "music_style", "audio_reuse", "sound_texture", "rhythm", "continuity")
VISUAL_RELATIONS = ("fully_preserved", "partially_preserved", "attribute_transfer", "weak_reference")
AUDIO_RELATIONS = ("fully_copy", "partially_copy", "reference", "weak_reference")
SPEAKERS = tuple(f"speaker_{i}" for i in range(1, 17))


def obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def enum(values):
    return {"type": "string", "enum": list(values)}


def array(items, minimum=0, maximum=32):
    return {"type": "array", "items": items, "minItems": minimum, "maxItems": maximum}


def choice_array(values, minimum=0, maximum=32):
    return array(enum(values) if values else TEXT, minimum, maximum if values else 0)


def reply_format(name, schema):
    return {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}}


def analysis_schema(context):
    images, audios = context.slots.references, context.slots.audios
    # Existing RefMods keep their logical image-slot schema; raw videos have their own whole-video roles.
    videos = [name for name in images if name.startswith("video")]
    pictures = [name for name in images if name not in videos]
    source = obj({"reference": enum(images) if images else TEXT, "role": enum(IMAGE_ROLES)})
    subject = obj({"id": {"type": "string", "pattern": r"^subject_[1-9][0-9]*$"}, "definition": TEXT,
                   "sources": array(source, 1, 9)})
    anchor = obj({"reference": enum(pictures) if pictures else TEXT, "role": enum(ANCHOR_ROLES), "definition": TEXT})
    audio = obj({"reference": enum(audios) if audios else TEXT, "roles": choice_array(AUDIO_ROLES, 1, 7),
                 "subject": {"type": "string", "pattern": r"^(subject_[1-9][0-9]*)?$"}, "definition": TEXT})
    return obj({"subjects": array(subject, maximum=32 if images else 0),
                "picture_anchors": array(anchor, maximum=len(pictures)),
                "audio_roles": array(audio, maximum=len(audios)),
                "video_roles": array(obj({"reference": enum(videos), "definition": TEXT}), maximum=len(videos))
                               if videos else array(TEXT, maximum=0)})


def prompt_schema(context, analysis=None):
    known = targets(analysis) if context.mode == "Ref2VA" else list(context.references)
    speaker = obj({"id": enum(SPEAKERS), "description": TEXT, "subject": enum(["", *subjects(analysis)])})
    dialogue = obj({"speakers": choice_array(SPEAKERS, 1, 16),
                    "language": {"type": "string", "pattern": r"^[A-Za-z][A-Za-z -]{0,63}$"},
                    "text": TEXT, "delivery": {"type": "string"}, "voiceover": {"type": "boolean"},
                    "singing": {"type": "boolean"}, "from_previous": {"type": "boolean"},
                    "to_next": {"type": "boolean"}, "cutoff": {"type": "boolean"}})
    use = obj({"target": enum(known) if known else TEXT, "detail": TEXT})
    shot = obj({"number": {"type": "integer", "minimum": 1, "maximum": 32},
                "cut": {"type": "boolean"},
                "start_ms": {"type": "integer", "minimum": 0, "maximum": context.duration_ms - 1},
                "composition": TEXT, "actions": array(TEXT, 1),
                "references": array(use, maximum=32 if known else 0),
                "camera": obj({"type": enum(CAMERAS), "amplitude": enum(("normal", "small", "large")),
                               "speed": enum(("normal", "slow", "fast"))}),
                "dialogue": array(dialogue), "diegetic_audio": array(TEXT)})
    properties = {"style": TEXT, "speakers": array(speaker, maximum=16), "shots": array(shot, 1),
                  "overall_soundscape": TEXT, "non_diegetic_music": TEXT}
    if context.mode == "Ref2VA":
        audios = [name for name in known if name.startswith(("audio", "video_audio"))]
        kept = {name: obj({"relationship": enum(AUDIO_RELATIONS if name.startswith(("audio", "video_audio")) else VISUAL_RELATIONS),
                           "detail": TEXT}) for name in known}
        properties.update({"summary": TEXT, "retention": obj(kept),
                           "soundscape_references": choice_array(audios), "music_references": choice_array(audios)})
    return obj(properties)
