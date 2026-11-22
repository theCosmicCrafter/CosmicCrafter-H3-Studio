"""The continuity check: for each rendered box it asks the Story's Vision model whether the box's frames keep the
bible's characters, props and place and the join from the box before, and measures drift against its scene's first
box. It never renders, and writes only the sequence folder's checks.json."""

import asyncio
import dataclasses
import io
import json
import logging
import os
import secrets
import time
import traceback

import av

from PIL import Image

from . import box_checks, check_frames, llm, media, store, story_bible, story_context, story_inputs, story_keys
from . import story_vram
from . import studio_pictures, reference_replacements
from . import h3_prompt_ir as prompt_ir, h3_prompt_schema as prompt_schema
from . import nodes as continuity
from . import timeline as rules

TEXT_INPUTS = ("base_url", "thinking", "vision_base_url", "vision_model")
MAX_PROBLEMS = 12
RENDERING = "ComfyUI is rendering or has prompts waiting. Check when its queue is empty."
CANCELLED = "Cancelled. Finished checks were kept."
DROPPED = "ComfyUI's queue dropped the check's turn."
ENDED = "ComfyUI's queue ended the check's turn, so the check stopped. Finished checks were kept."
FAILED = "The check failed unexpectedly; the ComfyUI console has the details."
SKIPPED = "Box {number}: the check couldn't read its video, so it skipped the box."
UNREADABLE = "The check couldn't read the Vision model's answer."
PICTURE = "The check couldn't read the picture for {slot}, so the model didn't see it."
NOTHING_RENDERED = "No box is rendered yet."
ALL_CURRENT = "Every rendered box has a current check. Use Check on a box's page to check it again."
NOT_RENDERED = "Box {number} isn't rendered yet."
UNKNOWN_BOX = "Select an existing Timeline box to check it."
JOINS = {"continue": "Join: continue from box {before}'s last frame.",
         "transition": "Join: a transition from box {before}.",
         "cut": "Join: a cut from box {before}, in the same scene.",
         "new_scene": "Join: a cut to a new scene, so box {before} needn't match."}
CHECK_INSTRUCTION = """You check one box of a generated video for continuity. First come the pictures it must keep \
to: the last frame of the box before, when the box continues from it, and the pictures of the box's characters, \
props and place. Then come frames from the box, each labelled with its shot and its time in the box.

Report only differences a viewer would notice:
- a character, prop or place that doesn't match its pictures or its wording: another face, hair, build, outfit, \
colour, shape or material, or a missing or extra detail that the wording names;
- a broken join: a box that continues from the box before but doesn't match its last frame and its ending in place, \
positions, light or props.

Don't report camera moves, framing, composition, motion, blur or artefacts, anything the wording doesn't settle, or \
how the story goes on.

Answer with one JSON object and nothing else: {"problems": [{"about": "...", "what": "...", "shot": 0}]}. "about" is \
the id of the character or prop the problem is about, "place" for the place, or "join" for the join. "what" is one \
short sentence that says what differs and names it. "shot" is the number of the shot where it shows, or 0 when it \
isn't in one shot. Give at most 12 problems, the clearest first. With none, answer {"problems": []}."""


@dataclasses.dataclass
class CheckContext:
    """What a check reads from the snapshot Check posts. `raw` are the Timeline's boxes as saved, `rendered` the
    manifest entries with a video by box id, in Timeline order, `boxes` the ids to check, and `pictures` the files of
    the image slots by slot, None for one the check can't find."""
    story_id: str
    timeline_id: str
    name: str
    folder: str
    timeline: rules.Timeline
    raw: list
    bible: dict | None
    rendered: dict
    boxes: list
    pictures: dict
    base_url: str = ""
    vision_base_url: str = ""
    vision_model: str = ""
    thinking: str = "medium"
    free_vram: bool = True
    links: dict = dataclasses.field(default_factory=dict)
    snapshot: dict = dataclasses.field(default_factory=dict)
    notes: list = dataclasses.field(default_factory=list)
    urls: dict = dataclasses.field(default_factory=dict)

    @property
    def url(self):
        return self.vision_base_url or self.base_url


def read(prompt, story_id, boxes=None):
    """The CheckContext of story node `story_id` in the API prompt `prompt` for the box ids `boxes`, or for Check all
    every rendered box without a current result, counting a drift-only result as none when the Story now has a
    Vision model; raises ValueError saying why the check can't start. The settings it has to run nodes for are in
    its links and "" until settle(); without a Vision model there are none."""
    if not isinstance(prompt, dict):
        raise ValueError("The check request has no workflow snapshot.")
    story, timeline_id, node = story_context.find_nodes(prompt, story_id)
    inputs = story.get("inputs") or {}
    if story_context._link(inputs.get("free_vram")):
        raise ValueError("Set free_vram on the story node itself.")
    texts, links = {}, {}
    for name in TEXT_INPUTS:
        way, text = story_context.read_text(prompt, inputs.get(name, ""))
        if way == "muted":
            raise ValueError(f"The {name} comes from a node that is muted or bypassed.")
        if way == "run":
            links[name] = inputs[name]
        texts[name] = text.strip() if way == "text" else ""
    vision = bool(texts["vision_model"]) or "vision_model" in links
    thinking = "medium"
    if not vision:
        links = {}
    else:
        if texts["vision_base_url"]:
            links.pop("base_url", None)
        if "vision_base_url" not in links and "base_url" not in links:
            story_keys.host_of(texts["vision_base_url"] or texts["base_url"])
        if "thinking" in inputs and "thinking" not in links:
            thinking = story_context._choice(texts["thinking"])
            if thinking is None:
                raise ValueError("Set thinking to off, minimal, low, medium, high, xhigh or max.")
    settings = node.get("inputs") or {}
    text = settings.get("timeline")
    if not isinstance(text, str):
        raise ValueError("The check can't read the Timeline's boxes; its timeline input must not be linked.")
    parsed = rules.parse(text)
    data = json.loads(text)
    try:
        raw = story_bible.boxes(data)
        bible = data.get("bible")
        if bible is not None:
            story_bible.entities(bible)
    except ValueError as error:
        raise ValueError(f"The Timeline's bible can't be used: {error}") from None
    name = story_context.resolve_text(prompt, settings.get("name", ""), "Timeline name")
    folder = store.sequence_dir(continuity.sequences_root(), name)
    with continuity.SEQUENCE_LOCK:
        segments = store.load_manifest(folder)["segments"]
    first = {}
    for entry in segments:
        first.setdefault((entry.get("timeline") or {}).get("box"), entry)
    rendered = {box.id: first[box.id] for box in parsed.boxes if (first.get(box.id) or {}).get("video")}
    ids = [box.id for box in parsed.boxes]
    if boxes is None:
        if not rendered:
            raise ValueError(NOTHING_RENDERED)
        records = box_checks.load(folder)
        chosen = [box_id for box_id, entry in rendered.items() if not box_checks.current(records.get(box_id), entry)
                  or vision and not records[box_id].get("model")]
        if not chosen:
            raise ValueError(ALL_CURRENT)
    else:
        if not isinstance(boxes, list) or not boxes or not all(isinstance(item, str) for item in boxes):
            raise ValueError("The check request's boxes must be a list of box ids.")
        for box_id in boxes:
            if box_id not in ids:
                raise ValueError(UNKNOWN_BOX)
            if box_id not in rendered:
                raise ValueError(NOT_RENDERED.format(number=ids.index(box_id) + 1))
        chosen = [box_id for box_id in ids if box_id in boxes]
    reference_replacements.refmods(parsed)
    pictures = {ref.name: ref.path for ref in story_context.references(prompt, settings)}
    for picture in parsed.pictures:
        if picture['slot'] not in parsed.reference_replacements:
            try:
                pictures[picture["slot"]] = studio_pictures.path(picture["file"])
            except ValueError:
                pictures[picture["slot"]] = None
    for clip in [*parsed.audio_clips, *parsed.voice_clips]:
        pictures.setdefault(clip['slot'], None)
    for ref in parsed.refmods:
        pictures[ref['slot']] = None
    pictures = reference_replacements.resolve(parsed, pictures,
        lambda target, file: reference_replacements.file_path(file, target))
    pictures = {name: path for name, path in pictures.items() if name.startswith('image') and name not in parsed.disabled_refs}
    return CheckContext(story_id=str(story_id), timeline_id=timeline_id, name=os.path.basename(folder), folder=folder,
                        timeline=parsed, raw=raw, bible=bible, rendered=rendered, boxes=chosen, pictures=pictures,
                        base_url=texts["base_url"], vision_base_url=texts["vision_base_url"],
                        vision_model=texts["vision_model"], thinking=thinking,
                        free_vram=inputs.get("free_vram", True) is not False, links=links,
                        snapshot=prompt if links else {})


def settle(ctx, texts):
    """`ctx` with `texts`, what ComfyUI gave for each of its links by input name, checked as typed settings are.
    Raises ValueError naming an input whose text fails its check."""
    values = {}
    for name in ctx.links:
        text = texts.get(name, "").strip()
        if name == "thinking":
            text = story_context._choice(text)
            if text is None:
                raise ValueError("The thinking input needs off, minimal, low, medium, high, xhigh or max.")
        elif name in ("base_url", "vision_base_url") and text:
            try:
                story_keys.host_of(text)
            except ValueError:
                raise ValueError(f"The {name} input didn't get a URL that starts with http:// or https://.") from None
        values[name] = text
    settled = dataclasses.replace(ctx, **values, links={}, snapshot={})
    if settled.vision_model:
        story_keys.host_of(settled.url)
    return settled


def _picture(ctx, slot):
    """The data URL of the picture in `slot`, or None. A slot the Timeline has but the check can't read gets a note,
    once per check; a slot it doesn't have, such as a RefMod's, gets none."""
    if slot not in ctx.pictures:
        return None
    if slot not in ctx.urls:
        try:
            ctx.urls[slot] = llm.picture_url(ctx.pictures[slot]) if ctx.pictures[slot] else None
        except (OSError, ValueError):
            ctx.urls[slot] = None
        note = PICTURE.format(slot=slot)
        if ctx.urls[slot] is None and note not in ctx.notes:
            ctx.notes.append(note)
    return ctx.urls[slot]


def _frame_url(frame):
    buffer = io.BytesIO()
    Image.fromarray(frame).save(buffer, "PNG")
    buffer.seek(0)
    return llm.picture_url(buffer)


def _seconds(frame):
    return f"{frame / rules.FPS:.1f} s"


def _ending(source):
    """A box's terminal state from its saved source, in words, or ""."""
    reply = source.get("reply") if isinstance(source, dict) else None
    state = reply.get("terminal_state") if isinstance(reply, dict) else None
    if not isinstance(state, dict):
        return ""
    return "; ".join(state[key].strip().rstrip(".") for key in ("setting", "positions", "props")
                     if isinstance(state.get(key), str) and state[key].strip())


def request(ctx, index, picks, frames, previous):
    """(messages, reply_format, allowed, shots) of the Vision request for box `index`: its `frames` at `picks`,
    against the bible's pictures and wording at the box and, unless it starts a new scene, the last frame of the box
    before at `previous` (a path, or None when that box isn't rendered) and its ending. `allowed` are the reply's
    "about" values: the ids of the box's characters and props, "place", and "join" after box 1. `shots` is the box's
    number of shots, 0 without a source."""
    number = index + 1
    raw = ctx.raw[index]
    ids = [box.id for box in ctx.timeline.boxes]
    known = {item["id"]: item for item in (ctx.bible or {}).get("entities", [])}
    schedule = raw.get("schedule") or {"entities": [], "place": None}
    cast = [known[item] for item in dict.fromkeys(schedule["entities"]) if item in known and known[item]["kind"] != "place"]
    place = known.get(schedule.get("place"))
    lines, pictures = [f"Check box {number} of {len(ids)}."], []
    if cast or place:
        lines.append("The bible's words for what the box shows:")
        lines += [f"- {item['id']}, {item['name']} ({item['kind']}): {story_bible.wording(item, ids, index)}"
                  for item in cast]
        if place:
            lines.append(f"- Place {place['id']}, {place['name']}: {story_bible.wording(place, ids, index)}")
    kind = story_bible.join_kind(raw) if index else None
    if kind:
        note = ((raw.get("join") or {}).get("note") or "").strip()
        lines.append(JOINS[kind].format(before=index) + (f" Note: {note}" if note else ""))
        if kind != "new_scene" and previous:
            try:
                url = llm.picture_url(previous)
            except (OSError, ValueError):
                url = None
            if url:
                pictures.append({"label": f"Box {index}'s last frame", "url": url})
            ending = _ending(ctx.raw[index - 1].get("source"))
            if ending:
                lines.append(f"Box {index} ended: {ending}.")
    for item in [*cast, *filter(None, [place])]:
        prefix = "Place " if item is place else ""
        for slot in story_bible.pictures_at(item, ids, index):
            url = _picture(ctx, slot)
            if url:
                pictures.append({"label": f"{prefix}{item['id']}, {item['name']} ({slot})", "url": url})
    shots = len(check_frames.shot_starts(raw.get("source")) or [])
    for position, ((shot, frame), image) in enumerate(zip(picks, frames)):
        if shot:
            label = f"Box {number}, shot {shot} at {_seconds(frame)}"
        elif position == len(picks) - 1:
            label = f"Box {number}, last frame at {_seconds(frame)}"
        else:
            label = f"Box {number} at {_seconds(frame)}"
        pictures.append({"label": label, "url": _frame_url(image)})
    allowed = [item["id"] for item in cast] + ["place"] + (["join"] if index else [])
    lines.append(f"Then come {len(frames)} frames of box {number}"
                 + (f", which has {shots} shot{'s' if shots > 1 else ''}." if shots else "."))
    lines.append('"about" can be ' + ", ".join(f'"{value}"' for value in allowed)
                 + (f'; "shot" runs from 1 to {shots}, or 0.' if shots else '; "shot" is 0.'))
    problem = prompt_schema.obj({"about": prompt_schema.enum(allowed), "what": prompt_schema.TEXT,
                                 "shot": {"type": "integer", "minimum": 0, "maximum": shots}})
    reply_format = prompt_schema.reply_format(
        "h3c_check", prompt_schema.obj({"problems": prompt_schema.array(problem, 0, MAX_PROBLEMS)}))
    messages = [{"role": "system", "content": CHECK_INSTRUCTION},
                {"role": "user", "content": "\n".join(lines), "pictures": pictures}]
    return messages, reply_format, allowed, shots


def parse(reply, allowed, shots):
    """The problems in the Vision model's reply, each {"about", "what", "shot"}; raises ValueError for a reply that
    doesn't fit the request's schema."""
    data = prompt_ir.parse_json(reply)
    problems = data.get("problems") if isinstance(data, dict) else None
    if not isinstance(problems, list) or len(problems) > MAX_PROBLEMS:
        raise ValueError(f"the reply needs a problems list of at most {MAX_PROBLEMS}")
    found = []
    for item in problems:
        if not isinstance(item, dict) or item.get("about") not in allowed:
            raise ValueError("a problem is about something the box doesn't have")
        what, shot = item.get("what"), item.get("shot")
        if not isinstance(what, str) or not what.strip():
            raise ValueError("a problem doesn't say what differs")
        if type(shot) is not int or not 0 <= shot <= shots:
            raise ValueError("a problem names a shot the box doesn't have")
        found.append({"about": item["about"], "what": what.strip(), "shot": shot})
    return found


class CheckJob:
    """One continuity check as a Story job: Jobs polls, cancels and forgets it as it does a Write, but it writes no
    Story recovery record. `client` is the id of the page that started it, `graph` the id of its workflow's graph,
    and `taken` whether a panel has shown how it ended."""
    kind = "check"

    def __init__(self, ctx, client="", graph=""):
        self.id = secrets.token_urlsafe(12)
        self.ctx, self.key = ctx, None
        self.client, self.graph = client, graph
        self.state, self.progress = "running", "Starting the check..."
        self.result = self.error = None
        self.notes = ctx.notes
        self.polled = time.monotonic()
        self.updated = lambda job: None
        self.ended = None
        self.task = None
        self.reached = self.releasing = self.taken = False
        self.vram = self.turn = self.stopped = None

    def report(self, progress):
        self.progress = progress

    def view(self):
        view = {"state": self.state, "progress": self.progress, "notes": list(self.notes), "kind": self.kind}
        if getattr(self, 'agent_request_id', None):
            view['request_id'] = self.agent_request_id
        for name in ("result", "error", "vram"):
            if getattr(self, name) is not None:
                view[name] = getattr(self, name)
        return view


def summary(tally, vision):
    """The end message, such as "Checked 3 boxes: 1 with problems, 1 drifted."."""
    count = len(tally["checked"])
    parts = [f"{tally['problems']} with problems" if tally["problems"] else "",
             f"{tally['unreadable']} couldn't be read" if tally["unreadable"] else "",
             f"{tally['drifted']} drifted" if tally["drifted"] else "",
             f"{tally['held']} {'holds' if tally['held'] == 1 else 'hold'} still" if tally.get("held") else "",
             "" if vision else "drift only, because the Story has no Vision model"]
    said = ", ".join(part for part in parts if part) or "no problems found"
    return f"Checked {'1 box' if count == 1 else f'{count} boxes'}: {said}."


def frame_picks(ctx, index, entry):
    """The frames the check reads from box `index`'s saved render: only the frames the movie plays."""
    carried = entry.get("context_frames", 0)
    return check_frames.picks(ctx.raw[index].get("source"), carried + store.played_frames(entry), carried)


def _drift(ctx, index, frames, firsts):
    """Box `index`'s drift against its scene's first box, {"box", "words", "texture"}; None when it starts its scene
    or that box has no render the check can read. `firsts` keeps each scene's first (colour, texture) for the job;
    "texture" is each band's ratio to it."""
    measured = check_frames.lab_mean(frames), check_frames.texture_mean(frames)
    start = check_frames.scene_start(ctx.timeline, index)
    if start == index:
        firsts[index] = measured
        return None
    if start not in firsts:
        firsts[start] = None
        entry = ctx.rendered.get(ctx.timeline.boxes[start].id)
        if entry is not None:
            picks = frame_picks(ctx, start, entry)
            try:
                first = check_frames.read(ctx.folder, entry, picks)
                firsts[start] = check_frames.lab_mean(first), check_frames.texture_mean(first)
            except ValueError:
                pass
    if firsts[start] is None:
        return None
    (lab, texture), (first_lab, first_texture) = measured, firsts[start]
    ratios = [round(float(value / base), 3) if base > 0 else None for value, base in zip(texture, first_texture)]
    return {"box": ctx.timeline.boxes[start].id, "words": check_frames.drift_words(lab, first_lab, texture, first_texture),
            "texture": ratios}


def _holds(ctx, index, entry):
    """checks.json holds of box `index`'s played frames, preceded by the box before's last played frame when this box
    continues it; None when a video can't be read. Frames are counted on the 24 fps Timeline clock: a video saved at
    another rate (frame interpolation) gives the frame shown at each of those moments."""
    def frames_of(item, wanted):
        video = item["video"]
        fps = video.get("fps") or rules.FPS
        at = {number: media.window_at_fps(number, 1, fps)[0] for number in wanted}
        found = media.read_frames(os.path.join(ctx.folder, video["file"]), sorted(set(at.values())))
        return [found[at[number]] for number in wanted]

    try:
        frames = frames_of(entry, list(range(store.played_frames(entry))))
        before = ctx.rendered.get(ctx.timeline.boxes[index - 1].id) if index else None
        joined = bool(entry.get("context_frames")) and before is not None
        if joined:
            frames = frames_of(before, [store.played_frames(before) - 1]) + frames
    except (ValueError, OSError, av.error.FFmpegError):
        return None
    return check_frames.hold_records(check_frames.holds(frames), joined)


async def _ask(job, messages, reply_format):
    """The Vision model's reply; raises ValueError with the provider's error."""
    ctx = job.ctx
    before = job.reached
    # a request on its way counts: the server may be loading the model for it
    job.reached = True
    try:
        return await llm.complete(ctx.url, ctx.vision_model, messages, key=job.key, reply_format=reply_format,
                                  thinking=ctx.thinking)
    except llm.ChatError as error:
        job.reached = before or error.reached
        raise ValueError(str(error)) from None


async def _check(job, tally):
    """Checks the job's boxes in Timeline order, saving each result as it finishes."""
    ctx = job.ctx
    ids = [box.id for box in ctx.timeline.boxes]
    firsts = {}
    for position, box_id in enumerate(ctx.boxes, 1):
        index = ids.index(box_id)
        what = "Checking" if ctx.vision_model else "Measuring drift for"
        job.report(f"{what} box {index + 1} ({position} of {len(ctx.boxes)})...")
        entry = ctx.rendered[box_id]
        picks = frame_picks(ctx, index, entry)
        try:
            frames = await asyncio.to_thread(check_frames.read, ctx.folder, entry, picks)
        except ValueError:
            job.notes.append(SKIPPED.format(number=index + 1))
            if check_frames.scene_start(ctx.timeline, index) == index:
                firsts[index] = None
            continue
        drift = await asyncio.to_thread(_drift, ctx, index, frames, firsts)
        held = await asyncio.to_thread(_holds, ctx, index, entry)
        problems = error = None
        if ctx.vision_model:
            before = ctx.rendered.get(ids[index - 1]) if index else None
            previous = os.path.join(ctx.folder, before["stem"] + "_last.png") if before else None
            messages, reply_format, allowed, shots = await asyncio.to_thread(request, ctx, index, picks, frames, previous)
            reply = await _ask(job, messages, reply_format)
            try:
                problems = parse(reply, allowed, shots)
            except ValueError:
                error = UNREADABLE
        box_checks.save(ctx.folder, box_id, box_checks.record(entry, ctx.vision_model, problems, drift, error,
                                                                held))
        tally["checked"].append(box_id)
        tally["problems"] += bool(problems)
        tally["unreadable"] += error is not None
        tally["drifted"] += bool(drift and drift["words"])
        tally["held"] += bool(held)
        job.updated(job)


async def run(jobs, job):
    """Runs check `job` of `jobs` as Jobs.run runs a Write: the linked settings first, a GPU turn when free_vram is
    on and the Vision model is on this PC, the boxes, then one unload. A cancelled or failed check keeps the results
    it finished."""
    watchdog = asyncio.get_running_loop().create_task(jobs.watch(job))
    shares_gpu = False
    tally = {"checked": [], "problems": 0, "unreadable": 0, "drifted": 0, "held": 0}
    try:
        if job.ctx.links:
            job.ctx = settle(job.ctx, await story_inputs.run(jobs.comfy, job))
        ctx = job.ctx
        if ctx.vision_model:
            job.key = story_keys.key_for(ctx.url)
            shares_gpu = ctx.free_vram and await asyncio.to_thread(story_vram.on_this_pc, ctx.url)
        if shares_gpu:
            job.turn = await story_vram.take_turn(jobs.comfy, job.id, job.report)
        await _check(job, tally)
        vision = bool(ctx.vision_model)
        outcome = {"state": "done", "progress": summary(tally, vision), "result": dict(tally, vision=vision)}
    except asyncio.CancelledError:
        # the check is over, but the Vision model must still be unloaded
        asyncio.current_task().uncancel()
        outcome = {"state": "failed", "error": ENDED} if job.stopped else {"state": "cancelled", "progress": CANCELLED}
    except ValueError as error:
        message = DROPPED if str(error) == story_vram.DROPPED else llm.scrub(str(error), job.key)
        outcome = {"state": "failed", "error": message}
        logging.warning("H3 Story check: %s", message)
    except Exception:
        logging.error("H3 Story check failed.\n%s", llm.scrub(traceback.format_exc(), job.key))
        outcome = {"state": "failed", "error": FAILED}
    finally:
        watchdog.cancel()
    try:
        if shares_gpu and job.reached:
            job.releasing = True
            job.report("Unloading the Vision model...")
            job.vram = await story_vram.unload(job.ctx.url, job.ctx.vision_model, job.key)
    finally:
        story_vram.end_turn(jobs.comfy, job.id)
        for name, value in outcome.items():
            setattr(job, name, value)
        job.ended = time.monotonic()
        job.updated(job)
