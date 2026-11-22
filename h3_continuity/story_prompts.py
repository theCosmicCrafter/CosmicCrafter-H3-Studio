"""What H3 Story asks the model and how it checks the replies: the story request, one request per box, and the
Timeline's own rules for mentions, modes and tags. Pure Python."""

import copy
import dataclasses
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

from . import story_lengths as lengths
from . import story_templates, story_stages, timed_text, timeline as rules
from .timing import FPS

SHOWN_REPLY = 500
NAME = re.compile(r"@?(image|audio|video_audio|video)\s*(\d+)(?:\s*\(.*\))?", re.IGNORECASE)
THINK = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
THINK_END = re.compile(r"</think>", re.IGNORECASE)
SAID = re.compile(r"<d>\s*(?:\[[^\]]*\]\s*)?(.*?)</d>", re.IGNORECASE | re.DOTALL)
FIXED = {"rendered": "fixed, already rendered", "kept": "fixed, the user's prompt"}
def load_h3_guides(directory=None):
    """Load locally installed MiniMax guides when available."""
    directory = Path(directory) if directory is not None else Path(__file__).with_name("h3_guide")
    guides = {}
    for name in ("base", "ref"):
        path = directory / f"{name}-en.txt"
        guides[name] = (path.read_text(encoding="utf-8") if path.is_file() else
                        f"Optional MiniMax H3 {name} prompt guide is not installed. "
                        "Consult the official MiniMax H3 prompt-writing documentation.")
    return guides


GUIDE = load_h3_guides()

# Adapted from the Singularity writing specification; provenance in docs/H3-PROMPT-WRITING.md.
BOX_PLANNING_RULES = """- Budget natural actions, speech, reactions and holds, then split into short, independently editable boxes by default. Prefer several short boxes even for one continuous take: the Timeline carries the previous latent and motion. A 15-second take can add 2 + 3 + 4 + 4 + 2 seconds across continuing boxes, with no cuts after the first. These NEW durations are illustrative, not a required count or template. Never rush content or add padding.
- Prefer generated clips under about 10 seconds, replay included. This is a soft preference; 15 seconds is the hard limit, not a target. A longer box needs an explicit user request or a concrete benefit continuation cannot preserve; explain it briefly in the beat. Continuous motion, a locked camera, shared cast, setting or one dramatic beat alone do not justify a long box. Plan enough boxes for the total instead of stretching a few.
- Boxes are render jobs, not camera cuts. Split at playable action stages as well as edits. For unbroken action after box 1 use new_shot=false, new_scene=false and join kind continue; preserve pose, momentum and direction without a pause or reset. Shot sections are timed stages; continuous/static views can use several with cut=false. For a longer box, describe its distinct stages in the beat. A character limit applies per shot, not across all shots.
- Choose playable beats that fit the total; do not compress a large idea into it. Two-second boxes are valid when playable with the supplied replay. No minimum preferred length or equal split. Avoid needless fragmentation or filling to the limit. In automatic-length mode the total is a ceiling, not time to fill."""


SELF_CONTAINED = """Write every video prompt as a self-contained scene. H3 renders each box alone: it knows only this prompt and
this clip's supplied inputs, replayed frames included, and has not seen the story, the plan or any other box.
Use neighboring beats, endings and replay timing only to derive explicit local setting, people, poses, props,
light, motion and sound. Every composition, action, camera line, ending and summary reads alone: who acts, on
what, where, in what pose, moving which way. Never point outside this clip: no box numbers or words that assume
an earlier moment, like 'continues', 'resumes', 'again', 'as before', 'previous' or 'already'."""

# Words of writer or planner prose that assume H3 saw a moment outside the clip.
RELATIVE = re.compile(r"\b(?:box \d+|continu(?:e|es|ed|ing)|resum(?:e|es|ed|ing)|again|once more|as before|"
                      r"previous(?:ly)?|earlier|already|from before|(?:picks? up|left off) where)\b", re.I)


def relative_wording(texts):
    """The distinct words in `texts` that assume a moment outside the clip, like "continues" or "again"."""
    return list(dict.fromkeys(match.group(0).lower() for text in texts for match in RELATIVE.finditer(text or "")))


H3_WRITING_RULES = SELF_CONTAINED + """

Describe visible mechanics rather than broad action labels. Detail develops the assigned event; it does not
add events to fill a checklist. A quiet hold or locked camera can be the complete shot.
- Establish framing, camera position, subject placement/depth and starting pose. Describe an action's onset,
  development and reached state; preparation, momentum, contact, reaction and recovery apply only when relevant
  and playable. Keep intended background movement continuous, with consistent direction and spacing.
- Tie camera movement or a fixed view to what it follows, reveals or keeps framed. Give direction; add speed,
  amplitude and focus changes only when meaningful. 'Dynamic camera' alone does not describe movement.
- Show emotion through gaze, face, breath, posture or grip, tied to what the character notices or reacts to.
- Intended effects have a trigger, source, form, motion/decay and consequence. Relevant cloth, hair, dust,
  recoil or reflections respond to the same force/contact; do not invent an effect or additional action.
- Specify light source/direction, color and material response rather than relying on quality adjectives.
  Atmosphere, reflections and light changes follow the scene; motion blur belongs to rapid movement.
- Within continuous action, carry screen direction, pose, prop ownership/state and persistent damage across
  shots. A planned change of time or place may establish a new state; an angle change alone does not reset it."""
H3_WRITING_GUIDANCE = ("Shot-writing guidance, subordinate to the creative Guide, supplied mode, schema and timing:\n"
                       + H3_WRITING_RULES)

TRANSITION_GUIDANCE = """Choose seamless continuation, a scene-driven H3 transition, or a hard cut to serve story,
rhythm and Guide. Continue unbroken action; cut when a new beat, view, place or time benefits the edit.
Use transitions only when a motivated connection helps. Animation may be expressive, cinema restrained;
context decides. You choose the mechanism; examples are illustrative.
Give transitions a visible cause in action, light, environment, camera movement or animation language.
A back can approach, cover the lens and clear into the next view; a light behind the action can bloom
as the camera turns toward it. Generate cause, cover and reveal inside H3, without FFmpeg or added overlays.
Start within outgoing action. Preserve momentum, identity, pose and screen direction: no waiting pose,
unconcealed framing jump or repeated effect in new frames. Start from the ending and revealed state,
written out in full; code supplies replay. Moving beats span continuing boxes; a separate tiny bridge is optional.
Respect fixed box boundaries and cuts. Auto-plan boundaries and playable durations around the movement.
Intentional quiet holds remain valid when the story or Guide calls for them."""

STORY_INSTRUCTIONS = """You plan a short film that the video model H3 renders as consecutive clips called boxes.
The user gives a raw idea. Turn it into one continuous story told across the boxes exactly as they are: their number, their lengths, the cuts between them and their first and last frames are fixed.

- A box that continues the box before it opens by replaying the end of that box, so it picks up exactly where that box ends: the same people, clothes, place, light and motion.
- A box marked "new shot of the same scene" follows a cut to another camera angle: it doesn't replay the box before, but keeps its people, clothes, place and light. A box marked "new scene" follows a cut and can start in another place or time.
- Fixed boxes already have prompts. Take their events as given and build the other boxes around them.
- References are pictures and sounds the user connected, named like image1 and audio1. H3 takes at most 9 images and 3 audios per box, so list in a box's "references" only those that box shows or plays, the most important first: the people on screen, then the place, then the rest. References the shared direction mentions are in every box and count toward those limits, so leave them out of "references", like the first and last frames, which are already set.
- The cast lists each person, place and object that references show, by name, with the references that show it. A box's "on_screen" names the cast members seen in that box, its ending included, and Write adds their references to it; someone only heard or talked about there is not on screen.
- The continuity sheet describes each person, place and important object once, precisely, and how the voice of each person who speaks sounds, so that every box can describe them the same way. It names a reference only beside what that reference shows.
- A creative guide, when there is one, holds the user's rules for every box: plan each beat, "on_screen" and "references" so that the box can follow them.
- The guide overrides conflicting creative details in the idea. Fit each beat's actions, dialogue and reactions to the box's NEW seconds, excluding replay. A short box needs a simple event, not many events played faster. Preserve mandatory content; if it cannot fit the fixed Timeline, identify the conflict. A box can contain several camera shots, each with its own visible cast; describe that coverage in the beat. A per-shot character limit is not a limit on the union across those shots.
- Suggest a reference picture when a person, place or object recurs and no reference shows it. Suggestions are optional.

Reply with one JSON object and nothing else:
{"title": "...", "sheet": "...", "cast": [{"name": "Maya", "references": ["image2"]}, {"name": "the kitchen", "references": ["image1"]}], "boxes": [{"box": 1, "beat": "what happens, in one or two sentences", "on_screen": ["Maya"], "references": ["image1"], "ends": "the last moment on screen"}], "suggestions": [{"what": "...", "why": "...", "boxes": [2, 3], "description": "what the picture should show"}]}
"boxes" has one entry per box, in order. "cast", "on_screen" and "suggestions" may be empty."""

PLAN_INSTRUCTIONS = """You plan a short film that the video model H3 renders as consecutive clips called boxes.
The user gives a raw idea. Turn it into one continuous story and split it into boxes: choose how many boxes there are, how long each one is and where the cuts go.

""" + BOX_PLANNING_RULES + """
- "seconds" is how long a box adds to the film. A box that continues the box before it opens by replaying the end of that box, so it picks up exactly where that box ends: the same people, clothes, place, light and motion. H3 generates its seconds plus that replayed part.
- Set "new_shot" to true for a box that follows a cut. Box 1 is always a new shot. A cut keeps the scene: the same people, clothes, place and light, seen from another camera angle. Set "new_scene" to true only for a new shot that moves to another place or time; Box 1 is always a new scene. One unbroken action continues from box to box.
- References are pictures and sounds the user connected, named like image1 and audio1. H3 takes at most 9 images and 3 audios per box, so list in a box's "references" only those that box shows or plays, the most important first: the people on screen, then the place, then the rest. References the shared direction mentions are in every box and count toward those limits, so leave them out of "references".
- The cast lists each person, place and object that references show, by name, with the references that show it. A box's "on_screen" names the cast members seen in that box, its ending included, and Write adds their references to it; someone only heard or talked about there is not on screen.
- The continuity sheet describes each person, place and important object once, precisely, and how the voice of each person who speaks sounds, so that every box can describe them the same way. It names a reference only beside what that reference shows.
- A creative guide, when there is one, holds the user's rules for every box: plan each beat, "on_screen" and "references" so that the box can follow them.
- The guide overrides conflicting creative details in the idea. Honor hard limits in every planned shot, counting background figures and arrivals. Use only the references those shots need; don't place unused cast in an establishing group shot.
- Suggest a reference picture when a person, place or object recurs and no reference shows it. Suggestions are optional.

Reply with one JSON object and nothing else:
{"title": "...", "sheet": "...", "cast": [{"name": "Maya", "references": ["image2"]}, {"name": "the kitchen", "references": ["image1"]}], "boxes": [{"box": 1, "seconds": 6, "new_shot": true, "new_scene": true, "beat": "what happens, in one or two sentences", "on_screen": ["Maya"], "references": ["image1"], "ends": "the last moment on screen"}], "suggestions": [{"what": "...", "why": "...", "boxes": [2, 3], "description": "what the picture should show"}]}
"boxes" has one entry per box, in order, at most 100. "cast", "on_screen" and "suggestions" may be empty."""


TEXT = {"type": "string"}

def guide_direction(ctx):
    """The current Guide, as every writer reads it."""
    if not ctx.guide.strip():
        return ""
    return "Current creative Guide (requirements, not optional format advice):\n" + ctx.guide


def _object(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def _reply_format(name, schema):
    return {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}}


def prompt_text(reply, ctx, index, context, plan=None, notes=None):
    """Keep prose permissively; only reject empty text, impossible timestamps or unrenderable asset bindings."""
    text = strip_reasoning(reply)
    text = re.sub(r"\A```[^\n]*\n|\n```\s*\Z", "", text).strip()
    if text.startswith("{"):
        try:
            wrapped = json.loads(text)
            if isinstance(wrapped, dict) and isinstance(wrapped.get("prompt"), str):
                text = wrapped["prompt"].strip()
        except ValueError:
            pass
    if not text:
        raise ValueError("the model returned no prompt text")
    # Asset numbering belongs to the actual box's slots, not the global image names.
    for name, tag in context.slots.tags.items():
        text = text.replace(tag, "@" + name)
    # Fix duplicated cue syntax without touching the words spoken inside <d>.
    parts = re.split(r"(<d>[\s\S]*?(?:</d>|$))", text)
    text = "".join(part if part.startswith("<d>") else re.sub(
        r"\bsays:\s*(\(S\d+(?:,S\d+)*\)\s+says:)", r"\1", part) for part in parts)
    if plan:
        # Only unambiguous, single-image identities from the plan can repair a wrong binding.
        # Do not guess from prose, reorder assets, or alter multi-source definitions.
        section = re.search(r"(?ms)^\s*subject_definitions:\s*(.*?)(?=^\s*\w+:|\Z)", text)
        if section:
            body = section.group(1)
            entries = list(re.finditer(r"<Subject [1-9]\d*>\s+is\s+", body))
            for entry, end in reversed(list(zip(entries, [e.start() for e in entries[1:]] + [len(body)]))):
                definition = body[entry.end():end]
                matches = [(name, refs) for name, refs in plan.cast.values()
                           if re.match(re.escape(name) + r"(?=\s*[,.;:]|\s+(?:in|from)\b|$)", definition, re.I)]
                sources = list(rules.MENTION.finditer(definition))
                if len(matches) != 1 or len(sources) != 1 or sources[0].group(1).lower() != "image":
                    continue
                name, refs = matches[0]
                if len(refs) != 1 or not refs[0].startswith("image") or sources[0].group(0) == "@" + refs[0]:
                    continue
                fixed = definition[:sources[0].start()] + "@" + refs[0] + definition[sources[0].end():]
                body = body[:entry.end()] + fixed + body[end:]
                if notes is not None:
                    notes.append(f"Box {index + 1}: restored {name}'s reference binding from the cast: @{refs[0]}.")
            text = text[:section.start(1)] + body + text[section.end(1):]
    if ctx.renderer != "image":
        text = with_timeline_audio(text, ctx, index)
    connected = mentionable(ctx)
    unknown = [name for _, name in rules.mentions(text) if name not in connected]
    if unknown:
        raise ValueError("unconnected references: " + ", ".join(unknown))
    slots = slots_for(ctx, index, text)
    if len(slots.image_inputs) > rules.MAX_REF_IMAGES or len(slots.audio_inputs) > rules.MAX_REF_AUDIOS:
        raise ValueError("the prompt exceeds H3's 9 image / 3 audio limit")
    # ponytail: only explicit clock/Duration metadata is mechanical; prose timing is guidance, not a verdict.
    times = [int(m) * 60 + float(s) for m, s in re.findall(
        r"(?:\[Shot\s+\d+\]\s*(?:At\s+)?|^At\s+)(\d{1,2}):(\d{2}(?:\.\d+)?)", text, re.I | re.M)]
    times += [float(s) for s in re.findall(r"(?im)^\s*(?:clip |video |total )?duration\s*:\s*(\d+(?:\.\d+)?)\s*s", text)]
    if times and max(times) > context.duration + 1 / FPS:
        raise ValueError(f"a timestamp or duration exceeds this clip's {context.duration:.3f} seconds")
    return text


@dataclass
class Reference:
    name: str
    title: str = ""
    path: str | None = None
    file: dict | None = None

    @property
    def label(self):
        return f"@{self.name} ({self.title})" if self.title else f"@{self.name}"


@dataclass
class StoryBox:
    id: str
    number: int
    frames: int
    carried: int
    fresh: bool
    first: str
    last: str
    prompt: str
    status: str
    last_frame: str | None = None
    new_scene: bool = False


@dataclass
class StoryContext:
    """What a Write works from. `thinking` is "off" or an API reasoning effort level. `descriptions` maps reference names,
    such as image2, to what their pictures show. `links` maps the story node's input names, such as model or
    descriptions.image2, to the links Write runs in ComfyUI for their texts, in the API prompt `snapshot`; until
    then those texts are "". `notes` says what reading the snapshot left out. `bible` is the Timeline's Story bible
    or None, `box_fields` has each box's saved schedule, join, cast and source by box id, and `hand_edited` lists,
    by box id, the entities whose definition line in the box's prompt differs from the bible's. `template` is the
    story_templates.Template Write follows, or None. `story_thinking` overrides the initial plan and writer image
    descriptions; "same as boxes" inherits `thinking`. `story_model` and `story_base_url` select their provider;
    empty values inherit `model` and `base_url`."""
    idea: str
    guide: str
    base_url: str
    model: str
    pictures: bool
    shared: str
    context_frames: int
    timeline: rules.Timeline
    boxes: list
    references: list
    timeline_id: str
    story_id: str
    free_vram: bool = True
    total_seconds: int = 0
    thinking: str = "medium"
    descriptions: dict = dataclasses.field(default_factory=dict)
    links: dict = dataclasses.field(default_factory=dict)
    snapshot: dict = dataclasses.field(default_factory=dict, repr=False)
    notes: list = dataclasses.field(default_factory=list)
    saved_plan: dict | None = None
    regenerate: bool = False
    vision_base_url: str = ""
    vision_model: str = ""
    reference_descriptions: dict = dataclasses.field(default_factory=dict)
    bible: dict | None = None
    box_fields: dict = dataclasses.field(default_factory=dict)
    hand_edited: dict = dataclasses.field(default_factory=dict)
    template: object = None
    story_thinking: str = "same as boxes"
    idea_images: list = dataclasses.field(default_factory=list)
    idea_descriptions: dict = dataclasses.field(default_factory=dict)
    idea_references: dict = dataclasses.field(default_factory=dict)
    idea_picture_before: dict = dataclasses.field(default_factory=dict)
    renderer: str = "video"
    image_model: str = ""
    story_model: str = ""
    story_base_url: str = ""

    @property
    def initial_base_url(self):
        return self.story_base_url or self.base_url

    @property
    def initial_model(self):
        return self.story_model or self.model

    @property
    def initial_thinking(self):
        return self.thinking if self.story_thinking == "same as boxes" else self.story_thinking

    @property
    def planning(self):
        """Whether Write plans the boxes: the Timeline has none."""
        return not self.timeline.boxes

    @property
    def targets(self):
        return [item for item in self.boxes if item.status == "write"]

    def label(self, name):
        found = next((ref for ref in self.references if ref.name == name), None)
        return found.label if found else f"@{name}"


@dataclass
class Beat:
    box: int
    beat: str
    references: list
    ends: str
    on_screen: list = dataclasses.field(default_factory=list)
    shots: list = dataclasses.field(default_factory=list)
    terminal_state: str = ""
    # How each subject looks at the end of this box when a Fast box changed it, by subject name.
    looks: dict = dataclasses.field(default_factory=dict)
    # The subject definition lines Fast wrote for this box, by subject name: label, text after "is", and whether
    # the user had edited it.
    definitions: dict = dataclasses.field(default_factory=dict)
    stages: list = dataclasses.field(default_factory=list)


@dataclass
class StoryPlan:
    """A parsed story reply; `notes` says what a lenient parse left out, and `cast` has the name and references of
    each cast member, by the name as `_called` has it."""
    title: str
    sheet: str
    beats: list
    suggestions: list
    frames: list = dataclasses.field(default_factory=list)
    cuts: list = dataclasses.field(default_factory=list)
    notes: list = dataclasses.field(default_factory=list)
    cast: dict = dataclasses.field(default_factory=dict)
    scenes: list = dataclasses.field(default_factory=list)


def said_in(prompt):
    """The dialogue lines of a saved H3 prompt."""
    return [re.sub(r"<[^>]*>", "", line).strip() for line in SAID.findall(prompt)]


def clock(seconds):
    """`seconds` as MM:SS.mmm."""
    millis = round(seconds * 1000)
    return f"{millis // 60000:02d}:{millis % 60000 // 1000:02d}.{millis % 1000:03d}"


def strip_reasoning(text):
    """`text` without <think> blocks, and without everything before a closing </think> left on its own."""
    text = THINK.sub("", text)
    ends = list(THINK_END.finditer(text))
    return (text[ends[-1].end():] if ends else text).strip()


def excerpt(reply):
    """The start of a reply, on one line, for error messages."""
    return " ".join(reply.split())[:SHOWN_REPLY]


def story_boxes(timeline, context, statuses, last_frames):
    """StoryBoxes for the parsed `timeline`: statuses[i] is "write", "rendered" or "kept"; `last_frames` maps a box
    id to the file of its rendered last frame."""
    boxes = []
    for index, box in enumerate(timeline.boxes):
        frames, carried = rules.box_length(timeline, index, context)
        fresh = rules.is_fresh(timeline, index)
        boxes.append(StoryBox(box.id, index + 1, frames, carried, fresh,
                              box.first if fresh and box.first not in timeline.disabled_refs else "",
                              box.last if box.last not in timeline.disabled_refs else "",
                              box.prompt, statuses[index], last_frames.get(box.id), index > 0 and box.cut and box.new_scene))
    return boxes


def planned_context(ctx, planned):
    """`ctx` on the Timeline `planned`, which Write planned: every box is one to write."""
    for name in ("refmods", "disabled_refs", "audio_clips", "timed_text", "reference_descriptions", "reference_replacements", "plates", "pictures"):
        setattr(planned, name, copy.deepcopy(getattr(ctx.timeline, name)))
    return dataclasses.replace(ctx, timeline=planned,
                               boxes=story_boxes(planned, ctx.context_frames, ["write"] * len(planned.boxes), {}))


def own_pictures(ctx):
    """Each image slot only boxes' first and last frames use, with the numbers of those boxes. A slot is a reference
    instead when the shared direction or a box's prompt mentions it (a prompt naming its own box's frames aside), a
    bible entity or look has it, or a RefMod fills it."""
    used = {name for _, name in rules.mentions(ctx.shared)} | {item["slot"] for item in ctx.timeline.refmods}
    for entity in (ctx.bible or {}).get("entities", []):
        used.update(entity["pictures"], *(look.get("pictures", []) for look in entity["looks"]))
    for box in ctx.boxes:
        used.update(name for _, name in rules.mentions(box.prompt) if name not in (box.first, box.last))
    own = {}
    for box in ctx.boxes:
        for name in dict.fromkeys(filter(None, (box.first, box.last))):
            if name not in used:
                own.setdefault(name, []).append(box.number)
    return own


def _facts(ctx, box):
    start = (f"continues box {box.number - 1}" if not box.fresh else "new shot" if box.number == 1
             else "new scene" if box.new_scene else "new shot of the same scene")
    parts = [f"{box.frames / FPS:.2f} s", start]
    if box.first:
        parts.append(f"first frame {ctx.label(box.first)}")
    if box.last:
        parts.append(f"last frame {ctx.label(box.last)}")
    return ", ".join(parts)


def _plan_lines(ctx):
    carried = ctx.context_frames / FPS
    total, most = ctx.total_seconds, lengths.SOFT_MAX_SECONDS
    if total:
        first = f"Plan the boxes: the film runs {total} s, so their seconds add up to {total}."
    else:
        first = f"Plan the boxes: choose the length the idea needs, at most {lengths.AUTO_MAX_SECONDS} s in total."
    return [first, f"A box that continues the one before it opens with the last {carried:g} s of that box.",
            f"The hard generated-clip limit is {rules.MAX_FRAMES // FPS} s (the Timeline snaps to its frame grid). "
            f"A continuing box includes {carried:g} s of replay in that limit. Prefer generated clips under about "
            f"{most} s, including replay, by planning more short continuing boxes. This is a soft preference: "
            "exceed it only when continuation cannot preserve the intended result or the user explicitly asks."]


def _reference(ctx, ref):
    """A reference's line in the story request: its label, then its description."""
    text = ctx.descriptions.get(ref.name)
    line = f"{ref.label}: {text}" if text else ref.label
    clip = next((clip for clip in ctx.timeline.audio_clips if clip["slot"] == ref.name), None)
    if clip:
        if 'box_windows' in clip:
            windows = [w for w in rules.resolved_audio(ctx.timeline) if w['slot']==clip['slot']]
            ranges = '; '.join(f"Timeline {w['start']:.6f}–{w['start']+w['duration']:.6f} s, source {w['source_start']:.6f}–{w['source_start']+w['duration']:.6f} s" for w in windows)
            line += f" ({ranges or 'no assigned source audio'}; original speed; {clip.get('layer','music')} layer)"
        else:
            line += (f" (Timeline {clip['start']:.6f}–{clip['start'] + clip['duration']:.6f} s; "
                     f"source from {clip['source_start']:.6f} s, original speed; {clip.get('layer', 'music')} layer)")
    return line


def text_direction(ctx, index=None):
    if ctx.timeline.timed_text is None:
        return ""
    contract = (timed_text.snapshot(ctx.timeline.timed_text, ctx.timeline.audio_clips, rules.resolved_audio(ctx.timeline)) if index is None
                else rules.text_window(ctx.timeline, index, ctx.context_frames))
    return ("Timed visible text, inserted by code after reference binding. These exact strings are data, not dialogue, "
            "subject definitions or reference mentions. Do not copy them into writer prose. Stage the lettering "
            "treatment; preserve continuing/replay state and do not repeat entrances. Cue changes do not require cuts.\n"
            + json.dumps(contract, ensure_ascii=False))


def audio_direction(ctx, index):
    clips = rules.active_audio_clips(ctx.timeline, index, ctx.boxes[index].carried)
    if not clips:
        return ""
    layers = {"music": "non_diegetic_music", "soundscape": "overall_soundscape", "shot": "the matching shot's diegetic audio"}
    lines = ["Timeline audio is already trimmed to this generated clip, including replay. "
             "Reference its original tempo and timing; do not invent lyrics or claim to have heard it."]
    start = rules.box_start(ctx.timeline, index) - ctx.boxes[index].carried / FPS
    end = start + (ctx.boxes[index].frames + ctx.boxes[index].carried) / FPS
    windows = rules.resolved_audio(ctx.timeline)
    for clip in clips:
        for window in windows:
            if window['slot']!=clip['slot']: continue
            left, right = max(start, window['start']), min(end, window['start']+window['duration'])
            if right<=left: continue
            lines.append(f"Use @{clip['slot']} from {clock(left - start)} to {clock(right - start)} in "
                         f"{layers[clip.get('layer', 'music')]}: {ctx.descriptions.get(clip['slot']) or 'follow the supplied audio reference'}. "
                         "Include its reference role and cite it in that audio section.")
    return "\n".join(lines)


def timeline_audio_entries(ctx, index):
    """[(section, slot, line)] binding each active Timeline audio clip of box `index` to its sections, in the order
    with_timeline_audio adds them."""
    clips = rules.active_audio_clips(ctx.timeline, index, ctx.boxes[index].carried)
    if not clips:
        return []
    start = rules.box_start(ctx.timeline, index) - ctx.boxes[index].carried / FPS
    end = start + (ctx.boxes[index].frames + ctx.boxes[index].carried) / FPS
    found = []
    for clip in clips:
        name = clip["slot"]
        description = ctx.descriptions.get(name) or "the supplied audio's character, rhythm and texture"
        layer = {"music": "non_diegetic_music", "soundscape": "overall_soundscape", "shot": "detailed_description"}[clip.get("layer", "music")]
        found += [("subject_definitions", name, f"@{name} is an audio reference: {description}."),
                  ("retention_analysis", name, f"@{name}: reference - follow the supplied chunk's original timing and sound.")]
        for window in rules.resolved_audio(ctx.timeline):
            if window['slot']!=name: continue
            left,right=max(start,window['start']),min(end,window['start']+window['duration'])
            if right>left: found.append((layer,name,f"From {clock(left-start)} to {clock(right-start)}, follow @{name}: {description}."))
    return found


def add_timeline_audio(text, entries):
    """`text` with each entry's line added to its section unless that section already mentions its slot, and the
    summary naming the audio reference; `text` unchanged without entries."""
    if not entries:
        return text
    section_names = "subject_definitions|summary|retention_analysis|detailed_description|overall_soundscape|non_diegetic_music"
    for key, name, addition in entries:
        pattern = re.compile(rf"(?ms)^({key}:\s*\n?)(.*?)(?=^(?:{section_names}):|\Z)")
        match = pattern.search(text)
        if match and name in {ref for _, ref in rules.mentions(match.group(2))}:
            continue
        if match:
            body = match.group(2).strip()
            if body.casefold() in ("n/a", "none", ""): body = ""
            text = text[:match.start(2)] + "\n".join(filter(None, (body, addition))) + "\n\n" + text[match.end():]
        else:
            text += f"\n\n{key}:\n{addition}"
    text = re.sub(r"(?m)^(summary:\s*\n?\[)([^\]]+)\]",
                  lambda match: match.group(1) + match.group(2) +
                  ("" if "audio reference" in match.group(2) or "audio reuse" in match.group(2) else " + audio reference") + "]",
                  text, count=1)
    return text.strip()


def with_timeline_audio(text, ctx, index):
    """Keep user-placed audio bound to its section even if a writer omits its reference."""
    return add_timeline_audio(text, timeline_audio_entries(ctx, index))


def mentionable(ctx):
    """The slots a prompt may mention: the connected references, and the voice clips, which no model is offered."""
    return {ref.name for ref in ctx.references} | {clip["slot"] for clip in ctx.timeline.voice_clips}


def _shared(ctx):
    """The connected references and voice clips the shared direction mentions, which every box renders with."""
    connected = mentionable(ctx)
    return list(dict.fromkeys(name for _, name in rules.mentions(ctx.shared) if name in connected))


def _room(ctx):
    """How many images and audios a box can list besides those the shared direction mentions."""
    shared = _shared(ctx)
    return (max(0, rules.MAX_REF_IMAGES - sum(name.startswith("image") for name in shared)),
            max(0, rules.MAX_REF_AUDIOS - sum(name.startswith("audio") for name in shared)))


def _listable(ctx):
    """The connected references a box can list, and how many of them one box can take."""
    shared, own = _shared(ctx), own_pictures(ctx)
    names = [ref.name for ref in ctx.references if ref.name not in shared and ref.name not in own]
    images, audios = _room(ctx)
    extra = sum(min(max(0, 3 - sum(_reference_kind(name) == kind for name in shared)),
                    sum(_reference_kind(name) == kind for name in names)) for kind in ("video", "video_audio"))
    return names, (min(images, sum(name.startswith("image") for name in names)) +
                   min(audios, sum(name.startswith("audio") for name in names)) + extra)


def _reference_kind(name):
    return re.sub(r"\d+$", "", name)


def video_guidance(ctx):
    if not any(ref.name.startswith("video") for ref in ctx.references):
        return []
    return ["Video references use video1–3. Optional video_audio1–3 are the synchronized soundtracks of the "
            "same-numbered videos; standalone audio1–3 remain separate. Select a soundtrack only when needed; "
            "it also requires its paired video. Videos provide motion, camera, subjects or whole-video structure. "
            "Use the supplied descriptions; do not infer unseen motion or unheard dialogue from a thumbnail. "
            "Each box takes up to 3 videos and their 3 soundtracks in addition to its images and standalone audios."]


def idea_text(ctx):
    descriptions = [f"{ref.title}{(' · @' + ctx.idea_references[ref.name]) if ref.name in ctx.idea_references else ''}: "
                    f"{ctx.idea_descriptions[ref.name]['text']}" for ref in ctx.idea_images
                    if ref.name in ctx.idea_descriptions]
    if not descriptions:
        return ctx.idea
    role = "creative inspiration; labeled images are optional Ref2VA guidance" if ctx.idea_references else "creative inspiration, not render references"
    return (ctx.idea + f"\n\nIdea images ({role}):\n"
            + "\n".join(descriptions)
            + "\nPair these visual details with the user's idea. Explicit text and the creative Guide take priority. "
            + ("Use the labeled images only for the guidance their selected attributes provide; do not copy their source scene."
               if ctx.idea_references else "Describe relevant details in words; do not assign these images reference slots or picture tags."))


def story_messages(ctx, system=None):
    """The story request: the instructions, or `system` in their place, then the idea, the boxes or what to plan, and
    the references, with their pictures."""
    lines = ["Idea:", idea_text(ctx), ""]
    direction = text_direction(ctx)
    if direction:
        lines.append(direction)
    if ctx.shared.strip():
        lines += ["Shared creative direction for every box:", ctx.shared.strip(), ""]
    if ctx.guide.strip():
        lines += ["Creative guide:", ctx.guide.strip(), ""]
    if ctx.template is not None:
        lines += [story_templates.block(ctx.template), ""]
    if ctx.planning:
        lines += _plan_lines(ctx)
    else:
        lines += [f"A box that continues the one before it opens with the last {ctx.context_frames / FPS:g} s of "
                  "that box.", "", "Boxes:"]
    own = own_pictures(ctx)
    for box in ctx.boxes:
        if box.status == "write":
            lines.append(f"Box {box.number}: {_facts(ctx, box)}; to write.")
            lines += [f"Box {box.number}'s {which} frame {ctx.label(name)}: {ctx.descriptions[name]}"
                      for which, name in (("first", box.first), ("last", box.last))
                      if name in own and ctx.descriptions.get(name)]
        else:
            lines += [f"Box {box.number}: {_facts(ctx, box)}; {FIXED[box.status]}. Its prompt:",
                      box.prompt.strip() or "(none of its own)"]
    lines += video_guidance(ctx)
    lines += ["", "References:"] + ([_reference(ctx, ref) for ref in ctx.references if ref.name not in own]
                                    or ["none"])
    shared, (names, most) = _shared(ctx), _listable(ctx)
    if shared or len(names) > most:
        images, audios = _room(ctx)
        lines.append(f"A box lists at most {images} images and {audios} audios"
                     + (f"; the shared direction already puts {', '.join(shared)} in every box." if shared else "."))
    pictures = ([{"label": ref.label, "path": ref.path} for ref in ctx.references if ref.path and ref.name not in own]
                if ctx.pictures else [])
    if ctx.pictures:
        pictures += [{"label": ref.title, "path": ref.path} for ref in ctx.idea_images
                     if ref.path and ref.name not in ctx.idea_references]
    if system is None:
        instructions = PLAN_INSTRUCTIONS if ctx.planning else STORY_INSTRUCTIONS
        instructions = instructions.split("\nReply with one JSON object", 1)[0]
        instructions = instructions.replace('"seconds" is how long a box adds to the film.',
                                            '"duration_ms" is how many integer milliseconds a box adds to the film.')
        instructions += ("\nKeep this plan small. Each beat is a self-contained brief: its events and ALL assigned "
                         "dialogue verbatim with speakers; the box writer stages only its assigned beat. "
                         "No shot scripts or Guide rewrite. ends is the physical endpoint, not action history. "
                         "duration_ms is NEW time excluding replay (1000 ms = one second). "
                         "The original Guide reaches each writer and overrides conflicting beat details.")
        if ctx.template is not None:
            instructions += "\n" + story_templates.plan_rule(False)
        system = instructions + "\n\n" + TRANSITION_GUIDANCE
        if ctx.renderer != "image":
            system = system.replace("its events and ALL assigned dialogue verbatim with speakers",
                                    "its events; exact dialogue belongs only in stages")
            system += "\n\n" + story_stages.RULES
    if ctx.idea_references:
        from .story_idea_refs import PLANNING
        system += "\n\n" + PLANNING
    return [{"role": "system", "content": system},
            {"role": "user", "content": "\n".join(lines), "pictures": pictures}]


def story_format(ctx):
    """The response format of the story request: its JSON as a schema, for the Timeline's boxes or, when planning,
    for up to 100 boxes with their seconds and cuts."""
    count = lengths.MAX_PLANNED_BOXES if ctx.planning else len(ctx.boxes)
    number = {"type": "integer", "minimum": 1, "maximum": count}
    names, most = _listable(ctx)
    references = ({"type": "array", "items": {"type": "string", "enum": names}, "maxItems": most} if most
                  else {"type": "array", "items": TEXT, "maxItems": 0})
    cut = {"new_shot": {"type": "boolean"}, "new_scene": {"type": "boolean"}}
    planned = {"duration_ms": {"type": "integer", "minimum": 1, "maximum": 15000}, **cut} if ctx.planning else {}
    entry = _object({"box": number, **planned, "beat": TEXT, "on_screen": {"type": "array", "items": TEXT},
                     "references": references, "ends": TEXT,
                     **({"stages": story_stages.plan_schema()} if ctx.renderer != "image" else {})})
    boxes = {"type": "array", "minItems": 1 if ctx.planning else count, "maxItems": count, "items": entry}
    cast = {"type": "array", "items": _object({"name": TEXT, "references": references})}
    suggestion = _object({"what": TEXT, "why": TEXT, "boxes": {"type": "array", "items": number},
                          "description": TEXT})
    return _reply_format("h3_story", _object({"title": TEXT, "sheet": TEXT, "cast": cast, "boxes": boxes,
                                               "suggestions": {"type": "array", "items": suggestion}}))


def _text(data, key, where):
    value = data.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f'"{key}" of {where} must be text')
    return value


def _reference_name(item):
    """The reference `item` names, as image1 for "@Image1 (Shore)", else None."""
    match = NAME.fullmatch(item.strip()) if isinstance(item, str) else None
    return f"{match.group(1).lower()}{int(match.group(2))}" if match else None


def _names(value, ctx, number, notes=None):
    """The references box `number` lists, as connected names without repeats or those the shared direction
    mentions. Raises ValueError for a list H3 can't take, unless there's a `notes` list: then it leaves out what
    doesn't fit and says so there."""
    if not isinstance(value, list):
        if notes is None:
            raise ValueError(f'"references" of box {number} must be a list')
        value = []
    connected, shared = [ref.name for ref in ctx.references], _shared(ctx)
    names = []
    for item in value:
        name = _reference_name(item)
        if notes is None and not name:
            raise ValueError(f'"references" of box {number} has {item!r}, which is not a name like image1')
        if notes is None and name not in connected:
            raise ValueError(f"box {number} uses {name}, which is not connected; the connected references are "
                             f"{', '.join(connected) or 'none'}")
        if name in connected and name not in names and name not in shared:
            names.append(name)
    room = _room(ctx)
    images = [name for name in names if name.startswith("image")]
    audios = [name for name in names if name.startswith("audio")]
    extra = {kind: [name for name in names if _reference_kind(name) == kind] for kind in ("video", "video_audio")}
    extra_room = {kind: max(0, 3 - sum(_reference_kind(name) == kind for name in shared)) for kind in extra}
    if len(images) <= room[0] and len(audios) <= room[1] and all(len(extra[kind]) <= extra_room[kind] for kind in extra):
        return names
    if notes is None:
        besides = f" besides {', '.join(shared)} from the shared direction" if shared else ""
        raise ValueError(f"box {number} lists {len(images)} images and {len(audios)} audios{besides}; H3 takes at most "
                         f"{rules.MAX_REF_IMAGES} images and {rules.MAX_REF_AUDIOS} audios per box, so list only those "
                         f"box {number} shows or plays, the most important first")
    kept = images[:room[0]] + audios[:room[1]] + [name for kind in extra for name in extra[kind][:extra_room[kind]]]
    notes.append(f"Box {number} listed more references than H3 takes, so Write kept the first: {', '.join(kept)}.")
    return [name for name in names if name in kept]


def _beat(entry, number, ctx, notes=None):
    if not isinstance(entry, dict) or notes is None and str(entry.get("box")).strip() != str(number):
        raise ValueError(f'entry {number} of "boxes" must be an object with "box": {number}')
    where = f"box {number}"
    beat, ends = _text(entry, "beat", where).strip(), _text(entry, "ends", where).strip()
    write = ctx.planning or ctx.boxes[number - 1].status == "write"
    if write and not beat:
        raise ValueError(f'box {number} needs a "beat"')
    references = entry.get("references")
    shots = []
    for shot in entry.get("shots", []) if isinstance(entry.get("shots"), list) else []:
        if (isinstance(shot, dict) and isinstance(shot.get("action"), str)
                and isinstance(shot.get("on_screen"), list)
                and all(isinstance(name, str) for name in shot["on_screen"])):
            shots.append({key: value for key, value in shot.items()
                          if key in ("action", "dialogue", "guide_application", "start_seconds", "on_screen")})
    looks = entry.get("looks")
    definitions = entry.get("definitions")
    return Beat(number, beat, _names([] if references is None else references, ctx, number, notes) if write else [],
                ends, [name for name in entry.get("on_screen", []) if isinstance(name, str)]
                if isinstance(entry.get("on_screen"), list) else [], shots,
                entry.get("terminal_state", "") if isinstance(entry.get("terminal_state", ""), str) else "",
                {name: text for name, text in looks.items() if isinstance(text, str)} if isinstance(looks, dict) else {},
                {name: {"label": item["label"], "line": item["line"], "edited": item.get("edited") is True}
                 for name, item in definitions.items() if isinstance(item, dict)
                 and isinstance(item.get("label"), str) and isinstance(item.get("line"), str)}
                if isinstance(definitions, dict) else {},
                story_stages.read(entry["stages"]) if "stages" in entry else [])


def _called(name):
    """A cast member's name as a box's "on_screen" matches it: without a leading article, in lowercase."""
    return re.sub(r"^(?:the|a|an)\s+", "", name.strip(), flags=re.IGNORECASE).lower()


def _member(cast, called):
    """The key of the member of `cast` whom `called` names, by the whole name or by a first name no other member
    shares, else None."""
    first = called.split(" ", 1)[0]
    found = [key for key in cast if key == called] or [key for key in cast if key.split(" ", 1)[0] == first]
    return found[0] if len(found) == 1 else None


def _cast(value, ctx, beats, entries):
    """Adds to each of the `beats` to write the references of the cast members in `value` that its entry of
    `entries` has on screen, by `_member`, or that its ending, the last moment on screen, names in full, as far as
    H3 takes them. Returns the cast, as `StoryPlan.cast`, and a note for each reference that didn't fit."""
    connected, shared = {ref.name for ref in ctx.references}, _shared(ctx)
    cast = {}
    for item in value if isinstance(value, list) else []:
        if isinstance(item, dict) and isinstance(item.get("name"), str) and isinstance(item.get("references"), list):
            shown = [_reference_name(ref) for ref in item["references"]]
            shown = [ref for ref in dict.fromkeys(shown) if ref in connected and ref not in shared
                     and ref not in ctx.idea_references.values()]
            if _called(item["name"]) and shown:
                cast[_called(item["name"])] = (item["name"].strip(), shown)
    room, notes = dict(zip(("image", "audio"), _room(ctx))), []
    room.update({kind: max(0, 3 - sum(_reference_kind(name) == kind for name in shared)) for kind in ("video", "video_audio")})
    for beat, entry in zip(beats, entries):
        seen = ([name for shot in beat.shots for name in shot["on_screen"]]
                if beat.shots else entry.get("on_screen"))
        if beat.shots:
            beat.on_screen = list(dict.fromkeys(seen))
        if not ctx.planning and ctx.boxes[beat.box - 1].status != "write" or not isinstance(seen, list):
            continue
        ending = [key for key in cast if re.search(rf"\b{re.escape(key)}\b", beat.ends, re.IGNORECASE)]
        for called in [*(_called(name) for name in seen if isinstance(name, str)), *ending]:
            key = _member(cast, called)
            if key is None:
                continue
            name, shown = cast[key]
            for ref in shown:
                kind = _reference_kind(ref)
                if ref in beat.references:
                    continue
                if sum(_reference_kind(item) == kind for item in beat.references) < room[kind]:
                    beat.references.append(ref)
                else:
                    notes.append(f"Box {beat.box} shows {name}, but H3 takes no more {kind}s there, so Write left out "
                                 f"{ref}.")
    return cast, notes


def _suggestions(value, count):
    """The suggestions in `value` that say what to add, each with the box numbers from 1 to `count` it names."""
    found = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        boxes = item["boxes"] if isinstance(item.get("boxes"), list) else []
        suggestion = {key: item[key].strip() if isinstance(item.get(key), str) else ""
                      for key in ("what", "why", "description")}
        if suggestion["what"]:
            found.append(dict(suggestion, boxes=[n for n in boxes if type(n) is int and 1 <= n <= count]))
    return found


def _lengths(entries, ctx):
    """The fitted frames, the cuts and the new scenes of the boxes a plan lists; a cut is a new scene unless its
    "new_scene" is false."""
    seconds, cuts, scenes = [], [], []
    for number, entry in enumerate(entries, 1):
        value = entry["duration_ms"] / 1000 if type(entry.get("duration_ms")) is int else entry.get("seconds")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'box {number} needs "seconds", a number of seconds above 0')
        for key in ("new_shot", "new_scene"):
            if entry.get(key) is not None and not isinstance(entry[key], bool):
                raise ValueError(f'"{key}" of box {number} must be true or false')
        seconds.append(value)
        cuts.append(number > 1 and entry.get("new_shot") is True)
        scenes.append(cuts[-1] and entry.get("new_scene") is not False)
    fresh = [number == 1 or cut for number, cut in enumerate(cuts, 1)]
    return lengths.fit(seconds, fresh, ctx.context_frames, ctx.total_seconds), cuts, scenes


def reply_data(reply):
    """The JSON object in a story reply; raises ValueError when there is none."""
    text = strip_reasoning(reply)
    start = text.find("{")
    if start < 0:
        raise ValueError("the reply has no JSON object")
    try:
        data, _ = json.JSONDecoder().raw_decode(text, start)
    except json.JSONDecodeError as error:
        raise ValueError(f"the JSON object is not valid ({error.msg})") from None
    return data


def parse_story(reply, ctx, lenient=False):
    """The StoryPlan in a story reply; raises ValueError saying what is wrong. A plan for an empty Timeline also
    has the fitted frames and the cuts of its boxes. `lenient` takes box numbers as they come
    and leaves out the references a box can't list, with notes."""
    data = reply_data(reply)
    entries = data.get("boxes")
    if ctx.planning:
        if not isinstance(entries, list) or not 1 <= len(entries) <= lengths.MAX_PLANNED_BOXES:
            raise ValueError(f'"boxes" must have from 1 to {lengths.MAX_PLANNED_BOXES} entries')
    elif not isinstance(entries, list) or len(entries) != len(ctx.boxes):
        raise ValueError(f'"boxes" must have one entry for each of the {len(ctx.boxes)} boxes')
    count, notes = len(entries), [] if lenient else None
    beats = [_beat(entry, number, ctx, notes) for number, entry in enumerate(entries, 1)]
    cast, unfit = _cast(data.get("cast"), ctx, beats, entries)
    frames, cuts, scenes = _lengths(entries, ctx) if ctx.planning else ([], [], [])
    sheet = data.get("sheet")
    if isinstance(sheet, (dict, list)):
        sheet = json.dumps(sheet, ensure_ascii=False, indent=1)
    if sheet is not None and not isinstance(sheet, str):
        raise ValueError('"sheet" of the story must be text')
    suggestions = data.get("suggestions")
    return StoryPlan(_text(data, "title", "the story").strip(), (sheet or "").strip(), beats,
                     _suggestions(suggestions, count), frames, cuts, (notes or []) + unfit, cast, scenes)


def saved_plan(ctx, saved, required=False):
    """Reuse the saved plan by box ID. Older workflows use their outline and existing prompts as the contract."""
    if ctx.planning or str(saved.get("timeline", ctx.timeline_id)) != str(ctx.timeline_id):
        saved = {}
    plan = saved.get("plan")
    if isinstance(plan, dict) and isinstance(plan.get("boxes"), list):
        if [item.get("id") for item in plan["boxes"] if isinstance(item, dict)] == [box.id for box in ctx.boxes]:
            return plan
    if not required:
        return None
    outline = {item.get("box"): item for item in saved.get("outline", []) if isinstance(item, dict)}
    return {"title": saved.get("title", ""), "sheet": saved.get("sheet", ""), "suggestions": [],
            "boxes": [{"box": box.number, "id": box.id,
                       "beat": outline.get(box.id, {}).get("beat") or box.prompt or ctx.idea,
                       "ends": outline.get(box.id, {}).get("ends", ""),
                       "references": [name for _, name in rules.mentions(box.prompt)]} for box in ctx.boxes]}


def slots_for(ctx, index, text):
    """The Timeline's slots for box `index` if its prompt were `text`."""
    boxes = list(ctx.timeline.boxes)
    boxes[index] = dataclasses.replace(boxes[index], prompt=text)
    return rules.box_slots(dataclasses.replace(ctx.timeline, boxes=boxes), index)


def plan_slots(ctx, index, references):
    """The mode and tags box `index` renders with when its prompt mentions exactly `references`."""
    return slots_for(ctx, index, " ".join(f"@{name}" for name in references))


def clock_line(box):
    end = clock((box.frames + box.carried) / FPS)
    if box.number == 1:
        return f"The clip runs from 00:00.000 to {end} and is a new shot."
    if box.new_scene:
        return (f"The clip runs from 00:00.000 to {end} and is a new scene after a cut: it doesn't replay box "
                f"{box.number - 1} and can start in another place or time.")
    if box.fresh:
        return (f"The clip runs from 00:00.000 to {end} and is a new shot of the same scene after a cut: it doesn't "
                f"replay box {box.number - 1}, but keeps its people, clothing, place, light, style and ambient sound "
                "from a new camera angle.")
    start = clock(box.carried / FPS)
    return (f"The clip runs from 00:00.000 to {end}. Until {start} it replays the end of box {box.number - 1}; new "
            f"action starts at {start}.")


def _shown(slots):
    """The names a box shows: its references, then its first and last frames."""
    return [name for name in dict.fromkeys([*slots.references, *slots.audios, slots.first, slots.last]) if name]


def _box_pictures(ctx, index, slots):
    """The pictures of box `index`: its references, its first and last frames, then the rendered last frame of the
    box before it."""
    paths = {ref.name: ref.path for ref in ctx.references if ref.path}
    pictures = [{"label": ctx.label(name), "path": paths[name]} for name in _shown(slots) if name in paths]
    before = ctx.boxes[index - 1] if index > 0 else None
    if before is not None and before.last_frame:
        pictures.append({"label": f"The last frame of box {before.number}", "path": before.last_frame})
    return pictures
