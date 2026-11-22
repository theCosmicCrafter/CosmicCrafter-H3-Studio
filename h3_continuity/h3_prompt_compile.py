"""Deterministic H3 syntax. Inputs are semantic JSON and a frozen transport context."""

import re

from .h3_prompt_validate import (NAME, NOT_NAMES, PLACED, SETTING, appearances, spare, subject_name, subject_words,
                                 validate_analysis, validate_prompt)
from .h3_prompt_ir import PROSE_FIELDS, SUBJECT_ID, subjects, targets

CONTINUATION = "Continue the supplied motion and camera framing seamlessly without a cut, pause or reset."

CAMERA_ACTIONS = dict(zip(
    ("Zoom In", "Zoom Out", "Push In", "Pull Out", "Pan Left", "Pan Right", "Truck Left", "Truck Right",
     "Tilt Up", "Tilt Down", "Pedestal Up", "Pedestal Down", "Arc Shot", "Tracking Shot", "Static Shot",
     "Shake Slightly", "Shake Strongly", "POV", "Roll Clockwise", "Roll Counterclockwise"),
    ("zooms in", "zooms out", "pushes in", "pulls out", "pans left", "pans right", "trucks left", "trucks right",
     "tilts up", "tilts down", "pedestals up", "pedestals down", "arcs around the subject", "tracks the subject",
     "holds a static shot", "shakes slightly", "shakes strongly", "shows the subject's point of view",
     "rolls clockwise", "rolls counterclockwise")))
ANCHORS = {"first_frame": "the first frame of", "last_frame": "the last frame of", "keyframe": "a keyframe of",
           "composition": "the composition reference for", "storyboard": "the storyboard for"}
# Words that start a description in capitals only because the model began a sentence with them.
OPENING = re.compile(
    r"^(A|An|The|Close|Wide|Medium|Extreme|Tight|Long|Full|Low|High|Overhead|Over|Reverse|Insert|Two|Someone)\b")
PRONOUNS = {"She": "", "He": "", "It": "", "They": "", "Her": "'s", "His": "'s", "Its": "'s", "Their": "'s"}
# Parts of a body a detail may open with, like "fingers" in "fingers gripping the wheel", which are its target's.
PARTS = {"hands", "fingers", "eyes", "ears", "arms", "legs", "feet", "lips", "shoulders", "paws"}
DETAILS = re.compile(r" (?=(?:with|wearing|featuring|characterized by|dressed in) )")
# The kind of being a definition calls a subject after its name, like "man" in "an elderly man in his seventies".
KIND = re.compile(r"(?:a|an|the) (?:[\w'-]+ ){0,3}?([\w-]+)(?=[,.;:]| (?:in|with|wearing|who|whose|that|from|of|"
                  r"seen|dressed|featuring|characterized|and)\b|$)", re.I)
# A definition written as a sentence, like "The kitchen is a small room" or "The kitchen is warm", which the
# appositive "The kitchen, a small room" writes as a definition.
COPULA = re.compile(r"^((?:the|a|an) (?:(?!\b(?:who|whose|which|that|where|when)\b)[^,.;:])*?) is (?=\w)", re.I)
# Words of a subject's detail that tell its role as a reference instead of what it does in the shot.
ROLE = re.compile(r"\b(?:environment|appearance|preserv(?:ed|es|ing)|retain(?:ed|s|ing)|maintain(?:ed|s)|consistent|"
                  rf"reference|{SETTING})\b", re.I)
# Words after a subject that have no verb of their own, like "wearing a coat", "in a coat", "frozen in place" or
# "now quietly sleeping".
STATE = (r"(?:(?:\w+ly|now|still|also|just) )*(?:\w{2,}(?:ing|ed)|visible|frozen|in|at|on|by|near|beside|behind|"
         r"under|inside|against)\b")
# A later part with a verb of its own, like ", leans forward" in "<Subject 3>, holding his mug, leans forward" or
# ", is seated", but not a part like ", eyes wide", ", ears slightly perked" or ", freckles," in a list.
VERB = re.compile(r",\s*(?:and\s+)?(?:(?:is|was|has)\b|(?!(?:his|its|this|eyes|ears)\b)[a-z]\w*s\b"
                  r"(?!,|\s+and\b|\s+(?:\w+ly\s+)?\w+(?:ed|ing)\b))")
# Words that end in "s" without being a verb.
NOT_VERBS = r"(?:across|as|his|its|this|towards|upstairs|downstairs|indoors|outdoors)\b"
# The start of a predicate, like "sits by the window", "slowly turns" or "wearing a coat", which a description like
# "curly black hair" or "man in a cream sweater" doesn't have.
OPENS = re.compile(rf"(?:who|which|whose|with)\b|{STATE}|(?:(?:\w+ly|now|still|also|just) )*"
                   rf"(?:(?!{NOT_VERBS})[a-z]\w*s|are|were|can|could|will|would|may|might|must|did|had)\b", re.I)
# A composition written as a sentence, like "The composition remains…", "We see…", "<Subject 1> slowly turns…",
# "A close-up shot frames…", "A medium close-up focuses…" or "Her sleeve is visible…", which "cuts to" can't
# take, but not a close-up "of the lamp as it is lit" or "of the lamp, but the view is angled".
FRAMING = re.compile(r"^(?:(?:the|this) (?:composition|framing|frame|shot|scene|view|camera)|we|(?:<Subject \d+>"
                     r"(?: and <Subject \d+>)?|an? [\w -]{0,40}?\b(?:shot|close-up)) (?:\w+ly )?(?:is|are|was|were|"
                     rf"(?!{NOT_VERBS})[a-z]+s)|(?:an?|the|her|his|its|their)\b(?:(?!\b(?:who|whose|which|that|where|"
                     r"when|while|as|if|until|though|but)\b)[^.;:(])*?\b(?:is|are|was|were|has|have|had))\b", re.I)


def sentence(text):
    """`text` as sentences that open with a capital, also where it is part of one, like "and she turns, and"."""
    text = re.sub(r"^and\s+|(?:[,;]|\s+(?:and|but|or))+$", "", text.strip())
    text = re.sub(r"(?<=[^.][.!?] )[a-z]", lambda match: match.group(0).upper(), text)
    text = text[:1].upper() + text[1:]
    return text if text[-1:] in ".!?" else text + "."


def clause(text):
    """`text` continuing a sentence: without its full stop, and with a leading article or shot size in lowercase."""
    return OPENING.sub(lambda match: match.group(1).lower(), text.strip().rstrip(".").rstrip())


def listing(labels):
    return labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " and " + labels[-1]


def defined(definition, pictures):
    """A subject's `definition` without the name it starts with, or a relation after it as "Tom's granddaughter" in
    "Maya, Tom's granddaughter, a young woman", as a phrase where it is a sentence, with the pictures it comes from,
    each label in `pictures` with the roles it gives, after its first phrase as the guide writes them: "the young
    woman in <Picture 1>, with long dark hair", or where pictures give different parts of it, "the woman whose
    appearance comes from <Picture 1> and whose clothing comes from <Picture 3>"."""
    if subject_name(definition):
        definition = definition[NAME.match(definition).end():]
        definition = "the one " + definition if definition.startswith(("who ", "whose ")) else definition
    definition = COPULA.sub(r"\1, ", definition, count=1)
    first = definition.split(". ", 1)[0]
    match = DETAILS.search(first)
    if match:
        head, rest = definition[:match.start()], ", " + definition[match.end():]
    else:
        head, rest = first, definition[len(first):]
    if len({tuple(roles) for roles in pictures.values()}) == 1:
        source = " in " + listing(list(pictures))
    else:
        source = " " + " and ".join(
            f"whose {' and '.join(roles)} {'comes' if len(roles) == 1 else 'come'} from {picture}"
            for picture, roles in pictures.items())
    return head + source + rest


def about(label, detail, words, names, kind=None):
    """A shot reference's `detail` as a sentence about the target `label`, whose name or first phrase is `words`: a
    predicate follows the label, with "is" before its first part without a verb, like "wearing a coat" or, after
    "<Subject 2>, with red hair,", "in a coat", and in place of a "the" phrase before that part, like "the golden
    retriever" in "Biscuit the golden retriever lying on a rug", unless another part has one, with "has" for a lone
    "with" part, like "with a red collar", and without the "who" or "which" it opens with, or with "'s" for "whose".
    A sentence that opens with the label, those words, a "the" phrase of the `kind` a named target is, like "the
    elderly man" for Tom, an elderly man, or a pronoun opens with the label instead, and one that opens with a part
    of a body, like "fingers gripping the wheel", with the label's "'s". None for another sentence, such as one that
    opens with an article, another label or a subject's name in `names`, and for words that open no predicate, like
    "curly black hair"."""
    def predicate(rest):
        relative = re.match(r",?\s+(who|which|whose)\s+", rest, re.I)
        if relative and not VERB.search(rest, relative.end()):
            return ("'s " if relative.group(1).lower() == "whose" else " ") + rest[relative.end():]
        match = re.match(rf"\s+(?:the(?:\s+[\w-]+){{1,3}}?\s+)?(?={STATE})", rest, re.I) or rest.startswith(
            ",") and re.search(rf",\s*(?={STATE})", rest, re.I)
        held = re.match(r",?\s+with\s+", rest, re.I)
        if held and not match and not VERB.search(rest, held.end()):
            return " has " + rest[held.end():]
        if not match or VERB.search(rest, 0, match.start()) or VERB.search(rest, match.end()):
            return rest
        return rest[:match.start()] + (" is " if match.start() == 0 else ", is ") + rest[match.end():]

    if detail.startswith(label):
        return label + predicate(detail[len(label):])
    if detail[:1] in "<@":
        return None
    match = re.match(rf"(?:(?:the|a|an) )?{re.escape(words)}\b('s)?", detail, re.I) if words else None
    if not match and kind:
        match = re.match(rf"the (?:[\w'-]+ ){{0,2}}?{re.escape(kind)}\b('s)?", detail, re.I)
    if match and detail[match.end():].strip():
        rest = detail[match.end():]
        return label + (match.group(1) + rest if match.group(1) else predicate(rest))
    first = detail.split(" ", 1)[0]
    if first.capitalize() in PRONOUNS:
        return label + PRONOUNS[first.capitalize()] + detail[len(first):]
    if first.lower() in PARTS:
        return f"{label}'s {detail[:1].lower()}{detail[1:]}"
    if first.lower() in ("the", "a", "an") or first.removesuffix("'s") in names:
        return None
    if detail[:1].islower():
        return label + predicate(" " + detail) if OPENS.match(detail) else None
    if first.endswith("s") and first not in NOT_NAMES:
        return f"{label} {detail[:1].lower()}{detail[1:]}"
    return None


def _restated(detail, label, words):
    """Whether a shot reference's `detail` about `label` only says again what the definition of the `words` says, as
    "small stone kitchen with a stove" does after "the kitchen, a small stone kitchen with a stove" and "<Subject 2>'s
    curly black hair" after "Maya, a woman with curly black hair"."""
    said = re.findall(r"[\w'-]+", detail.replace(label + "'s", "").lower())
    return len(said) > 2 and set(said) <= words


def clock(ms):
    return f"{ms // 60000:02d}:{ms % 60000 // 1000:02d}.{ms % 1000:03d}"


def alignment(context, shots):
    """The guide's first line of an I2VA, FL2VA or L2VA prompt of `shots` shots, with logical mentions; "" for
    T2VA and Ref2VA."""
    first, last, duration = context.slots.first, context.slots.last, f"{context.duration:.2f}"
    if context.mode == "I2VA":
        return f"For the target video, at 0.00 seconds into the target video, @{first} (from [Shot 1]) is fully referenced."
    if context.mode == "FL2VA":
        return (f"How the reference pictures align with the target video — @{first} (from Shot 1) aligns with the "
                f"0.00-second mark of the target video; @{last} (from Shot {shots}) aligns with the {duration}-second "
                "mark of the target video.")
    if context.mode == "L2VA":
        return (f"How the reference pictures align with the target video — @{last} (from [Shot {shots}]) aligns with "
                f"the {duration}-second mark of the target video.")
    return ""


def speaker_order(data):
    order = {}
    for shot in data["shots"]:
        for line in shot["dialogue"]:
            for name in line["speakers"]:
                order.setdefault(name, f"S{len(order) + 1}")
    return order


def _labelled(value, labels, field=""):
    """`value` with each subject ID in its descriptions written as that subject's label."""
    if isinstance(value, dict):
        return {key: _labelled(item, labels, key) for key, item in value.items()}
    if isinstance(value, list):
        return [_labelled(item, labels, field) for item in value]
    if isinstance(value, str) and field in PROSE_FIELDS:
        return SUBJECT_ID.sub(lambda match: labels[match.group(0)], value)
    return value


def compile_prompt(data, context, analysis=None):
    """Validate then return Timeline text with logical mentions. Never calls a model."""
    data = validate_prompt(data, context, analysis)
    labels = {name: f"@{name}" for name in context.references}
    used, phrases, kinds, names, worded = {}, {}, {}, set(), {}
    if analysis:
        analysis = validate_analysis(analysis, context)
        left_out = spare(data, analysis)
        analysis = dict(analysis, subjects=[item for item in analysis["subjects"] if item["id"] not in left_out])
        data = dict(data, retention={key: value for key, value in data["retention"].items() if key not in left_out})
        labels.update({item["id"]: f"<Subject {i}>" for i, item in enumerate(analysis["subjects"], 1)})
        used = appearances(data, analysis)
        for item in analysis["subjects"]:
            phrase = re.sub(r"^(?:a|an|the) ", "", subject_words(item["definition"]), flags=re.I)
            if subject_name(item["definition"]) or " " in phrase:
                phrases[item["id"]] = phrase
            kind = subject_name(item["definition"]) and KIND.match(item["definition"],
                                                                   NAME.match(item["definition"]).end())
            if kind:
                kinds[item["id"]] = kind.group(1)
        names = {subject_name(item["definition"]) for item in analysis["subjects"]} - {None}
        worded = {item["id"]: set(re.findall(r"[\w'-]+", item["definition"].lower())) for item in analysis["subjects"]}
        analysis = _labelled(analysis, labels)
    data = _labelled(data, labels)
    speaker_ids = speaker_order(data)
    speakers = {item["id"]: item for item in data["speakers"]}
    retention = data.get("retention", {})
    anchors = {item["reference"]: item["role"] for item in analysis["picture_anchors"]} if analysis else {}

    def audio_use(name):
        relation = retention[name]["relationship"]
        phrase = {"fully_copy": "is copied in full", "partially_copy": "is partially copied",
                  "reference": "provides an audio reference", "weak_reference": "provides a weak audio reference"}
        return f"{labels[name]} {phrase[relation]}."

    shots = []
    seen_speakers = set()
    for i, shot in enumerate(data["shots"]):
        parts = [f"[Shot {i + 1}]"]
        if i and not shot["cut"]:
            parts += [f"At {clock(shot['start_ms'])}, the view continues without a cut.", sentence(shot["composition"])]
        elif i and FRAMING.match(shot["composition"]):
            parts += [f"At {clock(shot['start_ms'])}, the camera cuts to a new shot.", sentence(shot["composition"])]
        elif i:
            parts.append(sentence(f"At {clock(shot['start_ms'])}, the camera cuts to {clause(shot['composition'])}"))
        else:
            if not analysis:
                parts.append(sentence(data["style"]))
            if context.carried_frames:
                parts.append(CONTINUATION)
            parts.append(sentence(shot["composition"]))
            if context.slots.first and not analysis:
                parts.append(f"The shot begins from {labels[context.slots.first]}.")
        told = " ".join([shot["composition"], *shot["actions"], *(
            labels[speakers[name]["subject"]] for line in shot["dialogue"] for name in line["speakers"]
            if speakers[name]["subject"])])
        begun, closing = set(), []
        for ref in shot["references"]:
            target = ref["target"]
            first = target not in begun
            begun.add(target)
            role = anchors.get(target) or ("audio" if target.startswith(("audio", "video_audio")) else "subject")
            line = None if role == "subject" and (ROLE.search(ref["detail"]) or _restated(
                ref["detail"], labels[target], worded.get(target, set()))) else about(
                labels[target], ref["detail"], phrases.get(target), names, kinds.get(target))
            if (line is None and first and role in ("subject", "composition", "storyboard")
                    and labels[target] not in told):
                line = f"{labels[target]} {PLACED[role]}"
            line = sentence(line) if line and line.rstrip(".").lower() not in told.lower() else ""
            if first and role == "last_frame":
                closing += [f"The shot ends on {labels[target]}.", line]
                continue
            if first and role == "first_frame":
                parts.append(f"The shot begins from {labels[target]}.")
            elif first and role == "keyframe":
                parts.append(f"The shot's keyframe corresponds to {labels[target]}.")
            parts.append(line)
            if first and role == "audio" and analysis:
                parts.append(audio_use(target))
        parts.extend(sentence(action) for action in shot["actions"])
        camera = shot["camera"]
        movement = "The camera " + CAMERA_ACTIONS[camera["type"]]
        if camera["type"] not in ("Static Shot", "POV"):
            if camera["amplitude"] != "normal":
                movement += f" with {camera['amplitude']} amplitude"
            if camera["speed"] != "normal":
                movement += f" at {camera['speed']} speed"
        if not re.search(r"\bcamera\b", told, re.I):
            parts.append(movement + ".")
        for line in shot["dialogue"]:
            voices = []
            introductions = []
            for name in line["speakers"]:
                speaker = speakers[name]
                if speaker["subject"]:
                    voices.append(labels[speaker["subject"]])
                    if name not in seen_speakers:
                        introductions.append(clause(speaker["description"]))
                else:
                    voices.append(speaker["description"].strip().rstrip("."))
                seen_speakers.add(name)
            ids = ",".join(speaker_ids[name] for name in line["speakers"])
            action = ("says in an off-screen voiceover" if line["voiceover"] else
                      "sings" if line["singing"] else "says")
            voice = " and ".join(voices) + f" ({ids})"
            voice = voice[:1].upper() + voice[1:]
            delivery = line["delivery"].strip().rstrip(".")
            if any(re.search(rf"\b{re.escape(delivery)}\b", text, re.I) for text in [*introductions, *voices]):
                delivery = ""
            modifiers = [text[0].lower() + text[1:] if text[1:2].islower() or text.startswith("A ") else text
                         for text in [*introductions, delivery] if text]
            if modifiers:
                voice += ", " + ", ".join(modifiers) + ","
            incoming_cut = line["from_previous"] and shot["cut"]
            outgoing_cut = line["to_next"] and i + 1 < len(data["shots"]) and data["shots"][i + 1]["cut"]
            words = ("<scenetrans>" if incoming_cut else "") + line["text"]
            words += "<scenetrans>" if outgoing_cut else "<cutoff>" if line["cutoff"] else ""
            spoken = f"{voice} {action}: <d>[{line['language']}] {words}</d>"
            if line["voiceover"]:
                spoken += " while the corresponding on-screen characters' lips remain completely closed."
            if line["from_previous"] or line["to_next"]:
                spoken += (" The audio continues seamlessly across the cut." if incoming_cut or outgoing_cut
                           else " The audio continues seamlessly.")
            parts.append(spoken)
        parts.extend(sentence(sound) for sound in shot["diegetic_audio"])
        parts += closing
        if i == len(data["shots"]) - 1 and context.slots.last and not analysis:
            parts.append(f"By the end, the composition and visible state converge on {labels[context.slots.last]}.")
        shots.append(" ".join(part for part in parts if part))

    sound, music = data["overall_soundscape"], data["non_diegetic_music"]
    if not analysis:
        fields = [("integrated_multimodal_description", "\n".join(shots)), ("overall_soundscape", sound),
                  ("non_diegetic_music", music)]
        line = alignment(context, len(shots))
        return (line + "\n\n" if line else "") + "\n\n".join(f"{key}: {value}" for key, value in fields)

    def shots_of(target):
        return ", ".join(f"[Shot {number}]" for number in used[target])

    definitions = []
    for subject in analysis["subjects"]:
        pictures = {}
        for source in subject["sources"]:
            pictures.setdefault(labels[source["reference"]], []).append(source["role"])
        definitions.append(sentence(f"{labels[subject['id']]} is {defined(clause(subject['definition']), pictures)}"))
    for anchor in analysis["picture_anchors"]:
        definitions.append(sentence(f"{labels[anchor['reference']]} is {ANCHORS[anchor['role']]} "
                                    f"{shots_of(anchor['reference'])}, showing {clause(anchor['definition'])}"))
    subject_speakers = {s["subject"]: speaker_ids[s["id"]] for s in data["speakers"] if s["subject"]}
    for video in analysis["video_roles"]:
        definitions.append(sentence(f"{labels[video['reference']]} is {clause(video['definition'])}"))
    for audio in analysis["audio_roles"]:
        roles = ", ".join(role.replace("_", " ") for role in audio["roles"])
        target = ""
        if audio["subject"]:
            target = f" for {labels[audio['subject']]}"
            if audio["subject"] in subject_speakers:
                target += f" ({subject_speakers[audio['subject']]})"
        definitions.append(sentence(f"{labels[audio['reference']]} provides {roles}{target}: {audio['definition']}"))
    task_types = []
    if any(item["role"] in ("first_frame", "last_frame", "keyframe") for item in analysis["picture_anchors"]) or context.slots.first or context.slots.last:
        task_types.append("keyframe completion")
    if analysis["subjects"] or analysis["video_roles"] or any(item["role"] in ("composition", "storyboard") for item in analysis["picture_anchors"]):
        task_types.append("reference generation")
    if any("audio_reuse" in item["roles"] for item in analysis["audio_roles"]):
        task_types.append("audio reuse")
    if any(any(role != "audio_reuse" for role in item["roles"]) for item in analysis["audio_roles"]):
        task_types.append("audio reference")
    retained = []
    for target in targets(analysis):
        where = shots_of(target)
        if target.startswith(("audio", "video_audio")) or not where:
            where = ""
        elif target in anchors:
            where = f" ({where} {anchors[target].replace('_', ' ')})"
        else:
            where = f" (appears in {where})"
        item = retention[target]
        retained.append(f"{labels[target]}{where}: {item['relationship']} - {sentence(item['detail'])}")
    # Separate native guides are deliberately not invented as Picture sources.
    if context.slots.first:
        shots[0] += " The opening matches the supplied first-frame guide."
    if context.slots.last:
        shots[-1] += " The final composition converges on the supplied last-frame guide."

    def layer(text, names):
        uses = [audio_use(name) for name in names]
        return " ".join(uses if uses and text.strip().upper() == "N/A" else [text, *uses])

    summary = sentence(data["summary"])
    featured = [labels[name] for name in subjects(analysis) if labels[name] not in summary]
    others = [labels[name] for name in targets(analysis) if not name.startswith("subject_")]
    also = [f"features {listing(featured)}" if featured else "", f"uses {listing(others)}" if others else ""]
    also = " and ".join(part for part in also if part)
    fields = [("subject_definitions", "\n".join(definitions)),
              ("summary", f"[{' + '.join(task_types)}] {summary}" + (f" It {also}." if also else "")),
              ("retention_analysis", "\n".join(retained)),
              ("detailed_description", sentence(data["style"]) + "\n" + "\n".join(shots)),
              ("overall_soundscape", layer(sound, data["soundscape_references"])),
              ("non_diegetic_music", layer(music, data["music_references"]))]
    return "\n\n".join(f"{key}:\n{value}" for key, value in fields)
