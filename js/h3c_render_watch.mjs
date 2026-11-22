// Turn ComfyUI's websocket events into render progress and live-preview frames. No DOM, so Node can test it.
export const WATCH_EVENTS = [
  'execution_start', 'executing', 'progress', 'status', 'execution_success', 'execution_error',
  'execution_interrupted', 'kj_preview_override', 'b_preview',
];

const TURN = 'h3c_turn';
const KJ_TYPES = new Set(['image/webp', 'image/jpeg', 'video/mp4']);
const count = (value, fallback = 0) => (Number.isFinite(value) ? value : fallback);
const ended = (watch, change = {}) => ({ ...watch, running: false, turn: false, preview: null, ...change });

// remaining is ComfyUI's queue_remaining, which counts the running run. ComfyUI sends it before execution_start,
// so the running run is left out only when the text is made.
export function idleWatch() {
  return { running: false, turn: false, step: 0, total: 0, remaining: 0, failure: null, stopped: false, preview: null };
}

export function watchEvent(watch, type, detail) {
  switch (type) {
    case 'execution_start':
      return { ...watch, running: true, turn: false, step: 0, total: 0, failure: null, stopped: false, preview: null };
    case 'executing':
      if (detail == null) return ended(watch);
      if (detail === TURN) return { ...watch, running: true, turn: true, step: 0, total: 0 };
      return { ...watch, running: true, turn: false };
    case 'progress':
      return { ...watch, running: true, step: count(detail?.value), total: count(detail?.max) };
    case 'status': {
      const remaining = detail?.exec_info?.queue_remaining;
      return Number.isFinite(remaining) ? { ...watch, remaining: Math.max(0, remaining) } : watch;
    }
    case 'execution_success':
      return ended(watch);
    case 'execution_error':
      return ended(watch, {
        failure: { node: String(detail?.node_id ?? ''), type: detail?.node_type ?? '', message: detail?.exception_message ?? '' },
      });
    case 'execution_interrupted':
      return ended(watch, { stopped: true });
    case 'kj_preview_override': {
      if (typeof detail?.image !== 'string' || !detail.image || !KJ_TYPES.has(detail.mime)) return watch;
      const msPerStep = detail.avg_step_ms > 0 ? detail.avg_step_ms : null;
      return {
        ...watch,
        preview: {
          source: 'kj', mime: detail.mime, data: detail.image,
          step: count(detail.step, watch.step), total: count(detail.total, watch.total), msPerStep,
        },
      };
    }
    case 'b_preview':
      if (!(detail instanceof Blob) || watch.preview?.source === 'kj') return watch;
      return {
        ...watch,
        preview: {
          source: 'core', mime: detail.type || 'image/jpeg', blob: detail, step: watch.step, total: watch.total, msPerStep: null,
        },
      };
    default:
      return watch;
  }
}

const steps = (step, total) => (total > 0 ? ` · step ${step} of ${total}` : '');

// feed: the Render that is posting runs a few at a time, as {held, note}. held counts the runs not in ComfyUI's queue
// yet; note says why the last Render stopped early.
export function progressText(watch, box, titleOf = () => '', feed = null) {
  const held = feed?.held > 0 ? ` · ${feed.held} more to queue` : '';
  if (watch.turn) return 'ComfyUI’s queue is held while the Story writes';
  if (watch.running) {
    const waiting = Math.max(0, watch.remaining - 1);
    return `Rendering${box ? ` box ${box}` : ''}${steps(watch.step, watch.total)}${waiting ? ` · ${waiting} more queued` : ''}${held}`;
  }
  if (watch.failure) {
    const { node, type, message } = watch.failure;
    return ['Render failed', titleOf(node) || type, message].filter(Boolean).join(': ') + (feed?.note ? ` ${feed.note}` : '');
  }
  if (feed?.note) return feed.note;
  if (watch.stopped) return 'Render stopped.';
  return watch.remaining ? `${watch.remaining} queued${held}` : held.replace(/^ · /, '');
}

export function liveBadge(watch, box) {
  const preview = watch.preview;
  if (!preview) return '';
  const left = preview.total - preview.step;
  const time = preview.msPerStep && preview.total > 0 && left > 0
    ? ` · about ${Math.round((preview.msPerStep * left) / 1000)} s left` : '';
  return `Live${box ? ` · box ${box}` : ''}${steps(preview.step, preview.total)}${time}`;
}
