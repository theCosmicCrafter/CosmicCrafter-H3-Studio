# Timeline HTTP API

For Codex or Claude Code, the [standalone MCP adapter](mcp.md) exposes these managed operations and saved native Story/still workflows through typed tools and the existing skill pack. Direct HTTP clients remain supported.

A script or agent can author and render a native Timeline over **HTTP alone**. The server supplies the complete configured ComfyUI graph, manages revisions and queues native H3 work; the caller owns prompts, references, timing and creative review. Use the serving ComfyUI origin, including any reverse-proxy prefix. The API uses ComfyUI's existing security boundary, so expose it only through your authenticated proxy.

!!! info "Reference"
    This page is an overview. The complete contract is in the repository's [Timeline API](https://github.com/KadoBOT/ComfyUI-H3-Continuity-Studio/blob/main/docs/TIMELINE-API.md) and [External Timeline](https://github.com/KadoBOT/ComfyUI-H3-Continuity-Studio/blob/main/docs/EXTERNAL-TIMELINE.md) notes, and `GET /h3c/timeline/instructions` serves a self-contained bundle of the guides and client.

## The flow

1. **Capabilities.** `GET /h3c/api/v1/capabilities` returns schemas, limits and profile readiness. Keep the reported **profile digest** with your production. The `native-turbo4` profile contains the complete native four-step graph and its exact configured models.
2. **Instructions.** `GET /h3c/timeline/instructions` returns the `timeline-api`, prompt, text, audio and transition guides and the stdlib client.
3. **Upload assets.** `POST /h3c/api/v1/assets` (multipart `kind`, `file`, optional `expected_sha256`; kinds `picture`, `guide`, `audio`, `whisper`) returns an ID and hash for the original bytes.
4. **Create a project.** `POST /h3c/api/v1/projects` with a saved `Idempotency-Key` and the authored body.
5. **Plan.** `POST /projects/{id}/plan` is read-only: it reports dependencies, reuse, native frame ranges, final frames and a `plan_sha256`.
6. **Render.** `POST /projects/{id}/jobs` with the plan hash and another saved `Idempotency-Key`.
7. **Poll and download.** `GET /jobs/{id}` until `succeeded`, then download the immutable artifacts and verify byte size, SHA-256 and decoded media. Report creative acceptance separately from technical completion.

An example body (no execution selectors or graph):

```json
{
  "name": "Harbour study",
  "profile": "native-turbo4",
  "settings": {"width": 768, "height": 448, "context_frames": 90,
               "carry_audio": true, "ref_image_size": "match"},
  "timeline": {
    "version": 1,
    "boxes": [
      {"id": "opening", "frames": 90, "seed": 41,
       "prompt": "A keeper watches a quiet harbour in pale dawn light."},
      {"id": "crossing", "frames": 68, "seed": 42,
       "prompt": "The camera follows a small boat across the harbour."},
      {"id": "roof", "frames": 90, "cut": true, "seed": 43,
       "prompt": "A new wide view reveals the harbour from the roof."}
    ],
    "bridges": [{"before": "roof", "frames": 29, "seed": 44,
                 "prompt": "The camera rises smoothly to the roof view."}]
  },
  "assets": [],
  "consumer": {"production_id": "my-study"}
}
```

The three clips and the 29-frame bridge splice to exactly 277 frames. Native output is 24 fps, geometry is a multiple of 32, `context_frames` is 22, 39, 90 or 141, bridge lengths are 12, 29 or 46 frames, and at most nine reference pictures and three reference audios apply to a clip.

## Revisions, plans and idempotency

- `GET /projects/{id}` returns the authored fields, current revision, normalised inspection and read-only native status. The status lists each dialogue cue's place on the Timeline's clock (`dialogue.cues`, without bridge time) and `timing_conflicts`, the messages for a [locked recording](../sound/dialogue.md#lock-a-recording) that a bridge or setting would move; they warn, and do not block a plan. `PUT` replaces the authored body with `expected_revision`; a stale revision is `409 revision_conflict`, and an active render or take lease is `409 project_busy`.
- Keys are permanently scoped to project creation or that project's job creation. Retrying a key with the same request returns the original accepted result, even after the job completes. A changed body with the same key is `409 idempotency_conflict`.
- Jobs advance through `accepted`, `queued`, `running`, `succeeded`, `failed` or `needs_reconciliation`. After a disconnect, poll the known job ID; if the acceptance response was lost, retry the **same body and key**. Never create another production to hide uncertainty.
- `POST /jobs/{id}/resume` reconciles existing evidence. It does not rerun a failed job or repeat an uncertain native submission.

## Held jobs, cancel and abandon

A job whose outcome can't be attributed is **held** (`needs_reconciliation`). Because its prompt might still be running on the one GPU, a held job can bar admission of later jobs in every project; waiting jobs then report `blocked_by`, and `GET /capabilities` reports `jobs: {held, waiting, blocked_by}`. The barrier lifts, without changing the held job, only when its prompt provably can't be running.

| Endpoint | Purpose |
| --- | --- |
| `POST /jobs/{id}/cancel` | Request cancellation. A job that never submitted closes at once as `failed`/`cancelled`, even behind a held job. If it can't be proven safe, the job holds as `cancel_uncertain`. |
| `POST /jobs/{id}/abandon` | **Human-attested** close for a held job whose outcome can't be attributed. Body: `{"reason": "...", "confirm_prompt_id": "<held attempt prompt_id>"}`. |

!!! danger "Automated clients must not abandon on their own"
    Surface the held job (and any `blocked_by` dependants) and send `abandon` only with a person's decision and reason. Refusals are `409`: `job_not_held`, `prompt_mismatch`, `prompt_active`, `native_evidence_available` (resume instead) or `owner_alive`.

## Artifacts, takes and the Studio

Successful jobs expose immutable artifacts (ID, identity, SHA-256, size, frames, fps, geometry). `GET /artifacts/{id}` reads metadata and `…/download` the bytes; old bytes stay identical after re-renders and take switches. `GET /projects/{id}/takes` lists saved takes and `POST /projects/{id}/takes/use` switches one under the revision guard.

`GET /projects/{id}/workflow` exports an editable workflow, defaulting to `mode=fork` (a new unmanaged sequence). `?mode=attached` shares API revisions with the Studio so it saves through the API, preserves local edits after a 409 and follows existing jobs. While attached, the Studio hides ComfyUI's global queue-clearing Stop control.

## Python and command line

The stdlib client `timeline_api.py` is in `examples/` and in the instruction bundle.

```python
from pathlib import Path
from timeline_api import Client

client = Client("http://127.0.0.1:8188")
project = client.create(body, saved_project_key)
selection = {"kind": "all"}
plan = client.plan(project["id"], {"expected_revision": project["revision"], "selection": selection})
accepted = client.render(project["id"], {"expected_revision": project["revision"],
    "selection": selection, "plan_sha256": plan["plan_sha256"]}, saved_render_key)
job = client.wait(accepted["id"], deadline=3600)
film = next(a for a in job["artifacts"] if a["kind"] == "full_video")
client.download(film, Path("film.mp4"))
```

```text
python timeline_api.py --base-url http://localhost:8188 capabilities
python timeline_api.py --base-url http://localhost:8188 create --body project.json --receipt create-receipt.json
python timeline_api.py --base-url http://localhost:8188 plan --project ID --body selection.json --destination plan.json
python timeline_api.py --base-url http://localhost:8188 render --project ID --body render.json --receipt render-receipt.json --wait
python timeline_api.py --base-url http://localhost:8188 status --job JOB_ID
python timeline_api.py --base-url http://localhost:8188 cancel --job JOB_ID
python timeline_api.py --base-url http://localhost:8188 export --project ID --mode attached --destination workflow.json
```

`Client.wait` stops at its deadline; when the job waits behind a held job, the error names it and carries `code="blocked"`. CLI receipts store the request and key before the POST and accepted IDs before polling, so repeating the same command after a network error reuses the same job. Downloads accept same-origin relative URLs only, refuse redirects and replace the local file only after streamed hash and size checks.

## For agents

The repository's `skills/` folder is a pack of agent skills that work together. An agent that knows them knows every feature on these pages, and can choose the ones a shot needs:

| Skill | Covers |
| --- | --- |
| `h3-continuity-video` | The entry: the Timeline in brief, every feature in one line, and which skill to read next. |
| `h3-continuity-joins` | Continue, cut, new scene, transitions inside H3, visual memory, bridges, splitting a clip. |
| `h3-continuity-timing` | The frame grid, exact lengths and long edits, clip starts, long clips and Context Windows. |
| `h3-continuity-references` | Prompts, the three modes, mentions, pictures, first and last frames, Shot guides, stills, RefMods, plates. |
| `h3-continuity-sound` | Audio lanes, the recording in the full video, voice clips, timed text. |
| `h3-continuity-story` | H3 Story, templates, the Story bible and Cast, Cast memory, the continuity check. |
| `h3-continuity-api` | This API, the graph-preparation route, receipts, held jobs, takes and export. |

`GET /h3c/timeline/instructions` serves the whole pack (`skills`, entry first, and `skill` for the entry), so a remote agent reads the version the server runs. To install the pack for agents on the same computer, run `python skills/install.py` from the copy of H3 Continuity that ComfyUI loads. It links each skill into the agent skill folders that exist (`~/.agents/skills`, `~/.claude/skills`, `~/.codex/skills`), or into those named with `--target`, so the skills follow that copy when it updates. Story and a writing provider are optional; no cast, canon, style or duration is assumed.
