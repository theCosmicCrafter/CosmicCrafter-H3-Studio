import test from 'node:test';
import assert from 'node:assert/strict';
import {installDom} from './fake_dom.mjs';

installDom();
const listeners = {};
const listen = (type, listener) => (listeners[type] ??= new Set()).add(listener);
const forget = (type, listener) => listeners[type]?.delete(listener);
Object.assign(globalThis.document, {hidden: false, visibilityState: 'visible', addEventListener: listen, removeEventListener: forget});
globalThis.window = {addEventListener: listen, removeEventListener: forget};
const fire = type => { for (const listener of [...(listeners[type] ?? [])]) listener({type}); };
const {mountSavedState, AUTOSAVE_OFF} = await import('../../../js/h3c_saved_state.mjs');

// A Timeline node in a root graph, an `app` whose Autosave setting the test flips, and a server that records its writes.
function mount(enabled) {
  const widget = {name: 'timeline', value: 'one'};
  const graph = {id: 'g1', extra: {}, _nodes: []};
  const node = {id: 7, type: 'H3C_Timeline', graph, widgets: [widget], properties: {}, setDirtyCanvas() {}};
  graph._nodes.push(node);
  const state = {autosave: enabled, writes: []};
  const app = {rootGraph: graph, ui: {settings: {getSettingValue: () => state.autosave}}};
  const api = {async fetchApi(url, options) {
    if (options?.method === 'POST') state.writes.push(JSON.parse(options.body).value);
    return {ok: true, status: 200, json: async () => ({revision: 1 + state.writes.length, value: null})};
  }};
  const root = document.createElement('div');
  const saved = mountSavedState(node, root, {app, api, loaded() {}});
  return {saved, widget, state, label: () => root.children[0].children[0].textContent};
}
const flush = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };

test('with Autosave off an edit leaves the label alone and nothing is sent', async t => {
  t.mock.timers.enable({apis: ['setTimeout', 'setInterval', 'Date']});
  const f = mount(false);
  t.mock.timers.tick(10); await flush();
  assert.equal(f.label(), AUTOSAVE_OFF);
  const labels = [];
  f.widget.value = 'two';
  f.saved.changed(); labels.push(f.label());
  t.mock.timers.tick(5000); await flush(); labels.push(f.label());
  assert.deepEqual(labels, [AUTOSAVE_OFF, AUTOSAVE_OFF]);
  assert.deepEqual(f.state.writes, []);
  f.saved.destroy();
});

test('with Autosave on an edit is saved after a pause or when focus leaves, not between keys', async t => {
  t.mock.timers.enable({apis: ['setTimeout', 'setInterval', 'Date']});
  const f = mount(true);
  t.mock.timers.tick(10); await flush();
  const before = f.state.writes.length;
  // typing: a value change a second at a time keeps the save waiting
  for (let second = 0; second < 5; second++) {
    f.widget.value = `typed ${second}`;
    f.saved.changed();
    fire('input');
    t.mock.timers.tick(1000); await flush();
  }
  assert.equal(f.state.writes.length, before, 'nothing is sent while keys keep coming');
  assert.equal(f.label(), 'Changes pending…');
  // focus leaves the field: saved now
  fire('focusout'); await flush();
  assert.equal(f.state.writes.length, before + 1);
  assert.equal(f.state.writes.at(-1)['7/H3C_Timeline/timeline'], 'typed 4');
  // a later edit with no more keys is saved by the pause alone
  f.widget.value = 'paused';
  f.saved.changed();
  t.mock.timers.tick(3000); await flush();
  assert.equal(f.state.writes.at(-1)['7/H3C_Timeline/timeline'], 'paused');
  f.saved.destroy();
});
