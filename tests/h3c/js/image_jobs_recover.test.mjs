import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ImageJobClient} from '../../../js/h3c_image_jobs.mjs';

// A client over receipts kept in `store`, whose server answers come from `answer(receipt)`.
function client(store, answer) {
  const saves = [], asked = [];
  const jobs = new ImageJobClient({
    receipts: () => store, context: () => 'g1', identify: () => ({}), capture: async () => {},
    request: async (path, receipt) => { asked.push(receipt.prompt_id); return answer(receipt); },
    save: async (receipt, context, options) => {
      saves.push({receipt: structuredClone(receipt), options});
      const index = store.findIndex(item => item.prompt_id === receipt.prompt_id);
      store[index] = {...store[index], ...structuredClone(receipt)};
    },
  });
  return {jobs, saves, asked};
}
const receipt = (state, extra = {}) => ({request_id: 'r', prompt_id: 'p', state, provenance: {frame: 0}, ...extra});

test('a request the server has nothing new about is not saved again', async () => {
  const store = [receipt('queued')];
  const {jobs, saves, asked} = client(store, async () => ({ok: true, state: 'queued'}));
  assert.equal(await jobs.recover(), 0);
  assert.equal(await jobs.recover(), 0);
  assert.equal(asked.length, 2, 'the server is still asked');
  assert.deepEqual(saves, []);
});

test('an unreadable request is saved as unknown once, not after every check', async () => {
  const store = [receipt('queued')];
  const {jobs, saves} = client(store, async () => ({ok: false, error: 'offline'}));
  assert.equal(await jobs.recover(), 1);
  assert.equal(await jobs.recover(), 0);
  assert.equal(await jobs.recover(), 0);
  assert.equal(saves.length, 1);
  assert.equal(saves[0].receipt.state, 'unknown');
  assert.deepEqual(saves[0].options, {recovered: true});
});

test('a finished request is saved as read back, and finished ones are not asked about again', async () => {
  const store = [receipt('queued'), receipt('complete', {prompt_id: 'done'})];
  const {jobs, saves, asked} = client(store, async () => ({ok: true, state: 'complete',
    images: [{file: {filename: 'a.png'}, batch_index: 0}]}));
  assert.equal(await jobs.recover(), 1);
  assert.deepEqual(asked, ['p']);
  assert.equal(saves[0].receipt.state, 'complete');
  assert.equal(saves[0].receipt.images[0].file.filename, 'a.png');
  assert.equal(await jobs.recover(), 0);
});
