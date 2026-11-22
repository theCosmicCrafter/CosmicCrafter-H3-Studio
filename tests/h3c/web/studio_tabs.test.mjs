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
const {StoryPanel} = await import('../../../js/h3c_story_panel.mjs');

const PROMPT = 'subject_definitions:\n<Subject 1> is Mara, a traveler.\nsummary:\nShe climbs the deck.\n'
  + 'retention_analysis:\n<Subject 1> keeps her coat.\ndetailed_description:\nWarm light.\n[Shot 1] Wide on the deck.\n'
  + 'overall_soundscape:\nWind.\nnon_diegetic_music:\nCello.\n';

function editor() {
  const state = {version: 1, prompt: '', boxes: [{id: 'a1', frames: 48, exact: true, prompt: PROMPT, seed: 7, cut: true, memory: 'off'}]};
  const host = {text: JSON.stringify(state), read() { return this.text; }, write(value) { this.text = value; },
    context: () => 39, connected: () => ({images: [], audios: []}), viewUrl: () => '/view', changed() {}, async queue() {}};
  return new TimelineEditor(host);
}
const tabs = (editor) => findAll(editor.structureEl, (node) => node.getAttribute?.('role') === 'tab');
const shown = (editor) => findAll(editor.structureEl, (node) => node.getAttribute?.('role') === 'tabpanel' && !node.hidden);

test('prompt sections are tabs that show one section at a time and keep the choice across redraws', () => {
  const timeline = editor();
  assert.deepEqual(tabs(timeline).map((tab) => tab.getAttribute('title')),
    ['Subjects & references', 'Summary', 'Reference retention', 'Shots', 'Soundscape', 'Background music']);
  assert.equal(shown(timeline).length, 1);
  assert.equal(shown(timeline)[0].getAttribute('aria-label'), 'Subjects & references');
  tabs(timeline)[1].click();
  assert.equal(shown(timeline).length, 1);
  assert.equal(shown(timeline)[0].getAttribute('aria-label'), 'Summary');
  timeline.renderPrompt();
  assert.equal(shown(timeline)[0].getAttribute('aria-label'), 'Summary');
  assert.equal(tabs(timeline)[1].getAttribute('aria-selected'), 'true');
});

test('turning a section tab off clears it, marks the tab empty, and on brings the text back', () => {
  const timeline = editor();
  tabs(timeline)[1].click();
  const toggle = () => findAll(shown(timeline)[0], (node) => node.getAttribute?.('role') === 'switch')[0];
  toggle().click();
  assert.doesNotMatch(JSON.parse(timeline.host.text).boxes[0].prompt, /She climbs the deck/);
  assert.equal(tabs(timeline)[1].classList.contains('empty'), true);
  assert.equal(shown(timeline)[0].getAttribute('aria-label'), 'Summary');
  toggle().click();
  assert.match(JSON.parse(timeline.host.text).boxes[0].prompt, /She climbs the deck/);
});

test('the Story outline is one row per clip that selects the clip and marks the selected one', () => {
  const panel = new StoryPanel({write() {}, rewrite() {}, checkAll() {}, cancel() {}, undo() {}, saveKey() {}, forgetKey() {}});
  const picked = [];
  panel.onSelectBox = (id) => picked.push(id);
  panel.showStory({title: 'T', outline: [{box: 'b', beat: 'Second.'}, {box: 'a', beat: 'First.'}]}, (id) => ({a: 1, b: 2})[id]);
  const rows = findAll(panel.outlineEl, (node) => node.classList?.contains('h3cs-beat'));
  assert.deepEqual(rows.map((row) => row.dataset.box), ['a', 'b']);
  assert.equal(rows[0].textContent, '1First.');
  rows[1].click();
  assert.deepEqual(picked, ['b']);
  panel.markBox('b');
  assert.equal(rows[1].getAttribute('aria-current'), 'true');
  assert.equal(rows[0].getAttribute('aria-current'), null);
});
