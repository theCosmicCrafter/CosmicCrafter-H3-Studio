---
name: h3-continuity-references
description: Use when writing an H3 Timeline box's prompt or deciding what H3 sees in that box. That covers native prompt sections (complete or partial) and timed [Shot N] stages, the definition, retention, dialogue and cue-line syntax the Studio's Sections form edits, the t2va/flf2va/ref2va mode rule, @image/@video/@audio mentions, connected references and Timeline pictures from image17 up, first and last frames, timed Shot guides, still candidates and scene anchors, RefMods and FLF2VA with cached RefMods, appearance plates, and replacing or disabling references. Part of the H3 Continuity pack; read h3-continuity-video first.
---

# Prompts, references and guides

## The mode decides how frames are used

Each box runs in one native mode, decided by what it uses (`box_slots` in
`h3_continuity/timeline.py`). Preparation and planning report it per box. The
`flf_refmods: true` override below takes precedence over the default reference rules.

- **`ref2va` by default**: the box mentions any picture other than its own first and last
  frame, any `@video` or `@video_audio`, any `@audio`, hears an audio lane or a
  voice clip, or uses a RefMod.
- **`flf2va`**: the box has a first frame, a last frame or an endpoint guide, and
  nothing that makes it `ref2va`. It is also `flf2va` with `flf_refmods: true`
  (see below).
- **`t2va`**: none of the above.

How frames are pinned differs by mode:

- In **`flf2va`**, H3 knows the first and last frames as endpoints and **works
  toward the last frame**, so the motion arrives at it smoothly. In an exact box
  that drops frames, the last frame stays a true endpoint only when the first frame
  is a frame-0 guide, or with cached RefMods. With a `first` picture it is inserted
  as a guide on the last played frame.
- In **`ref2va`**, the first and last frames are **inserted as guides** at frame 0
  and the last played frame. The video doesn't build toward them, so a box whose
  start or end must be exact can jump or flash there.
- **Shot guides** (timed `previews` inside a box) are inserted frames in every mode.
  H3 follows them at their frame but moves freely between them, and doesn't work
  toward them. Many Shot guides in a short box look choppy. Use one where a
  substantial change must land, or split the box there (see `h3-continuity-joins`).
- A **continuing box** ignores `first`, because its opening comes from the carried
  frames and the previous box's last image, which is placed as a guide at its first
  new frame. An explicit guide at that frame takes precedence.

So before adding audio, a reference picture or a guide to a box with endpoints,
check which mode it will run in, including the cached-RefMod override. Image or
audio references alone do not rule out `flf2va`.

## Native prompt structure

- `t2va` and `flf2va` prompts have `integrated_multimodal_description:` with one or
  more `[Shot N]` stages, then `overall_soundscape:` and `non_diegetic_music:`
  (audience-only music, or `N/A`).
- `ref2va` prompts have six sections: `subject_definitions:`, `summary:`,
  `retention_analysis:`, `detailed_description:`, `overall_soundscape:` and
  `non_diegetic_music:`. Read the `ref` guide for each section's contract and the
  `  base` guide for the others. Both are MiniMax's guides, installed optionally on
  the host.
- A box's `prompt` is the only saved prompt content, and H3 receives it as
  written. It may hold just the sections it needs (for example only
  `subject_definitions:` and `detailed_description:`). The Studio's Sections form
  edits any recognized subset, never adds empty sections or `N/A`, and keeps
  everything else (unknown `snake_case:` sections, duplicated headers, unfamiliar
  wording) as Existing text. Write fields in the forms below so a person can edit
  them there.
- `[Shot 1]` has no timestamp. Each later `[Shot N]` starts `At MM:SS.mmm,` and
  those starts must increase, land on distinct frames and stay inside the box's
  played length. In a continuing box the timestamp is on H3's clock, which includes
  the carried frames: native seconds = playback seconds + carried frames / 24. A
  stage whose time falls inside the replay is left as written. After the time,
  `the camera cuts to a new shot.` or `the view continues without a cut.` marks
  the transition; other wording is kept as custom.
- Field syntax the Studio reads and writes:
  - Definition: `<Subject 1> is Mara in a blue coat; appearance reference: @image17`
    (zero or more `; <role> reference: @slot` sources). A standalone picture,
    video or audio definition uses its stable slot, `@image17 is the opening frame.`
  - Summary: `[keyframe completion + reference generation] One paragraph.` The
    bracketed task types are optional.
  - Retention: `<Subject 1> (appears in [Shot 1], [Shot 3]): fully_preserved -
    Her coat stays blue.` or `@image18 ([Shot 1] first frame): weak_reference -
    …`. Visual markers are `fully_preserved`, `partially_preserved`,
    `attribute_transfer` and `weak_reference`. Audio markers are `fully_copy`,
    `partially_copy`, `reference` and `weak_reference`. Other markers are kept but
    flagged as outside H3's vocabulary.
  - Typed dialogue (the box's `dialogue` is `manual`):
    `<Subject 1> (S1), quietly, says: <d>[English] Hello.</d>`, with `sings` or
    `says in an off-screen voiceover` (followed by `while the corresponding
    on-screen characters' lips remain completely closed.`). Speaker IDs like `S1`
    stay stable across shots.
- Optional detail cues are plain lines inside a shot, after its description, one
  per line start (outside `<d>`): `Style:`, `Composition:`, `Action:` (or `Action 1:`,
  `Action 2:`…), `Camera movement:`, `Camera speed:`, `Camera amplitude:`,
  `Dialogue:`, `Scene sound:` and, behind the form's Advanced switch, `Initial state:`,
  `Trigger:`, `Contact:`, `Reaction:`, `Shot size:`, `Camera position:`,
  `Camera direction:`, `Camera subject:`, `Focus:`, `Effect N trigger:`,
  `Effect N:`, `Effect N motion:`, `Effect N response:`, `Physical response:`,
  `Lighting:`, `Light direction:`, `Colour and contrast:`, `Reflections:`,
  `Atmosphere:`, `Materials:`, `Depth of field:`, `Gaze:`, `Expression:`,
  `Breathing:`, `Posture:`, `Hands:`, `Continuity:`, `Recovery:` and
  `End state:`. A value runs until the next cue (the Studio indents its
  continuation lines two spaces). A repeated cue is left as plain text. Cues are a Studio editing convention, not an H3 format
  requirement; use them only where they help. `h3_inspect` `prompt_fields` shows
  how the form reads a prompt; `unstructured_text` counts what it cannot edit as fields.
- Dialogue and sung words go in `<d>…</d>`. Visible on-screen text is timed text
  (see `h3-continuity-sound`), never `<d>`.
- Give each distinct action or view its own `[Shot N]` with time to play. A turn, a
  gaze change or a step needs playable time. Name the camera move and its speed
  when it matters; quiet holds and static framing are valid.
- The Timeline's shared `prompt` goes before every box's prompt and every bridge's:
  say style, setting and who `@image1` is there once.
- Text can't guarantee pixels. For exact prop counts or strict start and end poses,
  use accepted first and last frames.
- `semantic_boxes` (external preparation and the API) can carry the structured
  prompt form for a box, compiled by H3. Leave that box's native `prompt` empty.
- Inspect what H3 will actually receive: the Studio's **Effective H3 prompt**, or
  `effective_prompt`, `tags` and `text_window` in preparation and plan inspection.

## References and mentions

| Source | Slots | Mention |
| --- | --- | --- |
| Connected images | `images.image1` to `image16` | `@imageN` |
| Timeline pictures | `pictures[]` `{slot, file, title}` from `image17` up, no upper limit | `@image17`… |
| Videos | `videos.video1` to `video3` (24 fps frames) | `@videoN` (visual track) |
| Video soundtracks | `video_audios.video_audio1` to `3`, paired with the same-numbered video | `@video_audioN` (also selects its video) |
| Audio | `audios.audio1` to `audio3`, shared with audio lanes and audio RefMods | `@audioN` |
| Voice clips | `voice_clips`, from `audio4` up | sent by H3 Story (see `h3-continuity-sound`) |

- A box sends H3 at most **9 pictures**, 3 videos and 3 audios. Only what a box
  mentions, or uses as first or last frame, is sent. Mentions become native tags per
  box (`<Picture N>`, `<Video N>`, `<Audio N>`), and preparation reports the mapping
  in `tags`.
- Timeline pictures are uploaded files (ComfyUI `input/h3_pictures`, or API
  `picture` assets) with a `title` that names them everywhere. Name them in `first`,
  `last`, mentions and the bible. A box loads only the pictures it uses, and one
  whose file is missing stops with a message naming the box, picture and file.
- `disabled_refs` lists slots that aren't sent. Their mentions read as a plain
  description of the subject or sound, and enabling them again restores them.
  `reference_replacements` swaps a slot's source for another of the same kind:
  mentions, frames and Cast pictures follow, and a video's paired soundtrack follows
  it.
- The Timeline node's `image_1`, `image_2`… outputs carry the selected box's final
  `<Picture N>` pixels, useful for feeding a still generator or an upscaler.
- Without an `audio_vae` connected to the Timeline, `@audio` mentions only label the
  prompt.

## First frames, last frames and Shot guides

- `first` and `last` name an image slot as the box's endpoints. A **guide** is an
  accepted still on a box's `previews[]`: `shot` (its saved number), `frame` (local)
  and the `guide` file (a PNG in `output/h3_previews`, bound through a `guide`
  asset). A guide on frame 0 or on the last played frame acts as an endpoint, and
  any other is a Shot guide. Guides can sit on any frame, not just the grid.
- On a continuing join, accepting box B's First in the Studio also sets box A's
  Last, so both share the boundary image. If either neighbour has rendered
  material, B becomes a cut instead, and **Use saved predecessor ending** restores
  the continue with the exact saved ending.
- Last targets the last delivered frame, after any exact-length trim.
- A guide can carry a lettering contract (`visible_text`, `text_contract`). Rendering
  stops when the timed text active there no longer matches (see
  `h3-continuity-sound`).

### Generating stills

Connect the user's own image workflow to the Timeline's `still_image` input: wrap it
in a native subgraph and connect the subgraph's `IMAGE` output. The subgraph's input
names bind it, with no recipe node:

- `prompt` (or `positive_prompt`) and `seed` (or `noise_seed`) are required.
- `width`, `height` and `negative` (or `negative_prompt`) are optional. Without
  `width` and `height` the workflow keeps its own size and a requested still size is
  refused.
- Every `IMAGE` input is one reference picture, filled in subgraph order; their count
  is the most references a still can use. An image input feeding a node that cannot
  run without a picture makes that many references necessary, and the server says so
  before queueing.
- Every other input and widget (steps, sampler, models, LoRAs, megapixels) is the
  user's and is never changed. Text the workflow joins to `prompt` still applies.
- The wording for pictures follows the nodes inside: `<image1>` for Qwen Image 2.1,
  `<Picture 1>` for P-H3-Image and MiniMax H3 Image conditioning, `image 1` otherwise.
  The Timeline node property `h3c_still_reference_label` (with `{index}`) overrides it.
- One node with its own `prompt` and `seed` inputs can connect without a subgraph.

Video rendering never evaluates `still_image`. The older connection still works and
wins when both are connected: a **Still Recipe** node (with `bindings` saying where a
generator's prompt, seed, size and references are), **P-H3-Image Still** or **MiniMax
H3 Image Still** on the Timeline's `still_recipe`. The examples include H3 Fizgig and
Qwen Image 2.1 generators; `examples/qwen_image_21_still.json` is a subgraph for
`still_image`, and `docs/QWEN-STORY-STUDIO.md` describes the bindings.

- **Generate candidates** never changes a render until one is accepted with
  **Use as guide**. Each candidate keeps its prompt, seed and source.
- Candidate generation always uses the selected clip prompt. Shared text, prepared
  still overrides, reference-role prose and generator instructions are not added.
  Edit the clip prompt itself to change candidate text. The server enforces this
  even for an older client. MiniMax image references separately follow the official
  4 MP resize and 32-pixel alignment; requested output resolution stays native.
  MiniMax H3 Image Still's optional `prompt_enhancer` (default `off`) can rewrite the
  prompt with the official templates' Qwen3.5 enhancer; leave it off to keep the clip
  text exact. With references the model edits `<Picture 1>`, so for MiniMax clip
  stills a location or scene-layout sheet is sent as one picture per view (cut at its
  divider lines): a 2 × 2 sheet becomes `<Picture 1>` to `<Picture 4>` instead of a
  grid to copy. Character sheets and Cast-entry stills stay whole.
- Still generation receives relevant Cast images, images explicitly mentioned in the clip prompt, and images
  connected to the image workflow's own image inputs (or to the Still Recipe). Scene anchors and preceding guides are not
  automatically added.
- Saved still-prompt preparation is retained as writing notes, not as a candidate
  prompt override. **Prepare references** (on the
  Cast page) makes reviewable candidates for characters, looks, places and props.
- Arbitrary-view geometry from still generators is experimental. Inspect every
  candidate before accepting it.

## RefMods, cached RefMods and plates

- **RefMods** are references saved as encoded H3 conditioning instead of pixels,
  made with the companion **ComfyUI-MiniMaxH3Mod** pack. They are `refmods[]`
  entries `{slot, name, kind: image|video|audio, strength 0..1, member,
  description}` on their own slots. A RefMod makes a box `ref2va` by default;
  the opt-in FLF2VA path below also accepts RefMods, including audio RefMods.
  A Timeline picture can't share its slot.
- **FLF2VA + cached RefMods** (`flf_refmods: true` on a box, off by default and
  experimental): a box that continues, or has a First picture or accepted First
  guide, and has no raw video converts its first, last and reference pictures
  into reusable RefMods and stays `flf2va`. It keeps endpoint motion while using
  image references, raw audio and existing RefMods, including audio RefMods.
  `@audioN` inputs and audio lanes keep their time-matched reference windows;
  raw audio is encoded with the H3 audio VAE into the same reference blocks as
  REF2VA, numbered before existing audio RefMods. It is not converted into a
  cached image RefMod. Connect an audio VAE for raw audio, and load H3's image
  VAE from a file (VAELoader) for cached image conversion. A fresh box without a
  First cannot use this override. Raw `@videoN` or `@video_audioN` still prevents
  conversion; prepare a video RefMod separately if needed. Use
  `examples/h3_timeline_flf2va_cached_refmods.json` and inspect the resolved mode,
  `tags` and effective prompt rather than inferring the mode from audio presence.
  Do not remove a recording merely to use cached FLF2VA.
- **Appearance plates** change what a reference slot shows partway through the film.
  `plates[]` holds accepted revisions `{id, slot, image}` (image in
  `output/h3_previews`, bound through a `plate` asset). A box's
  `plate_changes[]` `{frame, slot, revision}` switches the slot to a revision from
  that local frame on (`revision: ""` restores the original), and later boxes keep it
  until another change. A box with plate changes starts a new scene for scene
  memory. `plate_edits` are the Studio's editing records; leave them as they are.

## One long video across boxes

To repaint or restyle a long video box by box, connect it to `video1`, add `"video_slices": ["video1"]` to the Timeline and mention `@video1` in each box. Each box then gets only its own window of the video: its Timeline start minus the frames it carries, through every frame H3 generates for it, so the reference lines up with the carried overlap. `video_audio1` is cut the same way. A video too short for a box stops that box with the frames it has and needs.

## Agent still and reference workflow

Use `h3_stills` for sources, import/pin, preparation, candidate generation and
reference catalog/approval. `prepare` returns a graph; `generate` actually submits
one owned candidate and returns a retained receipt. Poll with `h3_job_status`;
results remain proposals even if a person edits the project while they run.
Keep manual prompts, source frame/clock, target, seed, text contracts and candidate
provenance. Explicitly accept/save under the current project revision. Reference
approval returns transformed Timeline data; it does not silently save it.

P-H3-Image Still is an available native recipe generator. Studio resolution uses
the width/height aspect ratio at 8 MP by default, 4 MP for less memory, or custom
dimensions; an explicit request size wins for that invocation. Video size stays
independent. Its ordered `lora_stack` applies model/CLIP strengths to diffusion
and conditioning, with compatible files; an empty stack changes nothing. Inspect
the installed node schema with `h3_inspect` before choosing a recipe/model.
Prepared prompts use generator-specific instructions; keep manually edited
conversion instructions and check staleness before replacing prepared prompts.
See `h3c://docs/MCP.md` for recipe payloads and snapshot requirements.
