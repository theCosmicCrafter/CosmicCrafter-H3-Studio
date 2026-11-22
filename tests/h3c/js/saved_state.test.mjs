import {test} from 'node:test';
import assert from 'node:assert/strict';
import {SavedState} from '../../../js/h3c_saved_state.mjs';

function fixture(enabled = false) {
  let local = {timeline: 'local'};
  const calls = [], messages = [];
  const sync = new SavedState({read: () => local, apply: value => {local = value;},
    enabled: () => enabled, status: message => messages.push(message),
    session: {revision: 1, base: {timeline: 'before'}},
    request: async body => {calls.push(body); return {revision: 2, value: body?.value};}});
  return {sync, calls, messages, local: () => local};
}

test('autosave off neither reads nor writes server state and keeps local edits', async () => {
  const f = fixture();
  await f.sync.sync();
  assert.deepEqual(f.calls, []);
  assert.deepEqual(f.local(), {timeline: 'local'});
  assert.match(f.messages.at(-1), /Autosave off/);
});

test('an explicit flush still saves when autosave is off', async () => {
  const f = fixture();
  await f.sync.flush();
  assert.deepEqual(f.calls, [{revision: 1, value: {timeline: 'local'}}]);
});

test('enabled autosave retains normal synchronization', async () => {
  const f = fixture(true);
  await f.sync.sync();
  assert.equal(f.calls.length, 1);
});

test('turning autosave off during an in-flight read prevents late restoration', async () => {
  let enabled = true, resolve, local = 'local';
  const sync = new SavedState({enabled: () => enabled, read: () => local,
    apply: value => {local = value;}, status() {},
    request: () => new Promise(done => {resolve = done;})});
  const pending = sync.sync();
  enabled = false;
  resolve({revision: 4, value: 'other workflow'});
  await pending;
  assert.equal(local, 'local');
});

test('the first explicit save with autosave off preserves the local workflow', async () => {
  let local = {timeline: 'local checkpoint'}, server = {timeline: 'other workflow'};
  const sync = new SavedState({enabled: () => false, read: () => local,
    apply: value => {local = value;}, status() {},
    request: async body => {
      if(body)server = body.value;
      return {revision: body ? 3 : 2, value: server};
    }});
  await sync.flush();
  assert.equal(local.timeline, 'local checkpoint');
  assert.equal(server.timeline, 'local checkpoint');
});
