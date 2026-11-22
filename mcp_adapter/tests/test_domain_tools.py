import json
import tempfile
import unittest
from pathlib import Path

from h3c_mcp.tools import StudioTools, Target
from h3c_mcp.transport import StudioClient, StudioError
from tests.support import FixtureStudio


class DomainTest(unittest.TestCase):
    def setUp(self):
        self.host = FixtureStudio()
        self.addCleanup(self.host.close)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.client = StudioClient(self.host.url, roots=[Path(self.temp.name)])
        self.addCleanup(self.client.close)
        self.tools = StudioTools(self.client, None, Path(self.temp.name))
        self.target = Target(kind='native', graph='g', timeline_node='2', story_node='1')
        self.rev = dict(state=1, workflow=1, execution=1)
        self.context = dict(name='native', timeline={'version': 1, 'boxes': []}, settings={}, graph='g', story='1',
                            workflow={'ui': {'nodes': []}, 'api': {}}, prompt={}, fields={}, timeline_node='2')
        self.host.routes[('POST', '/h3c/agent/projects/context')] = (200, self.context)

    def route(self, method, path, result=None):
        self.host.routes[(method, path)] = (200, result or {'ok': True})

    def test_all_nonexecuting_domain_routes_are_fixed(self):
        cases = [
            ('h3_story', 'templates', 'GET', '/h3c/story/templates', {}),
            ('h3_story', 'hosts', 'GET', '/h3c/story/keys', {}),
            ('h3_story', 'bible', 'POST', '/h3c/timeline/bible', {'action': 'status'}),
            ('h3_stills', 'sources', 'POST', '/h3c/stills/sources', {'box': 'a'}),
            ('h3_stills', 'pin', 'POST', '/h3c/stills/pin', {'file': {}}),
            ('h3_stills', 'reference_catalog', 'POST', '/h3c/reference-assets/catalog', {}),
            ('h3_stills', 'reference_approve', 'POST', '/h3c/reference-assets/approve', {'asset_key': 'x', 'candidate_id': 'c', 'approval_revision': 0}),
            ('h3_stills', 'prompt_instructions', 'POST', '/h3c/still-prompts/instructions', {}),
            ('h3_takes', 'list', 'POST', '/h3c/timeline/takes', {'box': 'a'}),
            ('h3_takes', 'use', 'POST', '/h3c/timeline/takes/use', {'take': 'takes/x'}),
            ('h3_takes', 'rate', 'POST', '/h3c/timeline/takes/rate', {'created': '2026-11-08T10:00:00', 'rating': 2, 'tag': 'keeper'}),
            ('h3_takes', 'delete_preview', 'POST', '/h3c/timeline/takes/delete', {'scope': 'other', 'box': 'a', 'apply': True}),
            ('h3_takes', 'delete_apply', 'POST', '/h3c/timeline/takes/delete', {'scope': 'take', 'take': 'takes/x'}),
            ('h3_library', 'list', 'GET', '/h3c/stories', {}),
            ('h3_library', 'load', 'GET', '/h3c/stories?id=x', {'id': 'x'}),
            ('h3_library', 'rename', 'POST', '/h3c/stories/rename', {'key': 'x', 'name': 'New'}),
            ('h3_library', 'delete', 'POST', '/h3c/stories/delete', {'id': 'x'}),
            ('h3_library', 'checkpoint', 'POST', '/h3c/stories/checkpoint', {'name': 'Named'}),
            ('h3_library', 'restore', 'POST', '/h3c/stories/restore', {'id': 'x'}),
            ('h3_library', 'generation_start', 'POST', '/h3c/generations/start', {}),
            ('h3_library', 'generation_history', 'POST', '/h3c/generations/history', {}),
            ('h3_library', 'generation_export', 'POST', '/h3c/generations/export', {}),
            ('h3_library', 'generation_preflight', 'POST', '/h3c/generations/preflight', {'archive': {}}),
            ('h3_library', 'generation_import', 'POST', '/h3c/generations/import', {'archive': {}, 'request_id': 'import-one'}),
            ('h3_inspect', 'status', 'POST', '/h3c/timeline/status', {}),
            ('h3_inspect', 'regeneration', 'POST', '/h3c/timeline/regeneration', {'box': 'a'}),
            ('h3_inspect', 'audio', 'POST', '/h3c/audio/info', {'file': {}}),
            ('h3_inspect', 'image_description', 'POST', '/h3c/images/description', {'action': 'read', 'file': {}}),
            ('h3_inspect', 'refmods', 'GET', '/h3c/refmods', {}),
            ('h3_inspect', 'nodes', 'GET', '/object_info', {}),
        ]
        for tool, action, method, path, arguments in cases:
            with self.subTest(tool=tool, action=action):
                self.route(method, path)
                result = getattr(self.tools, tool)(action, self.target, json.dumps(arguments), self.rev)
                self.assertIn('data_json', result)
                self.assertTrue(any(r['method'] == method and r['path'] == path for r in self.host.requests))
                if action == 'delete_preview':
                    self.assertFalse(json.loads(self.host.requests[-1]['body'])['apply'])

    def test_duplicate_copies_the_saved_story_and_returns_the_copy_target(self):
        copy = {'id': 'f' * 64, 'graph': 'copy', 'story': '1', 'timeline_node': '2', 'sequence': 'generation_x', 'title': 'Copy'}
        self.route('POST', '/h3c/stories/duplicate', copy)
        line = {'version': 1, 'boxes': [], 'requires': []}
        result = self.tools.h3_library('duplicate', self.target, json.dumps({'title': 'Copy', 'timeline_json': line}), self.rev)
        body = json.loads(self.host.requests[-1]['body'])
        self.assertEqual(body, {'graph': 'g', 'story': '1', 'workflow': {'nodes': []}, 'sequence': 'native',
                                'title': 'Copy', 'timeline_json': json.dumps(line, separators=(',', ':'))})
        self.assertEqual(result['target'], {'kind': 'native', 'graph': 'copy', 'timeline_node': '2', 'story_node': '1'})
        self.assertEqual(json.loads(result['data_json']), copy)
        with self.assertRaisesRegex(StudioError, 'arguments'):
            self.tools.h3_library('duplicate', self.target, '{"name":"Copy"}', self.rev)

    def test_prompt_fields_read_a_given_prompt_or_a_saved_box(self):
        self.route('POST', '/h3c/prompts/fields', {'summary': {'shots': 1}})
        tags = [{'tag': '<Picture 1>', 'name': 'image1'}]
        self.tools.h3_inspect('prompt_fields', self.target, json.dumps({'prompt': '[Shot 1] A.', 'tags': tags}))
        self.assertEqual(json.loads(self.host.requests[-1]['body']), {'prompt': '[Shot 1] A.', 'tags': tags})
        self.assertFalse(any(r['path'] == '/h3c/agent/projects/context' for r in self.host.requests))
        result = self.tools.h3_inspect('prompt_fields', self.target, '{"box":"a","layer":"v2"}', self.rev)
        body = json.loads(self.host.requests[-1]['body'])
        self.assertEqual(body, {'timeline': '{"version":1,"boxes":[]}', 'box': 'a', 'layer': 'v2'})
        self.assertEqual(json.loads(result['data_json']), {'summary': {'shots': 1}})
        with self.assertRaisesRegex(StudioError, 'prompt'):
            self.tools.h3_inspect('prompt_fields', self.target, '{"box":"a","name":"x"}', self.rev)

    def test_managed_take_cleanup_cannot_use_native_route(self):
        target = Target(kind='managed', id='p')
        for action in ('delete_preview', 'delete_apply', 'rate'):
            with self.assertRaises(StudioError):
                self.tools.h3_takes(action, target, '{}', {'project': 1})
        self.assertEqual(self.host.requests, [])

    def test_managed_status_and_immutable_media_are_returned(self):
        self.route('GET', '/h3c/api/v1/projects/p', {'id': 'p', 'revision': 1, 'timeline': {}, 'status': {'full_video': {'id': 'artifact'}}})
        view = self.tools.h3_inspect('status', Target(kind='managed', id='p'))
        self.assertEqual(json.loads(view['status_json'])['full_video']['id'], 'artifact')

    def test_context_identity_cannot_be_overridden(self):
        with self.assertRaises(StudioError):
            self.tools.h3_takes('list', self.target, '{"name":"api_other"}', self.rev)
        with self.assertRaises(StudioError):
            self.tools.h3_stills('replacement_generate', self.target, '{}', self.rev)
        with self.assertRaises(StudioError):
            self.tools.h3_story('write', self.target, '{"check_only":true}', self.rev, 'key')

    def test_rating_requires_created_identity_instead_of_take_path(self):
        with self.assertRaisesRegex(StudioError, 'created'):
            self.tools.h3_takes('rate', self.target, '{"take":"takes/x","rating":2}', self.rev)
        self.assertEqual(self.host.requests, [])
