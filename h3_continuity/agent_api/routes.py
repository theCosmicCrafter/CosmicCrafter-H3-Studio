"""Small agent support routes on the existing ComfyUI security boundary."""
import asyncio

from aiohttp import web

from . import resources
from ..timeline_api.contracts import APIError


def register(instance):
    from . import projects
    @instance.routes.get('/h3c/agent/projects')
    async def listing(request):
        try:
            return web.json_response(await asyncio.to_thread(projects.list_projects, request.query.get('cursor'), int(request.query.get('limit', '50'))))
        except (ValueError, OSError) as error:
            return _error(error)

    for action in ('read', 'save', 'register', 'context'):
        def endpoint(action):
            async def handler(request):
                try:
                    body = await request.json()
                    if not isinstance(body, dict):
                        raise ValueError('Agent project body must be an object')
                    return web.json_response(await asyncio.to_thread(getattr(projects, action), **body))
                except (ValueError, OSError, KeyError, TypeError) as error:
                    return _error(error)
            return handler
        instance.routes.post('/h3c/agent/projects/' + action)(endpoint(action))
    @instance.routes.get('/h3c/agent/catalog')
    async def catalog(request):
        try:
            return web.json_response(await asyncio.to_thread(resources.catalog))
        except (ValueError, OSError) as error:
            return web.json_response({'ok': False, 'error': {'code': 'agent_catalog', 'message': str(error)}}, status=400)

    @instance.routes.get('/h3c/agent/resource')
    async def resource(request):
        try:
            raw, mime = await asyncio.to_thread(resources.read, request.query.get('uri'), request.query.get('digest'))
            return web.Response(body=raw, content_type=mime)
        except resources.ResourceChanged as error:
            return web.json_response({'ok': False, 'error': {'code': 'resource_changed', 'message': str(error)}}, status=409)
        except (ValueError, OSError) as error:
            return web.json_response({'ok': False, 'error': {'code': 'resource_not_found', 'message': str(error)}}, status=404)


def _error(error):
    if isinstance(error, APIError):
        return web.json_response(error.response(), status=error.status)
    return web.json_response({'ok': False, 'error': {'code': 'agent_request', 'message': str(error)}}, status=400)
