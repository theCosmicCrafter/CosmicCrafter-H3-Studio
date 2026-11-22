import test, {mock} from 'node:test';
import assert from 'node:assert/strict';
import {installDom} from './fake_dom.mjs';
import * as model from '../../../js/h3c_timeline_model.mjs';

installDom();
const {TimelineEditor, TYPING_PAUSE} = await import('../../../js/h3c_timeline_editor.mjs');

// The real edit path, with drawing counted instead of done. The host marks the status stale on every change, as
// TimelineHost does.
function stub() {
  const editor = Object.create(TimelineEditor.prototype);
  const host = {writes: [], typing: [], changes: 0, context: () => 39,
    write(text, typing = false) { this.writes.push(text); this.typing.push(typing); },
    changed() { this.changes += 1; editor.markStale(); }};
  Object.assign(editor, {
    host, state: model.parseState(JSON.stringify({version: 1, prompt: '', boxes: [{id: 'a', frames: 96, prompt: 'p'}]})),
    status: null, statusById: new Map(), bridgeById: new Map(), stale: true, followNote: '', tracks: 0, heads: 0,
    cast: {changed() {}},
    renderTrack() { this.tracks += 1; }, renderHead() { this.heads += 1; }, renderPanel() {}, renderPanelInfo() {},
    renderReferenceOverview() {},
  });
  return editor;
}

test('typing writes every key but draws, records and tells the host once it pauses', (t) => {
  t.mock.timers.enable({apis: ['setTimeout']});
  const editor = stub();
  editor.state.boxes[0].prompt = 'pa';
  editor.typed();
  editor.state.boxes[0].prompt = 'pab';
  editor.typed();
  assert.equal(editor.host.writes.length, 2);
  assert.deepEqual(editor.host.typing, [true, true]);
  assert.equal(JSON.parse(editor.host.writes.at(-1)).boxes[0].prompt, 'pab');
  assert.equal(editor.tracks, 0);
  assert.equal(editor.host.changes, 0);
  t.mock.timers.tick(TYPING_PAUSE - 1);
  assert.equal(editor.tracks, 0);
  t.mock.timers.tick(1);
  assert.equal(editor.tracks, 1);
  assert.equal(editor.host.changes, 1);
  assert.equal(editor.host.typing.at(-1), false);
});

test('flushing typing commits what is pending once, and nothing when typing has paused', (t) => {
  t.mock.timers.enable({apis: ['setTimeout']});
  const editor = stub();
  editor.flushTyping();
  assert.equal(editor.host.writes.length, 0);
  editor.state.boxes[0].prompt = 'pa';
  editor.typed();
  editor.flushTyping();
  assert.equal(editor.tracks, 1);
  assert.equal(editor.host.typing.at(-1), false);
  editor.flushTyping();
  t.mock.timers.tick(TYPING_PAUSE);
  assert.equal(editor.tracks, 1);
  assert.equal(editor.host.changes, 1);
});

test('an edit during the typing pause takes the pending redraw with it', (t) => {
  t.mock.timers.enable({apis: ['setTimeout']});
  const editor = stub();
  editor.state.boxes[0].prompt = 'pa';
  editor.typed();
  editor.state.boxes[0].frames = 120;
  editor.commit();
  assert.equal(editor.tracks, 1);
  assert.equal(editor.host.changes, 1);
  t.mock.timers.tick(1000);
  assert.equal(editor.tracks, 1);
  assert.equal(editor.host.changes, 1);
});

test('an edit draws the Timeline once and keeps its takes, marked stale, until the next status', () => {
  const editor = stub();
  editor.setStatus({ok: true, boxes: [{id: 'a', status: 'done', thumb: {filename: 'a.png'}}]});
  editor.tracks = 0;
  editor.heads = 0;
  editor.state.boxes[0].prompt = 'changed';
  editor.commit();
  assert.equal(editor.tracks, 1);
  assert.equal(editor.heads, 1);
  assert.equal(editor.stale, true);
  assert.equal(editor.remaining(), 1);
  assert.equal(editor.statusOf(editor.state.boxes[0]).thumb.filename, 'a.png');
  editor.setStatus({ok: true, boxes: [{id: 'a', status: 'outdated', thumb: {filename: 'a.png'}}]});
  assert.equal(editor.stale, false);
  assert.equal(editor.tracks, 2);
});

test('a setting change marks a fresh status stale and redraws only the head', () => {
  const editor = stub();
  editor.setStatus({ok: true, boxes: [{id: 'a', status: 'done'}]});
  editor.tracks = 0;
  editor.heads = 0;
  editor.markStale();
  editor.markStale();
  assert.equal(editor.stale, true);
  assert.equal(editor.tracks, 0);
  assert.equal(editor.heads, 1);
});

test('an edit keeps the full video in the player until the next status', () => {
  const editor = stub();
  const node = (tag) => document.createElement(tag);
  Object.assign(editor, {renderHead: TimelineEditor.prototype.renderHead, frameImages: {preparation: {render() {}}},
    feedbackEl: node('div'), feedbackButton: node('button'), summaryEl: node('span'), addButton: node('button'), renderButton: node('button'),
    renderNextButton: node('button'), seedInput: {validity: {valid: true}}, fullLink: node('a'), fullDownloadLink: node('a'),
    hintEl: node('p'), readOnlyEl: node('p'), checks: {render() {}}, queuing: false});
  editor.host.viewUrl = (file) => `/view?filename=${file.filename}`;
  editor.setStatus({ok: true, boxes: [{id: 'a', status: 'done'}], full_video: {filename: 'full.mp4'}});
  editor.state.boxes[0].prompt = 'changed';
  editor.commit();
  assert.equal(editor.stale, true);
  assert.equal(editor.fullLink.hidden, false);
  assert.equal(editor.fullLink.href, '/view?filename=full.mp4');
});

test('clearing a status that is drawn still redraws', () => {
  const editor = stub();
  editor.setStatus({ok: true, boxes: [{id: 'a', status: 'done'}]});
  editor.tracks = 0;
  editor.setStatus(null);
  assert.equal(editor.tracks, 1);
  assert.equal(editor.statusOf(editor.state.boxes[0]), undefined);
});
