// Session-only edit snapshots. Files and running jobs are deliberately not part of an edit.
import {parseJSON, stringifyJSON} from './h3c_project.mjs?v=0882b8a6265a';
import {preparationOf} from './h3c_reference_preparation.mjs?v=d05409662438';

export function editingSnapshot(timeline) {
  return dropReceipts(structuredClone(timeline));
}

// editingSnapshot of a Timeline the caller owns, changed in place.
export function dropReceipts(value) {
  delete value.still_requests;
  const preparation = value.reference_preparation;
  if (preparation) {
    delete preparation.requests;
    if (!preparation.assets?.length && !Object.values(preparation.generate ?? {}).some(Boolean)
      && Object.keys(preparation).every(key => ['version', 'generate', 'assets'].includes(key))) delete value.reference_preparation;
  }
  return value;
}

export function withLiveReceipts(snapshot, current) {
  const value = structuredClone(snapshot);
  if (current.still_requests) value.still_requests = structuredClone(current.still_requests);
  if (value.reference_preparation || current.reference_preparation?.requests?.length) {
    value.reference_preparation ??= preparationOf(value);
    value.reference_preparation.requests = structuredClone(current.reference_preparation?.requests ?? []);
  }
  return value;
}

export class EditHistory {
  constructor(value) {
    this.limit = 100;
    this.reset(value);
  }

  reset(value) {
    this.entries = [{value: stringifyJSON(value), label: 'Initial state', time: Date.now()}];
    this.index = 0;
    this.endGroup();
  }

  get canUndo() { return this.index > 0; }
  get canRedo() { return this.index < this.entries.length - 1; }
  get value() { return parseJSON(this.entries[this.index].value); }

  record(value, label, group = null) {
    const text = stringifyJSON(value);
    if (text === this.entries[this.index].value) return false;
    if (typeof label === 'function') label = label();
    const merge = group != null && group === this.group && !this.canRedo && this.canUndo
      && label === this.entries[this.index].label;
    this.entries.splice(this.index + 1);
    const entry = {value: text, label, time: Date.now()};
    if (merge) this.entries[this.index] = entry;
    else {
      this.entries.push(entry);
      this.index++;
    }
    this.group = group;
    if (this.entries.length > this.limit + 1) {
      this.entries.shift();
      this.index--;
      this.entries[0].label = 'Earlier state';
    }
    return true;
  }

  endGroup() { this.group = null; }

  jump(index) {
    this.endGroup();
    if (!Number.isInteger(index) || index < 0 || index >= this.entries.length || index === this.index) return null;
    this.index = index;
    return this.value;
  }
}

// Connect snapshots to the editor's existing save/render paths without rebuilding the graph.
// `fresh`: read() returns a new value on every call, so the last recorded one can be kept.
export class TimelineHistory extends EditHistory {
  constructor({read, identity, apply, notify, group, flush, fresh = false}) {
    super(read());
    Object.assign(this, {read, identity, apply, notify, groupOf: group, flush, fresh});
    this.projectIdentity = identity();
  }

  capture(loaded = false) {
    if (this.restoring) return;
    const value = this.read(), identity = this.identity();
    if (identity !== this.projectIdentity || (loaded && this.entries.length === 1)) {
      this.projectIdentity = identity;
      this.reset(value);
    } else {
      // The step's value as last read, so naming the next step doesn't parse the whole Timeline again.
      const before = () => this.recorded?.text === this.entries[this.index].value ? this.recorded.value : this.value;
      if (this.record(value, () => editLabel(before(), value), this.groupOf()) && this.fresh) this.recorded = {text: this.entries[this.index].value, value};
    }
    this.notify();
  }

  restore(index) {
    this.flush();
    const previous = this.index, value = this.jump(index);
    if (!value) return;
    this.restoring = true;
    try { this.apply(value); }
    catch (error) { this.index = previous; throw error; }
    finally { this.restoring = false; this.notify(); }
  }

  undo() { this.flush(); this.restore(this.index - 1); }
  redo() { this.flush(); this.restore(this.index + 1); }
}

const same = (a, b) => a === b || stringifyJSON(a) === stringifyJSON(b);
const title = key => ({prompt: 'prompt', frames: 'length', previews: 'frame guides', bible: 'cast',
  refmods: 'RefMods', audio_clips: 'audio', timed_text: 'timed text', seed: 'seed',
  context_frames: 'context frames', carry_audio: 'carry audio'}[key] ?? key.replaceAll('_', ' '));

export function editLabel(before, after) {
  for (const key of Object.keys(after.settings ?? {})) {
    if (!same(before.settings?.[key], after.settings[key])) return `Change ${title(key)}`;
  }
  const left = before.timeline ?? {}, right = after.timeline ?? {};
  const a = left.boxes ?? [], b = right.boxes ?? [];
  if (b.length > a.length) return b.length - a.length === 1 ? 'Add clip' : 'Add clips';
  if (b.length < a.length) return a.length - b.length === 1 ? 'Delete clip' : 'Delete clips';
  if (!same(a.map(box => box.id), b.map(box => box.id))) return 'Reorder clips';
  for (let index = 0; index < b.length; index++) {
    const keys = new Set([...Object.keys(a[index]), ...Object.keys(b[index])]);
    const key = [...keys].find(key => !same(a[index][key], b[index][key]));
    if (key) return `Edit clip ${index + 1} ${title(key)}`;
  }
  const key = [...new Set([...Object.keys(left), ...Object.keys(right)])].find(key => !same(left[key], right[key]));
  return key === 'prompt' ? 'Edit shared prompt' : key ? `Edit ${title(key)}` : 'Edit Timeline';
}

// Keep native text undo in fields; project shortcuts act only outside them.
export function historyShortcut(event) {
  if (!(event.ctrlKey || event.metaKey) || event.altKey || event.repeat || event.isComposing
    || event.target.closest?.('input, textarea, select, [contenteditable]:not([contenteditable="false"])')) return null;
  const key = event.key.toLowerCase();
  return key === 'z' ? (event.shiftKey ? 'redo' : 'undo') : key === 'y' && !event.shiftKey ? 'redo' : null;
}
