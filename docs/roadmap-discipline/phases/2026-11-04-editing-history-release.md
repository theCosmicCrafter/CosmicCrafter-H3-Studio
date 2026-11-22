# Editing history release

### Phase 3: Editing history release

- [ ] **EH2** (State: `active` | Verification: `node tests/run.mjs; isolated desktop/mobile browser smoke; strict docs build; git diff --check; PR checks; merged tag and published release verification`)
  - *Behavior:* Port verified Timeline undo/redo/history onto current main, create and merge its PR, and publish v0.10.0 from the merge commit.
  - *Authorization:* User requested PR creation, merge and tagged release on 2026-11-04. Preserve unrelated edits in the original checkout and the separate partial-export workstream. No live deployment or GPU work required.
  - *Recovery:* History-only port rebased from 172fe5c onto 47c1d43 after PR #23 merged. Retains guide, raw-audio, take, chain-setting and partial-export code. v0.10.0 notes include both editing history and partial export since v0.9.0. Original dirty checkout remains separate.
  - *Evidence:* Post-rebase `node tests/run.mjs`: 84 JS + 192 Python pass, no skips. Isolated desktop/mobile Chromium smoke exercises actual workspace controls and TimelineHost restore paths with mocked services, zero page errors; screenshots inspected. Strict MkDocs, syntax and diff checks pass. Conflict resolution briefly introduced mojibake through Windows default encoding; corrected to UTF-8 before pushing and browser smoke rerun. PR/tag/release publication pending.
  - *Next:* Commit the final verified release metadata/UTF-8 corrections, push, create and link PR, inspect checks and merge readiness, merge with a merge commit, then tag that commit and publish v0.10.0.
