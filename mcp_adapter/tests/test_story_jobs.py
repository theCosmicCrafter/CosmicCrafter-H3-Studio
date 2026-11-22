import json
from tests.test_domain_tools import DomainTest
from h3c_mcp.tools import JobHandle


class StoryJobsTest(DomainTest):
    def test_late_story_result_is_proposal_until_explicit_save(self):
        self.route('POST', '/h3c/story/write', {'ok': True, 'job': 'writer-one'})
        result = self.tools.h3_story('write', self.target, '{}', self.rev, 'write-once')
        self.context['timeline']['newer_edit'] = True
        self.route('GET', '/h3c/story/job?id=writer-one&graph=g&story=1', {'state': 'complete', 'timeline': {'boxes': []}})
        status = self.tools.h3_job_status(JobHandle.model_validate(result['job']))
        self.assertTrue(status['result_available'])
        self.assertTrue(self.context['timeline']['newer_edit'])
        self.assertFalse(any(r['path'].endswith('/save') for r in self.host.requests))
        self.assertTrue(json.loads(status['data_json'])['result']['timeline'] == {'boxes': []})

    def test_lost_story_start_requires_positive_attribution_not_another_write(self):
        self.host.routes[('POST', '/h3c/story/write')] = lambda request: None
        result = self.tools.h3_story('write', self.target, '{}', self.rev, 'lost')
        self.route('GET', '/h3c/story/current?client=h3c-mcp&graph=g&story=1&recover=true', {'job': 'unrelated'})
        self.tools.h3_job_status(JobHandle.model_validate(result['job']))
        again = self.tools.h3_story('write', self.target, '{}', self.rev, 'lost')
        self.assertEqual(again['state'], 'needs_reconciliation')
        self.assertEqual(sum(r['path'] == '/h3c/story/write' for r in self.host.requests), 1)

    def test_story_action_routes(self):
        for action, path in [('rewrite', '/h3c/story/write'), ('feedback', '/h3c/story/write'), ('check', '/h3c/story/check'), ('still_prompts', '/h3c/still-prompts/prepare')]:
            self.route('POST', path, {'ok': True, 'job': action})
            self.assertEqual(self.tools.h3_story(action, self.target, '{}', self.rev, action)['state'], 'accepted')

    def test_recovery_adopts_only_matching_request_and_acknowledges_after_retention(self):
        self.host.routes[('POST', '/h3c/story/write')] = lambda request: None
        result = self.tools.h3_story('write', self.target, '{}', self.rev, 'recover')
        self.route('GET', '/h3c/story/current?client=h3c-mcp&graph=g&story=1&recover=true', {'job': 'recovered', 'request_id': result['job']['id']})
        self.route('GET', '/h3c/story/job?id=recovered&graph=g&story=1', {'state': 'done', 'result': {'prompt': 'proposal'}})
        status = self.tools.h3_job_status(JobHandle.model_validate(result['job']))
        self.assertTrue(status['result_available'])
        self.route('POST', '/h3c/story/taken')
        self.tools.h3_story('taken', self.target, json.dumps({'job': result['job']}))
        self.assertTrue(self.tools.h3_job_status(JobHandle.model_validate(result['job']))['result_available'])
