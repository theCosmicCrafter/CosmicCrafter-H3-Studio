import copy
import json
from pathlib import Path
import unittest
from unittest import mock
from h3_continuity import audio_windows, timeline
from h3_continuity import timeline_prepare
from h3_continuity.timeline_api import contracts

F = json.loads((Path(__file__).parents[1] / 'fixtures/box_audio_windows.json').read_text())


class AudioWindowsTest(unittest.TestCase):
    def clip(self):
        return dict(F['clip'], box_windows=audio_windows.capture(F['clip'], F['boxes'], F['origin']))

    def line(self, clip=None):
        return dict(version=1, requires=['box-audio-windows-1'], boxes=[
            dict(id='a', frames=96, exact=True), dict(id='b', frames=96, exact=True, cut=True)],
            audio_clips=[self.clip() if clip is None else clip])

    def test_source_duration_is_optional_but_validated_when_present(self):
        clip = dict(F['clip']); clip.pop('source_duration', None)
        timeline.parse(json.dumps(self.line(clip)))
        contracts.validate('timeline', self.line(clip))
        for bad in [None, True, 0, -1, "200", float('nan'), float('inf')]:
            with self.subTest(value=bad), self.assertRaises(ValueError):
                timeline.parse(json.dumps(self.line(dict(clip, source_duration=bad))))
        parsed = timeline.parse(json.dumps(self.line(dict(clip, source_duration=200))))
        self.assertEqual(parsed.audio_clips[0]['source_duration'], 200)
        schema = contracts.schemas()
        audio = schema['timeline']['properties']['audio_clips']['items']
        self.assertIn('source_duration', audio['properties'])
        self.assertNotIn('source_duration', audio['required'])
        contracts.validate('timeline', self.line(dict(clip, source_duration=200)))
        for bad in [None, True, 0, -1, '200']:
            with self.subTest(schema_value=bad), self.assertRaises(contracts.APIError):
                contracts.validate('timeline', self.line(dict(clip, source_duration=bad)))

    def test_shared_capture_resize_and_empty_map(self):
        clip = self.clip()
        self.assertEqual(clip['box_windows']['by_box'], F['bindings'])
        self.assertEqual(audio_windows.resolve(clip, F['boxes']), F['resolved'])
        boxes = [dict(id='a', start=0, duration=6), dict(id='b', start=6, duration=4)]
        self.assertEqual(audio_windows.resolve(clip, boxes)[1]['source_start'], 33.5)
        self.assertEqual(audio_windows.resolve(clip, boxes)[1]['start'], 6)
        self.assertEqual(audio_windows.resolve(clip, [dict(id='a',start=0,duration=2)])[0]['duration'],1.5)
        self.assertEqual(audio_windows.resolve(clip, F['boxes']), F['resolved'])
        clip['box_windows']['by_box'] = {}
        self.assertEqual(audio_windows.resolve(clip, F['boxes']), [])
        self.assertIsNone(audio_windows.resolve(F['clip'], F['boxes'])[0]['box'])

    def test_invalid_inputs_and_hidden_tail(self):
        for bad in [float('nan'), float('inf'), True, -1, 0]:
            clip = self.clip(); clip['box_windows']['by_box']['a']['duration'] = bad
            with self.assertRaises(ValueError): audio_windows.validate(clip,F['boxes'],F['origin'])
        for edit in [lambda c: c.update(start=1), lambda c: c['box_windows'].update(version=2),
                     lambda c: c['box_windows']['by_box'].update(missing=F['bindings']['a']),
                     lambda c: c['box_windows']['by_box']['a'].update(source_start=100)]:
            clip=self.clip(); edit(clip)
            with self.assertRaises(ValueError): audio_windows.validate(clip,F['boxes'],F['origin'])
        with self.assertRaises(ValueError): audio_windows.validate(self.clip(), F['boxes'], {'source':'audio2'})
        audio_windows.validate(self.clip(),[dict(id='a',start=0,duration=.1),dict(id='b',start=.1,duration=1)],F['origin'])

    def test_native_reader_requires_feature_and_preserves_empty_mapping(self):
        line = self.line()
        parsed = timeline.parse(json.dumps(line))
        self.assertEqual(timeline.audio_box_spans(parsed),F['boxes'])
        self.assertEqual(parsed.audio_clips[0]['box_windows']['by_box'],F['bindings'])
        line['audio_clips'][0]['box_windows']['by_box']={}
        self.assertEqual(timeline.parse(json.dumps(line)).audio_clips[0]['box_windows']['by_box'],{})
        line.pop('requires')
        with self.assertRaisesRegex(ValueError,'requires'): timeline.parse(json.dumps(line))
        with mock.patch.object(timeline,'REQUIRES',()):
            with self.assertRaisesRegex(ValueError,'newer'): timeline.parse(json.dumps(self.line()))

    def test_api_schema_and_normalization_preserve_hidden_and_empty_windows(self):
        for empty in [False, True]:
            line=self.line()
            if empty: line['audio_clips'][0]['box_windows']['by_box']={}
            line['boxes'][0]['frames']=24
            expected=copy.deepcopy(line['audio_clips'][0]['box_windows'])
            contracts.validate('timeline',line)
            timeline_prepare.normalize(line)
            self.assertEqual(line['audio_clips'][0]['box_windows'],expected)

    def test_frozen_placement_rejects_booleans_even_when_equal_to_a_number(self):
        clip=dict(F['clip'],duration=1)
        clip['box_windows']=audio_windows.capture(clip,F['boxes'],F['origin'])
        clip['box_windows']['placement']['duration']=True
        with self.assertRaises(ValueError): audio_windows.validate(clip,F['boxes'],F['origin'])
