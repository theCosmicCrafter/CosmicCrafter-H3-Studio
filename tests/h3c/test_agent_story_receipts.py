import unittest
from types import SimpleNamespace
from tests.h3c.continuity_support import enable_comfy_cpu
enable_comfy_cpu()
from h3_continuity import story_job


class StoryReceiptsTest(unittest.TestCase):
    def test_current_and_recovery_return_request_attribution(self):
        jobs = story_job.Jobs()
        jobs.forget = lambda: None
        jobs.jobs['j'] = SimpleNamespace(taken=False, graph='g', ctx=SimpleNamespace(story_id='s', timeline_id='t'),
                                         client='c', id='j', kind='write', agent_request_id='owned')
        self.assertEqual(jobs.current('c', 'g', 's')['request_id'], 'owned')
        jobs.jobs.clear()
        jobs.recovered = lambda graph, story: {'job': 'j', 'timeline': 't', 'view': {'request_id': 'owned'}}
        self.assertEqual(jobs.current('c', 'g', 's', recover=True)['request_id'], 'owned')
