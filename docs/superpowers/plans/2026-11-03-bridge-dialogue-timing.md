# Recording-anchored dialogue and replacement bridges Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task (the user forbids subagents). Steps use checkbox (`- [ ]`) syntax for tracking. The plan's author executes it inline with TDD; each task's code lands in its own commit, so the plan records exact interfaces, behaviours and test assertions rather than duplicating the code.

**Goal:** Let a Timeline with a fixed (locked) recording gain transitions without dialogue drift: dialogue cues bound to the recording drive box prompts and speech protection, and a *replacement* bridge regenerates a reviewed region around a cut, delivering exactly the frames it removes.

**Architecture:** Two pure-Python models own the rules: `dialogue.py` (cue identity, recording binding, source→sequence→generation clocks, `<d>` compilation, protection) and `replacement.py` (coverage geometry on the native 17k+5 grid, protection checks, review/region keys, assembly windows). Torch-side code builds endpoint latent windows (`latents.window`, exact slice when chunk-aligned, VAE decode→crop→encode otherwise), the render path saves candidates beside the boxes (`replacement_candidates.py`), and full-video assembly plays trimmed box windows plus the selected candidate while placing locked audio on the unchanged sequence clock. The Studio consumes server-computed plans from the Timeline status; it keeps no second timing model.

**Tech Stack:** Python 3.13 (ComfyUI portable, torch, PyAV), stdlib `unittest`; browser ES modules tested with `node --test` (Node 24).

## Global Constraints

- A picture-only replacement never cuts, moves, stretches, loops or inserts silence into a locked recording.
- Delivered replacement frames equal the frames removed (`L + R`); total duration and every later box start stay unchanged.
- Original media and takes are never trimmed or overwritten; candidates are stored beside them.
- Automatic replacement never touches protected visible speech; explicit voiceover may continue over replacement pictures. Unknown portrayal or unchecked timing is not silence.
- The user confirms the exact region before generation and selects a reviewed candidate before it plays.
- Failure, stale or missing evidence, or unsupported geometry never removes protection, expands coverage, moves audio or falls back to inserting time.
- Existing projects keep insertion semantics; missing fields never mean replacement. Files with new semantics carry `"requires"` naming the minimum reader feature.
- Delivered replacement durations are `12`, `29` or `46` frames (`17j + 12`), the only interiors that keep `C + N + E` on the 17k+5 grid with canonical contexts.
- Endpoint construction is unvalidated with real generation until feature B1.11 passes; the Studio labels it experimental and nothing activates without explicit selection.
- No subagents; no mutation of the user's running ComfyUI service.

## Commands

- Python tests: `C:/Users/ricar/ComfyUI/ComfyUI_windows_portable/python_embeded/python.exe -m unittest discover -s tests/python -t .`
- Browser-model tests: `node --test "tests/web/*.test.mjs"`
- Syntax: `node --check web/<file>` for edited browser modules.

## File Structure

| File | Responsibility |
| --- | --- |
| `h3_continuity/dialogue.py` (new) | Cue validation, recording binding/state, alignment keys, sequence/generation projection, `<d>` compile/insert, prompt conflicts, protected intervals, lock conflicts. Pure. |
| `h3_continuity/replacement.py` (new) | Replacement record helpers, coverage geometry (`J`, `L`, `R`, context `C'`, ending `E'`, source windows), options/proposal, protection checks, static/region/recipe keys, per-box trims. Pure. |
| `h3_continuity/replacement_candidates.py` (new) | Manifest candidates: stems/ids, saving entries, validity, selection state, active windows for export, previews. Uses `store`. |
| `h3_continuity/timeline.py` | Parse `dialogue`, `locked`, `requires`, box `dialogue`, replacement bridge records; compile cues into box plans; layout identity. |
| `h3_continuity/latents.py` | `window(video, audio, start, frames, vae)` endpoint extraction. |
| `h3_continuity/bridges.py` | Insertion-only helpers skip replacement records. |
| `h3_continuity/timeline_node.py` | Replacement render plan/review gate; status payload for replacements, dialogue and conflicts; record `replace` for export. |
| `h3_continuity/nodes.py`, `media.py`, `store.py`, `audio_tracks.py` | Save candidates; window-aware video/audio assembly and fingerprints; previews. |
| `h3_continuity/takes.py` | Bridge-take functions ignore replacement records. |
| `h3_continuity/timeline_api/contracts.py`, `planning.py` | Schema for new fields; non-accumulating ranges; replacement units explicitly Studio-only. |
| `web/h3c_timeline_model.mjs` | Parse/serialize new fields, `requires`, replacement edits, insertion totals. |
| `web/h3c_bridges.mjs` | Bridge panel with Insert/Replace modes, region review, candidates. |
| `web/h3c_dialogue.mjs` (new) | Cue editor and pure helpers (transcript/Story seeding, alignment toggles). |
| `web/h3c_audio_lanes.mjs`, `web/h3c_timeline_editor.mjs`, `web/h3c_studio.mjs` | Lock toggle, conflict banner, summary line, region/candidate playback. |
| `tests/python/*`, `tests/web/*` (new) | Deterministic coverage. |
| `scripts/validate_replacement_vae.py` (new) | CPU validation of endpoint windows against the real H3 video VAE. |
| `guide/continuity/joins-and-bridges.md`, `guide/sound/dialogue.md` (new), `mkdocs.yml`, `CHANGELOG.md` | User documentation. |

---

### Task 1: Test harness (B1.1)

**Files:** Create `tests/__init__.py`, `tests/python/__init__.py`, `tests/python/test_harness.py`, `tests/web/harness.test.mjs`.

- [ ] Write `test_harness.py` asserting `timeline.snap_frames(100, True) == 107` and `timing.tokens_for_frames(39) == 12`; write `harness.test.mjs` asserting `snapFrames(100, true, 39) === 107` from `web/h3c_timeline_model.mjs`.
- [ ] Run both commands; expect 1 Python test and 1 Node test passing (they characterise existing behaviour, so they pass immediately; this task only proves the runners work).
- [ ] Commit `test: add unittest and node test runners`.

### Task 2: Dialogue cue model, binding and clocks (B1.2)

**Files:** Create `h3_continuity/dialogue.py`, `tests/python/test_dialogue.py`. Modify `h3_continuity/timeline.py` (parse `dialogue`, audio `locked`, `requires`, box `dialogue`).

**Interfaces (produces):**
- `dialogue.validate(value) -> dict | None` — raises `ValueError("H3 Timeline: dialogue …")`.
- `dialogue.binding(cue, audio_clips, disabled) -> ("bound"|"missing"|"changed", clip|None)`.
- `dialogue.alignment_key(cue) -> str`; `dialogue.is_aligned(cue) -> bool`.
- `dialogue.placed(cue, clip) -> dict` with `source=(s,e)`, `sequence=(t0,t1)` seconds, `frames=(a,b)` outward-rounded, `cut: bool`, or `None` when outside the placed window.
- `dialogue.projected(timeline) -> list[dict]` per cue: `id, state, cut, aligned, sequence, frames, portrayal spans in sequence frames`.
- `dialogue.lock_conflicts(timeline) -> list[str]`.
- `timeline.Timeline.dialogue` (validated dict or None); `Box.dialogue` (`"cues"` default or `"manual"`); `REQUIRES = {"replacement-bridges-1", "dialogue-cues-1"}`.

**Tests (assert exactly):**
- Mapping `sequence = clip.start + source - clip.source_start`: clip `start=2.0, source_start=10.0, duration=30`, cue `12.5–14.0` → sequence `4.5–6.0`, frames `(108, 144)`.
- Outward rounding: sequence `1.01–1.02` s → frames `(24, 25)`.
- Cue partly outside the placed window → `cut=True`, clipped sequence; cue fully outside → `placed` returns `None`.
- File changed on the slot → `binding` returns `"changed"`; slot removed → `"missing"`; disabled slot → `"missing"`.
- `alignment_key` changes when text, start, end or recording file changes; unchanged by speaker/portrayal.
- Validation rejects duplicate ids, `end <= start`, unknown portrayal, spans outside the cue, overlapping spans, `<d>` inside text.
- `timeline.parse` rejects `locked: true` without `file`; rejects unknown `requires` feature with a "newer H3 Continuity" message; accepts box `dialogue: "manual"`.
- `lock_conflicts`: locked clip not `in_full_video` → message naming the slot; locked clip with an insertion bridge → message naming the bridge's box and added seconds; no lock → `[]`.
- Two locked recordings with different sample placements both project independently (no priority).

- [ ] Write the failing tests; run; expect `ModuleNotFoundError: h3_continuity.dialogue` / assertion failures.
- [ ] Implement `dialogue.py` and the parse changes.
- [ ] Run Python tests; expect all pass. Commit `feat: add recording-bound dialogue cue model`.

### Task 3: Cue compilation into box prompts (B1.3)

**Files:** Modify `h3_continuity/dialogue.py`, `h3_continuity/timeline.py` (`plan_box`, `layout_key`); test `tests/python/test_dialogue_compile.py`.

**Interfaces:**
- `dialogue.box_events(timeline, index, context) -> list[dict]` with `start_ms, end_ms` on the box generation clock (origin `box_start - carried/24`), `continuing`, `continues_after`, `speaker`, `text`, `language`, `portrayal`.
- `dialogue.block(events) -> str`; `dialogue.insert(prompt, mode, events) -> str` (inside `integrated_multimodal_description` / `detailed_description`, else appended).
- `dialogue.prompt_conflict(timeline, index, context) -> str` — `""` or a reconciliation sentence when the box's own prompt has `<d>` and bound cues cover it (box not `manual`).
- `dialogue.digest(events) -> str` added to `layout_key` as `"dialogue"` when non-empty.

**Tests:**
- Box 2 of `[48, 48]` frames, continuing, context 39: a cue at sequence `2.5–3.0` s → `start_ms = round((2.5 - (2.0 - 39/24)) * 1000) = 2125`.
- A cue spanning the boundary between two boxes appears once as an event in each box: first with `continues_after=True`, second with `continuing=True`; `block` uses "finishes the line already in progress" for the continuation and never repeats it as a fresh line.
- Voiceover line compiles with "off-screen voiceover" and "lips remain closed"; on-screen with "says".
- A cut cue (clipped by the placed window) makes `plan_box` raise naming the cue and slot.
- Manual box ignores cues; a box prompt with `<d>` plus covering cues raises the reconciliation sentence from `plan_box`; unmanaged prompt with `<d>` and no cues renders unchanged.
- `layout_key` changes when a covering cue's text changes and not when only `aligned` changes.

- [ ] Failing tests → implement → pass. Commit `feat: compile dialogue cues into box prompts`.

### Task 4: Replacement records and coverage geometry (B1.4)

**Files:** Create `h3_continuity/replacement.py`, `tests/python/test_replacement.py`; modify `h3_continuity/timeline.py::_bridges`, `h3_continuity/bridges.py` (insertion helpers skip replacement records).

**Interfaces:**
- Record: `{"before", "mode": "replace", "left": L, "right": R, "seed", "prompt", "review"?, "selected"?}`; `L + R in (12, 29, 46)`, `L, R >= 0`.
- `replacement.is_replacement(bridge) -> bool`; `replacement.insertions(timeline)`, `replacement.replacements(timeline)`.
- `replacement.geometry(timeline, bridge, context) -> Geometry` dataclass: `index, join, left, right, frames, start, end` (sequence frames), `context_frames` (C'), `ending_frames` (E'), `left_window=(box index, run start, C')`, `right_window=(box index, start, E')`, `generated = C' + N + E'`, `problem` ("" when supported).
- `replacement.protections(timeline) -> list[dict]` (`start, end, kind, id, label, stale`), using `dialogue.projected` plus `dialogue.observed`.
- `replacement.check(timeline, bridge, context, takes=None) -> str` (geometry + protection + unchecked cue problems).
- `replacement.options(timeline, index, context, takes=None) -> list[[N, [valid L…]]]`; `replacement.proposal(...) -> (N, L) | None` (prefer 29, 12, 46; L closest to N/2).
- `replacement.static_key(timeline, bridge, known) -> str`; `replacement.region_key(static, before_link, after_link) -> str`; `replacement.recipe(timeline, bridge) -> str`.
- `replacement.trims(timeline, active_ids) -> dict[index, (start_cut, end_cut)]`.

**Tests:**
- Boxes `[107, 107]` (fresh, fresh), context 39, `L=14, R=15`: `join=107, start=93, end=122, C'=39, E'=39, generated=107`, left window `(0, 54, 39)`, right window `(1, 15, 39)`.
- Continuing box A (`[107, 68]` then cut B): left window run coordinates include A's carried 39 frames.
- `L + R = 30` rejected at parse; `left: -1` rejected; record without `mode` keeps insertion meaning and still requires `frames`.
- Insufficient room: boxes `[22, 107]`, `L=20` → problem mentions leaving a frame of box 1; `R` leaving fewer than 5 frames of box 2 → problem.
- Overlap: replacements at both ends of a 30-frame box with `R1 + L2` > available → problem on the later one.
- On-screen cue inside `[start, end)` → problem naming speaker and seconds; voiceover cue inside → no problem; unknown portrayal → problem; unchecked on-screen cue anywhere in the two boxes → problem asking to check it; recording changed → problem.
- `options` excludes protected allocations; `proposal` returns `(29, 14)` with no cues and a shifted allocation when speech protects the right side.
- `static_key` changes with L/R, a relevant cue, locked placement and settings; unaffected by prompt/seed; `recipe` changes with prompt/seed.
- `trims` for active replacement → `{0: (0, 14), 1: (15, 0)}`.
- `bridges.splice`, `bridges.states` and `bridges.problem` ignore replacement records without raising.

- [ ] Failing tests → implement → pass. Commit `feat: plan replacement bridges within existing duration`.

### Task 5: Endpoint windows and replacement render path (B1.5)

**Files:** Modify `h3_continuity/latents.py`, `h3_continuity/timeline_node.py` (`bridge` dispatch, `_replacement` render), `h3_continuity/nodes.py` (`save_replacement`), create `h3_continuity/replacement_candidates.py`; tests `tests/python/test_latent_window.py`, `tests/python/test_candidates.py`.

**Interfaces:**
- `latents.window(video, audio, start, frames, vae=None) -> (video_tokens, audio_ticks)`; chunk-aligned `start % 17 == 0` slices tokens `[start/17*5, +tokens)`; otherwise decodes the covering chunk span, crops `[start, start+frames)`, re-encodes. Audio ticks start `round(start*40/24)` clamped inside the source.
- `replacement_candidates.candidate_id(box, created, seed, region) -> str`, `stem(box, cid)`, `entries(manifest, box)`, `state(folder, manifest, timeline, bridge, known, context, done) -> dict`, `active(folder, manifest, wanted) -> list[(box, entry, L, R)]`, `wanted(timeline, known, context, manifest, folder) -> dict`.
- Render refuses unless `bridge["review"] == region_key`, never archives other candidates, and records `{"replacement", "region", "layout", "from", "to", "left", "right", "played", "seed", "settings"}`.

**Tests:**
- Fake chunk VAE (`encode`: token values carry the first source-frame number of each token group; `decode`: inverse): aligned window `start=34, frames=39` equals a direct token slice and never calls the VAE; unaligned `start=54` calls decode once and encode once and the result's token frame numbers are `54, 55, 59, 63, …` (first token = one frame, then groups of four); window shorter than the source error; audio ticks `[90, 155)` for `start=54, frames=39`.
- Candidate validity: manifest with candidate whose region matches → `active` returns it with its L/R; region mismatch → `stale`; missing files → `missing`; no `selected` → original.
- Saving a replacement candidate appends to `manifest["replacements"]` and leaves an existing selected candidate untouched.

- [ ] Failing tests → implement → pass. Commit `feat: render replacement candidates from reviewed endpoints`.

### Task 6: Assembly with replacements (B1.6)

**Files:** Modify `h3_continuity/media.py` (`build_full_video` windows), `h3_continuity/store.py` (fingerprint windows), `h3_continuity/nodes.py` (`rebuild_full_video` replaced parts, previews), `h3_continuity/audio_tracks.py` (`place` for replacement parts, `place_window`); tests `tests/python/test_assembly.py`.

**Behaviour:**
- Ordered parts: insertion bridges whole; box windows `(start_cut, played - start_cut - end_cut)`; selected candidate `N` frames at the join.
- Copy mode only when every window starts at frame 0; otherwise decode and re-encode.
- Soundtrack placement uses `(frames, inserted)`; replacement and trimmed parts are not inserted, so locked audio keeps its authored clock.
- Generated audio uses `(context + start_cut + count, context + start_cut, waveform, rate)` parts.
- Candidate previews: `<stem>_preview.mp4` (A tail, candidate, B head) and `<stem>_original.mp4` (original frames), up to 48 frames each side, with the same audio rules.

**Tests (real PyAV media, synthetic frames whose colour encodes their index):**
- Two 22-frame boxes, a 12-frame candidate replacing `L=6, R=6`: full video has 44 frames; frames 0–15 come from box A, 16–27 from the candidate, 28–43 from box B frames 6–21.
- Two replacements and one insertion bridge in one sequence: total = sum of boxes + insertion frames only.
- `place` with a 10 s clip and parts `[(16,False),(12,False),(16,False)]` is sample-identical to placing it with `[(44, False)]`; with an insertion bridge it shifts as before (legacy).
- Fingerprint changes when the selected candidate changes.

- [ ] Failing tests → implement → pass. Commit `feat: assemble replacement candidates without moving audio`.

### Task 7: Status, takes and API integration (B1.7)

**Files:** Modify `h3_continuity/timeline_node.py` (`_status`, `request_status`, `execute` next selection), `h3_continuity/takes.py`, `h3_continuity/timeline_api/contracts.py`, `h3_continuity/timeline_api/planning.py`, `h3_continuity/timeline_api/artifacts.py`; tests `tests/python/test_status_payload.py`, `tests/python/test_api_replacement.py`.

**Behaviour:**
- `status["bridges"]` items for replacements: `{box, mode: "replace", status: problem|waiting|review|ready|done, note, region, region_key, reviewed, protected, options, proposal, candidates, selected}`.
- `status["dialogue"]` with projected cues and `status["timing_conflicts"]`.
- Render-all picks a ready replacement after boxes; never selects a candidate.
- Takes: replacement records produce `bridge: None` listings; `follow` skips them.
- API: schema accepts replacement records, `dialogue`, `locked`, `requires`, box `dialogue`; planner splice ranges overlay replacements without adding time; replacement units are `blocked` with "Replacement regions are reviewed and selected in the Studio".

**Tests:** pure helper `replacement_status_item(...)` shapes; planner ranges for `[107,107]` with a replacement: units total 214 frames; API schema validation accepts a replacement Timeline and rejects `L+R=30`.

- [ ] Failing tests → implement → pass. Commit `feat: report replacement and dialogue state`.

### Task 8: Studio UI (B1.8)

**Files:** Modify `web/h3c_timeline_model.mjs`, `web/h3c_bridges.mjs`, `web/h3c_audio_lanes.mjs`, `web/h3c_timeline_editor.mjs`, `web/h3c_studio.mjs`; create `web/h3c_dialogue.mjs`; tests `tests/web/model_replacement.test.mjs`, `tests/web/dialogue.test.mjs`, `tests/web/bridges_line.test.mjs`.

**Behaviour:**
- Model: parse/serialize `dialogue`, `locked`, box `dialogue`, replacement fields; `serialize` writes `requires`; `insertBridge(state, index, mode)` defaults to replace when a recording is locked; `insertedFrames(state)` counts only insertion bridges; `setCoverage`, `confirmRegion`, `selectCandidate`.
- Bridge panel: mode select (Insert disabled while locked), length + split control with server validity, protected list, Preview original, Confirm region, Render candidate, candidate rows (Play in context, Play original, Select/Use original cut), experimental notice.
- Dialogue panel: cue list/editor, add cue, import transcript JSON as cues (speaker kept), seed from Story schedule, Checked toggle, audition.
- Audio settings: Lock dialogue timing checkbox (uploaded clips only).
- Editor: conflict banner, summary counts inserted time only.

**Tests:** serialize round-trip keeps new fields and `requires`; old Timeline without fields serializes unchanged; `insertBridge` modes; `insertedFrames`; transcript import → cues with speaker; `bridgeLine` texts for replacement statuses.

- [ ] Failing tests → implement → pass; `node --check` each edited module. Commit `feat: studio review for replacement bridges and dialogue cues`.

### Task 9: Documentation (B1.9)

**Files:** `guide/continuity/joins-and-bridges.md`, `guide/sound/dialogue.md` (new), `mkdocs.yml`, `CHANGELOG.md`.

- [ ] Document modes, region review, candidates, experimental status, dialogue cues, locking, conflicts, older-install behaviour. Check local links. Commit `docs: replacement bridges and dialogue cues`.

### Task 10: Native VAE endpoint validation (B1.10)

**Files:** Create `scripts/validate_replacement_vae.py`; record `docs/research/2026-11-03-replacement-vae-validation.md`.

- [ ] On CPU (separate process, `CUDA_VISIBLE_DEVICES=""`), load `minimax_h3_video_vae_fp16.safetensors`, encode a synthetic moving clip of 107 frames at 256×256, then measure: decode(aligned slice) vs decode(full) window error; `latents.window` unaligned re-encode vs direct encode of the same pixel window; round-trip PSNR. Record numbers and the pass criteria (aligned slice ≥ 35 dB vs full decode; unaligned window decode ≥ 30 dB vs source pixels). Commit evidence.

### Task 11: Real generation endpoint review (B1.11)

- [ ] Requires a GPU generation run of a replacement candidate in a real Timeline and human review of both joins, motion and dialogue sync. Blocked while the GPU is held by the user's running ComfyUI and a human reviewer is needed; record the exact procedure and return condition.

---

## Self-review

- Spec §2 invariants → Global Constraints; tested in Tasks 4–6.
- §3 cues/clocks/intake/verification → Tasks 2, 3, 8.
- §4 geometry, exact range binding, overlap, feasibility gate → Tasks 4, 5, 10, 11.
- §5 workflow, pending/failed, stale, undo, take switching → Tasks 5–8 (undo via Timeline JSON state revalidated by status).
- §6 component boundaries → File Structure.
- §7 compatibility and insertion mode → Tasks 2 (`requires`, lock conflicts), 4 (legacy records), 8 (mode availability).
- §8 acceptance cases → Tasks 2–7 test lists; real media review → Task 11.
