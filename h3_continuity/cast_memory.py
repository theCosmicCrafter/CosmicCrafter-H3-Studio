"""Cast memory: the earlier moments a box remembers, chosen from the Story bible.

A window is (source box index, frame after the source's replay, label), as `timeline.memory_sources` gives them.
Only moments from an entity's current look count, so a look change drops the older ones. Nothing here reads a file:
`visual_memory.records` checks that each source box is rendered."""
from . import story_bible, timeline as rules

MAX_WINDOWS = 3


def check(timeline):
    """Raises ValueError for a bible or a box schedule that Cast memory can't read."""
    if timeline.bible is not None:
        try:
            story_bible.entities(timeline.bible)
        except ValueError as error:
            raise ValueError(f"H3 Timeline: {error}") from None
    for number in range(1, len(timeline.boxes) + 1):
        schedule = _saved(timeline, number - 1)["schedule"]
        if schedule is not None and not story_bible.valid_schedule(schedule):
            raise ValueError(f"H3 Timeline: box {number}'s schedule must list entity ids and give a place id or null.")


def windows(timeline, index):
    """Cast box `index`'s windows: each scheduled character no picture shows as it looks now, then its place unless
    it continues the previous box there, then the moment before a cut at the same place. At most 3 less the box's
    RefMods videos; Same scene's windows without a bible or a schedule."""
    box, schedule = timeline.boxes[index], _saved(timeline, index)["schedule"]
    budget = max(0, MAX_WINDOWS - sum(ref["kind"] == "video" for ref in rules.box_slots(timeline, index).refmods))
    if not timeline.bible or schedule is None:
        return rules.scene_sources(timeline, index)[:budget]
    ids = [item.id for item in timeline.boxes]
    position = {box_id: number for number, box_id in enumerate(ids)}
    by_id = {entity["id"]: entity for entity in timeline.bible["entities"]}
    found = []
    for entity_id in schedule["entities"]:
        entity = by_id.get(entity_id)
        if entity is not None and entity["kind"] == "character" and not _shown(timeline, index, entity, ids):
            found.append(_moment(timeline, index, entity, ids, position, _character_box))
    place = by_id.get(schedule.get("place"))
    before=rules.previous_index(timeline,index,False)
    previous = _saved(timeline,before)["schedule"] if before is not None else None
    at_place = place is not None and previous is not None and previous.get("place") == place["id"]
    if place is not None and not (at_place and not box.cut):
        found.append(_moment(timeline, index, place, ids, position, _place_box))
    if at_place and box.cut:
        found.append((before, _near_end(timeline,before), "the moment before this cut"))
    result = []
    for window in found:
        if window is not None and all(window[:2] != chosen[:2] for chosen in result):
            result.append(window)
    return result[:budget]


def _saved(timeline, index):
    """Box `index`'s Story fields as saved; a Timeline built without `parse` has none."""
    return timeline.story[index] if index < len(timeline.story) else {"schedule": None, "source": None, "cast": {}}


def _own(timeline, index):
    return rules.played_frames(timeline, index)


def _near_end(timeline, index):
    """5 frames before box `index`'s end, or its first frame when it plays fewer."""
    return max(0, _own(timeline, index) - 5)


def _shown(timeline, index, entity, ids):
    """Whether a picture the box mentions shows the entity as it looks now: one of its current look's own pictures,
    or its own for the description."""
    look = story_bible.look_at(entity, ids, index)
    own = entity["looks"][look - 1].get("pictures", []) if look else entity["pictures"]
    mentioned = {slot for kind, slot in rules.mentions(rules.assemble_prompt(timeline, index)) if kind == "image"}
    return bool(mentioned & set(own))


def _moment(timeline, index, entity, ids, position, earlier_box):
    """The entity's window for box `index`: its latest pin from its current look before this box, else what
    `earlier_box` gives, labeled by the entity's label in the box or else its name. None without either."""
    look = story_bible.look_at(entity, ids, index)
    start = position[entity["looks"][look - 1]["from"]] if look else 0
    pins = [(position[pin["box"]], order, pin["frame"]) for order, pin in enumerate(entity.get("pins", []))
            if start <= position.get(pin["box"], -1) < index and pin["frame"] < _own(timeline, position[pin["box"]])]
    moment = max(pins)[::2] if pins else earlier_box(timeline, index, entity, start)
    if moment is None:
        return None
    cast = _saved(timeline, index)["cast"]
    label = next((key for key, value in cast.items() if value == entity["id"]), entity["name"])
    return (*moment, f"showing {label}")


def _character_box(timeline, index, entity, start):
    """The middle of the character's last shot in the first box of its look before `index` that schedules it, from
    that box's source, else 5 frames before that box's end."""
    for source in rules.track_indices(timeline,index):
        if source==index or rules.box_start(timeline,source)>=rules.box_start(timeline,index) or (source<start if timeline.tracks is None else rules.box_start(timeline,source)<rules.box_start(timeline,start)): continue
        saved = _saved(timeline, source)
        if saved["schedule"] is not None and entity["id"] in saved["schedule"]["entities"]:
            frame = _shot_middle(saved["source"], entity["id"])
            return source, _near_end(timeline, source) if frame is None else min(max(frame, 0), _own(timeline, source) - 1)
    return None


def _place_box(timeline, index, entity, start):
    """5 frames before the end of the latest box of the place's look before `index` that is set there."""
    for source in reversed(rules.track_indices(timeline,index)):
        if source==index or rules.box_start(timeline,source)>=rules.box_start(timeline,index) or (source<start if timeline.tracks is None else rules.box_start(timeline,source)<rules.box_start(timeline,start)): continue
        schedule = _saved(timeline, source)["schedule"]
        if schedule is not None and schedule.get("place") == entity["id"]:
            return source, _near_end(timeline, source)
    return None


def _shot_middle(source, entity_id):
    """The frame after the replay at the middle of the last shot of a box's saved source that lists the entity, or
    None when the source can't give one. Shot times count the replay; the source's frame has the box's frames and
    carried frames."""
    frame = source.get("frame") if isinstance(source, dict) else None
    reply = source.get("reply") if isinstance(source, dict) else None
    shots = reply.get("shots") if isinstance(reply, dict) else None
    if not isinstance(frame, dict) or not isinstance(shots, list):
        return None
    frames, carried = frame.get("frames"), frame.get("carried", 0)
    starts = [shot.get("start_ms") if isinstance(shot, dict) else None for shot in shots]
    if type(frames) is not int or type(carried) is not int or not all(type(value) is int for value in starts):
        return None
    for number in range(len(shots) - 1, -1, -1):
        subjects = shots[number].get("subjects")
        if isinstance(subjects, list) and entity_id in subjects:
            start = max(starts[number], round(carried * 1000 / rules.FPS))
            end = starts[number + 1] if number + 1 < len(shots) else round(frames * 1000 / rules.FPS)
            return (start + end) * rules.FPS // 2000 - carried
    return None
