# P-H3-Image still node: implementation plan

Design: `docs/superpowers/specs/2026-11-04-ph3-image-still-node-design.md`. Issue #21. Branch `feat/ph3-image-still` in `D:/development/rambrogi/work/h3c-ph3-image`. No code before the design is approved (gate G0). Ledger: `docs/roadmap-discipline/phases/2026-11-04-ph3-image-still.md`.

Test command (CPU, no models): `node tests/run.mjs`. Python alone: `python -m unittest discover -s tests -t . -p "test_ph3*.py" -v` with ComfyUI's Python.

## Spikes (answer before building; each ends with a line in the ledger)

- **S1 expansion + recipe slot.** In a scratch node, return `NodeOutput(link_from_expanded_graph, {literal dict}, expand=graph)` and confirm ComfyUI accepts a literal at slot 1 while slot 0 is an expanded link; confirm an unevaluated slot 1 runs nothing. *Fallback:* thin wrapper node.
- **S2 sizes and speed.** Run the official text-to-image graph at 1024×576, 1280×720 and 2912×2912 with the local int8 set; record time, VRAM, and look at the images. Decides default size and the `width/height` minimum.
- **S3 validation.** With a P-H3 node connected to `still_recipe` and no P-H3 files selectable, does a plain Timeline video submit validate? Decides the `(not installed)` sentinel.
- **S4 upsampler.** Same prepared still prompt with upsampler off and on (int8 upsampler); decide D2 from the images and the time/VRAM cost.
- **S5 references.** Edit mode with a location image first, then identity and prop images; check that the canvas, identity and prop come through, and what happens when the output size differs from `image_1`.

Spikes use the shared GPU: follow the GPU ticket protocol in the follow-ups ledger (`gpu.py` request, 90 s idle queue, `/free`, release).

## Tasks

1. **PI2 node + validation** (`h3_continuity/ph3_image_nodes.py`, `extension.py`). Schema, file filtering through `folder_paths`, validation messages, expansion into the native graph (as in `p-h3-image_text_to_image.json` and `_edit.json`), optional upsampler branch (`StringFormat`, `TextGenerate`, `ComfySwitchNode` or an equivalent plain Python choice made at expansion time), recipe output. Tests: `tests/python/test_ph3_image_nodes.py` for schema, filtering, each message, expanded graph shape (node classes, wiring, sigmas, shift 1/1, sampler `euler`).
2. **PI3 recipe integration.** `web/h3c_stills.mjs` `captureRecipe` branch for the self-describing generator; `recipeControls` unchanged shape; `story_context.renderer_for` treats the class as `pixels`; `image_recipe.prepare` gets `p-h3-image-scene-v1` prompt policy (canvas first, `<Picture N>`), reference capacity 8. Tests: `tests/js/ph3_recipe.test.mjs` (capture from API prompt + UI workflow, nested subgraph copy, muted node, bad link), `tests/python/test_ph3_image_recipe.py` (prepare binds prompt/seed/size/images, labels, provenance, capacity error text, Qwen and generic recipes unchanged).
3. **PI4 on-demand regression.** `tests/python/test_ph3_image_lazy.py`: video prompt with the node attached runs no P-H3 node; Studio still prompt does.
4. **PI5 example + docs.** `examples/ph3_image_still.json` (Timeline + node, models unset), `docs/PH3-IMAGE-STILLS.md` or `guide/build/` page (exact upstream dependencies: ComfyUI version, files and folders, `hf download` commands copied from upstream, VRAM table, license note), pointers from `guide/build/frame-guides.md` and `docs/QWEN-STORY-STUDIO.md`, CHANGELOG `[Unreleased]`. `mkdocs build --strict`.
5. **PI6 real Studio verification.** GPU ticket; live clone on the branch; open the example, select the int8 set, prepare a prompt, generate First and a Shot with and without references, apply as guide, then render a short video from the same Timeline; record job ids, timings, screenshots, and that the video prompt ran no P-H3 node. Re-capture the Qwen and Fizgig examples. Restore the clone to main, `/free`, release the ticket.
6. **PI7 PR.** `node tests/run.mjs`, `git diff --check`, `mkdocs build --strict`; push; PR linked to #21 (only when the user asks).

## Gates

- G0: user approves the design (decisions D1–D4).
- G1: spikes S1–S5 recorded; design amended if any answer changes it.
- G2: PI6 shows a real Studio generation before the issue is called done.
