# Studio capability coverage for MCP

Source baseline: `main` at `b5b734e` (v0.19.5), inspected 2026-11-08.
Roadmap: [MCP0](../roadmap-discipline/phases/2026-11-08-mcp-tools-skills.md).
Status: source audit complete; standalone adapter and [design](../superpowers/specs/2026-11-08-mcp-tools-skills-design.md) approved by the user. The [implementation plan](../superpowers/plans/2026-11-08-mcp-tools-skills.md) includes required README/docs installation instructions and awaits execution-method selection.

## Intent and method

Reuse the seven existing `skills/*/SKILL.md` files as the maintained authoring guidance, distribute them through the official MCP Skills extension, and expose executable Studio operations as MCP tools. Compare source, current controls, route registration, registered nodes, tests and the guide in both directions: missing current functionality and advertised obsolete functionality.

This inventory groups user capabilities, rather than turning every button or helper into a tool. A skill explains how to perform a task; an executable tool needs an implemented callable operation. Browser-only controls and graph configuration have explicit treatment below. Nothing here claims that MCP tools already exist.

Skill abbreviations: V = video entry; J = joins; T = timing; R = references; S = sound; W = story; A = API. Every abbreviation refers to `skills/h3-continuity-<name>/SKILL.md`.

## Guidance requiring correction

| Finding | Existing claim | Current source evidence | Required correction |
| --- | --- | --- | --- |
| Assembly geometry | V:86–88 says different aspects are unsupported and assembly uses the largest clip size. | `h3_continuity/media.py:201–218`; `tests/python/test_durable_renders.py:157–178`. | Explain smallest clip dimensions by pixel count, resize across differing aspects, unchanged duration, highest rate and mixed HDR handling. |
| Cached FLF2VA audio | R:138–141 requires no audio or video. | `h3_continuity/timeline.py:1000–1023`; `tests/test_flf2va_audio.py:21–56`. | Raw audio is permitted in cached FLF2VA with an audio VAE; raw video still requires REF2VA. Clarify the exception to the initial mode summary too. |
| Shot splitting | J frontmatter says splitting at a guide, while its body correctly describes timed Shot splits. | `skills/h3-continuity-joins/SKILL.md:3,135–146`; `web/h3c_timeline_editor.mjs:1940`; `CHANGELOG.md:258–260`. | Remove the obsolete guide-split description; preserve Split before Shot N and existing saved joins. |
| Bible use | W:65–66 says rendering never reads the bible. | `h3_continuity/timeline.py:553–561,915–920`; `cast_memory.py:29–47`; `reference_assets.py:388–400`. | Distinguish authored prompt text from render-time Cast memory and approved-reference instructions derived from the bible. |

These claims have been identified, not edited yet. The existing packaging tests verify exact delivery of skill bodies, not their semantic completeness.

## Current capability matrix

“Tools + skill” means callable operations with workflow guidance. “Data edits + skill” means authoring through a revision-checked Timeline/project operation, rather than one tool per field. Native operations are not automatically valid for managed projects; see ownership boundaries below.

| Capability | Current implementation / callable surface | Existing coverage | Proposed exposure |
| --- | --- | --- | --- |
| Host instructions, schemas, limits and profile readiness | `timeline_prepare.py:27–67`; `timeline_api/service.py:87`; GET instructions and capabilities. | V/A substantial. | Resources for maintained guidance and skills; tools for host readiness and capabilities. Preserve host/version identity. |
| Project discovery, create, read, replace, inspect effective prompts | `timeline_api/routes.py:49–174`; `service.py:129–174`. | A substantial; listing needs explicit guidance. | Tools + A; retain revisions, profile pins and unknown authored fields. |
| Clip creation/removal/reordering/duplication, seed, prompt sections, exact length, joins | `web/h3c_timeline_model.mjs:449–514,727`; `web/h3c_timeline_editor.mjs:378,408`. | V/J/T/R cover semantics. | Data edits + skills. Duplication needs fresh identity/seed and correct bound-audio semantics. |
| Timed Shot split | `web/h3c_shot_split.mjs`; editor:1940. | J body covered, description stale. | Shared domain transformation or documented authored-data operation; no guide-split tool. |
| Visual memory, selected moments, Cast pins | `timeline.py:553`; `web/h3c_cast.mjs:889`; `web/h3c_studio.mjs:1554`. | J/W covered. | Data edits + skills; verify source take/frame and dependencies. |
| Insertion bridges | `web/h3c_bridges.mjs:158–176`; managed plan/jobs. | J covered. | Data edits and render tools + J; preserve added-time semantics. |
| Long boxes, Context Windows, continuing-chain merge/refinement, anti-burn controls | `windows.py`; `long_merge.py`; `web/h3c_chain_settings.mjs:32–83`; registered nodes. | J/T/R largely covered. | Skills for graph/configuration; data edits/render tools where supported. Do not imply arbitrary pinned-profile mutation. |
| Plan, submit, inspect, cancel, reconcile renders; artifacts | `timeline_api/routes.py:127–164`; `service.py:160–197`; jobs/planner. | A substantial. | Tools + A; short calls return durable IDs, no duplicate submissions after lost replies. Human-attested abandonment retains its existing contract. |
| Native queue feeding and selected/multiple takes | `web/h3c_timeline_editor.mjs:276,939,1295`; `web/h3c_timeline.js:1319`. | V partial. | Explain native browser queue feed versus durable managed jobs. Project cancel must not become global queue clearing. |
| Incompatible continuity regeneration / rebuild receipt | `regeneration.py:85,157`; managed `contracts.py:212–215`, `planning.py:197–205`. | Missing. | Tools + A/V/J; read-only preflight and explicit recovery selection, preserving dependent takes. |
| Takes listing/use/compatibility | `timeline_api/service.py:199,233`; native `takes.py:317,344,364`. | V/A covered. | Tools + A/V, respect ownership and current revision. |
| Takes ratings/tags and scoped deletion | `routes.py:145–165`; `takes.py:490,503`. Native only. | Ratings/tags and cleanup scopes missing. | Tools + skill; deletion preview/counts before application. Managed ownership needs an explicit implementation decision. |
| Full video, video so far, source-backed partial preview, build progress/errors | `timeline_node.py:163–306`; `web/h3c_partial_video.mjs:1–25`; media assembly. | V outdated and incomplete. | Status/media tools + V; distinguish preview type and availability. Playback/scrubbing need no separate tool. |
| New project and whole workflow import/export | `web/h3c_timeline.js:367–424`; `web/h3c_story_archive.mjs:16–54`; managed workflow export. | A partial. | Transfer tools + A; distinguish a supplied/exported graph from the currently open browser graph. |
| New generation, generation history | `generations.py:20,41`; `web/h3c_generations.mjs:2–28`. | Missing. | Tools + A/V; fresh independent unrendered sequence, earlier outputs retained. |
| Generation preflight/export/import/fork | `generations.py:133,169,230`; `web/h3c_generation_archive.mjs:8–31`. | A mentions transfer, lacks preflight/local media/receipt details. | Tools + A; verified same-installation transfer, no implied portable embedded media or replayed jobs. |
| Saved story groups, versions, naming and deletion | `story_library.py:106,143,203,313`; routes:443–450; `web/h3c_story_library.mjs:110–162`. | W/A partial. | Tools + W/A; distinguish display name from render identity and version versus whole-group deletion. |
| Named checkpoints and editable restore | `story_library.py:32,37`; `story_checkpoints.py:119,190,206`; routes:447–448. | Missing. | Tools + W/A; preserve media, create an independent editable restoration. |
| Autosave, saved-state revisions and conflicts | `routes.py:32–126`; `web/h3c_saved_state.mjs:8–20,100–116`. | Missing. | Skill guidance for preference and explicit saves; tools for supported stored-state operations. Client preference control is a separate decision. |
| General Undo/Redo and 100-edit history | `web/h3c_history.mjs:31–112`. | Only Cast/last-Write undo described. | Skill-only boundary initially: browser session history is not server revision history. Do not promise remote undo of an open tab. |
| Pictures, wired references, enable/replace, RefMods and appearance plates | `web/h3c_pictures.mjs:222–247`; model:740,887–917; native reference endpoints. | R substantial. | Data edits/assets/reference tools + R. Respect source kind and immutable upload identity. |
| Image descriptions and Cast reference preparation/approval | `image_descriptions.py:164`; `reference_assets.py:107,224,350`; `/reference-assets/*`. | W/R partial. | Tools + W/R; separate preparation, generated candidates and explicit acceptance. |
| First/Last/Shot/interior guide import, placement, source frame, anchor and candidate acceptance | `routes.py:177–253`; `stills.py:306,511,566`; `web/h3c_frame_images.mjs:66–103,309–347`. | R substantial, target/source controls incomplete. | Tools/data edits + R; accepted guide has priority, assigned reference remains distinct from unaccepted candidate. |
| Still Recipe preparation, native submission and result recovery | `/stills/prepare`, `/result`; `web/h3c_image_jobs.mjs:9–45`; ComfyUI `/prompt`. | R conceptual, submission receipts/recovery missing. | Tools + R/A. Preparing a graph is not rendering; persist submission evidence and recover result without duplicate work. |
| Prepared still prompts, manual apply/staleness and generator-specific instructions | `/still-prompts/prepare`, `/instructions`; `web/h3c_still_prompt_preparation.mjs:25–56`. | R partial. | Tools + R/W, preserve manual edits and target/recipe identity. |
| P-H3 still generator, size helper, 8 MP/4 MP/custom and ordered LoRA stack | `ph3_image_nodes.py:96,125,167–222`; guide/build/p-h3-image-stills.md:37–51. | Missing. | Skills for graph/profile configuration and supported still-request options; validate available model/recipe rather than inventing graph mutation. |
| Audio lanes, original soundtrack, voice clips and timed text | `audio_tracks.py`; `timed_text.py`; `web/h3c_audio_lanes.mjs`; `/audio/info`. | S substantial for older movie-clock contract. | Data edits/asset tools + S; preserve source clocks, exact words and audio-VAE requirements. |
| Recording locks, box-owned audio windows, dialogue cues/mode | `audio_windows.py:15–98`; `dialogue.py:39,225,309,329`; `timeline_api/contracts.py:149,160–189`. | Missing. | Data edits + S/A; explain discontinuous box windows, ownership and source edits before exposing mutation. |
| Beat analysis, waveform and snap | `web/h3c_audio_lanes.mjs:47–61,130–148`; `web/h3c_waveform.mjs:7–33`. | Missing. | Document browser-only analysis/preferences. A future server analysis tool requires implementing it; frame authoring remains available today. |
| Story writing/selection/rewrite/feedback, templates, bible/Cast and continuity checks | `/h3c/story/*`, `/timeline/bible`; `story_job.py:406–542`; `story_bible.py:573–594`. | W substantial; bible claim needs correction. | Tools + W with separate job lifecycle and supplied graph/current-state requirements. |
| Writer endpoints/models/keys; queue/render settings | `web/h3c_story_panel.mjs:145–169`; `routes.py:298–361`; `web/h3c_timeline.js:1319`. | V/W partial. | Skills and explicit configuration tools where supported; retain server-side credential storage. |
| Disk Cache, Save Segment codec/colour/first-pass guide frames | `disk_cache.py:397–476`; `nodes.py:277–313,392`; guide/output/first-pass-cache.md. | Missing. | Graph-configuration skills initially; existing workflow execution handles it. Preserve CPU-only verification limits for Disk Cache. |
| Legacy/graph-only node workflows | All 17 classes in `extension.py:5–18`, including Sequence, Continue, Save Segment, Story Turn, Still Conditioning/Image Source and Timeline Image. | Scattered/partial; T covers Context Windows/Join Chain. | Add discoverable graph-node guidance/schema access; no separate imperative tool needed for every registered node. |
| Panel layout, zoom, selection, player position and enlarged previews | `web/h3c_studio.mjs:349–353,507–547,779–825`. | Primarily human guide. | Document UI boundary. Persistent pin/take/reference decisions are domain edits; viewing them is presentation. |

## Removed, unavailable and compatibility-only behavior

- Replacement bridges are disabled by `replacement.UNAVAILABLE` (`replacement.py:15–17`); creation/content controls are hidden (`web/h3c_bridges.mjs:347–371,471`). Do not advertise candidate generation/playback. Old records may be inspected/removed. Insertion bridges remain available.
- Split at guide is removed. Timed Shot-boundary splitting remains available.
- Story `writing_mode` is a retired compatibility input; current Write uses Fast (`story_node.py:69–72`). `check_only` Guide Recheck is refused (`story_job.py:419–420`).
- `SHA256SUMS.json` was removed and is not referenced by skills. Recent responsiveness, cache-tag and thumbnail fixes change behavior without requiring additional MCP operations.

## Ownership and state boundaries

1. Managed projects pin configured profiles and allocate `api_<uuid>` sequences. Existing APIs cannot adopt an arbitrary native sequence, discover every open browser graph, or change a project's pinned graph/profile (`service.py:129–161`; `profiles.py:244–247,359–411`).
2. Native Story/still calls need supplied graph and node identities plus authored state. They do not read the graph in a browser tab automatically. Saved Story discovery is not a complete native Timeline registry.
3. Native endpoints are not universal fallbacks for managed projects. Managed ownership guards reject native take mutations and media materialization without the appropriate owner. Managed status reads use `materialize=False` (`service.py:43–78`; `planning.py:37–42`; `timeline_node.py:410–424`).
4. Managed API lacks take deletion/rating, first-class Story/still job and checkpoint lifecycle operations. Supporting those for managed projects needs an explicit safe route, not bypassing guards.
5. Native status can rebuild previews; it is not an entirely passive read. Media/status tool descriptions must represent this accurately.
6. Generation archives reference verified local installation files. Browser edit history, waveform/beat caches, selection and user preferences are separate from durable server records.

## Saved-project editing decision

The user explicitly confirmed that live synchronization is **not required**. Agents may work on the same saved project as a person. Saving an older browser state over newer agent work is an accepted overwrite scenario; optional safeguards may reduce that risk. Do not require a browser bridge, realtime updates, collaborative editing, automatic merging or browser presence for agent work.

Existing persistence is already suitable for a saved-state contract:

- Managed projects use an expected revision on replacement (`timeline_api/service.py:153` and `records.py`), with existing busy/render ownership checks.
- Native Timeline/Story widget snapshots are saved under graph identity by `/h3c/state`. Its HTTP save requires an integer revision and returns 409 on mismatch (`routes.py:103–127`; `saved_state.py:35–71`). It is a widget-value snapshot, not an arbitrary full workflow graph.
- Saved stories retain the workflow graph; loading overlays the latest widget snapshot (`story_library.py:106–130,143–157`). Workflow-wiring revisions and immutable named checkpoints have existing guards.

Proposed safeguard: preserve these existing revision/conflict responses and let the caller reread/retry deliberately. Do not silently merge a stale document or disable current render leases. No new collaboration subsystem or blanket force-save mechanism is needed. Stores/routes without revision checks must describe their overwrite behavior accurately.

Unsaved browser edits are outside the agent's view. Agent tools must identify the saved project/graph explicitly, return the resulting revision where supported, and avoid claiming that an open tab has updated. New server access for saved native workflows remains in scope where needed; no browser synchronization is implied by it.

## MCP Skills extension research

The official extension is `io.modelcontextprotocol/skills`. It serves skill metadata/manifests with `skills/list` and `skills/get`; skill files are read through ordinary resources, conventionally `skill://<name>/SKILL.md`. Publish actual files and their byte sizes/digests, not duplicated rewritten bodies. Supporting guidance outside each skill directory also needs an explicit resource location. Reading a resource alone does not activate a host skill.

The current specification targets MCP revision 2026-07-28 or later; the extension repository labels its lifecycle Beta even though SEP-2640 is Final. Verify the selected SDK and client versions, and retain ordinary resource/local-pack access for clients without extension support. Optional directory reads are unnecessary for the current one-file-per-skill pack unless supporting files are added.

Sources inspected on 2026-11-08:

- [Official extension overview](https://skills.extensions.modelcontextprotocol.io/)
- [Current beta specification](https://github.com/modelcontextprotocol/ext-skills/blob/main/specification/beta/skills.mdx)
- [Extension repository and lifecycle](https://github.com/modelcontextprotocol/ext-skills)
- [Client support matrix](https://modelcontextprotocol.io/extensions/client-matrix) (community-maintained; not an end-to-end compatibility test)
- [Official Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [Python SDK Skills extension documentation](https://py.sdk.modelcontextprotocol.io/advanced/skills/) (documents helpers present on upstream main; actual published-package verification below supersedes the assumed release availability)

Planning verified the actual `mcp==2.3.0` wheel and sdist from PyPI: neither contains the documented Skills helper modules. The release does expose public `Extension`/`MethodBinding` registration. The plan pins that release and supplies the two spec-shaped Skills methods through its supported extension interface; the SDK still owns wire/version/capability handling. No unreleased Git dependency or custom JSON-RPC server is needed. This is a corrected implementation assumption, not a reduction in requested Skills extension support.

## Selected connection approach

First clients confirmed by the user: **Codex and Claude Code**. Their official MCP documentation supports local stdio processes and remote HTTP connections: [Codex](https://learn.chatgpt.com/docs/extend/mcp?surface=cli), [Claude Code](https://code.claude.com/docs/en/mcp). These pages establish transport support, not verified support for `io.modelcontextprotocol/skills`; the extension needs its own compatibility check.

The user selected a local stdio adapter with a configured Studio HTTP base URL, which may point to the same computer or another reachable host. Preserve the skill installer as an available delivery path while verifying extension loading in each client. The embedded endpoint was considered and not selected.

Both approaches should share the same capability mapping, underlying Studio operations and skill sources.

- A small standalone MCP adapter calls Studio's existing HTTP API. An agent can launch it locally using stdio, while Studio stays on its existing host. This isolates MCP dependencies from ComfyUI. A remote URL deployment needs an HTTP transport and its own lifecycle/access boundary.
- An MCP endpoint inside ComfyUI offers one Studio address and lifecycle. It requires integrating the selected MCP SDK/transport with the existing aiohttp host and keeping dependency compatibility with ComfyUI.

Codex and Claude Code launch the adapter locally; Studio may run locally or remotely. Saved-project editing without browser synchronization is confirmed. New design research identifies the need to persist native execution snapshots: current Story saves send a captured API prompt but save only the editor workflow. A stored execution snapshot permits later agent execution without an open browser; old saved workflows remain editable and report missing-snapshot readiness for execution.

## Verification and next action

- Read-only server and Studio inventories independently inspected source, tests and current skill coverage. Parent verified the key contradictory claims in source. No worker changed files.
- `python_embeded/python.exe -m unittest discover -s tests -t . -p test_skill_pack.py -v`: **4 passed**.
- With `COMFY_ROOT` set to the installed ComfyUI path, the same discovery command with `-p test_flf2va_audio.py -v`: **4 passed**, including raw-audio FLF2VA and raw-video REF2VA cases. The initial attempt stopped at bootstrap because COMFY_ROOT was missing; the corrected run passed.
- No full suite, live API calls, browser interaction, model loading or generation was needed for this source audit. Mixed-format assertions were inspected, not rerun.

Next: obtain implementation-plan review and the Native versus subagent-driven execution choice, then execute the approved scope. Design approval is already granted and must not be requested again. The plan reconciles the four stale claims, missing guidance and executable coverage, Skills extension contracts, ownership/revision/idempotency behavior, and the maintained capability map.
