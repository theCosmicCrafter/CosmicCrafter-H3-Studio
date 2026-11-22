import json
import os
import tempfile
import unittest
from pathlib import Path
import numpy as np
import torch
import av
from tests.h3c.continuity_support import enable_comfy_cpu
enable_comfy_cpu()
from h3_continuity import track_output,tracks,timeline as rules,media

def parsed():
 return rules.parse(json.dumps(dict(version=1,requires=[tracks.FEATURE],tracks=[dict(id='v1',type='video',name='Video 1'),dict(id='v2',type='video',name='Video 2')],boxes=[dict(id='A',track='v1',start=0,frames=90,exact=True,cut=True,prompt='A field.'),dict(id='B',track='v2',start=27,frames=33,exact=True,cut=True,prompt='A detail.') ])))
class TrackOutputTest(unittest.TestCase):
 def test_top_track_reveals_lower_through_gaps(self):
  spans=track_output.edit_list(parsed(),dict(segments=[]))
  self.assertEqual([(p['outputEnd']-p['outputStart'],p['sources'][0]['id']) for p in spans],[(27,'A'),(33,'B'),(30,'A')])
  self.assertEqual(spans[-1]['sources'][0]['first'],60)
 def test_fade_uses_existing_centered_weights_and_offsets(self):
  p=parsed();p.overlap_switches=[dict(id='sw',**{'from':'A','to':'B','at':40,'fade':6,'sound':'screen'})]
  spans=track_output.edit_list(p,dict(segments=[]));at40=next(s for s in spans if s['outputStart']==40)
  self.assertEqual([s['weight'] for s in at40['sources']],[.5,.5]);self.assertEqual([s['first'] for s in at40['sources']],[40,13])
 def test_real_output_contains_correct_source_pixels_and_duration(self):
  with tempfile.TemporaryDirectory() as folder:
   entries=[]
   for index,(name,count,channel) in enumerate([('A',90,0),('B',33,2)],1):
    images=torch.zeros(count,32,48,3);images[:,:,:,channel]=.7
    media.write_segment_video(os.path.join(folder,name+'.mp4'),images,24,16)
    entries.append(dict(index=index,stem=name,frames=count,context_frames=0,timeline=dict(box=name),video=dict(file=name+'.mp4',fps=24,frames=count)))
   record,notes=track_output.build(folder,'test',parsed(),dict(segments=entries),16,'full')
   self.assertTrue(record,notes)
   with av.open(os.path.join(folder,record['file'])) as container: frames=[f.to_ndarray(format='rgb24') for f in container.decode(video=0)]
   self.assertEqual(len(frames),90)
   self.assertEqual([int(frames[i].mean(axis=(0,1)).argmax()) for i in [0,26,27,59,60,89]],[0,0,2,2,0,0])
 def test_missing_upper_take_refuses_full_and_limits_so_far(self):
  spans=track_output.edit_list(parsed(),dict(segments=[]))
  self.assertEqual(spans[1]['sources'][0]['id'],'B')
  with tempfile.TemporaryDirectory() as folder:
   result,note=track_output.build(folder,'test',parsed(),dict(segments=[]),16,'full')
   self.assertIsNone(result);self.assertIn('A',note)

 def test_independent_text_lanes_reach_native_prompt_without_overwrite(self):
  p=parsed()
  def attachment(text):
   return dict(version=1,enabled=True,sync_audio=False,audio_slot='audio1',source_name='words.json',source_sha256='a'*64,start=0,source_start=0,duration=5,direction='Bottom left',cues=[dict(id='cue1',start=0,end=1,text=text)])
  p.text_lanes=[dict(track='t1',attachment=attachment('One')),dict(track='t2',attachment=attachment('Two'))]
  plan=rules.plan_box(p,0,39,False,256,256,'match',{}, {})
  self.assertIn('One',plan.prompt);self.assertIn('Two',plan.prompt)
  self.assertEqual(len(plan.text_window['cues']),2)
  self.assertEqual(rules.frame_text(p,0,0,39)['visible_text'],['One','Two'])

 def test_missing_upper_does_not_export_lower_as_complete(self):
  with tempfile.TemporaryDirectory() as folder:
   images=torch.zeros(90,32,48,3);images[:,:,:,0]=.7
   media.write_segment_video(os.path.join(folder,'A.mp4'),images,24,16)
   entry=dict(index=1,stem='A',frames=90,context_frames=0,timeline=dict(box='A'),video=dict(file='A.mp4',fps=24,frames=90))
   manifest=dict(segments=[entry])
   record,note=track_output.build(folder,'test',parsed(),manifest,16,'full')
   self.assertIsNone(record);self.assertIn('B',note)
   record,note=track_output.build(folder,'test',parsed(),manifest,16,'so_far')
   self.assertEqual(record['frames'],27);self.assertIn('B',note)
   record,note=track_output.build(folder,'test',parsed(),manifest,16,'partial')
   self.assertEqual(record['frames'],90);self.assertIn('B',note)
 def test_third_track_keeps_priority_over_switch_pair(self):
  p=parsed();p.tracks.append(dict(id='v3',type='video',name='Video 3'))
  p.boxes.append(rules.Box('C',10,'Close',1,True,'',''));p.exact.append(True)
  p.placements['C']=dict(id='C',track='v3',start=36,end=46)
  p.overlap_switches=[dict(id='sw',**{'from':'A','to':'B','at':40,'fade':6,'sound':'screen'})]
  spans=track_output.edit_list(p,dict(segments=[]))
  at40=next(s for s in spans if s['outputStart']<=40<s['outputEnd'])
  self.assertEqual(at40['sources'][0]['id'],'C')

 def test_materialized_status_uses_track_movie_and_clock(self):
  from h3_continuity import store,timeline_node,nodes
  from unittest import mock
  with tempfile.TemporaryDirectory() as folder:
   entries=[]
   for index,(name,count) in enumerate([('A',90),('B',33)],1):
    media.write_segment_video(os.path.join(folder,name+'.mp4'),torch.zeros(count,32,48,3),24,16)
    entries.append(dict(index=index,stem=name,frames=count,context_frames=0,timeline=dict(box=name),video=dict(file=name+'.mp4',fps=24,frames=count)))
   store.write_manifest(folder,dict(segments=entries))
   with mock.patch('h3_continuity.timeline_api.service.authorize_sequence',lambda *a,**k:None):
    status=timeline_node._status('test',folder,parsed(),store.load_manifest(folder),lambda i,e:True,materialize=True)
    nodes.wait_full_video(folder,30)
    status=timeline_node._status('test',folder,parsed(),store.load_manifest(folder),lambda i,e:True,materialize=True)
   self.assertIsNotNone(status['full_video']);self.assertEqual(status['seconds'],3.75)
   self.assertEqual(status['full_video_clock'],[[0,90,0,1]])

 def test_generated_audio_follows_visible_clip_and_lower_return_offset(self):
  from h3_continuity import store
  with tempfile.TemporaryDirectory() as folder:
   entries=[]
   for index,(name,count,value) in enumerate([('A',90,.1),('B',33,.6)],1):
    media.write_segment_video(os.path.join(folder,name+'.mp4'),torch.zeros(count,32,48,3),24,16)
    entry=dict(index=index,stem=name,frames=count,context_frames=0,audio_sample_rate=8000,timeline=dict(box=name),video=dict(file=name+'.mp4',fps=24,frames=count))
    store.save_segment(folder,entry,torch.zeros(1,24,1,1,1),torch.zeros(1,1),torch.full((2,round(count/24*8000)),value))
    entries.append(entry)
   record,note=track_output.build(folder,'test',parsed(),dict(segments=entries),16,'full')
   converter=av.AudioResampler(format='fltp',layout='stereo',rate=8000)
   with av.open(os.path.join(folder,record['file'])) as container:
    chunks=[p.to_ndarray() for f in container.decode(audio=0) for p in converter.resample(f)]
   chunks.extend(p.to_ndarray() for p in converter.resample(None));wave=np.concatenate(chunks,axis=1)
   for second,want in [(.5,.1),(1.5,.6),(3,.1)]:self.assertAlmostEqual(float(wave[:,int(second*8000):int((second+.1)*8000)].mean()),want,delta=.04)
   self.assertGreaterEqual(wave.shape[1],30000);self.assertLess(wave.shape[1],31024)
 def test_empty_picture_interval_is_black_and_bridges_pause_all_tracks(self):
  p=parsed();p.placements['A'].update(start=12,end=102);p.placements['B'].update(start=39,end=72)
  p.all_bridges=[dict(before='B',frames=12)]
  spans=track_output.edit_list(p,dict(segments=[]))
  self.assertEqual(spans[0]['sources'],[]);self.assertEqual(spans[0]['outputEnd'],12)
  bridge=next(s for s in spans if s['bridgeId'])
  self.assertEqual((bridge['outputStart'],bridge['outputEnd']),(39,51))
  resumed=next(s for s in spans if s['outputStart']==51)
  self.assertEqual(resumed['sources'][0]['first'],0)

 def test_superseded_outputs_are_removed_and_recorded_ones_kept(self):
  with tempfile.TemporaryDirectory() as folder:
   for name in ['tracks@old.mp4','tracks@full.mp4','tracks@so.mp4','other.mp4']:Path(folder,name).write_bytes(b'x')
   track_output.discard_superseded(folder,dict(track_full=dict(file='tracks@full.mp4'),track_so_far=dict(file='tracks@so.mp4'),segments=[]))
   self.assertEqual(sorted(os.listdir(folder)),['other.mp4','tracks@full.mp4','tracks@so.mp4'])
