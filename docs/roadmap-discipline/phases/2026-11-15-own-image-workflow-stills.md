# Stills from the user's own image workflow

### Phase 23: own image workflow stills

- [x] **OW1** (State: `passing` | Verification: `node tests/run.mjs; strict guide build; git diff --check; browser check of a real subgraph connected to still_image`)
  - *Behavior:* The Timeline's `still_image` input takes the IMAGE output of any image workflow wrapped in a native subgraph; the Studio binds it by input names (`prompt`, `seed`, optional `width`, `height`, `negative`, IMAGE inputs as references) and never changes other settings.
  - *User intent (2026-11-15):* Replace the still custom nodes with the user's own workflows and settings. User agreed to the subgraph-contract design, to deprecating the old nodes for one release before deleting them, and to leaving H3 video-model stills alone. User then asked for docs/skills, PR, merge, release, both checkouts fast-forwarded and a ComfyUI restart.
  - *Design:* [Written design](../../superpowers/specs/2026-11-15-own-image-workflow-stills-design.md).
  - *Evidence (2026-11-15):* After merging main at v1.1.1: `node tests/run.mjs` 401 JavaScript + 541 Python pass; strict guide build passes; `git diff --check` clean. Live check on ComfyUI 0.45.0 / frontend 1.58.0: the user's `strays_minimax-h3-image-edit` workflow, converted to a subgraph in `rebuild_v2_amv_grade_disk_cache_own_still`, bound from a real `graphToPrompt` result, prepared clip S001 with a four-view location sheet and generated a 5472 x 3072 still. The check found and fixed one defect: prefix-numbered autogrow image sockets were refused as reference inputs.
  - *Limits:* The still was queued from the prepared prompt, not with the Studio's Generate button. Cast reference generation, Story image writing and a video render with `still_image` connected were not run.
  - *Template note:* The official MiniMax edit workflow extracts the enhancer caption with native `JsonExtractString`, so OW2 needs no custom caption node.

- [ ] **OW2** (State: `pending` | Verification: `templates load and generate; deprecated nodes still load saved workflows`)
  - *Behavior:* Native subgraph templates for P-H3-Image and MiniMax H3 Image; mark `H3C_StillRecipe`, `H3C_PH3ImageStill` and `H3C_MiniMaxH3ImageStill` deprecated for one release.

- [ ] **OW3** (State: `pending`) Native `LoadImage` instead of the injected `H3C_StillImageSource`.
- [ ] **OW4** (State: `pending`) Server-side recipe derivation so MCP agents send no recipe.
- [ ] **OW5** (State: `pending`) Delete the deprecated nodes one release after OW2.

## Resume

Open the worktree, run `node tests/run.mjs`, then do the OW1 browser check before a PR.
