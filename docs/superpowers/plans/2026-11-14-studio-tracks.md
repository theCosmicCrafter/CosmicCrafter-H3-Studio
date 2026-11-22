# Studio Tracks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. User selected native implementation here, with one independent review after integration. Steps use checkbox syntax.

**Goal:** Independent video tracks with a compact combined view, expandable lane editing, shared overlap controls and the seven requested Studio UX improvements.

**Architecture:** Keep stable box IDs and the flat box catalog; add explicit track membership and frame placement, resolved by matching pure JS/Python layout modules. Both collapsed output and expanded tracks consume that layout. Route generation through same-track dependencies and assembly through an output edit list, keeping old timelines on their unchanged legacy path until tracks are authored.

**Tech Stack:** Existing ES modules/DOM/CSS, Python dataclasses, PyAV/NumPy/PyTorch CPU media paths, Node tests, unittest and Playwright. No new frontend framework or icon dependency.

**Spec:** `docs/superpowers/specs/2026-11-14-studio-tracks-design.md`

## Global Constraints

- Preserve original projects, stack switches, saved media, reference approval checks and history. No GPU inference or live project mutation is required for implementation verification.
- Independent clip placements use integer frames at 24 fps. Preserve exact lengths and the existing H3 generation grid and context rules.
- Retain separate Timeline and movie clocks for insertion bridges. Never ripple independently placed tracks as a side effect of trimming another clip.
- Upper video tracks win; lower tracks appear through gaps; a complete picture gap is black. Generated sound follows visible picture unless the existing original soundtrack policy or an explicit overlap sound choice applies.
- Icons have accessible names/tooltips/focus; navigation has icon plus label. Desktop targets at least 28px, touch targets 44px. Palette/type/layout follow the spec.
- Preserve all existing local documents. Stamp changed web modules with `node tools/module_versions.mjs --write` before tests that check tags.
- Do not deploy, release, merge or restart ComfyUI as part of this implementation plan.

## Review Focus

1. Interleaved catalog order must never make a clip continue from another track (Tasks 2–3).
2. A missing upper take must be reported as missing, rather than silently exporting the lower clip as if complete (Task 4).
3. Async reference catalog refresh must not select/approve the wrong asset or discard an edit (Task 8).
4. Nonempty lane removal and Undo must restore IDs, source assignments, text attachments and overlap switches (Tasks 1, 5).
5. Insert bridges, older saved clip lengths and partial source footage must share the same time mapping in preview and export (Tasks 2, 4).

## Data contract and ownership

Existing `boxes` stay the render catalog with stable IDs and existing stack `layers`/`switch` data. Track mode adds `tracks: [{id, type, name}]`, ordered bottom to top for video; `type` is `video`, `audio` or `text`. Every box in track mode has `track` and nonnegative integer `start` (Timeline frames). Audio records retain seconds and native slots, adding `track`. Text mode adds `text_lanes: [{track, attachment}]`, where attachment uses the existing timed-text schema. A legacy single `timed_text` attachment migrates losslessly when track mode is entered. No track fields are written merely by opening an old project. Clip duration resolution is injected into pure layout helpers, avoiding a tracks/timeline import cycle.

Use reader token `timeline-tracks-1` whenever any track-mode data exists, including empty tracks. An explicit `enableTracks(state)` converts legacy positions and assigns existing audio/text to typed tracks atomically; stable clip/layer IDs and segment files stay unchanged. Python validates the same representation. The first implementation task includes a shared fixture to lock down this contract.

New `overlap_switches` records are `{id, from, to, at, fade, sound}`: `from`/`to` are clip IDs on different tracks, `at` is a Timeline frame, `fade` is 0–12 frames with the current centered fade convention, and `sound` is `screen` or one of the two IDs. A record overrides default visibility across that pair's overlap: from before the switch, to after. The entire fade must fit the overlap; records involving a common clip cannot compete over the same interval. A third higher clip may occlude both; it keeps priority. Do not flatten existing internal stack switches into these records.

New modules own layout, clock mapping and overlap resolution only. Existing timeline modules keep H3 rules; existing media code keeps encoding. Use helpers from the new modules rather than copying sums or predecessor searches into consumers.

## Task 1: Persist and validate typed tracks (STU1a)

**Files:** create `web/h3c_tracks.mjs`, `h3_continuity/tracks.py`, `tests/fixtures/timeline_tracks.json`, `tests/web/tracks.test.mjs`, `tests/python/test_tracks.py`; modify `web/h3c_timeline_model.mjs`, `h3_continuity/timeline.py`, `h3_continuity/timeline_api/contracts.py`.

**Interfaces:** JS `enableTracks(state): void`, `addTrack(state,type): string`, `removeTrack(state,id): void`, `trackContents(state,id): {clips,audio,text}`, `placements(state): Placement[]`, `predecessor(state,boxId): string|null`, `durationFrames(state): number`. Python matching pure functions operate on validated raw data; `validate(parsed,data): None` fills parsed track/placement/text/overlap fields. Placement is `{id,track,start,end}` with half-open frame bounds; durations come from existing played-frame rules. IDs remain globally unique.

- [x] Write shared fixture assertions: legacy A=48/B=72 becomes V1 A[0,48),B[48,120); V2 C[24,72) gives duration120, predecessor(B)=A and predecessor(C)=null. Empty A/T/V tracks survive save/load. A legacy stack and text attachment survive conversion unchanged.
- [x] Add rejection cases: duplicate IDs, unknown/wrong-type tracks, boolean/negative/fractional starts, overlapping same-track clips, invalid overlap endpoints, unsupported feature token, nonempty lane removal leaving dangling overlap/reference records. Verify cancel leaves serialization byte-identical and removal/Undo restores it.
- [x] Run `node --test tests/web/tracks.test.mjs` and `python -m unittest tests.python.test_tracks`; observe the missing behavior fail, then implement validation/migration/edit helpers and run green.
- [x] Ensure parse/serialize without tracks remains byte-identical in existing model fixtures. Add API schema acceptance/rejection for the feature; no server silently drops track fields.
- [x] Stamp modules, run the full suite, commit only this task's implementation/tests/docs.

## Task 2: Authoring and output clocks (STU1b)

**Files:** extend track modules/tests; modify `timeline.py` (`box_start`, `audio_box_spans`, `video_window`), `h3c_timeline_model.mjs` (`totalFrames`, `audioBoxSpans`, `globalFrame`), `h3_continuity/bridges.py`, `web/h3c_bridges.mjs` and callers found by the audit.

**Interfaces:** `startFrame(state,id): int`, `outputFrame(state,timelineFrame): int`, `timelineFrame(state,outputFrame): {frame,bridgeId|null}`, `outputSpans(state): Span[]`. Span identifies Timeline interval or inserted bridge, with output start/end. Python exports snake_case equivalents. Frames inside an inserted bridge map to its paused Timeline boundary. Keep existing continuous/box-bound soundtrack policies.

- [x] Audit every prefix-duration sum and `index - 1` consumer; save categorized inventory with changed paths in the task ledger. Include Story, Cast, visual memory, reference plates, guide anchors, still preparation, audio locks, dialogue and API plans.
- [x] Test A[0,48),B[48,120),C[24,72) with a 12-frame insertion at48: Timeline duration120, movie132; C's source frame24 resumes after the bridge. Forward/inverse mappings agree outside insertion; inside it reports the bridge. Replacement coverage adds zero frames.
- [x] Test audio conditioning for C uses Timeline frame24, not its catalog prefix; text/beat/guide windows use the same start. Existing no-track bridge/audio fixtures stay unchanged.
- [x] Observe red, implement pure mappings, replace clock consumers, rerun targeted tests then full suite. Commit the coherent clock change.

## Task 3: Generation dependencies, memory and reuse (STU1c)

**Files:** `timeline.py`, `timeline_prepare.py`, `timeline_node.py`, `regeneration.py`, `visual_memory.py`, `cast_memory.py`, `layers.py`, `store.py`, `h3c_timeline_model.mjs`, relevant API planning/jobs/native queue consumers; create `tests/python/test_track_generation.py` and extend regeneration/layer tests.

**Interfaces:** `tracks.generation_view(parsed, box_id) -> (Timeline, local_index, original_ids)`: a same-track chronological view retaining absolute placements and project reference context. Explicit memory IDs resolve in the project catalog; automatic scene/previous memory follows the track. Public clip numbers remain catalog numbers. Add one centralized dependency lookup for all native latent/audio carry; never use a view's local number to look up another catalog segment.

- [x] Test catalog order A(V1),C(V2),B(V1): B continues A, uses A's saved latent and carry; C is fresh. A gap or first-on-track Continue raises a named error. Dropped-frame conflicts and legacy stack Cut restriction apply to the actual same-track predecessor.
- [x] Test moving C changes its conditioning window and invalidates affected generation, but changing only track priority invalidates assembly rather than unrelated native latents. Explicit memory rejects future Timeline moments even when their catalog indices are earlier.
- [x] Test dependency ordering in render-next/remaining/API plans; no hidden lower take substitutes for an unrendered dependency. Keep managed-job restrictions explicit for any unsupported unit, with a reason before queue submission.
- [x] Observe red, implement generation view and dependency plumbing, audit all inventory entries, run targeted generation/regeneration/continuity tests and full suite; commit.

## Task 4: Composed output, overlaps and independent text (STU1d)

**Files:** create `h3_continuity/track_output.py`, `tests/python/test_track_output.py`; modify `nodes.py`, `stacks.py`, `partial_video.py`, `media.py`, `audio_tracks.py`, `timed_text.py`, Timeline status/API artifact consumers.

**Interfaces:** `track_output.edit_list(parsed, manifest, available=None) -> list[OutputSpan]`; span records output frames, source clip ID and source offset or gap/bridge, optional pair/fade weights and selected audio. `build(folder,name,parsed,manifest,crf,mode) -> (record,notes)`, where mode is full/so_far/partial. All modes consume the same visibility and clock resolver; cache keys include placements/order/switches/source stamps, not only catalog index. Resolve internal legacy stacks before composing independent tracks.

- [x] Use committed CPU video fixtures: A lower90frames, B upper[27,60) yields A27+B33+A30; an all-track gap yields black/silence. Default total duration matches latest clip end plus bridges. Assert every output frame's source index, output fps, audio sample placement and duration.
- [x] Test explicit overlap switch at27 with fade6 uses old centered weights; fixed-source and screen sound match existing stack choices. Test third-track occlusion, shared-clip conflicting controls, unequal source lengths, mixed native resolutions/fps and boundary fades. Compare decoded fixture frames, not only edit-list structure.
- [x] Test missing upper footage: full export refuses with named missing clip; partial output uses a labeled missing-footage slate for an unavailable visible upper clip (source-footage fallback remains only where explicitly provided); so-far ends at the first missing visible interval and reports it. No full export silently falls through to lower footage. Keep existing saved-length/source-window rules rather than stretching media.
- [x] Test two text attachments preserve cues, sync anchors and enable state independently; both reach conditioning in overlapping boxes without replacing one another or exceeding prompt limits silently. Legacy singleton behavior stays unchanged.
- [x] Observe red, implement output adapters and CPU compositor reuse, run existing assembly/stacks/audio/text/partial acceptance tests plus full suite; commit.

## Task 5: Expandable timeline, lane lifecycle and snapping (STU2a)

**Files:** create `web/h3c_track_editor.mjs`, `tests/web/track_editor.test.mjs`, `tests/browser/studio_tracks.py`; modify `h3c_timeline_editor.mjs`, `h3c_audio_lanes.mjs`, `h3c_studio.mjs`.

**Interfaces:** `TrackEditor(editor)` owns lane rendering, expand/collapse, header/add/delete and placement gestures. Calls Task1 edits through the existing commit/Undo gate. `snapPlacement(state,{id,track,start,end,tolerance,bypass,playhead}) -> {start,end,guide|null}` is pure. Selection stores stable clip/track/overlap IDs.

- [x] Test collapsed combined row and expanded individual rows resolve to the same edit list and selection. Add video/audio/text icons create typed lanes; audio/text cancelled import leaves deletable empty lanes. Preserve audio-slot limits with an actionable explanation.
- [x] Test nonempty deletion confirmation cancel/accept, last video track removal, overlap cleanup and Undo/Redo. Never delete files. Read-only mode blocks every new edit path.
- [x] Test drag snap to another track's left/right edges and playhead; Shift bypass, pixel-to-frame zoom mapping, negative start clamp, collisions and frame-grid resize. Move earlier/later and Duplicate operate on the selected track without changing another track's times.
- [x] Observe red, implement pure gestures then DOM wiring, run browser interactions including empty/populated tracks and interrupted drag. Fill available timeline height; maintain sticky headers, one shared horizontal ruler/scroll and resize divider; commit after full suite.

## Task 6: Icon system, toolbar and grouped tabs (STU2b)

**Files:** create `web/h3c_icons.mjs`, `tests/web/studio_navigation.test.mjs`; modify `h3c_studio.mjs`, `h3c_timeline_editor.mjs`, `h3c_frame_images.mjs` and project settings integration.

**Interfaces:** `icon(name): SVGElement`, `iconButton(name,label,action): HTMLButtonElement`, `setIconLabel(button,label): void`; icon SVG is aria-hidden, button name is authoritative. Preserve dynamic labels/counts and disabled reasons without replacing icons with text during refresh.

- [x] Read impeccable craft-floor immediately before UI edits. Test top toolbar, timeline toolbar and clip actions retain correct callbacks, names, busy/disabled states and keyboard access. Generate requests one take; remove the header count input.
- [x] Test semantic Viewer/Story/Cast/References tabs and existing deep links; grouped References includes both Pictures/RefMods. Keyboard arrows/Home/End move among tabs, focus and panel IDs agree.
- [x] Move reusable still conversion instructions to Project settings by reusing existing host fields/storage, test edits persist and detached Studio regions return correctly on close. Do not change the clip-only/no-hidden-text still submission policy.
- [x] Observe red where behavior changes, implement shared SVG icons and toolbar/tab layout, stamp modules, run targeted/full tests; commit.

## Task 7: Contextual Resolve-style inspector (STU2c)

**Files:** `h3c_studio.mjs`, `h3c_timeline_editor.mjs`, `h3c_audio_lanes.mjs`, new `tests/web/track_inspector.test.mjs`; extend browser smoke.

- [x] Test stable selected clip header and visible icon actions; Prompt/Shots/Takes/Settings tabs preserve form values and selection. Selecting audio/text/overlap swaps context without displaying stale clip controls.
- [x] Expose the overlap pair, switch frame, fade and sound controls using Task4 validation; show bounds/reasons before commits. Property disclosures use full-width headings and aligned label/value controls; preserve all existing mode/reference/endpoints/length/memory controls.
- [x] Test narrow inspector, long labels, disabled fields and invalid transition edits. Observe red, implement, visually check desktop/mobile with populated content; commit after required suite.

## Task 8: Cast preparation master/detail (STU2d)

**Files:** `web/h3c_reference_preparation.mjs`; new `tests/web/reference_preparation_navigation.test.mjs`, extend reference preparation/browser tests.

- [x] Test category filters, thumbnail/status list, focused asset, Generate missing inclusion, generator settings and batch stop. Test uploaded-ready versus candidate-needs-approval status remains truthful.
- [x] Test async refresh, asset disappearance, stale candidate fingerprint, upload failure and an input edit during refresh. Selection/focus remain on stable asset IDs; obsolete responses cannot approve another asset.
- [x] Replace repeated full forms with master/detail. Keep Generate/Upload/Use as reference explicit; move seed/dimensions into Advanced, Add object opens its form on demand. Phone list/detail uses Back with retained selection.
- [x] Observe red, implement without changing backend approval policy, run reference unit/browser and full suite; commit.

## Task 9: Integration, visual review and documentation (STU2e)

- [ ] Run `node tools/module_versions.mjs --write`, `node tests/run.mjs`, `uv run --with-requirements requirements-docs.txt python -m mkdocs build --strict --site-dir .tmp/studio-tracks-docs`, `git diff --check`. Record actual counts/failures.
- [ ] Run isolated Playwright integration against realistic multi-track fixtures at 1440x1000, 1024x768 and 390x844. Batch interaction/capture checks for the seven requested areas, expanded/collapsed tracks, empty/loading/errors, long content, keyboard focus and deletion dialogs. Inspect every saved capture.
- [ ] Follow impeccable's rendered-review/detector/documentation workflow for changed surfaces. Preserve the pinned graphite direction; document tokens and behavior, not a marketing redesign. No public preview/browser tools unless the user asks for browser work.
- [ ] Perform one independent whole-change review, as user selected. Give the reviewer original request, design/plan, full diff, timing inventory, test results and all viewport captures. Fix material findings with targeted regression coverage and repeat affected verification; no per-task delegate reviews.
- [ ] Update guide pages for adding/removing lanes, expand/collapse, snapping, overlap visibility and inspector/reference workflows; add CHANGELOG entry. Check old-project migration and actual output with CPU fixture export one last time.
- [ ] Checkpoint roadmap with exact branch/head, changed files, verification and remaining limits. Deliver the implementation for review; PR/merge/release/deployment is a separate action.

## Execution gate and first action

The user approved the design direction and selected native implementation with one final review. The writing-plans skill still requires review of this concrete plan before implementation. After approval, use executing-plans, isolate work without copying unrelated dirty files, run baseline, and begin Task1's shared fixture and failing tests. Do not start on icons as a substitute for the track model.
