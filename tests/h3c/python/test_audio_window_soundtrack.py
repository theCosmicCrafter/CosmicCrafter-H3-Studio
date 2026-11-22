import unittest
import torch
from h3_continuity import audio_tracks, audio_windows, timeline, nodes, dialogue, replacement
from .helpers import box, clip, parse

def parts():
    return [dict(frames=96,coverage=[dict(box='a',first=0,frames=96)]),dict(frames=12,coverage=[]),dict(frames=96,coverage=[dict(box='b',first=0,frames=96)])]


class SoundtrackWindowsTest(unittest.TestCase):
    def lane(self):
        lane=clip(start=0,source_start=0,duration=8,in_full_video=True)
        lane['box_windows']=audio_windows.capture(lane,[dict(id='a',start=0,duration=4),dict(id='b',start=4,duration=4)],{'file':lane['file']})
        lane['windows']=audio_windows.resolve(lane,[dict(id='a',start=0,duration=4),dict(id='b',start=4,duration=4)])
        return lane

    def test_bound_bridge_is_silent_and_ownership_survives_different_saved_duration(self):
        lane=self.lane();rate=11025
        source={'audio1':dict(waveform=torch.ones(1,1,10*rate)*.5,sample_rate=rate)}
        output,_=audio_tracks.place([lane],source,parts())
        self.assertTrue(torch.equal(output[:,4*rate:round(4.5*rate)],torch.zeros_like(output[:,4*rate:round(4.5*rate)])))
        self.assertEqual(output[0,round(4.5*rate)+10],.5)
        short=parts();short[0]=dict(frames=48,coverage=[dict(box='a',first=0,frames=48)])
        mapped=audio_windows.on_output(lane,lane['windows'],short)
        self.assertEqual(mapped[1]['source_start'],4)
        self.assertEqual(mapped[1]['start'],2.5)

    def test_continuous_lane_keeps_playing_through_bridge_and_empty_stays_selected(self):
        lane=self.lane(); continuous=dict(lane);continuous.pop('box_windows');continuous.pop('windows')
        old=audio_windows.on_output(continuous,audio_windows.resolve(continuous,[]),parts())
        self.assertEqual((old[0]['start'],old[0]['duration']),(0,8))
        lane['box_windows']['by_box']={}
        parsed=parse([box('a',96,exact=True)],audio_clips=[lane],requires=[audio_windows.FEATURE])
        marked=audio_tracks.marked(parsed)
        self.assertEqual(len(marked),1);self.assertEqual(marked[0]['windows'],[])
        wave,_=audio_tracks.place(marked,{'audio1':dict(waveform=torch.ones(1,1,44100),sample_rate=11025)},parts())
        self.assertEqual(wave.count_nonzero().item(),0)

    def test_replacement_coverage_and_equivalence(self):
        lane=self.lane()
        whole=[dict(frames=192,coverage=[dict(box='a',first=0,frames=96),dict(box='b',first=0,frames=96)])]
        split=[dict(frames=90,coverage=[dict(box='a',first=0,frames=90)]),dict(frames=12,coverage=[dict(box='a',first=90,frames=6),dict(box='b',first=0,frames=6)]),dict(frames=90,coverage=[dict(box='b',first=6,frames=90)])]
        self.assertTrue(audio_windows.equivalent(audio_windows.on_output(lane,lane['windows'],whole),audio_windows.on_output(lane,lane['windows'],split)))
        continuous=dict(lane);continuous.pop('box_windows')
        self.assertFalse(audio_windows.equivalent(audio_windows.on_output(lane,lane['windows'],parts()),audio_windows.on_output(continuous,audio_windows.resolve(continuous,[]),parts())))

    def test_sequence_clock_lock_covers_internal_gaps_and_box_boundaries(self):
        lane=self.lane();lane['locked']=True
        parsed=parse([box('a',240,exact=True),box('b',96,cut=True,exact=True)],audio_clips=[lane],requires=[audio_windows.FEATURE],bridges=[dict(before='b',frames=12)])
        self.assertTrue(any('inserts' in problem for problem in dialogue.lock_conflicts(parsed)))

    def test_replacement_identity_tracks_effective_bound_source_changes(self):
        lane=self.lane();lane['box_windows']['by_box']['b']['duration']=3
        def parsed(): return parse([box('a',107),box('b',107,cut=True)],audio_clips=[lane],requires=[audio_windows.FEATURE],bridges=[dict(before='b',mode='replace',left=14,right=15)])
        before=parsed();key=replacement.static_key(before,before.replacements[0],39)
        lane['box_windows']['by_box']['b']['source_start']+=.5
        after=parsed()
        self.assertNotEqual(key,replacement.static_key(after,after.replacements[0],39))

    def test_moved_adjacent_windows_never_repeat_or_borrow_boundary_samples(self):
        for rate in [11025,44100,48000]:
            wave=torch.arange(5*rate,dtype=torch.float32).reshape(1,1,-1)
            lane=clip(start=.031,source_start=1.13,duration=3)
            original=[dict(id='a',start=0,duration=1),dict(id='b',start=1,duration=25/24),dict(id='c',start=49/24,duration=1)]
            lane['box_windows']=audio_windows.capture(lane,original,{'file':lane['file']})
            for shift in [1,17,-17]:
                spans=[dict(original[0],duration=1+shift/24),dict(original[1],start=1+shift/24),dict(original[2],start=49/24+shift/24)]
                windows=audio_windows.resolve(lane,spans)
                b,c=windows[1:]
                first,last=round(b['start']*rate),round((spans[2]['start']+spans[2]['duration'])*rate)
                source=dict(waveform=wave,sample_rate=rate)
                heard=audio_tracks.samples(source,windows,first,last,lane['box_windows']['placement']).flatten()
                boundary=round(c['start']*rate)-first
                left=audio_tracks.samples(source,[b],first,first+boundary,lane['box_windows']['placement']).flatten()
                right=audio_tracks.samples(source,[c],first+boundary,last,lane['box_windows']['placement']).flatten()
                self.assertTrue(torch.equal(heard,torch.cat([left,right])))
                parsed=parse([box('a',24+shift,exact=True),box('b',25,cut=True,exact=True),box('c',24,cut=True,exact=True)],
                             audio_clips=[lane],requires=[audio_windows.FEATURE])
                native=[audio_tracks.for_box(parsed,index,0,{'audio1':source})['audio1']['waveform'].flatten() for index in (1,2)]
                self.assertTrue(torch.equal(heard,torch.cat(native)))
                nonzero=heard[heard!=0]
                self.assertTrue(torch.all(nonzero[1:]>nonzero[:-1]))
                end_source=round((lane['start']+b['source_start']+b['duration']-lane['source_start'])*rate)+round(lane['source_start']*rate)-round(lane['start']*rate)
                self.assertTrue(torch.all(left[left!=0]<end_source))
                output_parts=[dict(frames=frames,coverage=[dict(box=name,first=0,frames=frames)]) for name,frames in [('a',24+shift),('b',25),('c',24)]]
                marked=dict(lane,windows=windows,sample_clock=lane['box_windows']['placement'])
                output,_=audio_tracks.place([marked],{'audio1':dict(waveform=wave/(5*rate),sample_rate=rate)},output_parts)
                self.assertTrue(torch.equal(output[0,first:last],heard/(5*rate)))
