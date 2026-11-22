import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseState } from '../../../js/h3c_timeline_model.mjs';
import { shotFrames } from '../../../js/h3c_shot_preview.mjs';

const prompt = (at) => `[Shot 1] Walk in.\n[Shot 2] At 00:0${at}.000, turn around.`;

test('clips with the same prompt keep their own carried frames', () => {
  const state = parseState(JSON.stringify({version: 1, boxes: [
    {id: 'a', frames: 96, prompt: prompt(3)}, {id: 'b', frames: 96, prompt: prompt(3)}]}));
  assert.deepEqual(shotFrames(state, 0, 39), [{shot: 1, frame: 0}, {shot: 2, frame: 72}]);
  assert.deepEqual(shotFrames(state, 1, 39), [{shot: 1, frame: 0}, {shot: 2, frame: 34}]);
  assert.deepEqual(shotFrames(state, 1, 17), [{shot: 1, frame: 0}, {shot: 2, frame: 56}]);
});

test('shot frames follow prompt and length edits', () => {
  const state = parseState(JSON.stringify({version: 1, boxes: [{id: 'a', frames: 96, prompt: prompt(3)}]}));
  const first = shotFrames(state, 0, 39);
  first[1].frame = 999;
  assert.deepEqual(shotFrames(state, 0, 39), [{shot: 1, frame: 0}, {shot: 2, frame: 72}]);
  state.boxes[0].prompt = prompt(2);
  assert.deepEqual(shotFrames(state, 0, 39), [{shot: 1, frame: 0}, {shot: 2, frame: 48}]);
  state.boxes[0].frames = 40;
  assert.deepEqual(shotFrames(state, 0, 39), [{shot: 1, frame: 0}, {shot: 2, frame: null}]);
  state.boxes[0].prompt = 'No shots here.';
  assert.deepEqual(shotFrames(state, 0, 39), [{shot: 1, frame: 0}]);
});
