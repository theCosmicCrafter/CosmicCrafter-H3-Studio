import test from 'node:test';
import assert from 'node:assert/strict';
import * as model from '../../../js/h3c_timeline_model.mjs';
import {applyFrameGuide, endpointGuide, adoptEndpointGuides} from '../../../js/h3c_shot_preview.mjs';

const file = name => ({filename: `${name}.png`, subfolder: 'h3_previews', type: 'output'});

function state(previews) {
  return model.parseState(JSON.stringify({version: 1, prompt: '', boxes: [
    {id: 'a', frames: 71, exact: true, prompt: 'A walk.', seed: 1, cut: false, flf_refmods: true, previews},
    {id: 'b', frames: 71, prompt: 'Next.', seed: 1, cut: true}]}));
}

const boundary = {a: 'a', b: 'b', renderedA: true, renderedB: false};

test('a free Frame guide on the last frame counts as the Last still', () => {
  const value = state([{shot: 1000, frame: 70, guide: file('free')}]);
  assert.deepEqual(endpointGuide(value, 0, 39, 'last')?.guide, file('free'));
  assert.equal(endpointGuide(value, 0, 39, 'first'), null);
});

test('a guide saved against the Last marker wins over a free guide on that frame', () => {
  const value = state([{shot: 1000, frame: 70, guide: file('free')},
    {target: {kind: 'last'}, frame: 70, guide: file('last')}]);
  assert.deepEqual(endpointGuide(value, 0, 39, 'last')?.guide, file('last'));
});

test('accepting a Last guide takes the frame over from a free guide instead of doubling it', () => {
  const value = state([{shot: 1000, frame: 70, guide: file('free')}]);
  applyFrameGuide(value, 'a', {kind: 'last'}, file('new'), {context: 39, boundary});
  const guided = value.boxes[0].previews.filter(item => item.guide);
  assert.equal(guided.length, 1);
  assert.deepEqual(guided[0].target, {kind: 'last'});
  assert.deepEqual(guided[0].guide, file('new'));
});

test('a free guide that keeps candidates stays as a saved still without its guide', () => {
  const candidate = {file: file('candidate')};
  const value = state([{shot: 1000, frame: 70, guide: file('free'), images: [candidate]}]);
  applyFrameGuide(value, 'a', {kind: 'last'}, file('new'), {context: 39, boundary});
  const kept = value.boxes[0].previews.find(item => !item.target);
  assert.equal(kept.guide, undefined);
  assert.deepEqual(kept.images, [candidate]);
});

test('a free guide on another frame is left alone', () => {
  const value = state([{shot: 1000, frame: 30, guide: file('free')}]);
  applyFrameGuide(value, 'a', {kind: 'last'}, file('new'), {context: 39, boundary});
  assert.equal(value.boxes[0].previews.filter(item => item.guide).length, 2);
});

test('converting adopts free guides on the first and last frames as First and Last stills', () => {
  const value = state([{shot: 1000, frame: 0, guide: file('start')}, {shot: 1001, frame: 70, guide: file('end')},
    {shot: 1002, frame: 30, guide: file('mid')}]);
  assert.equal(adoptEndpointGuides(value, 0, 39), true);
  const [first, last, mid] = value.boxes[0].previews;
  assert.deepEqual([first.target, first.frame, first.guide], [{kind: 'first'}, 0, file('start')]);
  assert.deepEqual([last.target, last.frame, last.guide], [{kind: 'last'}, 70, file('end')]);
  assert.equal(mid.target, undefined);
});

test('adopting merges into an existing First marker without a guide and skips one that has a guide', () => {
  const candidate = {file: file('candidate')};
  const value = state([{target: {kind: 'first'}, frame: 0, images: [candidate]}, {shot: 1000, frame: 0, guide: file('free')},
    {target: {kind: 'last'}, frame: 70, guide: file('last')}, {shot: 1001, frame: 70, guide: file('other')}]);
  adoptEndpointGuides(value, 0, 39);
  const previews = value.boxes[0].previews;
  assert.equal(previews.length, 3);
  assert.deepEqual(previews[0].guide, file('free'));
  assert.deepEqual(previews[0].images, [candidate]);
  assert.deepEqual(previews.find(p => !p.target).guide, file('other'));
});
