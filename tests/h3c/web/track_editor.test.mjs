import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {snapPlacement,visibleSpans,placeClip} from '../../../js/h3c_track_editor.mjs';
const fixture=()=>JSON.parse(fs.readFileSync(new URL('../fixtures/timeline_tracks.json',import.meta.url)));
test('cross-track edges snap and Shift bypass preserves exact drag position',()=>{
 const s=fixture();let p=snapPlacement(s,{id:'C',track:'v2',start:49,end:97,tolerance:3});assert.equal(p.start,48);assert.equal(p.end,96);assert.equal(p.guide,48);
 p=snapPlacement(s,{id:'C',track:'v2',start:49,end:97,tolerance:3,bypass:true});assert.equal(p.start,49);assert.equal(p.guide,null);
});
test('placement rejects same-track collisions without partial edits',()=>{
 const s=fixture(),before=structuredClone(s);assert.throws(()=>placeClip(s,'C','v1',20),/overlap/);assert.deepEqual(s,before);
 placeClip(s,'C','v2',48);assert.equal(s.boxes[1].start,48);
});
test('combined row represents uppermost picture and lower return with stable IDs',()=>{
 const s=fixture();assert.deepEqual(visibleSpans(s).map(p=>[p.start,p.end,p.id]),[[0,24,'A'],[24,72,'C'],[72,120,'B']]);
});

test('moving a clip away from its insertion bridge is refused and deleting a lane forgets its clips',async()=>{
 const {TrackEditor}=await import('../../../js/h3c_track_editor.mjs');
 const s=fixture();s.bridges=[{before:'B',frames:12}];s.boxes[2].cut=true;
 const model=await import('../../../js/h3c_timeline_model.mjs');
 assert.deepEqual(model.keptBridges(s).map(b=>b.before),['B']);
 s.boxes[2].start=60;assert.deepEqual(model.keptBridges(s),[]);
 const t=fixture();t.audio_clips=[{slot:'audio1',track:'a1',box_windows:{by_box:{C:{offset:0,duration:1},A:{offset:0,duration:1}}}}];
 t.bible={entities:[{id:'e',pins:[{box:'C'},{box:'A'}],looks:[{from:'C'},{from:'A'}]}]};
 const gone=t.boxes.filter(b=>b.track==='v2').map(b=>b.id);
 const tracks=await import('../../../js/h3c_tracks.mjs');
 tracks.removeTrack(t,'v2');model.forgetBoxes(t,gone);
 assert.deepEqual(Object.keys(t.audio_clips[0].box_windows.by_box),['A']);
 assert.deepEqual(t.bible.entities[0].pins,[{box:'A'}]);assert.deepEqual(t.bible.entities[0].looks,[{from:'A'}]);
});
