import test from 'node:test';
import assert from 'node:assert/strict';
import {snapFrames} from '../../../js/h3c_timeline_model.mjs';

test('frame lengths snap to the H3 grid', () => {
  assert.equal(snapFrames(100, true, 39), 107);
});
