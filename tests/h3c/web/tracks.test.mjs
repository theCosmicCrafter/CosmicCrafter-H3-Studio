import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import * as tracks from '../../../js/h3c_tracks.mjs';
import * as model from '../../../js/h3c_timeline_model.mjs';
const fixture=JSON.parse(fs.readFileSync(new URL('../fixtures/timeline_tracks.json',import.meta.url)));
const sample=()=>structuredClone(fixture);
test('independent placements use shared time and same-track predecessor',()=>{
 const s=sample(); tracks.validate(s);
 assert.deepEqual(tracks.placements(s),[{id:'A',track:'v1',start:0,end:48},{id:'C',track:'v2',start:24,end:72},{id:'B',track:'v1',start:48,end:120}]);
 assert.equal(tracks.durationFrames(s),120); assert.equal(tracks.predecessor(s,'B'),'A'); assert.equal(tracks.predecessor(s,'C'),null);
});
test('track roundtrip keeps empty lanes and explicit placement',()=>{
 const s=model.parseState(JSON.stringify(sample()));
 const saved=JSON.parse(model.serialize(s)); assert.deepEqual(saved.tracks,fixture.tracks);
 assert.deepEqual(saved.boxes.map(b=>[b.id,b.track,b.start]),[['A','v1',0],['C','v2',24],['B','v1',48]]);
 assert.ok(saved.requires.includes(tracks.FEATURE)); assert.deepEqual(model.unknownFeatures(s),[]);
});
test('legacy conversion preserves IDs and layer settings without mutating on open',()=>{
 const s=model.parseState(JSON.stringify({version:1,boxes:[{id:'A',frames:48,exact:true,cut:true},{id:'B',frames:72,exact:true,cut:true}]}));
 assert.equal(s.tracks,undefined); const before=model.serialize(s); assert.equal(model.serialize(model.parseState(before)),before);
 tracks.enableTracks(s); assert.deepEqual(tracks.placements(s).map(p=>[p.id,p.start,p.end]),[['A',0,48],['B',48,120]]);
 const id=tracks.addTrack(s,'video'); assert.equal(tracks.trackContents(s,id).clips,0); tracks.removeTrack(s,id); assert.equal(s.tracks.length,1);
});
test('invalid placement is rejected without silently repairing the project',()=>{
 for(const value of [-1,1.5,true]) {const s=sample();s.boxes[0].start=value;assert.throws(()=>tracks.validate(s),/start/);}
 for(const change of [s=>s.boxes[0].track='missing',s=>s.boxes[0].track='a1',s=>s.boxes[2].start=20,s=>s.tracks.push({...s.tracks[0]})]) {const s=sample();change(s);assert.throws(()=>tracks.validate(s));}
});
test('removing a populated lane removes owned clips and dangling switches only',()=>{
 const s=sample();s.overlap_switches=[{id:'sw',from:'A',to:'C',at:40,fade:6,sound:'screen'}];
 const snapshot=structuredClone(s); assert.equal(tracks.trackContents(s,'v2').clips,1);
 tracks.removeTrack(s,'v2'); assert.deepEqual(s.boxes.map(b=>b.id),['A','B']);assert.deepEqual(s.overlap_switches,[]);
 Object.assign(s,snapshot);assert.deepEqual(s,snapshot);
});

test('conversion keeps legacy stack and timed text and audio sources',()=>{
 const s=sample(); delete s.tracks; s.boxes=s.boxes.filter(b=>b.id!=='C');for(const b of s.boxes){delete b.track;delete b.start;}
 s.boxes[0].layers=[{id:'layer',prompt:'Alternate.'}];s.boxes[0].switch={cuts:[{at:27,to:'layer'}],fade:6,sound:'screen'};
 s.timed_text={version:1,cues:[{id:'line',start:0,end:1,text:'Hello'}]};s.audio_clips=[{slot:'audio1',start:0,source_start:0,duration:5}];
 const before=structuredClone(s);tracks.enableTracks(s);assert.deepEqual(s.boxes[0].layers,before.boxes[0].layers);assert.deepEqual(s.boxes[0].switch,before.boxes[0].switch);
 assert.deepEqual(s.text_lanes[0].attachment,before.timed_text);assert.equal(s.timed_text,undefined);assert.equal(s.audio_clips[0].slot,'audio1');
 tracks.validate(s);assert.deepEqual(JSON.parse(model.serialize(model.parseState(model.serialize(s)))).text_lanes,s.text_lanes);
});

test('tracks share authoring time while insertion bridges pause the movie clock',()=>{
 const s=sample();s.bridges=[{before:'B',frames:12}];
 assert.equal(tracks.startFrame(s,'C'),24);assert.equal(tracks.outputFrame(s,48),60);
 assert.deepEqual(tracks.timelineFrame(s,53),{frame:48,bridgeId:'B'});
 assert.deepEqual(tracks.timelineFrame(s,84),{frame:72,bridgeId:null});
 assert.equal(tracks.outputSpans(s).at(-1).outputEnd,132);
 assert.equal(model.totalFrames(s),120);assert.equal(model.audioBoxSpans(s)[1].start,1);
 s.audio_clips=[{slot:'audio1',start:1,source_start:0,duration:1}];assert.equal(model.activeAudioClips(s,1).length,1);
});

test('generation validation and scene memory use the selected track',()=>{
 const s=sample();s.boxes[1].memory='scene';assert.deepEqual(model.memorySources(s,1),[]);
 s.boxes[0].frames=56;s.boxes[2].start=56;s.boxes[2].frames=34;s.boxes[2].cut=false;delete s.boxes[0].exact;delete s.boxes[2].exact;
 assert.equal(model.carryConflict(s,2,39),'');s.boxes[2].start=60;
 assert.match(model.carryConflict(s,2,39),/adjacent/);
});
