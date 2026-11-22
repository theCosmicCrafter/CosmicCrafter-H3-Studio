# Implementation plan — Split a clip at a frame guide

**Status:** Historical plan, superseded by the [2026-11-04 removal design](../../roadmap-discipline/phases/2026-11-04-guide-split-prompt-continuity.md).

**Spec:** [2026-11-03-guide-split-design.md](../specs/2026-11-03-guide-split-design.md) (decisions Q1–Q4 settled; open questions resolved below).
**Ledger:** [phases/2026-11-03-guide-split.md](../../roadmap-discipline/phases/2026-11-03-guide-split.md).
**Scope:** browser-side Timeline state edit plus tests. No Python behaviour change; the server already understands `first`/`last` guide targets, the shared continuing boundary (`timeline.frame_guides`) and `flf_refmods` (`timeline.box_slots`).

## Resolved open questions (assistant judgment, delegated by the user)

1. **Conflicting neighbour guides.** No extra refusal. The split writes the same PNG to the left Last and right First, so it cannot create a boundary conflict. The outer boundaries (previous clip → left, right → next clip) keep exactly the records they had, so any pre-existing conflict is unchanged and still reported by the existing checks.
2. **`flf_refmods` on a half that mentions no references.** Inherit the original clip's choice. Additionally switch it on for every half that mentions an `@image` reference, which is what keeps that half FLF2VA instead of REF2VA. (Refined during GS2: `box_slots` honours the flag on a *fresh* clip only when it opens on a First image or guide, and never with raw audio/video, so such halves are reported instead of flagged.)
3. **Where the action lives.** In the marker panel of an accepted mid-clip guide (beside *Remove guide*), and in the clip's saved-stills list for legacy guides that have no marker. No context menu.

## Coordinates (verified in code)

- Box-local frame `f`: fresh box `0..F-1`; continuing box `0..F`, where `0` is the shared boundary (the previous clip's final frame), `timeline.py:662`.
- Generated frame of a box-local frame: `g = f + (carry ? carry - 1 : 0)`; shot timestamps (`At MM:SS.mmm,`) are generated time (`h3c_shot_preview.mjs:15`, `timeline._shot_frames`).
- Grid: fresh `17k+5` (≥22), continuing `17k` (≥17), max `362` / `362-context` (`h3c_timeline_model.mjs:23`).

## Algorithm (`web/h3c_guide_split.mjs`)

`guideSplitTiming(state, index, preview, context)`:

1. Resolve the guide frame `f` (target records through `frameTargets`; legacy records use `frame`). Refuse if it has no accepted `guide`, cannot be resolved, sits at `f ≤ 0` (already the First) or `f ≥ last` (already the Last).
2. Needed lengths: `L0 = fresh ? f + 1 : f` (left ends on the guide); `R0 = last - f` (right continues from it).
3. Round up: `L = roundUp(L0, fresh)` always (a continued clip must not drop frames, `dropConflict`); `R = exact ? R0 : roundUp(R0, continuing)`. Refuse past the limits, or when a fresh left plays fewer frames than the context the right carries (`carryConflict`).
4. `offset = g - (context - 1)` generated frames: the right half's timestamps subtract it, because the guide becomes the right half's generated frame `context - 1`.
5. Report `added = (L - L0) + (R - R0)` and `moved = L - L0` (how much later the guide lands).

`splitAtGuide(state, index, preview, context)`:

1. **Prompt division.** With no `[Shot N]` markers, both halves keep the prompt. Otherwise find shot `k` (last shot whose start ≤ `g`). On a shot start: left = shots `< k`, right = shots `≥ k`. Mid-shot: left = shots `≤ k`, right = shots `≥ k` (shot `k` in both; the right's copy loses its `At …,` / camera-cut prefix). Right timestamps are shifted by `offset`. Prompt bodies are built by the existing `halfPrompt` (exported from `h3c_shot_split.mjs`, now with a `stripFirst` option and an `endpoint` flag so the left summary keeps *keyframe completion*).
2. **Boxes.** Left keeps id, seed, join, `first`; `last = ''`. Right: new id and seed, continuing (`cut: false`, no `new_scene`/`join`), `first = ''`, keeps original `last`. Both drop `cast` and `source` (new prompt text, as in the shot split).
3. **Guide records.** Left gets `{target:{kind:'last'}, frame:L - (fresh?1:0), guide}`; right gets `{target:{kind:'first'}, frame:0, guide}` plus the original record's candidates and still settings.
4. **Other previews, plates and plate edits** partition by resolved frame: `< f` left (unchanged frame), `> f` right (`frame - f`). Shot targets are renumbered to the half's shots; legacy shot numbers stay unique and never alias the right's First. Candidates at exactly `f` merge into the right First.
5. **References.** `flf_refmods` per resolved question 2. The result lists halves that still run REF2VA because they use raw audio/video (the guide stays an insert there) and that the cached RefMods need H3's VAE loaded from a file.
6. **Dependants.** Story-bible pins and other clips' selected memories that point past the guide move to the right half.

## Adjacent fix (same partition, found while reading)

`splitBox` (*Split before Shot N*) keeps a targeted Shot guide's `target.shot` unrenumbered, so a Shot-target guide in the second half resolves to a missing shot and is dropped (`resolved_previews` skips it). The guide documentation promises the guide moves with its shot. Fix: remap `target.shot` through the half's shot map (shot 1 → `first`) and stop adding `shot` to targeted records.

## Tasks

| Item | Task | Files | Verification |
|---|---|---|---|
| GS1 | Test harness: `node --test` for browser modules, `unittest` for the package (portable Python), one runner script | `tests/js/`, `tests/python/`, `tests/run.mjs`, `tests/README.md` | Harness runs and reports green on a smoke test |
| GS2 | `guideSplitTiming` + `splitAtGuide` | `web/h3c_guide_split.mjs`, `web/h3c_shot_split.mjs` | Unit tests: fresh/continuing/exact arithmetic, refusals, on-shot and mid-shot prompts, timestamps, previews/plates partition, `flf_refmods`, dependants, undo-independent purity |
| GS3 | `splitBox` targeted-guide fix | `web/h3c_shot_split.mjs` | Regression test: a Shot 3 guide survives *Split before Shot 2* as Shot 2 of the right half |
| GS4 | Server agreement: Node writes split timelines, Python parses them and checks `box_slots`, `frame_guides`, `box_length` | `tests/python/test_guide_split_server.py`, `tests/js/emit_guide_split.mjs` | Left FLF2VA with a Last endpoint guide; right continuing FLF2VA; no conflicts; lengths on the grid |
| GS5 | UI: *Split at guide* in the marker panel and saved-stills list, one undo step, result note, cache-busting import versions | `web/h3c_timeline_editor.mjs`, `web/h3c_frame_images.mjs`, `web/h3c_timeline.js` | `node --check`; DOM-free logic covered by GS2; manual UI check listed for the user |
| GS6 | Docs: guide page row, CHANGELOG *Unreleased*, spec status | `guide/build/timeline.md`, `CHANGELOG.md`, spec | Links resolve |
| GS7 | Visual gate: one clip with a mid-clip guide rendered before and after the split | — | **User-owned.** Needs this build installed into the live ComfyUI and GPU time; not run by the assistant |

## Known limits (accepted)

- Placed audio clips and timed text keep absolute times; the rounding (`added`) shifts later clips by up to ~1.4 s, exactly as *Split before Shot N* does today.
- A lettering guide (`visible_text`) is re-checked against timed text at its new time when rendered; a mismatch is reported by the existing render check.
- Whether the cached RefMods VAE is file-backed is only known at render time (`frame_refmods.py:26`); the split reports the requirement rather than detecting it.

_Created using Anthropic Claude. Internal draft: keep this line until a human has reviewed and verified the content._
