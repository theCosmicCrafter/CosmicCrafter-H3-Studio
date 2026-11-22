import test from 'node:test';
import assert from 'node:assert/strict';
import {installDom} from './fake_dom.mjs';
import {replaceChanged, setText} from '../../../js/h3c_dom.mjs';

installDom();

function box(label, title = '') {
  const node = document.createElement('div');
  node.className = 'box';
  node.title = title;
  node.append(label);
  return node;
}

test('a redraw keeps the children that did not change', () => {
  const parent = document.createElement('div');
  replaceChanged(parent, [box('#1'), box('#2'), box('#3')]);
  const [first, second, third] = parent.childNodes;
  parent.replaced = 0;
  replaceChanged(parent, [box('#1'), box('#2 ✓'), box('#3')]);
  assert.equal(parent.childNodes[0], first);
  assert.notEqual(parent.childNodes[1], second);
  assert.equal(parent.childNodes[1].textContent, '#2 ✓');
  assert.equal(parent.childNodes[2], third);
  assert.equal(parent.replaced, 1);
});

test('a redraw adds and removes only at the end when the count changes', () => {
  const parent = document.createElement('div');
  replaceChanged(parent, [box('#1'), box('#2')]);
  const [first] = parent.childNodes;
  replaceChanged(parent, [box('#1'), box('#2'), box('#3')]);
  assert.equal(parent.childNodes.length, 3);
  assert.equal(parent.childNodes[0], first);
  replaceChanged(parent, [box('#1')]);
  assert.deepEqual(parent.childNodes.map((node) => node.textContent), ['#1']);
  assert.equal(parent.childNodes[0], first);
});

test('a changed tooltip alone is written onto the drawn element', () => {
  const parent = document.createElement('div');
  replaceChanged(parent, [box('#1', 'Clip 1: an old prompt')]);
  const [first] = parent.childNodes;
  parent.replaced = 0;
  replaceChanged(parent, [box('#1', 'Clip 1: a new prompt')]);
  assert.equal(parent.childNodes[0], first);
  assert.equal(first.title, 'Clip 1: a new prompt');
  assert.equal(parent.replaced, 0);
});

test('a node already in the page is placed itself, never a copy that looks the same', () => {
  const parent = document.createElement('div');
  const playhead = box('|');
  replaceChanged(parent, [box('#1'), box('#2'), playhead]);
  replaceChanged(parent, [box('#1'), box('|'), playhead]);
  replaceChanged(parent, [box('#1'), playhead]);
  assert.equal(parent.childNodes[1], playhead);
  assert.equal(parent.childNodes.length, 2);
});

function clip(number, seconds, left) {
  const node = box(`#${number} · ${seconds} s`, `Clip ${number}: ${seconds} s`);
  node.setAttribute('aria-label', `Clip ${number}`);
  node.style.left = left;
  node.dataset.frames = String(seconds * 24);
  const handle = document.createElement('div');
  handle.className = 'handle';
  node.append(handle);
  node.addEventListener('click', () => { parent.clicked.push(number); });
  return node;
}
const label = (node) => node.getAttribute('aria-label');
let parent;

test('with a key, children that only moved or changed words take the new markup in place and keep their listeners', () => {
  parent = Object.assign(document.createElement('div'), {clicked: []});
  replaceChanged(parent, [clip(1, 4, '0%'), clip(2, 4, '50%')], label);
  const [first, second] = parent.childNodes;
  parent.replaced = 0;
  replaceChanged(parent, [clip(1, 6, '0%'), clip(2, 4, '60%')], label);
  assert.equal(parent.replaced, 0);
  assert.equal(parent.childNodes[0], first);
  assert.equal(parent.childNodes[1], second);
  assert.equal(first.textContent, '#1 · 6 s');
  assert.equal(first.title, 'Clip 1: 6 s');
  assert.equal(first.dataset.frames, '144');
  assert.equal(second.style.left, '60%');
  assert.ok(first.isEqualNode(clip(1, 6, '0%')));
  second.click();
  assert.deepEqual(parent.clicked, [2]);
});

test('with a key, a child is replaced when its key, its shape or its nesting changes', () => {
  parent = Object.assign(document.createElement('div'), {clicked: []});
  replaceChanged(parent, [clip(1, 4, '0%'), clip(2, 4, '50%'), clip(3, 4, '75%')], label);
  const [first, second, third] = parent.childNodes;
  const longer = clip(2, 4, '50%');
  longer.append(document.createElement('img'));
  const renamed = clip(3, 4, '75%');
  renamed.setAttribute('aria-label', 'Clip 4');
  parent.replaced = 0;
  replaceChanged(parent, [clip(1, 4, '0%'), longer, renamed], label);
  assert.equal(parent.childNodes[0], first);
  assert.equal(parent.childNodes[1], longer);
  assert.notEqual(parent.childNodes[1], second);
  assert.equal(parent.childNodes[2], renamed);
  assert.notEqual(parent.childNodes[2], third);
  assert.equal(parent.replaced, 2);
});

test('with a key, attributes the new child lacks are removed from the kept one', () => {
  parent = Object.assign(document.createElement('div'), {clicked: []});
  const selected = clip(1, 4, '0%');
  selected.classList.add('selected');
  selected.setAttribute('aria-current', 'true');
  replaceChanged(parent, [selected], label);
  replaceChanged(parent, [clip(1, 4, '0%')], label);
  assert.equal(parent.childNodes[0], selected);
  assert.equal(selected.className, 'box');
  assert.equal(selected.getAttribute('aria-current'), null);
});

function thumbed(number, file) {
  const node = clip(number, 4, '0%');
  const image = document.createElement('img');
  image.dataset.src = `/view?filename=${file}`;
  node.prepend(image);
  return node;
}

test('a deferred image loads once its node is placed, and never on a new node the redraw throws away', () => {
  parent = Object.assign(document.createElement('div'), {clicked: []});
  replaceChanged(parent, [thumbed(1, 'a.png')], label);
  const [first] = parent.childNodes, image = first.childNodes[0];
  assert.equal(image.getAttribute('src'), '/view?filename=a.png');
  const same = thumbed(1, 'a.png');
  parent.replaced = 0;
  replaceChanged(parent, [same], label);
  assert.equal(parent.childNodes[0], first);
  assert.equal(parent.replaced, 0);
  assert.equal(same.childNodes[0].getAttribute('src'), null);
  replaceChanged(parent, [thumbed(1, 'b.png')], label);
  assert.equal(parent.childNodes[0], first);
  assert.equal(image.getAttribute('src'), '/view?filename=b.png');
  const renamed = thumbed(2, 'c.png');
  replaceChanged(parent, [renamed], label);
  assert.equal(parent.childNodes[0], renamed);
  assert.equal(renamed.childNodes[0].getAttribute('src'), '/view?filename=c.png');
});

test('setting the same text keeps the text node, and new words change it in place', () => {
  const label = document.createElement('span');
  label.append('Saved');
  const node = label.firstChild;
  setText(label, 'Saved');
  assert.equal(label.firstChild, node);
  setText(label, 'Saving…');
  assert.equal(label.firstChild, node);
  assert.equal(label.textContent, 'Saving…');
  setText(label, '');
  assert.equal(label.textContent, '');
});
