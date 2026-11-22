---
name: h3-continuity-joins
description: Use when deciding how an H3 Timeline box meets the one before it, through continue, cut, new scene, a transition generated inside H3, visual memory (scene, selected, cast, off), an insertion bridge, or splitting at a timed Shot boundary, and whenever people, clothes or places must survive a cut. Part of the H3 Continuity pack; read h3-continuity-video first.
---

# Joins, visual memory and bridges

Every box after the first meets the box before it in one of the ways below. Choose
the join and the memory **per box**, for what that shot needs. A whole film rarely
wants one setting everywhere.

## The joins

| Join | Box fields | What H3 gets |
| --- | --- | --- |
| Continue | `cut` and `new_scene` false | The previous box's last `context_frames` frames, frozen as native context, and their audio with `carry_audio`. It also gets the previous box's saved last image as a guide at its first new frame, so the pose doesn't reset. Motion and sound carry on. |
| Cut | `cut: true` | No carried frames, so the box starts fresh from a new camera angle in the same scene. With memory on it still remembers the scene. |
| New scene | `cut: true, new_scene: true` | A cut to another place, time or look. A new scene begins for scene memory, and the new prompt defines the setting. |
| Transition | `join: {"kind": "transition", "note": "…"}` on a continuing box, with a Story bible | A continuation that H3 Story stages as an in-scene transition. `join` only tells the writer; rendering follows the flags. |
| Bridge | top-level `bridges` entry | A few generated frames on a cut between two rendered boxes (see below). |

- A continuing box must start from the pose and motion the previous box actually
  reached. Write its prompt from the rendered ending, not from the plan.
- A box can't be continued after a box that drops frames (an `exact` length off
  the grid), and the box before must play at least `context_frames` frames. See
  `h3-continuity-timing`.
- For scene memory, a scene starts at box 1, at every box with both `cut` and
  `new_scene`, and at every box with `plate_changes`. Set `new_scene` only when the
  place, time or look really changes, because it resets what scene memory
  remembers. `new_scene` without `cut` is a continuation.

## Long continuing chains

Over many continuing boxes, texture builds up ("burn"); the continuity check reports it as *N% grainier* and a hitch at a join as *Holds still: 3 frames at the join.* Optional Timeline fields, measured on a six-box chain (FastH3 omniref 8-step int8):

- `"context_noise": true` cut texture growth by about a third (clip 6: 1.75 against 2.04), same framing, about 10% slower. With the **H3 Sigmas Tail** node (`BasicScheduler -> H3 Sigmas Tail -> sampler sigmas`, `segment` connected): 1.67.
- `"continuation_guide": false` removes the join hold in moving shots; calm shots then move a little more at the join. Keep the default for calm shots.
- `"audio_feather": N` lets the last N carried audio ticks regenerate.
- **H3 Continuation Model** routes continuing boxes to another model, for a continuation LoRA. The public anti-burn LoRA cut to a close-up at 0.5 and did nothing at 0.3 on FastH3 int8, so do not recommend it for that model. On MiniMax REF2VA (int8 ConvRot or bf16, with the ref2v turbo LoRA v1.1) the same chain barely burns without it (clip 6: 1.19); at 0.5 it caused no cut and gave 1.04. FastH3 v2 int8 with turbo LoRA v1.0 (the Story Studio examples' video model) did not burn (clip 6: 0.97) but box 2 cut to a closer framing one frame after the join, with or without the LoRA, with euler or the examples' res_multistep, and on a second seed, each time after box 1 had rendered wider than the prompted shot size; on that model, check the first join.

## Transitions inside H3

To join two shots with a move, generate the cause, the cover and the reveal inside
H3, out of action, light, environment or camera movement. A back crossing the lens
and light blooming as the camera turns are examples, not presets. Plan the trigger
within the outgoing movement and place the box boundaries around it. Avoid a waiting
pose before the effect, an exposed jump in framing, and replaying the effect in
newly generated frames. Keep a moving beat in one box, or in continuing boxes,
rather than splitting it where the split would bump. Quiet holds and hard cuts are
still valid choices. Read `transitions` and `native-transitions` in the bundle.

## Visual memory

Visual memory shows H3 earlier moments of the film, so a later box keeps what they
established: a room's layout, a coat, a house seen from another side. Each
remembered moment is a **five-frame** window, read from a rendered box's original
video latent and handed to H3 as a native video reference (`<Video N>`, described
in `subject_definitions`). It needs no extra model. Memory is video only, so audio
continuity still comes from `carry_audio`. Memory doesn't change a box's mode: on
`flf2va` boxes the memory windows go alongside the first and last frames.

| `memory` | The box is shown |
| --- | --- |
| `scene` | the first frame of the box that began the scene, and a view from the middle of the box before. At a cut, the whole preceding shot replaces that view. A box that begins a scene has no earlier view of it. This is the Studio's and Story's default for new boxes. |
| `selected` | up to three moments you choose in `memories`, from any earlier box, across scenes too. Each is `{box, frame, label}`, where `frame` is a time in that box's played footage and `label` names the details to keep, such as `red brick house, blue door, three upstairs windows`. |
| `cast` | with a Story bible: each scheduled character as they look now, and the place (see `h3-continuity-story`). At most three moments, fewer when the box has RefMods videos. |
| `off` | nothing. This is what a JSON box without `memory` gets. |

- **At a cut**, every mode except `off` also supplies the **whole preceding shot's**
  original latent, first and in place of single moments from that box (`selected`
  moments still add theirs), so layout, object appearance and movement carry across
  the cut while the new shot starts from a fresh target. It doesn't freeze opening
  frames or turn the cut into a continuation. A `new_scene` cut keeps this, and its
  new prompt defines the new setting.
- **Continuing boxes** already carry the box before them. Their memory can be `off`,
  as in the bundled memory demo's last box, unless they need something from further
  back.
- **Choose by shot.** A return to a place seen earlier wants `selected` moments from
  where it was established. A new angle in the same scene wants `scene`. A shot that
  should look unlike anything before it wants `off` or a `new_scene`.
- A remembered moment must lie inside its source box's played frames. When it
  doesn't, choose an earlier moment or another source box. Never lengthen the source
  box, and never shorten a box to suit a moment (see `h3-continuity-video`).
- H3 snaps each moment to a 17-frame boundary and reads five frames from there,
  so a window can start slightly before the time you chose. In a continuing source,
  the time counts delivered footage, and a window never starts inside the replayed
  overlap.
- **Render the source first.** A box whose remembered source is missing, stale or
  incompatible stops with a "render the source first" message. Re-rendering or
  switching the take of a remembered box marks every box that remembers it as
  needing a render. In the API, remembered boxes count as dependencies of the box
  that remembers them.
- Not yet benchmarked: the full renderer hasn't been visually compared across every
  memory mode. To judge one, render the same seeds with memory `off`, `scene` and
  hand-picked moments, then compare details, motion at the joins, runtime and VRAM.

Reproduce the bundled example with `examples/memory_demo.json` (see
`docs/MEMORY-DEMO.md`). It has six boxes and one bridge, using `scene`, `selected`
with moments from box 1, and `off` on a continuation.

## Bridges

A bridge turns the hard cut between two rendered boxes into a generated move.
Neither box renders again, and every box keeps its Timeline time.

```json
"bridges": [{"before": "box4", "frames": 29, "seed": 4410, "prompt": "The camera rises to the roof view."}]
```

- `before` is the box the bridge leads into. That box must come after box 1 and
  start with `cut` or `new_scene`, and at most one bridge leads into it. `frames`
  is 12, 29 or 46 (`limits.bridge_frames`). A missing `seed` is derived from the
  box id and written back.
- The bridge carries the end of the box before from its saved latents and freezes
  the start of its own box. H3 generates only the frames in between, as text to
  video with audio, from the shared prompt and the bridge prompt. With 39 context
  frames that means runs of 90, 107 and 124 frames, adding 0.5 s, 1.2 s and 1.9 s.
- A bridge sends **no** pictures, references, first or last frame, guides, timed
  text or memory. Write its prompt to describe the move on its own, because a
  mention there reads only as "the described subject".
- **Only the full video gets longer.** Box starts, audio lanes, timed text, memory,
  pins, the check and the Story's seconds never see a bridge. After a 29-frame
  bridge, everything from its box on plays 1.2 s later in the full video than on
  the Timeline, while an `in_full_video` recording plays straight through from the
  box its clip starts in. A film whose picture must stay on a fixed soundtrack can't
  take bridges without drifting from it.
- A bridge renders once both its boxes are rendered: on a plain run after every
  box, or alone with `render_bridge` set to its box id in the queued copy (never
  together with `render_box`). Until it renders, the join plays as a cut. A bridge
  after an exact box that drops frames can't render.
- The frozen ends hold the look at both sides, but the move isn't guaranteed to
  arrive smoothly. Inspect the last bridge frame against its box's first frame,
  and cover a step that shows (with smoke or a passing body) or remove the bridge.

## Splitting a box

- **Split before Shot N** turns a timed `[Shot N]` boundary of one box into two
  boxes. Later shots need increasing `At MM:SS.mmm,` timestamps. The second box
  starts as a Cut. Each half keeps its own shots and required references, accepted
  guides move with their shots, and a bridge before the box stays with the first half.
- Frame guides can steer a moment inside a shot, including without Shot markers,
  but have no split action. Keep one continuous camera move in one box: repeating
  the whole-shot prompt in a second box can restart its opening action.
- Existing saved boxes keep their prompts, paired guides and joins, including
  Continue joins created by earlier guide splits.

Through MCP, edit joins/memory in the exact saved document with `h3_save_project`.
Inspect dependencies using `h3_plan_video` and overlap effects through
`h3_inspect` regeneration. If a replacement take requires rebuilding continuity,
review the affected clips/takes and submit its exact preflight fingerprint as
`selection_json.rebuild_continuity`; never invent consent or delete dependent takes.
Each native `h3_render_video` submits one box or insertion bridge; status does not
queue the next. Replacement bridge generation is disabled, and split-at-guide and
Guide Recheck are retired. Keep insertion bridges separate from those old records.
