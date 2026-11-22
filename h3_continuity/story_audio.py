"""Typed audio choices compiled to prose; visual state and spoken words have no fields here."""

from . import h3_prompt_schema as schema, h3_prompt_validate as validate

SOUNDS = {
    "room_tone": "room tone", "footsteps": "footsteps", "fabric": "fabric rustling",
    "contact": "contact sounds", "impact": "impact sounds", "scrape": "scraping",
    "creak": "creaking", "rattle": "rattling", "paper": "paper rustling",
    "breathing": "breathing", "nonverbal_voice": "nonverbal vocal sounds",
    "liquid": "liquid sounds", "water": "flowing water", "wind": "wind",
    "rain": "rainfall", "thunder": "thunder", "fire": "fire crackling",
    "birds": "bird calls", "insects": "insect sounds", "animal": "animal calls",
    "traffic": "traffic noise", "engine": "engine noise", "machinery": "mechanical sounds",
    "electronic": "electronic tones", "crowd": "indistinct crowd murmur", "applause": "applause",
}
LEVELS = {"faint": "faint", "quiet": "quiet", "normal": "", "loud": "loud"}
QUALITIES = ("neutral", "soft", "sharp", "muffled", "hollow", "metallic", "wooden", "ceramic",
             "crisp", "crackling", "airy", "rumbling", "buzzing", "wet")
VOLUMES = {"normal": "at a conversational volume", "quiet": "quietly", "loud": "loudly",
           "whisper": "whispering", "shout": "shouting"}
PACES = {"natural": "", "slow": "slowly", "quick": "quickly"}
TONES = {"neutral": "", "warm": "warmly", "gentle": "gently", "firm": "firmly",
         "hesitant": "hesitantly", "urgent": "urgently", "cheerful": "cheerfully", "sad": "sadly",
         "angry": "angrily", "weary": "wearily", "amused": "with amusement", "tense": "tensely"}
INSTRUMENTS = ("piano", "strings", "acoustic guitar", "electric guitar", "bass", "brass", "woodwinds",
               "percussion", "drums", "synthesizer", "wordless choir")
USES = {"voice_timbre": "Voice timbre reference.", "ambience": "Ambient sound reference.",
        "sound_effect": "Sound effect reference.", "music": "Music reference.",
        "rhythm": "Rhythm reference.", "continuity": "Audio continuity reference.",
        "audio_reuse": "Reuse the supplied audio."}

RULES = """Audio uses typed choices, never prose. action.sound and overall_soundscape are arrays of
{kind, level, quality}; [] means no added sound. Select only audible events caused by the planned action or
existing environment, not visual movements. For example a ceramic tap is
[{"kind":"contact","level":"quiet","quality":"ceramic"}].
non_diegetic_music is {instruments, tempo, level}; instruments:[] means no music.
audio_references[].use selects an audio role. dialogue[].delivery is {volume, pace, tone}, for example
{"volume":"quiet","pace":"natural","tone":"neutral"}. Code writes every audio sentence.
subject_updates MUST be []. Appearance is read-only for this writer. Put pose, movement, gaze, position,
and prop ownership in stages or terminal_state, never in appearance. User edits in Cast/Bible own appearance."""


def effects_schema():
    return schema.array(schema.obj({"kind": schema.enum(SOUNDS), "level": schema.enum(LEVELS),
                                    "quality": schema.enum(QUALITIES)}), maximum=8)


def delivery_schema():
    return schema.obj({"volume": schema.enum(VOLUMES), "pace": schema.enum(PACES), "tone": schema.enum(TONES)})


def fields_schema():
    return schema.obj({"overall_soundscape": effects_schema(),
        "non_diegetic_music": schema.obj({"instruments": schema.choice_array(INSTRUMENTS, maximum=8),
                                           "tempo": schema.enum(("slow", "moderate", "fast")),
                                           "level": schema.enum(LEVELS)}),
        "audio_references": schema.array(schema.obj({"reference": {"type": "string", "pattern": r"^(?:audio|video_audio)[1-9]\d*$"},
                                                     "use": schema.enum(USES)}))})


def stage_schema(lines):
    return schema.obj({"sound": effects_schema(), "dialogue": schema.obj({key: delivery_schema() for key in lines})})


def effects(value):
    validate.shape(value, effects_schema(), "audio effects")
    return " ".join((" ".join(filter(None, (LEVELS[item['level']],
        "" if item['quality'] == 'neutral' else item['quality'], SOUNDS[item['kind']])))).capitalize() + "."
        for item in value)


def delivery(value):
    validate.shape(value, delivery_schema(), "vocal delivery")
    return ", ".join(filter(None, (VOLUMES[value['volume']], PACES[value['pace']], TONES[value['tone']])))


def fields(value):
    validate.shape(value, fields_schema(), "audio fields")
    music = value['non_diegetic_music']
    score = (" ".join(filter(None, (LEVELS[music['level']], "music with " + ", ".join(music['instruments']),
             "at a " + music['tempo'] + " tempo"))).capitalize() + ".") if music['instruments'] else "N/A"
    return {"overall_soundscape": effects(value['overall_soundscape']) or "N/A", "non_diegetic_music": score,
            "audio_references": [dict(item, use=USES[item['use']]) for item in value['audio_references']]}
