import {test} from 'node:test';
import assert from 'node:assert/strict';
import {savedStoryContent} from '../../../js/h3c_story_library.mjs?v=8b88866ede39';
import {groupStories, versionLabel} from '../../../js/h3c_story_groups.mjs?v=734f66b40a7e';

const workflow = (extra = {}) => ({
  nodes: [
    {id: 1, type: 'H3C_Story', inputs: [{name: 'state', widget: {name: 'state'}}],
      widgets_values: [JSON.stringify({title: 'Heavy', timeline: '2'})]},
    {id: 2, type: 'H3C_Timeline', inputs: [{name: 'name', widget: {name: 'name'}}, {name: 'timeline', widget: {name: 'timeline'}},
      {name: 'width', widget: {name: 'width'}}],
      widgets_values: ['Project-b62045ea', JSON.stringify({version: 1, boxes: [{id: 'a', frames: 22, previews: [
        {image: 'h3_previews/x.png [output]', pending: true, job: 'j1'}]}]}), extra.width ?? 736]},
  ],
  links: [],
});

test('a saved story keeps its own folder and rendered clips even when the wiring differs', () => {
  const value = {workflow: workflow(), story: '1', sequence: 'Project-b62045ea'};
  const content = savedStoryContent(value, workflow({width: 1024}));
  assert.equal(content.sequence, 'Project-b62045ea');
  assert.equal(content.renders, true);
  assert.equal(content.wiring, false);
  const preview = JSON.parse(content.timeline).boxes[0].previews[0];
  assert.equal(preview.image, 'h3_previews/x.png [output]');  // finished candidates stay
  assert.equal(preview.pending, undefined);  // in-flight jobs of the other queue do not
});

test('the same wiring keeps everything', () => {
  const value = {workflow: workflow(), story: '1', sequence: 'Project-b62045ea'};
  const content = savedStoryContent(value, workflow());
  assert.equal(content.wiring, true);
  assert.equal(JSON.parse(content.timeline).boxes[0].previews[0].job, 'j1');
});

test('Saved stories carry the linked Timeline attachment and bindings without sharing the saved snapshot', () => {
  const saved = workflow();
  const project = {mode: 'attached', id: 'managed-project', revision: 1, profile_sha256: 'profile'};
  const assets = [{asset_id: 'endpoint', bindings: [{kind: 'picture', slot: 'image17'}]}];
  saved.nodes[1].properties = {h3c_project: project, h3c_asset_bindings: assets};
  // Another Timeline must not supply this Story's attachment.
  saved.nodes.unshift({id: 3, type: 'H3C_Timeline', properties: {h3c_project: {mode: 'attached', id: 'other'}}});
  const value = {workflow: saved, story: '1', sequence: 'api_managedproject'};
  for (const current of [saved, workflow({width: 1024})]) {
    const content = savedStoryContent(value, current);
    assert.deepEqual(content.project, project);
    assert.deepEqual(content.asset_bindings, assets);
    assert.equal(content.sequence, value.sequence);
    content.project.revision = 99;
    content.asset_bindings[0].bindings[0].slot = 'image18';
    assert.equal(project.revision, 1);
    assert.equal(assets[0].bindings[0].slot, 'image17');
  }
});

test('native Saved stories keep bindings and never reconnect a fork export to its source project', () => {
  for (const project of [undefined, {mode: 'fork', id: 'original-project'}]) {
    const saved = workflow();
    saved.nodes[1].properties = {h3c_project: project, h3c_asset_bindings: []};
    const content = savedStoryContent({workflow: saved, story: '1', sequence: 'native-copy'}, workflow());
    assert.equal(content.project, undefined);
    assert.deepEqual(content.asset_bindings, []);
    assert.equal(content.sequence, 'native-copy');
  }
});

const row = (id, title, sequence, updated, rendered = 0) => ({id, title, sequence, updated, boxes: 88, status: 'saved', rendered});

test('entries sharing a folder or a title are one story', () => {
  const groups = groupStories([
    row('a', 'Heavy Things Fall Up v07 · r1', 'Project-b62045ea', 5, 88),
    row('b', 'Heavy Things Fall Up v07 · r1', 'Project-483e8217', 4),
    row('c', 'Renamed draft', 'Project-b62045ea', 3, 88),
    row('d', 'Other', 'Project-1', 2),
  ]);
  assert.equal(groups.length, 2);
  assert.deepEqual(groups[0].versions.map(item => item.id), ['a', 'b', 'c']);
  assert.equal(groups[0].folders, 2);
});

test('a name given to a title before folders joined groups still applies', () => {
  const groups = groupStories([row('a', 'New title', 'P1', 2), row('b', 'Old title', 'P1', 1)], {'old title': 'Gravity'});
  assert.equal(groups[0].label, 'Gravity');
});

test('versions show their folder and rendered clips', () => {
  assert.match(versionLabel({...row('a', 'T', 'Project-b62045ea', 1, 88), version: 3}, () => 'today'),
    /^v3 · 88 clips · 88 rendered · Project-b62045ea · saved · today$/);
});

test('named checkpoints are distinct from automatic versions', () => {
  assert.match(versionLabel({...row('a', 'Heavy', 'snapshot', 1, 88), version: 29,
    checkpoint_name: 'All boxes rendered'}, () => 'today'), /^Checkpoint: All boxes rendered · 88 clips · 88 rendered/);
});
