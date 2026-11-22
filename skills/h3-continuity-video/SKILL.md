---
name: h3-continuity-video
description: Use when authoring, rendering, reviewing or revising MiniMax H3 video with H3 Continuity Studio (the ComfyUI H3 Timeline, its Studio, H3 Story or the Timeline API), from a script, an agent or the Studio. The entry to the H3 Continuity skill pack, it says which scoped skill covers joins and memory, timing, references, sound, Story and the API.
---

# H3 Continuity Studio

H3 Continuity Studio lays a film out as **boxes** on an **H3 Timeline**. The Studio
calls them clips, while saved JSON and messages say box. Each box is one MiniMax H3
generation. A box can continue the one before it, cut to a new angle, start a new
scene, or be joined to it by a generated bridge. This skill is the entry to a pack
of scoped skills. Load the ones the task touches, using the table below. You won't
use every feature every time, but you should know each one exists before you choose
how to build a shot.

## Read the host first

Over MCP, call `h3_capabilities`, then `h3_read_guidance` for this skill and
`h3c://docs/MCP.md`. Load the scoped skills through their `skill://` resources.
The server's Skills extension advertises the same canonical files; resource
reading alone does not activate a client's skill. See `h3-continuity-api` for saved
targets, exact JSON documents, receipts and installation.

On the ComfyUI host you'll render on, read `GET /h3c/timeline/instructions` before
authoring. It is a self-contained bundle:

- `skill` is this file, and `skills` lists every skill of the pack (`name`, `body`)
  at the version the host runs. If they differ from a local copy, prefer the
  host's: it matches the code that renders.
- `guides[].body`: `base` and `ref` (MiniMax's own prompt guides, when installed on
  the host; otherwise the body says so, and you consult MiniMax's official H3
  documentation under its terms), `prompt-writing`, `transitions`,
  `native-transitions`, `external-timeline` (the Timeline JSON contract),
  `timeline-text`, `timeline-audio`, `timeline-references` and `timeline-api`.
- `examples[].body`, `limits` (the frame grid, context lengths, slot and per-box
  reference limits, bridge lengths, `max_frames`), `revisions`, and `client` and
  `clients` (the stdlib Python clients).

Use the guide bodies, not their titles. In a checkout of the repository, the same
texts are under `docs/` and the user guide is under `guide/`.

## The pack

| Skill | Load it when the work involves |
| --- | --- |
| `h3-continuity-joins` | how a box meets the one before it: continue, cut, new scene, transitions inside H3, **visual memory**, bridges, splitting a box before a timed Shot |
| `h3-continuity-timing` | box lengths, the frame grid, **exact lengths** and long edits of many cuts, where each box starts, long boxes past 362 frames, Context Windows, merging and refining continuing chains |
| `h3-continuity-references` | prompts and what H3 sees in one box: the native prompt structure, `t2va`/`flf2va`/`ref2va` modes, `@` mentions, Timeline pictures, first/last frames and Shot guides, still candidates, RefMods, plates, replacements |
| `h3-continuity-sound` | audio lanes, playing the original recording in the full video, character voice clips, Whisper timed text |
| `h3-continuity-story` | H3 Story (the writer), templates, the Story bible and Cast (looks, schedules, pins), Cast memory, Story feedback, the continuity check and colour drift |
| `h3-continuity-api` | driving the host from code: Timeline API v1 projects, plans, jobs, held jobs, artifacts, takes and workflow export, and the older graph-preparation route |

## The Timeline in brief

- **Frames.** Output is 24 fps. A box that starts fresh generates `17k + 5` frames
  (at least 22), and one that continues generates `17k` new frames (at least 17).
  Without `exact` every box snaps to that grid. The default maximum is 362
  generated frames. See `h3-continuity-timing`.
- **Box fields** (H3 owns these keys): `id`, `frames`, `seconds`, `exact`, `prompt`,
  `seed`, `cut`, `new_scene`, `first`, `last`, `memory`, `memories`, `previews`,
  `plate_changes`, `plate_edits`, `cast`, `schedule`, `join`, `source` and
  `flf_refmods`. Keep your own metadata on a box under another key (for example
  `edit`), and H3 preserves it. `source` is what H3 Story wrote, so don't author
  it yourself.
- **Timeline fields** include the shared `prompt` (it goes before every box's prompt
  and every bridge's), `pictures`, `audio_clips`, `voice_clips`, `timed_text`,
  `bible`, `refmods`, `plates`, `disabled_refs`, `reference_replacements`,
  `bridges` and `max_frames`.
- **Node settings**: `width` and `height` (multiples of 32), `context_frames` (22,
  39, 90 or 141: the frames a continuing box carries), `carry_audio`,
  `ref_image_size` (`match` or `max`) and `audio_context_frames`.
- **Mode.** Each box runs as `t2va`, `flf2va` or `ref2va`, decided by what it uses.
  The mode changes how first and last frames behave, so read
  `h3-continuity-references` before you add pictures, audio or guides to a box.
- **Current boxes.** A box is current while its saved render still matches its
  prompt, seed, length, join, pictures, RefMods, guides, audio, timed text,
  memory and the node's settings. A continuing box also needs the box before it
  unchanged. A box whose saved render no longer matches is *outdated*: it keeps
  its take, thumbnail and place in the full video, and the Timeline says why.
  Each queued run renders the next box that has no take; an outdated box renders
  again only when it is selected (Regenerate, or `render_box`). Takes follow box
  ids, so inserting or moving a box never makes later boxes lose theirs.
- **Render order.** A continuing box, a bridge and a box that remembers another
  each need their source rendered first. A re-render can make later boxes stale.
- **Takes.** Each new render of a box or bridge keeps the one before it in
  `takes/`. A take can be played, compared, put back without rendering (only
  when it fits both neighbours) or deleted. The Studio can render 1 to 10 takes
  of a box at once, and the API lists and switches takes (see `h3-continuity-api`).
  Put an earlier take back rather than re-rendering when it was better.
- **Full video.** Once every box has a take, `<name>_full.mp4` is assembled in
  the background from the box videos in Timeline order (status reports
  `full_video_building` meanwhile). Clips may differ in frame rate, HDR or size
  and aspect ratio: the join uses the highest rate, HDR when any clip is HDR
  and the dimensions of the smallest clip by pixel count. Larger clips resize to
  that width and height even across aspect ratios, which can stretch them. It plays rendered
  bridges on their joins, and the uploaded recording instead of H3's audio when
  a clip is marked `in_full_video` (see `h3-continuity-sound`). Each box saves its
  MP4 without carried frames, its latents (`.safetensors`) and a last-frame PNG
  under `output/h3_sequences/<name>/`. Keep the folder together, because the
  latents are what continuation, memory and bridges read.

Saved projects and generations are separate identities. `h3_library` lists saved
versions/checkpoints and earlier generations; a fresh generation keeps earlier
outputs. Named checkpoints are immutable; restore opens an independent editable
copy. Autosave preferences and browser Undo belong to the browser; explicit agent
saves use server revisions. No browser synchronization is required, and unsaved
browser edits are invisible. A stale save may overwrite newer work where existing
guards permit it; reread on a revision conflict and never silently merge.

Status distinguishes full video, video so far and source-backed partial previews,
including build progress/errors. `h3_inspect` status may build native previews;
`h3_plan_video` is read-only. A preview is not proof that every box is current.
Takes have ratings (0–5) and a tag; `h3_takes` previews scoped deletion before an
explicit delete action. Keep better takes instead of automatically cleaning them.

## Box lengths belong to the author

Lip sync, music beats, timed text, audio lanes and guides all hang off each box's
length, and every box starts where the boxes before it end. A changed length moves
every later box, so lengths stay fixed while you work:

- Never change a box's `frames`, `seconds` or `exact` to make something else fit. A
  remembered moment, a guide, a plate change, a bridge or timing in a prompt depends
  on its box. It never sets the box's length. Move the dependent thing inside the
  box's played frames, point it at another box, or remove it.
- Turning `cut` on or off for a box without `exact` also changes its length, because
  a fresh box and a continuing box snap to different grids.
- Some errors offer a length change as one of two fixes, for example "make box 4 a
  cut, or give box 3 a length on the grid". Take the fix that keeps every length.
  If only a length change would work, stop and ask the user first, and say which
  later boxes would move.
- When a length did change by mistake, put back the approved length, then fix
  what depended on the wrong one.

## Defaults that differ by how a box is made

A box drawn in the Studio or planned by H3 Story starts with visual memory on
**Same scene** (`scene`). A box written as JSON without `memory` has memory **off**,
so it knows nothing about earlier shots beyond what it carries. Choose each box's
memory on purpose (see `h3-continuity-joins`); don't inherit `off` by omission.
Likewise, a box without `exact` snaps its length to the grid, which moves every
later box.

## Every feature, in one line each

- Joins: continue, cut, new scene and transition (`h3-continuity-joins`).
- Visual memory, in `scene`, `selected`, `cast` and `off` modes, with up to three
  chosen moments (`h3-continuity-joins`).
- Bridges: 12, 29 or 46 generated frames on a cut, without re-rendering either box
  (`h3-continuity-joins`).
- Split a box before a timed `[Shot N]`; frame guides remain independent (`h3-continuity-joins`).
- Exact lengths, long edits and saved pictures from `image17` up
  (`h3-continuity-timing`).
- Long boxes up to 991 frames with H3 Context Windows, merging a continuing chain
  into one box, and refining a rendered chain with H3 Join Chain
  (`h3-continuity-timing`).
- Native prompt sections (complete or partial), timed `[Shot N]` stages, the field
  and cue-line syntax the Studio's Sections form edits, the shared prompt, and the
  effective-prompt inspection (`h3-continuity-references`).
- Connected references (images, videos, video audio, audio), Timeline pictures,
  enabling, disabling and replacing references, and the `image_N` outputs
  (`h3-continuity-references`).
- First and last frames, timed Shot guides, still candidates from the user's own image workflow,
  scene anchors and prepared still prompts (`h3-continuity-references`).
- RefMods, FLF2VA with cached RefMods, and appearance plates
  (`h3-continuity-references`).
- Audio lanes, `in_full_video`, voice clips, timed text and lettering contracts
  (`h3-continuity-sound`).
- H3 Story writing, rewriting and feedback, templates, idea images, the bible,
  adding a Cast entity to a box, looks, schedules, pins, the continuity check and drift (`h3-continuity-story`).
- Timeline API v1, the graph-preparation route, receipts, held jobs, artifacts,
  takes, attached or forked workflow export, and project and generation export
  (`h3-continuity-api`).

## Always

- Preserve the user's brief, wording, references and requested deliverable. The
  Timeline takes native H3 prompts directly. Story and a writing provider are
  optional, and no cast, canon, style or duration is assumed.
- Continuity features give H3 more to work with; they don't guarantee identity,
  geometry or timing. Watch each render, and especially each join. Report
  technical completion (verified files and frame counts) separately from creative
  acceptance (what the frames actually show).
- Some decisions belong to a person: abandoning a held job, deleting takes, and
  spending GPU time beyond what was asked. Surface them; don't make them yourself.

## Installing the pack

The pack lives in the repository's `skills/` folder and works as a whole, so
install all of it. `python skills/install.py` links every skill folder of the pack
into the agent skill folders that exist (`~/.agents/skills`, `~/.claude/skills`,
`~/.codex/skills`), or into those you name with `--target`. Run it from the copy
of the node that ComfyUI loads, so the skills match the installed code. A link
follows that copy when it updates, and running the script again adds any skill
added to the pack since.
