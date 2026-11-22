import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseState, serialize } from '../../../js/h3c_timeline_model.mjs?v=1dfc1612e462';
import { splitBox } from '../../../js/h3c_shot_split.mjs?v=d147aa313f65';
import { syncTargets, acceptedGuideFrames } from '../../../js/h3c_shot_preview.mjs?v=1dfc1612e462';
import { CONTEXT, guideFile, shotGuideTimeline, savedGuideSplitTimeline, unstructuredGuideTimeline } from './shot_split_fixtures.mjs';

test('Split before Shot N keeps a targeted Shot guide with its shot', () => {
  const state = parseState(JSON.stringify(shotGuideTimeline()));
  splitBox(state, 0, 2, CONTEXT);
  syncTargets(state, CONTEXT);
  const right = state.boxes[1];
  // Shot 2 opens the right half; Shot 3 becomes its Shot 2 and still guides that shot's frame.
  assert.deepEqual(right.previews.map((p) => [p.target, p.frame, p.guide.filename]),
    [[{ kind: 'first' }, 0, 'guide_a.png'], [{ kind: 'shot', shot: 2 }, 48, 'guide_c.png']]);
  assert.ok(right.previews.every((p) => !('shot' in p)));
  assert.deepEqual(acceptedGuideFrames(state, 1, CONTEXT), [0, 48]);
});

test('Split before Shot N still renumbers legacy records by shot', () => {
  const timeline = shotGuideTimeline();
  timeline.boxes[0].previews = [{ shot: 3, frame: 144, guide: guideFile() }];
  const state = parseState(JSON.stringify(timeline));
  splitBox(state, 0, 2, CONTEXT);
  assert.deepEqual(state.boxes[1].previews.map((p) => [p.shot, p.frame]), [[2, 48]]);
});

test('Shot splitting partitions the camera action and starts the next shot with a Cut', () => {
  const timeline = shotGuideTimeline();
  timeline.boxes[0].prompt = '[Shot 1] The camera starts at her feet and tilts up.\n'
    + '[Shot 2] At 00:04.000, the camera cuts to a close-up of her face.';
  const state = parseState(JSON.stringify(timeline));
  splitBox(state, 0, 2, CONTEXT);
  assert.equal(state.boxes[0].prompt, '[Shot 1] The camera starts at her feet and tilts up.');
  assert.equal(state.boxes[1].prompt, '[Shot 1] a close-up of her face.');
  assert.equal(state.boxes[1].cut, true);
});

test('an interior guide without a timed Shot boundary cannot split or change the box', () => {
  for (const prompt of ['The camera tilts up.', '[Shot 1] The camera tilts up.\n[Shot 2] The shaft overhead.']) {
    const timeline = unstructuredGuideTimeline();
    timeline.boxes[0].prompt = prompt;
    const state = parseState(JSON.stringify(timeline)), before = serialize(state);
    assert.throws(() => splitBox(state, 0, 2, CONTEXT), /Choose a shot after the first|Give this shot a cut timestamp/);
    assert.equal(serialize(state), before);
    assert.deepEqual(acceptedGuideFrames(state, 0, CONTEXT), [80]);
  }
});

test('existing paired guides and interior guides survive target sync and save/reload without rewriting boxes', () => {
  for (const timeline of [savedGuideSplitTimeline(), unstructuredGuideTimeline()]) {
    const state = parseState(JSON.stringify(timeline)), before = serialize(state);
    syncTargets(state, CONTEXT);
    assert.equal(serialize(state), before);
    const reloaded = parseState(serialize(state));
    assert.equal(serialize(reloaded), before);
    assert.deepEqual(reloaded.boxes.map((box) => [box.prompt, box.cut, box.previews]),
      timeline.boxes.map((box) => [box.prompt, box.cut, box.previews]));
  }
});
