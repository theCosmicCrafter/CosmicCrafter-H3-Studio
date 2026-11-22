import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {captureWindows, resolveWindows, validateWindows, outputWindows, equivalentWindows} from '../../../js/h3c_audio_windows.mjs';
import {audioBoxSpans, parseState, serialize} from '../../../js/h3c_timeline_model.mjs';
const f = JSON.parse(readFileSync(new URL('../fixtures/box_audio_windows.json', import.meta.url)));
const locked = () => ({...f.clip, box_windows: captureWindows(f.clip, f.boxes, f.origin)});

test('output windows preserve ownership with bridge gaps and compare geometry',()=>{
  const clip=locked(), windows=resolveWindows(clip,f.boxes);
  const parts=[{frames:96,coverage:[{box:'a',first:0,frames:96}]},{frames:12,coverage:[]},{frames:96,coverage:[{box:'b',first:0,frames:96}]}];
  const output=outputWindows(clip,windows,parts);
  assert.equal(output[1].start,4.5);assert.equal(output[1].source_start,33.5);
  assert.equal(equivalentWindows(output,outputWindows(f.clip,resolveWindows(f.clip,f.boxes),parts)),false);
  assert.equal(equivalentWindows(output,structuredClone(output)),true);
});

test('shared capture, resize and empty binding semantics', () => {
  const clip = locked();
  assert.deepEqual(clip.box_windows.by_box, f.bindings);
  assert.deepEqual(resolveWindows(clip, f.boxes), f.resolved);
  assert.equal(f.clip.box_windows, undefined);
  const boxes = [{id:'a',start:0,duration:6},{id:'b',start:6,duration:4}];
  assert.equal(resolveWindows(clip, boxes)[1].source_start, 33.5);
  assert.equal(resolveWindows(clip, boxes)[1].start, 6);
  assert.equal(resolveWindows(clip, [{id:'a',start:0,duration:2}])[0].duration, 1.5);
  assert.deepEqual(resolveWindows(clip, f.boxes), f.resolved);
  clip.box_windows.by_box = {};
  assert.deepEqual(resolveWindows(clip, f.boxes), []);
  assert.equal(resolveWindows(f.clip, f.boxes)[0].box, null);
});

test('invalid bindings and source/placement changes fail explicitly; hidden tails are legal', () => {
  for (const value of [NaN, Infinity, true, -1, 0]) {
    const clip = locked(); clip.box_windows.by_box.a.duration = value;
    assert.throws(() => validateWindows(clip, f.boxes, f.origin), /audio|window/i);
  }
  for (const edit of [c => c.box_windows.version=2, c => c.start=1,
    c => c.box_windows.by_box.missing=c.box_windows.by_box.a,
    c => c.box_windows.by_box.a.source_start=100]) {
    const clip=locked(); edit(clip); assert.throws(() => validateWindows(clip,f.boxes,f.origin));
  }
  assert.throws(() => validateWindows(locked(),f.boxes,{source:'audio2'}));
  validateWindows(locked(),[{id:'a',start:0,duration:0.1},{id:'b',start:0.1,duration:1}], f.origin);
});

test('editor serialization negotiates the reader feature and preserves the map', () => {
  const state = parseState(JSON.stringify({boxes:[{id:'a',frames:96,exact:true},{id:'b',frames:96,exact:true,cut:true}],audio_clips:[locked()]}));
  assert.deepEqual(audioBoxSpans(state), f.boxes);
  const saved = JSON.parse(serialize(state));
  assert.ok(saved.requires.includes('box-audio-windows-1'));
  assert.deepEqual(parseState(JSON.stringify(saved)).audio_clips[0].box_windows.by_box,f.bindings);
});

test('imported box identifiers are data, including prototype property names',()=>{
  const boxes=[{id:'__proto__',start:0,duration:4}],clip={...f.clip};
  clip.box_windows=captureWindows(clip,boxes,f.origin);
  assert.equal(Object.hasOwn(clip.box_windows.by_box,'__proto__'),true);
  assert.equal(resolveWindows(clip,boxes)[0].box,'__proto__');
});
