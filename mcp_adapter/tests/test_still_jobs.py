import json
from tests.test_domain_tools import DomainTest
from h3c_mcp.tools import JobHandle


class StillJobsTest(DomainTest):
    def test_prepare_is_not_generation_and_completed_candidate_is_not_applied(self):
        prepared = dict(ok=True, prompt_id='owned', prompt={'h3c_still_output': {'class_type': 'SaveImage', 'inputs': {}}},
                        outputs=['h3c_still_output'], provenance={'request_id': 'request', 'prompt': 'keep manual'})
        self.route('POST', '/h3c/stills/prepare', prepared)
        args = json.dumps(dict(box='a', prompt='keep manual', recipe={'version': 2}))
        self.tools.h3_stills('prepare', self.target, args, self.rev)
        self.assertFalse(any(r['path'] == '/prompt' for r in self.host.requests))
        self.host.routes[('POST', '/prompt')] = lambda request: (200, {'prompt_id': json.loads(request['body'])['prompt_id']})
        result = self.tools.h3_stills('generate', self.target, args, self.rev, 'still-one')
        posted = next(json.loads(r['body']) for r in self.host.requests if r['path'] == '/prompt')
        self.assertEqual(posted['extra_data']['h3c_still']['provenance']['prompt'], 'keep manual')
        self.route('POST', '/h3c/stills/result', {'ok': True, 'state': 'complete', 'images': [{'file': {'filename': 'x'}}]})
        status = self.tools.h3_job_status(JobHandle.model_validate(result['job']))
        self.assertTrue(status['result_available'])
        self.assertFalse(any(r['path'].endswith('/save') for r in self.host.requests))
        self.tools.h3_stills('generate', self.target, args, self.rev, 'still-one')
        self.assertEqual(sum(r['path'] == '/prompt' for r in self.host.requests), 1)

    def test_reference_generate_has_its_own_prepare_and_result(self):
        self.route('POST', '/h3c/reference-assets/prepare', dict(ok=True, prompt_id='owned', prompt={}, outputs=['h3c_still_output'], provenance={}))
        self.host.routes[('POST', '/prompt')] = lambda request: (200, {'prompt_id': json.loads(request['body'])['prompt_id']})
        result = self.tools.h3_stills('reference_generate', self.target, '{"asset_key":"cast"}', self.rev, 'cast-one')
        self.route('POST', '/h3c/reference-assets/result', {'ok': True, 'state': 'complete', 'images': []})
        self.assertTrue(self.tools.h3_job_status(JobHandle.model_validate(result['job']))['result_available'])
