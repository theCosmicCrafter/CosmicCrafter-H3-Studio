import test from 'node:test';
import assert from 'node:assert/strict';
import * as model from '../../../js/h3c_timeline_model.mjs';

const wav = {type: 'input', filename: 'line.wav', subfolder: ''};
const clip = (extra = {}) => ({slot: 'audio1', file: wav, title: 'Line', start: 0, source_start: 0, duration: 30,
  source_duration: 30, ...extra});
const cue = {id: 'c1', recording: {slot: 'audio1', file: wav}, start: 1, end: 2, text: 'Hello there.', speaker: 'Mara',
  portrayal: 'on_screen'};

function line(extra = {}, boxes = undefined) {
  return {version: 1, prompt: 'A street.', boxes: boxes ?? [
    {id: 'a', frames: 107, prompt: 'One.', seed: 1, cut: false, first: '', last: ''},
    {id: 'b', frames: 107, prompt: 'Two.', seed: 2, cut: true, first: '', last: ''},
    {id: 'c', frames: 107, prompt: 'Three.', seed: 3, cut: true, first: '', last: ''}], ...extra};
}

const parse = (value) => model.parseState(JSON.stringify(value));
const written = (state) => JSON.parse(model.serialize(state));

test('a Timeline without the new fields serializes as before', () => {
  const value = line({bridges: [{before: 'b', frames: 29, seed: 4, prompt: 'A pan.'}], audio_clips: [clip()]});
  const out = written(parse(value));
  assert.equal('requires' in out, false);
  assert.equal('dialogue' in out, false);
  assert.deepEqual(out.bridges, value.bridges);
  assert.equal(out.boxes.some((box) => 'dialogue' in box), false);
});

test('dialogue, box dialogue, locks and replacement records survive an edit and name what they require', () => {
  const swap = {before: 'b', mode: 'replace', left: 14, right: 15, seed: 7, prompt: 'A turn.', review: 'r', selected: 's'};
  const value = line({bridges: [swap], audio_clips: [clip({locked: true, in_full_video: true})],
    dialogue: {version: 1, cues: [cue], observed: [{id: 'o1', box: 'b', take: 't', start: 3, end: 9}]}});
  value.boxes[2].dialogue = 'manual';
  const out = written(parse(value));
  assert.deepEqual(out.bridges, [swap]);
  assert.deepEqual(out.dialogue, value.dialogue);
  assert.equal(out.audio_clips[0].locked, true);
  assert.equal(out.boxes[2].dialogue, 'manual');
  assert.equal('dialogue' in out.boxes[1], false);
  assert.deepEqual(out.requires, ['dialogue-cues-1', 'replacement-bridges-1']);
});

test('requires keeps features this editor does not own and drops its own once unused', () => {
  const state = parse(line({requires: ['replacement-bridges-1', 'someday-2'],
    bridges: [{before: 'b', frames: 12, seed: 1, prompt: ''}]}));
  assert.deepEqual(written(state).requires, ['someday-2']);
  state.audio_clips = [clip({locked: true})];
  assert.deepEqual(written(state).requires, ['dialogue-cues-1', 'someday-2']);
});

test('a new bridge inserts time unless a recording is locked', () => {
  const free = parse(line({audio_clips: [clip()]}));
  assert.deepEqual(Object.keys(model.insertBridge(free, 1)).sort(), ['before', 'frames', 'prompt', 'seed']);
  const locked = parse(line({audio_clips: [clip({locked: true})]}));
  const swap = model.insertBridge(locked, 1);
  assert.equal(swap.mode, 'replace');
  assert.deepEqual([swap.left, swap.right, 'frames' in swap], [14, 15, false]);
  assert.equal(model.insertBridge(locked, 2, 'insert').frames, 29);
  assert.deepEqual(model.lockedClips(locked).map((item) => item.slot), ['audio1']);
});

test('a locked clip needs its own file and an enabled slot', () => {
  const state = parse(line({audio_clips: [clip({locked: true, file: undefined}), clip({slot: 'audio2', locked: true})],
    disabled_refs: ['audio2']}));
  assert.deepEqual(model.lockedClips(state), []);
});

test('switching a bridge mode keeps its length and drops what the other mode cannot read', () => {
  const state = parse(line());
  model.insertBridge(state, 1, 'insert');
  const swap = model.setBridgeMode(state, 1, 'replace');
  assert.deepEqual([swap.mode, swap.left, swap.right, 'frames' in swap], ['replace', 14, 15, false]);
  swap.review = 'r'; swap.selected = 's';
  const back = model.setBridgeMode(state, 1, 'insert');
  assert.deepEqual([back.frames, 'mode' in back, 'left' in back, 'review' in back, 'selected' in back],
    [29, false, false, false, false]);
  assert.equal(model.bridgeOf(state, 1), back);
});

test('coverage edits keep the length on the replacement grid and leave review to the server', () => {
  const state = parse(line({bridges: [{before: 'b', mode: 'replace', left: 14, right: 15, seed: 1, prompt: '', review: 'r'}]}));
  const swap = model.bridgeOf(state, 1);
  model.setCoverage(swap, 12, 20);
  assert.deepEqual([swap.left, swap.right, swap.review], [12, 0, 'r']);
  model.setCoverage(swap, 46, -3);
  assert.deepEqual([swap.left, swap.right], [0, 46]);
  model.setCoverage(swap, 30, 4);
  assert.deepEqual([swap.left, swap.right], [4, 25]);
});

test('confirming a region and selecting a candidate edit only the replacement record', () => {
  const state = parse(line({bridges: [{before: 'b', mode: 'replace', left: 14, right: 15, seed: 1, prompt: ''}]}));
  const swap = model.bridgeOf(state, 1);
  model.confirmRegion(swap, 'key');
  model.selectCandidate(swap, 'abc');
  assert.deepEqual([swap.review, swap.selected], ['key', 'abc']);
  model.useOriginalCut(swap);
  assert.equal('selected' in swap, false);
});

test('only insertion bridges add time', () => {
  const state = parse(line({bridges: [{before: 'b', mode: 'replace', left: 14, right: 15, seed: 1, prompt: ''},
    {before: 'c', frames: 12, seed: 1, prompt: ''}]}));
  assert.equal(model.insertedFrames(state), 12);
  assert.equal(model.totalFrames(state), 321);
  assert.equal(model.isReplacement(model.bridgeOf(state, 1)), true);
  assert.equal(model.isReplacement(model.bridgeOf(state, 2)), false);
});

test('dropped frames block an insertion bridge but not a replacement', () => {
  const boxes = [{id: 'a', frames: 100, exact: true, prompt: 'One.', seed: 1, cut: false, first: '', last: ''},
    {id: 'b', frames: 107, prompt: 'Two.', seed: 2, cut: true, first: '', last: ''}];
  const state = parse(line({bridges: [{before: 'b', frames: 12, seed: 1, prompt: ''}]}, boxes));
  assert.match(model.bridgeProblem(state, 1), /drops/);
  model.setBridgeMode(state, 1, 'replace');
  assert.equal(model.bridgeProblem(state, 1), '');
});

test('box dialogue mode', () => {
  const state = parse(line({dialogue: {version: 1, cues: [cue]}}));
  model.setBoxDialogue(state, 1, 'manual');
  assert.equal(written(state).boxes[1].dialogue, 'manual');
  model.setBoxDialogue(state, 1, 'cues');
  assert.equal('dialogue' in written(state).boxes[1], false);
});
