# H3 Continuity MCP reference

For installation, local/remote URLs, credentials and client setup, see the [published MCP guide](../guide/automation/mcp.md). The standalone package is `mcp_adapter`; it uses stdio and the existing Studio HTTP boundary. This file is also served as `h3c://docs/MCP.md`.

## Identity and exact documents

Managed target: `{"kind":"managed","id":"<project UUID>"}`. Native target: `{"kind":"native","graph":"<saved graph identity>","timeline_node":"2","story_node":"1"}`; Story identity is optional for Timeline-only work and required for Story execution.

`h3_get_project` returns `document_json`, a JSON **string**, and `revision`. Managed revisions are `{"project":N}`; native revisions contain separate `state`, `workflow` and `execution` integers. Pass the entire revision unchanged. Parse/edit/stringify authored documents with arbitrary-precision integers: seeds can be `18446744073709551615`. Preserve unknown creative/consumer fields and nested metadata. Inspection, plans and domain results use JSON strings too. Typed IDs/counters outside those strings are safe small metadata.

Native document shape: `{timeline,settings,story?,extra_widgets,...}`. Story contains the saved Story state object; other Story widget inputs are in `extra_widgets`, using `node_id/type/widget_name` keys (for example `1/H3C_Story/idea`). Keep the exact keys returned by the read. Managed document fields are `{name,timeline,settings,assets,consumer,semantic_boxes?}`. Creation also needs an available `profile`; capabilities supplies its schema/readiness. Existing projects retain their pinned profile/digest.

An executable native snapshot is `{ui:<editor workflow>,api:<ComfyUI API prompt>}` with matching saved graph/node identities. `h3_register_workflow` requires the current revision when replacing an existing snapshot. Supported literal/Primitive widget bindings are updated without detaching links; computed or changed wiring requires recapture. No editor-to-API compiler is provided. Snapshot registration, project saves and checkpoint guards are host operations; adapter receipt storage is separate.

An explicit recapture replaces the authoritative saved library workflow and its widget overlay. Linked Primitive numeric/text controls are updated in both the saved editor and API graph; an edit that would change an unedited shared consumer is refused. For timed text with `audio_sha256`, native planning derives a verified asset binding from the saved file-backed audio clip or a direct literal LoadAudio source. Existing preparation rechecks the bytes and transcript audio hash; computed audio needs an explicit supported source rather than bypassing verification.

## Core tools

| Tool | Inputs / result |
| --- | --- |
| `h3_capabilities` | Read host profiles, schemas, queue readiness, agent API version and capability classification. |
| `h3_read_guidance` | `uri`, default `skill://h3-continuity-video/SKILL.md`. Reads host text as ordinary context. |
| `h3_list_projects` | `kind:managed|native`, `cursor?`, `limit` 1–100. Keep cursors with their kind. Native rows saved in the Story library also carry `title`, `sequence`, `library_id` and, for checkpoints, `checkpoint_name`. |
| `h3_get_project` | `target`; authored JSON, revision, readiness, managed inspection/status or native checkpoint state. Native views list `unsupported_features`: Timeline `requires` entries this host cannot read. The Studio opens such a Timeline read-only and saves reject it; `h3_library` `duplicate` with a corrected `timeline_json` makes an editable copy. |
| `h3_create_project` | Managed `document_json` including profile and a durable `request_key`. |
| `h3_save_project` | `target`, `expected_revision`, full replacement `document_json`. No automatic merge. |
| `h3_register_workflow` | Native `target`, `workflow_json:{ui,api}`, `expected_revision?`. |
| `h3_export_workflow` | Managed `target`, `mode:fork|attached` (default fork); returns editor workflow JSON. Deliberate fork isolates native edits from the source project. |
| `h3_upload_asset` | Adapter-local `path`, `kind:picture|guide|audio|video|whisper`. Returns host asset identity/hash; bind returned IDs using the managed schema. |
| `h3_download_artifact` | Immutable managed `artifact_id`, allowed local `destination`. Hash/size verification precedes replacement. |
| `h3_plan_video` | `target`, `expected_revision`, `selection_json`, default `{"kind":"all"}`. Returns plan JSON and SHA-256; never queues. |
| `h3_render_video` | Same target/revision/selection plus `plan_sha256` and permanent `request_key`. Returns durable job handle. |
| `h3_job_status` | `job` handle; polls once, retains evidence/proposals, never submits native progression. |
| `h3_resume_job` | Reconciles the same job; never retries uncertain work. |
| `h3_cancel_job` | Scoped managed/Story cancellation. Native video/still hosts lack a safely scoped cancellation endpoint. |
| `h3_abandon_job` | Managed held jobs only, person's `reason` and matching `confirm_prompt_id`; no automatic abandonment. |

Managed selection follows Timeline API v1: `all`, or `boxes` with `ids`, `rerender?` and an optional reviewed continuity receipt. Native `all` picks the first missing take, retaining outdated takes until explicitly selected; `boxes` picks one requested box and `bridges` one requested insertion bridge (`ids` are before-box IDs). Only one native unit is submitted per call. Plan again after reviewing its result. A preflight requiring continuity rebuild returns affected work and a `{box,fingerprint}` receipt. Review it before placing that exact receipt in `selection_json.rebuild_continuity` and planning/submitting again. Consent modifies the submitted graph, never the saved Timeline.

## Domain tools and action payloads

Each domain tool has a finite `action` enum, `target`, `arguments_json` (default `{}`) and `expected_revision?`. Execution actions also take `request_key`. Payloads are JSON object strings; named fields below are the existing native route contracts. Project name, Timeline, settings, graph, workflow, Story/client identity and prompt ID are resolved by the adapter and cannot be overridden. Host validation remains authoritative. Read [native references](TIMELINE-REFERENCES.md), [audio](TIMELINE-AUDIO.md) and [external Timeline](EXTERNAL-TIMELINE.md) for full nested schemas.

### h3_story

| Action | Arguments |
| --- | --- |
| `write` | `box?`, `rewrite_all?`; uses saved Story provider/idea/template configuration. |
| `rewrite` | `box?`; explicit rewrite request. |
| `feedback` | `edit:{kind:feedback,box,text}` or a bible edit matching the current Story edit contract (see `story_edits.py`); returned data remains a proposal. |
| `check` | `boxes?`; continuity/colour review of rendered clips. |
| `still_prompts` | `instructions?`, `source?` and generator-specific conversion options from the still-prompt preparation contract. Keeps manually edited prompt state. |
| `templates` / `hosts` | No arguments; reads templates or configured host names without retrieving keys. |
| `bible` | `action:build|link|apply|status|recompile`, plus `plan?`, `bible?`, `links?`, `boxes?`, `force?`, `merged?`; or `action:assign` with `box` and `entity` to add one Cast entity to one box as its next `<Subject N>`, returning `prompts`, `casts`, `schedules`, `subject` and `changed`. Returns transformed Timeline data, no save. |
| `taken` | `job:<retained Story handle>`; acknowledges only after a finished proposal is retained locally. Does not apply it. |

Write/rewrite/feedback/check/still_prompts require an executable snapshot, explicit Story node, revision and request key. Poll the returned `job`. Story polls return `result_available` and `data_json` containing the retained result; apply chosen content using `h3_save_project`. A lost start reply uses `current?recover=true` only with matching request attribution; an unrelated current job is never adopted. Story execution omits the browser's save-on-start workflow argument. Writer recovery/check files may be created by the existing host lifecycle; authored Timeline data is unchanged.

### h3_stills

| Action | Arguments |
| --- | --- |
| `sources` | `box`, `target?` (`{kind:first|last|shot,...}`) for eligible saved frame sources. |
| `import` | Adapter-local `path`; original image bytes go to the existing image importer. |
| `pin` | Host `file` descriptor; returns a pinned hash. |
| `prepare` / `generate` | `box`, `target?`, `seed?`, compiled `recipe`, `size?`, `source?`. The host always uses the selected clip prompt; a legacy `prompt` argument does not override it. Reference-generation actions still use their explicit reference prompt. |
| `reference_catalog` | Enumerate Cast/appearance preparation requirements. |
| `reference_prepare` / `reference_generate` | `asset_key`, current catalog `input_fingerprint`, `prompt`, `seed?`, compiled `recipe` and generator options. |
| `reference_approve` | `asset_key`, `candidate_id`, `approval_revision` (the approval record's revision, distinct from project revision). Returns proposed Timeline. |
| `prompt_instructions` | Reads installed generator conversion guidance. |

Prepare returns a prompt/provenance graph and does **not** generate. Generate prepares then persists a receipt before submitting one owned SaveImage closure. Compiled recipe bindings are explicit inputs from the configured native generator; arbitrary browser graphs are not compiled automatically. Use node/schema guidance to inspect available generators. P-H3's Studio 8 MP/4 MP/custom resolution and ordered LoRA stack remain graph configuration; an explicit request size overrides dimensions for that invocation.

Poll still/reference handles through `h3_job_status`. It calls the existing result verifier, preserves collector/request/provenance identity and returns candidates. Retain candidate/source/seed/target records; acceptance requires an explicit project save. `reference_approve` also returns data for deliberate save under the current project revision. A completed image or prepared graph never means an accepted guide. Preserve source clocks, text contracts, manual prompt edits and reference approval state.

### h3_takes

| Action | Arguments |
| --- | --- |
| `list` | Native `box`; managed `box?`. |
| `use` | Native `take` (listed folder), selection fields required by the route; managed `take_id`, `box`, `kind:box|bridge`. |
| `rate` | Native `created` (listed render timestamp), `rating` (0–5), optional `tag` under the existing rating contract. |
| `delete_preview` | `scope:take|other|unusable`, `take?`, `box?`, `bridge?`; forces `apply:false`, returns count/bytes. |
| `delete_apply` | Same reviewed selection; explicitly applies deletion. |

Managed supports list/use through its revision/lease guards. Cleanup/ratings never fall back to a native route. Native actions check the saved revision before dispatch; routes without their own compare-and-save are not cross-request transactions. Existing busy/ownership checks remain in force.

### h3_library

| Action | Arguments / behavior |
| --- | --- |
| `list` / `load` | List saved groups/versions; load uses `id` returned by listing. |
| `rename` | `key`, display `name`; independent of render identity. |
| `delete` | Exact listed `id`; deletes the selected version/group per the existing library identity contract. |
| `checkpoint` | Display `name`; pins current saved UI/media under the native revision. |
| `restore` | Checkpoint `id`; returns a separate editable workflow identity. Register its matching API export before headless execution. |
| `duplicate` | `title?` (1–120 characters), `timeline_json?` (a Timeline object or JSON text this host must accept); needs the target's `story_node` and current revision. Copies the saved story, its renders and takes into a new editable library story (the checkpoint-and-restore copy in one step), starting from `timeline_json` when given — for example the saved Timeline without `requires` entries listed in `unsupported_features`. The source is unchanged. Returns the copy's `target` plus `data_json` with `id`, `graph`, `story`, `timeline_node`, `sequence` and `title`. Register an API export before headless execution. |
| `generation_start` | Starts a fresh independent sequence, preserving previous sequence outputs/history. Explicitly adopt the returned name in the saved workflow. |
| `generation_history` | Playable earlier sequences. |
| `generation_export` | `references?`, `origin?`; exports saved Story/Timeline/settings and verified installation media references. |
| `generation_preflight` | `archive`; verifies available files/hashes before import. |
| `generation_import` | `archive`, stable `request_id`, `renderer?`; creates separate state, never resumes source jobs. Explicitly save the returned authored state. |

These are native workflows; managed targets need deliberate export/fork. Pure saved operations remain available on old projects without execution snapshots. Archives contain references to verified files in the same Studio installation, not embedded videos/model weights. New-project authoring is a document edit: preserve uploads, connected references, idea/guide/provider inputs; clear the chosen Timeline/Story output state explicitly and save, keeping old generated files.

### h3_inspect

`status` returns native status/media descriptors (may materialize previews) or managed project status. `regeneration` takes `box` and resolves its executable snapshot for read-only overlap preflight. `audio` takes `file`. `image_description` uses `action:read|resolve|edit|clear|regenerate|clear_all`, file/source/slot/provider fields from the existing route. `refmods` lists installed entries. `nodes` takes optional `node` class name and returns ComfyUI's schema, including graph-only nodes. No model downloads or key readback are offered.

`prompt_fields` reads a prompt the way the Studio's Sections form does. Pass either `prompt` (any target, no revision) or a saved `box` with optional `layer` id (native target and revision). Optional `tags` (`[{tag:"<Picture 1>",name:"image3"}]`) resolve picture labels as the Studio's picked references do. The result has `structured` (a known section header is present), `sections[].entries[]` with `kind` (`definition`, `retention`, `summary`, `narrative`, `cue`, `dialogue` or `existing`), `shot`, `start`/`end` (Python string offsets into the prompt) and the parsed `value`, plus `summary` counts: `shots`, `cues`, `advanced_cues` (cues behind the form's Advanced switch), `dialogue` and `unstructured_text` (shot text, unknown or duplicate sections and unresolved reference lines that the form can show only as Existing text). Use it to check a prompt before saving it.

## Skills/resources and boundaries

The host `/h3c/agent/catalog` lists all seven canonical `skills/*` packages, complete YAML frontmatter and each contained file's `skill://<name>/<path>`, exact byte size and `sha256:` digest. Reads use the catalog's digest and reject changes; refresh before retrying. `skills/list` and `skills/get` implement `io.modelcontextprotocol/skills` using the released Python SDK's public Extension/MethodBinding API. The SDK owns protocol negotiation/stdio; adapter code does not implement JSON-RPC. Optional directory reads are not advertised. Modern extension behavior and legacy ordinary resources/tools are separately tested.

`h3c://instructions` is the maintained host bundle. Allowlisted `h3c://docs/...` guides and `h3c://examples/...` clients supplement skills. Reading them is ordinary context, not automatic client skill activation. Filesystem installer fallback remains `skills/install.py`; it links canonical files without replacing ordinary user folders.

`h3_capabilities.coverage` classifies the current 17 nodes and feature groups as tools, authored data, graph guidance, browser UI, retired or unavailable. Arbitrary transport paths, global queue mutation, browser synchronization, editor graph compilation, waveform/beat analysis, playback/layout/session Undo and disabled replacement generation are outside the tool surface. Node parameters such as Disk Cache modes and Save Segment codec/colour/guide frames are configured in the captured workflow and explained by the skills/schema.

## Verification evidence

Observed on 2026-11-08, without model turns or live ComfyUI calls:

| Client / path | Verified | Skills activation |
| --- | --- | --- |
| Python MCP SDK 2.3.0 | Real stdio tools/resources, modern Skills list/get/cache fields; legacy guidance path | Extension conformance passes with an extension-aware SDK client. |
| Codex CLI 0.166.0 | Process-local app-server initialized the adapter and listed all 21 tools plus fixture resource | Automatic activation unverified; observed server capabilities were legacy tools/resources, without negotiated Skills. |
| Claude Code 2.1.316 | Isolated configuration registered the stdio launcher; `mcp list` reported Connected and `mcp get` resolved it | Automatic activation unverified; health does not prove resource reading or Skills loading. |
| uv + installed wheel/venv | Both `--check` launchers work from a different cwd with installation paths containing spaces; wheel imports without ComfyUI/torch | Skill source remains the configured host. |

Reproduce with `uv run --project mcp_adapter python tools/mcp_client_smoke.py --clients`.

Adapter tests use an isolated HTTP fixture and real SDK stdio. They cover Skills negotiation and exact resources, revision conflicts, uint64/opaque document preservation, nonblocking crash-released receipt locks, uncertain submission recovery, candidate/Story proposal retention and managed ownership boundaries. No live generation is implied. Installed-client versions and handshake/Skills activation evidence are recorded with the final implementation verification in the [MCP feature ledger](roadmap-discipline/phases/2026-11-08-mcp-tools-skills.md). Tool support and automatic Skills activation are separate acceptance results.
