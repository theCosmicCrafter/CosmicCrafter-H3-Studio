# Split a clip at a frame guide (guide → Last/First)

**Status:** Superseded by the [2026-11-04 removal design](../../roadmap-discipline/phases/2026-11-04-guide-split-prompt-continuity.md). The historical design below introduced guide splitting; the replacement keeps only Split before Shot N and retains independent frame guides.

## Problem

A mid-clip frame guide (a `previews` record with `guide` and a `frame`) is pinned into the clip at that frame. The original premise was that H3 does not develop smoothly toward it. GS7 testing found it does blend toward and away from the guide; the split's real value is a hard boundary, the native First/Last path and separately editable clips. A real Last frame (end of the left clip) followed by a real First frame (start of the right clip) makes H3 generate toward and away from the image.

## Feature

A **Split at guide** action on a mid-clip guide. It splits the clip at the guide's frame; the guide becomes the left clip's **Last** and the right clip's **First**.

Reuses `splitBox` in `web/h3c_shot_split.mjs` (timing, prompt halves, previews/plates partition). New: the split point comes from a guide frame, not a `[Shot N]` timestamp.

## Settled decisions

1. **Join (Q1): Continue.** The right clip is not a Cut. Left Last = right First = the guide image; frame 0 of the right clip is the shared boundary and it carries the left clip's context frames (existing `frame_guides` shared-boundary model, `timeline.py:677`). Motion and sound flow through.
2. **Prompt (Q2): divide the shot.** If the guide falls inside `[Shot k]`, k is kept in both halves: the left half ends the shot at the guide; the right half begins with a new `[Shot 1]` continuing from the guide image. Timestamps are re-based. If the guide is on a `[Shot N]` start, behave like today's split. No LLM. The user edits the two halves afterwards.
3. **References (Q3): cached RefMods per half.** Each half keeps only the references its own text mentions (`halfPrompt` already prunes definitions). Each half that still mentions a reference gets `flf_refmods = true` so it stays `flf2va` (otherwise `box_slots` turns it into `ref2va`). If no file-backed VAE is available, leave plain references and show a visible warning.
4. **Grid (Q4): round up.** Both halves round up to H3's grid so no performance time is lost; the guide lands on the left clip's final frame and so moves a few frames later. The split reports the time added. Exact-length clips split exactly.

## Defaults I propose (to confirm)

- **Not splittable:** a guide at frame 0 (it is already the First) or at the final frame (already the Last). Show why.
- **Other guides** are partitioned by frame, as `splitBox` does now. The original First stays with the left, the original Last goes to the right, as in the shot split.
- **Rendered clips:** splitting makes both halves "not current"; earlier takes remain in `takes/`. The action is one undoable step.
- **Guide candidates** (its other generated images) travel with the First guide of the right half; the left Last keeps the accepted guide only.
- **Seed:** the right half gets a new seed (as the shot split does); the left keeps the original.
- The guide image is the accepted PNG itself, so no re-encoding occurs for the two uses.

## Open questions (resolved)

- **Conflicting neighbour guides:** no extra refusal. The split writes the same PNG to both sides of the new boundary and leaves the outer boundaries unchanged, so it cannot create a conflict.
- **`flf_refmods` with no references:** each half inherits the original choice; a half that mentions references and opens on a frame also gets it.
- **Where:** the Shot marker panel, plus the saved-stills list for legacy guides without a marker. No context menu.
- **Refinement found in code:** cached RefMods keep a *fresh* half FLF2VA only when it has a First image or guide (`box_slots`), so the split reports such halves instead of setting the flag.

## Verification (to plan)

- Unit: split arithmetic (guide on/off grid, carried frames, exact clips), prompt division, preview/plates partition, `box_slots` mode for each half.
- Visual (real): one clip with a mid-clip guide rendered before and after the split; compare the approach to the guide.
- Public checkout has no JS/Python test suite yet (see readiness checklist); the plan must add one.

_Created using Anthropic Claude. Internal draft: keep this line until a human has reviewed and verified the content._
