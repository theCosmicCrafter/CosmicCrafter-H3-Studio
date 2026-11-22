// H3 Story's saved state, applying a Write result to the Timeline, and Undo. Pure: no DOM and no ComfyUI.
import { FPS, normalize, totalFrames, resolvedAudio } from './h3c_timeline_model.mjs?v=1dfc1612e462';
import { validateTimedText, textClock } from './h3c_timed_text.mjs?v=21a5be84eb83';
import {pruneWindows} from './h3c_audio_windows.mjs?v=cdefbd77b246';

export const VERSION = 1;
export const DROPPED = 'The Timeline got boxes while Write worked, so the planned boxes were dropped.';
export const BIBLE_KEPT = 'The bible changed while Write worked, so yours was kept; boxes that name entities it lacks show as unlinked on the Cast page.';
const STALE_TEXT = 'Timed text or its audio clock changed while Write worked. Your edits and earlier applied work were kept; Write again for current text.';

const text = (value) => (typeof value === 'string' ? value : '');
const texts = (value) => (Array.isArray(value) ? value.filter((item) => typeof item === 'string') : []);
const objects = (value) => (Array.isArray(value) ? value.filter((item) => item && typeof item === 'object') : []);

function textMap(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  return Object.fromEntries(Object.entries(value).filter(([, item]) => typeof item === 'string'));
}

const filled = (value) => (value && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length > 0);
// The box fields a Write with the bible gives each box it writes.
const BOX_FIELDS = ['cast', 'source', 'schedule', 'join'];
const fieldsOf = (from, keys) => Object.fromEntries(keys.filter((key) => from && Object.hasOwn(from, key))
  .map((key) => [key, structuredClone(from[key])]));

function usesPicture(timeline, slot) {
  const mentioned = new RegExp(`@${slot}(?![0-9])`, 'i');
  return mentioned.test(timeline.prompt) || timeline.boxes.some(box =>
    mentioned.test(box.prompt) || box.first === slot || box.last === slot) ||
    (timeline.bible?.entities ?? []).some(entity => (entity.pictures ?? []).includes(slot) ||
      (entity.looks ?? []).some(look => (look.pictures ?? []).includes(slot)));
}

// The panel's line about the pictures: where they go.
export function targetText({ pictures, host }) {
  return pictures && host ? `Pictures go to ${host}.` : '';
}

export const UNKNOWN_HOST = 'base_url is linked; press Write once so the panel knows its host.';

// The base URL of the panel's host line and key box: the typed one or, while base_url is linked, the one the last
// Write in this page got; '' when there is none.
export function panelBaseUrl({ linked, typed, written }) {
  return String((linked ? written : typed) ?? '');
}

export function parseStoryState(raw) {
  let data;
  try {
    data = JSON.parse(raw || '{}');
  } catch {
    data = {};
  }
  if (!data || typeof data !== 'object' || Array.isArray(data)) data = {};
  return {
    version: VERSION,
    timeline: text(data.timeline),
    title: text(data.title),
    sheet: text(data.sheet),
    outline: objects(data.outline).map((item) => ({ box: text(item.box), beat: text(item.beat) })),
    suggestions: objects(data.suggestions).map((item) => ({
      what: text(item.what), why: text(item.why), description: text(item.description), boxes: texts(item.boxes),
    })),
    written: textMap(data.written),
    undo: textMap(data.undo),
    created: texts(data.created),
    failed: texts(data.failed),
    notes: texts(data.notes),
    job: text(data.job),
    received: texts(data.received),
    plan: data.plan && typeof data.plan === 'object' && !Array.isArray(data.plan) ? data.plan : null,
    ...(data.original_text ? {original_text: structuredClone(data.original_text)} : {}),
    ...(data.undo_metadata && typeof data.undo_metadata === 'object' && Object.keys(data.undo_metadata).length
      ? {undo_metadata: data.undo_metadata} : {}),
    ...(data.metadata_written && typeof data.metadata_written === 'object' && Object.keys(data.metadata_written).length
      ? {metadata_written: data.metadata_written} : {}),
    ...(filled(data.undo_boxes) ? {undo_boxes: data.undo_boxes} : {}),
    ...(filled(data.idea_descriptions) ? {idea_descriptions: structuredClone(data.idea_descriptions)} : {}),
    ...(filled(data.drafts) ? {drafts: Object.fromEntries(Object.entries(data.drafts).filter(([, value]) =>
      value && typeof value.reply === 'string' && typeof value.error === 'string'))} : {}),
  };
}

export function serializeStoryState(state) {
  const { timeline, title, sheet, outline, suggestions, written, undo, created, failed, notes, job, received, plan,
    undo_metadata, metadata_written, original_text, undo_boxes, idea_descriptions, drafts } = state;
  return JSON.stringify({ version: VERSION, timeline, title, sheet, outline, suggestions, written, undo, created,
    failed, notes, job, received, plan, undo_metadata, metadata_written, original_text,
    ...(filled(undo_boxes) ? {undo_boxes} : {}), ...(filled(idea_descriptions) ? {idea_descriptions} : {}),
    ...(filled(drafts) ? {drafts} : {}) });
}

function textSnapshot(timeline) {
  const value = validateTimedText(timeline.timed_text);
  const timed_text = value ? Object.fromEntries(['version','enabled','audio_slot','sync_audio','start','source_start','duration','direction']
    .map(key => [key, value[key]])) : null;
  if (value) for (const key of ['cues', 'words']) timed_text[key] = (value[key] ?? []).map(({id,start,end,text}) => ({id,start,end,text}));
  return {timed_text, clock:textClock(value, timeline.audio_clips ?? [], resolvedAudio(timeline))};
}

function sameData(a, b) {
  if (a === b) return true;
  if (!a || !b || typeof a !== 'object' || typeof b !== 'object' || Array.isArray(a) !== Array.isArray(b)) return false;
  const keys = Object.keys(a);
  return keys.length === Object.keys(b).length && keys.every(key => Object.hasOwn(b, key) && sameData(a[key], b[key]));
}

export function canUndo(state) {
  return Object.keys(state.undo).length > 0 || state.created.length > 0 || Object.keys(state.undo_metadata ?? {}).length > 0;
}

// Adds the boxes of a planned result to `timeline` while it is still empty, and snaps their lengths with `context`.
function applyPlan(timeline, state, result, timelineId, context) {
  if (timeline.boxes.length) return { applied: 0, planned: 0, dropped: true, state };
  const written = { ...state.written };
  const boxes = objects(result.boxes);
  let applied = 0;
  for (const box of boxes) {
    const id = String(box.id);
    const prompt = text(result.prompts?.[id]?.text);
    timeline.boxes.push({ id, frames: Number(box.frames), prompt, seed: box.seed, cut: !!box.cut, first: '', last: '',
      ...(box.cut && box.new_scene ? { new_scene: true } : {}), memory: box.schedule ? 'cast' : 'scene',
      ...fieldsOf(box, ['schedule', 'join']), ...fieldsOf(result.prompts?.[id], ['cast', 'source']) });
    written[id] = prompt;
    if (prompt) applied += 1;
  }
  normalize(timeline, context);
  const next = { ...result, timeline: String(timelineId ?? ''), written, undo: {},
    created: boxes.map((box) => String(box.id)),
    received: Object.keys(result.prompts ?? {}),
    failed: result.job ? texts(result.failed)
      : boxes.filter((box) => !text(result.prompts?.[String(box.id)]?.text)).map((box) => String(box.id)),
    notes: texts(result.notes) };
  return { applied, planned: boxes.length, failed: next.failed.length, dropped: false,
    state: parseStoryState(JSON.stringify(next)) };
}

// Writes the result's prompts into `timeline` (a parsed Timeline state, changed in place) where a box still holds
// the text Write started from, or adds the boxes of a planned result; `context` is the Timeline's context_frames.
// Returns the numbers written and planned, whether a plan was dropped, and the new story state.
export function applyResult(timeline, state, result, timelineId, context) {
  const original_text = result.original_text ?? (result.job === state.job ? state.original_text : null);
  if (original_text) {
    let matches = false;
    try { matches = sameData(original_text, textSnapshot(timeline)); } catch { /* Invalid live text is stale input too. */ }
    if (!matches) return {applied:0, planned:0, staleText:true, state:{...state, original_text:structuredClone(original_text),
      notes:[...new Set([...state.notes, STALE_TEXT])]}};
  }
  const continuing = !!result.job && result.job === state.job && String(timelineId) === state.timeline;
  for (const picture of objects(result.pictures)) {
    const current = (timeline.pictures ?? []).find(item => item.slot === picture.slot);
    const previous = continuing ? state.metadata_written?.pictures?.[picture.slot] : null;
    if (current && !sameData(current.file, picture.file) || !current && (previous || result.pictures_before?.[picture.slot]) ||
      (timeline.disabled_refs ?? []).includes(picture.slot)) {
      return {applied:0, planned:0, metadataChanged:false, state:{...state,
        notes:[...new Set([...state.notes, `The reference @${picture.slot} changed while Write worked; your pictures and prompts were kept.`])]}};
    }
  }
  if (objects(result.boxes).length && !continuing) {
    const planned = applyPlan(timeline, state, result, timelineId, context);
    if (planned.dropped) return planned;
    if (!result.reference_descriptions && !result.shared && !result.bible && !result.pictures) return planned;
    const job = result.job || 'planned-metadata';
    const metadata = applyResult(timeline, { ...planned.state, job },
      { ...result, boxes: [], prompts: {}, job }, timelineId, context);
    return { ...planned, state: { ...metadata.state, job: planned.state.job }, metadataChanged: metadata.metadataChanged };
  }
  const notes = texts(result.notes);
  const written = { ...state.written };
  const undo = continuing ? { ...state.undo } : {};
  const created = continuing ? [...state.created] : [];
  const received = new Set(continuing ? state.received : []);
  const undo_metadata = continuing ? { ...state.undo_metadata } : {};
  const metadata_written = continuing ? { ...state.metadata_written } : {};
  const undo_boxes = continuing ? { ...state.undo_boxes } : {};
  let metadataChanged = false;
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  if (result.revision && !undo_metadata.story) {
    undo_metadata.story = {};
    metadata_written.story = {};
    for (const key of ['title', 'sheet', 'outline', 'plan']) {
      undo_metadata.story[key] = structuredClone(state[key]);
      metadata_written.story[key] = result[key];
    }
  }
  if (result.shared && !received.has('shared')) {
    received.add('shared');
    if (timeline.prompt === result.shared.before) {
      undo_metadata.shared = timeline.prompt;
      metadata_written.shared = result.shared.text;
      timeline.prompt = result.shared.text;
      metadataChanged = true;
    } else notes.push('Shared direction changed during revision; your text was kept.');
  }
  const cache = result.reference_descriptions;
  if (cache?.value) {
    for (const ref of new Set([...Object.keys(cache.before ?? {}), ...Object.keys(cache.value)])) {
      const value = cache.value[ref];
      if (same(timeline.reference_descriptions?.[ref], value)) continue;
      if (!same(timeline.reference_descriptions?.[ref], cache.before?.[ref])) {
        notes.push(`The description for @${ref} changed during writing; yours was kept.`);
        continue;
      }
      undo_metadata.references ??= {};
      metadata_written.references ??= {};
      undo_metadata.references[ref] = timeline.reference_descriptions?.[ref] ?? null;
      metadata_written.references[ref] = value ?? null;
      timeline.reference_descriptions ??= {};
      if (value === undefined) delete timeline.reference_descriptions[ref];
      else timeline.reference_descriptions[ref] = structuredClone(value);
      metadataChanged = true;
    }
  }
  // The bible Write made replaces the Timeline's while it is the one this Write last applied, or started from.
  if (result.bible && typeof result.bible === 'object' && Object.hasOwn(result.bible, 'value')) {
    const current = timeline.bible ?? null, value = result.bible.value ?? null;
    const last = Object.hasOwn(metadata_written, 'bible') ? metadata_written.bible : result.bible.before ?? null;
    if (!sameData(current, value)) {
      if (sameData(current, last)) {
        if (!Object.hasOwn(undo_metadata, 'bible')) undo_metadata.bible = structuredClone(current);
        metadata_written.bible = structuredClone(value);
        if (value === null) delete timeline.bible;
        else timeline.bible = structuredClone(value);
        metadataChanged = true;
      } else notes.push(BIBLE_KEPT);
    }
  }
  let applied = 0;
  for (const [id, change] of Object.entries(result.prompts ?? {})) {
    if (received.has(id)) continue;
    received.add(id);
    const index = timeline.boxes.findIndex((box) => box.id === id);
    if (index < 0) {
      notes.push('A box was deleted while Write worked, so its new prompt was dropped.');
    } else if (timeline.boxes[index].prompt !== change.before) {
      notes.push(`Box ${index + 1} changed while Write worked, so it kept your text.`);
    } else {
      const box = timeline.boxes[index];
      if (!created.includes(id)) undo[id] = change.before;
      box.prompt = change.text;
      if (BOX_FIELDS.some((key) => Object.hasOwn(change, key))) {
        // Written with the bible: the box takes the entry's cast and source, and its schedule and join when it has them.
        const record = { before: {}, after: {} };
        for (const key of ['cast', 'source', ...['schedule', 'join'].filter((key) => Object.hasOwn(change, key))]) {
          record.before[key] = structuredClone(box[key] ?? null);
          if (Object.hasOwn(change, key)) box[key] = structuredClone(change[key]);
          else delete box[key];
          record.after[key] = structuredClone(box[key] ?? null);
        }
        if (box.memory === 'scene') [record.before.memory, box.memory, record.after.memory] = ['scene', 'cast', 'cast'];
        if (!created.includes(id)) undo_boxes[id] = record;
      } else delete box.cast;
      written[id] = change.text;
      applied += 1;
    }
  }
  for (const picture of objects(result.pictures)) {
    const current = (timeline.pictures ?? []).find(item => item.slot === picture.slot);
    if (current) {
      metadata_written.pictures ??= {};
      metadata_written.pictures[picture.slot] = structuredClone(current);
      continue;
    }
    if (!usesPicture(timeline, picture.slot)) continue;
    timeline.pictures ??= [];
    timeline.pictures.push(structuredClone(picture));
    undo_metadata.pictures ??= {};
    metadata_written.pictures ??= {};
    undo_metadata.pictures[picture.slot] = null;
    metadata_written.pictures[picture.slot] = structuredClone(picture);
    metadataChanged = true;
  }
  const drafts = {...(state.timeline === String(timelineId ?? '') ? state.drafts : {}), ...result.drafts};
  delete drafts.plan;
  delete drafts.revision;
  for (const [id, change] of Object.entries(result.prompts ?? {})) {
    if (timeline.boxes.some(box => box.id === id && box.prompt === change.text)) delete drafts[id];
  }
  const next = { ...result, drafts, timeline: String(timelineId ?? ''), written, undo, created, received: [...received],
    undo_metadata, metadata_written, undo_boxes,
    failed: [...new Set([...state.failed.filter((id) => !Object.hasOwn(result.prompts ?? {}, id)),
      ...texts(result.failed)])],
    notes: [...new Set([...notes, ...(continuing ? state.notes : [])])] };
  return { applied, planned: 0, failed: texts(result.failed).length, dropped: false, metadataChanged,
    state: parseStoryState(JSON.stringify(next)) };
}

export function resultMessage({ applied, planned, failed = 0, staleText }, timeline) {
  if (staleText) return STALE_TEXT;
  if (failed) return `Incomplete: wrote ${applied} of ${applied + failed} box prompts. ${failed} `
    + `${failed === 1 ? 'box needs' : 'boxes need'} another Write; see Notes for the reasons.`;
  if (!planned) return applied === 1 ? 'Wrote 1 box prompt.' : `Wrote ${applied} box prompts.`;
  const seconds = (totalFrames(timeline) / FPS).toFixed(1);
  const boxes = planned === 1 ? `Planned 1 box (${seconds} s)` : `Planned ${planned} boxes (${seconds} s)`;
  if (!applied) return `${boxes} without prompts.`;
  if (applied < planned) return `${boxes} and wrote ${applied} of their prompts.`;
  return planned === 1 ? `${boxes} and wrote its prompt.` : `${boxes} and wrote their prompts.`;
}

// Puts back the prompts the last Write replaced and removes the boxes it added, where `timeline` (changed in place)
// still holds Write's text, then snaps the lengths with `context` when boxes went. Returns the number restored or
// removed and the new story state.
export function undo(timeline, state, context) {
  const written = { ...state.written };
  const notes = [];
  const removed = new Set();
  let restored = 0;
  const before = state.undo_metadata ?? {}, after = state.metadata_written ?? {};
  const restoredStory = {};
  for (const [key, value] of Object.entries(before.story ?? {})) {
    if (JSON.stringify(state[key]) === JSON.stringify(after.story?.[key])) restoredStory[key] = value;
  }
  if (Object.hasOwn(before, 'shared') && timeline.prompt === after.shared) {
    timeline.prompt = before.shared;
    restored += 1;
  }
  for (const [ref, value] of Object.entries(before.references ?? {})) {
    if (JSON.stringify(timeline.reference_descriptions?.[ref] ?? null) !== JSON.stringify(after.references?.[ref])) continue;
    if (value === null) delete timeline.reference_descriptions[ref];
    else timeline.reference_descriptions[ref] = structuredClone(value);
    restored += 1;
  }
  if (Object.hasOwn(before, 'bible') && sameData(timeline.bible ?? null, after.bible ?? null)) {
    if (before.bible === null) delete timeline.bible;
    else timeline.bible = structuredClone(before.bible);
    restored += 1;
  }
  timeline.boxes.forEach((box, index) => {
    const created = state.created.includes(box.id);
    if (!created && !Object.hasOwn(state.undo, box.id)) return;
    if (box.prompt !== state.written[box.id]) {
      notes.push(`Box ${index + 1} was edited after Write, so Undo ${created ? 'kept it' : 'left it alone'}.`);
      return;
    }
    if (created) removed.add(box.id);
    else {
      box.prompt = state.undo[box.id];
      const record = state.undo_boxes?.[box.id];
      for (const [key, value] of Object.entries(record?.before ?? {})) {
        if (!sameData(box[key] ?? null, record.after?.[key] ?? null)) continue;
        if (value === null) delete box[key];
        else box[key] = structuredClone(value);
      }
    }
    delete written[box.id];
    restored += 1;
  });
  if (removed.size) {
    timeline.boxes = timeline.boxes.filter((box) => !removed.has(box.id));
    pruneWindows(timeline);
    normalize(timeline, context);
  }
  for (const [slot, picture] of Object.entries(after.pictures ?? {})) {
    if (before.pictures?.[slot] !== null) continue;
    const current = (timeline.pictures ?? []).find(item => item.slot === slot);
    if (sameData(current, picture) && !usesPicture(timeline, slot)) {
      timeline.pictures = timeline.pictures.filter(item => item.slot !== slot);
      restored += 1;
    }
  }
  return { restored, state: { ...state, ...restoredStory, written, undo: {}, created: [], failed: [], notes,
    undo_metadata: {}, metadata_written: {}, undo_boxes: {} } };
}
