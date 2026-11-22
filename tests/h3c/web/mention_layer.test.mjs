import test from 'node:test';
import assert from 'node:assert/strict';
import { installDom } from './fake_dom.mjs';

installDom();
const { MentionLayer } = await import('../../../js/h3c_mentions.mjs');

function layer(value, live) {
  const area = document.createElement('textarea');
  area.value = value;
  const marks = new MentionLayer(area, { live: () => new Set(live), onHover() {}, onLeave() {} });
  marks.render();
  return { area, marks };
}

const shown = (marks) => marks.layer.childNodes.map((node) => node.nodeType === 3 ? node.data : `[${node.className} ${node.textContent}]`);
const kept = (marks, nodes) => marks.layer.childNodes.length === nodes.length && marks.layer.childNodes.every((node, index) => node === nodes[index]);

test('typing around the mentions changes the highlighted text in place', () => {
  const live = ['image1'];
  const { area, marks } = layer('Look at @image1 now', live);
  const nodes = [...marks.layer.childNodes];
  area.value = 'Look closely at @image1 now!';
  area.fire('input');
  assert.ok(kept(marks, nodes), 'the layer nodes were replaced');
  assert.deepEqual(shown(marks), ['Look closely at ', '[h3cm-mark @image1]', ' now!']);
  assert.ok(marks.marks.length === 1 && marks.marks[0].part.name === 'image1' && marks.marks[0].mark === nodes[1]);
  live.length = 0;
  area.fire('input');
  assert.ok(kept(marks, nodes), 'the layer nodes were replaced');
  assert.deepEqual(shown(marks), ['Look closely at ', '[h3cm-mark missing @image1]', ' now!']);
});

test('layers drawn in one redraw read their textareas together at the next frame, after all of them wrote', (t) => {
  const log = [], frames = [];
  globalThis.requestAnimationFrame = (callback) => { frames.push(callback); return frames.length; };
  globalThis.getComputedStyle = (area) => {
    log.push(`style ${area.name}`);
    return {backgroundColor: 'rgb(1, 2, 3)', fontSize: '13px', paddingTop: '4px'};
  };
  t.after(() => { delete globalThis.requestAnimationFrame; delete globalThis.getComputedStyle; });
  const connected = (name, value) => {
    const area = document.createElement('textarea');
    Object.assign(area, {name, value, isConnected: true});
    Object.defineProperty(area, 'scrollTop', {get() { log.push(`scroll ${name}`); return 12; }});
    const marks = new MentionLayer(area, {live: () => new Set(['image1']), onHover() {}, onLeave() {}});
    return {area, marks};
  };
  const first = connected('first', 'Look at @image1'), second = connected('second', 'And @image1 again');
  first.marks.render();
  second.marks.render();
  assert.deepEqual(log, [], 'a layer read its textarea while the redraw was still writing');
  assert.equal(frames.length, 1);
  frames.shift()();
  assert.deepEqual(log.filter((entry) => entry.startsWith('style')), ['style first', 'style second']);
  for (const {area, marks} of [first, second]) {
    assert.equal(marks.layer.style.fontSize, '13px');
    assert.equal(marks.layer.style.backgroundColor, 'rgb(1, 2, 3)');
    assert.equal(area.style.backgroundColor, 'transparent');
    assert.equal(marks.layer.scrollTop, 12);
  }
  log.length = 0;
  first.area.value = 'Look closer at @image1';
  first.area.fire('input');
  assert.deepEqual(log, []);
  frames.shift()();
  assert.deepEqual(log, ['scroll first'], 'a painted layer follows only the scroll position');
});

test('a mention or final newline that comes or goes redraws the highlights', () => {
  const { area, marks } = layer('Look at @image1', ['image1']);
  area.value = 'Look at @image1 and @audio2';
  area.fire('input');
  assert.deepEqual(shown(marks), ['Look at ', '[h3cm-mark @image1]', ' and ', '[h3cm-mark missing @audio2]']);
  assert.deepEqual(marks.marks.map(({ part }) => part.name), ['image1', 'audio2']);
  area.value = 'Look at @image1 and @audio2\n';
  area.fire('input');
  assert.equal(marks.layer.textContent, `${area.value} `);
  area.value = 'Look at @image1 and @audio2\nNext';
  area.fire('input');
  assert.equal(marks.layer.textContent, area.value);
  area.value = 'Look at';
  area.fire('input');
  assert.deepEqual(shown(marks), ['Look at']);
  assert.deepEqual(marks.marks, []);
});
