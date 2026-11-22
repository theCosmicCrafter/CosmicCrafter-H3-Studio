import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {overlapDraft,editOverlap} from '../../../js/h3c_overlap_inspector.mjs';
const fixture=()=>JSON.parse(fs.readFileSync(new URL('../fixtures/timeline_tracks.json',import.meta.url)));
test('overlap controls are bounded to the selected clip pair',()=>{
 const s=fixture(),draft=overlapDraft(s,'A','C');assert.equal(draft.start,24);assert.equal(draft.end,48);assert.equal(draft.value.at,36);
 editOverlap(s,'A','C',{...draft.value,id:'switch1',at:40,fade:6});assert.equal(s.overlap_switches[0].at,40);
 const before=structuredClone(s);assert.throws(()=>editOverlap(s,'A','C',{...draft.value,id:'switch1',at:47,fade:6}),/overlap/);assert.deepEqual(s,before);
 editOverlap(s,'A','C',null);assert.deepEqual(s.overlap_switches,[]);
});
test('existing switches retain explicit sound selection and orientation',()=>{
 const s=fixture();s.overlap_switches=[{id:'switch1',from:'C',to:'A',at:40,fade:6,sound:'C'}];
 assert.deepEqual(overlapDraft(s,'A','C').value,s.overlap_switches[0]);
});
