# Still quality Implementation Plan

> **For agentic workers:** Use executing-plans for inline implementation and one fresh whole-branch review.

**Goal:** Correct the diagnosed inputs and publish a verified patch release.
**Architecture:** Recipe-owned CPU size conversion, untouched native sampler, preserved references, explicit still prompt preparation.
**Tech Stack:** Python ComfyUI V3, existing JavaScript modules, unittest and node:test.
**Spec:** docs/superpowers/specs/2026-11-05-still-quality-design.md

## Global Constraints

- Preserve explicit still size, original images, other generators, manual/prepared prompts, and all unrelated local changes.
- No GPU generation or restart.

## Review Focus

- Linked dimensions must remain scheduler-resolved; explicit sizes bypass automatic scaling.
- Nonstandard aspects and landscape sizes must remain valid multiples of 32.
- File and computed references must retain their aspect and pixels.
- Missing Cast must preserve subject definitions and titles without guessing roles.
- Prepared/manual text must still work when no source snapshot exists.

### Task 1: Fix inputs

- [x] Add failing Python tests in test_ph3_image_recipe.py for runtime size, explicit sizes and unchanged references; test CPU size conversion and contextual roles.
- [x] Add failing JS tests for P-H3 imported video requiring still preparation, authored snapshot selection, and preserved reference subject descriptions.
- [x] Implement minimal changes in ph3_image_nodes.py, still_nodes.py, extension.py, image_recipe.py, stills.py, h3c_shot_preview.mjs and frame hint; bump importing module cache versions.
- [x] Run targeted tests to green, then full CPU suite and strict MkDocs. Update guide and CHANGELOG.

### Task 2: Release

- [x] Fresh code reviewer inspects full branch and requirements; fix material findings.
- [ ] Commit only task files, push, create PR and link it, verify checks, merge.
- [ ] Publish annotated patch tag and release on merge commit.
- [ ] Fast-forward both main checkouts and verify retained local files, commit equality and installed source hashes.
