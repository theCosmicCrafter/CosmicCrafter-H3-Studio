"""H3 Timeline: renders the next or selected box, carrying continuity from its saved neighbors."""

import datetime
import hashlib
import json
import os

from comfy_api.latest import io
from comfy_execution.graph_utils import ExecutionBlocker

from . import conditioning, latents, store, timing, shot_preview, refmods, audio_tracks, visual_memory
from . import box_checks, bridges, dialogue, studio_pictures, voice_clips, reference_replacements, replacement_candidates
from . import partial_video, replacement, regeneration, layers, stacks, track_output, tracks
from . import nodes as continuity
from . import timeline as rules
from .story_node import StoryType
from .still_nodes import StillRecipeType

IMAGE_SLOTS = rules.IMAGE_SLOTS
AUDIO_SLOTS = [f"audio{i}" for i in range(1, rules.MAX_REF_AUDIOS + 1)]
EMPTY_TIMELINE = '{"version": 1, "prompt": "", "boxes": []}'
FULL_VIDEO_CRF = 16
MAX_RESOLUTION = 16384


class MediaHashes:
    """SHA-1 of the references and keyframes a box uses; each input is hashed once per run."""

    def __init__(self, images, audios):
        self.images, self.audios, self.digests = images, audios, {}

    def digest(self, name):
        if name not in self.digests:
            digest = hashlib.sha1(name.encode("utf-8"))
            if name in self.images:
                data = self.images[name] if name.startswith('video') else self.images[name][:1]
            else:
                audio = self.audios[name]
                digest.update(str(int(audio["sample_rate"])).encode("utf-8"))
                data = audio["waveform"]
            digest.update(str(tuple(data.shape)).encode("utf-8"))
            # Avoid a second full-video copy while hashing every frame in presentation order.
            for chunk in data if name.startswith('video') else (data,):
                chunk = chunk.detach().float().contiguous().cpu()
                digest.update(chunk.numpy().tobytes())
            self.digests[name] = digest.hexdigest()
        return self.digests[name]

    def of(self, slots, keyframes=True):
        def pick(names):
            return [[name, self.digest(name)] for name in names if name]

        value = {"references": pick(slots.image_inputs), "audios": pick(slots.audio_inputs)}
        if slots.video_inputs:
            value.update(videos=pick(slots.video_inputs), video_audios=pick(slots.video_audio_inputs))
        if keyframes:
            value.update(first=pick([slots.first]), last=pick([slots.last]))
        if slots.refmods:
            value["refmods"] = [{key: ref.get(key) for key in ("slot", "name", "member", "kind", "strength", "stamp")}
                                for ref in slots.refmods]
        return hashlib.sha1(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()


def _view(name, filename, version):
    return {"filename": filename, "subfolder": f"h3_sequences/{name}", "type": "output", "v": version}


def replacement_states(folder, parsed, manifest, done, known):
    """(each replacement's State, or None while context_frames is unknown; the candidates the full video plays;
    why the full video can't be checked, or "")."""
    if not parsed.replacements:
        return [], [], ""
    context = known.get("context_frames")
    if context is None:
        note = ("Full video not rebuilt: the node's context_frames is unknown, so the selected replacements can't be "
                "checked." if any(item.get("selected") for item in parsed.replacements) else "")
        return None, [], note
    found = replacement_candidates.states(folder, parsed, manifest, done, known, context)
    return found, list(replacement_candidates.active(found).values()), ""


def selections(folder, parsed, manifest, by_index, is_done, known):
    """{box id, candidate} of each selected candidate the full video plays now, for H3 Save Segment to check again."""
    done = {i for i in range(len(parsed.boxes)) if i + 1 in by_index and is_done(i, by_index[i + 1])}
    _, replaced, _ = replacement_states(folder, parsed, manifest, done, known)
    return [{"box": entry["box"], "candidate": entry["candidate"]} for entry in replaced]


def video_clock(parsed, ordered):
    """Where the full video's (or the video so far's) frames sit on the Timeline, for the Studio's playhead:
    [[first video frame, frames, first Timeline frame, 1 when the Timeline advances with it or 0 while a bridge
    inserts time]] for each of `ordered`'s parts (nodes.ordered_parts), on the 24 fps clock."""
    starts, position = {}, 0
    for index, box in enumerate(parsed.boxes):
        starts[box.id] = position
        position += rules.played_frames(parsed, index)
    clock, video = [], 0
    for entry, first, count, inserted in ordered:
        if "box" not in entry:  # a saved segment names its box in its record; bridges and candidates at the top
            at, moves = starts.get((entry.get("timeline") or {}).get("box"), 0) + first, 1
        elif inserted:
            at, moves = starts.get(entry.get("box"), 0), 0
        else:
            at, moves = starts.get(entry.get("box"), 0) - (entry.get("timeline") or {}).get("left", 0), 1
        clock.append([video, count, at, moves])
        video += count
    return clock


def _clock(parsed, joined, bridges_played, replaced):
    try:
        return video_clock(parsed, continuity.ordered_parts(joined, bridges_played, replaced))
    except (ValueError, KeyError):
        return None


def video_so_far(name, folder, parsed, manifest, playable, spliced, replaced, soundtrack, managed_owner=None,
                 restack=None):
    """The video so far: the boxes from the first up to the first one without a take, with their bridges and selected
    replacements, and the marked soundtrack (or their own audio), so timing can be checked before every box renders.
    A stacked clip plays the stack of the videos with takes; with every box rendered, it plays until the other
    videos are too. `manifest` holds the stacks in place (stacks.substitute) and `restack` rechecks them.
    Returns ({"record", "boxes", "clock"} or None, building, why it could not be built or "")."""
    count = next((i for i in range(len(parsed.boxes)) if i not in playable), len(parsed.boxes))
    waiting = " ".join(stacks.waiting(folder, parsed, manifest, count)) if parsed.layers else ""
    if count < 1 or (count == len(parsed.boxes) and not waiting) or soundtrack is None:
        return None, False, ""
    indices = {box.id: index for index, box in enumerate(parsed.boxes)}
    joined = {**manifest, "segments": [entry for entry in store.placed(manifest, count)]}
    if len(joined["segments"]) != count or not all(entry.get("video") for entry in joined["segments"]):
        return None, False, ""
    inside = [entry for entry in spliced if indices.get(entry.get("box"), count) < count]
    kept = [entry for entry in replaced if indices.get(entry.get("box"), count) < count]
    try:
        sources = audio_tracks.soundtrack_sources(soundtrack)
    except ValueError:
        return None, False, ""
    record = store.current_full_video(folder, joined, [*inside, *kept], sources, key="preview_video")
    note, building = "", False
    if record is None:
        try:
            note = continuity.rebuild_full_video(folder, name, joined, FULL_VIDEO_CRF, inside, soundtrack,
                                                 managed_owner=managed_owner, replaced=kept, background=True,
                                                 kind="preview", restack=restack)
        except (OSError, ValueError) as error:
            note = f"Video so far could not be saved: {error}"
        building = continuity.full_video_state(folder, "preview")["building"]
        record = store.current_full_video(folder, joined, [*inside, *kept], sources, key="preview_video")
        if building or note == continuity.BUILDING:
            note = ""
        else:
            note = note.replace("Full video", "Video so far", 1)
    if record is None and (building or note == ""):
        # While the next one builds, the last one keeps playing, so the Studio can swap it in at the same moment.
        earlier = manifest.get("preview_video") or {}
        file, shown = earlier.get("file"), min(int(earlier.get("boxes") or 0), count)
        if shown and file == os.path.basename(file) and os.path.isfile(os.path.join(folder, file)):
            older = {**manifest, "segments": store.placed(manifest, shown)}
            within = [entry for entry in inside if indices.get(entry.get("box"), shown) < shown]
            replacing = [entry for entry in kept if indices.get(entry.get("box"), shown) < shown]
            return {"record": earlier, "boxes": shown, "clock": _clock(parsed, older, within, replacing)}, True, waiting
    if record is None:
        return None, building, note
    return {"record": record, "boxes": count, "clock": _clock(parsed, joined, inside, kept)}, building, waiting


def _status(name, folder, parsed, manifest, is_done, reasons=None, materialize=False, known=None, managed_owner=None):
    """`known` holds the node settings a bridge compares, None where they are unknown."""
    with continuity.SEQUENCE_LOCK:
        segments = manifest["segments"]
        count = len(parsed.boxes)
        placed = store.placed(manifest, count)
        done = {entry["index"] - 1 for entry in placed if is_done(entry["index"] - 1, entry)}
        # A box with a saved take keeps it in the Timeline and the full video even when it is outdated; Render only
        # renders the boxes that have none.
        kept = {entry["index"] - 1 for entry in placed if store.has_segment_latents(folder, entry)} - done
        next_index = next((i for i in rules.render_order(parsed) if i not in done and i not in kept), None)
        known = known or {}
        keys = bridges.splice(parsed, known)
        spliced = bridges.spliced(folder, manifest, keys) if keys else []
        found_replacements, replaced, unchecked = replacement_states(folder, parsed, manifest, done, known)

        def thumb(entry):
            filename = entry["stem"] + "_last.png"
            if not os.path.exists(os.path.join(folder, filename)):
                return None
            return _view(name, filename, entry.get("created", ""))

        # A stacked clip plays its stack; one is built only by a materializing status, from the takes there are.
        view, restack, waiting = manifest, None, []
        if parsed.layers:
            restack = stacks.restacker(parsed, count, partial=True)
            view, waiting = stacks.substitute(folder, parsed, manifest, count, FULL_VIDEO_CRF, partial=True,
                                              make=materialize)
        complete = bool(count) and len(placed) == count and next_index is None
        track_mode=parsed.tracks is not None
        current = complete and not waiting and not track_mode
        joined = {**view, "segments": store.placed(view, count)}
        full_video = None
        building = False
        export_error = ""
        try:
            soundtrack = audio_tracks.marked(parsed, manifest.get('reference_audio'))
        except ValueError as error:
            export_error = str(error)
            soundtrack = None
        if unchecked and not export_error:
            export_error = unchecked
        if complete and waiting and not export_error:
            export_error = " ".join(waiting)
        if current and materialize and not unchecked:
            from .timeline_api.service import authorize_sequence
            authorize_sequence(name, managed_owner, "full_video")

            def saved_full_video():
                try:
                    sources = audio_tracks.soundtrack_sources(soundtrack)
                except ValueError:
                    return None
                return store.current_full_video(folder, joined, [*spliced, *replaced], sources)

            record = saved_full_video() if soundtrack is not None else None
            if record is None and soundtrack is not None:
                # Built on its own thread: a status request never waits for an encode of every box.
                try:
                    note = continuity.rebuild_full_video(folder, name, joined, FULL_VIDEO_CRF, spliced, soundtrack,
                                                         managed_owner=managed_owner, replaced=replaced, background=True,
                                                         restack=restack)
                except (OSError, ValueError) as error:
                    note = f"Full video could not be saved: {error}"
                building = continuity.full_video_state(folder)["building"]
                if not building and note != continuity.BUILDING:
                    export_error = note
                record = saved_full_video()
            if record:
                full_video = _view(name, record["file"], record["sources"])
        partial = None
        if materialize and not track_mode and not current and parsed.video_slices and manifest.get("source") and soundtrack is not None:
            from .timeline_api.service import authorize_sequence
            authorize_sequence(name, managed_owner, "full_video")
            try:
                partial, note = partial_video.build(folder, name, parsed, manifest, done, soundtrack, FULL_VIDEO_CRF)
            except (OSError, ValueError, RuntimeError) as error:
                note = f"Partial video could not be saved: {error}"
            export_error = export_error or note
        so_far, so_far_building, so_far_note = None, False, ""
        if materialize and not track_mode and not current and not partial and not unchecked:
            from .timeline_api.service import authorize_sequence
            authorize_sequence(name, managed_owner, "full_video")
            so_far, so_far_building, so_far_note = video_so_far(name, folder, parsed, view, done | kept, spliced,
                                                                replaced, soundtrack, managed_owner, restack)
        status = rules.status_payload(name, parsed, segments, next_index, thumb, full_video,
                                      store.sequence_seconds(joined, spliced), done, kept)
        if building and full_video is None:
            status["full_video_building"] = True
        if export_error and full_video is None:
            status["export_error"] = export_error
        if full_video is not None:
            clock = _clock(parsed, joined, spliced, replaced)
            if clock is not None:
                status["full_video_clock"] = clock
        if so_far:
            status["preview_video"] = {"file": _view(name, so_far["record"]["file"], so_far["record"]["sources"]),
                                       "boxes": so_far["boxes"], "total": count, "clock": so_far["clock"]}
        if so_far_building:
            status["preview_video_building"] = True
        if so_far_note:
            status["preview_error"] = so_far_note
        if partial:
            status["partial_video"] = {"file": _view(name, partial["file"], partial["sources"]),
                                       "rendered": partial["rendered"], "boxes": partial["boxes"]}
            if parsed.all_bridges:
                status["partial_video"]["note"] = "Bridges and replacements are left out."
        if track_mode:
            if materialize:
                from .timeline_api.service import authorize_sequence
                authorize_sequence(name,managed_owner,'full_video')
            mode='full' if complete and not waiting else ('partial' if parsed.video_slices else 'so_far')
            record,building,note=track_output.ensure(folder,name,parsed,manifest,FULL_VIDEO_CRF,mode,materialize)
            spans=tracks.output_spans(tracks.document(parsed))
            status['seconds']=(spans[-1]['outputEnd'] if spans else 0)/24
            if record:
                if mode=='full':
                    status['full_video']=_view(name,record['file'],record['sources']);status['full_video_clock']=record['clock']
                elif mode=='partial':
                    status['partial_video']=dict(file=_view(name,record['file'],record['sources']),rendered=len(done|kept),boxes=count,note=note,clock=record['clock'])
                else:
                    status['preview_video']=dict(file=_view(name,record['file'],record['sources']),boxes=len(done|kept),total=count,clock=record['clock'])
            if building: status['full_video_building' if mode=='full' else 'preview_video_building']=True
            if note: status['export_error' if mode=='full' else 'preview_error']=note
        if parsed.layers:
            found_layers = layers.states(folder, parsed, manifest, done | kept, known, known.get("context_frames"),
                                         next_index)
            for state in found_layers:
                item = {"id": state.layer["id"], "status": state.status}
                if state.note:
                    item["reason"] = state.note
                video = (state.entry or {}).get("video")
                if video:
                    item["video"] = {"file": _view(name, video["file"], state.entry.get("created", "")),
                                     "frames": video["frames"], "fps": video["fps"]}
                status["boxes"][state.index].setdefault("videos", []).append(item)
            status["done_layers"] = [state.layer["id"] for state in found_layers if state.status == "done"]
            status["layers_remaining"] = sum(state.entry is None for state in found_layers)
            upcoming = next((state for state in found_layers if state.status == "next"), None)
            if upcoming is not None:
                status["message"] = (f"Clip {upcoming.index + 1}'s video "
                                     f"{layers.label(parsed, upcoming.index, upcoming.layer['id'])} is next.")
        if parsed.all_bridges:
            items = {}
            found = bridges.states(folder, parsed, manifest, done, known)
            items.update((state.bridge["before"], _bridge_item(name, state)) for state in found)
            upcoming = next((state for state in found if state.status == "next"), None)
            if upcoming is not None:
                status["message"] += f" The bridge before box {upcoming.index + 1} is next."
            elif found_replacements:
                upcoming = next((state for state in found_replacements if state.status == "next"), None)
                if upcoming is not None:
                    status["message"] += f" The replacement candidate before box {upcoming.index + 1} is next."
            if found_replacements is None:
                items.update((bridge["before"], {"box": bridge["before"], "mode": "replace", "status": "waiting",
                                                 "note": "the node's context_frames is unknown, so the region can't "
                                                         "be planned"}) for bridge in parsed.replacements)
            else:
                current_takes = replacement_candidates.takes(folder, parsed, manifest)
                items.update((state.bridge["before"], replacement_candidates.item(
                    state, parsed, known["context_frames"], lambda file, version: _view(name, file, version),
                    current_takes)) for state in found_replacements)
            status["bridges"] = [items[bridge["before"]] for bridge in parsed.all_bridges]
        if parsed.dialogue is not None:
            status["dialogue"] = {"cues": dialogue.summary(parsed)}
        status["timing_conflicts"] = dialogue.lock_conflicts(parsed)
        if replacement.UNAVAILABLE:
            status["replacement_unavailable"] = replacement.UNAVAILABLE
        context = known.get("context_frames")
        checks = box_checks.load(folder)
        placed = {entry["index"]: entry for entry in store.placed(manifest, len(parsed.boxes))}
        shown = {entry["index"]: entry for entry in joined["segments"] if "stack" in entry}
        for index, (item, box) in enumerate(zip(status["boxes"], parsed.boxes)):
            entry = placed.get(index + 1)
            if entry and entry.get("video"):
                video = entry["video"]
                item["video"] = {"file": _view(name, video["file"], entry.get("created", "")),
                                 "frames": video["frames"], "fps": video["fps"]}
            stack = shown.get(index + 1)
            if stack is not None:
                item["stack"] = {"file": _view(name, stack["video"]["file"], stack["created"]),
                                 "frames": stack["video"]["frames"], "fps": stack["video"]["fps"]}
            check = box_checks.status(checks.get(box.id), entry)
            if check is not None:
                item["check"] = check
            if reasons and index in reasons:
                item["reason"] = reasons[index]
            if parsed.dialogue is not None and context is not None:
                try:
                    problem = dialogue.box_problem(parsed, index, context, rules.assemble_prompt(parsed, index))
                except ValueError as error:
                    problem = str(error).removeprefix("H3 Timeline: ")
                if problem:
                    item["dialogue_problem"] = problem
        return status


def _bridge_item(name, state):
    item = {"box": state.bridge["before"], "mode": "insert", "status": state.status}
    if state.note:
        item["note"] = state.note
    video = (state.entry or {}).get("video")
    if video:
        item["video"] = {"file": _view(name, video["file"], state.entry.get("created", "")),
                         "frames": video["frames"], "fps": video["fps"]}
    return item


def slice_videos(images, audios, slots, start, count, label):
    """`images` and `audios` with each slot in `slots` (and its same-numbered soundtrack) cut to frames
    start..start + count at 24 fps."""
    images, audios = dict(images), dict(audios)
    for slot in slots:
        if slot not in images:
            continue
        frames = images[slot]
        if frames.shape[0] < start + count:
            raise ValueError(f"H3 Timeline: {slot} has {frames.shape[0]} frames, but {label} needs frames {start} to "
                             f"{start + count - 1} of it; connect a longer video or remove {slot} from video_slices")
        images[slot] = frames[start:start + count]
        sound = audios.get(slot.replace("video", "video_audio"))
        if sound is not None:
            rate = sound["sample_rate"]
            first, last = timing.sample_at_frame(start, rate), timing.sample_at_frame(start + count, rate)
            audios[slot.replace("video", "video_audio")] = {**sound, "waveform": sound["waveform"][..., first:last]}
    return images, audios


def box_media(parsed, index, context, images, audios, loaded, voices):
    """(images, audios) box `index` of `parsed` receives: the connected ones with its Timeline audio, voices, Studio
    pictures, sliced videos and appearance plates."""
    box_audios = audio_tracks.for_box(parsed, index, context, audios)
    if parsed.voice_clips:
        box_audios.update(voice_clips.load(parsed, index, voices))
    box_images = {**images, **studio_pictures.load(parsed, index, loaded)} if parsed.pictures else images
    if parsed.video_slices:
        box_images, box_audios = slice_videos(box_images, box_audios, parsed.video_slices,
                                              *rules.video_window(parsed, index, context), f"box {index + 1}")
    return shot_preview.plate_images(parsed, index, box_images, context=context), box_audios


def layers_taken(folder, parsed, manifest, but=None):
    """Whether every layer of `parsed` other than `but` has a saved take."""
    return all(layer_id == but or ((entry := layers.saved(manifest, layer_id)) is not None
                                   and store.has_segment_latents(folder, entry)) for layer_id in layers.ids(parsed))


def read_request(body):
    """(parsed Timeline, sequence folder, known settings, context frames or None) from a status-style request."""
    parsed = rules.parse(body.get("timeline") or EMPTY_TIMELINE)
    reference_replacements.refmods(parsed)
    refmods.resolve(parsed)
    folder = store.sequence_dir(continuity.sequences_root(), body.get("name") or "")
    known = body.get("settings") or {}
    context = known.get("context_frames")
    return parsed, folder, known, None if context in (None, "") else int(context)


def saved_manifest(folder, parsed, persist=False):
    """The sequence's manifest with every saved segment numbered by its box's place in `parsed` (store.align), so a
    box that moved keeps its take. With `persist`, a changed numbering is written back."""
    with continuity.SEQUENCE_LOCK:
        manifest = store.load_manifest(folder)
        if store.align(manifest, [box.id for box in parsed.boxes]) and persist and os.path.isdir(folder):
            store.write_manifest(folder, manifest)
        return manifest


def box_problem(parsed, index, entry, folder, entries, known, context, is_done, files=None):
    """Why saved box `entry` isn't box `index` of `parsed` now, as (kind, sentence), or None. The kinds are
    "context", "memory", "files", "sources", "layout", "settings" and "remembered", in the order they are checked.
    The latent is looked for in `files`, or in `folder`."""
    settings = rules.box_settings(rules.is_fresh(parsed, index), rules.box_slots(parsed, index, context if context is not None else 39).mode,
                                  known.get("width"), known.get("height"), context,
                                  known.get("carry_audio"), known.get("ref_image_size"),
                                  audio_context_frames=known.get('audio_context_frames', 0))
    record = entry.get("timeline") or {}
    if context is None and (record.get("text_chain") or (parsed.timed_text and parsed.timed_text["enabled"])):
        return "context", "Current context_frames is unresolved; timed text continuity cannot be verified."
    layout = rules.layout_key(parsed, index, context if context is not None else 39)
    saved = record.get("memories", [])
    try:
        memories = visual_memory.records(parsed, index, folder, entries, is_done, known.get("width"), known.get("height"))
    except ValueError as error:
        reason = str(error).removeprefix("H3 Timeline: ")
        return "memory", reason[:1].upper() + reason[1:] + "."
    if not store.has_segment_latents(files or folder, entry):
        return "files", "Its saved latents are missing."
    if ([[item["box"], item["frame"], item["label"], item.get("tokens", 2), item.get("frames"),
          item.get("new_scene", False)] for item in saved]
            != [[item["box"], item["frame"], item["label"], item.get("tokens", 2), item.get("frames"),
                 item.get("new_scene", False)] for item in memories]):
        return "sources", "Its visual memory sources changed."
    if record.get("layout") != layout:
        return "layout", "Its prompt or box settings changed since it was rendered."
    if not rules.segment_matches(entry, layout, settings):
        return "settings", "The node's width, height, context, audio or reference size changed since it was rendered."
    if saved != memories:
        source = next(item["index"] for old, item in zip(saved, memories) if old != item)
        return "remembered", f"Box {source}, which it remembers, was rendered again."
    return None


def status_test(parsed, folder, entries, known, context):
    """(is_done(index, entry), reasons): the status's test for a saved box, kept per index, and why each isn't done."""
    checked, reasons = {}, {}

    def is_done(index, entry):
        if index not in checked:
            problem = box_problem(parsed, index, entry, folder, entries, known, context, is_done)
            if problem:
                reasons[index] = problem[1]
            checked[index] = problem is None
        return checked[index]
    return is_done, reasons


def request_status(body, *, materialize=True, managed_owner=None):
    """Status for the editor from {"name", "timeline", "settings"}. Settings it could not read are None
    and not compared; the references are never compared."""
    if not isinstance(body, dict):
        return {"ok": False, "error": "H3 Timeline: the status request must be a JSON object"}
    with continuity.SEQUENCE_LOCK:
        try:
            if materialize:
                from .timeline_api.service import authorize_sequence
                authorize_sequence(body.get("name"), managed_owner, "full_video")
            parsed, folder, known, context = read_request(body)
            name = os.path.basename(folder)
            manifest = saved_manifest(folder, parsed, persist=materialize)
            entries = {entry["index"]: entry for entry in manifest["segments"]}
            is_done, reasons = status_test(parsed, folder, entries, known, context)
            status = _status(name, folder, parsed, manifest, is_done, reasons, materialize=materialize, managed_owner=managed_owner,
                             known=bridges.settings(known.get("width"), known.get("height"), context,
                                                    known.get("carry_audio"), audio_context_frames=known.get('audio_context_frames', 0)))
            if parsed.timed_text is not None:
                for index, item in enumerate(status["boxes"]):
                    item.update(text_window=None, effective_prompt=None)
                    if context is None:
                        item["text_note"] = "Current context_frames is unresolved; effective timed text cannot be projected."
                        continue
                    try:
                        window = rules.text_window(parsed, index, context)
                        slots = rules.box_slots(parsed, index, context)
                        prompt = rules.rewrite(rules.assemble_prompt(parsed, index), slots.tags)
                        item.update(text_window=window,
                                    effective_prompt=rules.timed_prompt(parsed, index, context, prompt, slots.mode, window))
                    except ValueError as error:
                        item["text_note"] = str(error)
            return status
        except (AttributeError, OverflowError, TypeError, ValueError, OSError) as error:
            return {"ok": False, "error": str(error)}


def describe(plan, count, saved, preserve_following=False):
    """Info text for the box about to render; `saved` is the number of saved segments."""
    n = plan.index + 1
    slots = plan.slots
    mode = "FLF2VA + RefMods" if plan.box.flf_refmods and slots.mode == "flf2va" else slots.mode.upper()
    parts = [f"Box {n} of {count} (segment {n}): {mode}."]
    if plan.carried:
        parts.append(f"{plan.frames} new frames ({timing.seconds(plan.frames):.2f} s) after {plan.carried} carried "
                     f"from box {n - 1}, {plan.generated} frames generated.")
    else:
        parts.append(f"{'Cut: no frames' if plan.index else 'Nothing'} carried; {plan.frames} frames "
                     f"({timing.seconds(plan.frames):.2f} s).")
    if slots.tags:
        parts.append(", ".join(f"{tag} = {name}" for name, tag in slots.tags.items()) + ".")
    if slots.first:
        parts.append(f"First frame {slots.first}.")
    if slots.last:
        parts.append(f"Last frame {slots.last}.")
    parts.append(f"Seed {plan.box.seed}.")
    if saved >= n:
        parts.append(f"Saving it moves {f'segments {n}-{saved}' if saved > n and not preserve_following else f'segment {n}'} to takes/.")
    return " ".join(parts + plan.notes)


class H3C_Timeline(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="H3C_Timeline",
            hidden=[io.Hidden.extra_pnginfo],
            display_name="H3 Timeline",
            category=continuity.CATEGORY,
            description="Draw the video as boxes, one H3 generation each, and mention the connected references in "
                        "the prompts as @image1, @video1, @video_audio1 or @audio1. Every queued run renders the next box that needs it, "
                        "or use the selected box's Generate/Regenerate button to render it alone. Saved neighbors "
                        "anchor its beginning and ending. Takes the place of H3 Sequence, the H3 Image to Video or "
                        "Reference to Video node and H3 Continue; connect segment to H3 Save Segment.",
            inputs=[
                io.Clip.Input("clip", optional=True),
                io.Vae.Input("vae", optional=True),
                io.Vae.Input("audio_vae", optional=True,
                             tooltip="Audio VAE for @audio references; without it they only label the prompt."),
                io.String.Input("name", default="timeline", tooltip="Folder under output/h3_sequences."),
                io.Int.Input("width", default=1344, min=32, max=MAX_RESOLUTION, step=32),
                io.Int.Input("height", default=768, min=32, max=MAX_RESOLUTION, step=32),
                io.Combo.Input("context_frames", options=list(timing.CONTEXT_OPTIONS), default="39",
                               tooltip="Frames each box carries from the box before it: 22 = 0.9 s, 39 = 1.6 s, 90 = 3.75 s, "
                                       "141 = 5.9 s."),
                io.Boolean.Input("carry_audio", default=True, tooltip="Also carry and freeze the matching audio."),
                io.Combo.Input("ref_image_size", options=["match", "max"], default="match",
                               tooltip="Reference image sizing, as in MiniMax H3 Reference to Video."),
                io.String.Input("timeline", default=EMPTY_TIMELINE, multiline=True,
                                tooltip="The boxes as JSON, written by the timeline editor."),
                io.Autogrow.Input("images", optional=True, template=io.Autogrow.TemplateNames(
                    io.Image.Input("image", lazy=True), names=IMAGE_SLOTS, min=0)),
                io.Autogrow.Input("audios", optional=True, template=io.Autogrow.TemplateNames(
                    io.Audio.Input("audio", lazy=True), names=AUDIO_SLOTS, min=0)),
                io.Conditioning.Input("negative", optional=True),
                StillRecipeType.Input("still_recipe", optional=True, raw_link=True, lazy=True,
                                      tooltip="Native still generator recipe; video rendering never evaluates it."),
                io.Image.Input("still_image", optional=True, raw_link=True, lazy=True,
                               tooltip="The IMAGE output of your own image workflow, wrapped in a subgraph whose inputs are "
                                       "named prompt and seed (optionally width, height, negative, and one "
                                       "IMAGE input per reference picture). The Studio generates stills through it; "
                                       "video rendering never evaluates it."),
                StoryType.Input("story", optional=True, lazy=True,
                                tooltip="From H3 Story, which writes this Timeline's prompts. Renders never wait "
                                        "for it."),
                io.Autogrow.Input("videos", optional=True, template=io.Autogrow.TemplateNames(
                    io.Image.Input("video", lazy=True, tooltip="Reference video frame batch at 24 fps."),
                    names=rules.VIDEO_SLOTS, min=0)),
                io.Autogrow.Input("video_audios", optional=True, template=io.Autogrow.TemplateNames(
                    io.Audio.Input("video_audio", lazy=True, tooltip="Optional soundtrack of the same-numbered video. "
                                   "Mention @video_audio1 to select video1's soundtrack; ordinary @audio inputs are standalone."),
                    names=rules.VIDEO_AUDIO_SLOTS, min=0)),
                io.Int.Input('audio_context_frames', optional=True, default=0, min=0,
                             tooltip='Incoming audio context in 24 fps frames; 0 follows video. Bounded to video context. Following-neighbour ending pins stay full length.'),
            ],
            outputs=[
                io.Conditioning.Output(display_name="positive"),
                io.Conditioning.Output(display_name="negative"),
                io.Latent.Output(display_name="latent"),
                continuity.SegmentType.Output(display_name="segment"),
                io.Int.Output(display_name="seed"),
                io.String.Output(display_name="prompt"),
                io.String.Output(display_name="info"),
            ],
        )

    @classmethod
    def fingerprint_inputs(cls, name, **kwargs):
        try:
            folder = store.sequence_dir(continuity.sequences_root(), name)
        except (AttributeError, ValueError):
            return float("nan")
        parsed = rules.parse(kwargs.get("timeline") or EMPTY_TIMELINE)
        reference_replacements.refmods(parsed)
        refmods.resolve(parsed)
        value = (store.manifest_fingerprint(folder), [ref.get("stamp") for ref in parsed.refmods])
        sources = {source + 1 for index in range(len(parsed.boxes)) for source, _, _ in rules.memory_sources(parsed, index)}
        if sources:
            entries = {entry["index"]: entry for entry in saved_manifest(folder, parsed)["segments"]}
            stamps = []
            for index in sorted(sources):
                entry = entries.get(index)
                if entry and store.has_segment_latents(folder, entry):
                    stamps.append((index, *store.latent_stamp(folder, entry)))
                else:
                    stamps.append((index, None))
            value += (stamps,)
        if parsed.audio_clips:
            value += (audio_tracks.fingerprint(parsed),)
        if parsed.pictures:
            value += (studio_pictures.fingerprint(parsed),)
        if parsed.reference_replacements:
            value += (reference_replacements.fingerprint(parsed),)
        return (*value, voice_clips.fingerprint(parsed)) if parsed.voice_clips else value

    @classmethod
    def check_lazy_status(cls, timeline="{}", images=None, audios=None, videos=None, video_audios=None, **kwargs):
        parsed = rules.parse(timeline)
        disabled = parsed.disabled_refs
        replacements = reference_replacements.effective(parsed)
        context = int(kwargs.get("context_frames", 39))
        slots = [rules.box_slots(parsed, index, context) for index in range(len(parsed.boxes))]
        used = {name for item in slots for name in (*item.references, *item.audios, item.first, item.last) if name}
        overridden = {name for index, box in enumerate(parsed.boxes)
                      for name, effective in ((box.first if rules.is_fresh(parsed, index) else "", slots[index].first),
                                              (box.last, slots[index].last)) if name and not effective}
        required = {reference_replacements.origin(slot, replacements).get('source') for slot in replacements
                    if not rules.reference_disabled(slot, disabled)}
        unused_endpoints = overridden - used - required
        # Empty autogrow groups arrive as ({}, group_name); populated groups map slots to (value, key).
        # Never request the Story or still recipe links, or disabled reference branches.
        return [key for pool in (images, audios, videos, video_audios) if isinstance(pool, dict)
                for slot, (value, key) in pool.items()
                if value is None and slot not in unused_endpoints and (slot in required or (slot not in replacements
                                      and not rules.reference_disabled(slot, disabled)))]

    @classmethod
    def execute(cls, clip=None, vae=None, name="h3_story", width=1024, height=576, context_frames=39, carry_audio=True, ref_image_size="match", timeline="{}",
                audio_vae=None, images=None, audios=None, negative=None, story=None, videos=None, video_audios=None, still_recipe=None, audio_context_frames=0, still_image=None) -> io.NodeOutput:
        from .timeline_api.service import authorize_sequence, sequence_owner
        owner_job = authorize_sequence(name, sequence_owner(cls), "conditioning")
        if clip is None or vae is None:
            raise ValueError("H3 Timeline video generation requires an H3 CLIP and VAE")
        parsed = rules.parse(timeline)
        reference_replacements.refmods(parsed)
        if not parsed.boxes:
            raise ValueError("H3 Timeline: the timeline has no boxes; draw one in the editor")
        context = int(context_frames)
        timing.effective_audio_context(context, carry_audio, audio_context_frames)
        images = {key: value for key, value in (images or {}).items() if value is not None}
        audios = {key: value for key, value in (audios or {}).items() if value is not None}
        images.update({key: value for key, value in (videos or {}).items()
                       if value is not None})
        audios.update({key: value for key, value in (video_audios or {}).items()
                       if value is not None})
        audios = audio_tracks.load_sources(parsed, audios)
        if audio_vae is None and any(rules.active_audio_clips(parsed, i) for i in range(len(parsed.boxes))):
            raise ValueError("H3 Timeline: connect an audio VAE to use Timeline audio clips as H3 references")
        if audio_vae is None and parsed.voice_clips:
            for index in range(len(parsed.boxes)):
                sent = voice_clips.used(parsed, index)
                if sent:
                    raise ValueError(f"H3 Timeline: box {index + 1} sends {voice_clips.title(parsed, sent[0]['slot'])}, "
                                     "so connect an audio VAE to Timeline")
        replaced = reference_replacements.effective(parsed)
        refmods.resolve(parsed, set(images) - replaced.keys(), set(audios) - replaced.keys())
        loaded = {}
        source_audios = audios
        images, audios = reference_replacements.media(parsed, images, audios, loaded)
        folder = store.sequence_dir(continuity.sequences_root(), name)
        name = os.path.basename(folder)
        manifest = saved_manifest(folder, parsed)
        recovery = None
        receipt = json.loads(timeline).get("rebuild_continuity")
        scheduled_next = (owner_job and parsed.render_box is not None and parsed.render_box < len(parsed.boxes)
                          and any(attempt["unit_id"] == "box:" + parsed.boxes[parsed.render_box].id
                                  and attempt["state"] == "pending" for attempt in owner_job["attempts"]))
        if parsed.render_box is not None and (receipt is not None or not scheduled_next):
            known = dict(width=width, height=height, context_frames=context, carry_audio=carry_audio,
                         ref_image_size=ref_image_size, audio_context_frames=audio_context_frames)
            box_id = parsed.boxes[parsed.render_box - 1].id
            with continuity.SEQUENCE_LOCK:
                check = (regeneration.validate(folder, parsed, known, box_id, receipt) if receipt is not None
                         else regeneration.inspect(folder, parsed, known, box_id))
            if check["needs_rebuild"]:
                if receipt is None:
                    raise ValueError(f"H3 Timeline: {check['reason']} Regenerate this clip in the Studio and "
                                     "confirm rebuilding the affected clips.")
                recovery = dict(timeline=json.loads(timeline), settings=known, box=box_id, receipt=receipt)
        elif parsed.render_box is None and receipt is not None:
            raise ValueError("H3 Timeline: continuity recovery requires a selected clip")
        with continuity.SEQUENCE_LOCK:
            records = manifest.get('reference_audio', {})
            if audio_tracks.snapshot_replacements(parsed, {**source_audios, **audios}, name,
                                                  records):
                manifest['reference_audio'] = records
                store.write_manifest(folder, manifest)
        effective_images = {}
        effective_audios = {}
        hashes = {}
        plans = {}
        checked = {}
        by_index = {entry["index"]: entry for entry in manifest["segments"]}
        voices = {}

        def media(target, index):
            return box_media(target, index, context, images, audios, loaded, voices)

        def refs(index):
            if index not in effective_images:
                effective_images[index], effective_audios[index] = media(parsed, index)
                hashes[index] = MediaHashes(effective_images[index], effective_audios[index])
            return effective_images[index]

        def plan(index):
            if index not in plans:
                plans[index] = rules.plan_box(parsed, index, context, carry_audio, width, height, ref_image_size,
                                              refs(index), effective_audios[index], audio_context_frames=audio_context_frames)
            return plans[index]

        def is_done(index, entry):
            if index in checked:
                return checked[index]
            try:
                box = plan(index)
                memories = visual_memory.records(parsed, index, folder, by_index, is_done, width, height)
            except ValueError:
                checked[index] = False
                return False
            checked[index] = (store.has_segment_latents(folder, entry)
                              and rules.segment_matches(entry, box.layout, box.settings, hashes[index].of(box.slots))
                              and (entry.get("timeline") or {}).get("memories", []) == memories)
            return checked[index]

        def references_match(index, entry):
            try:
                box = plan(index)
            except ValueError:
                return False
            record = entry.get("timeline") or {}
            if "references" in record:
                return record["references"] == hashes[index].of(box.slots, keyframes=False)
            return ((record.get("mode") == box.slots.mode and record.get("media") == hashes[index].of(box.slots))
                    or (record.get("mode") != "ref2va" and box.slots.mode != "ref2va"))

        # Render renders the boxes without a saved take; an outdated box is rendered again only when selected.
        next_index = (parsed.render_box - 1 if parsed.render_box is not None
                      else rules.next_box(len(parsed.boxes), by_index,
                                          lambda index, entry: store.has_segment_latents(folder, entry), order=rules.render_order(parsed)))
        known = bridges.settings(width, height, context, carry_audio, audio_context_frames=audio_context_frames)
        taken = {i for i in range(len(parsed.boxes)) if i + 1 in by_index and store.has_segment_latents(folder, by_index[i + 1])}
        # A clip's other videos render right after its main video, before the next box, bridges and replacements.
        if parsed.layers and parsed.render_box is None and parsed.render_bridge is None:
            box_known = dict(width=width, height=height, context_frames=context, carry_audio=carry_audio,
                             ref_image_size=ref_image_size, audio_context_frames=audio_context_frames)
            found = layers.states(folder, parsed, manifest, taken, box_known, context, next_index)
            if parsed.render_layer is not None:
                chosen = next(state for state in found if state.layer["id"] == parsed.render_layer)
                if chosen.status == "waiting":
                    raise ValueError(f"H3 Timeline: {chosen.note}")
            else:
                chosen = next((state for state in found if state.status == "next"), None)
            if chosen is not None:
                complete = (len(taken) == len(parsed.boxes)
                            and layers_taken(folder, parsed, manifest, but=chosen.layer["id"]))
                return cls.layer(chosen, parsed, name, folder, manifest, by_index, is_done, box_known, known, complete,
                                 media, clip, vae, audio_vae, negative)
        replacing = parsed.render_bridge in {item["before"] for item in parsed.replacements}
        if (parsed.render_bridge is not None and not replacing) or (next_index is None and parsed.bridges):
            done = {i for i in range(len(parsed.boxes)) if i + 1 in by_index and is_done(i, by_index[i + 1])}
            found = bridges.states(folder, parsed, manifest, done, known)
            if parsed.render_bridge is not None:
                chosen = next(state for state in found if state.bridge["before"] == parsed.render_bridge)
                if chosen.status in ("problem", "waiting"):
                    raise ValueError(f"H3 Timeline: {chosen.note}")
            else:
                chosen = next((state for state in found if state.status == "next"), None)
            if chosen is not None:
                complete = len(taken) == len(parsed.boxes) and layers_taken(folder, parsed, manifest)
                return cls.bridge(chosen, parsed, name, folder, manifest, by_index, is_done, known, complete,
                                  clip, vae, audio_vae, ref_image_size, negative)
        if replacing or (next_index is None and parsed.replacements):
            done = {i for i in range(len(parsed.boxes)) if i + 1 in by_index and is_done(i, by_index[i + 1])}
            found = replacement_candidates.states(folder, parsed, manifest, done, known, context)
            if replacing:
                chosen = next(state for state in found if state.bridge["before"] == parsed.render_bridge)
                if chosen.status in ("unavailable", "problem", "waiting", "review"):
                    raise ValueError(f"H3 Timeline: the replacement before box {chosen.index + 1}: {chosen.note}")
            else:
                chosen = next((state for state in found if state.status == "next"), None)
            if chosen is not None:
                return cls.replace(chosen, parsed, name, folder, manifest, by_index, is_done, known,
                                   clip, vae, audio_vae, ref_image_size, negative)
        if next_index is None:
            return cls.finish(name, folder, parsed, manifest, is_done, known)
        if parsed.video_slices and parsed.video_slices[0] in images:
            partial_video.keep_source(folder, name, parsed.video_slices[0], images, audios, width, height,
                                      MediaHashes(images, audios).digest)
        box = plan(next_index)
        conflict = rules.carry_conflict(parsed, next_index, context)
        if conflict:
            raise ValueError(f"H3 Timeline: {conflict}")
        previous_index = rules.previous_index(parsed,next_index)
        previous = by_index.get(previous_index+1) if previous_index is not None else None
        video = audio = None
        if not box.fresh:
            if (previous is None or not store.has_segment_latents(folder, previous)
                    or (previous.get("timeline") or {}).get("box") != parsed.boxes[previous_index].id):
                raise ValueError(f"H3 Timeline: render box {next_index} first, or enable Cut on box {next_index + 1}")
            if ((previous.get("timeline") or {}).get("guide_chain", "") != rules.guide_chain(parsed, previous_index, context)
                    or (rules.guide_chain(parsed, previous_index, context) and not is_done(previous_index, previous))):
                raise ValueError(f"H3 Timeline: preview guides changed; render box {next_index} first to rebuild continuity")
            if (previous.get("timeline") or {}).get("plate_chain", "") != rules.plate_chain(parsed, previous_index):
                raise ValueError(f"H3 Timeline: appearance plates changed; render box {next_index} first to rebuild continuity")
            if (previous.get("timeline") or {}).get("text_chain", "") != rules.text_chain(parsed, previous_index, context):
                raise ValueError(f"H3 Timeline: timed text changed; render box {next_index} first to rebuild continuity")
            if rules.memory_sources(parsed, previous_index) and not is_done(previous_index, previous):
                raise ValueError(f"H3 Timeline: visual memory changed; render box {next_index} first to rebuild continuity")
            if not references_match(previous_index, previous):
                raise ValueError(f"H3 Timeline: references changed; render box {next_index} first, "
                                 f"or enable Cut on box {next_index + 1}")
            video, audio = store.load_segment_latents(folder, previous)
        sequence = continuity.SequenceRef(name, folder, next_index + 1, previous, video, audio)
        memories = visual_memory.records(parsed, next_index, folder, by_index, is_done, width, height)
        memory_args = {}
        if video is not None and parsed.continuation_guide:
            memory_args['continuation_image'] = store.load_continuation_frame(folder, previous)
        if memories:
            memory_args["memories"] = visual_memory.load(folder, by_index, memories)
            memory_args["memory_frames"] = [item.get("frames") for item in memories]
            box.prompt = visual_memory.box_prompt(parsed, next_index, context, box, memories)
            sources = list(dict.fromkeys(str(item["index"]) for item in memories))
            views = "video references (full preceding video included)" if any(item.get("whole") for item in memories) else "earlier 5-frame views"
            box.notes.append(f"Visual memory: {len(memories)} {views} from box{'es' if len(sources) > 1 else ''} "
                             f"{', '.join(sources)}.")
        guides = rules.frame_guides(parsed, next_index, context)
        end = box.carried + box.frames - 1
        endpoint_files = {}
        for frame, file in guides:
            if frame == 0 and box.fresh:
                endpoint_files["first"] = file
            elif frame == end:
                endpoint_files["last"] = file
        if endpoint_files:
            memory_args["endpoint_images"] = {key: shot_preview.load_image(file) for key, file in endpoint_files.items()}
        positive, latent = conditioning.encode(box, clip, vae, audio_vae, width, height, ref_image_size,
                                               refs(next_index), effective_audios[next_index], **memory_args)
        internal_guides = [(frame, file) for frame, file in guides
                           if frame >= box.carried and frame != end and not (box.fresh and frame == 0)]
        positive = shot_preview.add_guides(positive, latent, vae, internal_guides)
        latent, positive, negative, segment, _ = continuity.prepare_segment(
            sequence, latent, context, carry_audio, positive, negative, node="H3 Timeline", audio_context_frames=audio_context_frames,
            noise_vae=vae if parsed.context_noise else None, audio_feather=parsed.audio_feather)
        segment.preserve_following = True
        segment.regeneration = recovery
        following_index = rules.following_index(parsed,next_index)
        following = by_index.get(following_index+1) if following_index is not None else None
        ending = 0
        if following is not None:
            same_box = (following.get("timeline") or {}).get("box") == parsed.boxes[following_index].id
            cut = rules.is_fresh(parsed, following_index)
            saved = by_index.get(next_index+1)
            references_changed = (saved is not None and (saved.get("timeline") or {}).get("box") == box.box.id
                                  and not references_match(next_index, saved))
            guides_changed = ((following.get("timeline") or {}).get("guide_chain", "")
                              != rules.guide_chain(parsed, following_index, context))
            guides_changed |= ((following.get("timeline") or {}).get("plate_chain", "")
                               != rules.plate_chain(parsed, following_index))
            compatible = (same_box and store.has_segment_latents(folder, following)
                          and following.get("latent_width") == width and following.get("latent_height") == height
                          and following.get("context_frames", 0) > 0)
            text_changed = ((following.get("timeline") or {}).get("text_chain", "")
                            != rules.text_chain(parsed, following_index, context))
            rebuilding_next = owner_job and any(
                attempt["unit_id"] == "box:" + parsed.boxes[following_index].id
                and attempt["state"] == "pending" for attempt in owner_job["attempts"])
            if recovery:
                box.notes.append("Affected clips will move to Takes only after this render saves successfully.")
            elif rebuilding_next and not cut:
                # The durable API plan owns this continuation's replacement.
                # Retain its old bytes as a take, but generate an unfrozen end.
                box.notes.append("Following continuation is scheduled for rebuilding by the project job.")
            elif text_changed and not cut:
                box.notes.append("Timed text changed; rebuild following continuations up to the next cut.")
            elif guides_changed and not cut:
                # Rebuild this end from the accepted guide, not the obsolete neighbor's frozen overlap.
                segment.preserve_following = True
            elif same_box and not cut and (references_changed or not references_match(following_index, following)):
                box.notes.append("References changed; the boxes that continue this one are outdated until you "
                                 "regenerate them.")
            elif compatible and not cut:
                ending = following["context_frames"]
                next_video, next_audio = store.load_segment_latents(folder, following)
                latent, segment.ending_video, segment.ending_audio = latents.build_ending(
                    latent, next_video, next_audio, ending, carry_audio, segment.context_frames)
                end_frame = segment.frames - ending
                positive, _ = latents.drop_guides_before(positive, 0, end_frame)
                negative, _ = latents.drop_guides_before(negative, 0, end_frame)
                segment.preserve_following = True
            elif same_box and cut:
                segment.preserve_following = True
            elif parsed.render_box is not None and same_box and not cut:
                raise ValueError(f"H3 Timeline: box {next_index + 2} has no compatible saved overlap; "
                                 "render the remaining boxes to rebuild continuity")
        segment.box_order = [item.id for item in parsed.boxes]
        segment.restack = stacks.restacker(parsed, len(parsed.boxes)) if parsed.layers or parsed.tracks is not None else None
        segment.description = box.prompt
        segment.timeline = {"box": box.box.id, "layout": box.layout, "mode": box.slots.mode,
                            "settings": box.settings, "media": hashes[next_index].of(box.slots),
                            "references": hashes[next_index].of(box.slots, keyframes=False),
                            "guide_chain": rules.guide_chain(parsed, next_index, context), "seed": box.box.seed}
        if box.generated > box.frames + box.carried:
            segment.timeline["played"] = box.frames
        if rules.text_chain(parsed, next_index, context):
            segment.timeline["text_chain"] = rules.text_chain(parsed, next_index, context)
        # Saving the last box without a take starts the full video; outdated boxes play in it until regenerated.
        segment.timeline_complete = (recovery is None and all(i == next_index or i in taken for i in range(len(parsed.boxes)))
                                     and layers_taken(folder, parsed, manifest))
        if rules.plate_chain(parsed, next_index):
            segment.timeline["plate_chain"] = rules.plate_chain(parsed, next_index)
        if memories:
            segment.timeline["memories"] = memories
        if ending:
            segment.timeline["ending_context_frames"] = ending
        if parsed.bridges:
            segment.timeline["splice"] = bridges.splice(parsed, known)
        if parsed.replacements:
            segment.timeline["replace"] = selections(folder, parsed, manifest, by_index, is_done, known)
        attach_soundtrack(segment.timeline, parsed, manifest)
        saved = next_index + 1 if next_index + 1 in by_index else 0
        info = describe(box, len(parsed.boxes), saved, segment.preserve_following)
        if ending:
            info += f" Ending frozen to the first {ending} frames of box {next_index + 2}; later boxes are kept."
        status = _status(name, folder, parsed, manifest, is_done, known=known)
        return io.NodeOutput(positive, negative, latent, segment, box.box.seed, box.prompt, info,
                             ui={"h3c_timeline": [status]})

    @classmethod
    def layer(cls, state, parsed, name, folder, manifest, by_index, is_done, known, bridge_known, complete, media,
              clip, vae, audio_vae, negative):
        """Renders the video of `state` as a fresh generation of its clip's time, planned on the layer view."""
        index, item = state.index, state.layer
        width, height, context, carry_audio, ref_image_size, audio_context_frames = (known[key] for key in (
            "width", "height", "context_frames", "carry_audio", "ref_image_size", "audio_context_frames"))
        view = layers.view(parsed, index, item)
        images, audios = media(view, index)
        plan = layers.plan(parsed, index, item, context, carry_audio, width, height, ref_image_size, images, audios,
                           audio_context_frames=audio_context_frames)
        hashes = MediaHashes(images, audios)
        layer_entries = {entry["layer"]: entry for entry in manifest.get("layers", [])}
        memories = visual_memory.records(view, index, folder, by_index, is_done, width, height, layer_entries)
        memory_args = {}
        if memories:
            memory_args["memories"] = visual_memory.load(folder, by_index, memories, layer_entries)
            memory_args["memory_frames"] = [record.get("frames") for record in memories]
            plan.prompt = visual_memory.box_prompt(view, index, context, plan, memories)
        guides = rules.frame_guides(view, index, context)
        end = plan.frames - 1
        endpoint_files = {("first" if frame == 0 else "last"): file for frame, file in guides if frame in (0, end)}
        if endpoint_files:
            memory_args["endpoint_images"] = {key: shot_preview.load_image(file) for key, file in endpoint_files.items()}
        positive, latent = conditioning.encode(plan, clip, vae, audio_vae, width, height, ref_image_size, images, audios,
                                               **memory_args)
        positive = shot_preview.add_guides(positive, latent, vae, [(frame, file) for frame, file in guides
                                                                   if frame not in (0, end)])
        sequence = continuity.SequenceRef(name, folder, index + 1, None, None, None)
        latent, positive, negative, segment, _ = continuity.prepare_segment(
            sequence, latent, context, carry_audio, positive, negative, node="H3 Timeline",
            audio_context_frames=audio_context_frames, audio_feather=parsed.audio_feather)
        segment.preserve_following = True
        segment.box_order = [box.id for box in parsed.boxes]
        segment.restack = stacks.restacker(parsed, len(parsed.boxes))
        segment.description = plan.prompt
        segment.timeline = {"layer": item["id"], "box": parsed.boxes[index].id,
                            "layout": layers.layer_key(parsed, index, item, context), "mode": plan.slots.mode,
                            "settings": plan.settings, "media": hashes.of(plan.slots),
                            "references": hashes.of(plan.slots, keyframes=False), "seed": item["seed"],
                            "layer_ids": layers.ids(parsed)}
        if plan.generated > plan.frames:
            segment.timeline["played"] = plan.frames
        if memories:
            segment.timeline["memories"] = memories
        if parsed.bridges:
            segment.timeline["splice"] = bridges.splice(parsed, bridge_known)
        if parsed.replacements:
            segment.timeline["replace"] = selections(folder, parsed, manifest, by_index, is_done, bridge_known)
        attach_soundtrack(segment.timeline, parsed, manifest)
        segment.timeline_complete = complete
        label = layers.label(parsed, index, item["id"])
        info = (f"Clip {index + 1} video {label}: {plan.slots.mode.upper()}, a fresh generation of the clip's "
                f"{plan.frames} frames ({timing.seconds(plan.frames):.2f} s). Seed {item['seed']}.")
        if state.entry is not None:
            info += " Saving it moves its earlier take to takes/."
        info = " ".join([info, *plan.notes])
        status = _status(name, folder, parsed, manifest, is_done, known=bridge_known)
        return io.NodeOutput(positive, negative, latent, segment, item["seed"], plan.prompt, info,
                             ui={"h3c_timeline": [status]})

    @classmethod
    def bridge(cls, state, parsed, name, folder, manifest, by_index, is_done, known, complete,
               clip, vae, audio_vae, ref_image_size, negative):
        """Renders the bridge of `state` between the saved segments of its two boxes."""
        before, after = by_index[rules.previous_index(parsed,state.index)+1], by_index[state.index + 1]
        width, height, context, carry_audio = (known[key] for key in ("width", "height", "context_frames", "carry_audio"))
        audio_context_frames = known.get('audio_context_frames', 0)
        plan = bridges.plan(parsed, state.bridge, context, carry_audio, width, height, before, after,
                            audio_context_frames=audio_context_frames)
        positive, latent = conditioning.encode(plan, clip, vae, audio_vae, width, height, ref_image_size, {}, {})
        video, audio = store.load_segment_latents(folder, before)
        sequence = continuity.SequenceRef(name, folder, state.index + 1, before, video, audio)
        latent, positive, negative, segment, _ = continuity.prepare_segment(
            sequence, latent, plan.carried, carry_audio, positive, negative, node="H3 Timeline", audio_context_frames=audio_context_frames)
        frozen = plan.generated - plan.carried - plan.frames
        next_video, next_audio = store.load_segment_latents(folder, after)
        latent, segment.ending_video, segment.ending_audio = latents.build_ending(
            latent, next_video, next_audio, frozen, carry_audio, segment.context_frames)
        segment.preserve_following = True
        segment.box_order = [item.id for item in parsed.boxes]
        segment.restack = stacks.restacker(parsed, len(parsed.boxes)) if parsed.layers or parsed.tracks is not None else None
        segment.description = plan.prompt
        segment.timeline = {"bridge": state.bridge["before"], "layout": plan.layout, "settings": plan.settings,
                            "from": bridges.link(folder, before), "to": bridges.link(folder, after),
                            "played": plan.frames, "splice": bridges.splice(parsed, known), "seed": plan.box.seed}
        if parsed.replacements:
            segment.timeline["replace"] = selections(folder, parsed, manifest, by_index, is_done, known)
        attach_soundtrack(segment.timeline, parsed, manifest)
        segment.timeline_complete = complete
        n = state.index + 1
        info = (f"Bridge before box {n}: {plan.frames} new frames, from box {n - 1}'s last {plan.carried} frames "
                f"to box {n}'s first {frozen}. Seed {plan.box.seed}.")
        if state.entry is not None:
            info += " Saving it moves its earlier take to takes/."
        status = _status(name, folder, parsed, manifest, is_done, known=known)
        return io.NodeOutput(positive, negative, latent, segment, plan.box.seed, plan.prompt, info,
                             ui={"h3c_timeline": [status]})

    @classmethod
    def replace(cls, state, parsed, name, folder, manifest, by_index, is_done, known,
                clip, vae, audio_vae, ref_image_size, negative):
        """Renders a candidate for the reviewed replacement of `state` from the footage that survives around it."""
        before, after = by_index[rules.previous_index(parsed,state.index)+1], by_index[state.index + 1]
        width, height, context, carry_audio = (known[key] for key in ("width", "height", "context_frames", "carry_audio"))
        audio_context_frames = known.get('audio_context_frames', 0)
        plan = replacement_candidates.plan(parsed, state, width, height, context, carry_audio,
                                           audio_context_frames=audio_context_frames)
        positive, latent = conditioning.encode(plan, clip, vae, audio_vae, width, height, ref_image_size, {}, {})
        latent, positive, negative, segment = replacement_candidates.prepare(
            state, latent, positive, negative, (name, folder, state.index + 1, before),
            store.load_segment_latents(folder, before), store.load_segment_latents(folder, after), vae, carry_audio,
            audio_context_frames=audio_context_frames)
        shape, bridge = state.geometry, state.bridge
        segment.description = plan.prompt
        segment.timeline = {"replacement": bridge["before"], "region": state.region, "recipe": state.recipe,
                            "settings": plan.settings, "from": bridges.link(folder, before),
                            "to": bridges.link(folder, after), "left": shape.left, "right": shape.right,
                            "windows": [list(shape.left_window), list(shape.right_window)],
                            "played": shape.frames, "seed": bridge["seed"]}
        if parsed.bridges:
            segment.timeline["splice"] = bridges.splice(parsed, known)
        attach_soundtrack(segment.timeline, parsed, manifest)
        n = state.index + 1
        info = (f"Replacement candidate before box {n}: {shape.frames} frames in place of the last {shape.left} of box "
                f"{n - 1} and the first {shape.right} of box {n}, from box {n - 1}'s surviving {shape.context_frames} "
                f"frames to box {n}'s next {shape.ending_frames}. Seed {bridge['seed']}. It plays in the full video "
                "only once you select it.")
        status = _status(name, folder, parsed, manifest, is_done, known=known)
        return io.NodeOutput(positive, negative, latent, segment, bridge["seed"], plan.prompt, info,
                             ui={"h3c_timeline": [status]})

    @classmethod
    def finish(cls, name, folder, parsed, manifest, is_done, known=None):
        """Every box has a saved take: move bridges the Timeline no longer has to takes/, start the full video in the
        background and block the sampling nodes. Takes of boxes the Timeline no longer has stay where they are, so
        the box finds its take again when it comes back."""
        with continuity.SEQUENCE_LOCK:
            from .timeline_api.service import authorize_sequence, sequence_owner
            authorize_sequence(name, sequence_owner(cls), "conditioning")
            latest = store.load_manifest(folder)
            aligned = store.align(latest, [box.id for box in parsed.boxes])
            if latest["segments"] != manifest["segments"]:
                raise ValueError("H3 Timeline: saved boxes changed during completion; queue again to use their current versions")
            manifest = latest
            count = len(parsed.boxes)
            info = ("The box" if count == 1 else f"All {count} boxes") + f" of '{name}' {'is' if count == 1 else 'are'} rendered"
            now = datetime.datetime.now()
            moved = bridges.keep(folder, manifest, {bridge["before"] for bridge in parsed.bridges}, now)
            moved_layers = layers.keep(folder, manifest, set(layers.ids(parsed)), now)
            if moved or moved_layers or aligned:
                store.write_manifest(folder, manifest)
            if moved:
                info += f"; moved {moved} bridge{'s' if moved > 1 else ''} the Timeline no longer has to takes/"
            if moved_layers:
                info += f"; moved {moved_layers} video{'s' if moved_layers > 1 else ''} the Timeline no longer has to takes/"
            keys = bridges.splice(parsed, known or {})
            spliced = bridges.spliced(folder, manifest, keys) if keys else []
            joined = {**manifest, "segments": store.placed(manifest, count)}
            info += f" ({store.sequence_seconds(joined, spliced):.1f} s). Nothing to generate."
            blocked = ExecutionBlocker(None)
            status = _status(name, folder, parsed, manifest, is_done, materialize=True, known=known, managed_owner=sequence_owner(cls))
            return io.NodeOutput(blocked, blocked, blocked, blocked, blocked, blocked, info, ui={"h3c_timeline": [status]})


def attach_soundtrack(record, parsed, manifest):
    try:
        soundtrack = audio_tracks.marked(parsed, manifest.get('reference_audio'))
    except ValueError as error:
        record['export_error'] = str(error)
    else:
        if soundtrack:
            record['soundtrack'] = soundtrack
