import copy
import json
from pathlib import Path
import unittest
from h3_continuity import tracks, timeline as rules
FIXTURE=json.loads((Path(__file__).parents[1]/'fixtures/timeline_tracks.json').read_text())
class TracksTest(unittest.TestCase):
 def test_shared_placements_and_catalog_independent_predecessor(self):
  data=copy.deepcopy(FIXTURE); parsed=rules.parse(json.dumps(data))
  self.assertEqual(tracks.placements(data),[dict(id='A',track='v1',start=0,end=48),dict(id='C',track='v2',start=24,end=72),dict(id='B',track='v1',start=48,end=120)])
  self.assertEqual(tracks.duration_frames(data),120)
  self.assertEqual(tracks.predecessor(data,'B'),'A');self.assertIsNone(tracks.predecessor(data,'C'))
  self.assertEqual(parsed.tracks,data['tracks'])
 def test_reject_invalid_placements(self):
  for value in [-1,1.5,True]:
   data=copy.deepcopy(FIXTURE);data['boxes'][0]['start']=value
   with self.assertRaisesRegex(ValueError,'start'):rules.parse(json.dumps(data))
  for track in ['missing','a1']:
   data=copy.deepcopy(FIXTURE);data['boxes'][0]['track']=track
   with self.assertRaises(ValueError):rules.parse(json.dumps(data))
 def test_same_track_collision_and_missing_feature_rejected(self):
  data=copy.deepcopy(FIXTURE);data['boxes'][2]['start']=20
  with self.assertRaisesRegex(ValueError,'overlap'):rules.parse(json.dumps(data))
  data=copy.deepcopy(FIXTURE);data['requires']=[]
  with self.assertRaisesRegex(ValueError,'timeline-tracks-1'):rules.parse(json.dumps(data))

 def test_api_declares_track_fields(self):
  from h3_continuity.timeline_api import contracts
  data=copy.deepcopy(FIXTURE)
  self.assertEqual(contracts.validate('timeline',data),data)
  data['boxes'][0]['start']=True
  with self.assertRaises(contracts.APIError): contracts.validate('timeline',data)
 def test_overlap_bounds_and_duplicate_ids(self):
  for patch in [dict(at=24,fade=6),dict(at=70,fade=6),dict(to='A'),dict(sound='missing')]:
   data=copy.deepcopy(FIXTURE);data['overlap_switches']=[dict(id='sw',**{'from':'A','to':'C','at':40,'fade':6,'sound':'screen'})];data['overlap_switches'][0].update(patch)
   with self.assertRaises(ValueError):rules.parse(json.dumps(data))
  data=copy.deepcopy(FIXTURE);data['tracks'].append(copy.deepcopy(data['tracks'][0]))
  with self.assertRaises(ValueError):rules.parse(json.dumps(data))

 def test_tracks_share_authoring_time_and_insertion_output_clock(self):
  data=copy.deepcopy(FIXTURE);data['bridges']=[dict(before='B',frames=12)]
  parsed=rules.parse(json.dumps(data))
  self.assertEqual(rules.box_start(parsed,1),1)
  self.assertEqual(rules.audio_box_spans(parsed)[1]['start'],1)
  self.assertEqual(tracks.output_frame(data,48),60)
  self.assertEqual(tracks.timeline_frame(data,53),dict(frame=48,bridgeId='B'))
  self.assertEqual(tracks.timeline_frame(data,84),dict(frame=72,bridgeId=None))
  self.assertEqual(tracks.output_spans(data)[-1]['outputEnd'],132)


class LegacyConversionTest(unittest.TestCase):
 def test_converting_to_tracks_keeps_every_layout_key(self):
  legacy=dict(version=1,boxes=[dict(id='A',frames=39,exact=True,cut=True,prompt='One.'),dict(id='B',frames=39,exact=True,cut=False,prompt='Two.'),
                               dict(id='C',frames=39,exact=True,cut=True,prompt='Three.')])
  converted=copy.deepcopy(legacy);converted['requires']=[tracks.FEATURE];converted['tracks']=[dict(id='v1',type='video',name='Video 1')]
  for box,start in zip(converted['boxes'],[0,39,78]):box.update(track='v1',start=start)
  before,after=rules.parse(json.dumps(legacy)),rules.parse(json.dumps(converted))
  self.assertEqual([rules.layout_key(before,i) for i in range(3)],[rules.layout_key(after,i) for i in range(3)])
  converted['boxes'][2]['start']=120
  moved=rules.parse(json.dumps(converted))
  self.assertNotEqual(rules.layout_key(before,2),rules.layout_key(moved,2))
