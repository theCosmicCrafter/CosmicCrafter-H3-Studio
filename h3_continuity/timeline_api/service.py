"""Public facade: creative inputs in, owned native preparation and durable DTOs out."""

import copy
import json
import logging
import os
import re
import secrets
import uuid

from .. import timing
from .contracts import APIError, digest, schemas, validate
from .assets import contained, file_hash

_records_provider = None
LOGGER = logging.getLogger(__name__)


def _native_body(project, box=None):
    return {"name": project["sequence"], "timeline": json.dumps(project["prepared"]["timeline"]),
            "settings": project["prepared"]["settings"], **({"box":box} if box else {})}


def _take_identity(folder, entry):
    filenames = [entry["stem"]+".safetensors",entry["stem"]+"_last.png",entry["video"]["file"]]
    return {"entry":entry,"files":{name:file_hash(contained(folder,folder/name)) for name in filenames}}


def sequence_owner(cls):
    hidden = getattr(cls, "hidden", None)
    info = getattr(hidden, "extra_pnginfo", None)
    return info.get("h3c_api") if isinstance(info, dict) else None


def sequence_identity(name):
    """Match native storage's stripped name and the host filesystem's case rules."""
    if not isinstance(name, str): return None
    from ..store import validate_name
    try: return os.path.normcase(validate_name(name))
    except ValueError: return None


def authorize_sequence(name, owner, operation):
    """Native pre-write guard; the runtime supplies the authoritative records."""
    name = sequence_identity(name)
    if name is None or not re.fullmatch(r"api_[a-f0-9]{32}", name) or _records_provider is None:
        return
    records = _records_provider()
    lease = records.owner_for_sequence(name)
    if lease is None:
        return
    rejected = APIError("project_busy", "Managed Timeline changes must use the project API and its current owner.", status=409)
    if not isinstance(owner, dict) or owner.get("project_id") != lease["project_id"] or lease["id"] is None:
        raise rejected
    if lease["kind"] == "job" and owner.get("job_id") == lease["id"]:
        job = records.get_job(lease["id"])
        if job["state"] in ("succeeded", "failed"):
            raise rejected
        if owner.get("revision") != job["revision"] or owner.get("profile_sha256") != job["profile_sha256"]:
            raise rejected
        supplied = owner.get("owner_token")
        if not isinstance(supplied, str): raise rejected
        if operation == "full_video" and secrets.compare_digest(supplied, job["owner_token"]):
            return
        attempt = next((item for item in job["attempts"] if item["id"] == owner.get("attempt_id")
                        and item["unit_id"] == owner.get("unit_id")), None)
        if (attempt and attempt["state"] in ("submitting", "acknowledged")
                and secrets.compare_digest(supplied, attempt.get("owner_token", ""))):
            return job
    elif lease["kind"] == "mutation" and owner.get("operation_id") == lease["id"]:
        with records.transaction() as db:
            row = db.execute("SELECT data,state FROM mutations WHERE id=?", (lease["id"],)).fetchone()
        if row and row["state"] == "pending":
            mutation = json.loads(row["data"])
            supplied = owner.get("owner_token")
            if (operation in ("take_use", "full_video") and isinstance(supplied, str)
                    and secrets.compare_digest(supplied, mutation["intent"].get("owner_token", ""))):
                return
    raise rejected


class TimelineAPI:
    def __init__(self, records, profiles, assets, planner=None, jobs=None, artifacts=None):
        self.records, self.profiles, self.assets = records, profiles, assets
        self.planner, self.jobs, self.artifacts = planner, jobs, artifacts

    def capabilities(self):
        operations = ["assets", "projects", "workflow"]
        if self.planner: operations.append("plan")
        if self.jobs: operations.extend(["jobs", "resume", "cancel", "abandon"])
        if self.artifacts: operations.append("artifacts")
        if self.planner: operations.append("takes")
        return {"api_version": 1, "timeline_version": 1, "schemas": schemas(), "profiles": self.profiles.list(),
                "instructions_url": "/h3c/timeline/instructions", "operations": operations,
                "readiness": {"render": self.jobs is not None and self.artifacts is not None, "plan": self.planner is not None},
                "limits": {"fps": 24, "geometry_multiple": 32, "context_frames": [int(c) for c in timing.CONTEXT_OPTIONS],
                           "bridge_frames": [12, 29, 46], "reference_images_per_box": 9, "reference_audios_per_box": 3,
                           "reference_videos_per_box": 3, "reference_video_audios_per_box": 3,
                           "max_upload_bytes": 2 * 1024**3, "project_page_size": {"default": 50, "max": 100}},
                "jobs": self.jobs.queue_status() if self.jobs else None}

    def _project_dto(self, project):
        result = {key: copy.deepcopy(project[key]) for key in (
            "api_version", "id", "revision", "name", "profile", "profile_sha256", "sequence", "created", "active_job", "timeline")}
        for key in ("settings", "assets", "consumer", "semantic_boxes"):
            result[key] = copy.deepcopy(project.get(key, {} if key != "assets" else []))
        result["active_operation"] = project["lease"]["id"] if project.get("lease",{} ) and project["lease"]["kind"] == "mutation" else None
        prepared = project["prepared"]
        result["inspection"] = {key: copy.deepcopy(prepared[key]) for key in ("timeline", "settings", "boxes", "fingerprint")}
        if prepared.get("production_size"):
            result["inspection"]["production_size"] = copy.deepcopy(prepared["production_size"])
        return result

    def _prepare(self, profile, sequence, body):
        resolved = self.assets.resolve(body.get("assets", []), body["timeline"], profile)
        verified_files = {(file["type"], file.get("subfolder", ""), file["filename"])
                          for asset in resolved if any(binding["kind"] != "candidate" for binding in asset["bindings"])
                          for file in [asset["file"]]}
        line = body["timeline"]
        pointers = [item.get(field) for collection, field in (("pictures", "file"), ("voice_clips", "file"),
                    ("audio_clips", "file"), ("plates", "image")) for item in line.get(collection, [])]
        pointers += [item.get("guide") for box in line.get("boxes", []) for item in box.get("previews", [])]
        pointers += [item.get('file') for item in line.get('reference_replacements', {}).values()]
        for file in pointers:
            if file is not None and (file.get("type"), file.get("subfolder", ""), file.get("filename")) not in verified_files:
                raise APIError("unregistered_asset", "File-backed Timeline media needs a verified uploaded asset binding.", status=422)
        return self.profiles.prepare(profile, sequence, body, resolved)

    def create_project(self, body, key):
        existing = self.records.lookup_key("project_create", key, digest(body))
        if existing is not None:
            return self._project_dto(existing)
        body = validate("project_create", body)
        profile = self.profiles.get(body["profile"])
        sequence = "api_" + uuid.uuid4().hex
        prepared = self._prepare(profile, sequence, body)
        return self._project_dto(self.records.create_project(body, prepared, profile, key))

    def get_project(self, project_id):
        project = self.records.get_project(project_id)
        result = self._project_dto(project)
        if self.planner:
            result["status"] = self.planner.native_status(_native_body(project))
            completed = self.records.latest_completed_job(project_id)
            if completed and completed["revision"] == project["revision"]:
                full = next((artifact for artifact in completed["artifacts"] if artifact["kind"] == "full_video"),None)
                if full: result["status"]["full_video"] = full
        return result

    def list_projects(self, cursor=None, limit=50):
        return self.records.list_projects(cursor, limit)

    def update_project(self, project_id, body):
        body = validate("project_update", body)
        current = self.records.get_project(project_id)
        self.records._check_edit(current, body["expected_revision"])
        profile = self.profiles.get(current["profile"], current["profile_sha256"])
        prepared = self._prepare(profile, current["sequence"], body)
        updated = self.records.update_project(project_id, body, prepared, body["expected_revision"])
        result = self._project_dto(updated)
        if self.planner: result["invalidation"] = self.planner.invalidation(current, updated)
        return result

    def plan_project(self, project_id, body):
        body = validate("plan_create", body)
        project = self.records.get_project(project_id)
        if project["revision"] != body["expected_revision"]:
            raise APIError("revision_conflict", "Project revision has changed.", status=409,
                           details={"current_revision": project["revision"]})
        if self.planner is None:
            raise APIError("planner_unavailable", "Timeline planner is unavailable.", status=503)
        return self.planner.plan(project, body["selection"])

    def workflow(self, project_id, mode="fork"):
        project = self.records.get_project(project_id)
        # Export remains available when a pinned model has gone offline.
        return self.profiles.workflow(project["profile_snapshot"], project, mode=mode)

    def create_job(self, project_id, body, key):
        if self.jobs is None: raise APIError("renderer_unavailable", "Timeline job worker is unavailable.", status=503)
        return self.jobs.accept(project_id, body, key)

    def get_job(self, job_id):
        if self.jobs is None: raise APIError("renderer_unavailable", "Timeline job worker is unavailable.", status=503)
        return self.jobs.get(job_id)

    async def resume_job(self, job_id):
        if self.jobs is None: raise APIError("renderer_unavailable", "Timeline job worker is unavailable.", status=503)
        return await self.jobs.resume(job_id)

    async def cancel_job(self, job_id):
        if self.jobs is None: raise APIError("renderer_unavailable", "Timeline job worker is unavailable.", status=503)
        return await self.jobs.cancel(job_id)

    async def abandon_job(self, job_id, body):
        if self.jobs is None: raise APIError("renderer_unavailable", "Timeline job worker is unavailable.", status=503)
        return await self.jobs.abandon(job_id, body)

    def list_takes(self, project_id, box_id):
        from .. import nodes, takes
        project = self.records.get_project(project_id)
        if not isinstance(box_id,str) or box_id not in {box["id"] for box in project["timeline"]["boxes"]}:
            raise APIError("invalid_selection","Specify an existing box ID.",path="/box")
        with nodes.SEQUENCE_LOCK:
            sequence = takes._Sequence(_native_body(project,box_id))
            folder = contained(self.assets.roots["output"],sequence.folder)
            listing = takes.listing(_native_body(project,box_id))
            if not listing.get("ok"): raise APIError("invalid_selection","Native takes cannot be listed for this box.",status=409)
            result = {"api_version":1,"project_id":project_id,"revision":project["revision"],"busy":bool(project["lease"]) or listing["busy"],"box":None,"bridge":None}
            for kind in ("box","bridge"):
                group = listing.get(kind)
                if group is None: continue
                items = []
                for item in group["takes"]:
                    native = next(take for take in sequence.saved if take["folder"] == item["folder"])
                    directory = contained(folder,folder/item["folder"])
                    try: proof = _take_identity(directory,native["entry"])
                    except (OSError,KeyError,TypeError): continue
                    identity = {"project_id":project_id,"box_id":box_id,"kind":kind,"folder":item["folder"],"proof":proof}
                    identifier = "take_"+digest(identity)
                    self.records.put_immutable_blob_record("take",{**identity,"id":identifier,"seed":item["seed"],"created":item["created"]})
                    items.append({key:copy.deepcopy(item[key]) for key in ("seed","created","usable","why","bytes")})
                    items[-1]["id"] = identifier
                    if self.artifacts:
                        artifact = self.records.find_artifact(project_id,proof["files"][native["entry"]["video"]["file"]])
                        if artifact: items[-1]["video"] = self.artifacts.get(artifact["id"])
                result[kind] = {"in_use":group["in_use"],"takes":items,"warnings":group.get("warnings",[])}
            return result

    def _take_fault(self, point):
        """Crash-window seam; ownership persists until native state reconciles."""

    def use_take(self, project_id, body):
        from .. import nodes, takes
        from .artifacts import Artifacts
        from .planning import native_status
        body = validate("take_use",body)
        project = self.records.get_project(project_id)
        if project.get("lease") and project["lease"]["kind"] == "mutation":
            operation = self.records.get_mutation(project["lease"]["id"])
            if operation["intent"]["request"] == body: return self._reconcile_take(operation)
        self.records._check_edit(project,body["expected_revision"])
        chosen = self.records.get_blob_record("take",body["take_id"])
        if (chosen["project_id"],chosen["box_id"],chosen["kind"]) != (project_id,body["box"],body["kind"]):
            raise APIError("invalid_selection","Take belongs to another project or unit.",status=409)
        authored = copy.deepcopy(project["authored"])
        targets = authored["timeline"]["boxes"] if body["kind"] == "box" else authored["timeline"].get("bridges",[])
        field = "id" if body["kind"] == "box" else "before"
        target = next((item for item in targets if item[field] == body["box"]),None)
        if target is None: raise APIError("invalid_selection","Selected unit no longer exists.",status=409)
        target["seed"] = chosen["seed"]
        profile = self.profiles.get(project["profile"],project["profile_sha256"])
        prepared = self._prepare(profile,project["sequence"],authored)
        updated = {**project,"authored":authored,"prepared":prepared}
        with nodes.SEQUENCE_LOCK:
            sequence = takes._Sequence(_native_body(updated,body["box"]))
            folder = contained(self.assets.roots["output"],sequence.folder)
            try: proof = _take_identity(contained(folder,folder/chosen["folder"]),chosen["proof"]["entry"])
            except (OSError,KeyError,TypeError):
                raise APIError("take_changed","Saved take is unavailable or changed.",status=409) from None
            if proof != chosen["proof"]: raise APIError("take_changed","Saved take bytes have changed.",status=409)
            native = next((take for take in sequence.saved if take["folder"] == chosen["folder"]),None)
            if native is None or sequence.why(native): raise APIError("take_incompatible","Take no longer fits this Timeline and its saved neighbours.",status=409)
            unit_id = body["kind"]+":"+body["box"]
            unit = next(item for item in self.planner._units(updated) if item["id"] == unit_id)
            inspector = self.artifacts or Artifacts(self.records,self.assets.roots["output"])
            inspector._inspect(folder/chosen["folder"]/native["entry"]["video"]["file"],updated,
                {"audio_sample_rate":native["entry"].get("audio_sample_rate")},unit["frames"])
            before = native_status(_native_body(project))
        intent = {"request":body,"body":authored,"prepared":prepared,"chosen":chosen,"before":before,
                  "before_body":_native_body(project),"owner_token":secrets.token_hex(32),"unit_id":unit_id}
        operation = self.records.reserve_mutation(project_id,body["expected_revision"],intent)
        return self._reconcile_take(operation)

    def _reconcile_take(self, operation):
        from .. import nodes, takes, store
        from .planning import native_status
        intent = operation["intent"]
        project = self.records.get_project(operation["project_id"])
        if operation["state"] == "completed": return self._project_dto(project)
        updated = {**project,"prepared":intent["prepared"],"authored":intent["body"]}
        chosen = intent["chosen"]
        uncertain = APIError("take_needs_reconciliation","Take files and project revision need reconciliation; the project remains reserved.",status=409,
                             details={"operation_id":operation["id"]})
        with nodes.SEQUENCE_LOCK:
            folder = contained(self.assets.roots["output"],store.sequence_dir(nodes.sequences_root(),project["sequence"]))
            def matches():
                sequence = takes._Sequence(_native_body(updated,chosen["box_id"]))
                entry = sequence.in_use(chosen["kind"],chosen["box_id"])
                if entry is None: return False
                return _take_identity(folder,entry) == chosen["proof"]
            try:
                current = native_status(intent["before_body"])
                if not matches():
                    if current["manifest_sha256"] != intent["before"]["manifest_sha256"]: raise uncertain
                    owner = {"project_id":project["id"],"operation_id":operation["id"],"owner_token":intent["owner_token"]}
                    result = takes.use({**_native_body(updated,chosen["box_id"]),"take":chosen["folder"],"created":chosen["created"],
                                        "bridge":chosen["kind"] == "bridge"},managed_owner=owner)
                    if not result.get("ok"):
                        if native_status(intent["before_body"])["manifest_sha256"] == intent["before"]["manifest_sha256"]:
                            self.records.abort_mutation(operation["id"])
                            raise APIError("take_incompatible","Native take selection was refused; the revision is unchanged.",status=409)
                        raise uncertain
                    self._take_fault("after_take_switch")
                after = native_status(_native_body(updated))
                if not matches() or any(after["unit_evidence"].get(key) != value for key,value in intent["before"]["unit_evidence"].items()
                                        if key != intent["unit_id"]): raise uncertain
            except (OSError,KeyError,TypeError,ValueError) as error:
                if isinstance(error,APIError): raise
                raise uncertain from None
        # The native lock is released; the durable lease excludes other writers.
        unit = next(item for item in self.planner._units(updated) if item["id"] == intent["unit_id"])
        self.records.put_blob_record("unit",{"id":project["id"]+":"+unit["id"],"verified":True,
            "input_sha256":unit["input_sha256"],"native_sha256":after["unit_evidence"][unit["id"]],"take_id":chosen["id"]})
        return self._project_dto(self.records.finish_mutation(operation["id"],intent["body"],intent["prepared"]))

    def reconcile_mutations(self):
        for operation in self.records.pending_mutations():
            try: self._reconcile_take(operation)
            except APIError:
                LOGGER.warning("Timeline take mutation remains reserved: %s",operation["id"])

# static-configuration-interop-v1

# captured-api-delivery-v2

# configured-production-size-v1
