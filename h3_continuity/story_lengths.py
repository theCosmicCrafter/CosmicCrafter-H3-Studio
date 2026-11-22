"""The boxes H3 Story plans on an empty Timeline: the model's seconds fitted to the Timeline's grid, its limits and
the total, a note for boxes that generate more than about 10 s, and the planned Timeline. Pure Python."""

import random
import string

from . import timeline as rules
from .timing import FPS

MAX_TOTAL_SECONDS = 600
AUTO_MAX_SECONDS = 60
MAX_PLANNED_BOXES = 100
SOFT_MAX_SECONDS = 10
SOFT_MAX_FRAMES = 243
SETTLE_FRAMES = 8
MAX_PLANNED_SEED = 2**32 - 1
ID_CHARACTERS = string.digits + string.ascii_lowercase
ID_LENGTH = 6


def _snapped(frames, fresh, context):
    return min(rules.snap_frames(frames, fresh), rules.frame_limits(fresh, context)[1])


def _boxes(count):
    return "1 box" if count == 1 else f"{count} boxes"


def _out_of_reach(count, target, grow, context):
    total = f"{target / FPS:g}"
    if grow:
        return (f"{_boxes(count)} can't add up to {total} s: a new shot adds at most {rules.MAX_FRAMES / FPS:.2f} s "
                f"and a box that continues at most {(rules.MAX_FRAMES - context) / FPS:.2f} s; plan more boxes")
    return (f"{_boxes(count)} can't fit in {total} s: a new shot adds at least {rules.MIN_FRESH_FRAMES / FPS:.2f} s "
            f"and a box that continues at least {rules.MIN_CONTINUING_FRAMES / FPS:.2f} s; plan fewer boxes")


def fit(seconds, fresh, context, total_seconds):
    """The frames of each planned box: seconds[i] snapped to the grid of a new shot (fresh[i]) or of a box that
    continues, within the Timeline's limits, then fitted to within SETTLE_FRAMES of `total_seconds`, or with 0 to
    AUTO_MAX_SECONDS when the boxes run longer. Raises ValueError when the limits keep the total out of reach."""
    frames = [_snapped(round(min(value, rules.MAX_FRAMES / FPS) * FPS), new, context)
              for value, new in zip(seconds, fresh)]
    total = sum(frames)
    if total_seconds:
        target = total_seconds * FPS
    elif total > AUTO_MAX_SECONDS * FPS:
        target = AUTO_MAX_SECONDS * FPS
    else:
        return frames
    frames = [_snapped(round(length * target / total), new, context) for length, new in zip(frames, fresh)]
    while abs(target - sum(frames)) > SETTLE_FRAMES:
        grow = sum(frames) < target
        step = rules.GRID if grow else -rules.GRID
        movable = [index for index, new in enumerate(fresh)
                   if rules.frame_limits(new, context)[0] <= frames[index] + step <= rules.frame_limits(new, context)[1]]
        if not movable:
            raise ValueError(_out_of_reach(len(frames), target, grow, context))
        clip = {index: frames[index] + (0 if fresh[index] else context) for index in movable}
        if grow:
            index = min(movable, key=lambda index: (clip[index], index))
        else:
            index = max(movable, key=lambda index: (clip[index], -index))
        frames[index] += step
    return frames


def _listed(items):
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def slow_note(frames, fresh, context):
    """The note naming the planned boxes whose generated clip, carried frames included, is longer than
    SOFT_MAX_FRAMES, or None."""
    clips = (length + (0 if new else context) for length, new in zip(frames, fresh))
    slow = [(number, clip / FPS) for number, clip in enumerate(clips, 1) if clip > SOFT_MAX_FRAMES]
    if not slow:
        return None
    guideline = f"above the {SOFT_MAX_SECONDS} s render-cost preference (allowed when the scene needs it)"
    if len(slow) == 1:
        number, seconds = slow[0]
        return f"Box {number} generates {seconds:.1f} s, {guideline}, so it will render slowly."
    numbers = _listed([str(number) for number, _ in slow])
    lengths = _listed([f"{seconds:.1f} s" for _, seconds in slow])
    return f"Boxes {numbers} generate {lengths}, {guideline}, so they will render slowly."


def planned_timeline(shared, frames, cuts, scenes, rng=random):
    """The Timeline Write plans: `shared` as its shared prompt and one empty box per entry of `frames`, each with a
    new id and seed, a cut where cuts[i] is true (never on box 1) and a new scene where scenes[i] also is."""
    boxes, used = [], set()
    for index, (length, cut, scene) in enumerate(zip(frames, cuts, scenes)):
        box_id = ""
        while not box_id or box_id in used:
            box_id = "".join(rng.choice(ID_CHARACTERS) for _ in range(ID_LENGTH))
        used.add(box_id)
        cut = bool(cut) and index > 0
        boxes.append(rules.Box(box_id, length, "", rng.randint(0, MAX_PLANNED_SEED), cut, "", "",
                               new_scene=cut and bool(scene)))
    return rules.Timeline(shared, boxes)
