import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,writeFileSync} from 'node:fs';
import {readPromptFields,SHOT_FIELDS} from '../../../js/h3c_prompt_fields.mjs';
// h3_continuity/prompt_fields.py must read prompts exactly like the browser; tests/test_prompt_fields.py checks it against these results.
// After an intended browser change, rerun with H3_WRITE_PROMPT_CASES=1 to record the new results.
const url=new URL('../fixtures/prompt_field_cases.json',import.meta.url);
const fixture=JSON.parse(readFileSync(url,'utf8'));
const fields=()=>SHOT_FIELDS.map(({key,prefix,advanced,repeatable})=>({key,prefix,advanced,repeatable}));
const parsed=c=>JSON.parse(JSON.stringify({sections:readPromptFields(c.prompt,{tags:c.tags??[]}).sections}));
if(process.env.H3_WRITE_PROMPT_CASES) {
  fixture.fields=fields();for(const c of fixture.cases)c.expected=parsed(c);
  writeFileSync(url,JSON.stringify(fixture,null,1)+'\n');
}
test('the recorded prompt-field cases are the browser parser results the host reader must match',()=>{
  assert.deepEqual(fixture.fields,fields());
  for(const c of fixture.cases)assert.deepEqual(parsed(c),c.expected,c.name);
});
