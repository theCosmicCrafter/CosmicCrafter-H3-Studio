# Incompatible saved overlap and fresh generations

### Phase 13: P-H3 still prompt instructions

- [x] **IO1** (State: `passing` | Verification: `Code tracing and relevant CPU regression tests; no GPU rendering.`)
  - *Behavior:* Investigate saved-overlap failure and propose accurate confirmation/recovery.
  - *Evidence:* Traced timeline_node.py overlap guard, nodes.py save archival, store.archive_box, outdated status and classic/project callers. Original 18 durable-render CPU tests pass. Draft design approved by user on 2026-11-06.
  - *Design:* [Approved design](../../superpowers/specs/2026-11-06-incompatible-overlap-design.md).

- [x] **IO2** (State: `passing` | Verification: `node tests/run.mjs; git diff --check; roadmap check`)
  - *Behavior:* Approved read-only preflight and confirmation before queueing, followed by dependency-scoped archival into Takes only after replacement media is written successfully. Independent clips stay active.
  - *Scope:* This main-based worktree only, branch fix/incompatible-render-overlap at3b2d569. No parent checkout changes, live rendering, deployment or restart.
  - *Implementation:* regeneration.py computes actual overlap compatibility, transitive Continue/memory closure and fingerprinted receipts; renderer and save validate receipts. Save stages new media then rolls back archive moves on failure. Classic UI checks before seed randomization/queueing; project selection carries consent and limits recovery job to the selected clip. Affected bridges archive; old replacement candidates stay but need fresh review. Documentation updated.
  - *Evidence:* Full 159 JS +298 Python passed before independent review fixes. Latest full159 JavaScript +301 Python tests pass with zero skips/failures; strict MkDocs, diff and roadmap checks pass after review fixes.
  - *Independent review:* Three Important findings fixed with regression tests observed failing then passing: H3 latent spatial scale16 (fixtures now4x4 for64px); linked settings resolve static scalar inputs or defer safely to execution; persisted classic workflow/node editor-state fingerprint rejects edits while queued/sampling, excluding permitted selected-seed updates. Project work is pinned by revision/lease. No minor findings or declined judgments.
  - *Decision:* Incompatible recovery starts with one take; compatible regeneration keeps 1-10 take batching. Existing take compatibility constraints remain. Dynamic linked settings that cannot resolve without execution defer to the renderer, which fails safely before conditioning if the actual overlap is incompatible.
  - *Next:* IO2 verified; IO3 owns the explicit follow-up.

- [x] **IO3** (State: `passing` | Verification: `node tests/run.mjs; git diff --check; roadmap check`)
  - *Behavior:* User follow-up: add Start a new generation in Project settings. Keep Timeline/prompts and preserve old generated videos while clearing every active render, including independent clips.
  - *Scope:* Run only after IO2 completes. Reuse safe archival or existing project/generation preservation patterns; inspect before deciding exact storage behavior. No live renders/deployment.
  - *Evidence:* User requested this during IO2 review on2026-11-06. Implemented a fresh empty sequence with durable history, preserving exact Timeline/settings and every old output file;5 Python +5 JS focused tests pass. Final combined164JS +307Python pass, zero skips; strict docs, syntax/diff/roadmap and retained browser smoke pass; independent review findings fixed.
  - *Next:* Local implementation verified; await user-requested integration.

IO3 review findings: linked sequence names now resolve using the existing static scalar helper; full node widget/input and Story identity snapshot rejects changes across confirmation/save/request. In-flight Story image uploads now block reset (real host browser regression observed failing then passing). History from another host/sequence is cleared before requesting its history; this reviewer Minor was treated as Important because stale links would falsely attribute another project's output (browser regression observed failing then passing). No deferred findings. Native/attached host preservation and settings at1440/390px pass in isolated Chromium, no page errors; screenshots inspected. Browser smoke retained in tests/browser/new_generation.py.

- [ ] **IO4** (State: `deferred` | Verification: `full tests; browser smoke; strict docs; PR merge/tag/release; both checkout HEADs`)
  - *Behavior:* User explicitly authorized PR creation/merge, tagged release and fast-forward of development and installed custom-node checkouts. User will restart ComfyUI.
  - *Scope:* Preserve existing local tracked/untracked work and all generated media. Do not restart services or render.
  - *Evidence:* origin/main e154bb1/v0.16.1 fetched; original checkout has only roadmap/product uncommitted work. Target v0.17.0 for new generation feature.
  - *Next:* Commit implementation, integrate latest main, verify and publish.
  - *Design-worktree recovery:* User explicitly redirected this fresh branch to box-audio brainstorming. Main `b7eaedc` already contains PR55's merge, so the inherited PR-creation instruction is stale. Remaining release/deployment claims were not checked here. Preserve the historical receipt; resume release work only on an explicit release task after checking actual remote/tag/installation state.

IO4: integrated main e154bb1/v0.16.1, retaining checkpoints/autosave and disk cache. Save conflict resolved by writing first-pass guide frames inside the recovery staging/rollback block; fingerprints now include native guide PNG stamps. Fresh175JS +332Python, browser smoke, strict docs and syntax/diff checks pass. Target v0.17.0.
