import copy
import json
import tempfile
import unittest
from pathlib import Path

from tests.support import FixtureStudio
from h3c_mcp.tools import Target, JobHandle
from h3c_mcp.transport import StudioClient, StudioError
try:
    from h3c_mcp.jobs import NativeJobs
except ImportError:
    NativeJobs = None


class NativeJobsTest(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(NativeJobs, 'Native submissions need durable recoverable receipts')
        self.host = FixtureStudio()
        self.addCleanup(self.host.close)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.client = StudioClient(self.host.url, roots=[Path(self.temp.name)])
        self.addCleanup(self.client.close)
        self.target = Target(kind='native', graph='g', timeline_node='2')
        self.revision = dict(state=1, workflow=1, execution=1)
        self.line = dict(version=1, boxes=[dict(id='a', frames=22, seed=1, prompt='A')])
        self.api = {'2': dict(class_type='H3C_Timeline', inputs=dict(name='native-study', timeline=json.dumps(self.line))),
                    '9': dict(class_type='H3C_SaveSegment', inputs={'segment': ['2', 3]})}
        self.context = dict(target=self.target.wire(), revision=self.revision, name='native-study', timeline=self.line,
            settings={}, outputs=['9'], workflow=dict(api=self.api, ui={'nodes': []}, timeline_node='2'),
            native_status={'boxes': [dict(id='a', status='missing', index=1)], 'bridges': []})
        self.host.routes[('POST', '/h3c/agent/projects/context')] = (200, self.context)
        self.host.routes[('POST', '/h3c/timeline/prepare')] = (200, dict(ok=True, version=1, timeline=self.line,
            fingerprint='f'*64, boxes=[dict(id='a', index=1)], workflow=dict(api=self.api, timeline_node='2')))
        self.host.routes[('POST', '/h3c/timeline/regeneration')] = (200, dict(ok=True, needs_rebuild=False, receipt=None))
        self.queue = {'queue_running': [], 'queue_pending': []}
        self.history = {}
        self.host.routes[('GET', '/queue')] = lambda request: (200, self.queue)
        self.host.routes[('POST', '/prompt')] = self.accept
        self.jobs = NativeJobs(self.client, Path(self.temp.name))

    def accept(self, request):
        body = json.loads(request['body'])
        self.submitted = body
        self.queue['queue_pending'] = [[1, body['prompt_id'], body['prompt'], body['extra_data'], body['partial_execution_targets']]]
        self.host.routes[('GET', '/history/' + body['prompt_id'])] = lambda request: (200, self.history)
        return 200, {'prompt_id': body['prompt_id']}

    def plan(self):
        return self.jobs.prepare(self.target, self.revision, {'kind': 'all'})

    def render(self, key='one-render'):
        plan = self.plan()
        return self.jobs.submit_video(self.target, self.revision, {'kind': 'all'}, plan['plan_sha256'], key)

    def posts(self):
        return [r for r in self.host.requests if r['method'] == 'POST' and r['path'] == '/prompt']

    def test_planning_is_read_only_and_submission_is_one_unit(self):
        self.plan()
        self.assertEqual(self.posts(), [])
        result = self.render()
        self.assertEqual(len(self.posts()), 1)
        line = json.loads(self.submitted['prompt']['2']['inputs']['timeline'])
        self.assertEqual(line['render_box'], 1)
        self.assertEqual(self.jobs.status(JobHandle.model_validate(result['job']))['state'], 'queued')
        self.assertEqual(len(self.posts()), 1)

    def test_lost_reply_and_restart_never_resubmit(self):
        def lost(request):
            self.accept(request)
            return None
        self.host.routes[('POST', '/prompt')] = lost
        first = self.render()
        self.assertEqual(first['state'], 'needs_reconciliation')
        self.jobs = NativeJobs(self.client, Path(self.temp.name))
        second = self.render()
        status = self.jobs.status(JobHandle.model_validate(second['job']))
        self.assertEqual(status['state'], 'queued')
        self.assertEqual(len(self.posts()), 1)

    def test_absent_evidence_stays_held_without_new_submission(self):
        result = self.render()
        self.queue['queue_pending'] = []
        status = self.jobs.status(JobHandle.model_validate(result['job']))
        self.assertEqual(status['state'], 'needs_reconciliation')
        self.assertEqual(len(self.posts()), 1)

    def test_unrelated_queue_evidence_is_rejected(self):
        result = self.render()
        self.queue['queue_pending'][0][2] = {'unrelated': dict(class_type='Other', inputs={})}
        status = self.jobs.status(JobHandle.model_validate(result['job']))
        self.assertEqual(status['state'], 'needs_reconciliation')

    def test_completed_history_is_retained(self):
        result = self.render()
        row = self.queue['queue_pending'][0]
        self.history[row[1]] = {'prompt': row, 'status': {'status_str': 'success', 'completed': True, 'messages': []}, 'outputs': {}}
        self.queue['queue_pending'] = []
        status = self.jobs.status(JobHandle.model_validate(result['job']))
        self.assertEqual(status['state'], 'succeeded')
        self.assertTrue(status['execution_completed'])

    def test_history_graph_with_comfyui_numeric_coercion_is_still_ours(self):
        # ComfyUI rewrites 24 as 24.0 for a FLOAT input while validating; the finished prompt must still match.
        self.api['9']['inputs'].update(fps=24, strength=1, seed=7)
        result = self.render()
        row = copy.deepcopy(self.queue['queue_pending'][0])
        row[2]['9']['inputs'].update(fps=24.0, strength=1.0)
        self.history[row[1]] = {'prompt': row, 'status': {'status_str': 'success', 'completed': True, 'messages': []}, 'outputs': {}}
        self.queue['queue_pending'] = []
        status = self.jobs.status(JobHandle.model_validate(result['job']))
        self.assertEqual(status['state'], 'succeeded')
        self.assertEqual(len(self.posts()), 1)

    def test_history_graph_with_a_different_value_is_still_rejected(self):
        self.api['9']['inputs'].update(strength=1)
        result = self.render()
        row = copy.deepcopy(self.queue['queue_pending'][0])
        row[2]['9']['inputs'].update(strength=1.5)
        self.history[row[1]] = {'prompt': row, 'status': {'status_str': 'success', 'completed': True, 'messages': []}, 'outputs': {}}
        self.queue['queue_pending'] = []
        self.assertEqual(self.jobs.status(JobHandle.model_validate(result['job']))['state'], 'needs_reconciliation')

    def test_new_request_content_cannot_reuse_an_accepted_key(self):
        self.render()
        self.line['boxes'][0]['prompt'] = 'Different'
        self.context['timeline'] = self.line
        with self.assertRaisesRegex(StudioError, 'key'):
            self.render()
        self.assertEqual(len(self.posts()), 1)

    def test_cancellation_does_not_clear_unrelated_queue(self):
        result = self.render()
        with self.assertRaisesRegex(StudioError, 'scoped'):
            self.jobs.cancel(JobHandle.model_validate(result['job']))
        self.assertFalse(any(r['path'] in ('/interrupt', '/queue') and r['method'] == 'POST' for r in self.host.requests))

    def test_rebuild_requires_matching_receipt_and_only_changes_submitted_graph(self):
        receipt = dict(box='a', fingerprint='c'*64)
        self.host.routes[('POST', '/h3c/timeline/regeneration')] = (200, dict(ok=True, needs_rebuild=True, receipt=receipt))
        with self.assertRaisesRegex(StudioError, 'receipt'):
            self.render()
        self.assertEqual(self.posts(), [])
        selection = dict(kind='boxes', ids=['a'], rebuild_continuity=receipt)
        plan = self.jobs.prepare(self.target, self.revision, selection)
        self.jobs.submit_video(self.target, self.revision, selection, plan['plan_sha256'], 'consent')
        self.assertEqual(json.loads(self.submitted['prompt']['2']['inputs']['timeline'])['rebuild_continuity'], receipt)
        self.assertNotIn('rebuild_continuity', self.line)

    def test_saved_take_is_skipped_and_unrelated_output_is_not_submitted(self):
        self.context['native_status']['boxes'][0]['status'] = 'outdated'
        with self.assertRaisesRegex(StudioError, 'eligible'):
            self.render()
        self.context['native_status']['boxes'][0]['status'] = 'missing'
        self.api['other'] = dict(class_type='UnrelatedOutput', inputs={})
        self.render()
        self.assertNotIn('other', self.submitted['prompt'])

    def test_native_preparation_carries_host_verified_audio_bindings(self):
        assets = [dict(file=dict(filename='recording.wav', type='input', subfolder=''), sha256='a'*64,
                       bindings=[dict(kind='loader', node='audio', input='audio', slot='audio1')])]
        self.context['assets'] = assets
        self.plan()
        request = next(r for r in self.host.requests if r['path'] == '/h3c/timeline/prepare')
        self.assertEqual(json.loads(request['body'])['assets'], assets)
