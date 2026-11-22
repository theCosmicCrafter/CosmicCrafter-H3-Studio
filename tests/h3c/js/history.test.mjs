import {test} from 'node:test';
import assert from 'node:assert/strict';
import {EditHistory, TimelineHistory, editLabel, historyShortcut, editingSnapshot, withLiveReceipts} from '../../../js/h3c_history.mjs?v=7fd74e6b1728';
import {Studio} from '../../../js/h3c_studio.mjs?v=44a6bea48e14';

const state = (prompt = '', boxes = [{id:'a', prompt, frames:124, seed:1}]) => ({timeline:{prompt:'', boxes}, settings:{width:960}});

test('undo, redo and direct jumps restore independent snapshots in both directions', () => {
  const initial = state(), history = new EditHistory(initial);
  initial.timeline.boxes[0].prompt = 'must not leak';
  assert.equal(history.value.timeline.boxes[0].prompt, '');
  history.record(state('one'), 'First edit');
  history.record(state('two'), 'Second edit');
  assert.equal(history.canUndo, true);
  assert.equal(history.canRedo, false);
  assert.equal(history.jump(0).timeline.boxes[0].prompt, '');
  assert.equal(history.canUndo, false);
  assert.equal(history.canRedo, true);
  const restored = history.jump(2);
  restored.timeline.boxes[0].prompt = 'must not leak either';
  assert.equal(history.value.timeline.boxes[0].prompt, 'two');
  assert.equal(history.jump(1).timeline.boxes[0].prompt, 'one');
});

test('no-op writes and invalid jumps preserve redo; a new edit discards it', () => {
  const history = new EditHistory(state());
  history.record(state('one'), 'First'); history.record(state('two'), 'Second');
  history.jump(1);
  assert.equal(history.record(state('one'), 'No-op'), false);
  for (const index of [-1, 3, 0.5, NaN, '0', 1]) assert.equal(history.jump(index), null);
  assert.equal(history.canRedo, true);
  history.record(state('different'), 'New branch');
  assert.deepEqual(history.entries.map(entry => entry.label), ['Initial state', 'First', 'New branch']);
  assert.equal(history.canRedo, false);
});

test('typing is grouped by field and action; blur and navigation end the group', () => {
  const history = new EditHistory(state()), field = {};
  history.record(state('a'), 'Prompt', field);
  history.record(state('ab'), 'Prompt', field);
  history.record(state('abc'), 'Prompt', field);
  assert.equal(history.entries.length, 2);
  history.endGroup(); history.record(state('abcd'), 'Prompt', field);
  assert.equal(history.entries.length, 3);
  history.record(state('async result'), 'Frame guides', field);
  assert.equal(history.entries.length, 4);
  history.jump(0); history.record(state('branch'), 'Prompt', field);
  assert.equal(history.entries.length, 2);
  assert.equal(history.jump(0).timeline.boxes[0].prompt, '');
});

test('a step is named only when the Timeline changed', () => {
  const history = new EditHistory(state('one'));
  let named = 0;
  const label = () => { named++; return 'Edit clip 1 prompt'; };
  assert.equal(history.record(state('one'), label), false);
  assert.equal(named, 0);
  assert.equal(history.record(state('two'), label), true);
  assert.equal(named, 1);
  assert.equal(history.entries[1].label, 'Edit clip 1 prompt');
});

test('100 edits are retained with a reachable base state', () => {
  const history = new EditHistory(0);
  for (let i = 1; i <= 105; i++) history.record(i, `Edit ${i}`);
  assert.equal(history.entries.length, 101);
  assert.equal(history.index, 100);
  assert.equal(history.jump(0), 5);
  assert.equal(history.entries[0].label, 'Earlier state');
  assert.equal(history.jump(100), 105);
});

test('large unsigned seeds survive record, restore and labels exactly', () => {
  const before = state(), after = state();
  after.timeline.boxes[0].seed = 18446744073709551615n;
  const history = new EditHistory(before);
  history.record(after, editLabel(before, after));
  history.jump(0);
  assert.equal(history.jump(1).timeline.boxes[0].seed, 18446744073709551615n);
  assert.equal(history.entries[1].label, 'Edit clip 1 seed');
});

test('labels distinguish clip operations, shared prompt, settings and other Timeline content', () => {
  const before = state(), after = state();
  after.timeline.boxes.push({id:'b', prompt:'', frames:119});
  assert.equal(editLabel(before, after), 'Add clip');
  assert.equal(editLabel(after, before), 'Delete clip');
  const moved = structuredClone(after); moved.timeline.boxes.reverse();
  assert.equal(editLabel(after, moved), 'Reorder clips');
  after.timeline.boxes.pop(); after.timeline.boxes[0].frames = 141;
  assert.equal(editLabel(before, after), 'Edit clip 1 length');
  after.timeline.boxes[0].frames = 124; after.timeline.prompt = 'Shared';
  assert.equal(editLabel(before, after), 'Edit shared prompt');
  after.settings.width = 1024;
  assert.equal(editLabel(before, after), 'Change width');
  const audio = state(); audio.timeline.audio_clips = [{slot:'audio4'}];
  assert.equal(editLabel(before, audio), 'Edit audio');
});

function connectedHistory() {
  let value = state(), identity = 'project-a', group = null, flush = () => {};
  let notifications = 0, saves = 0;
  const history = new TimelineHistory({
    read: () => value, identity: () => identity, group: () => group,
    flush: () => flush(), notify: () => notifications++,
    apply: snapshot => { value = snapshot; saves++; history.capture(true); },
  });
  return {history, edit: next => {value = next; history.capture();}, read: () => value,
    project: next => {identity = next;}, group: next => {group = next;},
    flush: fn => {flush = fn;}, counts: () => ({notifications, saves})};
}

test('restoration uses the save path without recording itself or losing redo', () => {
  const host = connectedHistory();
  host.edit(state('one')); host.edit(state('two'));
  host.history.undo();
  assert.equal(host.read().timeline.boxes[0].prompt, 'one');
  assert.equal(host.history.entries.length, 3);
  assert.equal(host.history.canRedo, true);
  host.history.redo();
  assert.equal(host.read().timeline.boxes[0].prompt, 'two');
  host.history.restore(0);
  assert.equal(host.read().timeline.boxes[0].prompt, '');
  assert.equal(host.counts().saves, 3);
  // A status refresh/autosave with unchanged content must not create an edit.
  host.history.capture(true);
  assert.equal(host.history.canRedo, true);
  assert.equal(host.history.entries.length, 3);
});

test('initial saved load sets the baseline; switching projects clears both branches', () => {
  const host = connectedHistory();
  host.flush(() => {});
  // Initial hydration arrives through the loaded callback before any user edit.
  const initial = state('loaded');
  const read = host.history.read; host.history.read = () => initial;
  host.history.capture(true); host.history.read = read;
  assert.equal(host.history.entries.length, 1);
  host.edit(state('edited')); host.history.undo();
  host.project('project-b'); host.edit(state('other project'));
  assert.equal(host.history.entries.length, 1);
  assert.equal(host.history.canUndo, false);
  assert.equal(host.history.canRedo, false);
  assert.equal(host.history.value.timeline.boxes[0].prompt, 'other project');
});

test('undo flushes a field that commits on blur before calculating the previous state', () => {
  const host = connectedHistory();
  host.edit(state('one'));
  host.flush(() => {host.flush(() => {}); host.edit(state('on blur'));});
  host.history.undo();
  assert.equal(host.read().timeline.boxes[0].prompt, 'one');
  assert.equal(host.history.canRedo, true);
  host.history.redo();
  assert.equal(host.read().timeline.boxes[0].prompt, 'on blur');
});

test('a failed apply leaves the history cursor and restoration guard usable', () => {
  const host = connectedHistory(); host.edit(state('one'));
  const apply = host.history.apply;
  host.history.apply = () => {throw Error('Cannot apply');};
  assert.throws(() => host.history.undo(), /Cannot apply/);
  assert.equal(host.history.index, 1);
  assert.equal(host.history.restoring, false);
  host.history.apply = apply; host.history.undo();
  assert.equal(host.read().timeline.boxes[0].prompt, '');
});

test('job progress is outside history and restores keep the latest receipts', () => {
  const original = state().timeline;
  const live = structuredClone(original);
  live.still_requests = [{request_id:'still', state:'running'}];
  live.reference_preparation = {version:1, generate:{cast:false,locations:false,props:false}, assets:[],
    requests:[{request_id:'reference', state:'running'}]};
  assert.deepEqual(editingSnapshot(live), original);
  assert.equal(live.still_requests[0].state, 'running');
  live.still_requests[0].state = live.reference_preparation.requests[0].state = 'complete';
  const restored = withLiveReceipts(original, live);
  assert.equal(restored.still_requests[0].state, 'complete');
  assert.equal(restored.reference_preparation.requests[0].state, 'complete');
  assert.deepEqual(editingSnapshot(restored), original);
  restored.reference_preparation.requests[0].state = 'mutated';
  assert.equal(live.reference_preparation.requests[0].state, 'complete');
});

test('redoing reference preparation restores a usable empty request list', () => {
  const enabled = state().timeline;
  enabled.reference_preparation = {version:1, generate:{cast:true,locations:false,props:false}, assets:[]};
  const restored = withLiveReceipts(enabled, state().timeline);
  assert.deepEqual(restored.reference_preparation.requests, []);
  assert.equal(restored.reference_preparation.generate.cast, true);
  assert.deepEqual(editingSnapshot(restored), enabled);
});

const keyEvent = (key, extra = {}) => ({key, ctrlKey:true, target:{closest:() => null}, ...extra});
test('shortcuts support Ctrl/Cmd+Z, Shift+Z and Y and leave fields/IME/repeats alone', () => {
  assert.equal(historyShortcut(keyEvent('z')), 'undo');
  assert.equal(historyShortcut(keyEvent('Z', {ctrlKey:false, metaKey:true})), 'undo');
  assert.equal(historyShortcut(keyEvent('z', {shiftKey:true})), 'redo');
  assert.equal(historyShortcut(keyEvent('y')), 'redo');
  for (const extra of [{altKey:true}, {repeat:true}, {isComposing:true}, {ctrlKey:false}, {target:{closest:() => ({})}}])
    assert.equal(historyShortcut(keyEvent('z', extra)), null);
  assert.equal(historyShortcut(keyEvent('a')), null);
});

test('Studio handles project shortcuts once and blocks ComfyUI from handling them again', () => {
  const calls = [], studio = {host:{undo:() => calls.push('undo'), redo:() => calls.push('redo')}};
  const event = keyEvent('z', {preventDefault:() => calls.push('prevent'), stopPropagation:() => calls.push('stop')});
  Studio.prototype.key.call(studio, event);
  assert.deepEqual(calls, ['prevent', 'stop', 'undo']);
  calls.length = 0;
  Studio.prototype.key.call(studio, {...event, target:{closest:() => ({})}});
  assert.deepEqual(calls, []);
});
