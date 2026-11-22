---
name: h3-continuity-story
description: Use when an H3 Timeline uses or could use H3 Story. That covers writing, rewriting or revising box prompts with a language model, story templates, idea images, the Story bible and Cast (characters, places, props, looks, schedules, joins, pins, adding an entity to a box), Cast visual memory, updating prose after Cast edits, and the continuity check with colour drift. Part of the H3 Continuity pack; read h3-continuity-video first.
---

# H3 Story, the bible and the continuity check

Everything here is optional. A Timeline renders from its box prompts alone, and a
person or an agent can write those prompts directly. H3 Story helps plan and write
them, and the bible keeps cast and places consistent in the wording.

## H3 Story, the writer

Link **H3 Story**'s `story` output to the Timeline's `story` input. Renders never wait
for it. It calls any OpenAI-compatible endpoint (`base_url`, `model`; optional
separate story-planning and vision endpoints and models). API keys are kept per host
on the ComfyUI server, never in the workflow.

- **Write story** plans and writes. It plans the boxes too on an empty Timeline,
  for `total_seconds` (0 lets the model choose, up to 60 s), and otherwise writes the
  boxes in `scope`: empty boxes, or also boxes that still hold what Write wrote.
  **Rewrite selected clip** and **Rewrite entire Timeline** rewrite. **Feedback**
  patches the current story from a sentence and keeps unrelated text, timing and
  boxes. **Undo last Write** restores the Timeline.
- The model returns structured data, and **code compiles** the native prompt. That
  keeps shot times consistent, inserts dialogue verbatim, and refuses plans that need
  more time than a box has instead of speeding them up. Invalid replies stay as
  drafts and never replace a prompt.
- The writer prefers short, independently editable boxes, even for a continuous
  take, and existing boundaries and cut flags stay authoritative. A continuing box
  starts from the pose and motion actually reached. Appearance is read-only for box
  writers: change a look in Cast first.
- The `guide` input holds creative requirements, checked against the final prompts.
  It ranks first: then the idea, the bible, the box's plan, the shot rules and last
  the general H3 guidance.
- **Idea images** are described and used as optional guidance for palette, texture,
  lighting or composition. They are never reproduced, and only images a prompt
  uses count toward the nine-picture limit. With **Send pictures to the writer**,
  the model describes connected pictures that have no description. Descriptions are
  cached per image.
- `thinking` sets reasoning effort. `free_vram`, with a model server on the same
  PC, takes a turn in ComfyUI's queue and frees ComfyUI's models while writing.
- **Saved stories** keeps every story written on the server, and a story can be
  loaded into a Timeline again.

## Templates

A template is a video to resemble, written as text: its sequence, style and rules.
Pick one on the Story page. Templates live in ComfyUI's `user/h3c_templates`, as a
single `.md` or as a folder with a `SKILL.md` and references. Front matter gives
`name` and `description`, and the whole template is limited to 100,000 characters.
The planner spreads the template's sequence over the boxes, and each box writer stages
its part in the template's look, camera, editing, typography and sound. A template
ranks after everything the user wrote. Shipped examples, read-only, are **Music
video** and **Trailer**. See `docs/STORY-TEMPLATES.md`.

## The Story bible and Cast

The bible (`timeline.bible`) lists **characters, places and props**, each with
pictures, a description, a voice and **looks** over time. Each box records which of
its subjects is which entity (`cast`, mapping subject labels to entity ids), its
`schedule` (the entities in it and its place) and its `join`
(`{kind: continue|transition|cut|new_scene, note}`). Box prompts provide rendered
prose. Render-time Cast memory, current appearance pictures, voices and reference
preparation also read the bible/schedule; keep them consistent with the prompts.

- **Build bible** links each box's `<Subject N> is …` lines to entities without
  changing any prompt. Lines it can't reproduce exactly stay unlinked, with a reason.
- With a bible, the writer names entities by id and code writes the prompt from the
  wording in force at that box. A Cast edit then recompiles the boxes Write wrote,
  and a box edited by hand gets only a line-by-line update. **Update prose with the
  writer** patches shot text that contradicts a new look.
- A **look** applies from its box until the next look, and can have its own picture
  (an outfit change). A look without a picture keeps the picture in force and says
  the change in words.
- A box's subject line **differs** when it isn't the bible's wording. Cast offers to
  use the bible's wording, make it a look, or link someone else.
- **Add from Cast** (bible action `assign` with `box` and `entity`) adds one
  entity to one box: the next unused `<Subject N>` (above every number in the box
  prompt, the shared prompt and the box's `cast`) defined with the bible's wording
  and pictures in force at that box, plus its `cast` link and `schedule` entry
  (`schedule.place` for a place). A prompt without `subject_definitions:` gains
  it; an `integrated_multimodal_description:` header becomes
  `detailed_description:`, and plain text moves under it. It returns
  `{prompts, casts, schedules, subject, changed}` for one atomic save, or
  `changed: false` with the existing label when the entity is already linked
  there. It refuses, changing nothing, an entity with neither description nor
  picture, disabled pictures, duplicate sections, or a box that would exceed
  H3's reference limits. It never adds shots, retention or actions.
- Removing an entity from a box's schedule leaves its prompt text and `cast`
  link; edit or delete the `<Subject N>` definition separately, after removing
  its other uses.
- Voices and voice clips belong to characters (see `h3-continuity-sound`).
- Each Cast change is one undo step.

## Cast memory and pins

With a bible, a box's `memory` can be `cast`. Up to three moments, fewer when the
box has RefMods videos, are remembered in this order:

1. Each scheduled character that no picture in the box shows as they look now. It
   uses their latest **pin** since that look began, otherwise the middle of their
   last shot in the first box of that look, or 5 frames before that box's end.
2. The place, unless the box continues the box before at the same place. It uses
   the place's latest pin, otherwise 5 frames before the end of the latest earlier
   box set there.

At a cut the whole preceding shot comes first, as for every memory mode (see
`h3-continuity-joins`). A **pin** marks a moment of a box's current take for a
character or place, through **Pin moment for…** in the Studio's player. A box Write
writes from the bible moves from `scene` to `cast`, while boxes on `off` or
`selected` keep their choice. Render the boxes a Cast box remembers first.

## The continuity check and drift

After rendering, the Story's **vision model** can check each rendered box against the
bible, its pictures and the box before it. It looks at the middle of each shot (up to
five) and the last frame, the pictures of the box's scheduled characters, props and
place, and the join with the previous box's last frame, unless the box starts a new
scene. It reports only differences a viewer would notice in a character, prop, place
or join. Camera, framing, motion, blur and artefacts are out of its scope.

- **Drift** compares a box's mean CIELAB colour with its scene's first box. A shift
  of 8 or more on a\*b\*, or 10 or more in L\*, is named, for example "warmer and 12%
  darker than box 1". Without a vision model the check measures drift only.
- **Check** checks one box, and **Check all rendered clips** checks every box
  without a current result. Both need a linked H3 Story node and an empty ComfyUI
  queue. Results are stored in `checks.json`, and a re-render makes a result stale.
- **Retake** renders that box alone with a new seed, and the old take stays in
  `takes/`. The check only reads renders; nothing renders unless asked.
- The check is a reviewer's aid, not acceptance. Watch the boxes it passes too.

## Saved agent work

`h3_story` exposes writing, rewriting, feedback, templates, bible transformations,
continuity checks and still-prompt conversion. Configure provider/model widgets in
the saved Story node; credentials stay on the server. Retired `writing_mode` and
Guide Recheck are unavailable. Read `h3c://docs/MCP.md` for action payloads.

Writing needs an explicit saved native graph/Story/Timeline and matching execution
snapshot. Keep the request key/handle; a lost start acknowledgement reconciles
only against matching request attribution. Poll with `h3_job_status`, retain the
finished proposal, then explicitly save selected content with the current revision.
A late result never overwrites a newer save. `taken` acknowledges a retained result
without applying it. Cancel is scoped to that Story job.

`h3_library` covers saved story versions, display names, deletion and named
checkpoints. Checkpoints keep their pinned media and cannot be edited; restore
returns an independent editable copy. `duplicate` copies a story with its renders
under a new `title`, optionally from a corrected Timeline. Generation export/import verifies local
installation media rather than embedding files or replaying old jobs. Browser
Undo/Redo (including Undo last Write) is separate from saved revisions.
