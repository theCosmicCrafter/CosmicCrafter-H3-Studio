"""Durable sequential attempts; missing native evidence never causes a resubmit."""

import asyncio
import copy
import logging
import secrets
import uuid
from datetime import datetime, timezone

from .contracts import APIError, digest, validate

LOGGER = logging.getLogger(__name__)
IN_FLIGHT = ("submitting", "acknowledged")


def public_job(job, blocked_by=None):
    result = {key: copy.deepcopy(job[key]) for key in ("api_version", "id", "project_id", "revision", "profile_sha256",
        "plan_sha256", "selection", "state", "artifacts", "error", "created", "progress", "poll_url")}
    result["attempts"] = [{key: copy.deepcopy(attempt[key]) for key in ("id", "unit_id", "state", "prompt_id") if key in attempt}
                       for attempt in job["attempts"]]
    result["progress"]["current"] = next((attempt["unit_id"] for attempt in job["attempts"] if attempt["state"] != "verified"), None)
    result["blocked_by"] = copy.deepcopy(blocked_by)
    return result


def _in_flight(job):
    return next((attempt for attempt in job["attempts"] if attempt["state"] in IN_FLIGHT), None)


class Jobs:
    async def cancel(self, job_id):
        async with self._lock:
            await self._record(self.records.request_job_cancel, job_id)
            self._wake.set()
            return await self._record(self.get, job_id)

    async def _cancel_tick(self, job):
        attempt = _in_flight(job)
        if attempt:
            evidence = await self._record(self.native.evidence, attempt["prompt_id"], attempt)
            if evidence["state"] in ("running", "queued"):
                removed = await self._record(self.native.cancel, attempt["prompt_id"])
                if not removed:
                    return False
            elif evidence["state"] in ("failed", "succeeded"):
                # Retain the conclusive native outcome on the attempt before closing.
                await self._record(self.records.save_attempt, job["id"], attempt["unit_id"], {"state": evidence["state"], "evidence": evidence})
            elif evidence["state"] == "conflict" or await self._record(self._owner, attempt) not in ("self", "gone"):
                # Absence from this process proves nothing while the owner may be alive elsewhere.
                if job["state"] != "needs_reconciliation" or (job.get("error") or {}).get("code") != "cancel_uncertain":
                    await self._record(self.records.set_job_state, job["id"], "needs_reconciliation", error={"code": "cancel_uncertain", "message": "Owned attempt cannot be attributed; inspect the host. No next unit will submit."})
                return False
        await self._record(self.records.set_job_state, job["id"], "failed", error={"code": "cancelled", "message": "Cancelled by the human; completed native segments and attempt evidence are preserved."})
        return True

    def __init__(self, records, planner, native, artifacts):
        self.records, self.planner, self.native, self.artifacts = records, planner, native, artifacts
        self._lock, self._wake, self._loop = asyncio.Lock(), asyncio.Event(), None
        self._closing = False
        self._held_notice, self._released_notice = None, set()

    def _fault(self, point):
        """Crash-window seam used by recovery tests."""

    def accept(self, project_id, body, key):
        existing = self.records.lookup_key("job_create:" + project_id, key, digest(body))
        if existing is not None: return public_job(existing)
        body = validate("job_create", body)
        project = self.records.get_project(project_id)
        self.records._check_edit(project, body["expected_revision"])
        plan = self.planner.plan(project, body["selection"])
        return public_job(self.records.accept_job(project_id, body, plan, key))

    def get(self, job_id):
        job = self.records.get_job(job_id)
        blocked_by = None
        if job["state"] not in ("succeeded", "failed", "needs_reconciliation"):
            jobs = self.records.recoverable()
            head = self._head(jobs)
            order = [item["id"] for item in jobs]
            if (head is not None and head["state"] == "needs_reconciliation" and job_id in order
                    and order.index(job_id) > order.index(head["id"])):
                blocked_by = self._blocker(head)
        return public_job(job, blocked_by)

    def queue_status(self):
        """Held-job summary for capabilities: what bars admission, and how many jobs wait."""
        jobs = self.records.recoverable()
        head = self._head(jobs)
        blocking = head if head is not None and head["state"] == "needs_reconciliation" else None
        waiting = len(jobs) - 1 - [item["id"] for item in jobs].index(blocking["id"]) if blocking else 0
        return {"held": sum(item["state"] == "needs_reconciliation" for item in jobs),
                "blocked_by": self._blocker(blocking) if blocking else None, "waiting": waiting}

    @staticmethod
    def _blocker(job):
        return {"job_id": job["id"], "project_id": job["project_id"], "state": job["state"],
                "error_code": (job.get("error") or {}).get("code")}

    def _owner(self, attempt):
        owner = getattr(self.native, "owner", None)
        return owner(attempt) if owner is not None else "unknown"

    def _released(self, job):
        """Why a held job no longer bars later API units, or None while it must.

        The barrier exists because an ambiguous older attempt may still be running
        on the single GPU. It is lifted only when that is provably impossible: no
        native attempt is in flight, or the attempt is absent from this process's
        queue and history while its owner is this process ("self": it was only ever
        queued here) or a process that has exited ("gone"). The held job itself
        keeps its state, project lease and evidence and is never resubmitted."""
        attempt = _in_flight(job)
        if attempt is None:
            return "no_native_attempt"
        if self.native.evidence(attempt["prompt_id"], attempt)["state"] != "unknown":
            return None
        owner = self._owner(attempt)
        return "owner_" + owner if owner in ("self", "gone") else None

    def _head(self, jobs):
        """First job that governs admission; released held jobs are stepped over."""
        for job in jobs:
            if job["state"] == "needs_reconciliation" and self._released(job) is not None:
                continue
            return job
        return None

    async def _record(self, method, *args, **kwargs):
        return await asyncio.to_thread(method, *args, **kwargs)

    async def _reconcile(self, job, attempt):
        evidence = await self._record(self.native.evidence, attempt["prompt_id"], attempt)
        state = evidence["state"]
        if state in ("unknown", "conflict"):
            await self._record(self.records.set_job_state, job["id"], "needs_reconciliation", error={
                "code": "native_evidence_uncertain", "message": "Native execution cannot be attributed conclusively; resume checks evidence without resubmitting."})
            return False
        if state == "failed":
            await self._record(self.records.save_attempt, job["id"], attempt["unit_id"], {"state": "failed", "evidence": evidence})
            await self._record(self.records.set_job_state, job["id"], "failed", error={
                "code": "native_execution_failed", "message": "Native execution failed or was interrupted."})
            return True
        if state == "succeeded":
            await self._record(self.records.save_attempt, job["id"], attempt["unit_id"], {"state": "succeeded", "evidence": evidence})
            await self._record(self.records.set_job_state, job["id"], "running")
            self._fault("after_terminal")
            return True
        if attempt["state"] == "submitting":
            await self._record(self.records.save_attempt, job["id"], attempt["unit_id"], {"state": "acknowledged", "evidence": evidence})
        await self._record(self.records.set_job_state, job["id"], "running" if state == "running" else "queued")
        return False

    async def _settle(self, jobs, head):
        """Persist terminal native evidence for in-flight attempts the main step will not reach.

        Native history lives only in this process's memory. A held job, or one
        behind a held head, previously never had its outcome read, so a restart
        turned a known failure into "unknown". Reconciling only ever records
        evidence and never submits."""
        for job in jobs:
            if job.get("cancel_requested") or (job is head and job["state"] != "needs_reconciliation"):
                continue
            attempt = _in_flight(job)
            if attempt is None:
                continue
            evidence = await self._record(self.native.evidence, attempt["prompt_id"], attempt)
            if evidence["state"] in ("failed", "succeeded"):
                LOGGER.info("Timeline job %s: recording %s native evidence for prompt %s", job["id"], evidence["state"], attempt["prompt_id"])
                await self._reconcile(job, attempt)
                return True
        return False

    def _notice(self, jobs, head):
        """Warn once per held head and waiting count, never on every tick."""
        for job in jobs:
            if job["state"] == "needs_reconciliation" and job["id"] not in self._released_notice:
                reason = self._released(job)
                if reason is not None:
                    self._released_notice.add(job["id"])
                    LOGGER.warning("Timeline job %s stays needs_reconciliation but no longer bars later jobs (%s).", job["id"], reason)
        if head is None or head["state"] != "needs_reconciliation":
            if self._held_notice is not None:
                LOGGER.info("Timeline job admission barrier cleared (was job %s).", self._held_notice[0])
            self._held_notice = None
            return
        waiting = len(jobs) - 1 - [item["id"] for item in jobs].index(head["id"])
        if self._held_notice != (head["id"], waiting):
            self._held_notice = (head["id"], waiting)
            attempt = _in_flight(head)
            LOGGER.warning("Timeline job %s (project %s) is needs_reconciliation (%s, prompt %s) and blocks %d later job(s). "
                           "Resume it if native evidence returns, or close it with POST /h3c/api/v1/jobs/%s/abandon.",
                           head["id"], head["project_id"], (head.get("error") or {}).get("code"),
                           attempt["prompt_id"] if attempt else None, waiting, head["id"])

    async def recover(self):
        async with self._lock:
            for job in await self._record(self.records.recoverable):
                attempt = _in_flight(job)
                if attempt: await self._reconcile(job, attempt)

    async def resume(self, job_id):
        async with self._lock:
            job = await self._record(self.records.get_job, job_id)
            if job["state"] not in ("succeeded", "failed"):
                attempt = _in_flight(job)
                if attempt: await self._reconcile(job, attempt)
                elif job["state"] == "needs_reconciliation":
                    # Recheck persisted media explicitly; never repeat a native submission.
                    await self._record(self.records.set_job_state, job["id"], "running")
            self._wake.set()
            return await self._record(self.get, job_id)

    async def abandon(self, job_id, body):
        """Human-attested close of a held job whose native outcome cannot be attributed.

        A state change only: attempts and their evidence stay as recorded and
        nothing is resubmitted. Refused while the prompt is visible in this
        process's queue, while conclusive evidence exists (resume instead), or while
        the owning process is provably alive elsewhere."""
        body = validate("job_abandon", body)
        reason, confirm = body["reason"].strip(), body["confirm_prompt_id"]
        if not reason:
            raise APIError("invalid_request", "Give the reason for closing this job.", path="/reason")
        async with self._lock:
            job = await self._record(self.records.get_job, job_id)
            held = next((attempt for attempt in job["attempts"] if attempt["state"] != "verified"), None)
            prompt_id = held.get("prompt_id") if held else None
            error = job.get("error") or {}
            if (job["state"] == "failed" and error.get("code") == "abandoned_by_human"
                    and error.get("prompt_id") == confirm and error.get("reason") == reason):
                return await self._record(self.get, job_id)  # Retry of a completed close.
            if job["state"] != "needs_reconciliation":
                raise APIError("job_not_held", "Only a needs_reconciliation job can be abandoned.", status=409,
                               details={"state": job["state"]})
            if confirm != prompt_id:
                raise APIError("prompt_mismatch", "confirm_prompt_id does not match the held attempt.", status=409,
                               details={"held_prompt_id": prompt_id})
            owner = None
            if prompt_id is not None:
                if await self._record(self.native.active, prompt_id):
                    raise APIError("prompt_active", "The held prompt is running or queued in ComfyUI.", status=409,
                                   details={"prompt_id": prompt_id})
                if held["state"] in IN_FLIGHT:
                    evidence = await self._record(self.native.evidence, prompt_id, held)
                    if evidence["state"] in ("failed", "succeeded"):
                        raise APIError("native_evidence_available", "Native evidence is conclusive; resume the job instead.",
                                       status=409, details={"prompt_id": prompt_id, "native_state": evidence["state"]})
                owner = await self._record(self._owner, held)
                if owner == "alive":
                    raise APIError("owner_alive", "The ComfyUI process that submitted this prompt is still running.",
                                   status=409, details={"prompt_id": prompt_id})
            await self._record(self.records.set_job_state, job_id, "failed", expected="needs_reconciliation", error={
                "code": "abandoned_by_human", "reason": reason, "prompt_id": prompt_id, "owner": owner,
                "held_error": copy.deepcopy(job.get("error")), "abandoned": datetime.now(timezone.utc).isoformat(),
                "message": "Closed by a human: " + reason + " Attempt evidence is preserved; nothing was resubmitted."})
            LOGGER.warning("Timeline job %s abandoned by a human (prompt %s, owner %s): %s", job_id, prompt_id, owner, reason)
            self._wake.set()
            return await self._record(self.get, job_id)

    async def tick(self):
        async with self._lock:
            jobs = await self._record(self.records.recoverable)
            if not jobs: return self._notice(jobs, None) or False
            head = await self._record(self._head, jobs)
            if await self._settle(jobs, head): return True
            for job in jobs:
                # A cancel that cannot touch a running prompt needs no turn at the head.
                if job.get("cancel_requested") and job is not head and await self._record(self._released, job) is not None:
                    return await self._cancel_tick(job)
            await self._record(self._notice, jobs, head)
            if head is None: return False
            # An ambiguous older attempt may still be running. It remains the
            # admission barrier for other API units without blocking native work.
            job, project = head, head["project_snapshot"]
            if job.get("cancel_requested"):
                return await self._cancel_tick(job)
            if job["state"] == "needs_reconciliation": return False
            attempt = next((item for item in job["attempts"] if item["state"] != "verified"), None)
            try:
                if attempt is None:
                    if self.artifacts is None: raise APIError("verification_unavailable", "Artifact verification is unavailable.", status=503)
                    artifacts = await self._record(self.artifacts.finalize, project, job, self.native)
                    self._fault("after_artifacts")
                    await self._record(self.records.finish_job, job["id"], artifacts)
                    return True
                unit_id = attempt["unit_id"]
                if attempt["state"] in IN_FLIGHT:
                    progressed = await self._reconcile(job, attempt)
                    job = await self._record(self.records.get_job, job["id"])
                    if job["state"] == "failed": return True
                    attempt = next(item for item in job["attempts"] if item["unit_id"] == unit_id)
                    if attempt["state"] != "succeeded": return progressed
                if attempt["state"] == "succeeded":
                    if self.artifacts is None: raise APIError("verification_unavailable", "Artifact verification is unavailable.", status=503)
                    artifact = await self._record(self.artifacts.verify_unit, project, job, attempt)
                    await self._record(self.records.save_attempt, job["id"], unit_id, {"state": "verified", "artifact": artifact})
                    await self._record(self.records.set_job_state, job["id"], "running")
                    return True
                if attempt["state"] != "pending": return False
                profile = await self._record(self.planner.profiles.get, project["profile"], project["profile_sha256"])
                await self._record(self.planner.assets.resolve, project.get("assets", []), project["authored"]["timeline"], profile)
                graph = await self._record(self.planner.selected_graph, project, attempt["unit"])
                pid, token = str(uuid.uuid4()), secrets.token_hex(32)
                owner = {"project_id": project["id"], "job_id": job["id"], "unit_id": unit_id, "attempt_id": attempt["id"],
                         "revision": job["revision"], "profile_sha256": job["profile_sha256"], "owner_token": token}
                if project.get("profile_snapshot", {}).get("captured_api") == 2:
                    owner["captured_api"] = 2
                    owner["execution_outputs"] = copy.deepcopy(project["profile_snapshot"]["workflow"]["execution_outputs"])
                validated = await self.native.validate(graph, pid, owner)
                selected_outputs = project.get("profile_snapshot", {}).get("workflow", {}).get("execution_outputs")
                if selected_outputs is not None:
                    if (not selected_outputs or any(n not in validated["outputs_to_execute"] for n in selected_outputs)):
                        raise APIError("invalid_native_graph", "Captured delivery output was not validated.")
                    validated["outputs_to_execute"] = copy.deepcopy(selected_outputs)
                snapshot = await self._record(self.records.snapshot_json, "execution", validated)
                self._fault("before_intent")
                intent = {"state": "submitting", "prompt_id": pid, "owner_token": token, "metadata": owner,
                          "graph_sha256": validated["graph_sha256"], "graph_snapshot": snapshot}
                if getattr(self.native, "process", None) is not None:
                    # Lets a later process prove this attempt's owner has exited.
                    intent["owner_process"] = copy.deepcopy(self.native.process)
                await self._record(self.records.save_attempt, job["id"], unit_id, intent)
                self._fault("after_intent")
                ack = await self.native.submit(validated)
                self._fault("after_enqueue")
                await self._record(self.records.save_attempt, job["id"], unit_id, {"state": "acknowledged", "ack": ack})
                await self._record(self.records.set_job_state, job["id"], "queued")
                self._fault("after_ack")
                return True
            except Exception as error:
                LOGGER.exception("Timeline job step failed: %s", job["id"])
                current = await self._record(self.records.get_job, job["id"])
                current_attempt = next((item for item in current["attempts"] if item["state"] != "verified"), None)
                pending = current_attempt is not None and current_attempt["state"] == "pending"
                public = {"code": error.code if isinstance(error, APIError) else "job_step_failed",
                          "message": str(error) if isinstance(error, APIError) else "Timeline job could not complete this step."}
                if pending:
                    await self._record(self.records.save_attempt, job["id"], current_attempt["unit_id"], {
                        "state": "failed", "diagnostics": getattr(error, "diagnostics", {})})
                await self._record(self.records.set_job_state, job["id"], "failed" if pending else "needs_reconciliation", error=public)
                return pending

    async def start(self):
        if self._loop is not None: return
        self._closing = False
        await self.recover()
        self._loop = asyncio.create_task(self._run(), name="h3c-api-jobs")

    async def _run(self):
        while not self._closing:
            try: progressed = await self.tick()
            except Exception:
                LOGGER.exception("Timeline job polling failed")
                progressed = False
            if not progressed:
                self._wake.clear()
                try: await asyncio.wait_for(self._wake.wait(), timeout=1)
                except asyncio.TimeoutError: pass

    async def close(self):
        self._closing = True
        self._wake.set()
        if self._loop is not None:
            await self._loop
            self._loop = None

# static-configuration-interop-v1

# captured-api-delivery-v2

# captured-api-active-outputs-v1
