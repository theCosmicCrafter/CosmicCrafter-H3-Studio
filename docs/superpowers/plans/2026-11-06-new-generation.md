# Start a new generation Implementation Plan

> **For agentic workers:** Use executing-plans inline; test first, no task delegation except final read-only review.

**Goal:** Keep authored content and all previous media while starting with no active renders.
**Architecture:** New backend generation helper creates empty sequence manifests with prior sequence/snapshot history. The host changes only sequence identity after success, retaining Timeline text/settings and source bindings. Project settings uses existing controls/dialog and lists playable earlier outputs.
**Tech Stack:** Python/unittest, existing aiohttp, ES modules/node:test; no dependencies.
**Spec:** docs/superpowers/specs/2026-11-06-new-generation-design.md

## Global Constraints
No deletion or moves of old media; no automatic rendering; preserve exact Timeline/prompts/settings/references; block busy/stale actions; no live service changes.

## Review Focus
Incomplete generations; missing old video files; busy or linked names; failed manifest write; attached project detachment with source bindings intact.

### Task 1: Preserve generations and start an empty sequence
- [x] Write failing Python tests for empty active state/all independent clips cleared, immutable old files, repeated generation history, busy rejection and failed writes.
- [x] Implement h3_continuity/generations.py with read-only history and start endpoints in routes.py. Reuse saved manifest and queue helpers. Run focused tests.

### Task 2: Project settings action and history
- [x] Write failing JS tests for cancel/no side effects, stale/busy rejection, preserving authored content and switching only after server success.
- [x] Implement web/h3c_generations.mjs helper, host adapter and existing Project settings UI. Add history links for full/partial and individual clips, error feedback and busy state.

### Task 3: Verify
- [x] Update docs/changelog, run full tests, syntax, strict docs, diff/roadmap checks; review data-preservation and stale-source cases before marking passing.

Evidence: full164JS +307Python pass; strict docs, retained Chromium browser smoke (desktop/phone, native/attached, upload/stale history), syntax/diff/roadmap pass. Independent review findings fixed with regressions. No deferred findings, live rendering or deployment.
