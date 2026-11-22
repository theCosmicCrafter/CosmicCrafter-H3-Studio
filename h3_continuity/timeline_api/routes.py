"""Thin aiohttp routes mounted on the existing ComfyUI origin."""

import asyncio
import functools
import json
import logging
import tempfile
import threading
from pathlib import Path

from aiohttp import web

from .assets import MAX_UPLOAD_BYTES
from .contracts import APIError

PREFIX = "/h3c/api/v1"
LOGGER = logging.getLogger(__name__)


def _endpoint(handler):
    @functools.wraps(handler)
    async def wrapped(request):
        try:
            return await handler(request)
        except APIError as error:
            return web.json_response(error.response(), status=error.status)
        except (json.JSONDecodeError, UnicodeError, web.HTTPBadRequest, web.HTTPRequestEntityTooLarge, AssertionError):
            return web.json_response(APIError("invalid_request", "Request body is malformed or incomplete.").response(), status=400)
        except Exception:
            LOGGER.exception("Timeline API request failed")
            return web.json_response(APIError("internal_error", "Timeline API could not complete this request.", status=500).response(), status=500)
    return wrapped


async def _body(request):
    value = await request.json()
    if not isinstance(value, dict):
        raise APIError("invalid_request", "Request must be a JSON object.")
    return value


def register(instance, api):
    def route(method, path):
        def decorate(handler):
            async def initialized(request):
                facade = await asyncio.to_thread(api) if callable(api) else api
                return await handler(request, facade)
            return getattr(instance.routes, method)(PREFIX + path)(_endpoint(initialized))
        return decorate

    @route("get", "/capabilities")
    async def capabilities(request, api):
        return web.json_response(await asyncio.to_thread(api.capabilities))

    @route("post", "/assets")
    async def upload(request, api):
        fields, size, got_file = {}, 0, False
        multipart = await request.multipart()
        stream = await asyncio.to_thread(tempfile.TemporaryFile, dir=api.assets.staging)
        try:
            while part := await multipart.next():
                if part.name == "file":
                    if got_file:
                        raise APIError("invalid_request", "Upload must contain exactly one file.")
                    got_file = True
                    while chunk := await part.read_chunk(64 * 1024):
                        size += len(chunk)
                        if size > MAX_UPLOAD_BYTES:
                            raise APIError("invalid_asset", "Asset exceeds the upload limit.", status=422)
                        await asyncio.to_thread(stream.write, chunk)
                elif part.name in ("kind", "expected_sha256") and part.name not in fields:
                    content = await part.read_chunk(1024)
                    if len(content) > 256 or not part.at_eof():
                        raise APIError("invalid_request", "Upload field is too long.")
                    fields[part.name] = content.decode("utf-8")
                else:
                    raise APIError("invalid_request", "Upload contains an unknown or duplicate field.")
            if not got_file or not size:
                raise APIError("invalid_request", "Upload requires original file bytes.")
            await asyncio.to_thread(stream.seek, 0)
            result = await asyncio.to_thread(api.assets.ingest, stream, fields.get("kind"), fields.get("expected_sha256"))
            return web.json_response(result, status=201)
        finally:
            await asyncio.to_thread(stream.close)

    @route("get", "/assets/{asset_id}")
    async def asset(request, api):
        identifier = request.match_info["asset_id"]
        if request.query.get("download") == "1":
            path = await asyncio.to_thread(api.assets.path, identifier)
            return web.FileResponse(path)
        return web.json_response(await asyncio.to_thread(api.assets.get, identifier))

    @route("get", "/projects")
    async def projects(request, api):
        try:
            limit = int(request.query.get("limit", "50"))
        except ValueError:
            raise APIError("invalid_request", "Project page limit is invalid.", path="/limit") from None
        return web.json_response(await asyncio.to_thread(api.list_projects, request.query.get("cursor"), limit))

    @route("post", "/projects")
    async def create(request, api):
        body = await _body(request)
        result = await asyncio.to_thread(api.create_project, body, request.headers.get("Idempotency-Key"))
        return web.json_response(result, status=201)

    @route("get", "/projects/{project_id}")
    async def project(request, api):
        return web.json_response(await asyncio.to_thread(api.get_project, request.match_info["project_id"]))

    @route("put", "/projects/{project_id}")
    async def update(request, api):
        body = await _body(request)
        return web.json_response(await asyncio.to_thread(api.update_project, request.match_info["project_id"], body))

    @route("get", "/projects/{project_id}/workflow")
    async def workflow(request, api):
        return web.json_response(await asyncio.to_thread(api.workflow, request.match_info["project_id"], request.query.get("mode", "fork")))

    @route("post", "/projects/{project_id}/plan")
    async def plan(request, api):
        body = await _body(request)
        return web.json_response(await asyncio.to_thread(api.plan_project, request.match_info["project_id"], body))

    @route("post", "/projects/{project_id}/jobs")
    async def create_job(request, api):
        body = await _body(request)
        return web.json_response(await asyncio.to_thread(api.create_job, request.match_info["project_id"], body,
                                request.headers.get("Idempotency-Key")), status=202)

    @route("get", "/jobs/{job_id}")
    async def job(request, api):
        return web.json_response(await asyncio.to_thread(api.get_job, request.match_info["job_id"]))

    @route("post", "/jobs/{job_id}/resume")
    async def resume(request, api):
        return web.json_response(await api.resume_job(request.match_info["job_id"]))

    @route("post", "/jobs/{job_id}/cancel")
    async def cancel(request, api):
        return web.json_response(await api.cancel_job(request.match_info["job_id"]))

    @route("post", "/jobs/{job_id}/abandon")
    async def abandon(request, api):
        body = await _body(request)
        return web.json_response(await api.abandon_job(request.match_info["job_id"], body))

    @route("get", "/artifacts/{artifact_id}")
    async def artifact(request, api):
        if api.artifacts is None: raise APIError("artifacts_unavailable", "Artifacts are unavailable.",status=503)
        return web.json_response(await asyncio.to_thread(api.artifacts.get,request.match_info["artifact_id"]))

    @route("get", "/artifacts/{artifact_id}/download")
    async def artifact_download(request, api):
        if api.artifacts is None: raise APIError("artifacts_unavailable", "Artifacts are unavailable.",status=503)
        return web.FileResponse(await asyncio.to_thread(api.artifacts.path,request.match_info["artifact_id"]))

    @route("get", "/projects/{project_id}/takes")
    async def takes_list(request, api):
        return web.json_response(await asyncio.to_thread(api.list_takes,request.match_info["project_id"],request.query.get("box")))

    @route("post", "/projects/{project_id}/takes/use")
    async def takes_use(request, api):
        return web.json_response(await asyncio.to_thread(api.use_take,request.match_info["project_id"],await _body(request)))

    # Existing registration fixtures have no application; registration stays pure.
    if callable(api) and hasattr(instance, "app"):
        async def start(app):
            facade = await asyncio.to_thread(api)
            await asyncio.to_thread(facade.reconcile_mutations)
            if facade.jobs: await facade.jobs.start()
        async def close(app):
            facade = await asyncio.to_thread(api)
            if facade.jobs: await facade.jobs.close()
        instance.app.on_startup.append(start)
        instance.app.on_cleanup.append(close)


def runtime(instance):
    """Registration is pure; initialize storage once, off the serving event loop."""
    lock, ready = threading.Lock(), []

    def get():
        with lock:
            if not ready: ready.append(_runtime(instance))
            return ready[0]
    from . import service
    service._records_provider = lambda: get().records
    return get


def _runtime(instance):
    import folder_paths
    import nodes
    from .assets import Assets
    from .profiles import Profiles
    from .planning import Planner, native_status
    from .records import Records
    from .service import TimelineAPI
    from .jobs import Jobs
    from .native_queue import NativeQueue
    from .artifacts import Artifacts

    root = Path(folder_paths.get_system_user_directory("h3c_api"))
    records = Records(root)

    def node_info(kinds):
        # Inspect only this snapshot's nodes; other plugins' INPUT_TYPES may
        # have independent service side effects and are irrelevant here.
        result = {}
        for kind in kinds:
            cls = nodes.NODE_CLASS_MAPPINGS.get(kind)
            if cls is None: continue
            if hasattr(cls, "GET_NODE_INFO_V1"):
                result[kind] = cls.GET_NODE_INFO_V1()
            else:
                result[kind] = {"input": cls.INPUT_TYPES(), "output": list(cls.RETURN_TYPES)}
        return result

    profiles = Profiles(root / "profiles", node_info)
    assets = Assets(records, {"input": Path(folder_paths.get_input_directory()),
                             "output": Path(folder_paths.get_output_directory()), "user": root})
    planner = Planner(profiles, assets, native_status)
    artifacts = Artifacts(records, assets.roots["output"])
    jobs = Jobs(records, planner, NativeQueue(instance), artifacts)
    facade = TimelineAPI(records, profiles, assets, planner=planner, jobs=jobs, artifacts=artifacts)
    instance.h3_timeline_api = facade
    facade.captured_api_delivery = 2
    return facade

# static-configuration-interop-v1

# captured-api-delivery-v2
