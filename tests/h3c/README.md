# Tests

```sh
node tests/run.mjs
```

This runs two suites:

- **Browser modules:** `tests/js/*.test.mjs` and `tests/web/*.test.mjs` with `node --test` (Node 20 or later). The tests import `web/` modules directly; none of them needs a browser or ComfyUI.
- **Package:** `tests/test_*.py` and `tests/python/test_*.py` with `unittest`, using ComfyUI's Python because the package needs ComfyUI's dependencies (`jsonschema`). The runner uses `$H3_PYTHON`, then the Windows portable install at `~/ComfyUI/ComfyUI_windows_portable/python_embeded/python.exe`, then `python`. Tests that load ComfyUI on the CPU read `COMFY_ROOT`; the runner defaults it to the portable install's `ComfyUI` folder.

To run one Python file, use discovery from the checkout root. ComfyUI's embedded Python does not put the working directory on `sys.path`, so `python -m unittest tests.name` fails there:

```sh
python -m unittest discover -s tests -t . -p test_shot_split_server.py -v
```

`test_skill_pack.py` checks that the instruction bundle serves every skill in `skills/` exactly, entry first, and that `skills/install.py` links the whole pack.

`test_shot_split_server.py` runs `tests/js/emit_shot_split.mjs` in Node. It checks that the renderer reads a Shot split as a Cut with the guides on the correct shots, and still accepts saved paired endpoint guides and interior guides without Shot markers. It is skipped when Node is not on `PATH`.

These tests run on the CPU and load no models. They do not replace watching a render.

## Standalone MCP adapter

The adapter has its own isolated Python 3.11+ environment; do not install MCP into ComfyUI:

```sh
uv run --project mcp_adapter python -m unittest discover -s mcp_adapter/tests -t mcp_adapter -v
uv run --with-requirements requirements-docs.txt python -m mkdocs build --strict --site-dir .tmp/mcp-docs
```

Adapter tests use an in-process HTTP fixture plus real SDK stdio subprocesses. They cover exact Skills resources, modern/legacy negotiation, uint64 JSON documents, saved revisions, native snapshots, proposal retention, receipt locks/restarts/lost replies and managed ownership. `test_agent_*.py` in the host suite verifies saved native state and catalog routes. No GPU/server restart or live media generation is required. Client smoke uses the same fixture, process-local Codex settings and an isolated Claude config directory, without a model turn or changing the user's global configuration. See [MCP evidence](../docs/roadmap-discipline/phases/2026-11-08-mcp-tools-skills.md) for observed versions and separate Skills activation results.

The optional settings/browser smoke also checks native and attached new-generation host actions, the upload guard, stale history, and desktop/mobile Project settings without connecting to ComfyUI:

```sh
uv run --with playwright python tests/browser/new_generation.py
```

It uses an installed Chrome when available (override with `PLAYWRIGHT_CHROMIUM_EXECUTABLE`), otherwise Playwright's Chromium. Screenshots go to `.tmp/`.

Saved stories attachment/transport regression (actual frontend host methods with synthetic storage):

```sh
uv run --with playwright python tests/browser/saved_story_attachment.py
```

This checks managed load/status GETs, exact Timeline content, asset bindings, recovery of previously stripped attachments, failed lookups, in-flight edits, conflict preservation, native imports/forks and connected text controls. It never contacts ComfyUI and does not test a full custom-node workflow import or render.

Read-only Timelines from a newer version (real Timeline host, Story writer and Studio editor, with a synthetic graph):

```sh
uv run --with playwright python tests/browser/read_only_timeline.py
```

A Timeline whose `requires` names an unknown feature must keep its text byte for byte through editor edits and typing, endpoint adoption on load, a context change, still and reference writes, Story Write and Undo with and without an editor, and undo and redo between whole Timelines. It also checks that the notice is on screen at 1440 and 390 px wide and that **+ Clip**, Render and Generate are off. Screenshots go to `.tmp/read-only-timeline-*.png`.

Structured prompt forms (real Studio/editor/history at desktop and phone sizes):

```sh
uv run --with playwright python tests/browser/prompt_forms.py
```

This isolated fixture routes this checkout's modules locally and mocks Bible, storage and queue responses. It checks Cast insertion, optional/custom fields, the Advanced switch (including on read-only projects), Raw/Sections switching, shot times, draft and guide guards, manual dialogue, history, reload, alternate videos, read-only projects and edits in an 88-clip Timeline. It never contacts ComfyUI, starts a server, mutates a live workflow or generates media. Screenshots go to `.tmp/prompt-forms-*.png`.
