import test from 'node:test';
import assert from 'node:assert/strict';
import {installDom, findAll} from './fake_dom.mjs';
import * as model from '../../../js/h3c_timeline_model.mjs';
import {TimelineEditor} from '../../../js/h3c_timeline_editor.mjs';
import {FrameImages} from '../../../js/h3c_frame_images.mjs';

installDom();
const createElement = document.createElement;
document.createElement = tag => {
  const node = createElement(tag);
  if (tag === 'dialog') {
    node.showModal = () => { node.open = true; };
    node.close = () => { node.open = false; };
  }
  return node;
};

const file = filename => ({filename, subfolder: 'frames', type: 'input'});
const viewUrl = file => `/view?filename=${file.filename}&subfolder=${file.subfolder}&type=${file.type}`;
const refs = [
  {name: 'image17', title: 'Opening', mediaFile: file('first.png'), preview: viewUrl(file('first.png'))},
  {name: 'image18', title: 'Ending', mediaFile: file('last.png'), preview: viewUrl(file('last.png'))},
];

function editor() {
  const editor = Object.create(TimelineEditor.prototype);
  editor.state = model.parseState(JSON.stringify({version: 1, boxes: [
    {id: 'a', frames: 73, exact: true, prompt: 'A street.', first: 'image17', last: 'image18', flf_refmods: true},
    {id: 'b', frames: 73, exact: true, prompt: 'Next.', first: 'image17', last: 'image18'},
  ]}));
  editor.selected = 0;
  editor.host = {context: () => 39, connected: () => ({images: refs, audios: []}), viewUrl};
  editor.frameImages = new FrameImages(editor);
  return editor;
}

const images = root => findAll(root, node => node.tagName === 'IMG');
function marker(editor, kind) {
  const mark = document.createElement('button');
  editor.fillStill(mark, editor.box(), {kind}, kind === 'last' ? 'Last' : 'First');
  return mark;
}
function hero(editor, kind) {
  const panel = editor.frameImages;
  panel.boxId = editor.box().id; panel.target = {kind};
  panel.render();
  return panel.acceptedEl;
}

for (const [kind, url] of [['first', '/view?filename=first.png&subfolder=frames&type=input'],
  ['last', '/view?filename=last.png&subfolder=frames&type=input']]) {
  test(`${kind} reference fills the shared Timeline/Shot marker and Shots image`, () => {
    const target = editor();
    const before = model.serialize(target.state);
    const mark = marker(target, kind), accepted = hero(target, kind);
    assert.equal(images(mark)[0]?.dataset.src, url);
    assert.equal(images(accepted)[0]?.src, url);
    assert.equal(mark.classList.contains('accepted'), true);
    assert.match(accepted.textContent, /Frame in use/);
    assert.equal(model.serialize(target.state), before, 'displaying a reference does not create a guide');
  });
}

test('node previews without a media file appear in both views and the enlarged image', async () => {
  const target = editor();
  target.host.connected = () => ({images: [{name: 'image17', preview: 'blob:opening'}], audios: []});
  assert.equal(images(marker(target, 'first'))[0]?.dataset.src, 'blob:opening');
  const accepted = hero(target, 'first');
  assert.equal(images(accepted)[0]?.src, 'blob:opening');
  document.body = document.createElement('body');
  findAll(accepted, node => node.tagName === 'BUTTON')[0].click();
  await Promise.resolve();
  assert.equal(images(target.frameImages.previewDialog)[0]?.src, 'blob:opening');
  target.frameImages.destroy();
});

test('assigned references win over unaccepted candidates but accepted guides still win', () => {
  const target = editor(), box = target.box();
  box.previews = [{target: {kind: 'first'}, frame: 0, images: [{file: file('candidate.png')}]}];
  assert.equal(images(marker(target, 'first'))[0]?.dataset.src, refs[0].preview);
  assert.equal(images(hero(target, 'first'))[0]?.src, refs[0].preview);
  box.previews[0].guide = file('guide.png');
  assert.equal(images(marker(target, 'first'))[0]?.dataset.src, viewUrl(file('guide.png')));
  assert.equal(images(hero(target, 'first'))[0]?.src, viewUrl(file('guide.png')));
});

test('disabled, missing and RefMod slots do not appear as assigned frames', () => {
  const target = editor();
  for (const unusable of [null, {...refs[0], refmod: true}, {...refs[0], problem: 'Unavailable'}]) {
    target.host.connected = () => ({images: unusable ? [unusable] : [], audios: []});
    assert.equal(images(marker(target, 'first')).length, 0);
    assert.equal(images(hero(target, 'first')).length, 0);
  }
  target.host.connected = () => ({images: refs, audios: []});
  target.state.disabled_refs = ['image17'];
  assert.equal(images(marker(target, 'first')).length, 0);
  assert.equal(images(hero(target, 'first')).length, 0);
});

test('continuations ignore their stored First reference while Last remains visible', () => {
  const target = editor();
  target.selected = 1;
  assert.equal(images(marker(target, 'first')).length, 0);
  assert.equal(images(hero(target, 'first')).length, 0);
  assert.equal(images(marker(target, 'last'))[0]?.dataset.src, refs[1].preview);
  assert.equal(images(hero(target, 'last'))[0]?.src, refs[1].preview);
});

test('a long Timeline resolves connected references once for all its frame markers', () => {
  const target = editor();
  target.state.boxes = Array.from({length: 88}, (_, index) => ({...target.state.boxes[0], id: `clip${index}`, flf_refmods: false}));
  target.stillsEl = document.createElement('div');
  let reads = 0;
  target.host.connected = () => { reads++; return {images: refs, audios: []}; };
  target.renderStills(88 * 73, 1200);
  assert.equal(reads, 1);
  assert.equal(images(target.stillsEl).length, 89, 'First on clip 1 and Last on all 88 clips');
});
