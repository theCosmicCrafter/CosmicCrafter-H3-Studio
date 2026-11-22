import { test } from 'node:test';
import assert from 'node:assert/strict';
import { checkState } from '../../../js/h3c_check.mjs?v=0ba848400498';

const base = {checked: '2026-11-04T07:40:00', model: null, problems: null};

test('holds read as lines and enable Retake', () => {
  const state = checkState({...base, holds: [{start_ms: 0, frames: 3, join: true}, {start_ms: 4167, frames: 12, join: false}]});
  assert.deepEqual(state.lines, ['Holds still: 3 frames at the join.', 'Holds still: 12 frames at 4.2 s.']);
  assert.equal(state.retake, true);
});

test('texture words arrive through drift words unchanged', () => {
  const state = checkState({...base, drift: {box: 'a', words: 'warmer and 30% grainier', texture: [1.3, 1, 1]}}, () => 1);
  assert.deepEqual(state.lines, ['Drift: warmer and 30% grainier than box 1.']);
});

test('no holds and no drift: nothing to retake', () => {
  assert.equal(checkState({...base, holds: []}).retake, false);
});
