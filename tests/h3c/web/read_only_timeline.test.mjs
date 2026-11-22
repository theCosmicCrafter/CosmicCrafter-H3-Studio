import test from 'node:test';
import assert from 'node:assert/strict';
import {installDom} from './fake_dom.mjs';
import * as model from '../../../js/h3c_timeline_model.mjs';

installDom();
const {TimelineEditor, TYPING_PAUSE} = await import('../../../js/h3c_timeline_editor.mjs');

const file = name => ({filename: `${name}.png`, subfolder: 'h3_previews', type: 'output'});
// What a newer Studio might write: a feature this one doesn't know, fields it doesn't copy, and a converted clip
// whose free endpoint guides this editor would otherwise adopt as soon as it loads.
const NEWER = JSON.stringify({version: 1, prompt: '', requires: ['video-layers-99'], future: {kept: true}, boxes: [
  {id: 'a', frames: 71, exact: true, prompt: 'A walk.', seed: 1, cut: false, flf_refmods: true,
    previews: [{shot: 1000, frame: 0, guide: file('start')}, {shot: 1001, frame: 70, guide: file('end')}]},
  {id: 'b', frames: 71, prompt: 'Two angles.', seed: 1, seed_mode: 'randomize', cut: true,
    layers: [{id: 'l1', prompt: 'The other angle.'}], switch: {at: 0.5, fade: 6}}]});

// The real edit path with drawing stubbed out, loaded from the host the way TimelineHost loads it.
function stub(text = NEWER) {
  const editor = Object.create(TimelineEditor.prototype);
  const host = {text, writes: [], queued: 0, frames: 39, context() { return this.frames; }, read() { return this.text; },
    write(value) { this.writes.push(value); this.text = value; }, changed() {}, async queue() { this.queued += 1; }};
  Object.assign(editor, {
    host, selected: 0, status: null, statusById: new Map(), bridgeById: new Map(), stale: true, followNote: '',
    cast: {changed() {}, render() {}}, replacements: {close() {}}, renders: 0,
    render() { this.renders += 1; }, renderTrack() {}, renderHead() {}, renderPanel() {}, renderPanelInfo() {},
    renderReferenceOverview() {}, inspectClip() {},
  });
  editor.load();
  return editor;
}

test('a Timeline that requires a feature this Studio does not know names it', () => {
  const state = model.parseState(JSON.stringify({requires: ['dialogue-cues-1', 'video-layers-99', 'video-layers-99'], boxes: []}));
  assert.deepEqual(model.unknownFeatures(state), ['video-layers-99']);
});

test('known features or none leave a Timeline editable', () => {
  assert.deepEqual(model.unknownFeatures(model.parseState(JSON.stringify({requires: ['dialogue-cues-1'], boxes: []}))), []);
  assert.deepEqual(model.unknownFeatures(model.parseState('{"boxes":[]}')), []);
});

test('the read-only note names the features and says what to do', () => {
  assert.equal(model.readOnlyNote(['video-layers-99']), 'This Timeline needs a newer H3 Continuity (video-layers-99). '
    + 'It is open read-only so nothing in it is lost; update the node pack to edit or render it.');
  assert.match(model.readOnlyNote(['a-1', 'b-1']), /\(a-1, b-1\)/);
});

test('loading a Timeline from a newer Studio writes nothing and marks it read-only', () => {
  const editor = stub();
  assert.deepEqual(editor.readOnly, ['video-layers-99']);
  assert.deepEqual(editor.host.writes, []);
});

test('a Timeline from a newer Studio is never written by an edit, and the edit is undone', () => {
  const editor = stub();
  const loaded = model.serialize(editor.state);
  const edits = [
    () => { editor.state.boxes[1].prompt = 'Changed.'; editor.commit(); },
    () => editor.addBox(),
    () => editor.duplicate(),
    () => editor.remove(),
    () => { editor.selected = 0; editor.move(1); },
  ];
  for (const edit of edits) {
    edit();
    assert.deepEqual(editor.host.writes, []);
    assert.equal(model.serialize(editor.state), loaded);
    assert.ok(editor.selected < editor.state.boxes.length);
  }
});

test('typing into a read-only Timeline is undone at each key and never written', (t) => {
  t.mock.timers.enable({apis: ['setTimeout']});
  const editor = stub();
  const loaded = model.serialize(editor.state);
  editor.state.boxes[1].prompt = 'T';
  editor.typed();
  assert.equal(model.serialize(editor.state), loaded);
  editor.state.boxes[1].prompt = 'Ty';
  editor.typed();
  t.mock.timers.tick(TYPING_PAUSE);
  assert.deepEqual(editor.host.writes, []);
  assert.equal(model.serialize(editor.state), loaded);
});

test('a new context, or an empty Timeline, does not rewrite a read-only Timeline', () => {
  const editor = stub();
  editor.host.frames = 24;
  editor.contextChanged();
  const empty = stub(JSON.stringify({version: 1, prompt: '', requires: ['video-layers-99'], boxes: []}));
  empty.startIfEmpty();
  assert.deepEqual(editor.host.writes, []);
  assert.deepEqual(empty.host.writes, []);
  assert.equal(empty.state.boxes.length, 0);
});

test('a read-only Timeline queues nothing and keeps its seeds', async () => {
  const editor = stub();
  assert.equal(await editor.submit(1), false);
  editor.selected = 1;
  await editor.queueBox(2);
  assert.equal(editor.host.queued, 0);
  assert.deepEqual(editor.host.writes, []);
  assert.equal(editor.state.boxes[1].seed, 1);
});

function drawnHead(editor) {
  const node = (tag) => document.createElement(tag);
  const readOnlyEl = node('p');
  readOnlyEl.hidden = true;
  Object.assign(editor, {renderHead: TimelineEditor.prototype.renderHead, renderHint: TimelineEditor.prototype.renderHint,
    frameImages: {preparation: {render() {}}}, feedbackEl: node('div'), feedbackButton: node('button'),
    summaryEl: node('span'), addButton: node('button'), renderButton: node('button'), renderNextButton: node('button'),
    seedInput: {validity: {valid: true}}, fullLink: node('a'), fullDownloadLink: node('a'), hintEl: node('p'), readOnlyEl,
    checks: {render() {}}, queuing: false});
  editor.renderHead();
  return editor;
}

test('a notice says why the Timeline is read-only, and add and render are off', () => {
  const editor = drawnHead(stub());
  assert.equal(editor.readOnlyEl.textContent, model.readOnlyNote(['video-layers-99']));
  assert.equal(editor.readOnlyEl.hidden, false);
  assert.equal(editor.addButton.disabled, true);
  assert.equal(editor.renderButton.disabled, true);
  assert.equal(editor.renderNextButton.disabled, true);
});

test('an editable Timeline shows no read-only notice and keeps its hint', () => {
  const editor = drawnHead(stub(JSON.stringify({...JSON.parse(NEWER), requires: ['dialogue-cues-1']})));
  assert.equal(editor.readOnlyEl.hidden, true);
  assert.match(editor.hintEl.textContent, /^Drag a clip/);
  assert.equal(editor.addButton.disabled, false);
});

test('a Timeline that needs only known features still loads, saves and queues as before', async () => {
  const text = JSON.stringify({...JSON.parse(NEWER), requires: ['dialogue-cues-1']});
  const editor = stub(text);
  assert.deepEqual(editor.readOnly, []);
  assert.equal(editor.host.writes.length, 1);
  editor.state.boxes[1].prompt = 'Changed.';
  editor.commit();
  assert.equal(editor.host.writes.length, 2);
  assert.equal(JSON.parse(editor.host.writes.at(-1)).boxes[1].prompt, 'Changed.');
  assert.equal(await editor.submit(1), true);
  assert.equal(editor.host.queued, 1);
});
