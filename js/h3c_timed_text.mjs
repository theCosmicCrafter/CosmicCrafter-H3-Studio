// Exact transcript import and source/movie clocks; mirrors h3_continuity/timed_text.py.
import { FPS, resolvedAudio } from './h3c_timeline_model.mjs?v=1dfc1612e462';
import {coalesceWindows} from './h3c_audio_windows.mjs?v=cdefbd77b246';

function error(field, message) {
  return new Error(`timed_text.${field} ${message}`);
}

function object(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function number(value, field, positive = false) {
  if (typeof value !== 'number' || !Number.isFinite(value)) throw error(field, 'must be a finite number');
  if (value < 0 || (positive && value === 0)) throw error(field, positive ? 'must be positive' : 'must be nonnegative');
  return value;
}

export function validateTimedText(value) {
  if (value == null) return null;
  if (!object(value)) throw error('attachment', 'must be an object');
  if (value.version !== 1) throw error('version', 'must be 1');
  for (const key of ['source_name', 'direction']) {
    if (typeof value[key] !== 'string') throw error(key, 'must be text');
  }
  for (const key of ['source_sha256', 'audio_sha256']) {
    if (key === 'audio_sha256' && !(key in value)) continue;
    if (typeof value[key] !== 'string' || !/^[0-9a-fA-F]{64}$/.test(value[key])) throw error(key, 'must be a SHA-256 hex digest');
  }
  for (const key of ['enabled', 'sync_audio']) {
    if (typeof value[key] !== 'boolean') throw error(key, 'must be a boolean');
  }
  if (!['audio1', 'audio2', 'audio3'].includes(value.audio_slot)) throw error('audio_slot', 'must be audio1, audio2 or audio3');
  for (const key of ['start', 'source_start', 'duration']) number(value[key], key, key === 'duration');
  for (const key of ['cues', 'words']) {
    if (key === 'words' && !(key in value)) continue;
    if (!Array.isArray(value[key])) throw error(key, 'must be a list');
    const ids = new Set();
    value[key].forEach((item, index) => {
      const field = `${key}[${index}]`;
      if (!object(item)) throw error(field, 'must be an object');
      if (typeof item.id !== 'string' || !item.id || ids.has(item.id)) throw error(`${field}.id`, 'must be unique nonempty text');
      ids.add(item.id);
      if (typeof item.text !== 'string') throw error(`${field}.text`, 'must be text');
      const token = /<\/?d>|<\|[^>]*\|>|<\/?(?:scenetrans|cutoff)>/.exec(item.text)?.[0];
      if (token) throw error(`${field}.text`, `contains unsupported H3 control token ${token}`);
      const start = number(item.start, `${field}.start`);
      const end = number(item.end, `${field}.end`);
      if (end <= start) throw error(`${field}.end`, 'must be after start');
    });
  }
  return structuredClone(value);
}

function items(raw, prefix) {
  if (!Array.isArray(raw)) throw error(prefix, 'must be a list');
  return raw.map((item, index) => {
    if (!object(item)) throw error(`${prefix}[${index}]`, 'must be an object');
    let { start, end } = item;
    if ('timestamp' in item) {
      if (!Array.isArray(item.timestamp) || item.timestamp.length !== 2) throw error(`${prefix}[${index}].timestamp`, 'must contain start and end');
      [start, end] = item.timestamp;
    }
    const text = 'word' in item ? item.word : 'text' in item ? item.text : item.value;
    return {id: `${prefix}${index + 1}`, start, end, text};
  });
}

export function importWhisper(data, sourceName, sourceSha256) {
  let cues, words = [];
  if (Array.isArray(data)) cues = items(data, 'cue');
  else if (object(data)) {
    if ('words' in data) words = items(data.words, 'word');
    if ('segments' in data) {
      cues = items(data.segments, 'cue');
      if (!('words' in data)) {
        const nested = [];
        for (const segment of data.segments) {
          if ('words' in segment) {
            if (!Array.isArray(segment.words)) throw error('words', 'must be a list');
            for (const word of segment.words) nested.push(word);
          }
        }
        words = items(nested, 'word');
      }
    } else if ('chunks' in data) cues = items(data.chunks, 'cue');
    else if ('words' in data) cues = items(data.words, 'cue');
    else throw error('import', 'needs segments, chunks, words or a timing array');
  } else throw error('import', 'must be an object or timing array');
  if (!cues.length && !words.length) throw error('import', 'contains no timed text');
  const value = validateTimedText({version:1, source_name:sourceName, source_sha256:sourceSha256,
    enabled:true, audio_slot:'audio1', sync_audio:false, start:0, source_start:0,
    duration:1, direction:'', cues, ...(words.length ? {words} : {})});
  value.duration = cues.concat(words).reduce((end, item) => Math.max(end, item.end), 0);
  return value;
}

export function textClock(value, audioClips, placements = null) {
  if (value == null) return {start:0, source_start:0, duration:0, resolved:false};
  const lane = value.sync_audio ? audioClips.find(clip => clip.slot === value.audio_slot) : value;
  const source = lane ?? value;
  return {start:source.start, source_start:source.source_start, duration:source.duration, resolved:!!lane,
    ...(value.sync_audio && source.box_windows ? {box_windows:structuredClone(source.box_windows),
      ...(placements ? {placements:placements.filter(w=>w.slot===value.audio_slot)} : {})} : {})};
}

function ranges(items, effective, sourceStart, sourceEnd) {
  const result = [];
  for (const item of items) {
    const start = Math.max(item.start, sourceStart), end = Math.min(item.end, sourceEnd);
    if (start < end) result.push({id:item.id, text:item.text, source_start:start, source_end:end,
      movie_start:effective.start + (start - effective.source_start), movie_end:effective.start + (end - effective.source_start)});
  }
  return result;
}

function milliseconds(seconds) { return Math.round(seconds * 1000); }

export function projectTimedText(value, audioClips, boxStart, frames, carried = 0, placements = null) {
  const effective = textClock(value, audioClips);
  const origin = boxStart - carried / FPS;
  const result = {direction:value?.direction ?? '', resolved:effective.resolved,
    source_start:null, source_end:null, generated_origin:origin, replay_end_ms:milliseconds(carried / FPS), cues:[], words:[]};
  if (!value?.enabled || !effective.resolved) return result;
  if (effective.box_windows) {
    if (!placements) throw Error('Bound timed text needs resolved audio windows.');
    result.source_windows = [];
    for (const window of coalesceWindows(placements.filter(w=>w.slot===value.audio_slot))) {
      const part = projectTimedText({...value,sync_audio:false,start:window.start,source_start:window.source_start,duration:window.duration},[],boxStart,frames,carried);
      if (part.source_start != null) {
        result.source_windows.push({source_start:part.source_start,source_end:part.source_end});
        for (const key of ['cues','words']) result[key].push(...part[key]);
      }
    }
    if (result.source_windows.length) {
      result.source_start=Math.min(...result.source_windows.map(w=>w.source_start));
      result.source_end=Math.max(...result.source_windows.map(w=>w.source_end));
    }
    for (const key of ['cues','words']) result[key].sort((a,b)=>a.start_ms-b.start_ms);
    return result;
  }
  const sourceStart = Math.max(effective.source_start, effective.source_start + (origin - effective.start));
  const sourceEnd = Math.min(effective.source_start + effective.duration, effective.source_start + (boxStart + frames / FPS - effective.start));
  if (sourceStart >= sourceEnd) return result;
  result.source_start = sourceStart; result.source_end = sourceEnd;
  for (const key of ['cues', 'words']) {
    const selected = ranges(value[key] ?? [], effective, effective.source_start, effective.source_start + effective.duration);
    for (const item of selected) {
      const continuing = item.movie_start < boxStart && boxStart < item.movie_end;
      const replayOnly = item.movie_end <= boxStart;
      const continuesAfter = item.source_end > sourceEnd;
      const [cue] = ranges([{id:item.id, text:item.text, start:item.source_start, end:item.source_end}], effective, sourceStart, sourceEnd);
      if (!cue) continue;
      result[key].push({...cue, start_ms:milliseconds(Math.max(0, cue.movie_start - origin)),
        end_ms:milliseconds(Math.max(0, cue.movie_end - origin)), continuing, replay_only:replayOnly, continues_after:continuesAfter});
    }
  }
  return result;
}

export function setTextSync(state, sync, audioSlot) {
  if (!state.timed_text) return;
  const value = state.timed_text;
  if (!sync && value.sync_audio) {
    let effective = textClock(value, state.audio_clips ?? []);
    if(effective.box_windows) {
      const windows=coalesceWindows(resolvedAudio(state).filter(w=>w.slot===value.audio_slot));
      if(windows.length!==1)throw Error('Unlock audio from boxes before detaching text: its ranges do not form one continuous clock.');
      effective={...windows[0],resolved:true};
    }
    if (effective.resolved) {
      value.start = effective.start; value.source_start = effective.source_start; value.duration = effective.duration;
    }
  }
  value.sync_audio = sync;
  if (audioSlot !== undefined) value.audio_slot = audioSlot;
}
