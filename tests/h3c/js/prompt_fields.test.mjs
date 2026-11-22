import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readPromptFields,writePromptField} from '../../../js/h3c_prompt_fields.mjs';
test('retention controls create exact subject and picture scope syntax',()=>{
  const source='retention_analysis:\n';
  const value={target:'<Subject 1>',shots:[1,3],scope:'',relationship:'fully_preserved',detail:'Keeps the coat.'};
  const next=writePromptField(source,{expectedSource:source,section:'retention_analysis',kind:'retention',entry:null,value});
  assert.equal(next,source+'<Subject 1> (appears in [Shot 1], [Shot 3]): fully_preserved - Keeps the coat.');
  assert.deepEqual(readPromptFields(next).sections[0].entries[0].value,value);
});
test('custom markers and opaque content survive reload and a local field edit',()=>{
  const source='retention_analysis:\n<Subject 1>: my_custom_relation - Keep this.\n\ncustom_section: untouched 😀';
  const entry=readPromptFields(source).sections[0].entries[0];
  const next=writePromptField(source,{expectedSource:source,section:'retention_analysis',kind:'retention',entry,value:{...entry.value,detail:'Changed.'}});
  assert.equal(next,'retention_analysis:\n<Subject 1>: my_custom_relation - Changed.\n\ncustom_section: untouched 😀');
});
test('stable slots are not retargeted when native reference numbering changes',()=>{
  const source='subject_definitions:\n@image17 is the opening frame.';
  for(const tags of [[{name:'image17',tag:'<Picture 1>'}],[{name:'image20',tag:'<Picture 1>'}]])
    assert.equal(readPromptFields(source,{tags}).sections[0].entries[0].value.target,'@image17');
  const unresolved=readPromptFields('retention_analysis:\n<Picture 9>: fully_preserved - Frame.');
  assert.equal(unresolved.sections[0].entries[0].kind,'existing');
});
test('deleting a referenced subject and applying stale source ranges are rejected',()=>{
  const source='subject_definitions:\n<Subject 1> is Mara.\ndetailed_description:\n[Shot 1] <Subject 1> waits.';
  const entry=readPromptFields(source).sections[0].entries[0];
  const edit={expectedSource:source,section:'subject_definitions',kind:'definition',entry,value:null};
  assert.throws(()=>writePromptField(source,edit),/used|reference/i);
  assert.throws(()=>writePromptField(source+'!',edit),/changed/i);
});
test('optional lighting is a readable cue and multiline cue-looking values round trip',()=>{
  const source='integrated_multimodal_description:\n[Shot 1] A quiet room.';
  const text='Warm window light\nCamera movement: keep this literal';
  const next=writePromptField(source,{expectedSource:source,section:'integrated_multimodal_description',kind:'cue',shot:1,entry:null,
    value:{key:'lighting',index:null,text}});
  assert.equal(next,source+'\nLighting: Warm window light\n  Camera movement: keep this literal');
  const cues=readPromptFields(next).sections[0].entries.filter(e=>e.kind==='cue');
  assert.equal(cues.length,1);assert.equal(cues[0].value.text,text);
});
test('repeated actions are addressable and duplicate cue names stay opaque',()=>{
  const source='integrated_multimodal_description:\n[Shot 1] A room.\nAction: She lifts a cup.';
  const next=writePromptField(source,{expectedSource:source,section:'integrated_multimodal_description',kind:'cue',shot:1,entry:null,
    value:{key:'action',index:2,text:'She sets it down.'}});
  assert.match(next,/Action 1: She lifts a cup\.\nAction 2: She sets it down\./);
  const duplicate=readPromptFields('[Shot 1] A room.\nLighting: A.\nLighting: B.');
  assert.equal(duplicate.sections[0].entries.filter(e=>e.kind==='cue').length,0);
});
test('new detail rank does not reorder existing narrative or cue lines',()=>{
  const source='detailed_description:\n[Shot 1] A room.\nEnd state: She waits.';
  const next=writePromptField(source,{expectedSource:source,section:'detailed_description',kind:'cue',shot:1,entry:null,
    value:{key:'camera_movement',index:null,text:'A slow spiral around her left shoulder'}});
  assert.equal(next,'detailed_description:\n[Shot 1] A room.\nCamera movement: A slow spiral around her left shoulder\nEnd state: She waits.');
});
test('native dialogue preserves multilingual words and structure-looking lines verbatim',()=>{
  const source='integrated_multimodal_description:\n[Shot 1] She waits.';
  const words='营业中! “Wait.”\nsummary: stay\n  [Shot 9] is spoken text';
  const next=writePromptField(source,{expectedSource:source,section:'integrated_multimodal_description',kind:'dialogue',shot:1,entry:null,
    value:{speakers:['S1','S2'],identity:'<Subject 1> and <Subject 2>',language:'Chinese',text:words}});
  assert.ok(next.includes('<d>[Chinese] '+words+'</d>'));
  const entry=readPromptFields(next).sections[0].entries.find(e=>e.kind==='dialogue');
  assert.ok(entry);assert.equal(entry.value.text,words);assert.deepEqual(entry.value.speakers,['S1','S2']);
});
test('voiceover and audio continuation use native tokens once and recover their flags',()=>{
  const source='[Shot 1] A room.';
  const next=writePromptField(source,{expectedSource:source,section:'integrated_multimodal_description',kind:'dialogue',shot:1,entry:null,
    value:{speakers:['S3'],identity:'<Subject 1>',language:'English',text:'Wait.',voiceover:true,fromPrevious:true,cutoff:true}});
  assert.ok(next.includes('<d>[English] <scenetrans>Wait.<cutoff></d>'));
  assert.match(next,/lips remain completely closed/);
  const entry=readPromptFields(next).sections[0].entries.find(e=>e.kind==='dialogue');
  assert.equal(entry.value.text,'Wait.');assert.equal(entry.value.voiceover,true);assert.equal(entry.value.fromPrevious,true);assert.equal(entry.value.cutoff,true);
});
test('known uncued native speech is editable and changing a referenced speaker ID is rejected',()=>{
  const source='subject_definitions:\n@audio1 is the voice for <Subject 1> (S1).\ndetailed_description:\n[Shot 1] She waits. <Subject 1> (S1) says: <d>[English] Hello.</d>';
  const entry=readPromptFields(source).sections.find(s=>s.key==='detailed_description').entries.find(e=>e.kind==='dialogue');
  assert.ok(entry);assert.equal(entry.value.text,'Hello.');
  assert.throws(()=>writePromptField(source,{expectedSource:source,section:'detailed_description',kind:'dialogue',entry,value:{...entry.value,speakers:['S2']}}),/speaker.*used|referenc/i);
});
test('a description added after an empty timed shot keeps the native comma separator',()=>{
  const source='[Shot 1] A room.\n[Shot 2] At 00:02.500,';
  const entry=readPromptFields(source).sections[0].entries.find(e=>e.kind==='narrative'&&e.shot===2);
  const next=writePromptField(source,{expectedSource:source,section:'integrated_multimodal_description',kind:'narrative',entry,value:{text:'the camera cuts to her hands.'}});
  assert.ok(next.endsWith('[Shot 2] At 00:02.500, the camera cuts to her hands.'));
});
test('dialogue language delimiters and mutually exclusive ending flags are validated',()=>{
  const source='[Shot 1] A room.';
  const edit={expectedSource:source,section:'integrated_multimodal_description',kind:'dialogue',shot:1,entry:null,
    value:{speakers:['S1'],language:'[English]',identity:'',text:'Hello.'}};
  assert.throws(()=>writePromptField(source,edit),/language/i);
  assert.throws(()=>writePromptField(source,{...edit,value:{...edit.value,language:'English',toNext:true,cutoff:true}}),/continue|cut off/i);
});
