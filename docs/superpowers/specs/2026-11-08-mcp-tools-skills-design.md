# MCP tools and skills for H3 Continuity Studio

Status: **approved by the user; implementation planning in progress**. User also explicitly requires README/docs MCP installation instructions.

Roadmap: [MCP0](../../roadmap-discipline/phases/2026-11-08-mcp-tools-skills.md).
Evidence and capability inventory: [source audit](../../research/2026-11-08-mcp-capability-audit.md).
Baseline: v0.19.5, main `b5b734e`.

## Intent and agreed decisions

Let an agent discover what this installation can do, load the maintained H3 skills, edit a saved production, prepare and submit supported work, and retrieve its results. Codex and Claude Code are the first clients. The same capability documentation must accurately cover current Studio features and identify unavailable behavior.

The user selected a **standalone MCP adapter** launched by the agent. It uses **stdio** for MCP and connects to a configured **local or remote Studio HTTP URL**. The existing `skills/` pack is the source of guidance and is also distributed through the official MCP Skills extension.

The user explicitly does not require browser synchronization. A person and an agent can edit the same saved project; a later save from an older state may overwrite newer work where the existing persistence permits it. Preserve existing revision checks as a small safeguard. There is no automatic merge, live-browser bridge, collaborative document model or requirement to keep a tab open.

Everything below marked as a design choice is the author's proposed implementation, rather than an additional user decision. Approval of this document approves those choices.

## Approaches

1. **Standalone adapter calling Studio HTTP — selected by the user.** Reuses host operations, keeps MCP dependencies outside ComfyUI, and works with either a local or reachable remote Studio. The adapter needs a small separate installation and host-version compatibility checks.
2. **Embedded MCP endpoint in ComfyUI — considered.** Gives one server address/lifecycle, but couples the SDK/transport and dependencies to ComfyUI's aiohttp process. The user chose the standalone option.
3. **Existing filesystem skills and raw HTTP alone — insufficient.** Useful as a compatibility path, but does not satisfy the requested executable MCP tools and Skills extension.

## Scope and completion

This is a project spanning the adapter, a few supporting host APIs, skill corrections and missing guidance, and verification. The adapter itself stays thin: Studio continues to own validation, rendering rules, media and persistent projects.

Complete means:

- Every capability family in the audit has a maintained classification: executable MCP operation, authored data plus skills, graph-configuration guidance, browser-only guidance, or explicitly unavailable.
- Saved managed projects and saved native Studio work are distinguishable and can be read/edited through their correct persistence paths. Supported render/Story/still tasks have a complete prepare/submit/status/result path with recovery.
- The running host supplies current skill content and supporting guides, and the adapter implements the official Skills extension using the SDK.
- Codex and Claude Code have tested MCP setup instructions. Extension loading is reported separately from ordinary tools/resources; filesystem installation remains supported if a client does not load extension skills.
- Existing HTTP clients/workflows continue to work. No change to rendering/timing semantics, no new replacement-bridge generation, and no dependency installation into ComfyUI for MCP.

Release, merge, live installation, service restart and GPU generation are outside this design/implementation authorization. Rendering tools are implemented and tested with stand-in host operations; actual generation remains an explicit caller action.

## Adapter and connection

Design choice: Python adapter under `mcp_adapter/`, with its own `pyproject.toml`, package and `h3c-mcp` console command. The adapter must import and run without ComfyUI, torch or model files. Use the official Python MCP SDK and its extension interface; do not hand-write JSON-RPC or extension negotiation. Dependency verification during planning found that the released `mcp==2.3.0` wheel and sdist omit the documented built-in Skills helpers, while the official repository's main branch contains them. Use the released SDK's public `Extension`/`MethodBinding` API for the two required Skills methods and ordinary resources, with conformance tests. This corrects an implementation assumption; transport and feature scope are unchanged. Pin the verified release rather than requiring an unreleased Git dependency.

The launcher takes a Studio base URL with optional reverse-proxy prefix. Default is `http://127.0.0.1:8188`. Provide repo-based `uv run --project ...` and ordinary isolated-venv instructions for both clients. stdout carries MCP only; logs go to stderr. Multiple agent processes may connect to the same host; server revisions and existing job ownership arbitrate writes.

Reuse the dependency-free HTTP client's URL validation, response limits, no-redirect behavior and verified upload/download patterns from `examples/timeline_api.py`. Factoring its transport into an importable, ComfyUI-free location is allowed if needed; preserve existing CLI imports/behavior and avoid copying implementations. Normalize both native string errors and managed structured errors into MCP tool errors, retaining host codes, paths and details.

For remote authenticated proxies, accept a bearer token through an environment variable, never through a logged argument. Retain TLS verification. Do not add an OAuth server, proxy or listening network port to the adapter. Additional proxy authentication mechanisms are builder decisions only if required by an actual supported setup, not speculative options.

Use one configured Studio origin per process. Tool inputs cannot choose arbitrary HTTP endpoints. Calls are restricted to documented Studio operations, required ComfyUI preparation/submission/status endpoints, and server-returned same-origin media routes. Local asset uploads stream bytes; no adapter-local path is presented to a remote host as its own path. Local uploads/downloads use explicit paths within declared MCP roots or a configured workspace root, resolve symlinks, and replace downloads only after verification.

## Saved targets and edits

Use explicit target identity in each applicable tool. Do not guess from the last selected clip or browser tab:

- **Managed target:** existing Timeline API project ID. The profile stays pinned. Use project revisions, planning hashes, leases and managed jobs/artifacts.
- **Native target:** saved graph identity plus selected Timeline node; include the Story node only for Story operations. Saved Story library IDs are discoverable handles that resolve to these identities. Native targets remain native sequences and are not silently imported as new managed projects.

Discovery includes managed project listing and the saved Story library. Timeline-only workflows can be supplied/registered as an explicit workflow snapshot with graph and Timeline identity. Do not crawl arbitrary host folders to discover workflows, pretend the Story library contains every native Timeline, or duplicate existing identities. A snapshot registration validates that its identities agree with its contents.

Design choice: read/save tools return authored data, target identity, supported operations and current revision information. Authored Timeline updates are full document replacement under the existing contract, preserving unknown fields, exact integer seeds, settings, references and Story state. A generic revision-checked document update covers ordinary clip edits, prompts, joins, memory, pins, plates, audio windows and text; do not build one tool per UI gesture.

Keep `/h3c/state` widget revisions, saved-library wiring revisions and managed revisions separate. Reuse their conflict responses. On a stale save return a conflict with enough current identity/revision information to reread and deliberately retry; do not silently change the expected revision or merge content. Preserve immutable checkpoints and active render/take leases. Do not introduce automatic overwrite, global collaborative locks or a blanket force-save flag.

Agent reads see saved data only. Existing browser autosave behavior can continue, but the MCP workflow does not depend on browser polling or promise the open tab reflects an agent save.

### Executable native snapshots

An editor workflow JSON is not an executable ComfyUI API graph. Current Story saves already send `prompt: captured.output`, but `story_library.save` does not retain it. Address this explicitly instead of introducing a general-purpose UI-to-API compiler.

Design choice: retain an optional execution snapshot alongside a native saved workflow: API graph, graph/Timeline/Story identity, selected output/recipe identities and the authored-state/wiring identity against which it was captured. Reuse the frontend's actual `graphToPrompt` result on ordinary saves; capture is a save-time operation, not browser synchronization. The execution snapshot must be associated with the accepted save revision, not applied to another graph with similar nodes.

Add the smallest host read/registration support needed to retrieve or register this snapshot. Saved Story retrieval supplies its snapshot when present. An explicit supplied native snapshot supports Timeline-only workflows without inventing a Story node. Persist that explicit snapshot under the graph identity so another adapter process can reopen it.

Old saved workflows without an execution snapshot remain readable/editable. Operations needing execution return `execution_snapshot_required` with the remedy: save once using the updated Studio or supply an exported API snapshot. Managed projects with ready profiles do not need this migration.

After authored edits, update execution inputs only through validated bindings for known Timeline/Story widgets and supported literal/primitive inputs, retaining graph wiring and unrelated nodes. Preserve existing text/linked-control resolution rules. A computed input that cannot be safely rebound, ambiguous node mapping, unsupported subgraph or changed wiring invalidates the execution snapshot and returns an actionable recapture error before submission. Graph/model/sampler/LoRA changes require a fresh consistent snapshot, not an invented graph rewrite.

This limitation must appear in capabilities and skills; accepting a project save must not imply it is ready to render. Design leaves exact binding serialization and helper placement to the builder, provided the tests demonstrate that UI values, executable inputs and snapshot identity agree.

## Executable operations

Expose domain operations with ordinary typed MCP tools. Use root object schemas compatible with the first clients. Tool names and file/module layout are left to the builder; scope and behavior are fixed by this table and the audit. Every operation has an input schema, target/ownership policy, output/error contract and tests. There is no generic `http_request`, `run_python`, `evaluate`, or unrestricted filesystem tool.

| Family | Required behavior |
| --- | --- |
| Host/guidance | Capabilities/readiness, schemas, profile choices, available node descriptions and instruction/guide discovery. Distinguish installed/ready/unavailable. |
| Saved work | List/read/create/save managed work; list/read/save native work and register explicit native snapshots. Reuse current native new-project/new-generation/history behavior. |
| Author/inspect | Revision-checked authored edits, effective prompts and timing/mode inspection. Provide the existing timed Shot split transformation through a shared validated operation or documented data editing; never recreate removed guide splitting. |
| Library/recovery | Saved stories/versions/names, named checkpoints and independent restore, generation export/preflight/import/fork. Retain local-media verification and operation identity. |
| Video | Read-only managed planning, native preparation, selected/remaining regeneration, continuity-rebuild preflight, submission, scoped status/cancel/reconciliation and artifacts/previews. Preserve current bounded take counts. |
| Takes | List fit and media, select a compatible take, rate/tag native takes, preview/apply scoped native cleanup. Do not route native mutations around managed ownership. |
| Story/Cast | Existing Write/rewrite/feedback, templates, bible build/link/apply/status/recompile, continuity checks and their job lifecycle. Provider configuration uses existing server-side settings; no credential readback. |
| Stills/references | Sources/import/pin, image descriptions, prepare prompts, prepare/render/recover candidates, reference preparation/catalog/approval and explicit guide/reference acceptance. Preparing a graph alone is not a finished rendering tool. |
| Assets/media | Upload original supported media/transcripts, bind them through authored data, audio inspection, metadata/media locations and verified managed artifact download. Native previews identify their weaker integrity guarantees. |

Graph-only capabilities (P-H3 resolution and LoRA stack, Disk Cache, Context Windows, Join Chain, continuation-model routing, codec/guide frames) receive concrete configuration skills and schema guidance. They execute through an appropriate captured workflow/profile; this design does not add a general graph editor to the adapter.

Browser-only waveforms/beat detection, snap preferences, layout, zoom, playback and session Undo/Redo are documented as browser operations. Frame/time/data authoring remains available through saved edits; do not fabricate server beat analysis or remote browser undo. Disabled replacement bridges and retired compatibility inputs are explicitly classified as unavailable/retired.

### Ownership and job completion

Managed targets always use managed mutation and render contracts. Operations available only natively must return a precise unsupported-operation response for a managed target rather than bypass its lease. Where a user needs a native-only operation, offer the existing explicit workflow/generation fork path; never fork or replace project identity automatically. This is an explicit coverage boundary, not a claim of identical managed/native tool support.

For native jobs, resolve a fresh saved target and validate its snapshot before preparing/submitting. Story or still generation returns proposed results/candidates and job receipts. Apply those results to saved authored state only through a separate revision-checked save/accept action, so a job finishing after an edit cannot silently replace the newer project. Candidate approval remains explicit.

Submission calls return quickly with durable IDs. Status calls poll once; no tool occupies a connection for the duration of a render. Preserve plan hashes, caller-supplied idempotency/request keys and the exact submitted request. Managed retries use existing server idempotency. Native work keeps a small durable receipt in an adapter state directory namespaced by Studio identity, recording prepared/submitting/accepted/terminal state before the relevant side effect; another adapter process must not submit the same receipt concurrently. Use atomic writes/exclusive ownership for that receipt, not a new general job scheduler.

Managed jobs keep their existing server-driven progression after disconnect. Native sequence tools submit one prepared unit at a time; the skill drives remaining boxes/takes by checking the receipt and explicitly submitting the next eligible unit. A status/read call never queues the next unit. On agent disconnect, an accepted ComfyUI prompt can finish while advancement pauses; another agent can resume from the receipt. Do not promise a native autonomous batch or start an adapter background scheduler. Still and Story results use their existing native job lifecycles.

After a lost native submission response, reconcile the retained prompt ID and queue/history evidence. If submission remains ambiguous, report it; do not resubmit, expire the uncertainty or create a different sequence. Existing native still provenance/result checks and external Timeline receipt rules remain authoritative. Native queue/global Stop is not a substitute for scoped cancellation. For native work without safe scoped cancellation, report that boundary rather than interrupt unrelated jobs.

### Errors and outputs

Preserve meaningful errors such as revision conflict, project busy, missing models/profile, unavailable snapshot, unsupported target operation, rejected asset binding and held/uncertain job. Return structured identifiers/details and a short actionable explanation. Remote outages are connection errors, not empty project/skill inventories.

Do not convert uint64 seeds or file stamps through a lossy JavaScript number. Keep exact integer JSON handling throughout authored state and any stored snapshot. Preserve unknown project metadata. Media responses return metadata/resource links rather than embedding full videos in tool context; downloads verify available size/hash evidence before replacing a destination.

## Skills, resources and capability coverage

The running Studio host is authoritative for skill bytes. A local adapter checkout may be a different version; do not publish that checkout's skills as if they describe the host.

Design choice: add a small host catalog/resource interface for agent guidance. Its catalog enumerates each shipped skill's frontmatter and full file manifest, alongside allowlisted guides/client references and content identity. Its resource reader serves the original file bytes under validated, contained paths. Do not derive raw-file hashes from the current normalized `read_text()` instruction bodies. Resources outside skill roots have their own explicit URIs; do not pretend `docs/...` lives inside every skill directory.

The adapter maps the host catalog to `skills/list`, `skills/get` and ordinary resource reads, conventionally `skill://h3-continuity-video/SKILL.md`. Use the SDK's public extension registration and request models with the specification's Skills result shapes; the SDK owns capability advertisement and wire/version handling. Static entries include every file exactly once with SHA-256 and byte size and all frontmatter fields. The adapter detects a catalog/read mismatch and refreshes or reports changed content; it never returns different bytes under a published digest. Unknown names/URIs and path traversal are rejected. Directory reads stay unadvertised unless supporting subdirectories actually require them.

Resources also expose the host instruction bundle, authoritative schemas and allowlisted guides. Server instructions point first to the entry skill. A small guidance read tool supports clients whose agent cannot request resources directly; it returns the same bytes as ordinary context and does not pretend to activate a host skill. Existing filesystem skill installation remains supported. State separately whether each client loaded extension skills, read ordinary resources or used the installed pack.

Update the existing seven skills, keeping their scoped entry structure. Correct the four verified stale claims and add missing current workflows from the audit. Give operations an MCP path and retain the existing HTTP path, including saved-target identity, conflicts, explicit result application and snapshot requirements. No skill may claim support for an unavailable operation or imply disabled features work.

Maintain one small capability map connecting the audited feature families to current source surfaces, skills and tool/explicit-boundary entries. Tests ensure all seven skill folders and registered H3 nodes are classified, tools reference valid skills/resources, and known removed behavior is not advertised as executable. Source-route inventory changes trigger a deliberate coverage review; avoid brittle tests that require a tool for every private helper or a documentation phrase for every line.

## Validation and delivery

Implementation checks must include:

1. Adapter import/start and tool discovery in a clean CPU-only environment without ComfyUI/torch; root ComfyUI installation does not acquire MCP dependencies.
2. SDK client integration over stdio for normal tools/resources and the real Skills extension, including manifests, frontmatter, pagination as needed, unknown URIs, content changes and newline/byte integrity.
3. Saved managed/native edits and conflicting saves; missing/ambiguous native snapshots; updates through literal/primitive controls; invalidated wiring; exact uint64 seeds and unknown metadata round trips.
4. End-to-end mocked prepare/submit/status/result/save flows for managed video, native video, Story and still candidates. Lost replies, retries, process restart and concurrent receipt use must not create duplicate jobs. Held jobs and active leases remain visible/enforced.
5. Negative ownership tests: managed IDs cannot use native takes/status materialization as a bypass. Disabled replacement rendering remains refused; native cleanup preview remains distinct from application.
6. Supported asset upload/download tests with remote-host semantics, proxy prefix, authenticated connection, redirects refused and verified downloads. Skill/resource paths and local filesystem roots remain contained.
7. Targeted existing tests plus the full `node tests/run.mjs` suite, strict guide build when guide pages change, cache-tag stamping if frontend save capture changes, and `git diff --check`.
8. Actual Codex and Claude Code connection smoke against an isolated host fixture: discover tools, read guidance/skill, read/edit saved data and receive a revision conflict. Record exact client versions. Test real extension loading if the installed client exposes it; otherwise report it unverified/unsupported and verify the documented fallback. Do not infer client extension support from SDK conformance alone.

Deliver the adapter, minimal host additions, corrected skills, coverage map and setup/usage guide together. An existing host without the supporting agent/snapshot API gets an explicit version/capability error and upgrade guidance; no silent host/check-out mismatch. No live workflow changes or GPU model runs are necessary to establish this contract.

User documentation requirement: README installation/discovery section plus a published guide page with isolated adapter installation, copyable Codex and Claude Code configuration commands, Windows path quoting and normal venv alternatives, local/remote Studio URLs with proxy prefixes and bearer environment configuration, connection verification, snapshot/conflict/recovery behavior, and the Skills-extension versus filesystem-pack compatibility path. Validate the documented launchers and link the page from the Automation navigation.

## Left to the builder

Choose exact SDK release and Python minimum compatible with it, tool names and split into modules, bounded catalog/cache details, precise validated snapshot-binding representation, and receipt file serialization/locking. These choices must meet the behavior and checks above. Do not change target scope, add browser synchronization or silently drop an audited capability family to simplify implementation.

## External technical references

- [Python SDK Skills support](https://py.sdk.modelcontextprotocol.io/advanced/skills/): built-in extension handles protocol primitives; handlers supply catalogs and resources.
- [Skills extension specification](https://github.com/modelcontextprotocol/ext-skills/blob/main/specification/beta/skills.mdx).
- [Codex MCP configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli) and [Claude Code MCP configuration](https://code.claude.com/docs/en/mcp).

These references establish the protocol and transport direction, not a tested compatibility claim for this adapter.

## Design review evidence

2026-11-08: a fresh read-only builder check reviewed this document and its connected source context and reported **“nothing important left”**. The author made native agent-driven progression explicit afterwards; no additional product decision was introduced. Document links resolve and roadmap/diff checks pass. This is design review evidence, not product or MCP client verification. No implementation has started.
