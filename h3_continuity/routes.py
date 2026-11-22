"""HTTP routes: the H3 Timeline editor's status, and H3 Story's Write jobs and keys."""

import asyncio
import json

from aiohttp import web
from .timeline_api.contracts import APIError

from . import prompt_fields, reference_assets, saved_state, story_library, story_names, story_bible, story_job, story_keys, story_templates, refmods, audio_tracks, takes, stills, timeline_prepare as preparation

STATUS_ROUTE = "/h3c/timeline/status"
REGENERATION_ROUTE = "/h3c/timeline/regeneration"
TAKES_ROUTE = "/h3c/timeline/takes"
USE_TAKE_ROUTE = "/h3c/timeline/takes/use"
DELETE_TAKES_ROUTE = "/h3c/timeline/takes/delete"
RATE_TAKE_ROUTE = "/h3c/timeline/takes/rate"
PREPARE_ROUTE = "/h3c/timeline/prepare"
INSTRUCTIONS_ROUTE = "/h3c/timeline/instructions"
BIBLE_ROUTE = "/h3c/timeline/bible"
WRITE_ROUTE = "/h3c/story/write"
CHECK_ROUTE = "/h3c/story/check"
JOB_ROUTE = "/h3c/story/job"
CANCEL_ROUTE = "/h3c/story/cancel"
KEY_ROUTE = "/h3c/story/key"
KEYS_ROUTE = "/h3c/story/keys"
CURRENT_ROUTE = "/h3c/story/current"
TAKEN_ROUTE = "/h3c/story/taken"
TEMPLATES_ROUTE = "/h3c/story/templates"
STATE_ROUTE = "/h3c/state"


async def story_library_view(request):
    try:
        identity = request.query.get('id')
        if request.query.get('graph'):
            return web.json_response({'deleted': saved_state.deleted(request.query['graph'])})
        result = await asyncio.to_thread(story_library.load, identity) if identity else {
            'stories': await asyncio.to_thread(story_library.listing), 'names': await asyncio.to_thread(story_names.read)}
        return web.json_response(result)
    except (ValueError, OSError) as error:
        return web.json_response({'error': str(error)}, status=400)


async def story_library_save(request):
    try:
        body = await _object(request) or {}
        sequence = body.get('sequence')
        if body.get('prompt'):
            _, timeline_id, timeline = story_job.story_context.find_nodes(body['prompt'], body['story'])
            sequence = story_job.story_context.resolve_text(body['prompt'], timeline['inputs']['name'], 'Timeline name')
        result = await asyncio.to_thread(story_library.save, body['graph'], body['story'], body['workflow'], sequence, body.get('revision'), body.get('library_revision'), body.get('prompt'))
        return web.json_response(result)
    except story_library.WorkflowWiringConflict as error:
        return web.json_response({'error': str(error), 'code': error.code,
                                  'library_revision': error.library_revision}, status=409)
    except (ValueError, OSError, KeyError, TypeError, APIError) as error:
        return web.json_response({'error': str(error)}, status=400)


async def story_checkpoint_save(request):
    try:
        body = await _object(request) or {}
        if story_job.JOBS.busy('') or story_job.JOBS.comfy.busy():
            raise ValueError('Wait for Story writing and rendering to finish before saving a checkpoint.')
        result = await asyncio.to_thread(story_library.save_checkpoint, body['graph'], body['story'],
                                         body['workflow'], body['sequence'], body.get('name'))
        return web.json_response(result)
    except (ValueError, OSError, KeyError, TypeError, APIError) as error:
        return web.json_response({'error': str(error)}, status=400)


async def story_checkpoint_restore(request):
    try:
        body = await _object(request) or {}
        if story_job.JOBS.busy('') or story_job.JOBS.comfy.busy():
            raise ValueError('Wait for Story writing and rendering to finish before opening a checkpoint.')
        return web.json_response(await asyncio.to_thread(story_library.restore_checkpoint, body['id']))
    except (ValueError, OSError, KeyError, TypeError, APIError) as error:
        return web.json_response({'error': str(error)}, status=400)


async def story_duplicate(request):
    try:
        body = await _object(request) or {}
        if story_job.JOBS.busy('') or story_job.JOBS.comfy.busy():
            raise ValueError('Wait for Story writing and rendering to finish before duplicating a story.')
        return web.json_response(await asyncio.to_thread(story_library.duplicate, body['graph'], body['story'], body['workflow'],
                                                         body['sequence'], body.get('title'), body.get('timeline_json')))
    except (ValueError, OSError, KeyError, TypeError, APIError) as error:
        return web.json_response({'error': str(error)}, status=400)


async def prompt_field_view(request):
    try:
        return web.json_response(prompt_fields.request(await _object(request) or {}))
    except (ValueError, TypeError) as error:
        return web.json_response({'error': str(error)}, status=400)


async def story_library_rename(request):
    try:
        body = await _object(request) or {}
        return web.json_response({'names': await asyncio.to_thread(story_names.rename, body.get('key'), body.get('name', ''))})
    except (ValueError, OSError) as error:
        return web.json_response({'error': str(error)}, status=400)


async def story_library_delete(request):
    try:
        body = await _object(request) or {}
        if story_job.JOBS.busy('') or story_job.JOBS.comfy.busy():
            raise ValueError('Wait for Story writing and rendering to finish before deleting a story.')
        # Keep the queue-idle check and deletion in one event-loop turn; a new HTTP write/render cannot slip between them.
        result = story_library.delete(body['id'])
        return web.json_response(result)
    except (ValueError, OSError, KeyError, TypeError, APIError) as error:
        return web.json_response({'error': str(error)}, status=400)


async def state_view(request):
    try:
        query = request.query
        if query.get("kind") != "workflow":
            raise ValueError("Unknown H3 state type.")
        record = saved_state.read(query["kind"], query.get("graph", ""), query.get("node", ""))
        if query.get("revision") == str(record["revision"]):
            record = {"revision": record["revision"]}
        return web.json_response(record)
    except (ValueError, OSError) as error:
        return web.json_response({"error": f"Could not load saved H3 state: {error}"}, status=400)


async def state_save(request):
    try:
        body = await _object(request) or {}
        value, revision = body.get("value"), body.get("revision")
        if (body.get("kind") != "workflow" or type(revision) is not int or revision < 0
                or not isinstance(value, dict) or len(value) > 10000
                or any(not isinstance(v, (str, int, float, bool, type(None))) for v in value.values())):
            raise ValueError("Invalid H3 saved state.")
        record = saved_state.write(body["kind"], body.get("graph", ""), body.get("node", ""), value, revision)
        return web.json_response(record, status=409 if record.get("conflict") else 200)
    except (ValueError, OSError) as error:
        return web.json_response({"error": f"Could not save H3 state: {error}"}, status=400)


async def timeline_status(request):
    try:
        body = await request.json()
    except ValueError:
        return web.json_response({"ok": False, "error": "H3 Timeline: the status request is not JSON"})
    return web.json_response(await asyncio.to_thread(takes.status, body))


async def timeline_regeneration(request):
    from . import regeneration
    body = await _object(request)
    if body is None:
        return web.json_response({"ok": False, "error": "H3 Timeline: regeneration requires a JSON object"}, status=400)
    return web.json_response(await asyncio.to_thread(regeneration.request, body))


async def _takes_request(request, action):
    body = await _object(request)
    if body is None:
        return web.json_response({"ok": False, "error": takes.REQUEST})
    return web.json_response(await asyncio.to_thread(action, body))


async def timeline_takes(request):
    return await _takes_request(request, takes.listing)


async def timeline_use_take(request):
    return await _takes_request(request, takes.use)


async def timeline_delete_takes(request):
    return await _takes_request(request, takes.delete)


async def timeline_rate_take(request):
    return await _takes_request(request, takes.rate)


async def audio_info(request):
    try:
        body = await _object(request) or {}
        info = await asyncio.to_thread(audio_tracks.metadata, body.get("file"))
        return web.json_response(info)
    except (ValueError, OSError) as error:
        return web.json_response({"error": str(error)}, status=400)


async def still_import(request):
    try:
        if request.content_type != "multipart/form-data":
            raise ValueError("H3 Timeline: the image import must be multipart/form-data")
        reader = await request.multipart()
        field = await reader.next()
        if field is None or field.name != "image":
            raise ValueError("H3 Timeline: the import needs an image field")
        data = bytes(await field.read())
        file = await asyncio.to_thread(stills.import_image, data)
        return web.json_response({"ok": True, "file": file})
    except (ValueError, OSError) as error:
        return web.json_response({"ok": False, "error": str(error)}, status=400)


async def still_pin(request):
    try:
        body = await _object(request) or {}
        return web.json_response({'ok': True, **stills.pin_image(body['file'])})
    except (ValueError, OSError, KeyError, TypeError) as error:
        return web.json_response({'ok': False, 'error': str(error)})


async def still_sources(request):
    result = await asyncio.to_thread(stills.sources, await _object(request))
    return web.json_response(result, status=200 if result['ok'] else 400)


async def still_result(request):
    result = await asyncio.to_thread(stills.result, await _object(request))
    return web.json_response(result, status=200 if result['ok'] else 400)


async def still_prepare(request):
    result = await asyncio.to_thread(stills.prepare, await _object(request))
    return web.json_response(result, status=200 if result['ok'] else 400)


async def reference_catalog(request):
    try:
        body = await _object(request)
        document = json.loads(body['timeline'])
        assets = await asyncio.to_thread(reference_assets.catalog, document, body)
        return web.json_response({'ok': True, 'assets': assets})
    except (ValueError, KeyError, TypeError) as error:
        return web.json_response({'ok': False, 'error': str(error)}, status=400)


async def reference_approve(request):
    try:
        body = await _object(request)
        timeline = await asyncio.to_thread(reference_assets.approve, json.loads(body['timeline']),
                                          body['asset_key'], body['candidate_id'], body['expected_revision'],body)
        return web.json_response({'ok': True, 'timeline': timeline})
    except (ValueError, KeyError, TypeError, OSError) as error:
        return web.json_response({'ok': False, 'error': str(error)}, status=400)


async def reference_prepare(request):
    result = await asyncio.to_thread(reference_assets.prepare, await _object(request))
    return web.json_response(result, status=200 if result['ok'] else 400)


async def reference_result(request):
    result = await asyncio.to_thread(reference_assets.result, await _object(request))
    return web.json_response(result, status=200 if result['ok'] else 400)


async def image_description(request):
    from . import image_descriptions
    try:
        body = await _object(request)
        if body is None:
            raise ValueError('The image description request must be a JSON object.')
        return web.json_response(await image_descriptions.handle(body))
    except (ValueError, OSError, TypeError, KeyError) as error:
        return web.json_response({'ok': False, 'error': str(error)}, status=400)


async def timeline_prepare(request):
    body = await _object(request)
    result = await asyncio.to_thread(preparation.prepare, body)
    return web.json_response(result, status=200 if result["ok"] else 400)


async def timeline_bible(request):
    body = await _object(request)
    result = await asyncio.to_thread(story_bible.handle, body)
    return web.json_response(result, status=200 if result["ok"] else 400)


async def timeline_instructions(request):
    return web.json_response(await asyncio.to_thread(preparation.instructions))


async def refmod_library(request):
    try:
        return web.json_response({"entries": refmods.library()})
    except (ValueError, OSError) as error:
        return web.json_response({"entries": [], "error": str(error)}, status=400)


async def refmod_thumbnail(request):
    try:
        pack, _ = refmods.backend()
        path = refmods.thumbnail(pack._find_mod_path(request.query.get("name", "")))
        if path:
            return web.FileResponse(path)
    except (ValueError, OSError):
        pass
    raise web.HTTPNotFound()


async def _object(request):
    try:
        body = await request.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


async def story_write(request):
    body = await _object(request)
    if body is None:
        return web.json_response({"ok": False, "error": "The Write request is not a JSON object."})
    return web.json_response(story_job.JOBS.start(body))


async def story_check_start(request):
    body = await _object(request)
    if body is None:
        return web.json_response({"ok": False, "error": "The check request is not a JSON object."})
    return web.json_response(story_job.JOBS.start_check(body))


async def still_prompt_prepare(request):
    body = await _object(request)
    if body is None:
        return web.json_response({'ok': False, 'error': 'The still prompt request is not a JSON object.'})
    return web.json_response(story_job.JOBS.start_still_prompts(body))


async def still_prompt_instructions(request):
    return web.json_response({'ok': True, 'instructions': story_job.still_prompt_preparation.DEFAULT_INSTRUCTIONS})


async def story_job_view(request):
    query = request.query
    return web.json_response(story_job.JOBS.poll(query.get("id", ""), query.get("graph", ""), query.get("story", "")))


async def story_cancel(request):
    body = await _object(request) or {}
    return web.json_response(story_job.JOBS.cancel(str(body.get("job", ""))))


async def story_current(request):
    query = request.query
    return web.json_response(story_job.JOBS.current(query.get("client", ""), query.get("graph", ""),
                                                    query.get("story", ""), query.get("recover") == "true"))


async def story_taken(request):
    body = await _object(request) or {}
    return web.json_response(story_job.JOBS.take(str(body.get("job", ""))))


async def story_key(request):
    body = await _object(request)
    if body is None:
        return web.json_response({"ok": False, "error": "The key request is not a JSON object."})
    try:
        hosts = story_keys.save(str(body.get("base_url") or ""), str(body.get("key") or ""))
    except ValueError as error:
        return web.json_response({"ok": False, "error": str(error)})
    return web.json_response({"ok": True, "hosts": hosts})


async def story_hosts(request):
    return web.json_response({"ok": True, "hosts": story_keys.hosts()})


async def story_templates_view(request):
    return web.json_response(await asyncio.to_thread(story_templates.listing))


async def generation_export(request):
    from . import generations
    return await _generation_call(request,lambda body: {'ok':True,'archive':generations.export_generation(body)})

async def generation_preflight(request):
    from . import generations
    return await _generation_call(request,lambda body: generations.preflight_generation(body['archive']))

async def generation_import(request):
    from . import generations
    return await _generation_call(request,lambda body: generations.import_generation(body['archive'],body['request_id'],body.get('renderer')))

async def generation_start(request):
    from . import generations
    return await _generation_call(request, generations.start)


async def generation_history(request):
    from . import generations
    return await _generation_call(request, generations.history)


async def _generation_call(request,call):
    try:
        body=await _object(request)
        if body is None:raise ValueError('Generation request must be a JSON object')
        return web.json_response(await asyncio.to_thread(call,body))
    except (ValueError,OSError,KeyError,TypeError) as error:
        return web.json_response({'ok':False,'error':str(error)},status=400)


def register():
    """Adds the routes to the running ComfyUI server; returns False when there is none."""
    try:
        from server import PromptServer
    except ImportError:
        return False
    instance = getattr(PromptServer, "instance", None)
    if instance is None:
        return False
    routes = instance.routes
    story_job.JOBS.updated = lambda job: instance.send_sync("h3c-story", {"job": job.id}, job.client or None)
    routes.post(STATUS_ROUTE)(timeline_status)
    routes.post('/h3c/generations/start')(generation_start)
    routes.post('/h3c/generations/history')(generation_history)
    routes.post(REGENERATION_ROUTE)(timeline_regeneration)
    routes.post(TAKES_ROUTE)(timeline_takes)
    routes.post(USE_TAKE_ROUTE)(timeline_use_take)
    routes.post(DELETE_TAKES_ROUTE)(timeline_delete_takes)
    routes.post(RATE_TAKE_ROUTE)(timeline_rate_take)
    routes.post(PREPARE_ROUTE)(timeline_prepare)
    routes.get(INSTRUCTIONS_ROUTE)(timeline_instructions)
    routes.post(BIBLE_ROUTE)(timeline_bible)
    routes.post("/h3c/audio/info")(audio_info)
    routes.post("/h3c/images/description")(image_description)
    routes.post('/h3c/reference-assets/approve')(reference_approve)
    routes.post('/h3c/reference-assets/catalog')(reference_catalog)
    routes.post('/h3c/reference-assets/prepare')(reference_prepare)
    routes.post('/h3c/reference-assets/result')(reference_result)
    routes.post("/h3c/stills/import")(still_import)
    routes.post("/h3c/stills/pin")(still_pin)
    routes.post("/h3c/generations/export")(generation_export)
    routes.post("/h3c/generations/preflight")(generation_preflight)
    routes.post("/h3c/generations/import")(generation_import)
    routes.post("/h3c/stills/sources")(still_sources)
    routes.post("/h3c/stills/prepare")(still_prepare)
    routes.post("/h3c/stills/result")(still_result)
    routes.get("/h3c/refmods")(refmod_library)
    routes.get("/h3c/refmods/thumbnail")(refmod_thumbnail)
    routes.post(WRITE_ROUTE)(story_write)
    routes.post('/h3c/still-prompts/prepare')(still_prompt_prepare)
    routes.post('/h3c/still-prompts/instructions')(still_prompt_instructions)
    routes.post(CHECK_ROUTE)(story_check_start)
    routes.get(JOB_ROUTE)(story_job_view)
    routes.post(CANCEL_ROUTE)(story_cancel)
    routes.post(KEY_ROUTE)(story_key)
    routes.get(KEYS_ROUTE)(story_hosts)
    routes.get(CURRENT_ROUTE)(story_current)
    routes.post(TAKEN_ROUTE)(story_taken)
    routes.get(TEMPLATES_ROUTE)(story_templates_view)
    routes.get(STATE_ROUTE)(state_view)
    routes.post(STATE_ROUTE)(state_save)
    routes.get('/h3c/stories')(story_library_view)
    routes.post('/h3c/stories')(story_library_save)
    routes.post('/h3c/stories/checkpoint')(story_checkpoint_save)
    routes.post('/h3c/stories/restore')(story_checkpoint_restore)
    routes.post('/h3c/stories/duplicate')(story_duplicate)
    routes.post('/h3c/prompts/fields')(prompt_field_view)
    routes.post('/h3c/stories/delete')(story_library_delete)
    routes.post('/h3c/stories/rename')(story_library_rename)
    from .timeline_api import routes as project_routes
    api = project_routes.runtime(instance)
    project_routes.register(instance, api)
    instance.h3c_timeline_api = api
    from .agent_api import routes as agent_routes
    agent_routes.register(instance)
    return True
