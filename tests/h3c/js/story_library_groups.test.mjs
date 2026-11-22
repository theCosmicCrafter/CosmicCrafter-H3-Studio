import {test} from 'node:test';
import assert from 'node:assert/strict';
import {StoryLibrary} from '../../../js/h3c_story_library.mjs?v=8b88866ede39';
import {groupStories} from '../../../js/h3c_story_groups.mjs?v=734f66b40a7e';

test('opening a named checkpoint restores an editable copy before loading', async () => {
  const calls = [];
  const l = new StoryLibrary({busy: () => false, save: async () => {},
    request: async (url, body) => {calls.push([url, body]);return body ? {graph: 'editable'} : {checkpoint_name: 'Rendered'};},
    load: async value => {calls.push(['load', value]);}});
  await l.open('snapshot');
  assert.deepEqual(calls, [['/h3c/stories?id=snapshot', undefined], ['/h3c/stories/restore', {id: 'snapshot'}],
    ['load', {graph: 'editable', restored_checkpoint: true}]]);
});

const rows = [
  {id: 'a', graph: 'g1', title: 'Heavy things fall up', updated: 1, boxes: 3, status: 'saved'},
  {id: 'b', graph: 'g2', title: 'Heavy things fall up', updated: 2, boxes: 3, status: 'saved'},
  {id: 'c', graph: 'g3', title: 'Other', updated: 3, boxes: 1, status: 'saved'},
];

const heavy = names => groupStories(rows, names).find(group => group.key === 'heavy things fall up');

const library = (overrides = {}) => {
  const calls = [], deleted = [];
  const host = {
    busy: () => false, request: async (url, body) => { calls.push([url, body]); return overrides.request?.(url, body) ?? {}; },
    confirm: async message => { calls.push(['confirm', message]); return overrides.confirm ?? true; },
    prompt: async (message, value) => { calls.push(['prompt', value]); return overrides.prompt; },
    deleted: async id => { deleted.push(id); },
  };
  return {library: new StoryLibrary(host), calls, deleted};
};

test('refresh returns the stories and the names', async () => {
  const {library: l} = library({request: async () => ({stories: rows, names: {k: 'N'}})});
  assert.deepEqual(await l.refresh(), {stories: rows, names: {k: 'N'}});
  const {library: older} = library({request: async () => ({stories: rows})});
  assert.deepEqual((await older.refresh()).names, {});
});

test('deleting a whole story removes every version after one confirmation, and clears its name', async () => {
  const {library: l, calls, deleted} = library();
  const group = heavy({'heavy things fall up': 'Gravity'});
  assert.equal(group.label, 'Gravity');
  assert.equal(await l.removeAll(group), true);
  assert.equal(calls.filter(c => c[0] === 'confirm').length, 1);
  assert.match(calls[0][1], /Gravity.*all 2 versions/);
  assert.deepEqual(calls.filter(c => c[0] === '/h3c/stories/delete').map(c => c[1].id), ['b', 'a']);
  assert.deepEqual(deleted, ['b', 'a']);
  assert.deepEqual(calls.at(-1), ['/h3c/stories/rename', {key: 'heavy things fall up', name: ''}]);
});

test('declining the confirmation deletes nothing', async () => {
  const {library: l, calls} = library({confirm: false});
  assert.equal(await l.removeAll(heavy()), false);
  assert.deepEqual(calls.map(c => c[0]), ['confirm']);
});

test('a failure part-way stops, and says how many versions were deleted', async () => {
  let count = 0;
  const {library: l, deleted} = library({request: async () => { if (++count === 2) throw Error('Wait for rendering'); return {}; }});
  await assert.rejects(l.removeAll(heavy()), error => {
    assert.match(error.message, /Wait for rendering \(1 of 2 versions deleted\.\)/);
    assert.equal(error.partial, true);
    return true;
  });
  assert.deepEqual(deleted, ['b']);
  assert.equal(l.pending, false);
});

test('a failure before anything is deleted is not partial', async () => {
  const {library: l} = library({request: async () => { throw Error('busy'); }});
  await assert.rejects(l.removeAll(heavy()), error => error.partial === false);
});

test('renaming asks with the current name; cancelling returns null and an empty name is kept to clear', async () => {
  const group = heavy();
  const cancelled = library({prompt: null});
  assert.equal(await cancelled.library.ask(group), null);
  assert.deepEqual(cancelled.calls[0], ['prompt', 'Heavy things fall up']);
  assert.equal(await library({prompt: ''}).library.ask(group), '');
  const {library: l, calls} = library();
  assert.equal(await l.rename('k', 'New'), true);
  assert.deepEqual(calls, [['/h3c/stories/rename', {key: 'k', name: 'New'}]]);
});
