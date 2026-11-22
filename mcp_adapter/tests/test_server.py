import json
import sys
import tempfile
import unittest
from pathlib import Path

from mcp import Client
from mcp.client.extension import ClientExtension
from mcp.client.stdio import StdioServerParameters
import mcp_types as types
from pydantic import BaseModel

from tests.support import FixtureStudio
from h3c_mcp.transport import StudioClient
try:
    from h3c_mcp.server import create_server
except ImportError:
    create_server = None


class SkillClient(ClientExtension):
    identifier = 'io.modelcontextprotocol/skills'


class SkillReply(BaseModel):
    skills: list = []
    skill: dict = {}
    resultType: str | None = None
    ttlMs: int | None = None
    cacheScope: str | None = None


class ServerTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertIsNotNone(create_server, 'MCP server must use the real SDK')
        self.host = FixtureStudio()
        self.addCleanup(self.host.close)
        self.uri, self.raw = self.host.guidance()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.http = StudioClient(self.host.url, roots=[Path(self.directory.name)])
        self.addCleanup(self.http.close)

    def server(self):
        return create_server(self.http, state_dir=Path(self.directory.name))

    async def test_real_sdk_skills_and_resource_bytes(self):
        from h3c_mcp.skills import GetSkillParams
        async with Client(self.server(), extensions=[SkillClient()]) as client:
            self.assertEqual(client.server_capabilities.extensions['io.modelcontextprotocol/skills'], {})
            reply = await client.session.send_request(types.Request(method='skills/list', params=types.PaginatedRequestParams()), SkillReply)
            self.assertEqual(reply.skills[0]['uri'], self.uri)
            self.assertEqual(reply.resultType, 'complete')
            self.assertEqual(reply.cacheScope, 'private')
            one = await client.session.send_request(types.Request(method='skills/get', params=GetSkillParams(uri=self.uri)), SkillReply)
            self.assertEqual(one.skill['frontmatter']['name'], 'h3-continuity-video')
            content = (await client.read_resource(self.uri)).contents[0]
            self.assertEqual(content.text.encode(), self.raw)

    async def test_unknown_skill_and_unadvertised_directory_are_rejected(self):
        from h3c_mcp.skills import GetSkillParams
        from mcp.shared.exceptions import MCPError
        async with Client(self.server(), extensions=[SkillClient()]) as client:
            with self.assertRaises(MCPError) as raised:
                await client.session.send_request(types.Request(method='skills/get', params=GetSkillParams(uri='skill://missing/SKILL.md')), SkillReply)
            self.assertEqual(raised.exception.code, -32602)
            with self.assertRaises(MCPError):
                await client.session.send_request(types.Request(method='resources/directory/read', params=GetSkillParams(uri='skill://h3-continuity-video')), SkillReply)

    async def test_tools_work_without_client_skill_extension(self):
        async with Client(self.server()) as client:
            names = {tool.name for tool in (await client.list_tools()).tools}
            self.assertIn('h3_save_project', names)
            self.assertNotIn('http_request', names)
            result = await client.call_tool('h3_capabilities', {})
            self.assertFalse(result.is_error)
            self.assertEqual(result.structured_content['agent_api_version'], 1)

    async def test_managed_document_string_preserves_seed_and_conflict(self):
        project = dict(id='p1', revision=1, profile='fixed', profile_sha256='a'*64,
                       timeline=dict(boxes=[dict(id='a', seed=18446744073709551615)]), consumer={'opaque': 'keep'})
        self.host.routes[('GET', '/h3c/api/v1/projects/p1')] = (200, project)
        self.host.routes[('PUT', '/h3c/api/v1/projects/p1')] = (409, {'error': {'code': 'revision_conflict', 'message': 'Changed', 'details': {'current_revision': 2}}})
        async with Client(self.server()) as client:
            result = await client.call_tool('h3_get_project', {'target': {'kind': 'managed', 'id': 'p1'}})
            self.assertFalse(result.is_error)
            view = result.structured_content
            self.assertEqual(json.loads(view['document_json'])['timeline']['boxes'][0]['seed'], 18446744073709551615)
            result = await client.call_tool('h3_save_project', {'target': {'kind': 'managed', 'id': 'p1'}, 'expected_revision': {'project': 1}, 'document_json': view['document_json']})
            self.assertTrue(result.is_error)
            self.assertEqual(result.structured_content['error']['code'], 'revision_conflict')
            self.assertFalse(any('/h3c/agent/projects/' in request['path'] for request in self.host.requests))

    async def test_real_stdio_launcher_can_discover_tools(self):
        parameters = StdioServerParameters(command=sys.executable, args=['-m', 'h3c_mcp', '--studio-url', self.host.url,
            '--workspace-root', self.directory.name, '--state-dir', self.directory.name])
        async with Client(parameters) as client:
            names = {tool.name for tool in (await client.list_tools()).tools}
            self.assertIn('h3_read_guidance', names)
            content = (await client.read_resource(self.uri)).contents[0]
            self.assertEqual(content.text.encode(), self.raw)

    async def test_legacy_client_can_read_guidance(self):
        async with Client(self.server(), mode='legacy') as client:
            self.assertNotEqual(client.protocol_version, '2026-07-28')
            result = await client.call_tool('h3_read_guidance', {'uri': self.uri})
            self.assertFalse(result.is_error)
            self.assertEqual(result.structured_content['text'].encode(), self.raw)

    async def test_catalog_rejects_a_skill_file_missing_from_resource_inventory(self):
        from h3c_mcp.guidance import Guidance
        from h3c_mcp.transport import StudioError
        self.host.catalog['resources'] = []
        with self.assertRaisesRegex(StudioError, 'catalog'):
            Guidance(self.http).catalog()

    async def test_changed_resource_is_not_returned_under_its_old_manifest(self):
        from h3c_mcp.guidance import Guidance
        from h3c_mcp.transport import StudioError
        guidance = Guidance(self.http)
        guidance.catalog()
        resource_path = next(path for (method, path) in self.host.routes if path.startswith('/h3c/agent/resource?'))
        self.host.routes[('GET', resource_path)] = (200, b'new bytes')
        with self.assertRaisesRegex(StudioError, 'hash changed'):
            guidance.read(self.uri)
        self.assertIsNone(guidance.current)
