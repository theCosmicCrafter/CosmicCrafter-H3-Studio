import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from h3_continuity.agent_api import resources
except ImportError:
    resources = None


class AgentResourcesTest(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(resources, 'The host must provide its agent resource catalog')

    def test_manifest_matches_original_skill_bytes(self):
        catalog = resources.catalog()
        self.assertEqual(catalog['agent_api_version'], 1)
        self.assertEqual(len(catalog['skills']), 7)
        self.assertEqual(catalog['skills'][0]['frontmatter']['name'], 'h3-continuity-video')
        for skill in catalog['skills']:
            for entry in skill['resources']:
                raw, mime = resources.read(entry['uri'], entry['digest'])
                self.assertEqual(entry['size'], len(raw))
                self.assertEqual(entry['digest'], 'sha256:' + hashlib.sha256(raw).hexdigest())
                self.assertTrue(mime)

    def test_crlf_frontmatter_and_supporting_files_keep_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / 'skills' / 'sample'
            (skill / 'references').mkdir(parents=True)
            raw = b'---\r\nname: sample\r\ndescription: Example\r\nmetadata:\r\n  version: 2\r\n---\r\nBody\r\n'
            (skill / 'SKILL.md').write_bytes(raw)
            (skill / 'references' / 'guide.md').write_bytes(b'reference\r\n')
            with mock.patch.object(resources, 'ROOT', root):
                entry = resources.catalog()['skills'][0]
                self.assertEqual(entry['frontmatter']['metadata'], {'version': 2})
                self.assertEqual(len(entry['resources']), 2)
                self.assertEqual(resources.read(entry['uri'])[0], raw)

    def test_changed_digest_is_a_conflict(self):
        entry = resources.catalog()['skills'][0]['resources'][0]
        with self.assertRaisesRegex(ValueError, 'changed'):
            resources.read(entry['uri'], 'sha256:' + '0' * 64)

    def test_unknown_and_traversal_uris_are_rejected(self):
        for uri in ('file:///etc/passwd', 'skill://../SKILL.md', 'skill://sample/%2e%2e/secret',
                    'h3c://docs/../../secret', 'skill://missing/SKILL.md'):
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                resources.read(uri)

    def test_skill_directory_and_frontmatter_name_must_match(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / 'skills' / 'sample'
            skill.mkdir(parents=True)
            (skill / 'SKILL.md').write_text('---\nname: other\ndescription: Example\n---\n')
            with mock.patch.object(resources, 'ROOT', root), self.assertRaisesRegex(ValueError, 'name'):
                resources.catalog()

    def test_links_cannot_escape_the_skill_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / 'skills' / 'sample'
            skill.mkdir(parents=True)
            (skill / 'SKILL.md').write_text('---\nname: sample\ndescription: Example\n---\n')
            outside = root / 'secret'
            outside.mkdir()
            (outside / 'private').write_text('private')
            linked = skill / 'secret'
            try:
                linked.symlink_to(outside, target_is_directory=True)
            except OSError:
                import _winapi
                _winapi.CreateJunction(str(outside), str(linked))
            try:
                with mock.patch.object(resources, 'ROOT', root), self.assertRaisesRegex(ValueError, 'escape'):
                    resources.catalog()
            finally:
                linked.unlink() if linked.is_symlink() else os.rmdir(linked)

    def test_coverage_classifies_all_nodes_and_skills(self):
        coverage = resources.catalog()['coverage']
        self.assertEqual(len(coverage['nodes']), 19)
        self.assertIn('H3C_MiniMaxH3ImageStill', coverage['nodes'])
        self.assertIn('H3C_MiniMaxPromptCaption', coverage['nodes'])
        self.assertEqual(len(coverage['skills']), 7)
        self.assertEqual(coverage['features']['replacement_bridges']['exposure'], 'unavailable')
        self.assertEqual(coverage['features']['browser_history']['exposure'], 'browser')
        self.assertTrue(json.dumps(coverage))


class AgentResourceRoutesTest(unittest.IsolatedAsyncioTestCase):
    async def test_resource_route_returns_original_bytes_and_conflict(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
        from types import SimpleNamespace
        from h3_continuity.agent_api import routes
        app = web.Application()
        instance = SimpleNamespace(routes=web.RouteTableDef())
        routes.register(instance)
        app.add_routes(instance.routes)
        async with TestClient(TestServer(app)) as client:
            catalog = await (await client.get('/h3c/agent/catalog')).json()
            entry = catalog['skills'][0]['resources'][0]
            response = await client.get('/h3c/agent/resource', params={'uri': entry['uri'], 'digest': entry['digest']})
            self.assertEqual(await response.read(), resources.read(entry['uri'])[0])
            response = await client.get('/h3c/agent/resource', params={'uri': entry['uri'], 'digest': 'changed'})
            self.assertEqual(response.status, 409)
            self.assertEqual((await response.json())['error']['code'], 'resource_changed')


if __name__ == '__main__':
    unittest.main()
