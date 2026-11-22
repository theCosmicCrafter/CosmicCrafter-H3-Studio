import test from 'node:test';
import assert from 'node:assert/strict';
import {exportedVideo, partialBadge, partialTitle, previewBadge, previewLabel, previewTitle, timelineFrame, videoSeconds}
  from '../../../js/h3c_partial_video.mjs';

const view = (filename) => ({filename, subfolder: 'h3_sequences/seq', type: 'output', v: 'x'});
const partial = {file: view('seq_partial.mp4'), rendered: 3, boxes: 6};
const soFar = {file: view('seq_sofar.mp4'), boxes: 5, total: 90, clock: [[0, 22, 0, 1]]};
const clock = [[0, 22, 0, 1], [22, 29, 22, 0], [51, 18, 22, 1]];

test('the full video wins; the partial video, then the video so far, plays only without one', () => {
  assert.deepEqual(exportedVideo({ok: true, full_video: view('seq_full.mp4'), full_video_clock: clock,
    partial_video: partial, preview_video: soFar}),
  {file: view('seq_full.mp4'), partial: null, preview: null, clock});
  assert.deepEqual(exportedVideo({ok: true, partial_video: partial, preview_video: soFar}),
    {file: partial.file, partial, preview: null, clock: null});
  assert.deepEqual(exportedVideo({ok: true, preview_video: soFar}),
    {file: soFar.file, partial: null, preview: soFar, clock: soFar.clock});
  assert.equal(exportedVideo({ok: true}), null);
  assert.equal(exportedVideo(null), null);
});

test('the label says how much is repainted, and the title adds what is left out', () => {
  assert.equal(partialBadge(partial), 'Partial video · 3 of 6 clips repainted, the rest from the source');
  assert.equal(partialTitle(partial), '3 of 6 clips repainted, the rest from the source.');
  assert.equal(partialTitle({...partial, note: 'Bridges and replacements are left out.'}),
    '3 of 6 clips repainted, the rest from the source. Bridges and replacements are left out.');
});

test('the video so far says which clips it plays', () => {
  assert.equal(previewLabel(soFar), 'Video so far · 5/90');
  assert.equal(previewBadge(soFar), 'Video so far · clips 1–5 of 90');
  assert.equal(previewBadge({...soFar, boxes: 1}), 'Video so far · clip 1 of 90');
  assert.match(previewTitle(soFar), /^Play clips 1–5 of 90, rendered so far, joined with the soundtrack/);
});

test('the playhead follows the video clock: a bridge holds the Timeline, then it moves on', () => {
  assert.equal(timelineFrame(clock, 0.5), 12);
  assert.equal(timelineFrame(clock, 30 / 24), 22, 'inside the bridge');
  assert.equal(timelineFrame(clock, 60 / 24), 31);
  assert.equal(timelineFrame(clock, 100), 40, 'past the end it holds at the end');
  assert.equal(timelineFrame(null, 1), 24, 'without a clock the video is the Timeline');
});

test('seeking finds the video moment of a Timeline frame, or null past the video', () => {
  assert.equal(videoSeconds(clock, 12), 0.5);
  assert.equal(videoSeconds(clock, 31), 60 / 24);
  assert.equal(videoSeconds(clock, 40), null);
  assert.equal(videoSeconds(null, 48), 2);
});
