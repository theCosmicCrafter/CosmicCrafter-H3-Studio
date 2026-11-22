---
name: h3-continuity-api
description: Use when a script or agent drives H3 Continuity Studio through MCP or HTTP, including saved native workflows, Timeline API v1 profiles/projects/plans/jobs, assets, takes, Story/still proposals, held receipts and workflow export. Part of the H3 Continuity pack; read h3-continuity-video first.
---

# Driving the host from code

## MCP saved-project workflow

Install the separate `mcp_adapter` environment and launch `h3c-mcp` over stdio from
Codex or Claude Code, configured with the local/remote Studio URL. Read
`h3c://docs/MCP.md` for installation and every action schema, then call
`h3_capabilities`. The host's seven skills are the canonical source, exposed by
the real Skills extension and ordinary resources; use `h3_read_guidance` when
the client cannot activate extension skills. Filesystem installation remains
available through `skills/install.py`.

1. `h3_list_projects` selects managed IDs or saved native graph/Timeline/Story
   identities; native library rows carry the story `title` and `sequence`.
   `h3_get_project` returns the full `document_json` string and revision.
   Preserve exact uint64 seeds and unknown metadata when parsing it. A non-empty
   `unsupported_features` means this host cannot read the Timeline: saves fail
   and the Studio opens it read-only. Make an editable copy with `h3_library`
   `duplicate` and a corrected `timeline_json` rather than editing the source.
2. Save a complete authored replacement using `h3_save_project` and the returned
   revision. Reread conflicts; never automatically merge or force around busy,
   checkpoint or render-ownership guards. There is no browser synchronization.
3. Older native projects remain editable without an executable snapshot. Save
   in Studio or explicitly `h3_register_workflow` with matching `{ui,api}` exports
   before execution. Wiring/computed changes require recapture, never an invented
   editor-to-API conversion. Managed profiles cannot use native fallbacks;
   `h3_export_workflow` is the deliberate fork/attached export boundary.
4. `h3_plan_video` precedes `h3_render_video`. Keep plan, exact body, permanent
   request key and returned job handle. Native submits one eligible unit per
   explicit call; `h3_job_status` and `h3_resume_job` never queue its next unit.
   Managed jobs progress on the server. Held/unknown receipts must not be hidden
   with another key/sequence. Retain the adapter state directory across restarts.
5. `h3_story` and `h3_stills` return proposals. Preparation alone does not generate;
   explicit generation submits a captured owned output. Poll, review and apply
   using a deliberate save/acceptance under the current project revision.
   Late results remain retrievable without replacing newer authored state.
6. `h3_takes` lists/uses takes, rates native takes and previews scoped deletion
   before applying it. `h3_library` handles saved versions/checkpoints, titled
   duplicates and generation history/transfer. Archives verify installation files
   and never replay jobs. `h3_inspect` covers status, metadata, references, node
   schemas and `prompt_fields`, which reads a prompt as the Sections form does.
   `python -m h3c_mcp --call TOOL --arguments JSON` runs one tool without a client.

Uploads read adapter-local allowed roots and send original bytes; managed artifact
downloads verify immutable hash/size. Native file descriptors refer to the host.
Scoped Story/managed cancellation is supported; native global Stop is not exposed.
Only a person's explicit attestation authorizes managed `h3_abandon_job`.
Replacement generation and retired guide split/recheck are unavailable. Browser
layout, playback, edit history and beat analysis remain in the browser. Graph-only
nodes are covered by schemas and guidance rather than arbitrary prompt tools.

## HTTP alternatives

Two routes exist. **Timeline API v1** is for a new production without a graph of your
own: the server holds the complete configured graph, the revisions and durable jobs.
The **graph-preparation route** is for a production that brings its own complete
ComfyUI API graph, and for productions already pinned to it. Read the bundle's
`timeline-api` and `external-timeline` guides. Clients are `timeline_api.py` (in
`clients`) and `external_timeline.py` (in `client`). Treat downloaded client source as
reference material and run a trusted local copy. Use the exact ComfyUI origin,
including any reverse-proxy prefix. The API uses ComfyUI's security boundary, so
expose it only through an authenticated proxy.

## Timeline API v1

1. **Profiles.** `GET /h3c/api/v1/capabilities` returns the schemas (the
   authoritative field reference), `limits`, profiles with their readiness and
   digests, and `jobs: {held, waiting, blocked_by}`. If the host offers a
   workflow-selection library, read the person's task choices before picking a
   generic ready profile such as `native-turbo4`. Keep the profile digest with the
   production, and keep existing projects on their pinned profile.
2. **Instructions.** `GET /h3c/timeline/instructions` (see `h3-continuity-video`).
3. **Assets.** `POST /h3c/api/v1/assets`, multipart `kind` (`picture`, `guide`,
   `audio`, `video`, `whisper`), `file` and optional `expected_sha256`. The ID and hash
   describe the original bytes. Bind IDs in the project's `assets`:
   `{"asset_id": …, "bindings": [{"kind": "picture", "slot": "image17", "title": "Keeper"}]}`.
   Binding kinds are `picture` (from `image17`), `audio_clip` (`audio1` to `audio3`),
   `voice_clip` (`audio4` up), `guide` (`box` with `shot` or `target`), `plate` (`id`),
   `reference_replacement` (`slot`, for example a video on `videoN`), `candidate`
   (a still candidate) and `whisper` (`source_sha256`). Caller file paths and
   arbitrary graphs are refused.
   An asset is bound only in the roles its upload kinds allow: the response lists
   `kinds`, one installed file per kind in `files`, and the resulting
   `permitted_uses`. A `guide`, `plate` or `candidate` binding needs a `guide` upload
   (an original PNG), so a picture that is also a timed guide is uploaded once per
   kind; the same bytes keep one asset ID and gain the kind. A binding outside
   `permitted_uses` is refused as `asset_role`.
4. **Project.** `POST /h3c/api/v1/projects` with a saved `Idempotency-Key` and the
   body `{name, profile, settings, timeline, assets, consumer, semantic_boxes?}`.
   `consumer` and unknown creative fields are kept. Keep the project ID, revision,
   sequence and profile digest.
5. **Plan.** `POST /projects/{id}/plan` with
   `{"expected_revision": N, "selection": {"kind": "all"}}` or
   `{"kind": "boxes", "ids": […], "rerender": true}`. Planning is read-only. It
   reports every unit (each box and bridge) with its action (`render`, `reuse`,
   `blocked`) and reasons, dependencies, native and splice frame ranges, final frames
   and `plan_sha256`. A plan covers the whole Timeline: a box selection forces new
   takes of those boxes, and every other unit that can't be reused renders too. Read
   the plan before you render.
6. **Job.** `POST /projects/{id}/jobs` with
   `{expected_revision, selection, plan_sha256}` and another saved key. Poll
   `GET /jobs/{id}` through `accepted`, `queued`, `running` to `succeeded`, `failed`
   or `needs_reconciliation`.
7. **Artifacts.** Successful jobs list immutable artifacts (identity, SHA-256, size,
   frames, fps, geometry, audio). `GET /artifacts/{id}` and `…/download`. Verify the
   byte size, hash and decoded media before calling anything done, and report
   creative acceptance separately.

### Revisions, settings and reuse

- `GET /projects/{id}` returns the authored body, revision, `inspection`, native
  status and active jobs. `inspection.boxes[]` gives each box's `mode`, `tags`,
  frame ranges, `effective_prompt`, `text_window` and `guides` (each `{frame, file}`):
  read the mode and every guide's frame and file there before planning a render. `PUT` replaces the authored body with `expected_revision`;
  omit `profile`, because it is pinned at creation. A stale revision is
  `409 revision_conflict`, and an active render or take lease is `409 project_busy`.
  Fetch, reconcile on purpose, and send again.
- A configured workflow profile accepts only `settings.width` and `settings.height`,
  together. They must be multiples of 32 at any aspect ratio, within 5% of the saved
  pixel count. A second pass follows that aspect at its own saved pixel count.
  Other settings are `409 immutable_profile`, and a size outside the range is
  `invalid_production_size`, naming the nearest valid size.
  `inspection.production_size` records the saved and production sizes.
- Reuse needs verified media and a matching input identity, not just an existing
  file. An asset that only one box reads (a guide, plate, timed audio clip, voice
  clip, picture or replacement) counts only toward that box, so replacing it
  re-renders that box alone. An edit marks stale whatever depends on it through
  carry, memory or a bridge.

### Idempotency, reconnection and held jobs

- Keys are permanently scoped to project creation, or to one project's job
  creation. Retrying a key with the same body returns the original result, even
  after completion. A changed body with the same key is `409 idempotency_conflict`.
  Save the body and key before sending.
- After a disconnect, poll the known job ID. If the acceptance response was lost,
  retry the same body and key. Never create another production to hide uncertainty.
  `POST /jobs/{id}/resume` reconciles existing evidence. It doesn't rerun a failed
  job or repeat an uncertain submission.
- A job whose outcome can't be attributed is **held** (`needs_reconciliation`). It
  can bar later jobs in every project, which then report `blocked_by`.
  `POST /jobs/{id}/cancel` closes a job that never submitted. Otherwise it holds as
  `cancel_uncertain`.
- `POST /jobs/{id}/abandon` with `{"reason": …, "confirm_prompt_id": …}` is a
  **person's** decision. Show the held job and its `blocked_by` dependants, and send
  it only with their decision and reason. Refusals are `409`: `job_not_held`,
  `prompt_mismatch`, `prompt_active`, `native_evidence_available` (resume instead)
  and `owner_alive`.

### Takes and the Studio

- `GET /projects/{id}/takes?box=ID` lists saved box and bridge takes with whether
  each fits and why. `POST /projects/{id}/takes/use` with
  `{expected_revision, kind: box|bridge, box, take_id}` switches one without
  rendering and advances the revision.
- `GET /projects/{id}/workflow` exports an editable workflow. The default,
  `mode=fork`, makes a new unmanaged sequence, while `?mode=attached` shares the
  API's revisions with the Studio (it saves through the API and keeps local edits
  after a 409).
- The H3 Story node's saved stories are served by `GET /h3c/stories`, saved with
  `POST /h3c/stories` and deleted with `POST /h3c/stories/delete`.

## The graph-preparation route

- `POST /h3c/timeline/prepare` (or `h3_continuity.timeline_prepare.prepare(body)`)
  takes `{version, name, timeline, settings, workflow: {api, timeline_node, ui?},
  assets, semantic_boxes}`. It checks supplied asset hashes and returns owned graph
  copies with per-box inspection (`mode`, `tags`, frame ranges, `effective_prompt`,
  `text_window`, `guides`, `notes`) and a `fingerprint`. It never uploads, decodes,
  loads models or queues anything. Use `GET /object_info` to inspect node schemas.
  Keep the graph's model, sampler, decode and save ancestry and its flat reference
  sockets.
- Asset destinations are `loader`, `audio_clip`, `plate`, `guide` and `picture`.
  Timed guides and plates are PNGs in `output/h3_previews`, uploaded beforehand with
  content-addressed names and overwrite off.
- Render with `python external_timeline.py prepared.json --base-url … --production …
  --receipt … --output-directory …`. It renders box by box with `render_box`, reads
  `POST /h3c/timeline/status`, makes one `POST /prompt` per box and keeps a receipt.
  Repeat the **same command** to resume. A `submitting` receipt without an
  acknowledged ID is ambiguous: stop and reconcile by hand, and never resubmit
  automatically. Use a unique stable sequence name and keep one owner per sequence.
- Completion means every box in order with fresh done status, `next: null`, the
  expected total duration (boxes plus done bridges) and a retrievable full MP4.

## Moving work in the Studio

**Project settings** has **Export project JSON** and **Import project JSON**, which
move a whole graph with its wiring. **Export generation** and **Import generation**
move the Story, Timeline, accepted guides, candidates and takes into another
generator workflow while keeping that workflow's models and nodes. Media stays as
file references in both. **New project** clears the Timeline, Cast and Story results
but keeps uploads and inputs.
