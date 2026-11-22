import copy
import json
import unittest
import torch
from h3_continuity import audio_tracks, audio_windows, timeline, dialogue, timed_text, reference_replacements, story_prompts
from types import SimpleNamespace
from .helpers import box, clip, cue

RATE=11025

def document():
    lane=clip(start=.5,source_start=1,duration=6)
    lane['box_windows']=audio_windows.capture(lane,[dict(id='a',start=0,duration=4),dict(id='b',start=4,duration=4)],{'file':lane['file']})
    return dict(boxes=[box('a',96,exact=True),box('b',96,cut=True,exact=True)],audio_clips=[lane],requires=[audio_windows.FEATURE])


class ConditioningTest(unittest.TestCase):
    def parse(self,line): return timeline.parse(json.dumps(line))

    def test_enabling_preserves_fractional_sample_phase_and_short_sources(self):
        source={'audio1':{'waveform':torch.arange(3*RATE,dtype=torch.float32).reshape(1,1,-1),'sample_rate':RATE}}
        for start, source_start in [(.031,1.13),(.5,1),(.3001,.2003)]:
            raw=document();lane=raw['audio_clips'][0]
            lane.update(start=start,source_start=source_start,duration=6)
            lane.pop('box_windows')
            before=self.parse(raw)
            lane['box_windows']=audio_windows.capture(lane,timeline.audio_box_spans(before),{'file':lane['file']})
            after=self.parse(raw)
            for index in range(2):
                self.assertTrue(torch.equal(audio_tracks.for_box(before,index,0,source)['audio1']['waveform'],audio_tracks.for_box(after,index,0,source)['audio1']['waveform']))

    def test_extensions_and_insertions_keep_original_samples_and_local_identity(self):
        raw=document(); original=self.parse(raw)
        source={'audio1':{'waveform':torch.arange(12*RATE,dtype=torch.float32).reshape(1,1,-1),'sample_rate':RATE}}
        expected=audio_tracks.for_box(original,1,0,source)['audio1']['waveform']
        original_key=timeline.layout_key(original,1,0)
        raw['boxes'][0]['frames']=144
        changed=self.parse(raw)
        self.assertTrue(torch.equal(audio_tracks.for_box(changed,1,0,source)['audio1']['waveform'],expected))
        self.assertEqual(timeline.layout_key(changed,1,0),original_key)
        a=audio_tracks.for_box(changed,0,0,source)['audio1']['waveform']
        self.assertTrue(torch.equal(a[...,4*RATE:],torch.zeros_like(a[...,4*RATE:])))
        raw['boxes'].insert(1,box('new',24,'@audio1',cut=True,exact=True))
        empty=self.parse(raw)
        self.assertNotIn('audio1',audio_tracks.for_box(empty,1,0,source))
        self.assertNotIn('audio1',timeline.box_slots(empty,1,0).audios)

    def test_carry_uses_actual_preceding_silence_and_refmods_cannot_bypass_windows(self):
        raw=document();raw['boxes']=[box('a',107),box('b',102)]
        raw['audio_clips'][0]['box_windows']['by_box']['a']=dict(offset=0,source_start=1,duration=1)
        wave=torch.ones(1,1,12*RATE)
        output=audio_tracks.for_box(self.parse(raw),1,39,{'audio1':{'waveform':wave,'sample_rate':RATE}})['audio1']['waveform']
        self.assertTrue(torch.equal(output[...,:round(39/24*RATE)],torch.zeros_like(output[...,:round(39/24*RATE)])))
        raw['refmods']=[dict(slot='audio1',kind='audio',name='x',strength=1)]
        with self.assertRaisesRegex(ValueError,'RefMod|refmod'):
            self.parse(raw)

    def test_dialogue_and_text_follow_windows_without_spurious_boundary_clipping(self):
        raw=document(); raw['dialogue']=dict(version=1,cues=[cue(start=5,end=6),cue('boundary',start=4,end=5)])
        parsed=self.parse(raw)
        self.assertFalse(any(item['cut'] for item in dialogue.projected(parsed)))
        raw['boxes'][0]['frames']=144
        parsed=self.parse(raw)
        event=next(event for event in dialogue.box_events(parsed,1,0) if event['id']=='c1')
        self.assertEqual((event['start_ms'],event['end_ms']),(500,1500))
        value=dict(version=1,source_name='words',source_sha256='0'*64,enabled=True,sync_audio=True,audio_slot='audio1',start=0,source_start=0,duration=12,direction='',cues=[dict(id='x',start=6,end=7,text=' Hello')])
        windows=timeline.resolved_audio(parsed)
        text=timed_text.project(value,parsed.audio_clips,6,96,placements=windows)
        self.assertEqual(text['cues'][0]['start_ms'],1500)
        self.assertEqual(timed_text.active(value,parsed.audio_clips,7.5,placements=windows)[0]['text'],' Hello')
        self.assertEqual(timed_text.active(value,parsed.audio_clips,5.5,placements=windows),[])
        continuous=copy.deepcopy(value);continuous['sync_audio']=False
        self.assertEqual(timed_text.project(continuous,parsed.audio_clips,4,96,placements=windows)['cues'][0]['start_ms'],2000)

    def test_shortening_a_cue_requires_review_and_hidden_changes_do_not_invalidate(self):
        raw=document();raw['dialogue']=dict(version=1,cues=[cue(start=2,end=3)])
        raw['boxes'][0]['frames']=48
        parsed=self.parse(raw)
        self.assertTrue(any(item['cut'] for item in dialogue.projected(parsed)))
        key=timeline.layout_key(parsed,0,0)
        raw['audio_clips'][0]['box_windows']['by_box']['a']['duration']=3
        self.assertEqual(timeline.layout_key(self.parse(raw),0,0),key)

    def test_source_sample_phase_is_part_of_effective_audio_identity(self):
        raw=document();before=self.parse(raw)
        source={'audio1':{'waveform':torch.arange(12*RATE,dtype=torch.float32).reshape(1,1,-1),'sample_rate':RATE}}
        key=timeline.layout_key(before,1,0)
        raw['audio_clips'][0]['start']=.5001
        raw['audio_clips'][0]['box_windows']['placement']['start']=.5001
        after=self.parse(raw)
        self.assertFalse(torch.equal(audio_tracks.for_box(before,1,0,source)['audio1']['waveform'],audio_tracks.for_box(after,1,0,source)['audio1']['waveform']))
        self.assertNotEqual(timeline.layout_key(after,1,0),key)

    def test_unplaced_raw_alias_and_effective_refmod_cannot_bypass_binding(self):
        raw=document();raw['reference_replacements']={'audio2':{'source':'audio1'}}
        raw['boxes'].insert(1,box('new',24,'@audio2',cut=True,exact=True))
        with self.assertRaisesRegex(ValueError,'bound|window'):
            self.parse(raw)
        # A deliberately separate lane has its own placement and remains independent.
        raw['audio_clips'].append(clip(slot='audio2',duration=12))
        parsed=self.parse(raw)
        source={slot:dict(waveform=torch.ones(1,1,12*RATE),sample_rate=RATE) for slot in ['audio1','audio2']}
        self.assertGreater(audio_tracks.for_box(parsed,1,0,source)['audio2']['waveform'].count_nonzero(),0)
    def test_aliased_refmod_cannot_bypass_binding(self):
        raw=document();lane=raw['audio_clips'][0];lane.pop('file')
        raw['reference_replacements']={'audio1':{'source':'audio2'}}
        lane['box_windows']['source']={'source':'audio2'}
        raw['refmods']=[dict(slot='audio2',kind='audio',name='voice',strength=1)]
        with self.assertRaisesRegex(ValueError,'RefMod|refmod'):
            reference_replacements.refmods(self.parse(raw))

    def test_story_instructions_describe_resolved_ranges_not_original_lane_clock(self):
        raw=document();lane=raw['audio_clips'][0];lane.update(start=0,source_start=0,duration=8)
        lane['box_windows']=audio_windows.capture(lane,[dict(id='a',start=0,duration=4),dict(id='b',start=4,duration=4)],{'file':lane['file']})
        raw['boxes'][0]['frames']=144;parsed=self.parse(raw)
        ctx=SimpleNamespace(timeline=parsed,descriptions={},boxes=[SimpleNamespace(frames=144,carried=0),SimpleNamespace(frames=96,carried=0)])
        ref=story_prompts._reference(ctx,SimpleNamespace(name='audio1',label='Audio1'))
        self.assertIn('6.000000–10.000000',ref)
        self.assertIn('to '+story_prompts.clock(4),story_prompts.audio_direction(ctx,1))
        self.assertIn('to '+story_prompts.clock(4),story_prompts.timeline_audio_entries(ctx,1)[-1][-1])
