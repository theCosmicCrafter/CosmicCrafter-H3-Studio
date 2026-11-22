import test from 'node:test';
import assert from 'node:assert/strict';
import {installDom, buttonNamed} from './fake_dom.mjs';

installDom();
const {CheckPanel} = await import('../../../js/h3c_check.mjs');
const {TakesPanel} = await import('../../../js/h3c_takes.mjs');

const WAIT = /Wait for the Timeline.s status to catch up/;
const output = (filename) => ({filename, subfolder: 'h3c', type: 'output'});

// An editor whose clip has a rendered take and a fresh status; `stale` flips as an edit and its status would.
function editor(requests) {
  return {state: {boxes: [{id: 'a'}], bible: null}, selected: 0, stale: false, queuing: false, activeTab: 'takes',
    status: {ok: true, boxes: [{id: 'a', status: 'done', video: output('a.mp4')}]},
    boxRenderButton: {disabled: false, title: 'Render'},
    host: {projectAttached: false, story: () => ({}), check: async (boxes) => { requests.push(['check', boxes]); },
      takes: async (action, body) => {
        requests.push([action, body]);
        const take = (n) => ({folder: `t${n}`, created: '2026-11-07T10:00:00', seed: n, usable: true, video: output(`t${n}.mp4`)});
        return {ok: true, box: {in_use: take(0), takes: [take(1), take(2)]}, bridge: null};
      }},
    box() { return this.state.boxes[this.selected]; },
    statusOf(box) { return this.status.boxes.find((item) => item.id === box?.id); }};
}

test('Check keeps its button while the status catches up, and a press then says to wait', async () => {
  const requests = [];
  const target = editor(requests);
  const panel = new CheckPanel(target);
  panel.render();
  assert.equal(panel.checkButton.disabled, false);
  target.stale = true;
  panel.render();
  assert.equal(panel.checkButton.disabled, false);
  assert.match(panel.checkButton.title, WAIT);
  panel.checkButton.click();
  await Promise.resolve();
  assert.deepEqual(requests, []);
  assert.match(panel.noteEl.textContent, WAIT);
  target.stale = false;
  panel.render();
  assert.equal(panel.noteEl.textContent, '');
  panel.checkButton.click();
  await Promise.resolve();
  assert.deepEqual(requests, [['check', ['a']]]);
});

test('Takes keep their rows while the status catches up, and Use then says to wait', async () => {
  const requests = [];
  const target = editor(requests);
  const panel = new TakesPanel(target);
  panel.render();
  await new Promise((resolve) => setTimeout(resolve, 0));
  const rows = [...panel.boxSection.rowsEl.childNodes];
  assert.equal(rows.length, 2);
  target.stale = true;
  panel.render();
  assert.deepEqual([...panel.boxSection.rowsEl.childNodes], rows);
  const use = buttonNamed(panel.boxSection.rowsEl, 'Use');
  assert.equal(use.disabled, false);
  use.click();
  await Promise.resolve();
  assert.deepEqual(requests.map(([action]) => action), ['list']);
  assert.match(panel.boxSection.noteEl.textContent, WAIT);
  target.stale = false;
  panel.show();
  assert.equal(panel.boxSection.noteEl.textContent, '');
});
