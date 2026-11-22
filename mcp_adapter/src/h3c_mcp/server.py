"""MCP transport/negotiation belongs to the SDK; this module binds Studio operations."""
import functools
import json
from typing import Any

import anyio
from mcp.server import MCPServer
from mcp.server.mcpserver.resources import Resource
from mcp.shared.exceptions import MCPError
from mcp_types import CallToolResult, TextContent, ToolAnnotations
from pydantic import PrivateAttr

from .guidance import Guidance
from .skills import SkillsExtension
from .tools import StudioTools
from .transport import StudioError


class HostResource(Resource):
    _guidance: Any = PrivateAttr()

    def __init__(self, guidance, **kwargs):
        super().__init__(**kwargs)
        self._guidance = guidance

    async def read(self):
        try:
            raw, mime = await anyio.to_thread.run_sync(self._guidance.read, str(self.uri))
            return raw.decode('utf-8') if mime.startswith('text/') or mime == 'application/json' else raw
        except StudioError as error:
            raise MCPError(-32602 if error.code == 'unknown_resource' else -32603, str(error)) from error


def _safe(function):
    @functools.wraps(function)
    def call(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (StudioError, OSError, ValueError) as error:
            detail = error.result() if isinstance(error, StudioError) else dict(code='local_or_input_error', message=str(error))
            return CallToolResult(is_error=True, content=[TextContent(type='text', text=json.dumps({'error': detail}))], structured_content={'error': detail})
    return call


def create_server(client, guidance=None, receipts=None, roots=None, state_dir=None):
    guidance = guidance or Guidance(client)
    catalog = guidance.catalog()
    server = MCPServer('h3-continuity', version='0.1.0', extensions=[SkillsExtension(guidance)],
        instructions='Read skill://h3-continuity-video/SKILL.md first (or h3_read_guidance). Use saved target identities. '
                     'Editable authored documents are JSON strings to preserve exact seeds. No browser synchronization. '
                     'Native results are proposals until explicitly saved/accepted; keep request keys and job receipts.')
    for entry in catalog['resources']:
        server.add_resource(HostResource(guidance, uri=entry['uri'], mime_type=entry.get('mime_type', 'application/octet-stream')))
    @server.resource('skill://{skill}/{+path}', mime_type='text/markdown')
    def skill_file(skill: str, path: str) -> str | bytes:
        raw, mime = guidance.read(f'skill://{skill}/{path}')
        return raw.decode() if mime.startswith('text/') else raw
    @server.resource('h3c://{section}/{+path}')
    def guide_file(section: str, path: str) -> str | bytes:
        raw, mime = guidance.read(f'h3c://{section}/{path}')
        return raw.decode() if mime.startswith('text/') else raw
    tools = StudioTools(client, guidance, state_dir)
    passive = {'h3_capabilities', 'h3_read_guidance', 'h3_list_projects', 'h3_get_project', 'h3_export_workflow', 'h3_plan_video'}
    for name in sorted(name for name in dir(tools) if name.startswith('h3_')):
        server.add_tool(_safe(getattr(tools, name)), name=name, structured_output=True,
                        annotations=ToolAnnotations(read_only_hint=name in passive, destructive_hint=name not in passive,
                                                    open_world_hint=True))
    return server
