import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters

from tests.support import FixtureStudio


class StdioWorkflowTest(unittest.IsolatedAsyncioTestCase):
    async def test_document_round_trip_through_stdio_preserves_uint64(self):
        host = FixtureStudio()
        self.addCleanup(host.close)
        host.guidance()
        original = dict(id='p', revision=1, name='example', timeline=dict(boxes=[dict(id='a', prompt='Old', seed=18446744073709551615)]),
                        consumer=dict(opaque={'seed': 18446744073709551615, 'unknown': [True, 'preserved']}))
        project = copy.deepcopy(original)
        host.routes[('GET', '/h3c/api/v1/projects/p')] = lambda request: (200, project)
        def save(request):
            body = json.loads(request['body'])
            if body.pop('expected_revision') != project['revision']:
                return 409, {'error': {'code': 'revision_conflict', 'message': 'Saved revision changed'}}
            project.update(body, revision=project['revision'] + 1)
            return 200, project
        host.routes[('PUT', '/h3c/api/v1/projects/p')] = save
        host.routes[('POST', '/h3c/agent/projects/read')] = (200, dict(target=dict(kind='native', graph='old', timeline_node='2'),
            revision=dict(state=1, workflow=1, execution=0), execution_ready=False, document_json='{"timeline":{"boxes":[]}}'))
        host.routes[('POST', '/h3c/agent/projects/context')] = (409, {'error': {'code': 'execution_snapshot_required', 'message': 'Capture a snapshot'}})
        with tempfile.TemporaryDirectory(prefix='h3c stdio working path ') as directory:
            parameters = StdioServerParameters(command=sys.executable, args=['-m', 'h3c_mcp', '--studio-url', host.url,
                '--workspace-root', directory, '--state-dir', directory], cwd=directory)
            async with Client(parameters) as client:
                target = dict(kind='managed', id='p')
                async def read():
                    return (await client.call_tool('h3_get_project', {'target': target})).structured_content
                before = await read()
                document = json.loads(before['document_json'])
                document['timeline']['boxes'][0]['prompt'] = 'Changed'
                arguments = dict(target=target, expected_revision=before['revision'], document_json=json.dumps(document))
                saved = await client.call_tool('h3_save_project', arguments)
                self.assertFalse(saved.is_error)
                after = await read()
                saved_document = json.loads(after['document_json'])
                self.assertEqual(saved_document['timeline']['boxes'][0]['seed'], 18446744073709551615)
                self.assertEqual(saved_document['consumer']['opaque'], original['consumer']['opaque'])
                self.assertGreater(after['revision']['project'], before['revision']['project'])
                conflict = await client.call_tool('h3_save_project', arguments)
                self.assertTrue(conflict.is_error)
                self.assertEqual(conflict.structured_content['error']['code'], 'revision_conflict')
                native = dict(kind='native', graph='old', timeline_node='2')
                old = (await client.call_tool('h3_get_project', {'target': native})).structured_content
                self.assertFalse(old['execution_ready'])
                plan = await client.call_tool('h3_plan_video', dict(target=native, expected_revision=old['revision']))
                self.assertTrue(plan.is_error)
                self.assertEqual(plan.structured_content['error']['code'], 'execution_snapshot_required')
        self.assertFalse(any(r['path'] == '/prompt' for r in host.requests))
