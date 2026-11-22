import {test} from 'node:test';
import assert from 'node:assert/strict';
import {parseState,serialize} from '../../../js/h3c_timeline_model.mjs';
import {shotTiming,editPromptShot} from '../../../js/h3c_prompt_shots.mjs';
const file={filename:'g.png',subfolder:'h3_previews',type:'output'};
function fixture({carry=false,previews=[],extra=''}={}) {
  const boxes=[...(carry?[{id:'a',frames:96,exact:true,seed:1,prompt:'[Shot 1] An opening.'}]:[]),
    {id:'b',frames:192,exact:true,seed:2,cut:!carry,previews,
      prompt:`${extra}integrated_multimodal_description:\n[Shot 1] A room.\n[Shot 2] At 00:02.000, the camera cuts to a doorway.\n[Shot 3] At 00:04.000, the camera cuts to her hand.`}];
  return parseState(JSON.stringify({boxes}));
}
test('seconds validate both neighbours and leave the input unchanged',()=>{
  const state=fixture(),before=serialize(state);
  for(const seconds of [NaN,Infinity,-1,0,4,8,'',null])assert.throws(()=>editPromptShot(state,0,{kind:'set-start',shot:2,seconds},39));
  const next=editPromptShot(state,0,{kind:'set-start',shot:2,seconds:2.5},39);
  assert.match(next.boxes[0].prompt,/At 00:02\.500,/);assert.equal(serialize(state),before);
  assert.equal(shotTiming(next,0,39).shots[0].editable,false);
});
test('continuing playback seconds include replay only in the native prompt clock',()=>{
  const state=fixture({carry:true});
  const next=editPromptShot(state,1,{kind:'set-start',shot:2,seconds:2},39);
  assert.match(next.boxes[1].prompt,/At 00:03\.625,/);
  assert.equal(shotTiming(next,1,39).shots[1].seconds,2);
  assert.match(editPromptShot(state,1,{kind:'set-start',shot:2,seconds:0},39).boxes[1].prompt,/At 00:01\.625,/);
});
test('timing edits protect accepted targeted guides and preserve legacy guides',()=>{
  const state=fixture({previews:[{target:{kind:'shot',shot:2},frame:48,guide:file}]});
  assert.throws(()=>editPromptShot(state,0,{kind:'set-start',shot:2,seconds:3},39),/guide/i);
  const legacy=fixture({previews:[{shot:99,frame:17,guide:file}]});
  assert.deepEqual(editPromptShot(legacy,0,{kind:'set-start',shot:2,seconds:3},39).boxes[0].previews,legacy.boxes[0].previews);
});
test('safe shot deletion remaps retention and surviving targets without moving a guide',()=>{
  const state=fixture({extra:'retention_analysis:\n<Subject 1> (appears in [Shot 2], [Shot 3]): fully_preserved - Appearance.\n',
    previews:[{target:{kind:'shot',shot:3},frame:96,guide:file}]});
  const next=editPromptShot(state,0,{kind:'remove',shot:2},39);
  assert.match(next.boxes[0].prompt,/appears in \[Shot 2\]\):/);
  assert.doesNotMatch(next.boxes[0].prompt,/\[Shot 3\]/);
  assert.deepEqual(next.boxes[0].previews[0].target,{kind:'shot',shot:2});
  assert.equal(next.boxes[0].previews[0].frame,96);
});
test('unknown references block renumbering; dialogue-looking references remain literal',()=>{
  const state=fixture();state.boxes[0].prompt+='\nA note refers to [Shot 3].';
  assert.throws(()=>editPromptShot(state,0,{kind:'remove',shot:2},39),/reference/i);
  state.boxes[0].prompt=state.boxes[0].prompt.replace('A note refers to [Shot 3].','<d>[English] Remember [Shot 3].</d>');
  assert.match(editPromptShot(state,0,{kind:'remove',shot:2},39).boxes[0].prompt,/<d>\[English\] Remember \[Shot 3\]\.<\/d>/);
});
test('cut and continue are explicit and preserve the timestamp',()=>{
  const state=fixture();
  const next=editPromptShot(state,0,{kind:'set-cut',shot:2,cut:false},39);
  assert.match(next.boxes[0].prompt,/At 00:02\.000, the view continues without a cut\./);
});
test('the first appended shot starts at zero without a timestamp and untouched shots keep their whitespace',()=>{
  const empty=fixture();empty.boxes[0].prompt='';
  assert.equal(editPromptShot(empty,0,{kind:'append',seconds:0,text:'A room.'},39).boxes[0].prompt,'[Shot 1] A room.');
  const state=fixture();state.boxes[0].prompt=state.boxes[0].prompt.replace('[Shot 1] A room.','[Shot 1]\n  A room.');
  assert.match(editPromptShot(state,0,{kind:'remove',shot:2},39).boxes[0].prompt,/\[Shot 1\]\n  A room\./);
});
