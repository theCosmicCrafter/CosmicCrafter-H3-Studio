import {test} from 'node:test';
import assert from 'node:assert/strict';
import {groupKey, groupLabel, groupStories, initialSelection, versionLabel} from '../../../js/h3c_story_groups.mjs?v=734f66b40a7e';

const row = (id, title, updated, extra = {}) => ({id, title, updated, boxes: 4, status: 'saved', ...extra});

test('entries with the same title, ignoring case and spacing, become versions of one story', () => {
  const groups = groupStories([
    row('a', 'Heavy Things Fall Up', 10),
    row('b', '  heavy things  fall up ', 30),
    row('c', 'Heavy things fall up', 20),
    row('d', 'The Lighthouse', 25),
  ]);
  assert.deepEqual(groups.map(group => group.versions.length), [3, 1]);
  assert.deepEqual(groups.map(group => group.title), ['heavy things fall up', 'The Lighthouse']);
});

test('the story shown first is the one saved most recently, and its title is the latest version\'s', () => {
  const groups = groupStories([row('a', 'Old', 5), row('b', 'Newer', 50), row('c', 'old', 70)]);
  assert.deepEqual(groups.map(group => group.title), ['old', 'Newer']);
});

test('versions are listed newest first and keep their number as more are saved', () => {
  const before = groupStories([row('a', 'S', 1), row('b', 'S', 2)])[0].versions;
  assert.deepEqual(before.map(v => [v.id, v.version]), [['b', 2], ['a', 1]]);
  const after = groupStories([row('a', 'S', 1), row('b', 'S', 2), row('c', 'S', 3)])[0].versions;
  assert.deepEqual(after.map(v => [v.id, v.version]), [['c', 3], ['b', 2], ['a', 1]]);
});

test('untitled stories share one group instead of one each', () => {
  const groups = groupStories([row('a', '', 1), row('b', undefined, 2), row('c', 'Untitled story', 3)]);
  assert.equal(groups.length, 1);
  assert.equal(groups[0].title, 'Untitled story');
  assert.equal(groupKey(''), groupKey('  UNTITLED   story'));
});

test('an empty library and non-array input give no groups', () => {
  assert.deepEqual(groupStories([]), []);
  assert.deepEqual(groupStories(undefined), []);
});

test('labels say how many versions there are and which one is open', () => {
  const [one, many] = [groupStories([row('a', 'A', 1)])[0], groupStories([row('a', 'B', 1), row('b', 'B', 2)])[0]];
  assert.equal(groupLabel(one), 'A');
  assert.equal(groupLabel(many), 'B · 2 versions');
  const text = versionLabel({...many.versions[0], current: true}, () => 'DATE');
  assert.equal(text, 'v2 · 4 clips · saved · DATE · open now');
  assert.equal(versionLabel(many.versions[1], () => 'DATE'), 'v1 · 4 clips · saved · DATE');
});

test('the picker keeps the user\'s choice, else opens on the story that is open now', () => {
  const groups = groupStories([row('a', 'S', 1), row('b', 'S', 2, {current: true}), row('c', 'T', 3)]);
  assert.deepEqual(initialSelection(groups, {key: groupKey('T'), id: 'c'}), {key: 't', id: 'c'});
  assert.deepEqual(initialSelection(groups, {key: groupKey('S'), id: 'a'}), {key: 's', id: 'a'});
  assert.deepEqual(initialSelection(groups, {key: 's', id: 'gone'}), {key: 's', id: ''});
  assert.deepEqual(initialSelection(groups, {key: '', id: ''}), {key: 's', id: 'b'});
  assert.deepEqual(initialSelection(groups, {key: 'deleted', id: 'x'}), {key: 's', id: 'b'});
  assert.deepEqual(initialSelection(groupStories([row('c', 'T', 3)]), {}), {key: '', id: ''});
});

test('a name the user gave replaces the title, but the story is still found by its title', () => {
  const rows = [row('a', 'Heavy Things Fall Up', 1), row('b', 'heavy things fall up', 2)];
  const [group] = groupStories(rows, {[groupKey('Heavy things fall up')]: '  Gravity short  '});
  assert.equal(group.key, 'heavy things fall up');
  assert.equal(group.name, 'Gravity short');
  assert.equal(group.label, 'Gravity short');
  assert.equal(group.title, 'heavy things fall up');
  assert.equal(groupLabel(group), 'Gravity short · 2 versions');
  const [plain] = groupStories(rows, {other: 'x', [group.key]: '   '});
  assert.equal(plain.label, 'heavy things fall up');
});

test('a trailing revision tag does not make a different story', () => {
  const groups = groupStories([
    row('a', 'Heavy Things Fall Up v07 (one story) · r1', 1),
    row('b', 'Heavy Things Fall Up v07 (one story) · r2', 2),
    row('c', 'Heavy Things Fall Up v07 (one story) · r3 · r3', 3),
    row('d', 'Heavy Things Fall Up v07 (one story)', 0),
    row('e', 'Heavy Things Fall Up P4 - final q1 (Quality) · r1', 4),
  ]);
  assert.deepEqual(groups.map(group => [group.title, group.versions.length]),
    [['Heavy Things Fall Up P4 - final q1 (Quality)', 1], ['Heavy Things Fall Up v07 (one story)', 4]]);
  assert.equal(groupKey('Story · r2'), groupKey('story'));
  assert.notEqual(groupKey('Story r2 final'), groupKey('Story'));
  assert.equal(groupKey('· r2'), '· r2');
});
