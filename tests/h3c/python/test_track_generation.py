import copy
import json
import unittest
from h3_continuity import tracks,timeline as rules

def data():
 return dict(version=1,requires=[tracks.FEATURE],tracks=[dict(id='v1',type='video',name='Video 1'),dict(id='v2',type='video',name='Video 2')],boxes=[dict(id='A',track='v1',start=0,frames=56,cut=True,prompt='A field.',memory='off'),dict(id='C',track='v2',start=0,frames=22,cut=True,prompt='A close view.',memory='off'),dict(id='B',track='v1',start=56,frames=34,cut=False,prompt='Continue across the field.',memory='off')])
class TrackGenerationTest(unittest.TestCase):
 def test_interleaved_catalog_continues_same_track(self):
  parsed=rules.parse(json.dumps(data()))
  self.assertEqual(rules.previous_index(parsed,2),0)
  plan=rules.plan_box(parsed,2,39,False,256,256,'match',{},{});
  self.assertFalse(plan.fresh);self.assertEqual(plan.carried,39);self.assertEqual(plan.index,2)
  entries={1:dict(timeline=dict(box='A')),2:dict(timeline=dict(box='C'))}
  self.assertEqual(tracks.previous_entry(parsed,2,entries),entries[1])
 def test_gap_cannot_continue_or_replay_another_track(self):
  raw=data();raw['boxes'][2]['start']=60;parsed=rules.parse(json.dumps(raw))
  with self.assertRaisesRegex(ValueError,'adjacent'):rules.plan_box(parsed,2,39,False,256,256,'match',{}, {})
 def test_memory_checks_moment_time_not_catalog_order(self):
  raw=data();raw['boxes'][1].update(start=120,memory='selected',memories=[dict(box='B',frame=10)])
  parsed=rules.parse(json.dumps(raw));self.assertIn((2,10,'visual continuity'),rules.memory_sources(parsed,1))
  raw['boxes'][1]['memories']=[dict(box='C',frame=1)]
  with self.assertRaises(ValueError):rules.parse(json.dumps(raw))
 def test_first_on_track_scene_memory_never_uses_other_track(self):
  raw=data();raw['boxes'][1]['memory']='scene';parsed=rules.parse(json.dumps(raw))
  self.assertEqual(rules.memory_sources(parsed,1),[])
 def test_move_invalidates_layout_but_priority_does_not(self):
  raw=data();parsed=rules.parse(json.dumps(raw));before=rules.layout_key(parsed,1)
  raw['tracks'].reverse();self.assertEqual(rules.layout_key(rules.parse(json.dumps(raw)),1),before)
  raw['boxes'][1]['start']=24;self.assertNotEqual(rules.layout_key(rules.parse(json.dumps(raw)),1),before)

 def test_parsed_placement_uses_played_length_not_raw_length(self):
  raw=data();raw['boxes'][1]['frames']=23
  parsed=rules.parse(json.dumps(raw))
  self.assertEqual(parsed.placements['C']['end'],22)
