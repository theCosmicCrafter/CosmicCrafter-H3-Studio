import test from 'node:test';
import assert from 'node:assert/strict';
import {installDom} from './fake_dom.mjs';
import * as model from '../../../js/h3c_timeline_model.mjs';

installDom();
const {TimelineEditor} = await import('../../../js/h3c_timeline_editor.mjs');

function stub(boxes) {
  const editor = Object.create(TimelineEditor.prototype);
  Object.assign(editor, {
    state: model.parseState(JSON.stringify({version: 1, prompt: '', boxes: boxes.map((id, index) =>
      ({id, frames: 22, prompt: 'p', seed: index + 1}))})),
    stale: false, renders: 0,
    renderTrack() { this.renders += 1; }, renderHead() {}, renderPanelInfo() {},
  });
  return editor;
}

test('outdated boxes keep their take and are not queued by Render', () => {
  const editor = stub(['a', 'b', 'c']);
  editor.setStatus({ok: true, boxes: [{id: 'a', status: 'done'}, {id: 'b', status: 'outdated', thumb: {filename: 'b.png'}},
    {id: 'c', status: 'next'}]});
  assert.equal(editor.remaining(), 1);
  assert.equal(editor.nextBox(), 3);
  assert.equal(editor.statusOf(editor.state.boxes[1]).thumb.filename, 'b.png');
});

test('a failed or timed-out status keeps the last known clips', () => {
  const editor = stub(['a', 'b']);
  editor.setStatus({ok: true, boxes: [{id: 'a', status: 'done', thumb: {filename: 'a.png'}}, {id: 'b', status: 'done'}]});
  editor.setStatus({ok: false, error: 'Status unavailable: timed out'});
  assert.equal(editor.status.ok, true);
  assert.match(editor.status.unavailable, /timed out/);
  assert.equal(editor.statusOf(editor.state.boxes[0]).thumb.filename, 'a.png');
  assert.equal(editor.remaining(), 0);
});
