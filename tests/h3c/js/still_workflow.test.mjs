import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {captureRecipe, recipeControls, isolateVideoPrompt} from '../../../js/h3c_stills.mjs';

const INPUT = -10;
// A subgraph "Mine": prompt and seed are required names, the rest optional; two reference pictures.
function mine({inputs, nodes, links}) {
  return {id: 'mine', name: 'Mine', inputNode: {id: INPUT}, inputs,
    nodes, links: links.map(([id, slot, target, targetSlot]) => ({id, origin_id: INPUT, origin_slot: slot, target_id: target, target_slot: targetSlot}))};
}
const encoder = {id: 3, type: 'Encode', inputs: [{name: 'text'}, {name: 'image1'}, {name: 'image2'}]};
const sampler = {id: 4, type: 'Sample', inputs: [{name: 'seed'}, {name: 'width'}, {name: 'height'}]};
const full = () => mine({
  inputs: [{name: 'prompt', type: 'STRING'}, {name: 'seed', type: 'INT'}, {name: 'width', type: 'INT'}, {name: 'height', type: 'INT'},
    {name: 'steps', type: 'INT'}, {name: 'face', type: 'IMAGE'}, {name: 'place', type: 'IMAGE'}, {name: 'Negative_Prompt', type: 'STRING'}],
  nodes: [encoder, sampler, {id: 5, type: 'Decode', inputs: []}, {id: 6, type: 'Encode', inputs: [{name: 'text'}]}],
  links: [[1, 0, 3, 0], [2, 1, 4, 0], [3, 2, 4, 1], [4, 3, 4, 2], [5, 5, 3, 1], [6, 6, 3, 2], [7, 7, 6, 0]]});
const compiled = () => ({
  '1': {class_type: 'H3C_Timeline', inputs: {still_image: ['9:5', 0]}},
  '9:3': {class_type: 'Encode', inputs: {text: 'old'}},
  '9:4': {class_type: 'Sample', inputs: {seed: 11, width: 1024, height: 576}},
  '9:5': {class_type: 'Decode', inputs: {samples: ['9:4', 0]}},
  '9:6': {class_type: 'Encode', inputs: {text: 'blurry'}}});
const root = (definition, extra = {}) => ({
  nodes: [{id: 1, type: 'H3C_Timeline', inputs: [{name: 'still_image', link: 20}], ...extra}, {id: 9, type: 'mine'}],
  links: [[20, 9, 0, 1, 0, 'IMAGE']], definitions: {subgraphs: [definition]}});

test('a subgraph is bound by the names of its inputs', () => {
  const output = compiled(), recipe = captureRecipe({workflow: root(full()), output}, '1');
  assert.deepEqual([recipe.version, recipe.adapter, recipe.auto, recipe.label], [2, 'pixels', true, 'Mine']);
  assert.deepEqual(recipe.output, ['9:5', 0]);
  assert.deepEqual(recipe.bindings.prompt, {node: '9:3', input: 'text'});
  assert.deepEqual(recipe.bindings.seed, {node: '9:4', input: 'seed'});
  assert.deepEqual(recipe.bindings.negative, {node: '9:6', input: 'text'});
  assert.deepEqual(recipe.bindings.size, {width: [{node: '9:4', input: 'width'}], height: [{node: '9:4', input: 'height'}]});
  assert.equal(recipe.bindings.instruction, undefined);
  // Every IMAGE input is a reference slot, in the subgraph's own order; other inputs stay the user's.
  assert.deepEqual(recipe.bindings.references, [{node: '9:3', input: 'image1'}, {node: '9:3', input: 'image2'}]);
  assert.equal(recipe.reference_limit, 2);
  assert.equal(recipe.reference_label, 'image {index}');
  const controls = recipeControls({output}, recipe);
  assert.deepEqual([controls.seed, controls.width, controls.height, controls.instruction, controls.label, controls.adapter],
    [11, 1024, 576, '', 'Mine', 'pixels']);
});

test('size and references are optional; prompt and seed are not', () => {
  const small = inputs => mine({inputs, nodes: [encoder, sampler, {id: 5, type: 'Decode'}],
    links: inputs.map((input, slot) => [slot + 1, slot, input.name === 'prompt' ? 3 : 4, 0])});
  const recipe = captureRecipe({workflow: root(small([{name: 'prompt', type: 'STRING'}, {name: 'noise_seed', type: 'INT'}])), output: compiled()}, '1');
  assert.deepEqual(recipe.bindings.size, {width: [], height: []});
  assert.deepEqual(recipe.bindings.references, []);
  const controls = recipeControls({output: compiled()}, recipe);
  assert.deepEqual([controls.width, controls.height], [undefined, undefined]);
  assert.throws(() => captureRecipe({workflow: root(small([{name: 'seed', type: 'INT'}])), output: compiled()}, '1'),
    /no text input named prompt\. Name an input of the "Mine" subgraph "prompt"/);
  assert.throws(() => captureRecipe({workflow: root(small([{name: 'prompt', type: 'STRING'}])), output: compiled()}, '1'),
    /no number input named seed, so every candidate would be the same picture/);
});

test('one input that feeds several nodes sets them all', () => {
  const definition = full();
  definition.links.push({id: 8, origin_id: INPUT, origin_slot: 5, target_id: 6, target_slot: 0});
  const recipe = captureRecipe({workflow: root(definition), output: compiled()}, '1');
  assert.deepEqual(recipe.bindings.references[0], {node: '9:3', input: 'image1', more: [{node: '9:6', input: 'text'}]});
});

test('the picture wording follows the model inside, unless the Timeline says otherwise', () => {
  const output = compiled();
  output['9:3'].class_type = 'TextEncodeQwenImage21';
  assert.equal(captureRecipe({workflow: root(full()), output}, '1').reference_label, '<image{index}>');
  output['9:3'].class_type = 'MiniMaxH3ImageConditioning';
  assert.equal(captureRecipe({workflow: root(full()), output}, '1').reference_label, '<Picture {index}>');
  const chosen = properties => captureRecipe({workflow: root(full(), {properties}), output}, '1');
  assert.equal(chosen({h3c_still_reference_label: 'Figure {index}'}).reference_label, 'Figure {index}');
  assert.throws(() => chosen({h3c_still_reference_label: 'Figure'}), /must contain \{index\}/);
});

test('a nested subgraph input is followed to the node that reads it', () => {
  const inner = {id: 'inner', name: 'Inner', inputNode: {id: INPUT}, inputs: [{name: 'x', type: 'STRING'}],
    nodes: [{id: 2, type: 'Encode', inputs: [{name: 'text'}]}], links: [{id: 1, origin_id: INPUT, origin_slot: 0, target_id: 2, target_slot: 0}]};
  const outer = mine({inputs: [{name: 'prompt', type: 'STRING'}, {name: 'seed', type: 'INT'}],
    nodes: [{id: 7, type: 'inner', inputs: [{name: 'x'}]}, sampler], links: [[1, 0, 7, 0], [2, 1, 4, 0]]});
  const workflow = root(outer);
  workflow.definitions.subgraphs.push(inner);
  const output = {...compiled(), '9:7:2': {class_type: 'Encode', inputs: {text: ''}}};
  assert.deepEqual(captureRecipe({workflow, output}, '1').bindings.prompt, {node: '9:7:2', input: 'text'});
});

test('one node with its own prompt and seed needs no subgraph; a plain decoder explains what to do', () => {
  const workflow = node => ({nodes: [{id: 1, type: 'H3C_Timeline', inputs: [{name: 'still_image', link: 20}]}, node], links: [[20, 5, 0, 1, 0, 'IMAGE']]});
  const output = {'1': {class_type: 'H3C_Timeline', inputs: {still_image: ['5', 0]}},
    '5': {class_type: 'ApiImage', inputs: {prompt: '', seed: 3, model: 'x'}}};
  const recipe = captureRecipe({workflow: workflow({id: 5, type: 'ApiImage', title: 'Cloud image',
    inputs: [{name: 'prompt', type: 'STRING'}, {name: 'image', type: 'IMAGE'}]}), output}, '1');
  assert.deepEqual(recipe.bindings.prompt, {node: '5', input: 'prompt'});
  assert.deepEqual(recipe.bindings.references, [{node: '5', input: 'image'}]);
  assert.equal(recipe.label, 'Cloud image');
  output['5'] = {class_type: 'VAEDecode', inputs: {samples: ['4', 0]}};
  assert.throws(() => captureRecipe({workflow: workflow({id: 5, type: 'VAEDecode', inputs: [{name: 'samples', type: 'LATENT'}]}), output}, '1'),
    /Select the image nodes, choose Convert to Subgraph, and name one of its inputs "prompt"/);
});

test('a muted workflow is refused and video renders drop the still branch', () => {
  const workflow = root(full());
  workflow.nodes[1].mode = 4;
  assert.throws(() => captureRecipe({workflow, output: compiled()}, '1'), /missing or muted/);
  const snapshot = {workflow: root(full()), output: {...compiled(), '2': {class_type: 'SaveVideo', inputs: {video: ['1', 0]}}}};
  assert.deepEqual(Object.keys(isolateVideoPrompt(snapshot, '1', ['2']).output).sort(), ['1', '2']);
});

test('a written Still Recipe wins over still_image, so saved workflows keep their behaviour', () => {
  const output = compiled();
  output['1'].inputs.still_recipe = ['5', 0];
  assert.throws(() => captureRecipe({workflow: root(full()), output}, '1'), /must connect to H3 Still Recipe/);
});

test('the shipped Qwen example binds without a recipe node', () => {
  const example = JSON.parse(readFileSync(new URL('../../../examples/qwen_image_21_still.json', import.meta.url), 'utf8'));
  assert.ok(!example.nodes.some(node => node.type === 'H3C_StillRecipe'));
  const definition = example.definitions.subgraphs[0], instance = example.nodes.find(node => node.type === definition.id);
  const output = {'1': {class_type: 'H3C_Timeline', inputs: {still_image: [`${instance.id}:20`, 0]}}};
  for (const node of definition.nodes) output[`${instance.id}:${node.id}`] = {class_type: node.type, inputs: Object.fromEntries((node.inputs ?? []).map(input => [input.name, 0]))};
  const workflow = {...example, nodes: [...example.nodes, {id: 1, type: 'H3C_Timeline', inputs: [{name: 'still_image', link: 999}]}],
    links: [...example.links, [999, instance.id, 0, 1, 0, 'IMAGE']]};
  const recipe = captureRecipe({workflow, output}, '1');
  assert.equal(recipe.label, 'Qwen Image 2.1 Still');
  assert.equal(recipe.reference_label, '<image{index}>');
  assert.equal(recipe.reference_limit, 10);
  assert.deepEqual(recipe.bindings.references.map(ref => ref.input), Array.from({length: 10}, (_, i) => `images.image_${i + 1}`));
  assert.ok(recipe.bindings.references.every(ref => ref.node === `${instance.id}:11`));
  // The subgraph joins its own instruction to the prompt; binding it too would apply it twice.
  assert.equal(recipe.bindings.instruction, undefined);
  assert.deepEqual(recipe.bindings.prompt, {node: `${instance.id}:6`, input: 'value'});
  assert.ok(recipe.bindings.size.width.length && recipe.bindings.size.height.length);
});
