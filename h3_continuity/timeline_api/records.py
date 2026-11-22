"""Durable identities, revisions and leases. No native locks or GPU work here."""

import base64
import copy
import hashlib
import json
import os
import re
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .contracts import APIError, canonical, digest

JOB_STATES = {"accepted", "queued", "running", "needs_reconciliation", "succeeded", "failed"}
ATTEMPT_STATES = {"pending", "submitting", "acknowledged", "succeeded", "verified", "failed"}
TERMINAL = {"succeeded", "failed"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _text(value):
    return canonical(value).decode("utf-8")


class Records:
    def request_job_cancel(self, job_id):
        with self.transaction() as db:
            job = self._job(db, job_id)
            if job["state"] not in TERMINAL:
                job["cancel_requested"] = True
                self._write_job(db, job)
            return job

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = self.root / "records.sqlite3"
        db = self._connect()
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS projects (
                    ordinal INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
                    sequence TEXT NOT NULL UNIQUE, revision INTEGER NOT NULL,
                    profile_sha256 TEXT NOT NULL, created TEXT NOT NULL,
                    lease_kind TEXT, lease_id TEXT);
                CREATE TABLE IF NOT EXISTS revisions (
                    project_id TEXT NOT NULL REFERENCES projects(id), revision INTEGER NOT NULL,
                    authored TEXT NOT NULL, prepared TEXT NOT NULL, profile TEXT NOT NULL,
                    created TEXT NOT NULL, PRIMARY KEY(project_id, revision));
                CREATE TABLE IF NOT EXISTS request_keys (
                    scope TEXT NOT NULL, key TEXT NOT NULL, request_sha256 TEXT NOT NULL,
                    response TEXT NOT NULL, PRIMARY KEY(scope, key));
                CREATE TABLE IF NOT EXISTS jobs (
                    ordinal INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
                    project_id TEXT NOT NULL REFERENCES projects(id), state TEXT NOT NULL,
                    data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS mutations (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                    state TEXT NOT NULL, data TEXT NOT NULL, response TEXT);
                CREATE TABLE IF NOT EXISTS blobs (
                    kind TEXT NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL,
                    PRIMARY KEY(kind, id));
                PRAGMA user_version=1;
            """)
        finally:
            db.close()

    def _connect(self):
        db = sqlite3.connect(self.database, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA busy_timeout=5000")
        return db

    @contextmanager
    def transaction(self):
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except sqlite3.OperationalError as error:
            db.rollback()
            if "locked" in str(error).lower() or "busy" in str(error).lower():
                raise APIError("storage_busy", "API storage is busy; retry the same request.", status=503) from None
            raise
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _lookup_key(self, db, scope, key, request_sha256):
        if not isinstance(key, str) or not key.strip() or len(key) > 256:
            raise APIError("idempotency_required", "Supply an Idempotency-Key of 1 to 256 characters.")
        row = db.execute("SELECT request_sha256,response FROM request_keys WHERE scope=? AND key=?", (scope, key)).fetchone()
        if row is None:
            return None
        if row["request_sha256"] != request_sha256:
            raise APIError("idempotency_conflict", "This key was already used with another request.", status=409)
        return json.loads(row["response"])

    def lookup_key(self, scope, key, request_sha256):
        with self.transaction() as db:
            return self._lookup_key(db, scope, key, request_sha256)

    def _key(self, db, scope, key, request_sha256, response):
        db.execute("INSERT INTO request_keys VALUES (?,?,?,?)", (scope, key, request_sha256, _text(response)))

    def _project(self, db, project_id):
        row = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if row is None:
            raise APIError("not_found", "Timeline project was not found.", status=404)
        revision = db.execute("SELECT * FROM revisions WHERE project_id=? AND revision=?", (project_id, row["revision"])).fetchone()
        authored = json.loads(revision["authored"])
        return {**authored, "api_version": 1, "version": 1, "id": row["id"], "sequence": row["sequence"],
                "revision": row["revision"], "profile_sha256": row["profile_sha256"], "created": row["created"],
                "active_job": row["lease_id"] if row["lease_kind"] == "job" else None,
                "lease": {"kind": row["lease_kind"], "id": row["lease_id"]} if row["lease_id"] else None,
                "authored": authored, "prepared": json.loads(revision["prepared"]),
                "profile_snapshot": json.loads(revision["profile"])}

    def get_project(self, project_id):
        with self.transaction() as db:
            return self._project(db, project_id)

    def _check_edit(self, project, expected_revision):
        if project["lease"] is not None:
            raise APIError("project_busy", "A render or take selection owns this project.", status=409,
                           details={"project_id": project["id"], "current_revision": project["revision"],
                                    "operation_id": project["lease"]["id"]})
        if type(expected_revision) is not int or project["revision"] != expected_revision:
            raise APIError("revision_conflict", "Project revision has changed.", status=409,
                           details={"current_revision": project["revision"]})

    def _insert_revision(self, db, project_id, number, body, prepared, profile):
        authored = copy.deepcopy(body)
        authored.pop("expected_revision", None)
        db.execute("INSERT INTO revisions VALUES (?,?,?,?,?,?)", (project_id, number, _text(authored), _text(prepared), _text(profile), _now()))

    def create_project(self, body, prepared, profile, key):
        request_hash = digest(body)
        # The facade mints a UUID before pure preparation, which needs the final
        # native sequence for its fingerprint. This is never caller-supplied data.
        with self.transaction() as db:
            old = self._lookup_key(db, "project_create", key, request_hash)
            if old is not None:
                return old
        sequence = prepared.get("name", "")
        if not re.fullmatch(r"api_[a-f0-9]{32}", sequence):
            raise APIError("invalid_preparation", "Prepared project identity is invalid.", status=500)
        project_id = str(uuid.UUID(hex=sequence[4:]))
        pinned_profile = {**profile, "snapshot": self.snapshot_json("profile", profile)}
        pinned_prepared = {**prepared, "snapshot": self.snapshot_json("prepared", prepared)}
        with self.transaction() as db:
            old = self._lookup_key(db, "project_create", key, request_hash)
            if old is not None:
                return old
            db.execute("INSERT INTO projects(id,sequence,revision,profile_sha256,created) VALUES (?,?,?,?,?)",
                       (project_id, sequence, 1, profile["sha256"], _now()))
            self._insert_revision(db, project_id, 1, body, pinned_prepared, pinned_profile)
            result = self._project(db, project_id)
            self._key(db, "project_create", key, request_hash, result)
            return result

    def _replace(self, db, project, body, prepared):
        if prepared.get("name") != project["sequence"]:
            raise APIError("invalid_preparation", "Prepared sequence does not match the project.", status=500)
        authored = {**body, "name": body.get("name", project.get("name", "Timeline")), "profile": project["profile"]}
        revision = project["revision"] + 1
        self._insert_revision(db, project["id"], revision, authored, prepared, project["profile_snapshot"])
        db.execute("UPDATE projects SET revision=? WHERE id=?", (revision, project["id"]))
        return self._project(db, project["id"])

    def update_project(self, project_id, body, prepared, expected_revision):
        pinned = {**prepared, "snapshot": self.snapshot_json("prepared", prepared)}
        with self.transaction() as db:
            project = self._project(db, project_id)
            self._check_edit(project, expected_revision)
            return self._replace(db, project, body, pinned)

    def list_projects(self, cursor=None, limit=50):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise APIError("invalid_request", "Limit must be an integer from 1 to 100.", path="/limit")
        after = 0
        with self.transaction() as db:
            if cursor is not None:
                try:
                    if not isinstance(cursor, str) or len(cursor) > 1024:
                        raise ValueError()
                    value = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
                    if set(value) != {"version", "ordinal", "id"} or value["version"] != 1 or type(value["ordinal"]) is not int:
                        raise ValueError()
                    row = db.execute("SELECT ordinal FROM projects WHERE id=?", (value["id"],)).fetchone()
                    if row is None or row["ordinal"] != value["ordinal"]:
                        raise ValueError()
                    after = value["ordinal"]
                except (ValueError, TypeError, KeyError, sqlite3.Error):
                    raise APIError("invalid_request", "Project cursor is invalid.", path="/cursor") from None
            rows = db.execute("SELECT id,ordinal FROM projects WHERE ordinal>? ORDER BY ordinal,id LIMIT ?", (after, limit + 1)).fetchall()
            page = rows[:limit]
            next_cursor = None
            if len(rows) > limit:
                next_cursor = base64.urlsafe_b64encode(canonical({"version": 1, "ordinal": page[-1]["ordinal"], "id": page[-1]["id"]})).decode("ascii")
            summaries = [{key: project[key] for key in ("id", "revision", "name", "profile", "profile_sha256", "created", "active_job")}
                         for project in (self._project(db, row["id"]) for row in page)]
            return {"api_version": 1, "projects": summaries, "next_cursor": next_cursor}

    def _job(self, db, job_id):
        row = db.execute("SELECT data FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise APIError("not_found", "Timeline job was not found.", status=404)
        return json.loads(row["data"])

    def _write_job(self, db, job):
        job["progress"] = {"completed": sum(item["state"] == "verified" for item in job["attempts"]), "total": len(job["attempts"])}
        db.execute("UPDATE jobs SET state=?,data=? WHERE id=?", (job["state"], _text(job), job["id"]))
        return job

    def accept_job(self, project_id, body, plan, key):
        scope, request_hash = "job_create:" + project_id, digest(body)
        with self.transaction() as db:
            old = self._lookup_key(db, scope, key, request_hash)
            if old is not None:
                return old
            project = self._project(db, project_id)
            self._check_edit(project, body.get("expected_revision"))
            if (plan.get("project_id") != project_id or plan.get("revision") != project["revision"]
                    or plan.get("profile_sha256") != project["profile_sha256"]
                    or plan.get("fingerprint") != project["prepared"].get("fingerprint")
                    or plan.get("plan_sha256") != body.get("plan_sha256") or plan.get("selection") != body.get("selection")):
                raise APIError("plan_conflict", "Render plan has changed; request a fresh plan.", status=409,
                               details={"current_revision": project["revision"]})
            if any(unit.get("action") == "blocked" for unit in plan["units"]):
                raise APIError("plan_blocked", "Render plan has blocked units.", status=409)
            job_id = str(uuid.uuid4())
            attempts = [{"unit_id": unit["id"], "id": str(uuid.uuid4()), "state": "pending", "unit": unit}
                        for unit in plan["units"] if unit["action"] == "render"]
            job = {"api_version": 1, "version": 1, "id": job_id, "project_id": project_id,
                   "revision": project["revision"], "profile_sha256": project["profile_sha256"],
                   "plan_sha256": plan["plan_sha256"], "selection": body["selection"], "plan": plan,
                   "state": "accepted", "attempts": attempts, "artifacts": [], "error": None, "created": _now(),
                   "owner_token": secrets.token_hex(32),
                   "project_snapshot": project, "progress": {"completed": 0, "total": len(attempts)},
                   "poll_url": "/h3c/api/v1/jobs/" + job_id}
            db.execute("INSERT INTO jobs(id,project_id,state,data) VALUES (?,?,?,?)", (job_id, project_id, "accepted", _text(job)))
            db.execute("UPDATE projects SET lease_kind='job',lease_id=? WHERE id=?", (job_id, project_id))
            self._key(db, scope, key, request_hash, job)
            return copy.deepcopy(job)

    def get_job(self, job_id):
        with self.transaction() as db:
            return self._job(db, job_id)

    def latest_completed_job(self, project_id):
        with self.transaction() as db:
            row = db.execute("SELECT data FROM jobs WHERE project_id=? AND state='succeeded' ORDER BY ordinal DESC LIMIT 1",(project_id,)).fetchone()
            return json.loads(row["data"]) if row else None

    def save_attempt(self, job_id, unit_id, values):
        with self.transaction() as db:
            job = self._job(db, job_id)
            if job["state"] in TERMINAL:
                raise APIError("job_terminal", "A terminal job cannot be changed.", status=409)
            attempt = next((item for item in job["attempts"] if item["unit_id"] == unit_id), None)
            if attempt is None:
                raise APIError("not_found", "Job unit was not found.", status=404)
            if values.get("state", attempt["state"]) not in ATTEMPT_STATES:
                raise APIError("invalid_request", "Attempt state is invalid.")
            order = {name: index for index, name in enumerate(("pending", "submitting", "acknowledged", "succeeded", "verified", "failed"))}
            if order[values.get("state", attempt["state"])] < order[attempt["state"]]:
                raise APIError("attempt_conflict", "A durable attempt cannot return to an earlier state.", status=409)
            for field in ("id", "unit_id", "unit"):
                if field in values and values[field] != attempt[field]:
                    raise APIError("attempt_conflict", "Attempt identity is immutable.", status=409)
            if attempt["state"] in ("failed", "verified") and values != {"state": attempt["state"]}:
                raise APIError("attempt_terminal", "A terminal attempt cannot be changed.", status=409)
            for field in ("prompt_id", "owner_token", "graph_sha256", "graph_snapshot"):
                if field in attempt and field in values and values[field] != attempt[field]:
                    raise APIError("attempt_conflict", "Submitted attempt evidence is immutable.", status=409)
            attempt.update(copy.deepcopy(values))
            self._write_job(db, job)
            return copy.deepcopy(attempt)

    def set_job_state(self, job_id, state, *, error=None, expected=None):
        if state not in JOB_STATES:
            raise APIError("invalid_request", "Job state is invalid.")
        with self.transaction() as db:
            job = self._job(db, job_id)
            if expected is not None and job["state"] != expected:
                raise APIError("job_state_changed", "Job state changed; read the job and retry.", status=409,
                               details={"state": job["state"]})
            if job["state"] in TERMINAL and state != job["state"]:
                raise APIError("job_terminal", "A terminal job cannot be restarted.", status=409)
            if state == "succeeded" and any(item["state"] != "verified" for item in job["attempts"]):
                raise APIError("job_unverified", "All required units must be verified before success.", status=409)
            job["state"], job["error"] = state, copy.deepcopy(error)
            self._write_job(db, job)
            if state in TERMINAL:
                db.execute("UPDATE projects SET lease_kind=NULL,lease_id=NULL WHERE id=? AND lease_kind='job' AND lease_id=?",
                           (job["project_id"], job_id))
            return job

    def recoverable(self):
        with self.transaction() as db:
            return [json.loads(row["data"]) for row in db.execute("SELECT data FROM jobs WHERE state NOT IN ('succeeded','failed') ORDER BY ordinal,id")]

    def finish_job(self, job_id, artifacts):
        with self.transaction() as db:
            job = self._job(db, job_id)
            if job["state"] == "succeeded": return job
            if job["state"] == "failed" or any(item["state"] != "verified" for item in job["attempts"]):
                raise APIError("job_unverified", "Every render unit must be verified before committing artifacts.", status=409)
            project = self._project(db, job["project_id"])
            if project["lease"] != {"kind": "job", "id": job_id}:
                raise APIError("job_conflict", "Job no longer owns this project.", status=409)
            job.update(state="succeeded", artifacts=copy.deepcopy(artifacts), error=None)
            self._write_job(db, job)
            db.execute("UPDATE projects SET lease_kind=NULL,lease_id=NULL WHERE id=?", (job["project_id"],))
            return job

    def reserve_mutation(self, project_id, expected_revision, intent):
        with self.transaction() as db:
            project = self._project(db, project_id)
            self._check_edit(project, expected_revision)
            operation = {"id": str(uuid.uuid4()), "project_id": project_id, "revision": expected_revision,
                         "state": "pending", "version": 1, "intent": copy.deepcopy(intent), "created": _now()}
            db.execute("INSERT INTO mutations(id,project_id,state,data) VALUES (?,?,?,?)", (operation["id"], project_id, "pending", _text(operation)))
            db.execute("UPDATE projects SET lease_kind='mutation',lease_id=? WHERE id=?", (operation["id"], project_id))
            return operation

    def finish_mutation(self, operation_id, body, prepared):
        pinned = {**prepared, "snapshot": self.snapshot_json("prepared", prepared)}
        with self.transaction() as db:
            row = db.execute("SELECT * FROM mutations WHERE id=?", (operation_id,)).fetchone()
            if row is None:
                raise APIError("not_found", "Take operation was not found.", status=404)
            if row["state"] == "completed":
                return json.loads(row["response"])
            operation = json.loads(row["data"])
            project = self._project(db, row["project_id"])
            if project["revision"] != operation["revision"] or project["lease"] != {"kind": "mutation", "id": operation_id}:
                raise APIError("mutation_conflict", "Take operation ownership has changed.", status=409)
            self._replace(db, project, body, pinned)
            db.execute("UPDATE projects SET lease_kind=NULL,lease_id=NULL WHERE id=?", (project["id"],))
            result = self._project(db, project["id"])
            db.execute("UPDATE mutations SET state='completed',response=? WHERE id=?", (_text(result), operation_id))
            return result

    def owner_for_sequence(self, name):
        with self.transaction() as db:
            row = db.execute("SELECT id,lease_kind,lease_id FROM projects WHERE sequence=?", (name,)).fetchone()
            if row is None:
                return None
            return {"project_id": row["id"], "kind": row["lease_kind"], "id": row["lease_id"]}

    def get_mutation(self, operation_id):
        with self.transaction() as db:
            row = db.execute("SELECT data,state FROM mutations WHERE id=?",(operation_id,)).fetchone()
            if row is None: raise APIError("not_found","Take operation was not found.",status=404)
            return {**json.loads(row["data"]),"state":row["state"]}

    def pending_mutations(self):
        with self.transaction() as db:
            return [json.loads(row["data"]) for row in db.execute("SELECT data FROM mutations WHERE state='pending' ORDER BY id")]

    def abort_mutation(self, operation_id):
        with self.transaction() as db:
            row = db.execute("SELECT project_id,state FROM mutations WHERE id=?",(operation_id,)).fetchone()
            if row is None or row["state"] != "pending": return
            db.execute("UPDATE mutations SET state='aborted' WHERE id=?",(operation_id,))
            db.execute("UPDATE projects SET lease_kind=NULL,lease_id=NULL WHERE id=? AND lease_kind='mutation' AND lease_id=?",(row["project_id"],operation_id))

    def snapshot_json(self, kind, value):
        if not re.fullmatch(r"[a-z_]+", kind):
            raise APIError("invalid_request", "Snapshot kind is invalid.")
        content = canonical(value)
        checksum = hashlib.sha256(content).hexdigest()
        folder = self.root / "snapshots" / kind
        folder.mkdir(parents=True, exist_ok=True)
        destination = folder / (checksum + ".json")
        if destination.exists():
            if destination.read_bytes() != content:
                raise APIError("storage_corrupt", "An immutable snapshot is damaged.", status=500)
        else:
            temporary = folder / (checksum + "." + uuid.uuid4().hex + ".tmp")
            try:
                with temporary.open("xb") as stream:
                    stream.write(content); stream.flush(); os.fsync(stream.fileno())
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
        return {"sha256": checksum, "size": len(content), "blob": destination.relative_to(self.root).as_posix()}

    def put_blob_record(self, kind, record):
        with self.transaction() as db:
            db.execute("INSERT INTO blobs VALUES (?,?,?) ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data",
                       (kind, record["id"], _text(record)))
        return copy.deepcopy(record)

    def get_blob_record(self, kind, identifier):
        with self.transaction() as db:
            row = db.execute("SELECT data FROM blobs WHERE kind=? AND id=?", (kind, identifier)).fetchone()
            if row is None:
                raise APIError("not_found", "Asset or artifact was not found.", status=404)
            return json.loads(row["data"])

    def find_artifact(self, project_id, sha256):
        with self.transaction() as db:
            row = db.execute("SELECT data FROM blobs WHERE kind='artifact' AND json_extract(data,'$.project_id')=? "
                             "AND json_extract(data,'$.sha256')=? ORDER BY id LIMIT 1",(project_id,sha256)).fetchone()
            return json.loads(row["data"]) if row else None

    def put_immutable_blob_record(self, kind, record):
        with self.transaction() as db:
            old = db.execute("SELECT data FROM blobs WHERE kind=? AND id=?",(kind,record["id"])).fetchone()
            if old is not None:
                if json.loads(old["data"]) != record:
                    raise APIError("immutable_conflict", "Immutable metadata cannot be replaced.",status=409)
            else:
                db.execute("INSERT INTO blobs VALUES (?,?,?)",(kind,record["id"],_text(record)))
        return copy.deepcopy(record)

# static-configuration-interop-v1

# captured-api-delivery-v2
