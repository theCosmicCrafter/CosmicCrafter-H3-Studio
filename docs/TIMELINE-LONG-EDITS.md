# Long edits

A long edit is a Timeline of many short cuts, each opening on its own picture, at exactly the lengths of a source
edit. H3 renders lengths on its frame grid: 17k+5 frames for a box that starts fresh (at least 22), and 17k new frames
for a box that continues the one before (at least 17). Without Exact length, the Timeline snaps every box to that
grid, so a 9-frame cut becomes 22 frames and the edit drifts out of sync.

## Exact lengths

In the Studio (**Open Studio** on the Timeline node), turn on **Exact length** on the Box page, beside New scene. The
**Frames** field then takes any length from 1 frame up to the box's limit: 362 frames for a box that starts fresh, and
362 minus the carried frames for one that continues. The length reads like `0.38 s · 9 frames · H3 generates 22`. H3
generates the next grid length up, and the box keeps its first frames and drops the rest:

| Plays | H3 generates | Dropped |
| --- | --- | --- |
| 9 (fresh) | 22 | 13 |
| 30 (fresh) | 39 | 9 |
| 96 (fresh) | 107 | 11 |
| 22 (fresh) | 22 | 0 |
| 40 (continuing) | 51 | 11 |

Turning Exact length on keeps the box's length; turning it off snaps the box to the grid again. Dragging an exact
box's edge on the track moves it one frame at a time, and **Split** gives two exact boxes that play the original's
frames between them. A box that drops frames gets a note when it renders, such as "Box 3 plays 9 frames; H3 generates
22 and drops the last 13."

A cut opens on its first frame, and its last frame, when it has one, lands on the last frame it plays: frame 9 of a
9-frame cut. A 1-frame cut shows only its first frame, so its last frame isn't used; its note says so when it renders.
The saved video, its `_last.png` and its audio stop there, while the saved latents keep every generated frame. The full
video and its audio last exactly as long as the boxes play. Box starts, timed text, audio lanes,
guides, memory, pins, the continuity check and the seconds the Story writes for all follow the played length. A
memory view is 5 frames long, so in a box shorter than that, it includes frames that were generated and dropped.

## Cuts after dropped frames

A box that continues the box before it replays that box's last frames, so it can't follow a box whose last generated
frames were dropped. After a box that drops frames, the next box must be a cut, or there must be no next box.
Otherwise both boxes show the problem, and Render refuses with the same sentence, for example: "Box 3 drops 9
generated frames, so box 4 can't continue it: make box 4 a cut, or give box 3 a length on the grid (22 or 39
frames), which moves every later box." Making box 4 a cut keeps every length. An exact length on the grid drops nothing, so the next box can continue it as before.

A box that continues another also carries the Timeline's `context_frames` from it, 39 by default, so box 1 or a cut
that plays fewer frames than that can't be continued either. The continuing box shows the problem, its **Render box**
is off, and rendering stops at it with the same sentence, for example: "Box 4 continues box 3, which plays 22 frames,
fewer than the 39 it carries: make box 4 a cut, or give box 3 at least 39 frames." The Story and Prepare still accept
such a Timeline.

Changing an exact length, or turning Exact length on for a box that is off the grid, makes the box need a render.
Turning it on for a box already on the grid changes nothing. Boxes without Exact length snap and render exactly as
before.

## Many pictures

Pictures added with **+ Picture** take slots from `@image17` up with no upper limit, so every cut can have its own
first and last frames. Each box still sends H3 at most 9 pictures. The First frame, Last frame and Cast pickers scroll
and load thumbnails as they come into view. With more than 12 pictures they show a **Filter pictures** field, which
matches the `@slot` or the title; None and the chosen picture always stay. See [Timeline pictures](TIMELINE-PICTURES.md).

An older H3 install fails a Timeline with a picture above `@image99`, and renders exact boxes snapped.

## Which pictures the Story uses

A picture that serves only as boxes' first or last frames is those boxes' own picture. It stops being one when the
shared direction or another box's prompt mentions it, when a Cast entity or look has it, or when a RefMod fills its
slot. A box's own prompt mentioning its frames doesn't count, since frame prompts usually do.

When you Write, Vision describes a box's own picture only when one of its boxes is being written, and reuses a saved
description while the file is unchanged. The planner sees each box's frames by label in the box's line, and for a box
being written, each own picture's description on a line of its own under it. Own pictures aren't listed under
References, and the planner isn't sent the pictures themselves; each box's writer still gets its box's own pictures.
With Vision off, the planner sees only the labels. Every other picture is described and sent as before, and exact
boxes are written for the seconds they play.

## Building long edits outside ComfyUI

An outside author can build the same Timeline with the external Timeline API: boxes take `"exact": true`, and a
`picture` binding puts a staged file into a saved slot. See
[External Timeline](EXTERNAL-TIMELINE.md#long-edits-exact-boxes-and-saved-pictures).
