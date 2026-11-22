import { test } from 'node:test';
import assert from 'node:assert/strict';
import { TakesClient, fromText, marksText } from '../../../js/h3c_takes.mjs?v=15deab5acdd6';

test('marks read as stars and tag', () => {
  assert.equal(marksText(4, 'keeper'), '★★★★☆ · keeper');
  assert.equal(marksText(0, 'wide'), 'tag: wide');
  assert.equal(marksText(0, ''), '');
});

test('a rating posts to the rate route', async () => {
  const sent = [];
  const client = new TakesClient(async (url, body) => { sent.push([url, body]); return {ok: true}; });
  assert.deepEqual(await client.send('rate', {created: 'c', rating: 3, tag: ''}), {ok: true});
  assert.deepEqual(sent, [['/h3c/timeline/takes/rate', {created: 'c', rating: 3, tag: ''}]]);
});

test('lineage names the take of the box before and whether it is in use', () => {
  assert.equal(fromText('2026-11-04T07:30:46', 3, {created: '2026-11-04T07:30:46'}), 'from box 2’s take of 11-04 07:30 (in use)');
  assert.equal(fromText('2026-11-04T07:30:46', 3, {created: 'other'}), 'from box 2’s take of 11-04 07:30');
  assert.equal(fromText(null, 3, null), '');
  assert.equal(fromText('x', 1, null), '');
});
