import test from 'node:test';
import assert from 'node:assert/strict';
import {installDom} from './fake_dom.mjs';

installDom();
const {iconButton, setIconLabel} = await import('../../../js/h3c_icons.mjs');

// Replacing a node, even with the same words, restyles the whole ComfyUI page, so a label that is unchanged keeps its node
// and a changed one only changes its words.
test('an icon button label keeps its text node when set again, and changes its words in place', () => {
  const button = iconButton('save', 'Render 93 remaining', () => {});
  const caption = button.children.find(node => node.className === 'h3ci-sr');
  const text = caption.firstChild;
  setIconLabel(button, 'Render 93 remaining');
  assert.equal(caption.firstChild, text);
  setIconLabel(button, 'Render 89 remaining');
  assert.equal(caption.firstChild, text, 'the same text node carries the new words');
  assert.equal(caption.textContent ?? text.data ?? text.text, 'Render 89 remaining');
  assert.equal(button.title, 'Render 89 remaining');
});
