import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import * as prompts from '../../../js/h3c_prompt_sections.mjs';
const fixtures=JSON.parse(readFileSync(new URL('../fixtures/prompt_forms.json',import.meta.url),'utf8'));

test('partial sections and complete prompts round trip without changing Unicode or CRLF',()=>{
  for(const source of Object.values(fixtures)) {
    const sections=prompts.promptSections(source);
    if(source===fixtures.raw) assert.equal(sections,null);
    else {assert.ok(sections);assert.equal(prompts.writePromptSections(source,sections),source);}
  }
  assert.deepEqual(prompts.promptShots(fixtures.partial).shots,[]);
});
test('literal structure inside dialogue never creates sections or shots',()=>{
  assert.deepEqual(prompts.promptShots(fixtures.dialogue).shots.map(s=>s.label),['[Shot 1]']);
  assert.deepEqual(prompts.promptSections(fixtures.dialogue).map(s=>s.key),['integrated_multimodal_description','overall_soundscape']);
});
test('unknown and duplicate sections remain opaque, separate from typed fields',()=>{
  const unknown=prompts.promptSections(fixtures.unknown);
  assert.equal(unknown[0].fields[0].value,'Keep this.');
  assert.equal(unknown[1].key,'existing');
  assert.match(unknown[1].fields[0].value,/custom_section:/);
  assert.equal(prompts.promptSections(fixtures.duplicate).filter(s=>s.key==='summary').length,0);
});
test('prose lines that start with a lowercase word and a colon stay inside their shot',()=>{
  for(const line of ['note: she is tired','https://example.com/ref']) {
    const source=`integrated_multimodal_description:\n[Shot 1] A woman walks in.\n${line}\n[Shot 2] At 00:03.000, She sits.\n\noverall_soundscape: Rain.`;
    assert.deepEqual(prompts.promptShots(source).shots.map(s=>s.value),[`A woman walks in.\n${line}`,'At 00:03.000, She sits.']);
  }
});
test('entry ranges include the label and body but preserve surrounding source',()=>{
  const source=fixtures.partial, field=prompts.promptSections(source)[0].fields[0];
  assert.equal(source.slice(field.entryStart,field.entryEnd),'<Subject 1> is Zoë 😀.');
  assert.equal(prompts.replacePromptRanges?.(source,[{start:field.start,end:field.end,before:field.value,text:'is Mara.'}]),
    'subject_definitions:\r\n<Subject 1> is Mara.\r\n');
});
test('range patches reject stale offsets, overlap and noninteger bounds',()=>{
  assert.equal(prompts.replacePromptRanges?.('😀 abc',[]),'😀 abc');
  assert.equal(prompts.replacePromptRanges?.('😀 abc',[{start:3,end:6,before:'abc',text:'Zoë'}]),'😀 Zoë');
  for(const patches of [[{start:0,end:1,before:'X',text:'Y'}],[{start:-1,end:2,before:'',text:''}],
    [{start:1.5,end:2,before:'',text:''}], [{start:0,end:2,before:'ab',text:'x'},{start:1,end:3,before:'bc',text:'y'}]]) {
    assert.throws(()=>prompts.replacePromptRanges('abc',patches));
  }
});
