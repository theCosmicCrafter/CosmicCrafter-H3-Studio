import test from 'node:test';
import assert from 'node:assert/strict';
import {installDom} from './fake_dom.mjs';
import {Studio} from '../../../js/h3c_studio.mjs';
import {idleWatch, watchEvent} from '../../../js/h3c_render_watch.mjs';

installDom();
const createElement = document.createElement;
// Media DOM behavior needed by the real player, without loading video files.
document.createElement = tag => {
  const node = createElement(tag);
  Object.defineProperty(node, 'src', {
    get: () => node.getAttribute('src'), set: value => node.setAttribute('src', value),
  });
  node.matches = selector => selector === '.h3cx-message' ? node.className === 'h3cx-message'
    : selector === '.h3cx-live' ? node.className === 'h3cx-live'
    : selector === 'video:not(.h3cx-live)' ? tag === 'video' && node.className !== 'h3cx-live'
    : selector === `${tag}.h3cx-live` && node.className === 'h3cx-live';
  node.querySelectorAll = selector => node.children.filter(child => child.matches(selector));
  node.querySelector = selector => node.querySelectorAll(selector)[0] ?? null;
  node.pause = node.load = () => {};
  return node;
};

function player() {
  const studio = Object.create(Studio.prototype);
  for (const name of ['screen', 'badge', 'hint', 'fullButton', 'takeButton', 'switchButton', 'fullLinks',
    'takeLinks', 'takeOpen', 'takeDownload', 'pinButton', 'pinMenu', 'pinNote', 'soundtrackNote', 'exportStatus', 'exportProgress', 'exportMessage']) {
    studio[name] = document.createElement('div');
  }
  const editor = {
    selected: 0, state: {boxes: [{id: 'a'}, {id: 'b'}, {id: 'c'}]}, status: {ok: true},
    box() { return this.state.boxes[this.selected]; },
    statusOf(box) { return box.id === 'b' ? {status: 'done', video: {file: {filename: 'b.mp4'}}} : null; },
    fullLink: Object.assign(document.createElement('a'), {hidden: true}),
    cast: {pinTargets: () => [{id: 'actor', name: 'Actor'}]},
  };
  studio.view = 'take';
  studio.host = {editor, runningBox: () => 1, viewUrl: file => `/view/${file.filename}`};
  return studio;
}

for (const source of ['kj', 'core']) {
  test(`${source} live preview follows the selected rendering box and restores other boxes' content`, () => {
    const studio = player(), editor = studio.host.editor;
    const watch = watchEvent({...idleWatch(), running: true}, source === 'kj' ? 'kj_preview_override' : 'b_preview',
      source === 'kj' ? {image: 'frame', mime: 'image/webp', step: 2, total: 8} : new Blob(['frame'], {type: 'image/jpeg'}));
    studio.refreshPlayer(watch);
    assert.equal(studio.screen.firstElementChild.className, 'h3cx-live');
    assert.match(studio.badge.textContent, /^Live · box 1/);

    editor.selected = 1;
    studio.refreshPlayer(watch);
    assert.equal(studio.screen.firstElementChild.tagName, 'VIDEO');
    assert.equal(studio.screen.firstElementChild.src, '/view/b.mp4');
    assert.equal(studio.badge.hidden, true);
    assert.equal(studio.hint.hidden, true);
    assert.equal(studio.pinButton.hidden, false);
    assert.equal(studio.blobSrc, null);
    // Further preview updates must not replace the selected box's video.
    studio.refreshPlayer({...watch, preview: {...watch.preview, step: 3}});
    assert.equal(studio.screen.firstElementChild.src, '/view/b.mp4');

    editor.selected = 2;
    studio.refreshPlayer(watch);
    assert.equal(studio.screen.textContent, 'Not rendered yet');

    editor.selected = 0;
    studio.refreshPlayer(watch);
    assert.equal(studio.screen.firstElementChild.className, 'h3cx-live');
    assert.equal(studio.hint.hidden, source !== 'core');

    studio.refreshPlayer(watchEvent(watch, 'execution_success'));
    assert.equal(studio.screen.textContent, 'Not rendered yet');
    assert.equal(studio.blobSrc, null);
  });
}

test('an unassociated render cannot take over the selected clip viewer', () => {
  const studio = player();
  studio.host.editor.selected = 1;
  studio.host.runningBox = () => null;
  studio.refreshPlayer({...idleWatch(), running: true, preview: {source: 'kj', mime: 'video/mp4', data: 'frame'}});
  assert.equal(studio.screen.firstElementChild.src, '/view/b.mp4');
});

test('preview build is visible while watching a clip and clears when the preview is ready', () => {
  const studio = player(), editor = studio.host.editor;
  editor.selected = 1;
  editor.status.preview_video_building = true;
  studio.refreshPlayer(idleWatch());
  assert.equal(studio.exportStatus.hidden, false);
  assert.equal(studio.exportProgress.hidden, false);
  assert.match(studio.exportMessage.textContent, /Building the video so far/);
  assert.match(studio.fullButton.textContent, /Video so far/);
  assert.equal(studio.fullButton.getAttribute('aria-busy'), 'true');
  assert.equal(studio.screen.firstElementChild.src, '/view/b.mp4');

  editor.status = {ok: true};
  editor.fullLink.hidden = false;
  editor.fullLink.setAttribute('href', '/view/preview.mp4');
  editor.previewVideo = {boxes: 2, total: 3};
  studio.refreshPlayer(idleWatch());
  assert.equal(studio.exportStatus.hidden, true);
  assert.equal(studio.exportProgress.hidden, true);
  assert.equal(studio.fullButton.disabled, false);
  assert.equal(studio.fullButton.getAttribute('aria-busy'), 'false');
});

test('a failed preview explains the disabled button beside the viewer', () => {
  const studio = player();
  studio.host.editor.status.preview_error = 'Video so far skipped: the segment videos have different aspect ratios.';
  studio.refreshPlayer(idleWatch());
  assert.equal(studio.exportStatus.hidden, false);
  assert.equal(studio.exportProgress.hidden, true);
  assert.match(studio.exportMessage.textContent, /different aspect ratios/);
  assert.match(studio.fullButton.textContent, /unavailable/);
  assert.equal(studio.fullButton.disabled, true);
});

test('an older preview stays playable while the next one builds', () => {
  const studio = player(), editor = studio.host.editor;
  editor.status.preview_video_building = true;
  editor.fullLink.hidden = false;
  editor.fullLink.setAttribute('href', '/view/preview.mp4');
  editor.previewVideo = {boxes: 2, total: 3};
  studio.view = 'full';
  studio.refreshPlayer(idleWatch());
  assert.equal(studio.fullButton.disabled, false);
  assert.equal(studio.screen.firstElementChild.src, '/view/preview.mp4');
  assert.equal(studio.exportStatus.hidden, false);
  assert.match(studio.exportMessage.textContent, /Updating the video so far/);
});
