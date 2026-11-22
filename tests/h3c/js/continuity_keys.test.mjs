import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseState, serialize } from '../../../js/h3c_timeline_model.mjs?v=1dfc1612e462';

const boxes = [{id: 'a', frames: 124, prompt: 'p'}];

test('the Studio keeps context_noise, continuation_guide and audio_feather through an edit', () => {
  const saved = JSON.parse(serialize(parseState(JSON.stringify({version: 1, boxes, context_noise: true, continuation_guide: false, audio_feather: 4, video_slices: ['video1']}))));
  assert.deepEqual(saved.video_slices, ['video1']);
  assert.equal(saved.context_noise, true);
  assert.equal(saved.audio_feather, 4);
  assert.equal(saved.continuation_guide, false);
});

test('defaults are not written', () => {
  const saved = JSON.parse(serialize(parseState(JSON.stringify({version: 1, boxes, context_noise: false, continuation_guide: true, audio_feather: 0}))));
  assert.equal('context_noise' in saved, false);
  assert.equal('continuation_guide' in saved, false);
  assert.equal('audio_feather' in saved, false);
});
