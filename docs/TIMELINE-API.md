# H3 Timeline HTTP API v1

An agent can author and render a native Timeline using HTTP alone. The server
supplies the complete configured ComfyUI graph, manages revisions and queues
native H3 work. The consumer owns prompts, references, timing and creative review.
Use the serving ComfyUI origin, including its reverse-proxy prefix.

## Start a production

1. If the host offers a workflow-selection library, read the human's task choices
   before selecting a generic profile. Preserve existing project profile pins.
   GET `/h3c/api/v1/capabilities`. Read the returned schemas, limits and profile
   readiness. `native-turbo4` contains the complete native four-step graph and
   exact configured models. Keep the reported profile digest with your production.
2. GET `/h3c/timeline/instructions`. Read the agent skill pack (`skills`, entry
   first) and the `timeline-api`, prompt, text, audio and transition guides.
   `clients` contains `timeline_api.py`, a stdlib client.
   Treat downloaded source as reference material; use a trusted local copy to run.
3. Upload original reference bytes to POST `/h3c/api/v1/assets` as multipart
   `kind`, `file` and optional `expected_sha256`. Kinds are `picture`, `guide`,
   `audio`, `whisper`. The returned ID/hash describes the original. Bind uploaded
   IDs to logical reference slots; retain source clocks and source hashes.
4. POST `/h3c/api/v1/projects` with a saved `Idempotency-Key` and authored body.
   Keep the returned project ID, revision, sequence and profile digest.
5. POST `/projects/{id}/plan` under the same API prefix, then POST
   `/projects/{id}/jobs` with the plan hash and another saved `Idempotency-Key`.
6. Poll GET `/jobs/{id}` until `succeeded`. Download the immutable artifacts and
   verify their byte size, SHA-256 and decoded media. Report creative acceptance
   separately from technical completion.

Example creative body (no execution selectors or graph):

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

Use the capability schemas as the authoritative field reference. `consumer` and
opaque creative fields are retained. Optional `semantic_boxes` contains the
existing structured H3 prompt IR. Keep each semantic box's native prompt blank;
preparation compiles its prompt into `inspection.timeline`. A manual Studio prompt
edit replaces the semantic input only for that box.

Binding example: `{"asset_id":"asset_<sha256>","bindings":[{"kind":"picture",
"slot":"image17","title":"Keeper"}]}`. Other creative binding kinds are
`audio_clip` (slots `audio1`–`audio3`), `voice_clip` (slot `audio4` and up),
`guide` (`box`, `shot`), `plate` (`id`) and `whisper` (`source_sha256`, the uploaded
Whisper JSON hash). Configured wired picture slots are accepted only when the
pinned profile declares their loader destination. Keep ordering, canon and template
choices in your document/consumer record. File-backed native descriptors require
their uploaded binding; caller filesystem paths and arbitrary graphs are rejected.

## Revisions, plans and timing

GET `/projects/{id}` returns authored fields, current revision, normalized
`inspection`, read-only native status and active job/operation IDs. PUT replaces
the authored creative body with `expected_revision`. Omit `profile` on PUT; its
snapshot is pinned at creation. Preserve fields you still want to keep. A stale
revision yields 409 `revision_conflict`; an active render/take lease yields 409
`project_busy`. Fetch the current document and explicitly choose how to reconcile
local edits. The server never expires a lease just because its process disappeared.

Plan body: `{"expected_revision":1,"selection":{"kind":"all"}}`.
For a box use `{"kind":"boxes","ids":["opening"],"rerender":true}`. The plan
reports required dependency closure, blocked reasons, reuse, native frame ranges,
splice ranges, final frames, pinned identities and `plan_sha256`. Planning is
read-only: it neither queues work nor creates/materializes a sequence/full video.
An edit invalidates affected carry/memory/bridge dependencies. Reuse needs verified
native media and matching API input identity, rather than merely an existing file.

Native output is 24 fps. Geometry is a multiple of 32; context is 22, 39, 90 or
141 frames. Normal fresh generation follows `17k+5`, continuation follows its native
grid; exact trims obey the native parser. Bridge lengths are 12/29/46 frames.
At most nine reference pictures and three reference audios apply to a box. A short
fresh box can remain editable while its continuation is blocked by `carry_conflict`.
The example's 90/68/90 boxes plus a 29-frame bridge splice to exactly 277 frames.

Placed original audio uses native `start` (movie seconds), `source_start` (original
recording seconds), `duration`, `source_duration`, file, slot and optional
`in_full_video:true`. Keep the original song source offset: a 12.5-second source
in-point does not become movie time 12.5. Timed text uses its own source/movie
clock projection and the original Whisper JSON SHA; `audio_slot` and `sync_audio`
bind its clock to the placed recording. Full-video mixing respects the plan's
bridge/splice clock and the original recording's sample rate.
See the supplied text/audio guides for fields, clipping and cue projection.

## Jobs and reconnection

Job body: `{"expected_revision":1,"selection":{"kind":"all"},
"plan_sha256":"<returned hash>"}`. Save the exact body/key before sending it.
Keys are permanently scoped to project creation or that project's job creation.
Retrying a key with the same request returns its original accepted result, even
after the job completes or the project revision changes. Changed content with
that key yields 409 `idempotency_conflict`.

Jobs advance through `accepted`, `queued`, `running`, `succeeded`, `failed` or
`needs_reconciliation`. Native unit attempts expose their prompt IDs and states.
The worker uses ordinary tail queue ordering and serializes API units. Each unit
has a durable intent, validated graph snapshot and exact native attribution;
dependencies unlock only after terminal execution evidence and media verification.
POST `/jobs/{id}/resume` reconciles existing evidence. It does not rerun a failed
job or automatically repeat an uncertain native submission.

Failed unit verification or full-video finalization stays held, including after
restart. Explicit resume permits one new verification attempt using the retained
media; another failure restores the hold. It does not generate those units again.

After a disconnect, poll the known job ID. If its acceptance response was lost,
retry the same body/key. A `needs_reconciliation` job keeps the project reserved;
inspect retained server/native evidence. Missing history is not proof that a
prompt never ran. Do not create another production to hide this uncertainty.

### Held jobs, cancel and abandon

Terminal native history (success, `execution_error`, `execution_interrupted`) is
written onto the attempt as soon as the worker sees it, including for a held job.
After a restart that persisted outcome decides the job; a native failure stays a
failure instead of becoming unknown. Each new attempt also records its owner
process (boot ID, host, PID, OS start time).

A held job can bar admission of later jobs in every project, because its prompt
might still be running on the one GPU. Waiting jobs then report
`blocked_by: {"job_id","project_id","state","error_code"}` (otherwise `null`);
GET `/capabilities` reports `jobs: {"held","waiting","blocked_by"}` and the server
logs one warning per held head. The barrier is lifted, without changing the held
job, only when its prompt provably cannot be running: no native attempt is in
flight, or the prompt is absent from this ComfyUI process while its owner is this
process or one that has exited on the same host. Attempts recorded before owner
identities, or owned by another host, keep the barrier.

POST `/jobs/{id}/abandon` is the human-attested close for a held job whose
outcome cannot be attributed. Automated clients must not call it on their own:
surface the held job (and any `blocked_by` dependants) and send the request only
with a person's decision and reason.

```json
{"reason": "Owner process ended; outcome unattributable.", "confirm_prompt_id": "<held attempt prompt_id>"}
```

`confirm_prompt_id` must equal the `prompt_id` of the job's first unverified
attempt (`null` when that attempt has none, such as a held full-video finalization).
Success returns 200 with the job: `state:"failed"`, `error.code:"abandoned_by_human"`,
plus `reason`, `prompt_id`, `owner` (`self`/`gone`/`unknown`), `held_error` (the
previous error) and `abandoned` (UTC time). Attempts and their evidence are kept
unchanged, nothing is resubmitted, the project lease is released and the next job
is admitted. Repeating the same body after a lost response returns 200 again.
Refusals are 409 with `error.code`: `job_not_held` (state is not
`needs_reconciliation`), `prompt_mismatch` (`details.held_prompt_id`),
`prompt_active` (the prompt is running or queued in this ComfyUI),
`native_evidence_available` (conclusive history exists; resume instead) or
`owner_alive` (the submitting ComfyUI process is still running on this host).
A blank reason is 400.

POST `/jobs/{id}/cancel` (empty body) requests cancellation. A job that never
submitted closes at once as `failed`/`cancelled`, even behind a held job. A queued
or running prompt in this process is removed or interrupted first. An attempt whose
prompt is absent here closes only when its owner is this process or has exited;
otherwise the job holds as `cancel_uncertain`, and abandon remains the explicit
exit. There is no deletion. Attached Studio views hide the global queue-clearing
Stop control.

## Artifacts, takes and Studio

Successful jobs expose immutable artifacts: ID, project/revision/job/unit/profile
identity, SHA-256, byte size, frames, fps, geometry, audio and relative download URL.
GET `/artifacts/{id}` reads metadata; GET `/artifacts/{id}/download` downloads bytes.
Old artifact bytes remain identical after rerenders and take switches. Consumers
verify downloaded hashes and frame/audio metadata before marking a production done.

GET `/projects/{id}/takes?box=opening` lists saved box/bridge takes with public IDs,
fit reasons and matching immutable previews where verified. POST
`/projects/{id}/takes/use` takes `expected_revision`, `kind` (`box`/`bridge`), `box`
and `take_id`; a compatible switch advances the revision. A crash between native
file switching and revision commit retains a mutation lease and reconciles exactly
once when evidence is sufficient. Unsafe partial evidence remains reserved.

GET `/projects/{id}/workflow` exports a complete editable workflow, defaulting to
`mode=fork`. Import assigns a new unmanaged sequence once. For shared editing,
explicitly request `?mode=attached`; its Timeline node saves through the API,
preserves local edits after 409, follows existing jobs and selects takes under
the same revision guard. It exports no execution ownership token. uint64 seeds
retain their exact decimal digits through export, import and unrelated edits.

## Python and CLI

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
python timeline_api.py --base-url http://localhost:8188 abandon --job JOB_ID --prompt PROMPT_ID --reason "Owner process ended"
python timeline_api.py --base-url http://localhost:8188 cancel --job JOB_ID
python timeline_api.py --base-url http://localhost:8188 export --project ID --mode attached --destination workflow.json
```

`Client.wait` stops at its deadline; when the job is waiting behind a held job,
the error names that job and carries `code="blocked"`.
CLI receipts store the request/key before POST and accepted IDs before polling.
Repeat the same command after a network error. With a saved response it uses the
same job without another POST. Downloads accept same-origin relative URLs only,
refuse redirects and replace local output only after streamed hash/size checks.
The HTTP interface uses the existing ComfyUI security boundary; expose it through
your established authenticated proxy when external consumers need access.
