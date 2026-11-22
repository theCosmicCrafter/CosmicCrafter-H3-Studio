import test from 'node:test';
import assert from 'node:assert/strict';
import * as model from '../../../js/h3c_timeline_model.mjs';

const connected = {images: new Set(['image1', 'image2', 'image3']), audios: new Set(['audio1']),
  videos: new Set(['video1']), video_audios: new Set(['video_audio1'])};

function state(box, extra = {}) {
  return model.parseState(JSON.stringify({version: 1, prompt: '', boxes: [
    {id: 'a', frames: 107, prompt: 'A walk.', seed: 1, cut: false, first: '', last: '', ...box}], ...extra}));
}

const convert = (value) => model.flfConversion(value, 0, connected, 39);

test('a REF2VA clip with a First frame and extra images converts; its images become cached RefMods', () => {
  const value = state({first: 'image1', last: 'image2', prompt: '@image3 walks to the door.'});
  assert.equal(model.describeBox(value, 0, connected, 39).mode, 'REF2VA');
  assert.deepEqual(convert(value), {ok: true, reason: ''});
  value.boxes[0].flf_refmods = true;
  assert.equal(model.describeBox(value, 0, connected, 39).mode, 'FLF2VA');
});

test('raw video blocks the conversion and says why', () => {
  const result = convert(state({first: 'image1', prompt: '@image3 dances like @video1.'}));
  assert.equal(result.ok, false);
  assert.match(result.reason, /@video1: raw video/);
});

test('raw audio converts and stays an audio reference after the cached image RefMods', () => {
  const value = state({first: 'image1', prompt: '@image3 sings @audio1.'});
  assert.equal(convert(value).ok, true);
  value.boxes[0].flf_refmods = true;
  const info = model.describeBox(value, 0, connected, 39);
  assert.equal(info.mode, 'FLF2VA');
  assert.deepEqual(info.tags.filter(item => item.name === 'audio1'), [{name: 'audio1', tag: '<Audio 1>'}]);
});

test('a fresh clip without a First frame cannot convert', () => {
  const result = convert(state({prompt: '@image3 walks.'}));
  assert.equal(result.ok, false);
  assert.match(result.reason, /needs a First frame/);
});
