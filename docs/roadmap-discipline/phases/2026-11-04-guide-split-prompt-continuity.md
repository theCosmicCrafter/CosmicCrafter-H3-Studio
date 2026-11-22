# Guide-split prompt continuity

### Phase 0: Design

- [x] **GSP0** [parallel: subagents recommended] (State: `passing` | Verification: `Inspect PR #5 and current split helpers, tests and guide documentation; record evidence and user design decisions`)
  - *Behavior:* Investigate the repeated-opening-action problem after frame-guide splitting, compare bounded product choices, and reach a user-confirmed design before implementation.
  - *Evidence:* PR/source/test inspection and sampled latest-render evidence recorded below. Fresh ledger/source-scope inspection and user answers Q1/Q2/Q3 confirm the complete design. All design choices settled on 2026-11-04.
  - *Constraints:* Read-only source/PR/render investigation; parent owns roadmap writes. A research subagent may inspect split behavior. No generation, live workflow mutation, PR changes or implementation.

## Design tree

- Settled Q1: automatic splitting requires an actual timed Shot boundary; no mid-shot split and no automatic LLM/vision rewriting.
- Settled Q2: image guides remain usable independently of splitting, including interior frames without Shot boundaries, First/Last guides and existing saved projects.
- Settled Q3: remove Split at guide entirely; keep only the existing Split before Shot N with its Cut behavior. No new disabled split controls or alternate split modes.
- Existing saved projects keep their guide data, boxes, prompts and joins. No migration or automatic rewrite.
- User confirmation across Q1/Q2/Q3 settles the shared design; proceed with removal and checks in this separate worktree.

## Recovery notes

- Original dirty checkout is not this branch and must remain untouched.
- PR #5 identified and inspected remotely: `03729af`, `126ba10`, merge `f73cb83`.
- Latest render evidence has now been sampled as described below; no full playback or audio review.

## Investigation evidence — 2026-11-04

- GitHub `gh pr view 5 --repo KadoBOT/ComfyUI-H3-Continuity-Studio --json number,title,url,state,mergedAt,body,files,commits`: PR [#5](https://github.com/KadoBOT/ComfyUI-H3-Continuity-Studio/pull/5), merged 2026-11-03. Its declared behavior keeps the intersected shot in both halves; on an actual timed shot start it partitions the shots. Its reported visual testing did not establish smoother motion than an unsplit guide.
- Source: `web/h3c_guide_split.mjs` divideShots and splitAtGuide duplicate intersected shot prose and preserve an unstructured prompt in both boxes. No semantic rewrite. `describeGuideSplit` gives a post-split manual-edit note for duplicated numbered shots, but not for unstructured prompts. This is an existing warning, not a new solution.
- Source: `web/h3c_shot_split.mjs` splitBox sets the right box to Cut. Guide splitting sets it to Continue and pairs the guide as left Last/right First. Removing the entire guide-split feature loses that operation at valid shot boundaries too.
- Source: `web/h3c_shot_preview.mjs` frameTargets already exposes First, Last and readable timed Shot markers. Legacy saved records without target may retain arbitrary guide frames and offer splitting through the saved-stills list. A `[Shot 1]` marker alone does not make an interior frame a semantic boundary.
- Fresh verification: `node --test tests/js/guide_split.test.mjs tests/js/guide_split_editor.test.mjs tests/js/shot_split.test.mjs`: 23 passed, zero failed/skipped. Read-only research subagent independently confirmed these source facts; no worker edits.
- Actual render evidence: the user's latest project manifest and two segment videos in their local ComfyUI output directory. Both saved descriptions include the same single-shot feet-to-up whole-take prose, including initial downward framing and final counterweight reveal. CPU FFmpeg sampled each video at four moments. Clip 1 rises from body to shaft; clip 2 begins on the shaft, returns to body/shoes, then rises toward counterweight. This supports the reported replay; sampling does not prove text is the only cause. Source videos and the disposable contact sheet remain outside the repository; original renders are untouched.

## Accepted first grilling frontier — user answers 2026-11-04

1. Approved: remove splitting inside a shot and avoid automatic LLM/vision prompt rewrites; require an actual timed Shot boundary for automatic splitting. User clarification: frames without a Shot boundary can remain allowed, but cannot split there.
2. Approved: keep image guides usable independently of splitting, including unrestricted First/Last and saved existing projects. Restricting split eligibility does not require restricting guide placement.

## Accepted second grilling frontier — user answer 2026-11-04

Q3 approved: keep only the existing Split before Shot N action (which starts the right box as Cut), removing Split at guide entirely. Join changes remain explicit through the existing control. This removes automatic paired Last/First guide creation via split; users can keep a continuous move in one guided box.

Prompt partitioning cannot guarantee good prose or visual continuity.

### Phase 1: Removal

- [x] **GSP1** (State: `passing` | Verification: `node tests/run.mjs; git diff --check; inspect remaining split callers and current documentation`)
  - *Behavior:* Remove all guide-based split actions, their dead helper code and feature-only tests. Retain existing Shot-boundary splitting, guide acceptance/placement and saved-project compatibility; update current docs/skills and release notes.
  - *Evidence:* Both guide-split UI actions and the helper removed; shared Shot-split helper simplified only to remove guide-specific options/exports; import cache revisions updated. User guide/skill pack/changelog updated, historical design/plan marked superseded. Feature-only tests replaced with retained Shot-split and saved-guide compatibility coverage. Fresh `node tests/run.mjs`: 51 JavaScript + 130 Python passed, no skips; `git diff --check` passed. `node --check` passed for all four modified JS product files; dynamic imports of changed standalone modules passed. `rg` found no removed guide-split callers or instructions in web/tests/guide/skills (saved-guide fixture names remain intentionally). Final source/diff review found no renderer or saved-data format changes.
  - *Constraints:* No GPU renders or live ComfyUI changes. Existing project data must not be rewritten. Preserve Shot split regression coverage and add meaningful coverage for kept guide data where removing feature-only tests would lose it.
  - *Next:* No implementation work remains. Changes are uncommitted in the isolated design branch; no live ComfyUI deployment or new render was performed.

### Phase 2: Release

- [x] **GSP2** (State: `passing` | Verification: `node tests/run.mjs; git diff --check; inspect PR checks and merge state; verify release tag resolves to the merged commit and published release notes cover v0.6.0 onward`)
  - *Behavior:* Create and merge a PR for the verified removal, then publish a tagged v0.7.0 release with all changes since v0.6.0, including already merged smoke tooling/examples from PR #12.
  - *Evidence:* User explicitly authorized PR creation, merge and tagged release. Fetched origin/tags: previous latest v0.6.0 at f05894d; branch and origin/main both at 469771e. No rebase needed. Inspected all intervening commits and the render_scene/test-runner diffs; other PrefixStream PRs #13-#18 remain open and are excluded.
  - *Release recovery:* Verified 2026-11-04: PR #19 merged at a4e660af5778e2b90964ee6d14c31120095f9353, and v0.7.0 is published. This inherited release checkpoint was stale; the editing-history release is a separate work item.
  - *Constraints:* Publish the merged PR commit, not an unmerged branch or unrelated later main changes. Do not deploy to live ComfyUI or run inference. Do not modify other worktrees.
  - *Next:* Complete; retain the published release.
