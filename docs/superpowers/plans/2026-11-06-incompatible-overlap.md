# Incompatible overlap recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Confirm incompatible joins before rendering and archive dependent clips only when the replacement saves.
**Architecture:** A shared Python recovery module computes incompatibility, dependency closure and a fingerprinted consent receipt. The renderer validates that receipt and attaches it to the prepared segment. Saving stages the replacement before transactional archival. The existing Timeline host confirms via the house dialog and sends consent only in the queued request; project planning carries the same consent and limits the job to the requested regeneration.
**Tech Stack:** Python, unittest, existing ComfyUI routes; JavaScript ES modules and node:test. No dependencies.
**Spec:** docs/superpowers/specs/2026-11-06-incompatible-overlap-design.md

## Global Constraints
- No live rendering, deployment, restart, parent checkout edits, automatic deletion of Takes or duration changes.
- Preserve old active renders on cancellation, sampling failure and save failure.
- Preflight before seed changes/queueing; recheck settings/manifest before execution and save.
- Preserve independent clips, including cuts that have no visual-memory dependency.
- Use existing confirmation components. Only requested clip regenerates; Render remaining handles affected clips afterward.

## Review Focus
- Old Cut changed to Continue and resolution mismatch must identify a useful reason.
- Transitive visual memory across cuts must invalidate dependents without clearing independent clips.
- File/write failures after generation must restore prior manifest and media.
- Consent becoming stale while queued must fail without changing saved media.
- Multi-take and project jobs must not accidentally clear twice or auto-render dependents.

### Task 1: Shared preflight and safe save recovery
**Files:** Create h3_continuity/regeneration.py and tests/python/test_regeneration.py; modify timeline_node.py, nodes.py, routes.py as needed.
**Interfaces:** preflight(body, target) returns ok, reason, affected clips and fingerprinted receipt; validate receipt against current state; commit replacement and archive consented entries with rollback.
- [x] Add CPU regression tests for incompatible overlap reasons, compatible no-warning path, dependency closure and stale consent. Run and observe failure.
- [x] Implement shared preflight, route and renderer integration using existing saved manifest/settings/timing helpers. Run tests to green.
- [x] Add save tests proving affected old bytes become takes only on success and failures roll back; implement transactional save integration. Run focused tests to green.

### Task 2: Confirm before queueing, including projects
**Files:** web/h3c_timeline.js, web/h3c_project.mjs, small web/h3c_regeneration.mjs helper; timeline_api/contracts.py, planning.py and jobs.py as needed; focused JS/API tests.
**Interfaces:** request-scoped receipt flows from read-only preflight through queued Timeline JSON or project selection into the renderer; no receipt persists in authored timeline.
- [x] Add JS tests for cancel/no mutation, consent transport, stale state, compatible queueing and multi-take behavior; observe failure.
- [x] Implement confirmation with concrete clip list/reason and existing dialog, before seed mutation and POST /prompt. Cover project planning without generation scope expansion.
- [x] Add project contract/planning tests for receipt validation/transport and requested-only execution; run focused checks to green.

### Task 3: Integration verification and documentation
**Files:** guide timeline rendering docs, CHANGELOG.md, roadmap/plan checkpoints.
- [x] Run node tests/run.mjs; fix regressions with targeted tests, then run syntax/diff/roadmap checks.
- [x] Review whole diff against approved design, including cancellation/failure and both queue paths; fix material findings and reverify.
- [x] Record evidence and remaining limits. Leave changes in this isolated branch for user review; no publish/deploy.

Verified after independent review:159JS +301Python, strict MkDocs, diff/roadmap checks. No live rendering/deployment. Three review findings fixed with regression tests. User follow-up IO3 is separate from this completed plan.
