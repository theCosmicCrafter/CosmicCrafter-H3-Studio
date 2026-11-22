"""H3 Timeline rules: the timeline JSON, box lengths, reference mentions, H3 modes and slots, and
matching boxes with saved segments. Pure Python, no torch."""

import hashlib
import json
import math
import re
import zlib
from copy import deepcopy
from dataclasses import dataclass, field

from .timing import FPS, seconds, effective_audio_context
from . import tracks
from . import timed_text
from . import audio_windows
from . import layers

MAX_FRAMES = 362
# A Timeline may raise its box limit to this with "max_frames"; boxes past MAX_FRAMES are sampled in context windows.
LONG_MAX_FRAMES = 991
GRID = 17
MIN_FRESH_FRAMES = 22
MIN_CONTINUING_FRAMES = 17
MAX_REF_IMAGES = 9
MAX_REF_AUDIOS = 3
MAX_REF_VIDEOS = 3
VIDEO_SLOTS = [f"video{i}" for i in range(1, MAX_REF_VIDEOS + 1)]
VIDEO_AUDIO_SLOTS = [f"video_audio{i}" for i in range(1, MAX_REF_VIDEOS + 1)]
IMAGE_SLOTS = [f"image{i}" for i in range(1, 17)]
AUDIO_SLOTS = [f"audio{i}" for i in range(1, MAX_REF_AUDIOS + 1)]
MAX_SEED = 2**64 - 1
# A bridge's new frames: 17j - 5, so carried and frozen ends of 17k + 5 frames keep the run on H3's latent grid.
BRIDGE_FRAMES = (12, 29, 46)
MENTION = re.compile(r"(?<![\w@])@(image|audio|video_audio|video)(\d+)(?!\w)", re.IGNORECASE)
RAW_TAG = re.compile(r"<(?:Picture|Audio|Video) \d+>")
IMAGE_SLOT = re.compile(r"@?image(\d+)", re.IGNORECASE)
MEMORY_MODES = ("off", "scene", "selected", "cast")
# Reader features a Timeline can name in "requires"; an editor writes them when the file depends on them.
REQUIRES = ("dialogue-cues-1", "replacement-bridges-1", audio_windows.FEATURE, layers.FEATURE, tracks.FEATURE)


@dataclass
class Box:
    id: str
    frames: int
    prompt: str
    seed: int
    cut: bool
    first: str
    last: str
    previews: list = field(default_factory=list)
    plate_changes: list = field(default_factory=list)
    memory: str = "off"
    memories: list = field(default_factory=list)
    new_scene: bool = False
    flf_refmods: bool = False


@dataclass
class Timeline:
    prompt: str
    boxes: list
    render_box: int | None = None
    plates: list = field(default_factory=list)
    refmods: list = field(default_factory=list)
    disabled_refs: list = field(default_factory=list)
    audio_clips: list = field(default_factory=list)
    pictures: list = field(default_factory=list)
    voice_clips: list = field(default_factory=list)
    reference_descriptions: dict = field(default_factory=dict)
    reference_replacements: dict = field(default_factory=dict)
    timed_text: dict | None = None
    bible: dict | None = None
    # Each box's Story fields as saved: {"schedule", "source", "cast"}. Not on Box, whose every field a box plan records.
    story: list = field(default_factory=list)
    # Whether each box plays exactly its frames; empty without `parse`. Not on Box either.
    exact: list = field(default_factory=list)
    # The bridges on cuts that insert time, each {"before", "frames", "seed", "prompt"}; outside the boxes, which never
    # see them.
    bridges: list = field(default_factory=list)
    # The bridges that replace a reviewed region instead, each {"before", "mode": "replace", "left", "right", "seed",
    # "prompt"} with optional "review" and "selected"; see replacement.py.
    replacements: list = field(default_factory=list)
    # Both kinds in the Timeline's order, as the JSON keeps them.
    all_bridges: list = field(default_factory=list)
    render_bridge: str | None = None
    still_requests: list = field(default_factory=list)
    continuity: dict | None = None
    reference_preparation: dict | None = None
    still_prompt_preparation: dict | None = None
    # Most frames a box can generate: 362 unless the JSON asks for more (windowed sampling).
    max_frames: int = MAX_FRAMES
    # Cues bound to recordings and observed protections: {"version", "cues", "observed"}; see dialogue.py.
    dialogue: dict | None = None
    # Whether each box keeps its own typed dialogue instead of the cues; empty without `parse`. Not on Box either.
    manual_dialogue: list = field(default_factory=list)
    # Continuing boxes only: the guide at the first new frame and paired context noise.
    continuation_guide: bool = True
    context_noise: bool = False
    audio_feather: int = 0
    # Reference video slots each box receives only its own time of, as audio clips are cut by Timeline time.
    video_slices: list = field(default_factory=list)
    # The other videos of the clips that hold several, and their switch plans, by clip id; see layers.py.
    layers: dict = field(default_factory=dict)
    switches: dict = field(default_factory=dict)
    render_layer: str | None = None
    tracks: list | None = None
    placements: dict = field(default_factory=dict)
    text_lanes: list = field(default_factory=list)
    overlap_switches: list = field(default_factory=list)


@dataclass
class Slots:
    mode: str
    references: list
    audios: list
    first: str
    last: str
    tags: dict
    refmods: list = field(default_factory=list)

    @property
    def image_inputs(self):
        return [name for name in self.references if name.startswith("image")
                and name not in {ref["slot"] for ref in self.refmods}]

    @property
    def audio_inputs(self):
        return [name for name in self.audios if name.startswith("audio")
                and name not in {ref["slot"] for ref in self.refmods}]

    @property
    def video_inputs(self):
        return [name for name in self.references if name.startswith('video')]

    @property
    def video_audio_inputs(self):
        return [name for name in self.audios if name.startswith('video_audio')]


def reference_disabled(name, disabled):
    return name in disabled or (name.startswith("video_audio") and name.replace("video_audio", "video") in disabled)


def _error(message):
    return ValueError(f"H3 Timeline: {message}")


class BridgeError(ValueError):
    """A bad entry in the Timeline's bridges; `index` counts from 0, so Prepare can name it."""

    def __init__(self, index, message):
        super().__init__(f"H3 Timeline: {message}")
        self.index = index


def slot_number(name):
    return int(re.sub(r"\D", "", name))


def is_picture_slot(name):
    return isinstance(name, str) and re.fullmatch(r"image[1-9]\d*", name) is not None


def is_studio_slot(name):
    """Pictures saved in the Timeline itself are numbered after the node's 16 wired inputs, with no last slot."""
    return is_picture_slot(name) and slot_number(name) > len(IMAGE_SLOTS)


def is_voice_slot(name):
    """Voice clips saved in the Timeline are numbered after the node's 3 wired audio inputs."""
    return isinstance(name, str) and re.fullmatch(r"audio[1-9]\d*", name) is not None and slot_number(name) > MAX_REF_AUDIOS


def parse(text):
    """Timeline from the node's JSON; raises ValueError naming the problem."""
    try:
        data = json.loads(text or "{}")
    except json.JSONDecodeError as error:
        raise _error(f"the timeline is not valid JSON ({error.msg} at character {error.pos})") from None
    if not isinstance(data, dict):
        raise _error("the timeline must be a JSON object")
    if data.get("version", 1) != 1:
        raise _error(f"timeline version {data['version']!r} is not supported; this node reads version 1")
    requires = data.get("requires", [])
    if not isinstance(requires, list) or any(not isinstance(item, str) for item in requires):
        raise _error("requires must be a list of feature names")
    unknown = [item for item in requires if item not in REQUIRES]
    if unknown:
        raise _error(f"this Timeline needs a newer H3 Continuity ({', '.join(unknown)}); update the node pack")
    boxes = data.get("boxes") or []
    if not isinstance(boxes, list):
        raise _error("'boxes' must be a list")
    target = data.get("render_box")
    if target is not None and (type(target) is not int or not 1 <= target <= len(boxes)):
        raise _error("render_box must be the number of a box in this timeline")
    parsed = Timeline(_text(data.get("prompt"), "the shared prompt"), [_box(raw, n) for n, raw in enumerate(boxes, 1)], target)
    parsed.exact = [_exact(raw, n, box) for n, (raw, box) in enumerate(zip(boxes, parsed.boxes), 1)]
    for n, raw in enumerate(boxes, 1):
        if raw.get("dialogue", "cues") not in ("cues", "manual"):
            raise _error(f"box {n} dialogue must be cues or manual")
    parsed.manual_dialogue = [raw.get("dialogue") == "manual" for raw in boxes]
    tracks.validate(parsed, data, lambda box,index: played_frames(parsed,index))
    layers.validate(parsed, boxes, requires)
    from . import still_scene, reference_assets
    parsed.reference_preparation = reference_assets.validate(data["reference_preparation"]) if "reference_preparation" in data else None
    if "still_prompt_preparation" in data:
        from . import still_prompt_preparation
        parsed.still_prompt_preparation = still_prompt_preparation.validate(data["still_prompt_preparation"])
    parsed.continuity = still_scene.validate(data["continuity"]) if "continuity" in data else None
    parsed.still_requests = data.get("still_requests", [])
    if not isinstance(parsed.still_requests, list) or any(not isinstance(item, dict) for item in parsed.still_requests):
        raise _error("still_requests must be a list of request receipts")
    parsed.timed_text = timed_text.validate(data.get("timed_text"))
    for attachment in parsed.text_lanes:
        attachment["attachment"] = timed_text.validate(attachment.get("attachment"))
    from . import dialogue
    parsed.dialogue = dialogue.validate(data.get("dialogue"))
    parsed.bible = data.get("bible")
    parsed.story = [{"schedule": raw.get("schedule"), "source": raw.get("source"),
                     "cast": raw["cast"] if isinstance(raw.get("cast"), dict) else {}} for raw in boxes]
    for index, box in enumerate(parsed.boxes):
        if box.memory not in MEMORY_MODES:
            raise _error(f"box {index + 1} memory must be off, scene, selected or cast")
        if not isinstance(box.memories, list) or len(box.memories) > 3:
            raise _error(f"box {index + 1} can remember at most 3 earlier moments")
        for item in box.memories:
            if not isinstance(item, dict) or type(item.get("frame")) is not int or item["frame"] < 0:
                raise _error(f"box {index + 1} memories need a source box and a nonnegative frame")
            _text(item.get("label"), "memory description")
    parsed.audio_clips = data.get("audio_clips", [])
    if not isinstance(parsed.audio_clips, list):
        raise _error("audio_clips must be a list")
    audio_slots = set()
    for clip in parsed.audio_clips:
        if not isinstance(clip, dict) or clip.get("slot") not in AUDIO_SLOTS or clip["slot"] in audio_slots:
            raise _error("audio clips need unique audio1, audio2 or audio3 slots")
        audio_slots.add(clip["slot"])
        if "file" in clip:
            audio_file(clip["file"])
        for key in ("start", "source_start", "duration"):
            value = _number(clip.get(key), f"audio clip {key}")
            if value < 0 or (key == "duration" and value == 0):
                raise _error(f"audio clip {key} must be {'positive' if key == 'duration' else 'nonnegative'}")
        if "source_duration" in clip:
            value = _number(clip["source_duration"], "audio clip source_duration")
            if value <= 0:
                raise _error("audio clip source_duration must be positive")
        _text(clip.get("description"), "audio clip description")
        if clip.get("layer", "music") not in ("music", "soundscape", "shot"):
            raise _error("audio clip layer must be music, soundscape or shot")
        if "in_full_video" in clip:
            if type(clip["in_full_video"]) is not bool:
                raise _error("audio clip in_full_video must be true or false")
            if clip["in_full_video"] and "file" not in clip:
                raise _error("only an uploaded audio clip can play in the full video")
        if "locked" in clip:
            if type(clip["locked"]) is not bool:
                raise _error("audio clip locked must be true or false")
            if clip["locked"] and "file" not in clip:
                raise _error("only an uploaded audio clip can be locked to the sequence clock")
    parsed.pictures = data.get("pictures", [])
    if not isinstance(parsed.pictures, list):
        raise _error("pictures must be a list")
    held = set()
    for picture in parsed.pictures:
        if not isinstance(picture, dict) or not is_studio_slot(picture.get("slot")) or picture["slot"] in held:
            raise _error("Studio pictures need unique slots from image17 up")
        held.add(picture["slot"])
        picture_file(picture.get("file"))
        _text(picture.get("title"), "Studio picture title")
    parsed.voice_clips = data.get("voice_clips", [])
    if not isinstance(parsed.voice_clips, list):
        raise _error("voice_clips must be a list")
    voiced = set()
    for clip in parsed.voice_clips:
        if not isinstance(clip, dict) or not is_voice_slot(clip.get("slot")) or clip["slot"] in voiced:
            raise _error("voice clips need unique slots from audio4 up")
        voiced.add(clip["slot"])
        audio_file(clip.get("file"))
    from . import reference_replacements
    parsed.reference_replacements = reference_replacements.validate(data.get('reference_replacements', {}))
    reference_replacements.pairing(parsed)
    for clip in parsed.audio_clips:
        if 'box_windows' in clip:
            if audio_windows.FEATURE not in requires:
                raise _error('box-bound audio requires ' + audio_windows.FEATURE)
            origin = ({'file': reference_replacements.file_for(parsed, clip['slot'])}
                      if reference_replacements.file_for(parsed, clip['slot']) else
                      reference_replacements.origin(clip['slot'], reference_replacements.effective(parsed)))
            audio_windows.validate(clip, audio_box_spans(parsed), origin)
    parsed.reference_descriptions = data.get("reference_descriptions", {})
    if not isinstance(parsed.reference_descriptions, dict) or any(
            not is_picture_slot(key) or not isinstance(value, dict)
            or not isinstance(value.get("text"), str) or not isinstance(value.get("source"), str)
            for key, value in parsed.reference_descriptions.items()):
        raise _error("reference_descriptions must map image slots to text and source")
    parsed.disabled_refs = data.get("disabled_refs", [])
    if not isinstance(parsed.disabled_refs, list) or any(
            not is_picture_slot(name) and name not in AUDIO_SLOTS and not is_voice_slot(name)
            and name not in VIDEO_SLOTS and name not in VIDEO_AUDIO_SLOTS and not reference_replacements.kind(name)
            for name in parsed.disabled_refs):
        raise _error("disabled_refs must be a list of image, video, video_audio or audio slots")
    parsed.refmods = data.get("refmods", [])
    if not isinstance(parsed.refmods, list):
        raise _error("refmods must be a list")
    assigned = set()
    for ref in parsed.refmods:
        if not isinstance(ref, dict) or (not is_picture_slot(ref.get("slot")) and ref.get("slot") not in AUDIO_SLOTS):
            raise _error("a RefMod needs an image or audio slot")
        if ref["slot"] in assigned:
            raise _error(f"multiple RefMods use {ref['slot']}")
        assigned.add(ref["slot"])
        if ref["slot"] in audio_slots:
            raise _error(f"{ref['slot']} has both a Timeline audio clip and a RefMod")
        if ref["slot"] in held:
            raise _error(f"{ref['slot']} has both a Studio picture and a RefMod")
        if not isinstance(ref.get("name"), str) or not ref["name"]:
            raise _error("a RefMod needs a saved name")
        strength = _number(ref.get("strength", 1), "RefMod strength")
        if not 0 <= strength <= 1:
            raise _error("RefMod strength must be between 0 and 1")
        if type(ref.get("member", -1)) is not int or ref.get("member", -1) < -1:
            raise _error("a RefMod member must be a valid index")
        _text(ref.get("description"), "RefMod description")
        if ref.get("kind") not in ("image", "video", "audio"):
            raise _error("a RefMod needs its stored reference type; select it again")
        if (ref["kind"] == "audio") != ref["slot"].startswith("audio"):
            raise _error("audio RefMods need an audio slot; visual RefMods need an image slot")
    limit = data.get("max_frames", MAX_FRAMES)
    if type(limit) is not int or not MAX_FRAMES <= limit <= LONG_MAX_FRAMES or limit % GRID != 5:
        raise _error(f"max_frames must be a length on the 17k+5 grid from {MAX_FRAMES} to {LONG_MAX_FRAMES} frames")
    parsed.max_frames = limit
    parsed.continuation_guide = data.get("continuation_guide", True)
    if not isinstance(parsed.continuation_guide, bool):
        raise _error("continuation_guide must be true or false")
    parsed.context_noise = data.get("context_noise", False)
    if not isinstance(parsed.context_noise, bool):
        raise _error("context_noise must be true or false")
    parsed.audio_feather = data.get("audio_feather", 0)
    if type(parsed.audio_feather) is not int or not 0 <= parsed.audio_feather <= 16:
        raise _error("audio_feather must be a whole number of audio ticks from 0 to 16")
    parsed.video_slices = data.get("video_slices", [])
    if (not isinstance(parsed.video_slices, list) or len(set(map(str, parsed.video_slices))) != len(parsed.video_slices)
            or any(slot not in VIDEO_SLOTS for slot in parsed.video_slices)):
        raise _error(f"video_slices must list distinct reference video slots ({VIDEO_SLOTS[0]} to {VIDEO_SLOTS[-1]})")
    parsed.plates = data.get("plates", [])
    if not isinstance(parsed.plates, list):
        raise _error("plates must be a list")
    reference_replacements.validate_box_audio(parsed)
    revisions = {}
    for plate in parsed.plates:
        if not isinstance(plate, dict) or not isinstance(plate.get("id"), str) or not plate["id"] or plate["id"] in revisions:
            raise _error("plates need unique nonempty revision IDs")
        plate["slot"] = _image_slot(plate.get("slot"), "the plate slot")
        if not plate.get("slot"):
            raise _error("a plate needs its original image slot")
        if plate.get("image"):
            preview_file(plate["image"])
        revisions[plate["id"]] = plate
    for n, box in enumerate(parsed.boxes, 1):
        seen = set()
        for change in box.plate_changes:
            if (not isinstance(change, dict) or type(change.get("frame")) is not int
                    or not 0 <= change["frame"] < LONG_MAX_FRAMES):
                raise _error(f"box {n} plate changes need a valid local frame")
            slot = _image_slot(change.get("slot"), f"box {n} plate slot")
            change["slot"] = slot
            fresh = is_fresh(parsed, n - 1)
            if change["frame"] > played_frames(parsed, n - 1) - (1 if fresh else 0):
                raise _error(f"box {n} has a plate change at frame {change['frame']}, past its end at "
                             f"{played_frames(parsed, n - 1)} frames: move the change earlier or remove it")
            if not slot or (slot, change["frame"]) in seen:
                raise _error(f"box {n} has duplicate or empty plate changes")
            seen.add((slot, change["frame"]))
            revision = change.get("revision")
            if not isinstance(revision, str):
                raise _error(f"box {n} needs a plate revision or an empty string for the original")
            if revision and (revision not in revisions or revisions[revision]["slot"] != slot or not revisions[revision].get("image")):
                raise _error(f"box {n} has a missing accepted plate for {slot}")
    # After the audio lanes, disabled references and dialogue are parsed: whether a box speaks decides what it remembers.
    for index, box in enumerate(parsed.boxes):
        if box.memory != "cast":
            memory_sources(parsed, index)
    layers.check_memory(parsed)
    parsed.all_bridges = _bridges(data.get("bridges", []), parsed)
    parsed.bridges = [bridge for bridge in parsed.all_bridges if bridge.get("mode") != "replace"]
    parsed.replacements = [bridge for bridge in parsed.all_bridges if bridge.get("mode") == "replace"]
    target = data.get("render_bridge")
    if target is not None:
        if not isinstance(target, str) or target not in {bridge["before"] for bridge in parsed.all_bridges}:
            raise _error("render_bridge must be the box id of one of this Timeline's bridges")
        if parsed.render_box is not None:
            raise _error("a run renders one box or one bridge: drop render_box or render_bridge")
        parsed.render_bridge = target
    target = data.get("render_layer")
    if target is not None:
        if not isinstance(target, str) or layers.layer_of(parsed, target) is None:
            raise _error("render_layer must be the id of one of this Timeline's videos")
        if parsed.render_box is not None or parsed.render_bridge is not None:
            raise _error("a run renders one box, one bridge or one video")
        parsed.render_layer = target
    if any(box.memory == "cast" for box in parsed.boxes):
        from . import cast_memory
        cast_memory.check(parsed)
    return parsed


def _text(value, what):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise _error(f"{what} must be text")
    return value


def _local_file(value):
    return (isinstance(value, dict) and value.get("type") in ("input", "output", "temp")
            and isinstance(value.get("filename"), str) and value["filename"] not in ("", ".", "..")
            and not re.search(r"[\\/:\x00]", value["filename"])
            and isinstance(value.get("subfolder", ""), str))


def audio_file(value):
    if not _local_file(value):
        raise _error("audio needs a local ComfyUI file")
    return value


def picture_file(value):
    if not _local_file(value):
        raise _error("a Studio picture needs a file in ComfyUI's input, output or temp folder")
    return value


def box_start(timeline, index):
    if timeline.tracks is not None:
        return timeline.placements[timeline.boxes[index].id]["start"] / FPS
    return sum(played_frames(timeline, i) for i in range(index)) / FPS


def audio_box_spans(timeline):
    if timeline.tracks is not None:
        return [dict(id=box.id, start=box_start(timeline,index), duration=played_frames(timeline,index)/FPS)
                for index,box in enumerate(timeline.boxes)]
    start, spans = 0, []
    for index, box in enumerate(timeline.boxes):
        duration = played_frames(timeline, index) / FPS
        spans.append(dict(id=box.id, start=start, duration=duration))
        start += duration
    return spans


def video_window(timeline, index, context):
    """(first frame, frames) of the Timeline's time box `index` generates: it starts the frames it carries before the
    box's own start, as timed audio clips do, and covers every frame H3 generates for it."""
    frames, carried = box_length(timeline, index, context)
    return round(box_start(timeline, index) * FPS) - carried, frames + carried + dropped_frames(timeline, index)


def resolved_audio(timeline):
    boxes = audio_box_spans(timeline)
    return [dict(window, slot=clip['slot']) for clip in timeline.audio_clips
            if clip['slot'] not in timeline.disabled_refs for window in audio_windows.resolve(clip, boxes)]


def active_audio_clips(timeline, index, context=0):
    start = box_start(timeline, index)
    end = start + played_frames(timeline, index) / FPS
    replay = box_length(timeline, index, context)[1] / FPS if context else 0
    windows = resolved_audio(timeline)
    return [clip for clip in timeline.audio_clips if clip['slot'] not in timeline.disabled_refs
            and any(window['slot'] == clip['slot'] and window['start'] < end
                    and window['start'] + window['duration'] > start - (replay if 'box_windows' in clip else 0)
                    for window in windows)]


def _number(value, what):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise _error(f"{what} must be a number")
    return value


def _image_slot(value, what):
    value = _text(value, what).strip()
    if not value:
        return ""
    match = IMAGE_SLOT.fullmatch(value)
    if not match:
        raise _error(f"{what} is {value!r}; use an image slot such as image1")
    return f"image{int(match.group(1))}"


def _box(raw, n):
    if not isinstance(raw, dict):
        raise _error(f"box {n} must be a JSON object")
    box_id = str(raw.get("id") or f"box{n}")
    if raw.get("frames") is not None:
        frames = round(_number(raw["frames"], f"box {n} frames"))
    elif raw.get("seconds") is not None:
        frames = round(_number(raw["seconds"], f"box {n} seconds") * FPS)
    else:
        raise _error(f"box {n} needs frames or seconds")
    seed = raw.get("seed")
    if seed is None:
        seed = zlib.crc32(box_id.encode("utf-8"))
    elif isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= MAX_SEED:
        raise _error(f"box {n} seed must be a whole number from 0 to {MAX_SEED}")
    return Box(box_id, frames, _text(raw.get("prompt"), f"box {n} prompt"), seed, bool(raw.get("cut")),
               _image_slot(raw.get("first"), f"box {n} first frame"),
               _image_slot(raw.get("last"), f"box {n} last frame"), _previews(raw.get("previews", []), n),
               _changes(raw.get("plate_changes", []), n), raw.get("memory", "off"), raw.get("memories", []),
               bool(raw.get("new_scene")), raw.get("flf_refmods") is True)


def _bridges(raw, parsed):
    if not isinstance(raw, list):
        raise BridgeError(0, "bridges must be a list")
    positions = {box.id: index for index, box in enumerate(parsed.boxes)}
    bridges, taken = [], {}
    for index, item in enumerate(raw):
        n = index + 1
        before = item.get("before") if isinstance(item, dict) else None
        if not isinstance(before, str) or not before:
            raise BridgeError(index, f"bridge {n} needs the id of the box it leads into, as before")
        if before not in positions:
            raise BridgeError(index, f"bridge {n} leads into box {before!r}, which this Timeline doesn't have")
        position = positions[before]
        previous=previous_index(parsed,position)
        if previous is None:
            raise BridgeError(index, f"bridge {n} leads into box 1, which has no box before it")
        if layers.stacked(parsed, position):
            raise BridgeError(index, f"bridge {n} leads into box {position + 1}, which has several videos")
        if layers.stacked(parsed, previous):
            raise BridgeError(index, f"bridge {n} leads out of box {position}, which has several videos")
        if not is_fresh(parsed, position):
            raise BridgeError(index, f"bridge {n} leads into box {position + 1}, which continues box {position}: "
                                     "a bridge needs a box that starts with Cut or New scene")
        if before in taken:
            raise BridgeError(index, f"bridges {taken[before] + 1} and {n} both lead into box {position + 1}")
        mode = item.get("mode", "insert")
        if mode not in ("insert", "replace"):
            raise BridgeError(index, f"bridge {n} mode must be insert or replace")
        if mode == "replace":
            if "frames" in item:
                raise BridgeError(index, f"bridge {n} replaces footage, so it has left and right coverage, not frames")
            left, right = item.get("left"), item.get("right")
            if type(left) is not int or type(right) is not int or left < 0 or right < 0:
                raise BridgeError(index, f"bridge {n} left and right must be whole numbers of frames")
            if left + right not in BRIDGE_FRAMES:
                raise BridgeError(index, f"bridge {n} replaces {left + right} frames; a replacement covers 12, 29 or 46")
            for key in ("review", "selected"):
                if key in item and not isinstance(item[key], str):
                    raise BridgeError(index, f"bridge {n} {key} must be text")
        else:
            frames = item.get("frames")
            if type(frames) is not int:
                raise BridgeError(index, f"bridge {n} frames must be 12, 29 or 46")
            if frames not in BRIDGE_FRAMES:
                raise BridgeError(index, f"bridge {n} has {frames} frames; a bridge has 12, 29 or 46")
        seed = item.get("seed")
        if seed is None:
            seed = zlib.crc32(f"bridge:{before}".encode("utf-8"))
        elif isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= MAX_SEED:
            raise BridgeError(index, f"bridge {n} seed must be a whole number from 0 to {MAX_SEED}")
        prompt = item.get("prompt")
        if prompt is not None and not isinstance(prompt, str):
            raise BridgeError(index, f"bridge {n} prompt must be text")
        taken[before] = index
        if mode == "replace":
            bridges.append({"before": before, "mode": "replace", "left": left, "right": right, "seed": seed,
                            "prompt": prompt or "", **{key: item[key] for key in ("review", "selected") if key in item}})
        else:
            bridges.append({"before": before, "frames": frames, "seed": seed, "prompt": prompt or "",
                            **({"mode": "insert"} if "mode" in item else {})})
    return bridges


def _exact(raw, n, box):
    value = raw.get("exact", False)
    if type(value) is not bool:
        raise _error(f"box {n} exact must be true or false")
    if value and box.frames < 1:
        raise _error(f"box {n} plays at least 1 frame")
    return value


def memory_sources(timeline, index):
    """Earlier delivered-frame moments as (source box index, frame after its replay, label); scene memory spans cuts
    and resets at new scenes and appearance changes, and Cast memory chooses them from the Story bible."""
    box = timeline.boxes[index]
    if box.memory == "off":
        return []
    if box.memory == "cast":
        from . import cast_memory
        result = cast_memory.windows(timeline, index)
    elif box.memory == "scene":
        result = scene_sources(timeline, index)
    else:
        result = []
        for item in box.memories:
            candidates = [i for i, source in enumerate(timeline.boxes) if source.id == item.get("box")]
            if len(candidates) != 1 or (candidates[0] >= index if timeline.tracks is None else
                    box_start(timeline,candidates[0])*FPS + item["frame"] >= box_start(timeline,index)*FPS):
                raise _error(f"box {index + 1} memory must refer to a unique earlier box; choose its source again")
            source = candidates[0]
            played = played_frames(timeline, source)
            if item["frame"] >= played:
                # A remembered moment depends on its source; it never sets that box's length.
                raise _error(f"box {index + 1} remembers frame {item['frame']} of box {source + 1}, which plays "
                             f"{played} frames: choose a moment before frame {played}")
            result.append((source, item["frame"], item.get("label") or "visual continuity"))
    previous = previous_index(timeline,index,False)
    if replays_previous(timeline, index):
        # The full preceding video covers its individual moments, independently of Cast's picture/budget filters.
        return [(previous, 0, "the previous shot before this cut"),
                *(item for item in result if box.memory == "selected" or item[0] != previous)]
    if previous is not None and box.cut:
        before = (previous, max(0, played_frames(timeline, previous) - 5), "the moment before this cut")
        return result + [before] if not any(item[:2] == before[:2] for item in result) else result
    return result


def replays_previous(timeline, index):
    """Whether cut box `index`'s memory starts with the whole preceding video. H3 replays that video's lip movement
    onto the new shot, so not when either side of the cut speaks."""
    from . import dialogue
    previous = previous_index(timeline,index,False)
    return (previous is not None and timeline.boxes[index].cut
            and not (dialogue.speaks(timeline, index) or dialogue.speaks(timeline, previous)))


def scene_sources(timeline, index):
    """Same scene's windows for box `index`: the scene's first frame, then the moment before a cut or an earlier view
    of the current scene."""
    box = timeline.boxes[index]
    indices=track_indices(timeline,index); indices=indices[:indices.index(index)+1]
    position=max(p for p,i in enumerate(indices) if p==0 or (timeline.boxes[i].cut and timeline.boxes[i].new_scene) or timeline.boxes[i].plate_changes)
    start=indices[position]
    if start==index: return []
    before=indices[-2]; previous=played_frames(timeline,before)
    if box.cut:
        return [(start,0,"scene establishing view"),(before,max(0,previous-5),"the moment before this cut")]
    return [(start,0,"scene establishing view"),(before,max(0,(previous-5)//2),"earlier view of the current scene")]


def _changes(value, n):
    if not isinstance(value, list):
        raise _error(f"box {n} plate changes must be a list")
    return value


def effective_plates(timeline, index, frame=0):
    revisions = {p["id"]: p for p in timeline.plates}
    active = {}
    for i in track_indices(timeline,index)[:track_indices(timeline,index).index(index)+1]:
        box=timeline.boxes[i]
        for change in sorted(box.plate_changes, key=lambda c: c["frame"]):
            if change['slot'] in timeline.reference_replacements:
                continue
            if i == index and change["frame"] > frame:
                continue
            if change["revision"]:
                active[change["slot"]] = revisions[change["revision"]]
            else:
                active.pop(change["slot"], None)
    return active


def plate_chain(timeline, index):
    values = []
    for i in continuation_chain(timeline,index):
        slots = box_slots(timeline, i)
        used = set(slots.references) - {slots.first, slots.last}
        plates = [[slot, p["id"], p["image"]] for slot, p in sorted(effective_plates(timeline, i).items()) if slot in used]
        if plates:
            values.append([timeline.boxes[i].id, plates])
    return _digest(values) if values else ""


def _preview_target(value, n):
    if not isinstance(value, dict) or value.get('kind') not in ('first', 'last', 'shot'):
        raise _error(f"box {n} preview target must be first, last or a numbered shot")
    if value['kind'] == 'shot':
        if set(value) != {'kind', 'shot'} or type(value.get('shot')) is not int or value['shot'] < 1:
            raise _error(f"box {n} preview target needs a positive shot number")
        return dict(kind='first') if value['shot'] == 1 else dict(value)
    if set(value) != {'kind'}:
        raise _error(f"box {n} endpoint target must contain only kind")
    return dict(value)


def _previews(value, n):
    if not isinstance(value, list) or len(value) > LONG_MAX_FRAMES:
        raise _error(f"box {n} previews must be a list of at most {LONG_MAX_FRAMES} shots")
    shots, targets, previews = set(), {}, []
    for item in value:
        duplicate = False
        if not isinstance(item, dict):
            raise _error(f"box {n} previews must be objects")
        if 'target' in item:
            item['target'] = _preview_target(item['target'], n)
            key = (item['target']['kind'], item['target'].get('shot'))
        else:
            if type(item.get("shot")) is not int or item["shot"] < 1 or item["shot"] in shots:
                raise _error(f"box {n} previews need unique positive shot numbers")
            shots.add(item["shot"])
        if type(item.get("frame")) is not int or not 0 <= item["frame"] < LONG_MAX_FRAMES:
            raise _error(f"box {n} preview frame must be a whole number from 0 to {LONG_MAX_FRAMES - 1}")
        if item.get("guide"):
            preview_file(item["guide"])
        if 'images' in item:
            if not isinstance(item['images'], list) or any(not isinstance(image, dict) for image in item['images']):
                raise _error(f"box {n} preview images must be a list of candidates")
            for image in item['images']:
                preview_file(image.get('file'))
        if 'target' in item:
            if key in targets and json.dumps(item, sort_keys=True) != json.dumps(targets[key], sort_keys=True):
                raise _error(f"box {n} previews need unique targets")
            duplicate = key in targets
            targets[key] = item
        if not duplicate:
            previews.append(item)
    return previews


def _shot_frames(prompt, carried, last):
    # Match promptShots: filter marker locations in dialogue, but retain original timestamp bodies.
    dialogue = list(re.finditer(r'<d>[\s\S]*?(?:</d>|$)', prompt))
    base = ['integrated_multimodal_description', 'overall_soundscape', 'non_diegetic_music']
    ref = ['subject_definitions', 'summary', 'retention_analysis', 'detailed_description', *base[1:]]
    headers = [m for m in re.finditer(r'^[ \t]*(' + '|'.join(dict.fromkeys(base + ref)) + r'):', prompt, re.MULTILINE)
               if not any(d.start() <= m.start() < d.end() for d in dialogue)]
    structured = [m[1] for m in headers] in (base, ref)
    start, end = 0, len(prompt)
    if structured:
        scene = next(i for i, m in enumerate(headers) if m[1] in ('detailed_description', base[0]))
        start, end = headers[scene].end(), headers[scene + 1].start()
    source = prompt[start:end]
    marked = source if structured else re.sub(r'<d>[\s\S]*?(?:</d>|$)', lambda m: ' ' * len(m[0]), source)
    flags = re.MULTILINE if structured else re.MULTILINE | re.IGNORECASE
    markers = [m for m in re.finditer(r'^[ \t]*\[Shot ([1-9]\d*)\](?=\s|$)', marked, flags)
               if not structured or not any(d.start() <= start + m.start() < d.end() for d in dialogue)]
    numbers = [int(m[1]) for m in markers]
    frames = {}
    for i, marker in enumerate(markers):
        shot = int(marker[1])
        if numbers.count(shot) != 1:
            continue
        body = source[marker.end():markers[i + 1].start() if i + 1 < len(markers) else len(source)].strip()
        match = re.match(r'At (\d+):(\d+)\.(\d+),', body, re.IGNORECASE)
        generated = math.floor((int(match[1]) * 60 + int(match[2]) + int(match[3]) / 1000) * FPS + .5) if match else 0
        frame = 0 if shot == 1 else max(0, generated - (carried - 1 if carried else 0)) if match else None
        if frame is not None and frame <= last:
            frames[shot] = frame
    return frames


def resolved_previews(timeline, index, context):
    """Active saved records; explicit targets own positions, legacy records keep their raw local frame."""
    saved_previews = timeline.boxes[index].previews
    if not any('target' in item for item in saved_previews):
        return deepcopy(saved_previews)
    frames, carried = box_length(timeline, index, context)
    last = frames - (0 if carried else 1)
    shots = _shot_frames(timeline.boxes[index].prompt, carried, last)
    result = []
    for saved in saved_previews:
        item = deepcopy(saved)
        target = item.get('target')
        if target is not None:
            target = item['target'] = _preview_target(target, index + 1)
            frame = 0 if target['kind'] == 'first' else last if target['kind'] == 'last' else shots.get(target['shot'])
            if frame is None:
                continue
            item['frame'] = frame
        result.append(item)
    if last == 0 and any(p.get('target', {}).get('kind') == 'first' and p.get('guide') for p in result):
        result = [p for p in result if p.get('target', {}).get('kind') != 'last']
    return result


def accepted_endpoints(timeline, index, context):
    """Accepted PNGs at delivered endpoints, including the shared opening of a continuing box."""
    frames, carried = box_length(timeline, index, context)
    positions = {'first': 0, 'last': frames - (0 if carried else 1)}
    result = {}
    for item in resolved_previews(timeline, index, context):
        if item.get('guide'):
            for key, frame in positions.items():
                if item['frame'] == frame:
                    if key in result and result[key] != item['guide']:
                        raise _error(f"box {index + 1} has conflicting guides at its {key} endpoint")
                    result[key] = item['guide']
    return result


def preview_file(image):
    """Only our immutable generated PNG assets can be loaded from timeline JSON."""
    if (not isinstance(image, dict) or image.get("type") != "output"
            or image.get("subfolder") != "h3_previews"
            or not re.fullmatch(r"[A-Za-z0-9_-]+\.png", str(image.get("filename", "")))):
        raise _error("a preview guide must be a generated PNG in output/h3_previews")
    if "visible_text" in image or "text_contract" in image:
        if (not isinstance(image.get("visible_text"), list)
                or any(not isinstance(text, str) for text in image["visible_text"])
                or not isinstance(image.get("text_contract"), str)
                or not re.fullmatch(r"[a-f0-9]{64}", image["text_contract"])):
            raise _error("a lettering image needs visible_text strings and a SHA-256 text_contract")
    return "h3_previews/" + image["filename"]


def frame_movie_time(timeline, index, frame, context):
    frames, carried = box_length(timeline, index, context)
    if type(frame) is not int or not 0 <= frame < frames + int(bool(carried)):
        raise _error(f"box {index + 1} preview frame is past its end")
    return box_start(timeline, index) + (frame - int(bool(carried))) / FPS


def frame_text(timeline, index, frame, context):
    if timeline.text_lanes:
        at=frame_movie_time(timeline,index,frame,context)
        parts=[timed_text.anchor_metadata(lane['attachment'],timeline.audio_clips,at,placements=resolved_audio(timeline)) for lane in timeline.text_lanes]
        visible=[text for part in parts for text in part['visible_text']]
        return dict(visible_text=visible,text_contract=hashlib.sha256(json.dumps(parts,sort_keys=True).encode()).hexdigest())
    return timed_text.anchor_metadata(timeline.timed_text, timeline.audio_clips,
                                      frame_movie_time(timeline, index, frame, context), placements=resolved_audio(timeline))


def frame_guides(timeline, index, context):
    """Generated-frame positions; local frame 0 is the shared boundary on continuing boxes."""
    frames, carried = box_length(timeline, index, context)
    guides = {}
    for item in resolved_previews(timeline, index, context):
        if not item.get("guide"):
            continue
        frame = item["frame"] + (carried - 1 if carried else 0)
        if frame >= frames + carried:
            raise _error(f"box {index + 1} has a saved guide past its end: move that guide earlier or remove it")
        timed_text.check_anchor(item["guide"], frame_text(timeline, index, item["frame"], context),
                                f"box {index + 1} guide")
        if frame in guides and guides[frame] != item["guide"]:
            raise _error(f"box {index + 1} has two different preview guides at frame {item['frame']}")
        guides[frame] = item["guide"]
    after=following_index(timeline,index)
    if after is not None and not is_fresh(timeline,after):
        for item in resolved_previews(timeline, after, context):
            if item["frame"] == 0 and item.get("guide"):
                timed_text.check_anchor(item["guide"], frame_text(timeline, after, 0, context),
                                        f"box {index + 2} guide")
                end = frames + carried - 1
                if end in guides and guides[end] != item["guide"]:
                    raise _error(f"box {index + 1} has conflicting guides at its shared boundary")
                guides[end] = item["guide"]
    return sorted(guides.items())


def guide_chain(timeline, index, context=39):
    """Guide edits invalidate dependent continuations, stopping at a cut. Empty preserves old manifests."""
    values = []
    for i in continuation_chain(timeline,index):
        own = []
        if any(p.get("guide") for p in timeline.boxes[i].previews):
            own = [[p["frame"], p["guide"]] for p in resolved_previews(timeline, i, context) if p.get("guide")]
        after=following_index(timeline,i)
        if (after is not None and not is_fresh(timeline,after)
                and any(p.get("guide") for p in timeline.boxes[after].previews)):
            own += [["end", p["guide"]] for p in resolved_previews(timeline, after, context)
                    if p["frame"] == 0 and p.get("guide")]
        if own:
            values.append([timeline.boxes[i].id, own])
    return _digest(values) if values else ""


def track_indices(timeline, index):
    if timeline.tracks is None:
        return list(range(len(timeline.boxes)))
    track = timeline.placements[timeline.boxes[index].id]['track']
    return sorted((i for i,b in enumerate(timeline.boxes) if timeline.placements[b.id]['track']==track),
                  key=lambda i: timeline.placements[timeline.boxes[i].id]['start'])


def previous_index(timeline, index, adjacent=True):
    if timeline.tracks is None:
        return index-1 if index else None
    indices=track_indices(timeline,index); position=indices.index(index)
    if not position:
        return None
    previous=indices[position-1]
    return previous if not adjacent or timeline.placements[timeline.boxes[previous].id]["end"]==timeline.placements[timeline.boxes[index].id]["start"] else None


def following_index(timeline, index):
    if timeline.tracks is None:
        return index+1 if index+1<len(timeline.boxes) else None
    indices=track_indices(timeline,index); position=indices.index(index)
    if position+1==len(indices):
        return None
    after=indices[position+1]
    return after if timeline.placements[timeline.boxes[index].id]["end"]==timeline.placements[timeline.boxes[after].id]["start"] else None


def continuation_chain(timeline,index):
    chain=[index]
    while not is_fresh(timeline,chain[0]):
        previous=previous_index(timeline,chain[0])
        if previous is None: break
        chain.insert(0,previous)
    return chain


def is_fresh(timeline, index):
    """Box 1 and cut boxes carry no frames from the box before them."""
    return timeline.boxes[index].cut or (index == 0 if timeline.tracks is None else previous_index(timeline,index,False) is None)


def frame_limits(fresh, context, limit=MAX_FRAMES):
    """Fewest and most frames a box can add to the movie; `limit` is the Timeline's most generated frames."""
    return (MIN_FRESH_FRAMES, limit) if fresh else (MIN_CONTINUING_FRAMES, limit - context)


def snap_frames(frames, fresh):
    """Nearest length on the grid: 17k+5 frames for a fresh box, 17k for a continuing one, k >= 1."""
    offset = 5 if fresh else 0
    return GRID * max(1, round((frames - offset) / GRID)) + offset


def generated_frames(frames, fresh):
    """Smallest length on the grid that holds `frames`: 17k+5 frames for a fresh box, 17k for a continuing one."""
    offset = 5 if fresh else 0
    return GRID * max(1, math.ceil((frames - offset) / GRID)) + offset


def is_exact(timeline, index):
    return index < len(timeline.exact) and timeline.exact[index]


def played_frames(timeline, index):
    """The frames box `index` adds to the movie: its own for an exact box, else the nearest length on the grid."""
    box = timeline.boxes[index]
    return box.frames if is_exact(timeline, index) else snap_frames(box.frames, is_fresh(timeline, index))


def dropped_frames(timeline, index):
    """The generated frames an exact box drops after its last played one; 0 for every other box."""
    if not is_exact(timeline, index):
        return 0
    frames = timeline.boxes[index].frames
    return generated_frames(frames, is_fresh(timeline, index)) - frames


def _drop_conflict(timeline, index, context):
    """The error for box `index`, which drops frames, and the next box, which would continue from them."""
    fresh = is_fresh(timeline, index)
    low, high = frame_limits(fresh, context, timeline.max_frames)
    above = generated_frames(timeline.boxes[index].frames, fresh)
    lengths = " or ".join(str(length) for length in (above - GRID, above) if low <= length <= high)
    n = index + 1
    return _error(f"box {n} drops {dropped_frames(timeline, index)} generated frames, so box {n + 1} can't continue "
                  f"it: make box {n + 1} a cut, or give box {n} a length on the grid ({lengths} frames), which moves "
                  "every later box")


def box_length(timeline, index, context):
    """(frames box `index` adds to the movie, frames it carries); raises when the box is too long, or when it or the
    box before it drops frames that the next one would continue from."""
    if timeline.tracks is not None and not timeline.boxes[index].cut and previous_index(timeline,index) is None:
        raise _error(f"box {index+1} must be adjacent to a preceding clip on its track to Continue; choose Cut or New scene")
    for source in (previous_index(timeline,index), index):
        after=following_index(timeline,source) if source is not None else None
        if source is not None and after is not None and not is_fresh(timeline, after) and dropped_frames(timeline, source):
            raise _drop_conflict(timeline, source, context)
    fresh = is_fresh(timeline, index)
    frames = played_frames(timeline, index)
    high = frame_limits(fresh, context, timeline.max_frames)[1]
    if frames > high:
        n = index + 1
        if fresh:
            raise _error(f"box {n} is {seconds(frames):.2f} s ({frames} frames), but H3 generates at most "
                         f"{seconds(timeline.max_frames):.2f} s ({timeline.max_frames} frames)")
        raise _error(f"box {n} adds {seconds(frames):.2f} s ({frames} frames), but a box that continues the "
                     f"previous one can add at most {seconds(high):.2f} s ({timeline.max_frames} frames minus {context} "
                     "carried)")
    return frames, 0 if fresh else context


def carry_conflict(timeline, index, context):
    """The problem when box `index` continues a box that plays fewer frames than it carries, or "". Only rendering
    refuses it; the Studio shows it on the box."""
    previous=previous_index(timeline,index)
    if is_fresh(timeline,index) or previous is None or not is_fresh(timeline,previous):
        return ""
    before = played_frames(timeline, previous)
    if before >= context:
        return ""
    return (f"box {index + 1} continues box {index}, which plays {before} frames, fewer than the {context} it carries: "
            f"make box {index + 1} a cut, or give box {index} at least {context} frames, which moves every later box")


def assemble_prompt(timeline, index):
    inactive = [clip["slot"] for clip in timeline.audio_clips if clip not in active_audio_clips(timeline, index)]
    from . import reference_assets
    prompt = join_prompts(*(without_disabled_refs(part.strip(), timeline.disabled_refs + inactive)
                            for part in (timeline.prompt, timeline.boxes[index].prompt)))
    return join_prompts(prompt,reference_assets.native_prompt(timeline,index))


def join_prompts(shared, prompt):
    """Shared direction stays inside a structured prompt's body, after its alignment/header."""
    if shared and (prompt.startswith(("integrated_multimodal_description:", "subject_definitions:",
                                      "For the target video,", "How the reference pictures align"))
                   and "\noverall_soundscape:" in prompt and "\nnon_diegetic_music:" in prompt):
        marker = "[Shot 1] "
        if marker in prompt:
            return prompt.replace(marker, marker + shared + " ", 1)
    return "\n\n".join(part for part in (shared, prompt) if part)


def without_disabled_refs(text, disabled):
    return MENTION.sub(lambda match: ("the described sound" if match.group(1).lower() in ("audio", "video_audio") else "the described subject")
                       if reference_disabled(f"{match.group(1).lower()}{int(match.group(2))}", disabled) else match.group(0), text)


def mentions(text):
    """Distinct mentions in order of appearance, as (kind, slot) pairs such as ("image", "image3")."""
    found = []
    for match in MENTION.finditer(text):
        kind = match.group(1).lower()
        item = (kind, f"{kind}{int(match.group(2))}")
        if item not in found:
            found.append(item)
    return found


def rewrite(text, tags):
    """Replaces mentions and bare names of selected references with their H3 tags."""
    rewritten = MENTION.sub(lambda match: tags[f"{match.group(1).lower()}{int(match.group(2))}"], text)
    rewritten = re.sub(r"(?<![\w@])(image|audio|video_audio|video)(\d+)(?!\w)",
                       lambda match: tags.get(f"{match.group(1).lower()}{int(match.group(2))}", match.group(0)),
                       rewritten, flags=re.IGNORECASE)
    # MiniMax's FL2VA alignment sentence uses unbracketed Picture/Shot names.
    # The keyframe order is fixed even when both endpoints use the same image slot.
    if rewritten.startswith("How the reference pictures align with the target video — "):
        first, separator, rest = rewritten.partition("\n")
        if "(from Shot 1)" in first and "; " in first:
            pictures = re.findall(r"<Picture \d+>", first)
            ordinary_pair = pictures == ["<Picture 1>", "<Picture 2>"] and len(tags) == 2
            repeated_endpoint = pictures == ["<Picture 1>", "<Picture 1>"] and len(tags) == 1
            if ordinary_pair or repeated_endpoint:
                ordinal = iter(("Picture 1", "Picture 2"))
                first = re.sub(r"<Picture \d+>", lambda _: next(ordinal), first, count=2)
                rewritten = first + separator + rest
    return rewritten


def box_slots(timeline, index, context=39):
    """Mode, references and the H3 tag of each slot for box `index` (the spec's box rules)."""
    box = timeline.boxes[index]
    first = box.first if is_fresh(timeline, index) and box.first not in timeline.disabled_refs else ""
    last = box.last if box.last not in timeline.disabled_refs else ""
    keyframes = [name for name in (first, last) if name]
    found = mentions(assemble_prompt(timeline, index))
    images = [name for kind, name in found if kind == "image"]
    audios = [name for kind, name in found if kind == "audio"]
    video_audios = sorted([name for kind, name in found if kind == "video_audio"], key=slot_number)
    videos = sorted(set([name for kind, name in found if kind == "video"] +
                        [name.replace("video_audio", "video") for name in video_audios]), key=slot_number)
    audios = list(dict.fromkeys(audios + [clip["slot"] for clip in active_audio_clips(timeline, index, context)]))
    assigned = {ref["slot"]: ref for ref in timeline.refmods if ref.get("strength", 1) > 0}
    mods = [assigned[name] for name in sorted(images + audios, key=lambda name: (name.startswith("audio"), slot_number(name)))
            if name in assigned and name not in effective_plates(timeline, index)]
    mod_slots = {ref["slot"] for ref in mods}
    images = [name for name in images if name not in mod_slots]
    audios = [name for name in audios if name not in mod_slots]
    endpoint_first = endpoint_last = False
    if any(p.get("guide") for box in timeline.boxes[index:index + 2] for p in box.previews):
        frames, carried = box_length(timeline, index, context)
        guides = frame_guides(timeline, index, context)
        endpoint_first = is_fresh(timeline, index) and any(frame == 0 for frame, _ in guides)
        endpoint_last = any(frame == frames + carried - 1 for frame, _ in guides)
    effective_first = "" if endpoint_first else first
    effective_last = "" if endpoint_last else last
    fresh = is_fresh(timeline, index)
    # Raw audio rides along as the same audio reference block REF2VA builds; raw video has no FLF2VA form.
    if box.flf_refmods and (not fresh or first or endpoint_first) and not videos:
        if endpoint_first and played_frames(timeline, index) == 1 and last in images:
            effective_last = last  # A referenced named Last remains a text-image source; First owns frame 0.
        last_present = bool((last or endpoint_last) and (not fresh or played_frames(timeline, index) > 1
                            or (effective_last and effective_last in images)))
        first_present = int(bool(first or endpoint_first))
        endpoint_count = first_present + int(last_present)
        tags = {first: "<Picture 1>"} if first else {}
        if last and last_present:
            tags.setdefault(last, f"<Picture {first_present + 1}>")
        images = sorted([name for name in images if name not in keyframes], key=slot_number)
        counters = {"image": endpoint_count * 2, "video": 0, "audio": 0}
        for name in images:
            counters["image"] += 1
            tags[name] = f"<Picture {counters['image']}>"
        audios = sorted(audios, key=slot_number)
        for name in audios:
            counters["audio"] += 1
            tags[name] = f"<Audio {counters['audio']}>"
        labels = {"image": "Picture", "video": "Video", "audio": "Audio"}
        for ref in mods:
            counters[ref["kind"]] += 1
            tags[ref["slot"]] = f"<{labels[ref['kind']]} {counters[ref['kind']]}>"
        return Slots("flf2va", sorted(images + [ref["slot"] for ref in mods if ref["kind"] != "audio"], key=slot_number),
                     audios + [ref["slot"] for ref in mods if ref["kind"] == "audio"],
                     effective_first, effective_last if last_present else "", tags, mods)
    if not mods and not audios and not videos and set(images) <= set(keyframes):
        if endpoint_first and played_frames(timeline, index) == 1 and last in images:
            effective_last = last  # A named Last remains a text-image source; First owns the only physical frame.
        tags = {}
        for number, name in enumerate(keyframes, 2 if endpoint_first and not first else 1):
            tags.setdefault(name, f"<Picture {number}>")
        return Slots("flf2va" if keyframes or endpoint_first or endpoint_last else "t2va", [], [],
                     effective_first, effective_last, tags)
    images.sort(key=slot_number)
    audios.sort(key=slot_number)
    tags = {name: f"<Picture {number}>" for number, name in enumerate(images, 1)}
    tags.update({name: f"<Video {number}>" for number, name in enumerate(videos, 1)})
    tags.update({name: f"<Audio {number}>" for number, name in enumerate(video_audios + audios, 1)})
    counters = {"image": len(images), "audio": len(video_audios) + len(audios), "video": len(videos)}
    labels = {"image": "Picture", "audio": "Audio", "video": "Video"}
    for ref in mods:
        counters[ref["kind"]] += 1
        tags[ref["slot"]] = f"<{labels[ref['kind']]} {counters[ref['kind']]}>"
    return Slots("ref2va", sorted(images + [ref["slot"] for ref in mods if ref["kind"] != "audio"], key=slot_number) + videos,
                 video_audios + sorted(audios + [ref["slot"] for ref in mods if ref["kind"] == "audio"], key=slot_number),
                 effective_first, effective_last, tags, mods)


@dataclass
class BoxPlan:
    index: int
    box: Box
    fresh: bool
    frames: int
    carried: int
    generated: int
    slots: Slots
    prompt: str
    layout: str
    settings: dict
    notes: list
    text_window: dict = field(default_factory=dict)


def plan_box(timeline, index, context, carry_audio, width, height, ref_image_size, images, audios, *, audio_context_frames=0):
    """What to render for box `index`, checked against the connected `images` / `audios` slot names."""
    n = index + 1
    box = timeline.boxes[index]
    fresh = is_fresh(timeline, index)
    frames, carried = box_length(timeline, index, context)
    source = timeline.story[index].get("source") if index < len(timeline.story) else None
    if source and "stages" in source.get("frame", {}):
        frame = source["frame"]
        if (frame["frames"], frame["carried"]) != (frames + carried, carried):
            raise _error(f"box {n}'s stage schedule has a different length or replay; rewrite it before rendering")
    text = assemble_prompt(timeline, index)
    if not text:
        raise _error(f"box {n} has no prompt")
    from . import dialogue
    problem = dialogue.box_problem(timeline, index, context, text)
    if problem:
        raise _error(problem)
    assigned = {ref["slot"] for ref in timeline.refmods if ref.get("strength", 1) > 0}
    slots = box_slots(timeline, index, context)
    for kind, name in mentions(text):
        if ((kind == "video" and name not in VIDEO_SLOTS) or (kind == "video_audio" and name not in VIDEO_AUDIO_SLOTS)) and name not in timeline.reference_replacements and name.replace('video_audio', 'video') not in timeline.reference_replacements:
            raise _error(f"box {n} uses unsupported @{name}; video and video_audio slots run from 1 to 3")
        pool = images if kind in ("image", "video") else audios
        if (slots.mode != "ref2va" and kind == "image" and name in slots.tags
                and name not in (slots.first, slots.last) and name not in slots.references):
            continue
        if name not in pool and name not in assigned:
            listed = ", ".join(sorted(pool, key=slot_number)) or "none"
            raise _error(f"box {n} mentions @{name}, but {name} is not connected (connected {kind} slots: {listed})")
    for name in slots.video_inputs:
        if name not in images:
            raise _error(f"box {n} needs {name}, but {name} is not connected")
    if len(slots.video_inputs) > MAX_REF_VIDEOS:
        raise _error(f"box {n} mentions too many videos; H3 takes at most {MAX_REF_VIDEOS}")
    for change in box.plate_changes:
        if change['slot'] not in timeline.reference_replacements and change["frame"] > 0 and change["slot"] in slots.references and change["slot"] not in (slots.first, slots.last):
            raise _error(f"box {n} changes a plate inside one H3 generation. Split before that shot to use both appearances")
    for what, name in (("first frame", slots.first), ("last frame", slots.last)):
        if name in assigned:
            raise _error(f"box {n} uses RefMod {name} as its {what}; use an image input or a saved guide")
        if name and name not in images:
            raise _error(f"box {n} uses {name} as its {what}, but {name} is not connected")
    if len(slots.image_inputs) > MAX_REF_IMAGES and slots.mode == "ref2va":
        raise _error(f"box {n} mentions {len(slots.references)} images; H3 takes at most {MAX_REF_IMAGES} references")
    if len(slots.audio_inputs) > MAX_REF_AUDIOS:
        raise _error(f"box {n} mentions {len(slots.audios)} audios; H3 takes at most {MAX_REF_AUDIOS} references")
    notes = []
    dropped = dropped_frames(timeline, index)
    if dropped:
        notes.append(f"Box {n} plays {frames} frame{'' if frames == 1 else 's'}; H3 generates {frames + dropped} "
                     f"and drops the last {dropped}.")
    elif frames != box.frames:
        notes.append(f"Box {n}: {box.frames} frames is off the H3 grid, so it renders {frames}.")
    if frames + dropped + carried > MAX_FRAMES:
        notes.append(f"Box {n} generates {frames + dropped + carried} frames, more than H3 samples at once ({MAX_FRAMES}): "
                     "connect H3 Context Windows between the model and the sampler.")
    if box.first and not fresh:
        notes.append(f"Box {n} continues box {index}, so its first frame {box.first} is not used.")
    if slots.first and slots.last and frames == 1:
        notes.append(f"Box {n} plays 1 frame, so its last frame {slots.last} is not used.")
    if RAW_TAG.search(text):
        notes.append(f"Box {n} has a typed <Picture N>-style tag, sent as written; @image mentions are safer.")
    settings = box_settings(fresh, slots.mode, width, height, context, carry_audio, ref_image_size,
                            audio_context_frames=audio_context_frames)
    window = text_window(timeline, index, context)
    prompt = timed_prompt(timeline, index, context, rewrite(text, slots.tags), slots.mode, window)
    return BoxPlan(index, box, fresh, frames, carried, frames + dropped + carried, slots, prompt,
                   layout_key(timeline, index, context), settings, notes, window)


def timed_prompt(timeline, index, context, prose, mode, window):
    """`prose` with box `index`'s timed text and its recordings' dialogue, as H3 receives it."""
    from . import dialogue
    prompt=prose
    for part in window.get("lanes", [window]):
        prompt=timed_text.insert(prompt,mode,part)
    return dialogue.insert(prompt, mode, dialogue.box_events(timeline, index, context))


def _digest(value):
    return hashlib.sha1(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def text_window(timeline, index, context):
    frames, carried = box_length(timeline, index, context)
    if timeline.text_lanes:
        windows=[timed_text.project(lane['attachment'],timeline.audio_clips,box_start(timeline,index),frames,carried,
                                   placements=resolved_audio(timeline)) for lane in timeline.text_lanes]
        merged=dict(windows[0],lanes=windows,cues=[],words=[],direction='\n'.join(w['direction'] for w in windows))
        for lane,window in zip(timeline.text_lanes,windows):
            for key in ('cues','words'):
                merged[key].extend(dict(cue,id=lane['track']+':'+cue['id']) for cue in window[key])
        return merged
    return timed_text.project(timeline.timed_text, timeline.audio_clips, box_start(timeline, index), frames, carried,
                             placements=resolved_audio(timeline))


def text_chain(timeline, index, context):
    """Text edits invalidate carried lettering up to the next cut, without hashing unrelated cues."""
    if not timeline.text_lanes and (timeline.timed_text is None or not timeline.timed_text["enabled"]):
        return ""
    values = []
    for i in continuation_chain(timeline,index):
        contract = timed_text.render_contract(text_window(timeline, i, context))
        if contract:
            values.append([timeline.boxes[i].id, contract])
    return _digest(values) if values else ""


def layout_key(timeline, index, context=39):
    """Fingerprint of what the timeline says about box `index`; its id is not part of it."""
    box = timeline.boxes[index]
    fresh = is_fresh(timeline, index)
    slots = box_slots(timeline, index, context)
    value = {"prompt": assemble_prompt(timeline, index), "frames": played_frames(timeline, index),
             "seed": box.seed, "fresh": fresh, "first": slots.first, "last": slots.last}
    if timeline.tracks is not None:
        # Only what differs from the sequential layout joins the key, so converting a project to tracks
        # does not make saved media read as outdated.
        if box_start(timeline,index)!=sum(played_frames(timeline,i) for i in range(index))/FPS:
            value["start"] = box_start(timeline,index)
        if not fresh:
            before=previous_index(timeline,index)
            if before!=(index-1 if index else None):
                value["previous"] = timeline.boxes[before].id if before is not None else None
    if box.flf_refmods:
        value["flf_refmods"] = True
    if not fresh and not timeline.continuation_guide:
        value["continuation_guide"] = False
    if not fresh and timeline.context_noise:
        value["context_noise"] = True
    if not fresh and timeline.audio_feather:
        value["audio_feather"] = timeline.audio_feather
    if timeline.reference_replacements:
        value['reference_replacements'] = timeline.reference_replacements
    dropped = dropped_frames(timeline, index)
    if dropped:
        value["generated"] = value["frames"] + dropped
    clips = active_audio_clips(timeline, index, context)
    if clips:
        value['audio_clips'] = [{key: clip.get(key) for key in ('slot','file','start','source_start','duration')}
                               for clip in clips if 'box_windows' not in clip]
        if value['audio_clips']:
            value['audio_box_start'] = box_start(timeline, index)
        origin = box_start(timeline, index) - box_length(timeline,index,context)[1] / FPS
        end = box_start(timeline,index) + played_frames(timeline,index) / FPS
        value['audio_windows'] = []
        for clip in clips:
            if 'box_windows' not in clip: continue
            for window in audio_windows.coalesce(w for w in resolved_audio(timeline) if w['slot']==clip['slot']):
                left, right = max(origin,window['start']), min(end,window['start']+window['duration'])
                if right > left:
                    value['audio_windows'].append(dict(slot=clip['slot'], file=clip.get('file'), source=clip['box_windows']['source'],
                        sample_origin={key:clip['box_windows']['placement'][key] for key in ('start','source_start')},
                        offset=left-origin, source_start=window['source_start']+left-window['start'], duration=right-left))
        if not value['audio_windows']: value.pop('audio_windows')
        if not value['audio_clips']: value.pop('audio_clips')
    from . import studio_pictures, voice_clips
    pictures = studio_pictures.used(timeline, index)
    if pictures:
        value["studio_pictures"] = [{"slot": picture["slot"], "file": picture["file"]} for picture in pictures]
    voices = voice_clips.used(timeline, index)
    if voices:
        value["voice_clips"] = [{"slot": clip["slot"], "file": clip["file"]} for clip in voices]
    mods = slots.refmods
    if mods:
        value["refmods"] = [{key: ref.get(key) for key in ("slot", "name", "member", "kind", "strength", "stamp")} for ref in mods]
    chain = guide_chain(timeline, index, context)
    if chain:
        value["preview_guides"] = chain
    text = text_chain(timeline, index, context)
    if text:
        value["timed_text"] = text
    from . import dialogue
    events = dialogue.box_events(timeline, index, context)
    if events:
        value["dialogue"] = dialogue.digest(events)
    plates = plate_chain(timeline, index)
    if plates:
        value["appearance_plates"] = plates
    if box.plate_changes:
        value["plate_changes"] = box.plate_changes
    sources = memory_sources(timeline, index)
    if sources:
        value["visual_memory"] = [[timeline.boxes[source].id, frame, label] for source, frame, label in sources]
    return _digest(value)


def box_settings(fresh, mode, width, height, context, carry_audio, ref_image_size, *, audio_context_frames=0):
    """The node settings that change what H3 renders for a box; unknown (None) values stay None."""
    result = {"width": width, "height": height, "context_frames": 0 if fresh else context,
              "carry_audio": False if fresh else carry_audio,
              "ref_image_size": ref_image_size if mode == "ref2va" else None}
    if audio_context_frames is None:
        if not fresh:
            result['audio_context_frames'] = None
    elif context is not None and carry_audio is not None:
        audio = effective_audio_context(context, carry_audio and not fresh, audio_context_frames)
        if audio not in (0, context):
            result['audio_context_frames'] = audio
    elif audio_context_frames:
        result['audio_context_frames'] = None
    return result


def settings_match(saved, wanted):
    """Compare known render settings, including an omitted legacy follow-video audio budget."""
    if not all(key in saved and saved[key] == value for key, value in wanted.items()
               if key != 'audio_context_frames' and value is not None):
        return False
    context, carry = wanted.get('context_frames'), wanted.get('carry_audio')
    requested = wanted.get('audio_context_frames', 0)
    if context is None or carry is None or requested is None:
        return True
    return (effective_audio_context(context, carry, requested)
            == effective_audio_context(context, carry, saved.get('audio_context_frames', 0)))


def segment_matches(entry, layout, settings, media=None):
    """Whether saved segment `entry` was rendered from this box: the same layout, the given settings
    and, unless `media` is None, the same references."""
    record = entry.get("timeline") or {}
    saved = record.get("settings") or {}
    return (record.get("layout") == layout
            and settings_match(saved, settings)
            and (media is None or record.get("media") == media))


def render_order(timeline):
    if timeline.tracks is None: return list(range(len(timeline.boxes)))
    return sorted(range(len(timeline.boxes)),key=lambda i:(box_start(timeline,i),i))


def next_box(count, segments_by_index, is_done, order=None):
    """Index of the first of `count` boxes that is not done, or None. `is_done(index, entry)` judges
    box `index` against the segment saved at position index + 1."""
    for index in (range(count) if order is None else order):
        entry = segments_by_index.get(index + 1)
        if entry is None or not is_done(index, entry):
            return index
    return None


def status_payload(name, timeline, segments, next_index, thumb, full_video, movie_seconds, done_indices=None,
                   kept_indices=()):
    """What the editor shows; `thumb(entry)` returns a /view file dict or None. `segments` are numbered by box
    (store.align). A box in `kept_indices` has a saved take that is outdated: it keeps its picture and plays until it
    is regenerated."""
    count = len(timeline.boxes)
    by_index = {entry["index"]: entry for entry in segments}
    done_indices = set(range(count if next_index is None else next_index)) if done_indices is None else done_indices
    done = len(done_indices)
    boxes = []
    for index, box in enumerate(timeline.boxes):
        entry = by_index.get(index + 1)
        if index in done_indices or index in kept_indices:
            item = {"id": box.id, "status": "done" if index in done_indices else "outdated"}
            picture = thumb(entry)
            if picture:
                item["thumb"] = picture
        else:
            item = {"id": box.id, "status": "next" if index == next_index else "pending"}
            if entry is not None:
                item["replaces"] = True
        boxes.append(item)
    trailing = [entry["index"] for entry in segments if entry["index"] > count]
    outdated = len([index for index in kept_indices if index not in done_indices])
    if not count:
        message = "Draw a box to start."
    elif next_index is not None:
        message = f"Box {next_index + 1} is next."
    elif outdated:
        message = (f"Every box has a take; {outdated} {'is' if outdated == 1 else 'are'} outdated. Select an outdated "
                   "box and regenerate it to update it.")
    else:
        message = "The box is rendered." if count == 1 else f"All {count} boxes are rendered."
    return {"ok": True, "name": name, "next": None if next_index is None else next_index + 1, "done": done,
            "outdated": outdated, "segments": len(segments), "trailing": len(trailing),
            "seconds": round(movie_seconds, 2), "full_video": full_video, "boxes": boxes, "message": message}
