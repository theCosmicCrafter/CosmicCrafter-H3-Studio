---
name: h3-continuity-timing
description: Use when H3 Timeline box lengths or start times matter. That covers the 17k+5 frame grid, exact lengths and long edits of many short cuts (for example cut to a beat map), dropped frames and the cut that must follow them, where a box starts on the movie clock, boxes past 362 frames with H3 Context Windows, merging a continuing chain, and refining a rendered chain with H3 Join Chain. Part of the H3 Continuity pack; read h3-continuity-video first.
---

# Lengths, exact edits and long boxes

## The grid and played frames

- Output is 24 fps. A fresh box (box 1, or a cut) generates `17k + 5` frames, at
  least 22. A continuing box generates `17k` new frames, at least 17, after the
  `context_frames` it carries.
- A box gives its length as `frames`, or as `seconds` (rounded to frames). Without
  `exact` the length snaps to the **nearest** grid length: 96 frames play 90 fresh
  or 102 continuing.
- **A box starts where the boxes before it end**: its start on the movie clock is
  the sum of the earlier boxes' played frames. Snapping one box moves every later
  box, along with the audio, text and guides placed on them. Planning or preparing
  reports each box's `delivered_range`, `generated_range` and `carry_range` as
  half-open movie frames, so read those rather than recomputing them.
- Lengths are the author's. Don't change one to make memory, guides, plate changes,
  bridges or prompt timing fit; move those instead (see `h3-continuity-video`).
  Give a box that must hold its length (lip sync, a beat) `exact`, or a length
  already on the grid, so the length you wrote is the one that plays.
- The default limit is 362 generated frames, or 362 minus `context_frames` new
  frames for a continuing box (`limits.exact_frames`).

## Exact lengths

`"exact": true` makes a box play exactly its `frames`, from 1 to its limit. H3
generates the next grid length up, and the box keeps its first frames and drops the
rest:

| Plays | H3 generates | Dropped |
| --- | --- | --- |
| 9 (fresh) | 22 | 13 |
| 30 (fresh) | 39 | 9 |
| 96 (fresh) | 107 | 11 |
| 22 (fresh) | 22 | 0 |
| 40 (continuing) | 51 | 11 |

- Box starts, timed text, audio lanes, guides, memory, pins, the check and the
  Story's seconds all follow the **played** length. The saved video, its last-frame
  PNG and its audio stop at the played length, while the saved latents keep every
  generated frame. The full video lasts exactly as long as its boxes play, plus any
  rendered bridges.
- A last-frame guide lands on the last *played* frame. A 1-frame box shows only its
  first frame.
- **After a box that drops frames, the next box must be a cut**, or there must be no
  next box, because a continuation replays the last *generated* frames. Preparation
  refuses otherwise, for example: "box 3 drops 9 generated frames, so box 4 can't
  continue it: make box 4 a cut, or give box 3 a length on the grid (22 or 39
  frames), which moves every later box". Make the next box a cut, which keeps
  every length. Ask the user before you change the length instead. An exact
  length that sits on the grid drops nothing and can be continued.
- A continuing box also needs the box before it to play at least `context_frames`
  frames. Rendering stops at the continuing box otherwise, and the plan reports
  `carry_conflict`. Here too, make the continuing box a cut rather than change a
  length.
- A bridge can't start after a box that drops frames either, so a join that should
  take a bridge needs the box before it on the grid.
- Choosing between the two: when a cut must land on an exact frame (a beat, a
  lyric, a source edit), use `exact` and accept that the next box is a cut. When
  boxes should flow into each other, keep grid lengths and let the boxes continue.

## Long edits of many cuts

A long edit is many short exact cuts, each usually opening on its own picture. Stage
the pictures as Timeline pictures in slots from `image17` up, with no upper limit
(`limits.saved_picture_slots`), and name them in each box's `first`, `last` and
mentions. A box still sends H3 at most 9 pictures. See `h3-continuity-references`
for pictures and guides, and the "Long edits" section of `external-timeline`.

## Boxes longer than 362 frames

- Raise the Timeline's `max_frames`, a `17k + 5` value from 362 to 991. A box over
  362 generated frames then needs the **H3 Context Windows** node between the model
  and the sampler, which samples the latent in overlapping windows. It wraps ComfyUI's
  MiniMax H3 Context Windows node, so it needs a ComfyUI version that includes it.
  The defaults are `context_length` 124, `context_overlap` 39, `fuse_method`
  `pyramid`, with `freenoise` and `split_conds_to_windows` as options.
- The Studio keeps a Timeline's `max_frames` and lets boxes reach it, but it has
  no control to set it, and the Story planner still stops at 362. Set `max_frames`
  in the JSON or through the API.
- Guides anchor only the window they fall in. Guides unrelated to the prompt make
  the middle windows follow the prompt alone, so the video cuts to the prompt's
  scene and back. In tests, windowed runs moved a little more than unwindowed ones.
  Memory with windows, last guides on boxes that drop frames, boxes past 498
  frames and higher resolutions are not verified.

## Merging and refining a continuing chain

- `h3_continuity.long_merge.merge_continuing(timeline_json, first_id, last_id)`
  turns a run of continuing boxes into one box. Frames add up on the grid, prompts
  join in order, and previews and plate changes move with their frames. It refuses
  cuts, exact boxes and a continuing box with a first frame. Windowed sampling then
  blends the old seams. Nothing calls it automatically.
- **H3 Join Chain** reads saved segments `first_segment`..`last_segment` of one
  continuing chain from `output/h3_sequences/<name>` into a single latent, keeping
  each carried stretch once. Noise it with a sampler `denoise` below 1 and sample it
  through H3 Context Windows. It refuses a chain that crosses a cut or a segment that
  dropped frames. The refined latent is not saved back as segments.

## First-pass cache and saved execution

H3 Disk Cache goes after the first-pass sampler; downstream decode, Save Segment
and second pass read its result. Key the Timeline positive, latent and seed.
Connect the first-pass 24 fps decode to Save Segment `guide_frames`, so later
second-pass changes do not alter the next clip's first-pass guide. Cache modes
are use, refresh and off; namespaces live under `output/h3c_cache`. Prompt,
reference, seed, LoRA or first-pass changes invalidate it. CPU scheduler behavior
is tested; full GPU rendering remains a separate validation boundary.

Disk Cache, Context Windows, Join Chain and Save Segment codec/colour are graph
configuration, discoverable with `h3_inspect` nodes. Capture a matching execution
snapshot after wiring changes. MCP timing edits use `h3_get_project` and
`h3_save_project`; preserve exact lengths and unknown metadata, then inspect the
new `h3_plan_video` before explicitly submitting work.
