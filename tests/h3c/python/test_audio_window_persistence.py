import json
import unittest
from h3_continuity import audio_windows, timeline, timeline_prepare, long_merge
from h3_continuity.timeline_api import contracts


class PersistenceTest(unittest.TestCase):
    def test_empty_disabled_and_hidden_assignments_round_trip_preparation(self):
        for empty in [False, True]:
            clip=dict(slot='audio1',start=0,source_start=30,duration=4)
            clip['box_windows']=audio_windows.capture(clip,[dict(id='a',start=0,duration=4)],{'source':'audio1'})
            if empty: clip['box_windows']['by_box']={}
            line=dict(boxes=[dict(id='a',frames=24,exact=True)],audio_clips=[clip],disabled_refs=['audio1'],requires=[audio_windows.FEATURE])
            saved=json.dumps(line)
            contracts.validate('timeline',line)
            timeline_prepare.normalize(line)
            self.assertEqual(timeline.parse(json.dumps(line)).audio_clips[0]['box_windows'],json.loads(saved)['audio_clips'][0]['box_windows'])

    def test_merge_rejects_bound_owners_before_editing(self):
        clip=dict(slot='audio1',start=0,source_start=0,duration=10)
        clip['box_windows']=audio_windows.capture(clip,[dict(id='a',start=0,duration=107/24),dict(id='b',start=107/24,duration=102/24)],{'source':'audio1'})
        line=json.dumps(dict(boxes=[dict(id='a',frames=107),dict(id='b',frames=102)],audio_clips=[clip],requires=[audio_windows.FEATURE]))
        with self.assertRaisesRegex(ValueError,'unlock|bound'):
            long_merge.merge_continuing(line,'a','b')
