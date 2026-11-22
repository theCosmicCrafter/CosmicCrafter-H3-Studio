import test from 'node:test';
import assert from 'node:assert/strict';
import {graphWiring} from '../../../js/h3c_stills.mjs';

// The live LiteGraph shape the ComfyUI frontend keeps: nodes with port link ids, links in a Map, subgraph definitions
// in a Map keyed by the type their instances carry.
function graph() {
  const inner = {nodes: [{id: 3, type: 'SaveVideo', mode: 0, inputs: [{link: 7}], outputs: []}],
    links: new Map([[7, {id: 7, origin_id: -10, origin_slot: 0, target_id: 3, target_slot: 0}]])};
  inner.id = 'sg';
  return {
    id: 'workflow',
    nodes: [{id: 1, type: 'H3C_Timeline', mode: 0, inputs: [], outputs: [{links: [5]}]},
      {id: 2, type: 'sg', mode: 0, inputs: [{link: 5}], outputs: []}],
    links: new Map([[5, {id: 5, origin_id: 1, origin_slot: 0, target_id: 2, target_slot: 0}]]),
    subgraphs: new Map([['sg', inner]]),
  };
}

test('the wiring is read from the live graph and names subgraph instances', () => {
  const live = graph();
  const wiring = graphWiring(live);
  assert.equal(wiring.nested, true);
  assert.equal(wiring.signature, graphWiring(graph()).signature);
});

test('the wiring changes with a link, a mode or a node inside a subgraph', () => {
  const before = graphWiring(graph()).signature;
  const muted = graph();
  muted.nodes[1].mode = 2;
  assert.notEqual(graphWiring(muted).signature, before);
  const rewired = graph();
  rewired.nodes[1].inputs[0].link = 6;
  rewired.links = new Map([[6, {id: 6, origin_id: 1, origin_slot: 1, target_id: 2, target_slot: 0}]]);
  assert.notEqual(graphWiring(rewired).signature, before);
  const inside = graph();
  inside.subgraphs.get('sg').nodes[0].mode = 4;
  assert.notEqual(graphWiring(inside).signature, before);
});

test('a graph without subgraph instances, or without a graph, is not nested', () => {
  const flat = graph();
  flat.nodes.pop();
  assert.equal(graphWiring(flat).nested, false);
  assert.equal(graphWiring(undefined).nested, false);
  const legacy = {id: 'old', _nodes: [{id: 1, type: 'H3C_Timeline', mode: 0}], links: {5: [5, 1, 0, 2, 0, 'IMAGE']}};
  assert.equal(graphWiring(legacy).nested, false);
  assert.match(graphWiring(legacy).signature, /H3C_Timeline/);
});
