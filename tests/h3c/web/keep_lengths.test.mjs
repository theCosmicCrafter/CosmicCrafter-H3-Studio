import test from 'node:test';
import assert from 'node:assert/strict';
import * as model from '../../../js/h3c_timeline_model.mjs';

const timeline = (boxes, extra = {}) => model.parseState(JSON.stringify({version: 1, prompt: '', boxes, ...extra}));
const box = (id, frames, extra = {}) => ({id, frames, prompt: 'A dock at dusk.', seed: 1, cut: false, ...extra});

test('normalizing keeps every saved length a long Timeline allows', () => {
  const state = timeline([box('a', 549), box('b', 510)], {max_frames: 991});
  model.normalize(state, 39);
  assert.deepEqual(state.boxes.map(item => item.frames), [549, 510]);
  assert.equal(JSON.parse(model.serialize(state)).max_frames, 991);
});

test('normalizing never shortens a box past the limit; the box reports it instead', () => {
  const state = timeline([box('a', 107), box('b', 340), box('c', 300, {cut: true, exact: true})]);
  model.normalize(state, 90);
  assert.deepEqual(state.boxes.map(item => item.frames), [107, 340, 300]);
  const connected = {images: new Set(), audios: new Set(), videos: new Set(), video_audios: new Set()};
  assert.ok(model.describeBox(state, 1, connected, 90).problems.includes('Longer than the 272 frames allowed.'));
});

test('editing memory or a prompt leaves every length as it plays', () => {
  const state = timeline([box('a', 96, {exact: true}), box('b', 107, {cut: true}), box('c', 90, {cut: true, exact: true})]);
  state.boxes[2].memory = 'selected';
  state.boxes[2].memories = [{box: 'a', frame: 40, label: 'the dock'}];
  state.boxes[1].prompt = 'The dock from the water.';
  model.normalize(state, 39);
  assert.deepEqual(state.boxes.map(item => item.frames), [96, 107, 90]);
});

test('normalizing writes the length timeline.py plays for an off-grid box', () => {
  const state = timeline([box('a', 96), box('b', 96)]);
  model.normalize(state, 39);
  assert.deepEqual(state.boxes.map(item => item.frames), [90, 102]);
});

test('typed lengths reach a long Timeline’s limit', () => {
  const state = timeline([box('a', 107)], {max_frames: 991});
  model.setFrames(state, 0, 600, 39);
  assert.equal(state.boxes[0].frames, 600);
});

test('conflicts say a length change moves every later box', () => {
  const state = timeline([box('a', 30, {exact: true}), box('b', 51)]);
  assert.match(model.dropConflict(state, 1, 39), /make box 2 a cut, .* which moves every later box\.$/);
});
