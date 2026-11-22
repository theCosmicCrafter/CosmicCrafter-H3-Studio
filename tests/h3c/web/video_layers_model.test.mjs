import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import * as model from '../../../js/h3c_timeline_model.mjs';
import * as layers from '../../../js/h3c_layers.mjs';
import {splitTiming} from '../../../js/h3c_shot_split.mjs';

const root = fileURLToPath(new URL('../../..', import.meta.url));
const CONTEXT = 39;

// Shot 02 of the test production: one 90-frame Cut clip, its second video swapped in at frame 27.
function shot02() {
  return {
    version: 1, requires: ['video-layers-1'], prompt: '', boxes: [{
      id: 'b2', frames: 90, prompt: 'The lamplighter reaches the first lamp.', seed: 5101, cut: true,
      first: 'image3', last: '', exact: true,
      layers: [{id: 'b2v1', seed: 5101, prompt: 'Close on the wick.', first: 'image4', last: '', previews: [],
        memory: 'off', memories: [], dialogue: 'cues'}],
      switch: {cuts: [{at: 27, to: 'b2v1'}], fade: 6, sound: 'screen'},
    }],
  };
}

function clip(frames = 90, extra = {}) {
  return {id: 'c1', frames, prompt: 'A walk.', seed: 7, cut: true, first: '', last: '', exact: true, ...extra};
}

const state = (...boxes) => model.parseState(JSON.stringify({version: 1, prompt: '', boxes}));

test('round trip keeps layers and switch', () => {
  const text = model.serialize(model.parseState(JSON.stringify(shot02())));
  assert.equal(model.serialize(model.parseState(text)), text);
  const saved = JSON.parse(text);
  assert.deepEqual(saved.requires, ['video-layers-1']);
  assert.deepEqual(saved.boxes[0].layers, shot02().boxes[0].layers);
  assert.deepEqual(saved.boxes[0].switch, shot02().boxes[0].switch);
});

test('a layer keeps only the fields a video has', () => {
  const data = shot02();
  Object.assign(data.boxes[0].layers[0], {frames: 40, cut: true, pending: 1});
  const saved = JSON.parse(model.serialize(model.parseState(JSON.stringify(data))));
  assert.deepEqual(Object.keys(saved.boxes[0].layers[0]),
    ['id', 'seed', 'prompt', 'first', 'last', 'previews', 'memory', 'memories', 'dialogue']);
});

// The editor as it was before video layers, loaded from a temporary copy that imports today's other modules.
async function oldModel() {
  const source = execFileSync('git', ['show', '33b7466:web/h3c_timeline_model.mjs'], {cwd: root, encoding: 'utf8'});
  const web = pathToFileURL(path.join(root, 'js')).href;
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'h3c-old-model-'));
  const file = path.join(folder, 'h3c_timeline_model.mjs');
  fs.writeFileSync(file, source.replace(/(['"])\.\//g, `$1${web}/`));
  return import(pathToFileURL(file).href);
}

test('a timeline without layers serializes byte for byte', async () => {
  const old = await oldModel();
  const rich = {version: 1, prompt: 'Night.', requires: ['dialogue-cues-1'], boxes: [
    {id: 'a', frames: 107, prompt: 'One.', seed: 1, cut: false, first: 'image1', last: '', memory: 'scene',
      previews: [{shot: 1, frame: 0, guide: {filename: 'g.png', subfolder: 'h3_previews', type: 'output'}}]},
    {id: 'b', frames: 71, prompt: 'Two.', seed: 2, cut: true, new_scene: true, first: '', last: 'image2',
      exact: true, memories: [{box: 'a', frame: 12}], dialogue: 'manual'},
    {id: 'c', frames: 68, prompt: 'Three.', seed: 3, cut: false, first: '', last: ''}],
    bridges: [{id: 'r1', before: 'b', frames: 12, prompt: 'Across.', seed: 9}],
    dialogue: {cues: [{box: 'a', text: 'Hello.', start: 0.5}]}};
  const texts = [fs.readFileSync(path.join(root, 'tests/h3c/fixtures/box_audio_windows.json'), 'utf8'), JSON.stringify(rich)];
  for (const text of texts) {
    assert.equal(model.serialize(model.parseState(text)), old.serialize(old.parseState(text)));
    const now = model.normalize(model.parseState(text), CONTEXT), then = old.normalize(old.parseState(text), CONTEXT);
    assert.equal(model.serialize(now), old.serialize(then));
  }
});

test('requires is written only with layers', () => {
  const s = state(clip());
  assert.deepEqual(model.requiredFeatures(s), []);
  const id = layers.addVideo(s, 0);
  assert.deepEqual(model.requiredFeatures(s), ['video-layers-1']);
  assert.ok(model.OWN_FEATURES.includes(layers.FEATURE));
  layers.removeVideo(s, 0, id);
  assert.deepEqual(model.requiredFeatures(s), []);
  const saved = JSON.parse(model.serialize(s)).boxes[0];
  assert.equal('layers' in saved, false);
  assert.equal('switch' in saved, false);
});

test('a Timeline that needs video-layers-1 is editable', () => {
  assert.deepEqual(model.unknownFeatures(model.parseState(JSON.stringify(shot02()))), []);
});

test('newId avoids layer ids', (t) => {
  const s = model.parseState(JSON.stringify(shot02()));
  s.boxes[0].layers[0].id = 'i';
  const values = [0.5, 0.5, 0.25];
  t.mock.method(Math, 'random', () => values.shift());
  assert.equal((0.5).toString(36).slice(2, 8), 'i');
  assert.equal(model.newId(s), '9');
});

test('addVideo copies prompt and seed and places the swap', () => {
  const s = state(clip(90, {first: 'image1', previews: [{shot: 1, frame: 0, guide: {filename: 'g.png'}}],
    memory: 'scene', dialogue: 'manual'}));
  const id = layers.addVideo(s, 0);
  const box = s.boxes[0];
  assert.deepEqual(box.layers, [{id, seed: 7, prompt: 'A walk.', first: '', last: '', previews: [], memory: 'off',
    memories: [], dialogue: 'cues'}]);
  assert.deepEqual(box.switch, {cuts: [{at: 45, to: id}], fade: 6, sound: 'screen'});
  assert.deepEqual(layers.videosOf(s, 0).map((video) => video.label), ['1 · main', '1b']);
  const third = layers.addVideo(s, 0);
  assert.deepEqual(box.switch.cuts, [{at: 45, to: id}, {at: 68, to: third}]);
  layers.addVideo(s, 0);
  assert.equal(box.layers.length, 3);
  assert.deepEqual(layers.videosOf(s, 0).map((video) => video.label), ['1 · main', '1b', '1c', '1d']);
  assert.equal(layers.addVideo(s, 0), null);
  assert.equal(box.layers.length, 3);
});

test('labels follow the clip number', () => {
  const s = model.parseState(JSON.stringify({...shot02(), boxes: [clip(), ...shot02().boxes]}));
  assert.deepEqual(layers.videosOf(s, 1), [{id: 'b2', label: '2 · main', main: true},
    {id: 'b2v1', label: '2b', main: false}]);
});

test('removeVideo drops its cuts and sound', () => {
  const s = state(clip());
  const b = layers.addVideo(s, 0), c = layers.addVideo(s, 0);
  const box = s.boxes[0];
  layers.setSound(s, 0, c);
  box.switch.cuts.push({at: 80, to: b});
  layers.removeVideo(s, 0, c);
  assert.deepEqual(box.switch.cuts, [{at: 45, to: b}]);
  assert.equal(box.switch.sound, 'screen');
  assert.deepEqual(box.layers.map((layer) => layer.id), [b]);
  layers.removeVideo(s, 0, b);
  assert.equal('layers' in box, false);
  assert.equal('switch' in box, false);
});

test('swaps and the fade stay inside the clip and apart', () => {
  const s = model.parseState(JSON.stringify(shot02()));
  const box = s.boxes[0];
  layers.setSwap(s, 0, 0, 1);
  assert.equal(box.switch.cuts[0].at, 4);
  layers.setSwap(s, 0, 0, 200);
  assert.equal(box.switch.cuts[0].at, 87);
  layers.setFade(s, 0, 0);
  layers.setSwap(s, 0, 0, 200);
  assert.equal(box.switch.cuts[0].at, 89);
  layers.setFade(s, 0, 40);
  assert.equal(box.switch.fade, 12);
  assert.equal(box.switch.cuts[0].at, 84);
  box.switch.cuts.push({at: 86, to: 'b2'});
  layers.setFade(s, 0, 4);
  layers.setSwap(s, 0, 1, 50);
  assert.deepEqual(box.switch.cuts.map((cut) => cut.at), [84, 88]);
  layers.setSwap(s, 0, 0, 87);
  assert.deepEqual(box.switch.cuts.map((cut) => cut.at), [84, 88]);
});

test('resize clamps the swaps', () => {
  const s = state(clip());
  layers.addVideo(s, 0);
  model.setFrames(s, 0, 30, CONTEXT);
  model.normalize(s, CONTEXT);
  assert.equal(s.boxes[0].switch.cuts[0].at, 27);
  assert.equal(layers.clampSwitch(s, 0), true);
  s.boxes[0].switch.cuts.push({at: 28, to: 'c1'});
  s.boxes[0].frames = 10;
  assert.equal(layers.clampSwitch(s, 0), false);
});

test('on-screen bars and the closing video', () => {
  const box = shot02().boxes[0];
  assert.deepEqual(layers.onScreenBars(box, 90), [{id: 'b2', start: 0, end: 27}, {id: 'b2v1', start: 27, end: 90}]);
  assert.equal(layers.closingVideo(box, 90), 'b2v1');
  box.switch.cuts.push({at: 60, to: 'b2'});
  assert.equal(layers.closingVideo(box, 90), 'b2');
  assert.deepEqual(layers.onScreenBars(clip(), 90), [{id: 'c1', start: 0, end: 90}]);
});

test('continueAfterStack names the follower', () => {
  const s = model.parseState(JSON.stringify({...shot02(), boxes: [clip(), ...shot02().boxes,
    {id: 'c3', frames: 68, prompt: '', seed: 1, cut: false, first: '', last: ''}]}));
  assert.equal(layers.continueAfterStack(s, 1),
    'Clip 3 continues from clip 2. With several videos in clip 2, clip 3 must start with a Cut. Change it?');
  assert.equal(layers.continueAfterStack(s, 0), '');
  assert.equal(layers.continueAfterStack(s, 2), '');
  s.boxes[2].cut = true;
  assert.equal(layers.continueAfterStack(s, 1), '');
});

test('duplicate gives the copy new layer ids and a Cut', () => {
  const s = model.parseState(JSON.stringify(shot02()));
  s.boxes[0].switch.sound = 'b2v1';
  s.boxes[0].switch.align = {b2v1: {x: 1, y: 0, scale: 1}};
  const at = model.duplicateBox(s, 0, CONTEXT);
  const copy = s.boxes[at];
  assert.equal(copy.cut, true);
  const [layer] = copy.layers;
  assert.notEqual(layer.id, 'b2v1');
  assert.notEqual(layer.id, copy.id);
  assert.deepEqual(copy.switch.cuts, [{at: 27, to: layer.id}]);
  assert.equal(copy.switch.sound, layer.id);
  assert.deepEqual(Object.keys(copy.switch.align), [layer.id]);
  assert.deepEqual(s.boxes[0].layers[0].id, 'b2v1');
});

test('split refuses a clip with several videos', () => {
  const s = model.parseState(JSON.stringify(shot02()));
  assert.throws(() => splitTiming(s, 0, 2, CONTEXT), /^Error: Split is not available on a clip with several videos\.$/);
});

test('no bridge leads into or out of a stack', () => {
  const s = model.parseState(JSON.stringify({...shot02(), boxes: [clip(), ...shot02().boxes, clip(68, {id: 'c3'})],
    bridges: [{id: 'r1', before: 'b2', frames: 12}, {id: 'r2', before: 'c3', frames: 12}]}));
  assert.deepEqual(model.keptBridges(s), []);
});

test('renderFrames sums every video', () => {
  const s = model.parseState(JSON.stringify(shot02()));
  assert.equal(layers.renderFrames(s), 180);
  assert.equal(model.totalFrames(s), 90);
  assert.equal(layers.hasLayers(s), true);
  assert.equal(layers.hasLayers(state(clip())), false);
});
