# Bridges

A bridge turns the hard cut between two rendered boxes into a generated move. H3 renders a few new frames that leave
the last frames of the box before and arrive at the first frames of the box after, and the full video plays them on
the join. Neither box renders again, and every box keeps its render and its Timeline time.

## Inserting a bridge

In the Studio (**Open Studio** on the Timeline node), select a box after box 1 that starts with **Cut** or **New
scene**. Its row on the Box page has a **Bridge** field next to Join. **Insert bridge** is on when this box and the
one before it are rendered, and the one before plays every frame it generates. Otherwise it is off, and the line under
the row says why, for example "Render box 3 first.", "Wait for the Timeline's status to catch up with the last edit."
or, after an exact box that drops frames, "Box 3 drops 9 frames, so the bridge before box 4 can't start from its last
frame: use a replacement bridge, or give box 3 a length on the grid, which moves every later box."

A new bridge has 29 frames, a new seed and a copy of the box's prompt. Its panel, under the box's row, has:

- **Length**: 12, 29 or 46 new frames, with their seconds;
- **Seed**, with a button for a new one;
- **Bridge prompt**: how the shot moves from the box before into this one;
- **Render bridge · new seed**, **Play** and **Remove bridge**;
- a line with the bridge's state.

The track shows a small diamond on the join, in the bridge's state color, and clicking it opens the bridge. The head
adds the bridges and the time they add, for example "5 boxes · 21.0 s · 1 bridge, +1.2 s".

## What H3 renders

A bridge run carries the last frames of the box before from its saved latents, as a continuing box does, and freezes
the first frames of the box after the same way. H3 generates only the bridge's frames between them. Each end is
`context_frames` long, or the box's length when that is shorter, so with 39 context frames and boxes of at least 39
frames:

| New frames | Run | Adds to the full video |
| --- | --- | --- |
| 12 | 90 | 0.5 s |
| 29 | 107 | 1.2 s |
| 46 | 124 | 1.9 s |

H3 gets the shared prompt and the bridge's prompt, as text to video with audio. A bridge sends no pictures, references,
first or last frame, guides, timed text or memory, so every mention, such as `@image2`, reads as "the described
subject" or "the described sound". The frozen frames carry the look at both ends. With **carry audio** on, the sound
is carried and frozen the same way.

## Only the full video gets longer

A bridge lives on the join, outside the boxes. Box starts, audio lanes, timed text, the seconds the Story writes for,
Check, drift, memory and pins never see it. The full video plays each rendered bridge between its two boxes, so after
each bridge it runs that much behind the audio lanes and the timed text: with a 29-frame bridge before box 4,
everything from box 4 on plays 1.2 s later in the full video than on the Timeline. A clip ticked
[In the full video](TIMELINE-AUDIO.md#in-the-full-video) starts with its box, after the bridges before it, and plays
straight through later bridges, so the boxes after a later bridge run that much behind it.

## When a bridge needs a render

A bridge needs a render when it has no take yet, and again when its prompt, length or seed changed, when the node's
width, height, context or audio changed, when the box before or after it rendered again, or when its saved files are
missing. Until it renders, the full video leaves it out and the join plays as a hard cut. The line in its panel, also
shown when you point at its diamond, says which:

| Line | Means |
| --- | --- |
| Rendered, 29 frames. | The full video plays it. |
| Needs a render: box 3 rendered again. | It has an older take, which the full video leaves out; the reason follows the colon. |
| Plays as a cut until it renders. | It has no take yet. |
| Render box 3 first. | A box it joins isn't rendered. |
| Waiting for the Timeline's status. | The Studio hasn't read the status since the last edit. |

A bridge after an exact box that drops frames, or one whose prompt and the shared prompt are both empty, has a
problem: its panel and diamond turn red, the line shows the problem, and it can't render.

## Rendering a bridge

**Render bridge · new seed** renders only this bridge, with a new seed, and keeps both boxes. **Render all** renders
every box that isn't rendered, then every bridge that needs a render and has no problem, in Timeline order, and its
count includes those bridges. **Render next** renders the next box, or once every box is rendered, the next bridge.
**Render box** renders only its box, after which a bridge next to it needs a render. Nothing renders a bridge
again by itself. **Play** shows the bridge's take in the Studio's player, labelled "Bridge before box 4".

## Removing a bridge

**Remove bridge** takes the bridge out, so the join plays as a cut. Turning Cut and New scene off on its box, choosing
**Continue**, deleting the box, deleting the box before it so that it becomes box 1, or moving it to the front removes
the bridge too. **Undo** (Ctrl+Z) restores the bridge with the box. **Split** keeps the bridge before the first half. A
Story Write that replaces the boxes leaves no bridge behind.

## Files and takes

H3 Save Segment saves a bridge apart from the boxes, in the sequence folder: `bridge@<id>.mp4` with the new frames and
their audio, `bridge@<id>_last.png` and `bridge@<id>.safetensors`, where `<id>` is the id of the box it leads into.
The manifest lists it under `bridges`. Box segments are never moved or renumbered. Rendering a bridge again moves its
earlier take to `takes/bridge@<id>_<time>`, and after the next run, the saved bridges the Timeline no longer has move
to `takes/` as well. The bridge's settings list those takes, and one that still joins both boxes can be put back: see
[Takes](TIMELINE-TAKES.md).

An older H3 install ignores bridges in the Timeline and in the sequence folder, and its Studio drops them when it saves.
Its full video leaves them out.

## Bridges from outside ComfyUI

An outside author adds the same bridges with a top-level `bridges` list, and renders one with `render_bridge`. See
[External Timeline](EXTERNAL-TIMELINE.md#bridges).
