# Studio MCP Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for Native execution; switch to superpowers:subagent-driven-development only if the user chooses that method. Steps use checkbox (`- [x]`) syntax for tracking. Design is approved. Native is the stated default after the optional execution-preference question; the user may steer it. README/docs installation work is explicitly authorized.

**Goal:** Deliver the standalone Studio MCP adapter, current skills and capability coverage, and tested README/guide installation instructions for Codex and Claude Code.

**Architecture:** A separate Python stdio MCP process calls existing Studio HTTP operations. Small host additions serve exact skill resources and saved native execution snapshots; managed projects keep the existing API. The adapter exposes domain tools, Skills extension methods through the SDK's public extension interface, and durable native submission receipts without a background scheduler.

**Tech Stack:** Python >=3.11; `mcp==2.3.0`; its installed `httpx2` transport dependency (declare `httpx2>=2.10,<3` because the adapter imports it); PyYAML >=6,<7 for real frontmatter parsing; stdlib unittest, Node tests and existing MkDocs tooling. MCP packages belong only to the adapter environment. PyYAML is already a ComfyUI dependency; declare its host use explicitly in `requirements.txt`.

**Spec:** [Approved design](../specs/2026-11-08-mcp-tools-skills-design.md). [Capability audit](../../research/2026-11-08-mcp-capability-audit.md).

## Global Constraints

- Codex/Claude Code launch stdio locally; Studio URL may be local/remote and include a reverse-proxy prefix. Default `http://127.0.0.1:8188`.
- Existing seven skills remain host-authoritative. Use exact served bytes, SHA-256, byte lengths and complete frontmatter; no adapter-local substitution.
- Saved projects are shared; no browser synchronization, automatic merge or forced stale save. Preserve existing revisions, immutable checkpoints and render ownership.
- Native execution needs a validated saved API snapshot. Older projects stay editable and return `execution_snapshot_required` before execution; a normal updated Studio save or explicit snapshot registration supplies it.
- Preserve exact integer seeds and unknown authored metadata. Cross-client editable documents travel as JSON **strings** (`document_json`/`arguments_json`), avoiding JavaScript integer rounding inside MCP client applications.
- No generic HTTP/eval/filesystem tool, new job scheduler, implicit sequence fork, replacement-bridge generation or live GPU/model runs.
- Stdout is MCP only in server mode; logs are stderr. `--check` is a separate read-only diagnostic mode.
- README and published guide installation/configuration instructions are required user deliverables, including Windows quoting, both clients, URLs, authentication and verification.

## Review Focus

1. An old/linked/subgraph workflow must remain editable without fabricating a runnable snapshot; test in Task 2.
2. A stale save or late Story/still result must preserve newer saved work and retain the result; test in Tasks 2 and 6.
3. Two adapter processes or a restart after a lost reply must not duplicate GPU work; test in Task 5.
4. Remote URL prefixes, credentials, binary downloads and CRLF skill files must preserve routing, containment and byte identity; test in Tasks 1, 3 and 4.
5. A seed `18446744073709551615` and opaque consumer fields must survive a client read/edit/save round trip; test in Tasks 2, 4 and 8.

## Verified planning facts and SDK correction

PyPI metadata and the actual `mcp==2.3.0` wheel/sdist were inspected. The release supports `MCPServer`, `Extension` and `MethodBinding`, but does **not** ship the documentation's `mcp.server.skills`/`mcp.shared.skills` helpers. Use `mcp.server.extension.Extension` and `MethodBinding` for `skills/list` and `skills/get`. The SDK registers capabilities and handles JSON-RPC; our small extension supplies spec-shaped request/result models and handlers. No private SDK patch, vendored upstream module or Git dependency.

Existing `examples/timeline_api.py` remains a dependency-free single-file client. The adapter's small `httpx2` transport follows its existing URL, redirect, size-limit and verified-download contracts; do not refactor that script into a package or duplicate its urllib implementation. Test parity at boundaries instead.

Installed planning baseline: Codex CLI `0.166.0`, Claude Code `2.1.316`, ComfyUI embedded Python `3.13.14`. Their presence is not a successful connection/Skills-loading claim.

## Files and interfaces

Host: new `h3_continuity/agent_api/{__init__,resources,projects,routes}.py` and `coverage.json`; hook registration into `h3_continuity/routes.py`. Modify `story_library.py` and `web/h3c_story.js` to retain already-captured save-time API snapshots. Reuse current state/library helpers and sequence ownership guards.

Adapter: new `mcp_adapter/pyproject.toml`, `uv.lock`, `src/h3c_mcp/{__init__,__main__,transport,guidance,skills,server,tools,receipts,jobs}.py`, plus `tests/` and fixture support. Each module has the named responsibility implied below; split tools by family only if that file becomes difficult to review.

Documentation: `README.md`, `guide/automation/mcp.md`, `guide/automation/api.md`, `mkdocs.yml`, `docs/MCP.md`, `tests/README.md`, and the seven existing skill bodies. Add `.gitignore` entries for the adapter environment/build outputs and any parent-owned implementation worktree when needed.

Common wire structures (plain JSON, opaque identifiers preserved):

- `Target`: `{kind:"managed", id:str}` or `{kind:"native", graph:str, timeline_node:str, story_node?:str}`.
- `Revision`: managed `{project:int}`; native `{state:int, workflow:int, execution:int}`. These are separate stores, not one interchangeable revision.
- `ProjectView`: `{target, revision, document_json:str, capabilities:object, execution_ready:bool, ...}`. Managed document is authored project fields; native document is `{timeline:object, settings:object, story?:object, extra_widgets:object}`. Full UI/API graphs are retrieved/registered explicitly, not duplicated editable fields in this document.
- `JobHandle`: `{kind:"managed"|"video"|"story"|"still"|"reference", id:str, target, request_key?:str}`. Every status/cancel tool uses this handle; never guess job kind from a bare ID.

Host routes (agent API version 1):

- `GET /h3c/agent/catalog`: `{agent_api_version:1, catalog_sha256, skills:[...], resources:[...], coverage:...}`.
- `GET /h3c/agent/resource?uri=...&digest=...`: original bytes for one catalog URI; 409 if expected digest changed, invalid/unknown URIs rejected.
- `GET /h3c/agent/projects`: native registered/saved-library targets, stable IDs/cursors; not all host files.
- `POST /h3c/agent/projects/read`, `/save`, `/register`, `/context`: typed native target read/save/registration/validated execution-context operations. They never submit a prompt.

Adapter tests: `uv run --project mcp_adapter python -m unittest discover -s mcp_adapter/tests -t mcp_adapter -v`.
Targeted host tests use the project's ComfyUI Python and `COMFY_ROOT`; configure those as documented in `tests/README.md`. Final host check is `node tests/run.mjs`, which selects and sets those defaults itself.

## Task 1: Host guidance catalog and capability coverage

**Files:** create `agent_api/__init__.py`, `resources.py`, `routes.py`, `coverage.json`; modify `h3_continuity/routes.py`, `requirements.txt`; tests `tests/test_agent_resources.py`.

**Interfaces:** `resources.catalog() -> dict`; `resources.read(uri: str, digest: str|None=None) -> tuple[bytes,str]`; `routes.register(instance) -> None`. `read` is allowlist-based and never treats a URI as an arbitrary path.

- [x] Write failing tests for all seven skills, entry discoverability, full YAML frontmatter, CRLF bytes and supporting files, allowlisted guide/client resources, changed digests, duplicate/malformed names, unknown URIs, traversal and symlink escape. Assert returned manifest SHA and length equal the exact bytes read.

  Regression `test_catalog_manifest_matches_served_bytes`:
  ```python
  for skill in resources.catalog()['skills']:
      for item in skill['resources']:
          raw, _ = resources.read(item['uri'], item['digest'])
          self.assertEqual(len(raw), item['size'])
          self.assertEqual('sha256:' + hashlib.sha256(raw).hexdigest(), item['digest'])
  ```
- [x] Run `python -m unittest discover -s tests -t . -p test_agent_resources.py -v` with the normal CPU bootstrap. Confirm missing module/route failures.
- [x] Implement catalog/read functions using real YAML parsing and contained file resolution. Catalog optional upstream guide bodies as currently installed, without downloading material. Register HTTP catalog/resource routes on the current ComfyUI origin.
- [x] Add `coverage.json`: every audited feature family has source references, skill names and planned tool names or a reasoned graph/browser/unavailable classification. Cover all 17 registered nodes. Native-only operations are labeled rather than advertised for managed targets.
- [x] Run tests; verify no MCP import/dependency enters the host. Commit the coherent host guidance change.

## Task 2: Saved native targets and executable snapshots

**Files:** create `agent_api/projects.py`; extend `agent_api/routes.py`; modify `story_library.py`, `web/h3c_story.js`; tests `tests/test_agent_projects.py`, `tests/js/agent_snapshot_save.test.mjs`; stamp module versions.

**Interfaces:** `projects.list_projects(cursor=None, limit=50) -> dict`; `read(target) -> ProjectView`; `save(target, expected_revision:dict, document:dict) -> ProjectView`; `register(target, workflow_ui:dict, workflow_api:dict, expected_revision:dict|None=None) -> ProjectView`; `context(target, expected_revision:dict, operation:str) -> dict`. Context returns validated native request fields, graph, selected outputs/recipe and source revision; it does not queue work.

- [x] Write failing read/save tests based on a temporary Story library/state store and explicit Timeline-only registration. Include stale state/wiring/execution revisions, checkpoint immutability, exact uint64 seeds/opaque fields, managed-sequence rejection, missing/wrong node IDs and a new snapshot on an old graph ID.
- [x] Write failing execution-readiness tests: legacy UI-only story remains editable; matching API snapshot becomes runnable; changed wiring, unsupported subgraphs or computed/ambiguous bindings yield `execution_snapshot_required`/recapture error before execution. Literal widgets and supported Primitive inputs update both UI and executable values correctly.

  Regressions `test_old_story_is_editable_without_execution_snapshot` and `test_stale_save_preserves_newer_seed` use the temporary project fixture:
  ```python
  before = projects.read(target)
  self.assertFalse(before['execution_ready'])
  self.assertEqual(json.loads(before['document_json'])['timeline']['boxes'][0]['seed'], 18446744073709551615)
  # Save once with before['revision']; a second distinct save using that revision must fail.
  self.assertEqual(projects.read(target)['document_json'], accepted['document_json'])
  ```
- [x] Run the tests red. Implement snapshots under the existing host user data boundary in `h3c_agent/projects/<sha256(graph)>.json`, containing graph/UI/API identities, binding map and source hashes/revisions. Use existing saved-state lock and atomic file replacement; do not invent new project IDs. Story-library save gains an optional API snapshot argument; old callers stay valid. Explicit Timeline-only registration uses the same snapshot store.
- [x] Resolve native authored values through the saved workflow plus current widget overlay. Validate all fields before writes. A partial filesystem failure must retain authored data and make a mismatched execution snapshot unusable; add a failure-injection regression. Never claim a multi-file save is transactional when it is not.
- [x] Extend the existing Story save's already captured API prompt into snapshot retention. Bind only known Timeline/Story literal/Primitive controls; complex linked inputs invalidate execution readiness rather than being overwritten. Frontend fixture asserts the saved capture matches the workflow state/revision; no polling or browser bridge is added.
- [x] Use existing ownership checks to reject native mutation/context access for attached managed sequences; preserve busy/checkpoint guards. Expose native read/save/register/context routes with structured errors.
- [x] Run targeted Python/JS tests and `node tools/module_versions.mjs --write` / `--check`. Commit the native persistence change.

## Task 3: Isolated adapter packaging and bounded HTTP transport

**Files:** create adapter package/project, `transport.py`, `__main__.py`, test package and `test_transport.py`, `test_cli.py`; update `.gitignore`.

**Interfaces:** `StudioClient(base_url:str, token:str|None=None, timeout:float=30)` with `json(path, *, method="GET", body=None, key=None) -> dict`, `bytes(path, *, expected_digest=None, expected_size=None) -> bytes`, `upload(path:Path, kind:str) -> dict`, `download(descriptor:dict, destination:Path) -> dict`. `StudioError` retains `code`, `status`, `path`, `details`.

- [x] Write failing fixture-server tests for proxy prefixes, auth headers, query encoding, native/managed errors (including HTTP 200 `ok:false`), timeouts, malformed/oversized responses, nonfinite JSON, redirects and same-origin boundaries. Assert errors/logs never contain the bearer token.

  Regression `test_remote_prefix_auth_and_redirect_boundary`: fixture records a request to `/comfy/h3c/agent/catalog` with the configured bearer header; a response redirect to a second fixture yields an error, and the second fixture has zero requests. `test_failed_download_preserves_destination` asserts:
  ```python
  self.assertEqual(destination.read_bytes(), b'previous-output')
  self.assertNotIn(token, str(error))
  ```
- [x] Write failing streaming upload/download tests: original hashes, changed-size/hash rejection, existing destination preserved on failure, local root/symlink containment and remote-host paths. Reuse a small stdlib HTTP fixture; no ComfyUI required.
- [x] Implement using installed `httpx2` primitives and the existing client's boundary rules. Keep the existing example client unchanged. Pin SDK 2.3.0 and lock dependencies in the isolated project; require Python >=3.11.
- [x] Implement `h3c-mcp --studio-url URL --token-env NAME --workspace-root PATH --state-dir PATH`; `--check` fetches catalog/capabilities and prints a small JSON diagnostic then exits. Normal execution runs stdio and sends logging to stderr. `--token-env`, root and state directory have safe defaults where applicable; never accept a raw token argument.
- [x] Run adapter tests in a clean environment, check imports while ComfyUI/torch are unavailable, and verify the launcher/diagnostic with the fixture. Commit packaging/transport.

## Task 4: MCP Skills, resources and saved/managed tools

**Files:** create `guidance.py`, `skills.py`, `server.py`, `tools.py`; tests `test_skills.py`, `test_server.py`, `test_projects.py`; complete host coverage tool references.

**Interfaces:** `Guidance(client)` supplies `catalog()`, `get_skill(uri)`, `read(uri, digest=None)`; `SkillsExtension(guidance)` subclasses the released SDK's `Extension`, advertises `io.modelcontextprotocol/skills`, and returns `MethodBinding` entries for required methods. `create_server(client, guidance, receipts, roots) -> MCPServer` registers only typed domain tools/resources.

- [x] Write a failing SDK stdio integration: discover tools and ordinary resources; call actual `skills/list`/`skills/get` via the SDK extension method interface; verify required result/caching shapes for negotiated protocol versions, all file digests/frontmatter, unknown URI errors and no directory-read advertisement. Test a client that does not opt into Skills still reads resources/tools.

  Regressions `test_stdio_skills_manifest_and_resources` and `test_unadvertised_directory_read_rejected` assert the wire results:
  ```python
  self.assertEqual(skill['uri'], 'skill://h3-continuity-video/SKILL.md')
  self.assertEqual(skill['frontmatter']['name'], 'h3-continuity-video')
  self.assertNotIn('directoryRead', extension_settings)
  self.assertEqual(unknown_skill_error['code'], -32602)
  ```
- [x] Implement the two Skills bindings and Pydantic request/result models against the official specification. Use SDK `RequestParams`/pagination/base result types and capability registration; no custom JSON-RPC loop. Enforce catalog/read identity and reject content changes before returning bytes under a stale digest.
- [x] Register `h3_capabilities`, `h3_read_guidance`, `h3_list_projects`, `h3_get_project`, `h3_create_project`, `h3_save_project`, `h3_register_workflow`, `h3_export_workflow`, `h3_upload_asset`, `h3_download_artifact`. Project tool signatures use the Target/Revision structures above, and authored input/output uses JSON strings. List each project kind separately with its own pagination cursor.
- [x] Register managed `h3_plan_video`, `h3_render_video`, `h3_job_status`, `h3_cancel_job`, `h3_resume_job`, `h3_abandon_job` with explicit JobHandles and request keys. Preserve hashes/revisions/held states. Human-attested abandon requires its existing reason/prompt evidence; it is never automatic.
- [x] Test managed lifecycle and native read/save against the fixture, including conflict details, unsupported target operations, disconnected host errors, unchanged uint64 text, pinned profile and no native fallback. Check tool annotations accurately represent status materialization and filesystem/network effects.
- [x] Run tests and commit the runnable server/core tools.

## Task 5: Recoverable native video and submission receipts

**Files:** create `receipts.py`, `jobs.py`; extend `tools.py`; tests `test_receipts.py`, `test_native_jobs.py`.

**Interfaces:** `ReceiptStore(state_dir, studio_identity).claim(request_key, request_hash)` is a context manager using an OS-released nonblocking file lock. `load`, `write` store prepared/submitting/accepted/terminal state atomically. `NativeJobs.prepare(target, revision, selection)`, `submit(prepared, request_key) -> JobHandle`, `status(handle) -> dict`, `cancel(handle) -> dict` drive one native unit per explicit submit.

- [x] Write failing cross-process/restart tests: one native submission for the same key/body; a changed body/key conflict; lost acknowledgement; no queue/history evidence; unrelated prompt evidence; process crash releases the advisory lock but retains a submitting receipt. Assert POST count never increases on ambiguous retry/status.

  Regression `test_lost_ack_restart_never_resubmits`: fixture accepts one prompt and drops its response; recreate the adapter against the same state directory, retry the same key, then poll. Assert:
  ```python
  self.assertEqual(prompt_posts_before_retry, 1)
  self.assertEqual(prompt_posts_after_retry_and_status, 1)
  self.assertIn(result['state'], ('accepted', 'queued', 'running', 'succeeded', 'failed', 'needs_reconciliation'))
  ```
- [x] Implement receipts with hashed origin/key paths, exact submitted body/hash and prompt/result provenance. Use `msvcrt`/`fcntl` advisory locking as appropriate so crashes do not leave permanent lock files. Do not expire uncertain submission evidence or create another sequence to recover it.
- [x] Obtain native context from Task 2, reuse current Timeline preparation/regeneration contracts, and submit only the chosen output closure. Mirror the existing external Timeline receipt attribution and still metadata contracts instead of adding a generic `/prompt` tool. Status reads queue/history once and validates ownership/input identity.
- [x] Implement native `h3_plan_video`/`h3_render_video` branches, including continuity-rebuild fingerprint/selection. One submit renders one eligible unit; skill-driven iteration handles remaining units/takes. Managed progression remains server-owned.
- [x] Scope cancellation to positively identified owned work. If existing host APIs cannot cancel safely, return the boundary; never call global Stop. Tests assert no unrelated queue mutation and no submission from a status read.
- [x] Run tests and commit native recovery support.

## Task 6: Story, stills, references, takes and saved-library workflows

**Files:** extend `tools.py`, `jobs.py`, host `projects.py` only where saved-state resolution is needed; tests `test_domain_tools.py`, `test_still_jobs.py`, `test_story_jobs.py`.

**Interfaces:** typed tools `h3_story(action, target, arguments_json, expected_revision=None, request_key=None)`, `h3_stills(...)`, `h3_takes(...)`, `h3_library(...)`, `h3_inspect(...)` use finite action enums and validated domain payloads. They map only to allowlisted existing operations; no user-selected route strings. Publish each action's schema/required fields in tool guidance.

- [x] Write failing parameterized endpoint/ownership cases for every action in the audit: Story write/rewrite/feedback/template/check/bible; still prompts/sources/import/pin/candidate generation/recovery/reference catalog/prepare/approve; take list/use/rate/deletion preview/apply; saved library versions/rename/delete/checkpoint/restore; generation start/history/export/preflight/import; audio/image metadata and node/schema inspection.
- [x] Implement native context resolution and domain mappings using existing routes. Require snapshots only for actions that need execution; pure saved edits/library reads stay usable on old projects. Managed-incompatible native operations return an explicit boundary with the existing deliberate export/fork route as guidance.
- [x] Complete native still preparation → persisted receipt → `/prompt` → result/provenance flow; preparation alone must not be reported as generation. Story jobs use write/current/poll/taken/cancel lifecycle and stable graph/client identity. A lost Story start reply queries current/recovery before any retry; unknown outcome remains held locally.
- [x] Tests return finished Story/still proposals without changing saved authored state. Apply prompts/accepted guides only with an explicit `h3_save_project` or acceptance action and the expected revision. Assert a target edited during execution remains unchanged and the completed result stays retrievable.

  Regressions `test_late_story_result_is_proposal_until_explicit_save` and `test_managed_take_cleanup_cannot_use_native_route` assert:
  ```python
  self.assertEqual(project_after_poll['document_json'], newer_save['document_json'])
  self.assertTrue(job_result['result_available'])
  self.assertEqual(native_take_delete_requests, [])
  ```
- [x] Preserve source clocks, bound audio windows/dialogue, manual still prompts, acceptance state, local generation media verification, checkpoint identity and scoped take cleanup. Destructive calls retain preview/explicit action semantics; no automatic cleanup/fork/model download/key readback.
- [x] Test disabled replacements/retired actions are refused, and that new project/generation actions preserve the uploads/settings/history required by current behavior. Run suites and commit complete domain coverage.

## Task 7: Current skills and MCP installation documentation

**Files:** modify the seven `skills/*/SKILL.md`, `README.md`, `mkdocs.yml`, `guide/automation/api.md`, `tests/README.md`; create `guide/automation/mcp.md`, `docs/MCP.md`; finalize `agent_api/coverage.json`.

**Interfaces:** all commands launch the actual Task 3 console entry point and all tool/action names match Tasks 4–6. The host catalog automatically serves edited skills; existing `skills/install.py` remains usable.

- [x] Correct the four audited stale claims: smallest-size/mixed-aspect assembly; cached FLF2VA raw audio; Shot-split frontmatter; bible's render-time Cast/reference use. Add current checkpoints/autosave, generation histories, P-H3 sizing/LoRA, audio locks/dialogue, continuity recovery, take cleanup/ratings, Disk Cache and preview guidance to the relevant existing skills.
- [x] Add MCP operation references alongside retained HTTP instructions. Include saved/native/managed identity, missing execution snapshots, explicit result application, revisions, native receipt progression and disabled/browser-only boundaries. Validate every tool/resource reference using catalog/registry data rather than exact prose assertions.
- [x] README: add a concise MCP installation section with prerequisites, isolated adapter installation/launcher, default Studio URL and links to the full guide/reference. Make clear the adapter environment is separate from ComfyUI's Python; remote Studio requires updating the host node too.
- [x] Published guide: provide `uv run --project <checkout>/mcp_adapter h3c-mcp ...` and isolated-venv `python -m pip install <checkout>/mcp_adapter` paths, copyable `codex mcp add ... -- <launcher>` and `claude mcp add --transport stdio ... -- <launcher>`, Windows paths containing spaces, local/remote URLs/proxy prefixes, bearer-token environment configuration, workspace roots and receipt location.
- [x] Include `--check`, `codex mcp list/get`, Claude `/mcp`/health checks and example first read-only requests. Explain extension discovery versus ordinary resource reading versus filesystem skill installation; do not claim both clients automatically load extension skills. Document host-version mismatch, offline host, missing model/snapshot, revision conflict and held receipt recovery.
- [x] Link guide under Automation, cross-link HTTP API page, and put detailed operation examples/contracts in `docs/MCP.md`. Update test instructions for the separate adapter environment and client smoke.
- [x] Run skill-pack/coverage tests and `uv run --with-requirements requirements-docs.txt python -m mkdocs build --strict --site-dir .tmp/mcp-docs`. Commit skills/docs together after checking all launch commands against the fixture in Task 8.

## Task 8: Documented setup, client smoke and final verification

**Files:** create `mcp_adapter/tests/test_stdio_workflow.py`, fixture helpers and `tools/mcp_client_smoke.py` only if needed to make client checks reproducible; update test docs, CHANGELOG and roadmap evidence.

- [x] Run the README/guide launchers from another working directory and an installation path containing spaces, both repo/uv and isolated-venv paths. Verify `--check`, stderr/stdout separation, wheel installation without the source checkout and import without host dependencies.
- [x] Use a real SDK stdio connection to the running fixture for tool discovery, Skills manifests/resource reads, saved read/edit/conflict, native old-snapshot readiness and exact seed/metadata round trips. Test supported legacy protocol behavior separately from modern Skills negotiation.

  Regression `test_document_round_trip_through_stdio_preserves_uint64` changes one prompt in `document_json`, saves it and rereads it. Assert:
  ```python
  self.assertEqual(saved_document['timeline']['boxes'][0]['seed'], 18446744073709551615)
  self.assertEqual(saved_document['consumer']['opaque'], original_document['consumer']['opaque'])
  self.assertGreater(after['revision']['project'], before['revision']['project'])
  ```
- [x] Test installed client launch/configuration without changing the user's global setup or contacting live ComfyUI. Codex has process-local `-c` configuration and an app-server status API; inspect/generated schema for its current `mcpServerStatus/list` interface and confirm fixture server/tool discovery without a model turn. Claude supports connection health checks; use an isolated task-specific config directory. Do not set or repurpose HOME/CODEX_HOME, invoke another model, or silently broaden existing MCP configurations.
- [x] Record exact client versions and observed handshake/tool/extension evidence. If an actual client cannot load extension skills, verify its documented resource/filesystem fallback and state that limit. SDK extension conformance and actual client activation are separate results. If a client cannot be exercised safely, retain the unverified acceptance item rather than claiming passing.
- [x] Run adapter suite, `node tests/run.mjs`, strict guide build, `node tools/module_versions.mjs --check`, syntax/import checks, and `git diff --check`. Inspect changes for unintended local-file/dependency/workflow edits.
- [x] Obtain the execution method's required final independent review. Fix concrete findings, rerun only affected checks, then record the final capability coverage, client evidence and remaining limitations in the feature ledger/Recovery State. Commit coherent final changes; PR/release/deployment require their own existing authorization.

## Self-review / spec coverage

- Host skill source, manifests, guides and coverage → Tasks 1, 4, 7.
- Shared native/managed saves, snapshot capture and revision/ownership boundaries → Tasks 2, 4, 6.
- Isolated packaging, remote transport, roots, media integrity and startup → Tasks 3, 8.
- Complete executable operations, native recovery, Story/still proposals and no implicit merge → Tasks 4–6.
- README/docs installation requirement and compatibility messaging → Tasks 7–8.
- All five Review Focus conditions have named tests in their owning tasks. No requirement is intentionally dropped. No UI-to-API compiler, synchronization subsystem or background scheduler was introduced.

Execution recommendation: **Native**, with one final independent review. The tasks share saved-state, transport and receipt interfaces heavily, so a single implementer avoids repeated handoffs while the plan carries their contracts.
