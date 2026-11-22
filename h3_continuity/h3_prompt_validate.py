"""Fail-closed local validation, independent of provider response-format support. Mistakes that have one right
answer are put right here instead of costing the model's one repair."""

import copy
import json
import math
import re

from .h3_prompt_ir import PROSE_FIELDS, SUBJECT_ID, normalize_prose, subjects, targets
from .h3_prompt_schema import analysis_schema, prompt_schema
from .timing import FPS

# Descriptions are text, never an alternate syntax/numbering channel.
SYNTAX = re.compile(r"<\s*/?\s*(?:(?:Picture|Audio|Video|Subject)(?:_\w*)?|d|scenetrans|cutoff|prompt)\b|"
                    r"\b(?:Picture|Audio|Video|Subject)\s+\d+|@(?:image|audio|video)\w*|"
                    r"\[\s*Shot\b|\(S\d+(?:,S\d+)*\)|"
                    r"\b(?:integrated_multimodal_description|subject_definitions|retention_analysis|"
                    r"detailed_description|overall_soundscape|non_diegetic_music|summary)\s*:", re.I)
VOICE = ("speakers", "language", "voiceover", "singing")
NAME = re.compile(r"([A-Z][\w'-]*(?: [A-Z][\w'-]*){0,2})(?: \([^()]*\))?(?:, (?:(?:[A-Z][\w-]*'s|his|her|their) "
                  r"[\w' -]+?, |(?=(?:a|an|the|who|whose)\b))| is (?=(?:a|an|the)\b))")
NOT_NAMES = {"A", "An", "The", "This", "That", "These", "Those", "Her", "His", "Their", "Its", "One"}
PLACED = {"subject": "appears in the scene", "audio": "is heard in the scene", "keyframe": "is a keyframe of the shot",
          "composition": "sets the shot's composition", "storyboard": "lays out the shot"}
PICTURE = re.compile(r"(?<![\w@])@?image_?(\d+)\b", re.I)
# A reference's name written in a description, like "image3" or "audio_1", which only ID fields hold.
BARE = re.compile(r"(?<![\w@])(?:image|audio|video_audio|video)_?\d+(?!\w)", re.I)
CUT = re.compile(r"^(?:(?:the )?(?:camera|shot|scene|view) |we )?(?:cuts?(?: back| away)?|transitions?|changes?|"
                 r"switch(?:es)?)(?: \w+ly)? to\b[:,]?\s*", re.I)
# How a later shot's composition may open that the cut the compiler writes before it says, like "The camera holds on".
HOLD = re.compile(r"^(?:the )?camera (?:holds|stays|lingers|rests|settles|focuses) on\s+", re.I)
# A sentence of a composition that moves the camera, like "The camera slowly pans left", which the shot's camera says.
MOVES = re.compile(r"^the camera (?:\w+ly )?(?:holds (?!on\b)|stays|remains|pans|tilts|tracks|follows|pushes|pulls|"
                   r"zooms|trucks|dollies|cranes|pedestals|arcs|orbits|circles|moves|glides|drifts|sweeps|rises|"
                   r"descends|rolls|shakes|travels|swings|begins|starts)", re.I)
# Words that tell a subject's role as the place, like "provides the detailed environment" or "serves as the backdrop".
SETTING = r"(?:provid\w*|serv\w* as|act\w* as|form\w*|is) (?:the|an?) (?:[\w-]+ ){0,3}?(?:environment|backdrop|setting)"
# A shot's clause that gives a subject that role, like "subject_5 provides the backdrop for the whole composition"
# or "subject_1 provides the setting anchor", which the guide says as the subject appearing in the scene.
BACKDROP = re.compile(rf"\b(subject_[1-9][0-9]*(?: \([^()]*\)|, [^,]*,)?) {SETTING}(?: [\w-]+)?"
                      r"(?: (?:for|of) [^,.;!?]*)?(?=[,.;!?]|$)", re.I)
# A subject's own picture written in its definition, like " in image1", " in <image1>" or " (image3)", which the
# compiler writes.
OWN = re.compile(r"\s*\(?(?:(?:seen |shown )?(?:in|from) )?<?@?(image\d+)\b>?\)?", re.I)
# A later sentence of a definition that only says which pictures its subject's look comes from, like "Her appearance
# is defined by image2.", which the compiler writes, or that a model copied without them, like "... defined by.".
SOURCED = re.compile(r"(?<=[.!?])\s+(?:Her|His|Its|Their) (?:\w+ ){1,3}(?:is|are|comes?|was) (?:\w+ ){0,2}"
                     r"(?:by|from|in|on)(?:,? (?:and )?@?image\d+)*\s*[.!?]", re.I)
# A definition that gives its subject's name after its first words, like "the elderly man named Tom, with..." or "the
# elderly man, Tom, with...".
CALLED = re.compile(r"^((?:[Aa]n?|[Tt]he) [^,.;:]*?)(?: (?:named|called) |, (?=[A-Z][\w'-]*(?: [A-Z][\w'-]*){0,2},))"
                    r"([A-Z][\w'-]*(?: [A-Z][\w'-]*){0,2})")
# The kind of picture a definition opens with instead of its subject, like "Portrait of " or "A photo of ".
FRAMED = re.compile(r"^(?:(?:a|an|the) )?(?:portrait|photo(?:graph)?|picture|image|close-up|headshot) of ", re.I)
BOXES = re.compile(r"\b(?:previous|prior|last|next) (?:box|clip|sequence|segment|video|scene)\b|"
                   r"\b(?:previous|prior) beat\b|\bbox \d+\b", re.I)
# A shot, moment or action before the clip or how it felt, which only another box has, like "the end of the previous
# shot" in its first shot, summary or sound, or "the previous tension" a score takes over from.
EARLIER = re.compile(r"\b(?:previous|prior) (?:shot|moment|action|mood|tension|atmosphere|calm|silence)\b", re.I)
# Where a sentence places what it says in another box, like " from the previous sequence" in "The melody from the
# previous sequence swells.", " after box 1", ", established in the previous clip," or " from the previous moment".
ELSEWHERE = re.compile(rf"(,)?\s+(?:(?:\w+ed|heard)\s+(?:earlier\s+)?)?(?:from|in|of|after|since) (?:the end of )?"
                       rf"(?:the )?(?:{BOXES.pattern}|{EARLIER.pattern})(?(1),)", re.I)
# How a sentence may say it continues another box before what it shows, like "continues from the end of box 3,
# showing", which leaves what it shows.
CONTINUES = re.compile(r"\bcontinues from (?:the end of )?(?:box \d+|the (?:previous|prior|last) (?:box|clip|"
                       r"sequence|segment|video|scene)),? showing\b", re.I)
# What a model may open a summary with that the summary doesn't say: task types, like "[video continuation]", which
# the compiler writes, and the mode, like "T2VA.", and a bracket it may close the summary with, like the "]" in
# "[reference generation] The woman stands.]". The guide's task types are left out anywhere else too, like after the
# style in "A cozy film. [reference generation] The woman stands.".
TASK_TYPES = re.compile(r"^(?:\s*(?:\[[^\]]*\]|(?:T2VA|I2VA|FL2VA|L2VA|Ref2VA)\b[.:]?))+\s*|(?<=[.!?])\]\s*$|"
                        r"\s*\[(?:(?:keyframe completion|reference generation|video editing|video continuation|"
                        r"audio reuse|audio reference)(?: \+ )?)+\]")
# A line or delivery that stands for none, like "N/A", "Nothing", "no dialogue" or "No dialogue yet", or only the
# guide's "[unclear]", which marks words it can't make out, not a sound.
NOTHING = re.compile(r"\W*(?:none|n/?a|null|nothing|silence|unclear|no (?:lines?|speech)|"
                     r"no (?:spoken )?dialogue\b.*)?\W*", re.I)
# A dialogue line that is only a sound in brackets, like "(sharp intake of breath)".
STAGED = re.compile(r"\s*[(\[*]+([^()\[\]*]*\w[^()\[\]*]*)[)\]*]+[.!?]?\s*")
# A sound in brackets in a dialogue line, like "(sip)" in "Mmm... (sip)", which isn't said.
ASIDE = re.compile(r"\s*[(\[]([^()\[\]]*\w[^()\[\]]*)[)\]]")
# A time something happens at, like "00:01.625" in "At 00:01.625, she turns", but not an end like "until 00:01.625".
TIMED = re.compile(r"(?<!until )\b(\d\d):(\d\d)\.(\d{3})\b", re.I)
# The least a shot can last: one frame, which a shot 1 ms after another doesn't get.
FRAME_MS = math.ceil(1000 / FPS)
# What a score adds and how it feels, which the guide keeps out of non_diegetic_music: a clause like ", providing a
# warm backdrop", ", building slight tension", ", with minor notes reflecting the storm", "that underscores the
# tension" or " to heighten the moment", a feeling beside a dynamic, like " and tension" in "rising in volume and
# tension", or naming a level, like "tension " in "a higher tension level", a predicate like "sets the mood", "holds
# the tension", "establishes the scene's warmth" or "provides a warm undercurrent to the scene", which leaves "plays",
# and a mood word, with the comma, conjunction or article it leaves behind, the quality it names, like " and a tense
# quality", or the change to it, like " and turns more tense" or ", growing tense", and a clause that only says that
# change, like ", with the strings growing tense".
# A clause of dynamics, like ", building to a crescendo", a word like "soaring" in "A gentle, soaring melody", an
# accompaniment, like the "underscored by strings" in "provides a baseline, underscored by strings" or ", providing a
# warm foundation, supported by strings", and a background that places the music, as in "fades into the background"
# or "a background wash", stay.
FUNCTION = (r"(?:evok|convey|underscor|reflect|mirror|match|balanc|suggest|captur|enhanc|heighten|emphasi[sz]|indicat|"
            r"signal)")
FELT = (r"mood|atmosphere|sense|tension|suspense|warmth|comfort|backdrop|"
        r"(?<!in the )(?<!into the )background(?! (?!(?:that|which|to|for)\b)\w)|undercurrent|foundation|emotions?|"
        r"intimacy|urgency|drama|anticipation|nostalgia|weight")
EFFECTS = rf"{FUNCTION}(?!\w*ed by\b)\w*|feel(?:s|ings?)?|undertone|contrast|counterpoint|{FELT}"
MOOD = (r"(?:(?:slightly|very|deeply|subtly|more|less|increasingly) )*(?:emotional|emotive|heartwarming|melanchol\w*|"
        r"hopeful|uplifting|tense|sad|happy|joyful|nostalgic|triumphant|poignant|touching|intimate|cozy|atmospheric|"
        r"ominous|suspenseful|dramatic|mysterious|eerie|somber|sombre|romantic|serene|haunting|wistful|bittersweet|"
        r"peaceful|tranquil|soothing|comforting|anxious|heroic|reassuring|encouraging|mournful|sorrowful|cheerful|"
        r"brooding|passionate|determined|resolute|thoughtful|mourning|majestic)\b")
EFFECT = re.compile(rf",\s*with\s+[^,.;!?]*?\s{FUNCTION}\w*ing\b[^,.;!?]*|"
                    rf",\s*(?:which|that)\s+[^,.;!?]*?\b(?:{EFFECTS})\b[^,.;!?]*,?|"
                    rf"(?:,\s*(?={FUNCTION}\w*ing\b|(?!{MOOD})\w+ing\s+(?:a|an|the|its|his|her|their|to|with|"
                    rf"{EFFECTS}|(?:[\w-]+\s+){{1,2}}(?:{FELT}))\b)|"
                    rf"\s+(?:that|which)\s+)(?:(?!,\s*\w+ing\b|\s(?:that|which)\s)[^.;!?])*?\b(?:{EFFECTS})\b"
                    rf"(?:(?!\s(?:that|which)\s|,\s*\w+ed by\b)[^.;!?])*|\s+to\s+{FUNCTION}e?\b[^,.;!?]*|"
                    rf"\s+and\s+(?:{FELT})\b(?!\s+of\b)", re.I)
SETS = re.compile(rf"\b(?:establish|set|provid|creat|add|lend|build|hold|keep|maintain|sustain)(e|es|s|ting|ing)?\s+"
                  rf"(?:(?:a|an|the)\s+(?:[\w'-]+,?\s+){{0,3}}?)?(?!\w+ed\b)(?:{EFFECTS})\b(?!\s+levels?\b)"
                  r"(?:\s+of(?:\s+(?!(?:over|under|with|at|in|as|and|while|during|through|before|after|against)\b)"
                  r"[\w-]+){1,3})?(?:\s+(?:to|for|against)\s+the(?:\s+[\w'-]+){1,3}(?=[,.;!?]|$))?", re.I)
MOODS = re.compile(rf",\s*with\s+[^,.;!?]*?\s(?:becom|turn|grow|get)\w*\s+{MOOD}[^,.;!?]*|"
                   rf"(?:,\s*|\s(?:and\s+)?)(?:becom|turn|grow|get)\w*\s+{MOOD}|"
                   rf"(?:,|\s(?:and|with))?\s+an?\s+(?:{MOOD},?\s+)+(?:quality|tone|feel|character|vibe)\b|"
                   rf",\s*{MOOD}|\s(?:and|but|yet|or) {MOOD}|\b(an?) {MOOD}(?:,| and| but| yet)? (\w)|"
                   rf"\b{MOOD}(?:,| and| but| yet)?|\b(?:{FELT})\s+(?=levels?\b)", re.I)
# A shot's sound that is the score, which non_diegetic_music has; the guide keeps to what the characters hear there.
SCORE = re.compile(r"\b(?:score|soundtrack|non-diegetic)\b", re.I)
GENDERS = {"male": re.compile(r"\b(?:male|masculine|man|boy|he|his|him|gentleman|father|grandfather|son|brother)\b",
                              re.I),
           "female": re.compile(r"\b(?:female|feminine|woman|girl|she|her|lady|mother|grandmother|daughter|sister)\b",
                                re.I)}


def shape(value, schema, path="reply", text_errors=None):
    """Validate the deliberately small JSON Schema vocabulary emitted by our schema builders.

    No optional dependency: all emitted keywords are interpreted here. Strict response formats
    are an optimization, never a substitute for this validation (including in text fallback).
    """
    kind = schema["type"]
    valid = {"object": isinstance(value, dict), "array": isinstance(value, list),
             "string": isinstance(value, str), "integer": type(value) is int,
             "boolean": type(value) is bool}[kind]
    if not valid:
        raise ValueError(f"{path} must be {kind}")
    if kind == "object":
        missing = [f"{path}.{key} is required" for key in schema["required"] if key not in value]
        if missing:
            raise ValueError("; ".join(missing))
        for key in value:
            if key not in schema["properties"]:
                raise ValueError(f"{path}.{key} is not allowed")
            shape(value[key], schema["properties"][key], f"{path}.{key}", text_errors)
    elif kind == "array":
        minimum, maximum = schema.get("minItems", 0), schema.get("maxItems", len(value))
        if not minimum <= len(value) <= maximum:
            raise ValueError(f"{path} must contain {minimum}..{maximum} entries")
        for index, item in enumerate(value):
            shape(item, schema["items"], f"{path}[{index}]", text_errors)
    elif kind == "string":
        if len(value.strip()) < schema.get("minLength", 0):
            raise ValueError(f"{path} must not be empty")
        if "pattern" in schema and not re.fullmatch(schema["pattern"], value):
            raise ValueError(f"{path} has an invalid identifier or language")
        match = SYNTAX.search(value)
        if match:
            message = (f"{path} must contain plain text; found H3 syntax or label {match.group(0)!r}. "
                       "Describe it in ordinary words; put reference IDs only in their dedicated fields")
            if text_errors is None:
                raise ValueError(message)
            text_errors.append(message)
    elif kind == "integer" and not schema.get("minimum", value) <= value <= schema.get("maximum", value):
        raise ValueError(f"{path} must be between {schema['minimum']} and {schema['maximum']}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path} must be one of {', '.join(schema['enum'])}")


def _once(items, key):
    """`items` without those whose key(item) an earlier item has."""
    seen, kept = set(), []
    for item in items:
        if key(item) not in seen:
            seen.add(key(item))
            kept.append(item)
    return kept


def _prose(value, path, field=""):
    """(path, text) for each description in `value`."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _prose(item, f"{path}.{key}", key)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _prose(item, f"{path}[{index}]", field)
    elif isinstance(value, str) and field in PROSE_FIELDS:
        yield path, value


def _undefined(value, path, ids):
    """An error for each description in `value` that names a subject ID outside `ids`."""
    errors = []
    for where, text in _prose(value, path):
        unknown = sorted(set(SUBJECT_ID.findall(text)) - ids)
        if unknown:
            errors.append(f"{where} names {', '.join(unknown)}, which " +
                          ("the frozen analysis doesn't define" if ids else "this clip doesn't have; use words"))
    return errors


def subject_name(definition):
    """The proper name a subject's definition starts with, as "Maya" in "Maya, a young woman...", "Maya is the
    young woman...", "Maya (the keeper), a young woman..." or "Maya, Tom's granddaughter, seen by the stove...", else
    None."""
    match = NAME.match(definition)
    return match.group(1) if match and match.group(1).split()[0] not in NOT_NAMES else None


def name_words(name):
    """The words a being named `name` goes by: all of it, its first word and each later word that can stand alone,
    like "Ellis" in "Captain Ellis" but not "A" in "Roommate A"."""
    first, *later = name.split()
    return {name, first, *(word for word in later if len(word) > 1 and word not in NOT_NAMES)}


def _continued(text):
    """`text` to go on after other words: with its first word in lowercase when that is an article or a pronoun."""
    return text[:1].lower() + text[1:] if text.split(" ", 1)[0] in NOT_NAMES else text


# The roles a picture gives a being.
BEINGS = {"appearance", "clothing", "pose"}


def _placed(subject):
    """Whether an analysis `subject` is a place: a picture gives it as an environment and none as a being's
    appearance, clothing or pose, or its definition calls it one, as in "The kitchen environment, with..."."""
    roles = {source["role"] for source in subject["sources"]}
    return ("environment" in roles and not roles & BEINGS or
            bool(re.search(r"\benvironment\b", re.split(r"[,.;:]", subject["definition"], maxsplit=1)[0], re.I)))


def places(analysis):
    """The IDs of the subjects of `analysis` that are places."""
    return {item["id"] for item in analysis["subjects"] if _placed(item)}


def subject_words(definition):
    """What plain text calls a subject: its name, else its definition's first phrase, as "a silver remote" in
    "A silver remote. It is lost"."""
    return _continued(subject_name(definition) or re.split(r"[,.;:]", definition, maxsplit=1)[0].strip())


def _settle_analysis(data):
    """`data` with each subject ID once, each source and anchor once, definitions that open with the subject instead of
    the kind of picture it is in, with a name given after their first words and without the subject's own pictures or
    a sentence that only says them, one place per picture, so that in the picture of an earlier place a later place
    loses its sources and another subject its environment, and a subject left without sources goes, definitions
    without a sentence that names a subject that isn't defined, no composition or storyboard anchor for a picture a
    subject comes from, an audio listed twice as one with all its roles, and voices bound only to defined subjects."""
    data = copy.deepcopy(data)
    ids, taken, top = set(), set(), max((int(item["id"].split("_")[1]) for item in data["subjects"]), default=0)
    for subject in data["subjects"]:
        if subject["id"] in ids:
            top += 1
            subject["id"] = f"subject_{top}"
        ids.add(subject["id"])
        subject["sources"] = _once(subject["sources"], lambda source: (source["reference"], source["role"]))
        place = _placed(subject)
        subject["sources"] = [source for source in subject["sources"] if source["reference"] not in taken or
                              not place and source["role"] != "environment"]
        if place:
            taken |= {source["reference"] for source in subject["sources"] if source["role"] == "environment"}
        own = {source["reference"] for source in subject["sources"]}
        definition = SOURCED.sub(lambda match: "" if set(re.findall(r"image\d+", match.group(0).lower())) <= own
                                 else match.group(0), subject["definition"])
        definition = CALLED.sub(r"\2, \1", FRAMED.sub("", definition))
        subject["definition"] = OWN.sub(lambda match: "" if match.group(1).lower() in own else match.group(0),
                                        definition)
    data["subjects"] = [subject for subject in data["subjects"] if subject["sources"]]
    ids = {subject["id"] for subject in data["subjects"]}
    for item in (*data["subjects"], *data["picture_anchors"], *data["audio_roles"], *data["video_roles"]):
        kept = [part for part in re.split(r"(?<=[.!?])\s+", item["definition"]) if set(SUBJECT_ID.findall(part)) <= ids]
        item["definition"] = " ".join(kept) or item["definition"]
    sources = {source["reference"] for subject in data["subjects"] for source in subject["sources"]}
    data["picture_anchors"] = [item for item in _once(data["picture_anchors"], lambda item: item["reference"])
                               if item["role"] not in ("composition", "storyboard") or item["reference"] not in sources]
    audios = {}
    for item in data["audio_roles"]:
        if item["reference"] in audios:
            audios[item["reference"]]["roles"] += item["roles"]
        else:
            audios[item["reference"]] = item
    for item in audios.values():
        item["roles"] = list(dict.fromkeys(item["roles"]))
        if item["subject"] not in ids:
            item["subject"] = ""
    data["audio_roles"] = list(audios.values())
    return data


def _accounted(data):
    """The references an analysis gives to a subject, an anchor or an audio role."""
    used = {source["reference"] for subject in data["subjects"] for source in subject["sources"]}
    return used | {item["reference"] for collection in ("picture_anchors", "audio_roles", "video_roles") for item in data[collection]}


def validate_analysis(data, context):
    data = normalize_prose(data)
    shape(data, analysis_schema(context), "analysis")
    data = _settle_analysis(data)
    errors = _undefined(data, "analysis", set(subjects(data)))
    for index, subject in enumerate(data["subjects"]):
        pictures = sorted({f"image{int(number)}" for number in PICTURE.findall(subject["definition"])})
        if pictures:
            errors.append(f"analysis.subjects[{index}].definition names {', '.join(pictures)}; say what the subject "
                          "is in words and give the pictures it comes from only in its sources")
    used = _accounted(data)
    if used != set(context.references):
        missing = ', '.join(sorted(set(context.references) - used)) or 'none'
        unexpected = ', '.join(sorted(used - set(context.references))) or 'none'
        errors.append(f"analysis must account for exactly these references: {', '.join(context.references)}; "
                      f"missing: {missing}; unexpected: {unexpected}. Add sources or anchors for the missing "
                      "references using their supplied descriptions; preserve existing correct classifications")
    if errors:
        raise ValueError("\n".join(errors))
    return data


def _kept(analysis):
    """What each defined target keeps when the model gave it no retention entry: all of it, in the frozen
    analysis's words, or for an audio its frozen reuse or reference."""
    kept = {subject["id"]: {"relationship": "fully_preserved", "detail": subject["definition"]}
            for subject in analysis["subjects"]}
    kept.update({item["reference"]: {"relationship": "fully_preserved", "detail": item["definition"]}
                 for item in analysis["picture_anchors"]})
    kept.update({item["reference"]: {"relationship": "weak_reference", "detail": item["definition"]}
                 for item in analysis["video_roles"]})
    kept.update({item["reference"]: {"relationship": "partially_copy" if "audio_reuse" in item["roles"] else "reference",
                                     "detail": item["definition"]} for item in analysis["audio_roles"]})
    return kept


def _retention(value, analysis):
    """Retention keyed by target, as the schema has it, also from a list of entries with "target": a target's
    first entry counts, unknown targets go and a missing one keeps what _kept gives."""
    if isinstance(value, list):
        entries = {}
        for item in value:
            if isinstance(item, dict) and isinstance(item.get("target"), str):
                entries.setdefault(item["target"], {key: item[key] for key in item if key != "target"})
        value = entries
    if not isinstance(value, dict):
        return value
    return {target: value.get(target, kept) for target, kept in _kept(analysis).items()}


def _own(text, later=False):
    """`text` without its sentences about another box, which H3 knows nothing of, and, unless it's about a `later`
    shot, which may look back at the shots before it, about a previous shot, moment or action, after a sentence that
    continues another box says only what it shows."""
    parts = re.split(r"(?<=[.!?])\s+", CONTINUES.sub("shows", text))
    return " ".join(part for part in parts if not BOXES.search(part) and (later or not EARLIER.search(part)))


def _told(text):
    """`text` without its sentences about another box or, when that would leave nothing, without the words that place
    it there."""
    return _own(text) or ELSEWHERE.sub("", text)


def _plain(music):
    """`music` without what it adds to the scene and how it feels, unless nothing would be left."""
    def left(match):
        if not match.group(1):
            return ""
        article = "an" if match.group(2).lower() in "aeiou" else "a"
        return (article.capitalize() if match.group(1)[0].isupper() else article) + " " + match.group(2)

    def played(match):
        ending = (match.group(1) or "").lower()
        return "playing" if ending.endswith("ing") else "plays" if ending in ("s", "es") else "play"

    text, before = music, None
    while text != before:
        text, before = MOODS.sub(left, SETS.sub(played, EFFECT.sub("", text))), text
    text = re.sub(r"\s+([,.;!?])", r"\1", re.sub(r"\s{2,}", " ", text)).strip(" ,")
    text = re.sub(r"(^|[.!?] )([a-z])", lambda match: match.group(1) + match.group(2).upper(), text)
    return text if re.search(r"\w", text) else music


def _settle(data, analysis, context):
    """`data` with the mistakes that have one right answer put right: the shot numbers, a composition that opens with
    the cut the compiler writes or, after shot 1, the camera holding on it, or moves the camera, which the shot's
    camera says, a subject that provides the environment or backdrop, which appears in the scene, sentences about
    another box, whose replay the compiler writes, with a composition left empty taking shot 1's first action or,
    after it, being "a new shot", which the cut the compiler writes can take where an action can't, the first start,
    while a shot that starts with it stays out of order, start times given in seconds and a cut before the replayed
    part ends, a reference repeated in a shot, lines without words or that stand for none, a line that is only a
    sound or has one in brackets, a delivery of none, a shot's sound that is the score, a line of four words or more
    its speakers already said in the clip,
    a speaker's ID in a description, continuation flags without their partner and a cutoff before the end, speakers
    that never speak or, in a voice of its gender, voice a subject another speaker voices, a speaker who is a place,
    a subject's voice described after the subject itself or with it in brackets, a voice of a line said together
    that the line names, music that says how it feels or what it adds, a summary that opens with the task types the
    compiler writes, a retention detail that names its own target as its source, audio relationships against the
    frozen roles, first- or last-frame anchors outside their shot or in none, which open or close their shot's
    references, and in a clip of one shot the anchors it leaves out."""
    placed = places(analysis) if analysis else set()
    speakers = [dict(speaker, subject="") if speaker["subject"] in placed else speaker for speaker in data["speakers"]]
    data = normalize_prose(dict(data, speakers=speakers),
                           voiced={speaker["id"]: speaker["subject"] for speaker in speakers})
    shots, appears = data["shots"], rf"\1 {PLACED['subject']}"
    for number, shot in enumerate(shots, 1):
        shot["number"], later = number, number > 1
        shot["actions"] = [text for text in (_own(BACKDROP.sub(appears, action), later) for action in shot["actions"])
                           if text]
        composition = _own(CUT.sub("", BACKDROP.sub(appears, shot["composition"])), later)
        composition = HOLD.sub("", composition) if number > 1 and shot["cut"] else composition
        composition = " ".join(part for part in re.split(r"(?<=[.!?])\s+", composition) if not MOVES.match(part))
        shot["composition"] = composition or (("a new shot" if shot["cut"] else "the same view") if number > 1 else
                                              shot["actions"].pop(0) if shot["actions"] else shot["composition"])
        shot["references"] = _once(shot["references"], lambda ref: (ref["target"], ref["detail"]))
        shot["dialogue"] = [line for line in shot["dialogue"] if not NOTHING.fullmatch(line["text"])]
        for line in shot["dialogue"]:
            staged = STAGED.fullmatch(line["text"])
            shot["diegetic_audio"] += [sound.strip() for sound in
                                       ([staged.group(1)] if staged else ASIDE.findall(line["text"]))]
            line["text"] = "" if staged else ASIDE.sub("", line["text"]).strip()
        shot["dialogue"] = [line for line in shot["dialogue"] if not NOTHING.fullmatch(line["text"])]
        shot["diegetic_audio"] = [sound for sound in (_own(sound, later) for sound in shot["diegetic_audio"])
                                  if sound and not SCORE.search(sound)]
        for line in shot["dialogue"]:
            if NOTHING.fullmatch(line["delivery"]):
                line["delivery"] = ""
    first, shots[0]["start_ms"] = shots[0]["start_ms"], 0
    if len(shots) > 1 and all(0 < shot["start_ms"] * 1000 < context.duration_ms for shot in shots[1:]):
        for shot in shots[1:]:
            shot["start_ms"] *= 1000
    for shot in shots[1:]:
        shot["start_ms"] = max(shot["start_ms"] if shot["start_ms"] > first else 0, context.replayed_ms)
    for speaker in data["speakers"]:
        if speaker["subject"]:
            speaker["description"] = re.sub(rf"^{speaker['subject']}\s*[,:;-]\s*(?=\S)|\s*\({speaker['subject']}\)", "",
                                            speaker["description"])
    kept, alias, voiced = [], {}, {}
    miscast = {item["id"] for item, _, _ in _miscast(data, analysis)}
    for speaker in data["speakers"]:
        if speaker["id"] in alias or any(item["id"] == speaker["id"] for item in kept):
            continue
        if speaker["subject"] in voiced and speaker["id"] not in miscast:
            alias[speaker["id"]] = voiced[speaker["subject"]]
            continue
        kept.append(speaker)
        if speaker["subject"] and speaker["id"] not in miscast:
            voiced[speaker["subject"]] = speaker["id"]
    lines = [line for shot in shots for line in shot["dialogue"]]
    named = _named_subjects(analysis) if analysis else {}
    for line in lines:
        line["speakers"] = list(dict.fromkeys(alias.get(name, name) for name in line["speakers"]))
        spoken_to = {voiced[named[name]] for name in named
                     if named[name] in voiced and re.search(rf"\b{re.escape(name)}\b", line["text"])}
        if len(line["speakers"]) > 1:
            line["speakers"] = [name for name in line["speakers"] if name not in spoken_to] or line["speakers"]
    said = set()
    for shot in shots:
        dialogue = []
        for line in shot["dialogue"]:
            words = (tuple(line["speakers"]), tuple(re.findall(r"\w+", line["text"].casefold())))
            if len(words[1]) < 4 or words not in said:
                dialogue.append(line)
                said.add(words)
        shot["dialogue"] = dialogue
    lines = [line for shot in shots for line in shot["dialogue"]]
    spoken = {name for line in lines for name in line["speakers"]}
    data["speakers"] = [speaker for speaker in kept if speaker["id"] in spoken]
    pairs = {i for i in range(len(shots) - 1) if shots[i]["dialogue"] and shots[i + 1]["dialogue"]
             and shots[i]["dialogue"][-1]["to_next"] and shots[i + 1]["dialogue"][0]["from_previous"]
             and all(shots[i]["dialogue"][-1][key] == shots[i + 1]["dialogue"][0][key] for key in VOICE)}
    for i, shot in enumerate(shots):
        last = len(shot["dialogue"]) - 1
        for j, line in enumerate(shot["dialogue"]):
            line["to_next"] = j == last and i in pairs
            line["from_previous"] = j == 0 and i - 1 in pairs
            line["cutoff"] = line["cutoff"] and not line["to_next"] and i == len(shots) - 1 and j == last
    data["overall_soundscape"] = _told(data["overall_soundscape"])
    data["non_diegetic_music"] = _plain(_told(data["non_diegetic_music"]))
    if not analysis:
        return data
    data["summary"] = _told(TASK_TYPES.sub("", data["summary"]))
    for target, entry in data["retention"].items():
        entry["detail"] = re.sub(rf" from {target}\b(?!')", "", entry["detail"])
    for field in ("soundscape_references", "music_references"):
        data[field] = list(dict.fromkeys(data[field]))
    for item in analysis["audio_roles"]:
        entry = data["retention"][item["reference"]]
        copied = entry["relationship"] in ("fully_copy", "partially_copy")
        if ("audio_reuse" in item["roles"]) != copied:
            entry["relationship"] = "reference" if copied else "partially_copy"
    for anchor in analysis["picture_anchors"]:
        name, role = anchor["reference"], anchor["role"]
        if role in ("first_frame", "last_frame"):
            home = shots[0 if role == "first_frame" else -1]
            uses = [ref for shot in [home, *shots] for ref in shot["references"] if ref["target"] == name]
            for shot in shots:
                shot["references"] = [ref for ref in shot["references"] if ref["target"] != name]
            use = uses[0] if uses else {"target": name, "detail": "shows " + _continued(anchor["definition"])}
            home["references"].insert(0 if role == "first_frame" else len(home["references"]), use)
        elif len(shots) == 1 and all(ref["target"] != name for ref in shots[0]["references"]):
            shots[0]["references"].append({"target": name, "detail": PLACED[role]})
    return data


def appearances(data, analysis):
    """The numbers of the shots that use each defined target: by reference, by the subject's ID or name in the
    shot's descriptions or by the subject speaking there, or for a voice by its subject speaking there."""
    names = {subject["id"]: subject_name(subject["definition"]) for subject in analysis["subjects"]}
    voices = {item["reference"]: item["subject"] for item in analysis["audio_roles"] if item["subject"]}
    bound = {speaker["id"]: speaker["subject"] for speaker in data["speakers"]}
    found = {target: [] for target in targets(analysis)}
    for shot in data["shots"]:
        text = " ".join([shot["composition"], *shot["actions"], *(ref["detail"] for ref in shot["references"])])
        speaking = {bound.get(name) for line in shot["dialogue"] for name in line["speakers"]}
        used = {ref["target"] for ref in shot["references"]} | set(SUBJECT_ID.findall(text)) | speaking
        used |= {subject for subject, name in names.items() if name and re.search(rf"\b{re.escape(name)}\b", text)}
        used |= {audio for audio, subject in voices.items() if subject in speaking}
        for target, numbers in found.items():
            if target in used:
                numbers.append(shot["number"])
    return found


def spare(data, analysis):
    """The subjects of `analysis` that settled `data` and the rest of `analysis` never use or mention outside their
    own retention, when a subject still in use or a picture anchor comes from each of their pictures too: the prompt
    leaves them out, and every picture stays cited."""
    used = appearances(data, analysis)
    idle = []
    for item in analysis["subjects"]:
        rest = [dict(data, retention={key: value for key, value in data["retention"].items() if key != item["id"]}),
                dict(analysis, subjects=[other for other in analysis["subjects"] if other is not item])]
        if not used[item["id"]] and not re.search(rf"\b{item['id']}\b", json.dumps(rest), re.I):
            idle.append(item)
    shown = {source["reference"] for item in analysis["subjects"] if item not in idle for source in item["sources"]}
    shown |= {item["reference"] for item in analysis["picture_anchors"]}
    return [item["id"] for item in idle if {source["reference"] for source in item["sources"]} <= shown]


def _relations(data, analysis, context):
    """The errors in well-typed, settled `data` that have no one right answer."""
    errors = []
    speakers = {item["id"] for item in data["speakers"]}
    last_time, named, end = -FRAME_MS, -1, context.duration_ms - FRAME_MS
    for i, shot in enumerate(data["shots"]):
        if shot["start_ms"] < last_time + FRAME_MS:
            errors.append(f"shots[{i}].start_ms must be at least {last_time + FRAME_MS}, a frame after shots[{i - 1}]")
        elif shot["start_ms"] <= named:
            errors.append(f"shots[{i - 1}].actions name {named} ms, which is not before shots[{i}].start_ms; start "
                          f"shots[{i}] later or move that action into it")
        elif shot["start_ms"] > end:
            errors.append(f"shots[{i}].start_ms must be at most {end}, a frame before the clip ends")
        last_time, named = shot["start_ms"], _named_ms(shot)
        for j, line in enumerate(shot["dialogue"]):
            path = f"shots[{i}].dialogue[{j}]"
            if not set(line["speakers"]) <= speakers:
                errors.append(f"{path}.speakers must refer to defined speakers")
            if SUBJECT_ID.search(line["text"]):
                errors.append(f"{path}.text is spoken aloud, so it must not contain subject IDs")
    errors += [f"{where} names {BARE.search(text).group(0)}, which only ID fields hold; describe what it shows in "
               "words or name its subject by ID" for where, text in _prose(data, "prompt") if BARE.search(text)]
    errors += [f"{item['id']} is a {voice} voice, but voices {item['subject']}, who is {person}; a voice goes with "
               "the subject whose voice it is, and one only heard, such as over a radio, with none"
               for item, voice, person in _miscast(data, analysis)]
    return errors + _undefined(data, "prompt", set(subjects(analysis)))


def _named_ms(shot):
    """The latest time the actions of `shot` name something happening at, like 1625 for "At 00:01.625, she turns",
    or -1."""
    return max((int(m) * 60000 + int(s) * 1000 + int(ms) for action in shot["actions"]
                for m, s, ms in TIMED.findall(action)), default=-1)


def _gender(text):
    """"male" or "female" where `text` says one of them and not the other, else None."""
    found = [name for name, words in GENDERS.items() if words.search(text)]
    return found[0] if len(found) == 1 else None


def _miscast(data, analysis):
    """The speakers of `data` whose voice is male or female where the subject they voice is the other, each with
    both."""
    defined = {item["id"]: item["definition"] for item in (analysis or {}).get("subjects", [])}
    found = [(item, _gender(item["description"]), _gender(defined.get(item["subject"], "")))
             for item in data["speakers"]]
    return [(item, voice, person) for item, voice, person in found if voice and person and voice != person]


def _sole_subjects(analysis):
    """The pictures of `analysis` that show one subject and anchor nothing, each with that subject's ID."""
    owners = {}
    for subject in analysis["subjects"]:
        for source in subject["sources"]:
            owners.setdefault(source["reference"], set()).add(subject["id"])
    anchored = {item["reference"] for item in analysis["picture_anchors"]}
    return {name: next(iter(ids)) for name, ids in owners.items() if len(ids) == 1 and name not in anchored}


def _named_subjects(analysis):
    """The names of the subjects of `analysis`, each with that subject's ID: the words a being's name gives it, or the
    name a place's definition starts with and its first word, where no other subject's name is or has the same."""
    owners, placed = {}, places(analysis)
    for subject in analysis["subjects"]:
        name = subject_name(subject["definition"])
        if name:
            for words in {name, name.split()[0]} if subject["id"] in placed else name_words(name):
                owners.setdefault(words, set()).add(subject["id"])
    return {name: next(iter(ids)) for name, ids in owners.items() if len(ids) == 1}


def _prepared(data, context, analysis):
    """`data` with its descriptions normalized and, in Ref2VA, its retention keyed, with the frozen analysis."""
    if context.mode == "Ref2VA":
        analysis = validate_analysis(analysis, context)
    elif analysis is not None:
        raise ValueError("analysis is only allowed in Ref2VA mode")
    data = normalize_prose(data, pictured=_sole_subjects(analysis) if analysis else None,
                           named=_named_subjects(analysis) if analysis else None)
    if analysis and isinstance(data, dict):
        data = dict(data, retention=_retention(data.get("retention"), analysis))
    return data, analysis


def _missing(data, analysis):
    """The defined targets that no shot and no audio layer of settled `data` uses, besides the spare subjects."""
    if not analysis:
        return []
    layered = set(data["soundscape_references"]) | set(data["music_references"]) | set(spare(data, analysis))
    return [target for target, numbers in appearances(data, analysis).items() if not numbers and target not in layered]


def shot_cuts(data):
    """Accept saved replies without cut choices using their original later-shot cut behavior."""
    if not isinstance(data, dict) or not isinstance(data.get("shots"), list):
        return data
    return dict(data, shots=[dict(shot, cut=shot.get("cut", index > 0)) if isinstance(shot, dict) else shot
                             for index, shot in enumerate(data["shots"])])


def validate_prompt(data, context, analysis=None):
    """`data` checked against the schema and the frozen analysis, with the mistakes that have one right answer put
    right; raises ValueError listing every other error."""
    data, analysis = _prepared(shot_cuts(data), context, analysis)
    errors = []
    try:
        shape(data, prompt_schema(context, analysis), "prompt", errors)
        # Text markup errors leave the object well typed, so the relational checks run
        # too and the one repair hears about everything at once.
        data = _settle(data, analysis, context)
        errors += _relations(data, analysis, context)
        missing = _missing(data, analysis)
        if missing:
            errors.append(f"shots and audio sections must use every defined target; missing: {', '.join(missing)}. "
                          "Name a subject by its ID in the shots where it appears, or add a target to "
                          "shots[].references with what it does there; audio can also go in its audio layer")
    except ValueError as error:
        errors.append(str(error))
    if errors:
        raise ValueError("\n".join(errors))
    return data
