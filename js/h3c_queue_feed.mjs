// Keeps a long Render from sitting in ComfyUI's queue all at once. Render all used to post one run per box that
// isn't rendered yet. Every run renders "the next box that needs it" when it starts, so when one failed (a story of
// 70+ boxes ran the machine out of memory), each run behind it retried the same box and failed the same way.
// The feed posts a few runs ahead, tops the queue up as runs succeed, and stops at the first failure.
// No DOM and no ComfyUI imports, so Node can test it.

export const DEFAULT_AHEAD = 3;
// Checks the posted runs against ComfyUI's queue and history, in case an event was missed or the queue was cleared.
const WATCHDOG_MS = 20000;
const SETTLE_MS = 1000;

// The setting's value as a count of runs to keep queued: 0 queues everything at once, anything unusable falls back
// to the default.
export function queueAhead(value) {
  if (value == null || value === '') return DEFAULT_AHEAD;
  const count = Math.floor(Number(value));
  return Number.isFinite(count) && count >= 0 ? count : DEFAULT_AHEAD;
}

const clip = (text, length = 240) => {
  const line = String(text ?? '').replace(/\s+/g, ' ').trim();
  return line.length > length ? `${line.slice(0, length - 1)}…` : line;
};

export class QueueFeed {
  // total: runs to post. ahead: how many may wait in ComfyUI's queue, running one included.
  // post(): posts one run and returns its prompt id. cancel(ids): takes those runs out of ComfyUI's queue.
  // lookup(id): 'queued', 'success', 'error' or 'gone'. listen(type, handler): adds a ComfyUI event handler and
  // returns the function that removes it. onEnd(outcome) is called once; onChange() whenever the counts change.
  constructor({total, ahead = DEFAULT_AHEAD, post, cancel, lookup, listen, onEnd = () => {}, onChange = () => {}}) {
    this.total = total;
    this.ahead = Math.max(1, ahead);
    this.post = post;
    this.cancel = cancel;
    this.lookup = lookup;
    this.onEnd = onEnd;
    this.onChange = onChange;
    this.posted = 0;
    this.succeeded = 0;
    this.ids = new Set();
    this.ended = false;
    this.filling = null;
    this.settle = null;
    this.stops = ['execution_success', 'execution_error', 'execution_interrupted', 'status']
      .map(type => listen(type, event => this.event(type, event?.detail ?? event)));
    this.watchdog = setInterval(() => this.reconcile(), WATCHDOG_MS);
    this.watchdog.unref?.();
  }

  // Runs not posted yet.
  get held() { return Math.max(0, this.total - this.posted); }

  get active() { return !this.ended; }

  // Posts the first runs. A run that cannot be posted ends the feed and the error goes to the caller, as it did
  // when every run was posted at once.
  async start() {
    try { await this.fill(); }
    catch (error) { this.close(); throw error; }
  }

  // Posts until the queue holds `ahead` runs. A call that arrives while posting makes the loop look again.
  fill() {
    if (this.filling) { this.again = true; return this.filling; }
    const run = this.top();
    this.filling = run;
    run.then(() => {}, () => {}).then(() => { if (this.filling === run) this.filling = null; });
    return run;
  }

  async top() {
    do {
      this.again = false;
      while (!this.ended && this.ids.size < this.ahead && this.posted < this.total) {
        const id = await this.post();
        if (this.ended) { await this.cancel([id]).catch(() => {}); break; }
        this.ids.add(id);
        this.posted += 1;
        this.onChange();
      }
    } while (this.again && !this.ended);
    this.settled();
  }

  settled() {
    if (!this.ended && this.posted >= this.total && !this.ids.size) this.finish({reason: 'done'});
  }

  event(type, detail) {
    if (this.ended) return;
    if (type === 'status') {
      // The queue emptied with runs of ours unaccounted for; give a late event a moment, then ask ComfyUI.
      if (detail?.exec_info?.queue_remaining === 0 && this.ids.size && !this.settle)
        this.settle = setTimeout(() => { this.settle = null; this.reconcile(); }, SETTLE_MS);
      return;
    }
    const id = detail?.prompt_id;
    if (!this.ids.has(id)) return;
    this.ids.delete(id);
    if (type === 'execution_success') { this.succeeded += 1; this.advance(); }
    else this.stop(type === 'execution_error'
      ? {reason: 'failed', node: String(detail?.node_id ?? ''), type: detail?.node_type ?? '', message: clip(detail?.exception_message)}
      : {reason: 'interrupted'});
  }

  advance() {
    this.onChange();
    this.fill().catch(error => this.stop({reason: 'post', message: clip(error?.message ?? error)}));
  }

  // Asks ComfyUI what became of every run that was posted and has not reported.
  async reconcile() {
    if (this.ended) return;
    for (const id of [...this.ids]) {
      let state;
      try { state = await this.lookup(id); } catch { return; }
      if (this.ended || !this.ids.has(id) || state === 'queued') continue;
      if (state === 'success') this.event('execution_success', {prompt_id: id});
      else if (state === 'error') this.event('execution_error', {prompt_id: id, exception_message: 'The run failed.'});
      else { this.ids.delete(id); this.stop({reason: 'cleared'}); }
    }
  }

  // Ends the feed and takes the runs it already posted but ComfyUI has not started out of the queue.
  async stop(outcome = {reason: 'stopped'}) {
    if (this.ended) return;
    const waiting = [...this.ids];
    this.close();
    if (waiting.length && outcome.reason !== 'stopped') await this.cancel(waiting).catch(() => {});
    this.onEnd({...outcome, posted: this.posted, succeeded: this.succeeded, left: this.total - this.succeeded,
      notQueued: this.total - this.posted});
  }

  finish(outcome) {
    this.close();
    this.onEnd({...outcome, posted: this.posted, succeeded: this.succeeded, left: 0, notQueued: 0});
  }

  close() {
    this.ended = true;
    clearInterval(this.watchdog);
    clearTimeout(this.settle);
    for (const stop of this.stops) stop();
    this.stops = [];
  }
}

// The line beside Render once a feed has ended without finishing, or null when it finished or the user stopped it.
// The failed run's own node and message come from the render watch, so this says only what is left.
export function feedNote(outcome) {
  if (!outcome || outcome.reason === 'done' || outcome.reason === 'stopped') return null;
  const left = outcome.left > 0 ? ` ${outcome.left} run${outcome.left === 1 ? '' : 's'} left; press Render to carry on.` : '';
  switch (outcome.reason) {
    case 'failed': return `Render stopped after a failed run.${left}`;
    case 'interrupted': return `Render interrupted.${left}`;
    case 'cleared': return `Render stopped: ComfyUI's queue was cleared.${left}`;
    case 'post': return `Render stopped: could not queue the next run${outcome.message ? ` (${outcome.message})` : ''}.${left}`;
    default: return null;
  }
}
