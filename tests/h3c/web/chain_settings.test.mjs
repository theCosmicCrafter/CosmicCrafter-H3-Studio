import test from 'node:test';
import assert from 'node:assert/strict';
import {findAll, installDom} from './fake_dom.mjs';
import * as model from '../../../js/h3c_timeline_model.mjs';
import {ChainSettings} from '../../../js/h3c_chain_settings.mjs';

installDom();

function editor(extra = {}, videos = []) {
  const state = model.parseState(JSON.stringify({version: 1, prompt: '', boxes: [
    {id: 'a', frames: 107, prompt: 'One.', seed: 1}, {id: 'b', frames: 107, prompt: 'Two.', seed: 2}], ...extra}));
  return {state, commits: 0, host: {connected: () => ({images: [], audios: [], videos, video_audios: []})},
    commit() { this.commits += 1; },
    saved() { return JSON.parse(model.serialize(this.state)); }};
}

const video = (name, extra = {}) => ({name, title: `${name}.mp4`, ...extra});
const slices = (panel) => findAll(panel.slicesEl, (node) => node.tagName === 'INPUT');
const KEYS = ['context_noise', 'continuation_guide', 'audio_feather', 'video_slices'];

test('a Timeline without the keys shows the defaults and saves none of them', () => {
  const target = editor();
  const panel = new ChainSettings(target);
  panel.render();
  assert.equal(panel.noiseInput.checked, false);
  assert.equal(panel.guideInput.checked, true);
  assert.equal(panel.featherInput.value, '0');
  assert.deepEqual(slices(panel), []);
  assert.match(panel.slicesEl.textContent, /Connect a video/);
  assert.deepEqual(KEYS.filter((key) => key in target.saved()), []);
});

test('saved values are drawn', () => {
  const panel = new ChainSettings(editor({context_noise: true, continuation_guide: false, audio_feather: 6,
    video_slices: ['video1']}, [video('video1')]));
  panel.render();
  assert.equal(panel.noiseInput.checked, true);
  assert.equal(panel.guideInput.checked, false);
  assert.equal(panel.featherInput.value, '6');
  assert.deepEqual(slices(panel).map((input) => input.checked), [true]);
});

test('context noise and the last-frame guide write their key only when not the default', () => {
  const target = editor();
  const panel = new ChainSettings(target);
  panel.render();
  panel.noiseInput.checked = true;
  panel.noiseInput.fire('change');
  panel.guideInput.checked = false;
  panel.guideInput.fire('change');
  assert.equal(target.commits, 2);
  assert.equal(target.saved().context_noise, true);
  assert.equal(target.saved().continuation_guide, false);
  panel.noiseInput.checked = false;
  panel.noiseInput.fire('change');
  panel.guideInput.checked = true;
  panel.guideInput.fire('change');
  assert.equal('context_noise' in target.saved(), false);
  assert.equal('continuation_guide' in target.saved(), false);
});

test('audio feather is a whole number of ticks from 0 to 16; 0 or empty removes it', () => {
  const target = editor();
  const panel = new ChainSettings(target);
  panel.render();
  for (const [typed, saved] of [['4', 4], ['40', 16], ['2.6', 3], ['-3', undefined], ['', undefined]]) {
    panel.featherInput.value = typed;
    panel.featherInput.fire('change');
    assert.equal(target.saved().audio_feather, saved, typed);
    assert.equal(panel.featherInput.value, String(saved ?? 0), typed);
  }
});

test('the split lists connected videos and listed ones, and saves the ticked slots in order', () => {
  const target = editor({video_slices: ['video3']}, [video('video2'), video('video1'), video('video4', {problem: 'missing'})]);
  const panel = new ChainSettings(target);
  panel.render();
  const labels = findAll(panel.slicesEl, (node) => node.tagName === 'LABEL').map((node) => node.textContent);
  assert.deepEqual(labels, ['Split @video1 across clips', 'Split @video2 across clips', 'Split @video3 across clips']);
  assert.deepEqual(slices(panel).map((input) => input.checked), [false, false, true]);
  slices(panel)[1].checked = true;
  slices(panel)[1].fire('change');
  slices(panel)[0].checked = true;
  slices(panel)[0].fire('change');
  assert.deepEqual(target.saved().video_slices, ['video1', 'video2', 'video3']);
  for (const input of slices(panel)) { input.checked = false; input.fire('change'); }
  assert.equal('video_slices' in target.saved(), false);
});
