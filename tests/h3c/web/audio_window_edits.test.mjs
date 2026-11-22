import test from 'node:test';
import assert from 'node:assert/strict';
import * as model from '../../../js/h3c_timeline_model.mjs';
import {captureWindows, splitWindows, pruneWindows, unlockWindows} from '../../../js/h3c_audio_windows.mjs';
import {splitBox} from '../../../js/h3c_shot_split.mjs';
import {EditHistory, TimelineHistory} from '../../../js/h3c_history.mjs';

function state(offset=0) {
  const state=model.parseState(JSON.stringify({boxes:[{id:'a',frames:96,exact:true,prompt:'[Shot 1] Walk.\n[Shot 2] At 00:01.000, turn.'}],
    audio_clips:[{slot:'audio1',start:offset,source_start:30,duration:4-offset}]}));
  state.audio_clips[0].box_windows=captureWindows(state.audio_clips[0],model.audioBoxSpans(state),{source:'audio1'});
  return state;
}
test('new boxes are unassigned; moving/deleting preserves other assignments', () => {
  const s=state(); model.duplicateBox(s,0,0); model.addBox(s,0,96);
  assert.deepEqual(Object.keys(s.audio_clips[0].box_windows.by_box),['a']);
  model.moveBox(s,0,1,0);
  assert.equal(s.audio_clips[0].box_windows.by_box.a.source_start,30);
  model.removeBox(s,1,0);
  assert.deepEqual(s.audio_clips[0].box_windows.by_box,{});
});
test('splitting a shortened box partitions the hidden tail once, including leading gaps', () => {
  const s=state(); s.boxes[0].frames=48;
  splitBox(s,0,2,0);
  const [a,b]=s.boxes.map(box=>box.id), windows=s.audio_clips[0].box_windows.by_box;
  assert.deepEqual(windows[a],{offset:0,source_start:30,duration:1});
  assert.deepEqual(windows[b],{offset:0,source_start:31,duration:3});
  const gap=state(2); gap.boxes.push({id:'right',frames:96});
  splitWindows(gap,'a','a','right',1);
  assert.equal(gap.audio_clips[0].box_windows.by_box.a,undefined);
  assert.deepEqual(gap.audio_clips[0].box_windows.by_box.right,{offset:1,source_start:30,duration:2});
});
test('unlock, history round trips and failed restore preserve full nested bindings', () => {
  const s=state(), original=structuredClone(s.audio_clips[0].box_windows), history=new EditHistory({timeline:s});
  s.boxes[0].frames=48; history.record({timeline:s},'Shorten');
  unlockWindows(s.audio_clips[0]); history.record({timeline:s},'Unlock');
  assert.equal(s.audio_clips[0].box_windows,undefined);
  assert.deepEqual(history.jump(1).timeline.audio_clips[0].box_windows,original);
  assert.equal(history.jump(2).timeline.audio_clips[0].box_windows,undefined);
  const live={timeline:state()}, fail=new TimelineHistory({read:()=>live,identity:()=>1,apply:()=>{throw Error('save failed');},notify:()=>{},group:()=>null,flush:()=>{}});
  live.timeline.boxes[0].frames=48;fail.capture();
  assert.throws(()=>fail.undo(),/save failed/); assert.equal(fail.index,1);
  assert.deepEqual(fail.value.timeline.audio_clips[0].box_windows,original);
  live.timeline.boxes=[]; pruneWindows(live.timeline);
  assert.deepEqual(live.timeline.audio_clips[0].box_windows.by_box,{});
});

test('grid padding and omitted replay-only halves never borrow another owner', () => {
  const s=state(); delete s.boxes[0].exact; s.boxes[0].frames=107;
  const timing=splitBox(s,0,2,0), map=s.audio_clips[0].box_windows.by_box;
  assert.ok(timing.added>0); assert.equal(map.a.duration,1);
  assert.equal(map[s.boxes[1].id].source_start,31);
  const replay=state();replay.boxes.unshift({id:'prior',frames:107,prompt:''});
  replay.boxes[1].prompt='[Shot 1] Replay.\n[Shot 2] At 00:01.625, turn.';
  splitBox(replay,1,2,39);
  assert.equal(replay.boxes.length,2);
  assert.deepEqual(replay.audio_clips[0].box_windows.by_box.a,{offset:0,source_start:30,duration:4});
});
