import assert from 'node:assert/strict';
import test from 'node:test';
import {DEFAULT_AHEAD, QueueFeed, feedNote, queueAhead} from '../../../js/h3c_queue_feed.mjs';
import {idleWatch, progressText, watchEvent} from '../../../js/h3c_render_watch.mjs';

// A ComfyUI that records what the feed posts and cancels, and lets a test deliver events.
function setup({total, ahead = 2, postFails = null, states = {}} = {}) {
  const handlers = new Map(), posted = [], cancelled = [], ends = [];
  let count = 0;
  const feed = new QueueFeed({
    total, ahead,
    post: async () => {
      if (postFails === posted.length) throw new Error('HTTP 500');
      const id = `run${++count}`;
      posted.push(id);
      return id;
    },
    cancel: async ids => { cancelled.push(...ids); },
    lookup: async id => states[id] ?? 'queued',
    listen: (type, handler) => { handlers.set(type, handler); return () => handlers.delete(type); },
    onEnd: outcome => ends.push(outcome),
  });
  const send = (type, detail) => handlers.get(type)?.({detail});
  const settle = () => new Promise(resolve => setImmediate(resolve));
  return {feed, posted, cancelled, ends, send, settle, handlers};
}

test('the setting keeps the default for anything that is not a count, and 0 means everything', () => {
  assert.equal(queueAhead(undefined), DEFAULT_AHEAD);
  assert.equal(queueAhead(''), DEFAULT_AHEAD);
  assert.equal(queueAhead('x'), DEFAULT_AHEAD);
  assert.equal(queueAhead(-2), DEFAULT_AHEAD);
  assert.equal(queueAhead(0), 0);
  assert.equal(queueAhead('5'), 5);
  assert.equal(queueAhead(4.7), 4);
});

test('only the first runs are posted, and each success posts the next', async () => {
  const t = setup({total: 5, ahead: 2});
  await t.feed.start();
  assert.deepEqual(t.posted, ['run1', 'run2']);
  assert.equal(t.feed.held, 3);
  t.send('execution_success', {prompt_id: 'run1'});
  await t.settle();
  assert.deepEqual(t.posted, ['run1', 'run2', 'run3']);
  assert.equal(t.feed.held, 2);
  t.send('execution_success', {prompt_id: 'someone-elses'});
  await t.settle();
  assert.equal(t.posted.length, 3, 'a run that is not the feed’s changes nothing');
  t.feed.close();
});

test('the feed ends done after the last run succeeds', async () => {
  const t = setup({total: 3, ahead: 2});
  await t.feed.start();
  for (const id of ['run1', 'run2', 'run3']) { t.send('execution_success', {prompt_id: id}); await t.settle(); }
  assert.equal(t.ends.length, 1);
  assert.equal(t.ends[0].reason, 'done');
  assert.equal(t.ends[0].succeeded, 3);
  assert.equal(t.handlers.size, 0, 'listeners are removed');
  assert.equal(feedNote(t.ends[0]), null);
});

test('a failed run stops the feed and takes the posted runs out of the queue', async () => {
  const t = setup({total: 70, ahead: 3});
  await t.feed.start();
  t.send('execution_success', {prompt_id: 'run1'});
  await t.settle();
  t.send('execution_error', {prompt_id: 'run2', node_id: '9626', node_type: 'OrreryRefinementResult',
    exception_message: 'Unable to allocate 95.1 MiB\n'});
  await t.settle();
  assert.equal(t.ends.length, 1);
  const [end] = t.ends;
  assert.equal(end.reason, 'failed');
  assert.equal(end.type, 'OrreryRefinementResult');
  assert.equal(end.left, 69, 'the failed box still needs rendering');
  assert.deepEqual(t.cancelled.sort(), ['run3', 'run4']);
  assert.equal(t.posted.length, 4, 'nothing is posted after the failure');
  assert.match(feedNote(end), /failed run\. 69 runs left; press Render/);
});

test('Stop ends the feed without cancelling, since Stop clears the queue itself', async () => {
  const t = setup({total: 10, ahead: 3});
  await t.feed.start();
  await t.feed.stop();
  t.send('execution_success', {prompt_id: 'run1'});
  await t.settle();
  assert.equal(t.posted.length, 3);
  assert.deepEqual(t.cancelled, []);
  assert.equal(t.ends[0].reason, 'stopped');
  assert.equal(feedNote(t.ends[0]), null);
});

test('an interrupted run stops the feed', async () => {
  const t = setup({total: 6, ahead: 2});
  await t.feed.start();
  t.send('execution_interrupted', {prompt_id: 'run1'});
  await t.settle();
  assert.equal(t.ends[0].reason, 'interrupted');
  assert.deepEqual(t.cancelled, ['run2']);
});

test('a run that cannot be posted later ends the feed with the reason', async () => {
  const t = setup({total: 6, ahead: 2, postFails: 2});
  await t.feed.start();
  t.send('execution_success', {prompt_id: 'run1'});
  await t.settle();
  assert.equal(t.ends[0].reason, 'post');
  assert.match(feedNote(t.ends[0]), /could not queue the next run \(HTTP 500\)/);
});

test('a run that cannot be posted at the start is the caller’s error', async () => {
  const t = setup({total: 6, ahead: 2, postFails: 0});
  await assert.rejects(t.feed.start(), /HTTP 500/);
  assert.equal(t.handlers.size, 0);
});

test('reconcile finds runs whose events were missed, and a cleared queue', async () => {
  const states = {};
  const t = setup({total: 4, ahead: 2, states});
  await t.feed.start();
  states.run1 = 'success';
  await t.feed.reconcile();
  await t.settle();
  assert.deepEqual(t.posted, ['run1', 'run2', 'run3'], 'the missed success posts the next run');
  states.run2 = 'gone';
  states.run3 = 'gone';
  await t.feed.reconcile();
  await t.settle();
  assert.equal(t.ends[0].reason, 'cleared');
  assert.match(feedNote(t.ends[0]), /queue was cleared/);
});

test('an emptied queue is checked with ComfyUI before the feed gives up', async context => {
  context.mock.timers.enable({apis: ['setTimeout']});
  const states = {};
  const t = setup({total: 4, ahead: 2, states});
  await t.feed.start();
  states.run1 = 'success';
  states.run2 = 'queued';
  t.send('status', {exec_info: {queue_remaining: 0}});
  context.mock.timers.tick(1000);
  await t.settle();
  assert.deepEqual(t.posted, ['run1', 'run2', 'run3'], 'a success whose event was late still posts the next run');
  assert.equal(t.ends.length, 0);
  t.feed.close();
});

test('the progress text counts runs the feed has not queued', () => {
  let watch = watchEvent(idleWatch(), 'execution_start', {});
  watch = watchEvent(watch, 'status', {exec_info: {queue_remaining: 3}});
  assert.equal(progressText(watch, 4, () => '', {held: 60}), 'Rendering box 4 · 2 more queued · 60 more to queue');
  assert.equal(progressText(watch, 4), 'Rendering box 4 · 2 more queued');
  const idle = idleWatch();
  assert.equal(progressText(idle, null, () => '', {held: 0, note: 'Render stopped after a failed run.'}),
    'Render stopped after a failed run.');
  const failed = watchEvent(idle, 'execution_error', {node_id: '9', node_type: 'Refine', exception_message: 'No memory'});
  assert.equal(progressText(failed, null, () => '', {held: 0, note: '69 runs left.'}),
    'Render failed: Refine: No memory 69 runs left.');
});
