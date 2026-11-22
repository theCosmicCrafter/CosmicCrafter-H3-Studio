import test from 'node:test';
import assert from 'node:assert/strict';
import {projectTimedText,textClock,setTextSync} from '../../../js/h3c_timed_text.mjs';
import {cuesFromStory} from '../../../js/h3c_dialogue.mjs';
import {resolveWindows,captureWindows} from '../../../js/h3c_audio_windows.mjs';
const boxes=[{id:'a',start:0,duration:4},{id:'b',start:4,duration:4}];
test('synced text follows bound windows, independent text keeps its clock',()=>{
  const lane={slot:'audio1',start:0,source_start:0,duration:8};lane.box_windows=captureWindows(lane,boxes,{source:'audio1'});
  const moved=[{id:'a',start:0,duration:6},{id:'b',start:6,duration:4}];
  const placements=resolveWindows(lane,moved).map(w=>({...w,slot:'audio1'}));
  const value={enabled:true,sync_audio:true,audio_slot:'audio1',start:0,source_start:0,duration:8,direction:'',cues:[{id:'x',start:5,end:6,text:' Hello'}]};
  assert.equal(projectTimedText(value,[lane],6,96,0,placements).cues[0].start_ms,1000);
  assert.equal(projectTimedText(value,[lane],4,48,0,placements).cues.length,0);
  assert.equal(projectTimedText({...value,sync_audio:false},[lane],4,96,0,placements).cues[0].start_ms,1000);
  assert.ok(textClock(value,[lane]).box_windows);
});

test('detaching text refuses a discontinuous clock without changing its data',()=>{
  const lane={slot:'audio1',start:0,source_start:0,duration:8};lane.box_windows=captureWindows(lane,boxes,{source:'audio1'});
  const state={boxes:[{id:'a',frames:144},{id:'b',frames:96}],audio_clips:[lane],timed_text:{sync_audio:true,audio_slot:'audio1',start:0,source_start:0,duration:8}};
  const before=structuredClone(state.timed_text);
  assert.throws(()=>setTextSync(state,false),/unlock|continuous/i);
  assert.deepEqual(state.timed_text,before);
  state.boxes[0].frames=96;setTextSync(state,false);
  assert.equal(state.timed_text.sync_audio,false);
  assert.deepEqual([state.timed_text.start,state.timed_text.source_start,state.timed_text.duration],[0,0,8]);
});

test('Story lines invert bound windows and skip gaps instead of using a scalar offset',()=>{
  const lane={slot:'audio1',file:{type:'input',filename:'voice.wav'},start:0,source_start:0,duration:8};lane.box_windows=captureWindows(lane,boxes,{file:lane.file});
  const line=(start_ms,end_ms,text)=>({start_ms,end_ms,text,speaker:'Mara'});
  const state={boxes:[{id:'a',frames:144,source:{reply:{shots:[{dialogue:[line(4500,5000,'gap')]}]}}},
    {id:'b',frames:96,cut:true,source:{reply:{shots:[{dialogue:[line(1000,1500,'Hello')]}]}}}],audio_clips:[lane]};
  const result=cuesFromStory(state,lane,[],0);
  assert.equal(result.skipped,1);assert.equal(result.cues.length,1);
  assert.deepEqual([result.cues[0].start,result.cues[0].end],[5,5.5]);
});
