import test from 'node:test';
import assert from 'node:assert/strict';
import {buttonNamed, findAll, installDom} from './fake_dom.mjs';
import * as model from '../../../js/h3c_timeline_model.mjs';
import {BridgePanel} from '../../../js/h3c_bridges.mjs';
import {DialoguePanel} from '../../../js/h3c_dialogue.mjs';

installDom();

const wav = {type: 'input', filename: 'line.wav', subfolder: ''};
const output = (filename) => ({filename, subfolder: 'h3_sequences/s', type: 'output', v: '1'});
const clip = (extra = {}) => ({slot: 'audio1', file: wav, title: 'Line', start: 0, source_start: 0, duration: 30,
  source_duration: 30, ...extra});
const swap = {before: 'b', mode: 'replace', left: 14, right: 15, seed: 7, prompt: 'A turn.', review: 'k1'};

function state(extra = {}) {
  return model.parseState(JSON.stringify({version: 1, prompt: 'A street.', boxes: [
    {id: 'a', frames: 107, prompt: 'One.', seed: 1},
    {id: 'b', frames: 107, prompt: 'Two.', seed: 2, cut: true}], ...extra}));
}

function replacementItem(extra = {}) {
  return {box: 'b', mode: 'replace', status: 'done',
    region: {join: 107, start: 93, end: 122, left: 14, right: 15, frames: 29, before: ['a', 93, 107], after: ['b', 0, 15]},
    region_key: 'k1', reviewed: true, options: [[29, [10, 11, 12, 13, 14]]], proposal: [29, 14],
    protected: [{kind: 'on_screen', id: 'c1', start: 80, end: 92, speaker: 'Mara', text: 'Hello there.', checked: true}],
    candidates: [{candidate: 'n1', created: '2026-11-03T11:00:00', seed: 7, state: 'current', recipe: true, left: 14,
      right: 15, frames: 29, video: output('n1.mp4'),
      preview: {file: output('n1-context.mp4'), original: output('n1-original.mp4'), frames: 77, region: [24, 53], fps: 24}}],
    selected: null, selection: 'none', plays: false, takes: {a: 'take-a', b: 'take-b'}, ...extra};
}

function editor(value, status, extra = {}) {
  return {state: value, selected: 1, stale: false, status, queuing: false, commits: 0,
    host: {projectAttached: false, context: () => 25, viewUrl: (file) => `/view?filename=${file.filename}`},
    box() { return this.state.boxes[this.selected]; },
    statusOf(box) { return this.status.boxes.find((item) => item.id === box?.id); },
    bridgeStatusOf(id) { return this.status.bridges?.find((item) => item.box === id); },
    commit() { this.commits += 1; },
    queueBridge() { this.queued = true; },
    ...extra};
}

const done = [{id: 'a', status: 'done'}, {id: 'b', status: 'done'}];

test('a replacement with a rendered candidate offers review, playback and selection', () => {
  const value = state({bridges: [swap]});
  const target = editor(value, {ok: true, boxes: done, bridges: [replacementItem()], full_video: output('full.mp4')});
  const panel = new BridgePanel(target);
  panel.render();
  assert.equal(panel.titleEl.textContent, 'Replacement before box 2');
  assert.equal(panel.stateEl.textContent, 'Review the candidates, then select one or keep the original cut.');
  assert.equal(panel.renderButton.textContent, 'Render candidate');
  assert.equal(panel.renderButton.disabled, false);
  assert.equal(panel.confirmButton.textContent, 'Region confirmed ✓');
  assert.equal(panel.confirmButton.disabled, true);
  assert.equal(panel.suggestButton.hidden, true);
  assert.equal(panel.allowedEl.textContent, 'Allowed before the cut for 29 frames: 10–14.');
  assert.match(panel.regionEl.textContent, /^Replaces box 1 frames 93–106 and box 2 frames 0–14/);
  assert.equal(panel.protectedEl.children.length, 1);
  assert.equal(panel.playButton.hidden, true);

  const played = [];
  panel.root.addEventListener('h3c-play-candidate', (event) => played.push(event.detail));
  panel.root.addEventListener('h3c-play-region', (event) => played.push(event.detail));
  buttonNamed(panel.candidatesEl, 'In context').click();
  buttonNamed(panel.candidatesEl, 'Original').click();
  panel.previewButton.click();
  assert.deepEqual(played, [
    {box: 'b', file: output('n1-context.mp4'), label: 'Candidate 1 before box 2 · in context'},
    {box: 'b', file: output('n1-original.mp4'), label: 'Candidate 1 before box 2 · original cut'},
    {start: (93 - 24) / 24, end: (122 + 24) / 24}]);

  buttonNamed(panel.candidatesEl, 'Select').click();
  assert.equal(value.bridges[0].selected, 'n1');
  assert.equal(target.commits, 1);
  panel.render();
  assert.equal(buttonNamed(panel.candidatesEl, 'Selected').disabled, true);
  assert.equal(panel.useOriginalButton.hidden, false);
  panel.useOriginalButton.click();
  assert.equal('selected' in value.bridges[0], false);
});

test('a candidate is selectable only once its region is confirmed and it is current', () => {
  const value = state({bridges: [{...swap, review: undefined}]});
  const stale = replacementItem({status: 'review', reviewed: false, note: 'confirm the region before rendering a candidate',
    candidates: [{...replacementItem().candidates[0], state: 'stale'}]});
  const panel = new BridgePanel(editor(value, {ok: true, boxes: done, bridges: [stale]}));
  panel.render();
  assert.equal(buttonNamed(panel.candidatesEl, 'Select').disabled, true);
  assert.equal(panel.confirmButton.disabled, false);
  assert.equal(panel.renderButton.disabled, true);
  assert.equal(panel.stateEl.textContent, 'Confirm the region before rendering a candidate. The full video plays the original cut.');
  panel.confirmButton.click();
  assert.equal(value.bridges[0].review, 'k1');
});

test('a project attached through the API leaves candidate renders to the graph', () => {
  const target = editor(state({bridges: [{...swap}]}), {ok: true, boxes: done, bridges: [replacementItem({status: 'next'})]});
  target.host.projectAttached = true;
  const panel = new BridgePanel(target);
  panel.render();
  assert.equal(panel.renderButton.disabled, true);
  assert.match(panel.renderButton.title, /through the API/);
});

test('while the status catches up a replacement says it is waiting', () => {
  const target = editor(state({bridges: [{...swap}]}), {ok: true, boxes: done, bridges: [replacementItem()]});
  target.stale = true;
  const panel = new BridgePanel(target);
  panel.render();
  assert.equal(panel.stateEl.textContent, "Waiting for the Timeline's status.");
  assert.equal(panel.renderButton.disabled, true);
  assert.equal(panel.candidatesEl.hidden, true);
});

test('protecting footage writes an observed mark on the take the box plays', () => {
  const value = state({bridges: [{...swap}]});
  const panel = new BridgePanel(editor(value, {ok: true, boxes: done, bridges: [replacementItem()]}));
  panel.render();
  panel.protectBox.value = 'b';
  panel.protectFrom.value = '';
  panel.protectTo.value = '2';
  buttonNamed(panel.protectForm, 'Protect').click();
  assert.match(panel.protectMessage.textContent, /^Choose a range inside box 2/);
  panel.protectFrom.value = '1';
  panel.protectLabel.value = ' door slam ';
  buttonNamed(panel.protectForm, 'Protect').click();
  assert.equal(panel.protectMessage.textContent, '');
  assert.deepEqual(value.dialogue.observed, [{id: 'o1', box: 'b', take: 'take-b', start: 24, end: 48, label: 'door slam'}]);
});

test('a locked recording turns Insert off and Replace adds a replacement', () => {
  const value = state({audio_clips: [clip({locked: true, in_full_video: true})]});
  const panel = new BridgePanel(editor(value, {ok: true, boxes: done, bridges: []}));
  panel.render();
  assert.equal(panel.field.hidden, false);
  assert.equal(panel.insertButton.disabled, true);
  assert.match(panel.insertButton.title, /^A locked recording keeps its place/);
  assert.equal(panel.replaceButton.disabled, false);
  assert.equal(panel.hint.hidden, true);
  panel.replaceButton.click();
  assert.deepEqual(value.bridges.map(({before, mode, left, right}) => ({before, mode, left, right})),
    [{before: 'b', mode: 'replace', left: 14, right: 15}]);
});

const OFF = 'replacement bridges are switched off';

test('while replacement is unavailable a locked recording keeps the cut', () => {
  const value = state({audio_clips: [clip({locked: true, in_full_video: true})]});
  const panel = new BridgePanel(editor(value, {ok: true, boxes: done, bridges: [], replacement_unavailable: OFF}));
  panel.render();
  assert.equal(panel.replaceButton.hidden, true);
  assert.equal(panel.insertButton.disabled, true);
  assert.match(panel.insertButton.title, /^A locked recording keeps its place, so this join stays a cut/);
  assert.equal(panel.hint.hidden, false);
  assert.equal(panel.hint.textContent, `${panel.insertButton.title}.`);
});

test('while replacement is unavailable an unlocked cut offers only insertion', () => {
  const panel = new BridgePanel(editor(state(), {ok: true, boxes: done, bridges: [], replacement_unavailable: OFF}));
  panel.render();
  assert.equal(panel.replaceButton.hidden, true);
  assert.equal(panel.insertButton.disabled, false);
  assert.equal(panel.hint.hidden, true);
});

test('an unavailable replacement says why and leaves only removal', () => {
  const value = state({bridges: [{...swap, selected: 'n1'}]});
  const panel = new BridgePanel(editor(value, {ok: true, boxes: done, replacement_unavailable: OFF,
    bridges: [replacementItem({status: 'unavailable', note: OFF, selected: 'n1', selection: 'current'})]}));
  panel.render();
  assert.equal(panel.stateEl.textContent, 'Replacement bridges are switched off.');
  assert.equal(panel.renderButton.disabled, true);
  assert.equal(panel.renderButton.title, 'Replacement bridges are switched off.');
  assert.equal(panel.replaceRoot.hidden, true);
  assert.equal(panel.modeSelect.options[1].disabled, true);
  panel.removeButton.click();
  assert.deepEqual(value.bridges, []);
});

test('an insertion keeps its controls and says why it waits', () => {
  const value = state();
  const panel = new BridgePanel(editor(value, {ok: true, boxes: [{id: 'a', status: 'done'}, {id: 'b', status: 'next'}], bridges: []}));
  panel.render();
  assert.equal(panel.insertButton.disabled, true);
  assert.equal(panel.hint.textContent, 'Insert bridge: Render box 2 first.');
  assert.equal(panel.replaceButton.disabled, false);
});

test('the dialogue panel lists cues with the server check and locks a recording', () => {
  const cue = {id: 'c1', recording: {slot: 'audio1', file: wav}, start: 1, end: 2, text: 'Hello there.', speaker: 'Mara',
    portrayal: 'on_screen'};
  const value = state({audio_clips: [clip({in_full_video: true})], dialogue: {version: 1, cues: [cue]}});
  const target = editor(value, {ok: true, boxes: done, dialogue: {cues: [
    {id: 'c1', slot: 'audio1', state: 'bound', aligned: false, placed: true, cut: false, sequence: [1, 2], frames: [24, 48],
      segments: []}]}});
  const panel = new DialoguePanel(target);
  panel.render();
  assert.equal(panel.root.hidden, false);
  assert.equal(panel.summary.textContent, 'Dialogue cues · 1, 0 checked');
  assert.equal(panel.list.children.length, 1);
  assert.match(panel.list.textContent, /Not checked · plays 1\.00–2\.00 s in the video\./);
  assert.equal(panel.lockButton.hidden, false);
  panel.lockButton.click();
  assert.equal(value.audio_clips[0].locked, true);

  const words = findAll(panel.draftEl, (node) => node.tagName === 'TEXTAREA')[0];
  words.value = 'Over here.';
  words.fire('input');
  buttonNamed(panel.draftEl, 'Add cue').click();
  assert.deepEqual(value.dialogue.cues.map((item) => [item.id, item.text]), [['c1', 'Hello there.'], ['c2', 'Over here.']]);
});

test('checking a cue whose recording changed binds it to the new file', async () => {
  const fresh = {type: 'input', filename: 'take2.wav', subfolder: ''};
  const cue = {id: 'c1', recording: {slot: 'audio1', file: wav}, start: 1, end: 2, text: 'Hello there.', speaker: 'Mara',
    portrayal: 'on_screen', aligned: 'an older key'};
  const value = state({audio_clips: [clip({file: fresh})], dialogue: {version: 1, cues: [cue]}});
  const target = editor(value, {ok: true, boxes: done, dialogue: {cues: [
    {id: 'c1', slot: 'audio1', state: 'changed', aligned: true, placed: false, cut: false, sequence: null, frames: null,
      segments: []}]}});
  const panel = new DialoguePanel(target);
  panel.render();
  const checkbox = () => findAll(panel.list, (node) => node.getAttribute('aria-label') === 'Cue c1 checked against the recording')[0];
  assert.equal(checkbox().checked, false);
  checkbox().checked = true;
  checkbox().fire('change');
  for (let tries = 0; tries < 100 && !target.commits; tries += 1) await new Promise((resolve) => setTimeout(resolve, 5));
  assert.equal(target.commits, 1);
  assert.deepEqual(value.dialogue.cues[0].recording, {slot: 'audio1', file: fresh});
  assert.notEqual(value.dialogue.cues[0].aligned, 'an older key');
});
