# Vendored code

## h3_continuity + mcp_adapter (H3 Continuity Studio)

- **Source:** https://github.com/KadoBOT/ComfyUI-H3-Continuity-Studio
- **Local fork:** https://github.com/theCosmicCrafter/ComfyUI-H3-Continuity-Studio
- **Pinned upstream commit:** `16cc17798fcc0dfb2f7fc48765321664bb82d3a7` (main, v1.3.0, 2026-11-19)
- **License:** MIT — see `h3_continuity/LICENSE` and upstream `LICENSE`. The
  pack remains GPL-3.0-only; MIT code is compatible inside it.
- **What was vendored:** `h3_continuity/` (19 V3 nodes, ~75 backend modules,
  `/h3c/*` routes, timeline/story/prompt-IR subsystems), `mcp_adapter/`
  (standalone `h3c-mcp` package), `skills/`, `guide/`, `APACHE-2.0.txt`
  (required by the adapted prompt spec — see THIRD_PARTY_NOTICES.md),
  upstream `docs/*.md` + `docs/{media,research,roadmap-discipline,
  superpowers,verification}/` merged into this repo's `docs/`,
  upstream `examples/` merged into this repo's `examples/`, upstream
  `tools/*.py|*.mjs` merged into this repo's `tools/`, and the upstream
  `tests/` suite under `tests/h3c/`.
- **What was deliberately not vendored:** upstream `__init__.py` (this pack
  wires `routes.register()` + `comfy_entrypoint` itself), `web/` as a
  separate dir (files merged into `js/` — only one WEB_DIRECTORY per pack),
  `logs/` residue, `requirements*.txt` (folded into this repo's
  `requirements.txt`), `mkdocs.yml` (guide/ kept as source).
- **Local adaptations** (all inside `tests/h3c/` — the vendored suite is
  isolated so `tests/run_tests.py` never globs it):
  - `tests/` → `tests/h3c/` nesting: JS specifiers `../../web/` →
    `../../../js/`, root refs `../..` → `../../..`, Python
    `from tests.*` → `from tests.h3c.*`, `parents[N]`/`dirname` depths +1 in
    `test_skill_pack.py`, `test_shot_split_server.py`, `test_smoke_harness.py`,
    and helper `sys.path` inserts now reach `../../tools`.
  - `tests/h3c/__init__.py` prepends `COMFY_ROOT` to `sys.path` so ComfyUI's
    own `nodes.py` wins over this pack's root `nodes.py` during
    `import nodes` inside ComfyUI's `server.py` (upstream has no root
    `nodes.py`, so this collision is new to the merged pack).
  - `tests/h3c/run.mjs` resolves this machine's Comfy-Desktop venv +
    `COMFY_ROOT`, sets `PYTHONPATH=$COMFY_ROOT` for the product tests that
    import `h3_continuity` without `enable_comfy_cpu()`, and globs
    `tests/h3c/{js,web}`.
  - `tools/module_versions.mjs` scans `js/` (was `web/`); its test fixture
    builds a `js/` tree.
  - `tests/h3c/web/video_layers_model.test.mjs` reads a historical model via
    `git show 33b7466:...` — requires upstream objects; fetch
    `h3c-upstream` (see below) on fresh clones or the test fails.
- **Sync procedure:** fetch upstream in the fork clone
  (`git -C C:\Users\richk\CascadeProjects\ComfyUI-H3-Continuity-Studio fetch upstream`),
  diff `h3_continuity/` against the vendored copy, re-copy changed files,
  re-apply the local adaptations above, re-run `tests/h3c/run.mjs`.
  Never git-merge across repos — histories differ. The satellite carries a
  `h3c-upstream` remote for fetching upstream objects (needed by the
  history-dependent JS test).

## guaardvark-derived code (ResonanceStudio side only)

Not vendored here. guaardvark (MIT) ports live in the ResonanceStudio repo;
see its THIRD_PARTY_NOTICES.md.
