import test from 'node:test';
import assert from 'node:assert/strict';
import {installDom} from './fake_dom.mjs';
import * as model from '../../../js/h3c_timeline_model.mjs';

installDom();
const {FrameImages} = await import('../../../js/h3c_frame_images.mjs');

// The still panel against a host whose saved-sources answers the test releases by hand.
function panel() {
  const asked = [];
  const state = model.parseState(JSON.stringify({version: 1, prompt: '', boxes: [{id: 'a', frames: 96, prompt: 'A street.'}]}));
  const host = {
    context: () => 39, connected: () => ({images: []}), read: () => model.serialize(editor.state), referenceContext: () => 'g1',
    stillSources(request, {signal} = {}) {
      return new Promise((resolve, reject) => {
        asked.push({request, signal, resolve});
        signal?.addEventListener('abort', () => reject(signal.reason));
      });
    },
  };
  const editor = {host, state, selected: 0, commits: 0, box() { return this.state.boxes[this.selected]; },
    commit() { this.commits += 1; }};
  const frames = new FrameImages(editor);
  editor.frameImages = frames;
  Object.assign(frames, {boxId: 'a', target: {kind: 'first'}, render() {}});
  return {frames, editor, asked};
}

const pin = (take) => ({sequence: 's', box: 'a', take, created: '2026-11-01T10:00:00', layout: 'h3', latent_stamp: [1, 2], moment: 0});

test('frame prompt edits persist separately and blank text uses the latest clip prompt', async () => {
  const {frames, editor} = panel();
  editor.state.prompt="Soft graphite shading. MIRA carries a blue umbrella.";
  editor.state.boxes[0].prompt='integrated_multimodal_description:\n\n[Shot 1] The stone fountain in a quiet courtyard. Nobody.\n\noverall_soundscape:\nSoft rain.\n\nnon_diegetic_music:\nN/A';
  frames.adapter='pixels';frames.referenceLabel='<Picture {index}>';
  assert.equal(frames.promptEl.value,'');
  frames.refreshControls=()=>{};
  const submitted=[];
  frames.host.generateStill=async request=>{submitted.push(request);return {state:'complete', request};};
  frames.renderGenerateControls();
  assert.equal(frames.generateButton.disabled,false);
  assert.equal((await frames.generate()).request.prompt,'integrated_multimodal_description:\n\n[Shot 1] The stone fountain in a quiet courtyard. Nobody.\n\noverall_soundscape:\nSoft rain.\n\nnon_diegetic_music:\nN/A');
  editor.state.boxes[0].prompt='The courtyard at dusk. Nobody.';
  frames.promptEl.value='   ';
  frames.renderGenerateControls();
  assert.equal(frames.generateButton.disabled,false);
  assert.equal((await frames.generate()).request.prompt,'The courtyard at dusk. Nobody.');
  frames.promptEl.value='An explicit still.';
  frames.promptEl.dispatchEvent({type:'input'});
  frames.promptEl.dispatchEvent({type:'change'});
  assert.equal(editor.state.boxes[0].previews[0].still_prompt,'An explicit still.');
  assert.equal(editor.state.boxes[0].prompt,'The courtyard at dusk. Nobody.');
  editor.state=model.parseState(model.serialize(editor.state));
  frames.promptEl.value='';
  frames.renderGenerateControls();
  assert.equal(frames.generateButton.disabled,false);
  assert.equal((await frames.generate()).request.prompt,'An explicit still.');
  frames.promptEl.dispatchEvent({type:'input'});
  frames.promptEl.dispatchEvent({type:'change'});
  assert.equal((await frames.generate()).request.prompt,'The courtyard at dusk. Nobody.');
  assert.equal(submitted.length,4);
});

test('a frame edit overrides a shared prepared prompt only for its own target', async () => {
  const {frames, editor}=panel();
  const first={kind:'first'},last={kind:'last'};
  editor.state.boxes[0].prompt='';
  editor.state.still_prompt_preparation={prompts:[{members:[{box:'a',target:first},{box:'a',target:last}],prompt:'A prepared still.'}]};
  frames.refreshControls=()=>{};
  frames.host.generateStill=async request=>({state:'complete',request});
  assert.ok(frames.promptSummary.children[0].children.includes(frames.promptEl));
  frames.saveField('still_prompt','First frame only.');
  assert.equal((await frames.generate()).request.prompt,'First frame only.');
  frames.target=last;
  assert.equal((await frames.generate()).request.prompt,'A prepared still.');
  assert.equal(editor.state.boxes[0].prompt,'');
});

test('Generate stays disabled only when neither still nor video text is available', async () => {
  const {frames,editor}=panel();
  editor.state.prompt='A global style cannot stand in for an empty clip.';
  editor.state.boxes[0].prompt='';frames.promptEl.value='   ';
  frames.refreshControls=()=>{};
  frames.host.generateStill=async()=>assert.fail('No request should be submitted');
  frames.renderGenerateControls();
  assert.equal(frames.generateButton.disabled,true);
  await assert.rejects(frames.generate(),/frame image prompt or a clip video prompt/);
});

test('an empty image seed draws a new random seed for every candidate request', async () => {
  const {frames, editor} = panel();
  frames.promptEl.value='A still.';
  frames.refreshControls=()=>{};
  frames.host.generateStill=async request=>({state:'complete', request});
  editor.state.boxes[0].seed=610001;
  for (const scope of ['native', 'box']) {
    frames.seedScope=scope;frames.seedEl.value='';
    const seeds=[];
    for (let i=0;i<4;i++) seeds.push((await frames.generate()).request.seed);
    for (const seed of seeds) assert.ok(Number.isSafeInteger(seed) && seed >= 0 && seed < 2 ** 32, `seed ${seed}`);
    assert.ok(new Set(seeds).size > 1, `${scope} seeds repeat: ${seeds}`);
    assert.ok(!seeds.includes(610001));
  }
  frames.seedEl.value='42';
  assert.equal((await frames.generate()).request.seed, 42);
});

test('a newer saved-sources load cancels the one it replaces before the host asks the server', async () => {
  const {frames, asked} = panel();
  const first = frames.loadSources(), second = frames.loadSources();
  assert.equal(asked.length, 2);
  assert.equal(asked[0].signal?.aborted, true);
  assert.equal(asked[1].signal?.aborted, false);
  asked[1].resolve({ok: true, choices: [pin('t2')], suggested: pin('t2')});
  await Promise.all([first, second]);
  assert.equal(frames.sourcesFailed, false);
  assert.equal(frames.noteEl.textContent, '');
  assert.equal(frames.sourceEl.options.length, 2);
  assert.match(frames.sourceEl.options[1].textContent, /^a · 2026-11-01T10:00:00/);
  assert.equal(frames.sourceEl.value, '');
});

test('the only load for a target is never cancelled and its answer fills the source list', async () => {
  const {frames, editor, asked} = panel();
  const load = frames.loadSources();
  assert.equal(asked[0].signal?.aborted, false);
  asked[0].resolve({ok: true, choices: [pin('t1')], suggested: pin('t1')});
  await load;
  assert.equal(frames.sourceEl.options.length, 2);
  assert.equal(editor.state.boxes[0].previews[0].still_source, null);
});

test('finished candidates are chosen right under the image, not below the prompt', () => {
  const {frames, editor} = panel();
  const box = editor.state.boxes[0];
  box.previews = [{target: {kind: 'first'}, frame: 0, images: [1, 2].map(n => ({file: {filename: `c${n}.png`, subfolder: '', type: 'output'}, seed: n, prompt: 'p'}))}];
  Object.assign(editor, {uploadNote: null});
  frames.host.viewUrl = file => `/view?filename=${file.filename}`;
  frames.host.pinGuide = null;
  frames.promptEl.value = 'p';
  delete frames.render;
  frames.render();
  const order = [...frames.root.children];
  assert.equal(order.indexOf(frames.candidatePicker), order.indexOf(frames.acceptedEl) + 1);
  assert.equal(frames.candidatePicker.hidden, false);
  assert.equal(frames.candidatesEl.children.length, 2);
  const caption = frames.acceptedEl.children.at(-1);
  assert.ok(caption.children.some(child => child.textContent === 'Use as guide'), 'the previewed candidate can be used from the image itself');
});

test('the saved ending of the clip before waits for edits to pause, and is not read for a clip left meanwhile', async () => {
  const {frames, editor} = panel();
  editor.state.boxes.push({id: 'b', frames: 96, prompt: 'B.'});
  const read = [];
  let release;
  frames.host.readBoundary = async id => {read.push(id);return null;};
  frames.host.stillsSettled = () => new Promise(resolve => {release = resolve;});
  frames.host.touchStills = () => {};
  Object.assign(frames, {boxId: 'b', target: {kind: 'first'}});
  const stayed = frames.showEnding();
  await Promise.resolve();
  assert.deepEqual(read, []);
  release();
  await stayed;
  assert.deepEqual(read, ['b']);
  const left = frames.showEnding();
  await Promise.resolve();
  frames.boxId = 'a';
  release();
  await left;
  assert.deepEqual(read, ['b'], 'the clip was left before the pause');
});
