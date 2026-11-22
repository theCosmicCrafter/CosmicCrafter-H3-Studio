import test from 'node:test';
import assert from 'node:assert/strict';
import {findAll, installDom} from './fake_dom.mjs';

installDom();
const element = Object.getPrototypeOf(document.createElement('div'));
element.getBoundingClientRect ??= () => ({left: 0, top: 0, right: 900, bottom: 100, width: 900, height: 100});
if (!('validity' in element)) Object.defineProperty(element, 'validity', {get: () => ({valid: true})});
element.querySelectorAll ??= () => [];
element.querySelector ??= () => null;
element.setCustomValidity ??= () => {};
element.focus ??= () => {};
const {TimelineEditor} = await import('../../../js/h3c_timeline_editor.mjs');

const LAYER = {id: 'b2v1', seed: 5101, prompt: 'Close.', first: '', last: '', previews: [], memory: 'off', memories: [],
  dialogue: 'cues'};
const doc = (first = {}) => ({version: 1, prompt: '', boxes: [
  {id: 'a1', frames: 48, exact: true, prompt: 'Street.', seed: 7, cut: false, memory: 'scene', first: 'image3', ...first},
  {id: 'b2', frames: 48, exact: false, prompt: 'Kitchen.', seed: 9, cut: true, memory: 'off'}]});

function panel(state = doc()) {
  const host = {text: JSON.stringify(state), read() { return this.text; }, write(value) { this.text = value; },
    context: () => 39, connected: () => ({images: [{name: 'image3', kind: 'image', title: 'Kitchen'}], audios: []}),
    viewUrl: (file) => `/view?filename=${file.filename}`, changed() {}, async queue() {}};
  return new TimelineEditor(host);
}
const saved = (editor) => JSON.parse(editor.host.text);
// The switch heading the section titled `title`.
const heading = (editor, title) => findAll(editor.panelEl, (node) => node.getAttribute?.('role') === 'switch'
  && node.children[1]?.textContent === title)[0];
const on = (editor, title) => heading(editor, title).getAttribute('aria-checked') === 'true';

test('the seed switch is random off and 42 on', () => {
  const editor = panel();
  assert.equal(on(editor, 'Fixed seed'), true);
  heading(editor, 'Fixed seed').click();
  assert.equal(saved(editor).boxes[0].seed_mode, 'randomize');
  assert.equal(on(editor, 'Fixed seed'), false);
  heading(editor, 'Fixed seed').click();
  assert.equal(saved(editor).boxes[0].seed_mode, undefined);
  assert.equal(saved(editor).boxes[0].seed, 42);
});

test('the length switch is the exact-length boolean', () => {
  const editor = panel();
  assert.equal(on(editor, 'Exact length'), true);
  heading(editor, 'Exact length').click();
  assert.equal(saved(editor).boxes[0].exact ?? false, false);
  assert.equal(on(editor, 'Exact length'), false);
});

test('visual memory has no Off choice: the switch is off, and on starts as Same scene without a bible', () => {
  const editor = panel();
  assert.equal(on(editor, 'Visual memory'), true);
  assert.equal(findAll(editor.memoryEl, (node) => node.tagName === 'OPTION' && node.value === 'off').length, 0);
  heading(editor, 'Visual memory').click();
  assert.equal(saved(editor).boxes[0].memory, 'off');
  assert.equal(editor.memoryEl.children.length, 0);
  heading(editor, 'Visual memory').click();
  assert.equal(saved(editor).boxes[0].memory, 'scene');
});

test('turning First & last frame off clears both, and on brings them back', () => {
  const editor = panel();
  assert.equal(on(editor, 'First & last frame'), true);
  heading(editor, 'First & last frame').click();
  assert.equal(saved(editor).boxes[0].first, '');
  assert.equal(on(editor, 'First & last frame'), false);
  heading(editor, 'First & last frame').click();
  assert.equal(saved(editor).boxes[0].first, 'image3');
});

test('First & last frame switched on with nothing kept stays on while empty', () => {
  const editor = panel(doc({first: ''}));
  assert.equal(on(editor, 'First & last frame'), false);
  heading(editor, 'First & last frame').click();
  assert.equal(on(editor, 'First & last frame'), true);
  editor.render();
  assert.equal(on(editor, 'First & last frame'), true, 'a redraw keeps the section the user turned on');
});

test('the Cut switch is the join: hidden on the first clip, Continue off and Cut on', () => {
  const editor = panel();
  assert.equal(editor.joinSettings.hidden, true);
  editor.select(1);
  assert.equal(editor.joinSettings.hidden, false);
  assert.equal(on(editor, 'Cut'), true);
  heading(editor, 'Cut').click();
  assert.equal(saved(editor).boxes[1].cut, false);
  assert.equal(heading(editor, 'Cut').children[2].textContent, 'Continues clip 1');
});

test('Multiple videos is on with other videos, and off keeps only the main video after a confirmation', () => {
  const state = doc();
  Object.assign(state.boxes[0], {frames: 90, layers: [LAYER], switch: {cuts: [{at: 27, to: 'b2v1'}], fade: 6, sound: 'screen'}});
  state.boxes[0].id = 'b2x';
  state.requires = ['video-layers-1'];
  state.boxes[1].cut = true;
  const editor = panel(state);
  assert.equal(on(editor, 'Multiple videos'), true);
  globalThis.confirm = () => false;
  heading(editor, 'Multiple videos').click();
  assert.equal(saved(editor).boxes[0].layers.length, 1, 'a dismissed confirmation keeps the videos');
  globalThis.confirm = () => true;
  heading(editor, 'Multiple videos').click();
  assert.equal(saved(editor).boxes[0].layers, undefined);
  assert.equal(on(editor, 'Multiple videos'), false);
  delete globalThis.confirm;
});

test('the continuity check switch follows the render and cannot be pressed', () => {
  const editor = panel();
  const sw = editor.continuityDetails;
  assert.equal(sw.open, false);
  assert.equal(sw.head.getAttribute('aria-disabled'), 'true');
  sw.head.click();
  assert.equal(sw.open, false);
  editor.checks.onRender(true);
  assert.equal(sw.open, true);
});

test('Story feedback is on while it has words or after being switched on', () => {
  const editor = panel();
  const sw = editor.feedbackSection;
  assert.equal(sw.open, false);
  editor.feedbackInput.value = 'Make her kneel.';
  editor.feedbackInput.fire('input');
  assert.equal(sw.open, true);
  sw.head.click();
  assert.equal(editor.feedbackInput.value, '');
  assert.equal(sw.open, false);
  sw.head.click();
  assert.equal(sw.open, true);
});

test('read-only Timelines keep their switches still', () => {
  const state = doc();
  state.requires = ['future-1'];
  const editor = panel(state);
  const before = editor.host.text;
  heading(editor, 'Fixed seed').click();
  assert.equal(editor.host.text, before);
});
