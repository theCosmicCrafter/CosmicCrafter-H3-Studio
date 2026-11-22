import test from 'node:test';
import assert from 'node:assert/strict';
import {captureRecipe, recipeControls} from '../../../js/h3c_stills.mjs';

const slots = Array.from({length: 8}, (_, i) => ({name: `images.image_${i + 1}`, link: null}));
const generator = (id, extra = {}) => ({id, type: 'H3C_PH3ImageStill', inputs: [{name: 'prompt'}, {name: 'seed'}, slots[0]], ...extra});
const inputs = {diffusion_model: 'p-h3-image_int8_convrot.safetensors', prompt: 'A kitchen at dawn.', instruction: 'Film still.', seed: 7, width: 1024, height: 576};

test('the P-H3-Image node is its own generator: its recipe output addresses its own inputs', () => {
  const output = {'1': {class_type: 'H3C_Timeline', inputs: {still_recipe: ['5', 1]}}, '5': {class_type: 'H3C_PH3ImageStill', inputs}};
  const recipe = captureRecipe({workflow: {nodes: [{id: 1, type: 'H3C_Timeline'}, generator(5)]}, output}, '1');
  assert.deepEqual(recipe.output, ['5', 0]);
  assert.equal(recipe.version, 2);
  assert.equal(recipe.adapter, 'pixels');
  assert.equal(recipe.label, 'P-H3-Image');
  assert.equal(recipe.reference_limit, 8);
  assert.equal(recipe.reference_label, '<Picture {index}>');
  assert.deepEqual(recipe.bindings.prompt, {node: '5', input: 'prompt'});
  assert.deepEqual(recipe.bindings.instruction, {node: '5', input: 'instruction'});
  assert.deepEqual(recipe.bindings.seed, {node: '5', input: 'seed'});
  assert.deepEqual(recipe.bindings.size, {width: [{node: '5', input: 'width'}], height: [{node: '5', input: 'height'}]});
  assert.deepEqual(recipe.bindings.references.map(ref => ref.input), slots.map(slot => slot.name));
  assert.ok(recipe.bindings.references.every(ref => ref.node === '5'));
});

test('a copy inside a native subgraph keeps its prefixed execution id', () => {
  const output = {'1': {class_type: 'H3C_Timeline', inputs: {still_recipe: ['9:5', 1]}}, '9:5': {class_type: 'H3C_PH3ImageStill', inputs}};
  const workflow = {nodes: [{id: 1, type: 'H3C_Timeline'}, {id: 9, type: 'sg'}], definitions: {subgraphs: [{id: 'sg', nodes: [generator(5)]}]}};
  const recipe = captureRecipe({workflow, output}, '1');
  assert.deepEqual(recipe.output, ['9:5', 0]);
  assert.deepEqual(recipe.bindings.prompt, {node: '9:5', input: 'prompt'});
  assert.deepEqual(recipe.bindings.size.width, [{node: '9:5', input: 'width'}]);
  assert.ok(recipe.bindings.references.every(ref => ref.node === '9:5'));
});

test('unmaterialized autogrow sockets remain available for Timeline references', () => {
  for (const visible of [[], slots.slice(0, 1), slots.slice(0, 3)]) {
    const output = {'1': {class_type: 'H3C_Timeline', inputs: {still_recipe: ['5', 1]}},
      '5': {class_type: 'H3C_PH3ImageStill', inputs: {...inputs}}};
    if (visible.length > 1) {
      output['5'].inputs['images.image_1'] = ['8', 0];
      output['8'] = {class_type: 'LoadImage', inputs: {image: 'identity.png'}};
    }
    const workflow = {nodes: [{id: 1, type: 'H3C_Timeline'}, generator(5, {inputs: visible})]};
    const recipe = captureRecipe({workflow, output}, '1');
    assert.deepEqual(recipe.bindings.references, slots.map(slot => ({node: '5', input: slot.name})));
    assert.deepEqual(recipeControls({output}, recipe).additionalReferences ?? [], visible.length > 1 ? ['@still1'] : []);
  }
});

test('Studio controls read the node\'s own seed, size and label', () => {
  const output = {'1': {class_type: 'H3C_Timeline', inputs: {still_recipe: ['5', 1]}}, '5': {class_type: 'H3C_PH3ImageStill', inputs}};
  const recipe = captureRecipe({workflow: {nodes: [{id: 1, type: 'H3C_Timeline'}, generator(5)]}, output}, '1');
  const controls = recipeControls({output}, recipe);
  assert.deepEqual([controls.seed, controls.width, controls.height, controls.label, controls.adapter, controls.referenceLabel, controls.instruction],
    [7, 1024, 576, 'P-H3-Image', 'pixels', '<Picture {index}>', 'Film still.']);
});

test('a muted or missing node is refused', () => {
  const output = {'1': {class_type: 'H3C_Timeline', inputs: {still_recipe: ['5', 1]}}, '5': {class_type: 'H3C_PH3ImageStill', inputs}};
  assert.throws(() => captureRecipe({workflow: {nodes: [{id: 1, type: 'H3C_Timeline'}, generator(5, {mode: 4})]}, output}, '1'), /muted/);
  assert.throws(() => captureRecipe({workflow: {nodes: [{id: 1, type: 'H3C_Timeline'}]}, output}, '1'), /muted/);
});

test('the image output cannot stand in for the recipe', () => {
  const output = {'1': {class_type: 'H3C_Timeline', inputs: {still_recipe: ['5', 0]}}, '5': {class_type: 'H3C_PH3ImageStill', inputs}};
  assert.throws(() => captureRecipe({workflow: {nodes: [{id: 1, type: 'H3C_Timeline'}, generator(5)]}, output}, '1'),
    /must connect to H3 Still Recipe or P-H3-Image Still/);
});

test('Still Recipe bindings keep working', () => {
  const bindings = {version: 2, adapter: 'pixels', label: 'Other', reference_limit: 1, reference_label: 'Image {index}',
    prompt: {node: ['7'], input: 'prompt'}, instruction: {node: ['7'], input: 'instruction'}, seed: {node: ['7'], input: 'seed'},
    size: {width: [{node: ['7'], input: 'width'}], height: [{node: ['7'], input: 'height'}]}, references: [{node: ['7'], input: 'ref'}]};
  const output = {'1': {class_type: 'H3C_Timeline', inputs: {still_recipe: ['6', 0]}},
    '6': {class_type: 'H3C_StillRecipe', inputs: {image: ['7', 0], bindings: JSON.stringify(bindings)}},
    '7': {class_type: 'Other', inputs: {prompt: 'p', instruction: '', seed: 1, width: 64, height: 64}}};
  const other = {id: 7, type: 'Other', inputs: [{name: 'ref'}]};
  const recipe = captureRecipe({workflow: {nodes: [{id: 1, type: 'H3C_Timeline'}, {id: 6, type: 'H3C_StillRecipe', inputs: [{name: 'image', link: 3}]}, other],
    links: [[3, 7, 0, 6, 0, 'IMAGE']]}, output}, '1');
  assert.deepEqual(recipe.output, ['7', 0]);
  assert.equal(recipe.label, 'Other');
  assert.deepEqual(recipe.bindings.prompt, {node: '7', input: 'prompt'});
  other.inputs = [];
  assert.throws(() => captureRecipe({workflow: {nodes: [{id: 1, type: 'H3C_Timeline'}, {id: 6, type: 'H3C_StillRecipe', inputs: [{name: 'image', link: 3}]}, other],
    links: [[3, 7, 0, 6, 0, 'IMAGE']]}, output}, '1'), /references\[0\].*ref.*missing/);
});
