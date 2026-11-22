import * as tracks from './h3c_tracks.mjs';
import {reconcileSceneAnchors} from './h3c_still_scene.mjs?v=0906bb5de9d7';
// H3 Timeline editor model: the timeline JSON, lengths on the H3 frame grid, edits, and the rules that
// decide how a box runs. Mirrors h3_continuity/timeline.py.
import {parseJSON, stringifyJSON, seedValue} from './h3c_project.mjs?v=0882b8a6265a';
import {imageDescriptionPrompt, imageDescriptionSource} from './h3c_image_descriptions.mjs?v=5f858b2b6a5a';
import {acceptedGuideFrames} from './h3c_shot_preview.mjs?v=1dfc1612e462';
import {AUDIO_WINDOWS_FEATURE, pruneWindows, resolveWindows, audioSourceLocked} from './h3c_audio_windows.mjs?v=cdefbd77b246';
import {LAYER_FIELDS, SWAPS_DONT_FIT, clampSwitch, hasLayers, layerIds, switchFits} from './h3c_layers.mjs?v=1dfc1612e462';
export const FPS = 24;
export const MAX_FRAMES = 362;
export const GRID = 17;
export const DEFAULT_GENERATED = 192;
export const MAX_REF_IMAGES = 9;
export const MAX_REF_AUDIOS = 3;
export const BRIDGE_FRAMES = [12, 29, 46];
const MENTION = /(?<![\w@])@(image|audio|video_audio|video)(\d+)(?!\w)/gi;
const IMAGE_SLOT = /^@?image(\d+)$/i;
const FILE_WIDGETS = { LoadImage: 'image', LoadImageOutput: 'image', LoadAudio: 'audio' };
const FILE_ANNOTATION = /(?:^|\s)\[(input|output|temp)\]$/;

export function isFresh(state, index) {
  return !!state.boxes[index]?.cut || (tracks.enabled(state) ? tracks.previousIndex(state,index,false)===null : index===0);
}

// The Timeline's most generated frames: its own max_frames (a long Timeline), else the default 362.
export function maxFrames(state) {
  return Number.isInteger(state?.max_frames) ? state.max_frames : MAX_FRAMES;
}

export function limits(fresh, context, most = MAX_FRAMES) {
  return fresh ? { min: 22, max: most } : { min: GRID, max: most - context };
}

// For a length the user is choosing: the nearest grid length, within the limits.
export function snapFrames(frames, fresh, context, limit = MAX_FRAMES) {
  const offset = fresh ? 5 : 0;
  const value = Number.isFinite(Number(frames)) && frames !== null ? Number(frames) : DEFAULT_GENERATED;
  const steps = Math.max(1, Math.round((value - offset) / GRID));
  const most = Math.floor((limits(fresh, context, limit).max - offset) / GRID);
  return GRID * Math.min(steps, most) + offset;
}

// The frames a box plays, as timeline.played_frames: an exact box its own, else the nearest grid length. Never clamped:
// a saved length is the author's, so a box over the limit stays as it is and its problem says so.
export function playedFrames(frames, exact, fresh) {
  if (exact) return Math.max(1, Math.round(Number(frames) || 0));
  const offset = fresh ? 5 : 0;
  return GRID * Math.max(1, Math.round((Number(frames) - offset) / GRID)) + offset;
}

export function defaultFrames(fresh, context) {
  return snapFrames(fresh ? DEFAULT_GENERATED : DEFAULT_GENERATED - context, fresh, context);
}

// An exact box plays exactly its frames; H3 generates the smallest grid length that holds them, as in timeline.py.
export function generatedFrames(frames, fresh) {
  const offset = fresh ? 5 : 0;
  return GRID * Math.max(1, Math.ceil((frames - offset) / GRID)) + offset;
}

export function fitExact(frames, fresh, context, limit = MAX_FRAMES) {
  return Math.min(Math.max(1, Math.round(Number(frames) || 0)), limits(fresh, context, limit).max);
}

export function droppedFrames(state, index) {
  const box = state.boxes[index];
  return box.exact ? generatedFrames(box.frames, isFresh(state, index)) - box.frames : 0;
}

export function setExact(state, index, exact, context) {
  if (exact) state.boxes[index].exact = true;
  else delete state.boxes[index].exact;
  normalize(state, context);
}

export function setFrames(state, index, frames, context) {
  const box = state.boxes[index], fresh = isFresh(state, index);
  const most = maxFrames(state);
  box.frames = box.exact ? fitExact(frames, fresh, context, most) : snapFrames(frames, fresh, context, most);
}

// The problem when box `index` drops generated frames and the next box continues it, or box `index` continues
// a box that does; the same sentence on both boxes, as timeline.box_length raises it.
export function dropConflict(state, index, context) {
  for (const source of [tracks.previousIndex(state,index),index]) {
    const after=source===null?null:tracks.followingIndex(state,source);
    if (source===null || after===null || isFresh(state,after)) continue;
    const dropped = droppedFrames(state, source);
    if (!dropped) continue;
    const fresh = isFresh(state, source);
    const { min, max } = limits(fresh, context, maxFrames(state));
    const above = generatedFrames(state.boxes[source].frames, fresh);
    const lengths = [above - GRID, above].filter((length) => min <= length && length <= max).join(' or ');
    return `Box ${source + 1} drops ${dropped} generated frames, so box ${source + 2} can't continue it: `
      + `make box ${source + 2} a cut, or give box ${source + 1} a length on the grid (${lengths} frames), `
      + 'which moves every later box.';
  }
  return '';
}

// The problem when box `index` continues a box that plays fewer frames than it carries, as timeline.carry_conflict words it.
export function carryConflict(state, index, context) {
  const previous=tracks.previousIndex(state,index);
  if (tracks.enabled(state) && !state.boxes[index].cut && previous===null) return 'Continue requires an adjacent preceding clip on this track; choose Cut or New scene.';
  if (isFresh(state,index) || previous===null || !isFresh(state,previous)) return '';
  const box=state.boxes[previous];
  const played = box.exact ? box.frames : snapFrames(box.frames, true, context);
  if (!(played < context)) return '';
  return `Box ${index + 1} continues box ${index}, which plays ${played} frames, fewer than the ${context} it carries: `
    + `make box ${index + 1} a cut, or give box ${index} at least ${context} frames, which moves every later box.`;
}

export function newSeed() {
  return Math.floor(Math.random() * 2 ** 32);
}

export function newId(state) {
  const used = new Set([...state.boxes.map((box) => box.id), ...layerIds(state),...(state.tracks??[]).map(t=>t.id),...(state.overlap_switches??[]).map(s=>s.id)]);
  let id = '';
  while (!id || used.has(id)) id = Math.random().toString(36).slice(2, 8);
  return id;
}

function slotName(value) {
  const text = String(value ?? '').trim();
  const match = IMAGE_SLOT.exec(text);
  return match ? `image${Number(match[1])}` : text;
}

const record = (value) => !!value && typeof value === 'object' && !Array.isArray(value);

// A clip's other videos with only the fields a video has, and its switch plan; {} for a clip with one video.
function parseLayers(box) {
  const items = Array.isArray(box.layers) ? box.layers.filter(record) : [];
  if (!items.length) return {};
  const sw = record(box.switch) ? box.switch : {};
  return {
    layers: items.map((item) => Object.fromEntries(LAYER_FIELDS.filter((key) => Object.hasOwn(item, key)).map((key) => [
      key, key === 'first' || key === 'last' ? slotName(item[key]) : key === 'id' ? String(item.id)
        : key === 'previews' && Array.isArray(item.previews)
          ? structuredClone(item.previews).filter(record).map(({pending, job, ...p}) => p)
          : structuredClone(item[key])]))),
    switch: {
      cuts: Array.isArray(sw.cuts) ? structuredClone(sw.cuts).filter(record) : [],
      fade: Number.isInteger(sw.fade) ? sw.fade : 6,
      sound: typeof sw.sound === 'string' ? sw.sound : 'screen',
      ...(record(sw.align) ? {align: structuredClone(sw.align)} : {}),
    },
  };
}

export function parseState(text) {
  let data;
  try {
    data = parseJSON(text || '{}');
  } catch {
    data = {};
  }
  if (!data || typeof data !== 'object' || Array.isArray(data)) data = {};
  const boxes = Array.isArray(data.boxes) ? data.boxes.filter((box) => box && typeof box === 'object') : [];
  return {
    ...(Object.hasOwn(data,'tracks') ? {tracks:structuredClone(data.tracks)} : {}),
    ...(Object.hasOwn(data,'text_lanes') ? {text_lanes:structuredClone(data.text_lanes)} : {}),
    ...(Object.hasOwn(data,'overlap_switches') ? {overlap_switches:structuredClone(data.overlap_switches)} : {}),
    prompt: typeof data.prompt === 'string' ? data.prompt : '',
    ...(record(data.reference_preparation) ? {reference_preparation:structuredClone(data.reference_preparation)} : {}),
    ...(record(data.still_prompt_preparation) ? {still_prompt_preparation:structuredClone(data.still_prompt_preparation)} : {}),
    ...(record(data.continuity)?{continuity:structuredClone(data.continuity)}:{}),
    ...(Array.isArray(data.still_requests) ? {still_requests:structuredClone(data.still_requests)} : {}),
    ...(data.timed_text && typeof data.timed_text === 'object'
      ? { timed_text: structuredClone(data.timed_text) } : {}),
    ...(data.reference_descriptions && typeof data.reference_descriptions === 'object'
      ? { reference_descriptions: structuredClone(data.reference_descriptions) } : {}),
    ...(record(data.reference_replacements) ? {reference_replacements:structuredClone(data.reference_replacements)} : {}),
    ...(data.context_noise === true ? {context_noise: true} : {}),
    ...(data.continuation_guide === false ? {continuation_guide: false} : {}),
    ...(Number.isInteger(data.audio_feather) && data.audio_feather > 0 ? {audio_feather: data.audio_feather} : {}),
    ...(Array.isArray(data.video_slices) && data.video_slices.length ? {video_slices: [...data.video_slices]} : {}),
    ...(Array.isArray(data.disabled_refs) ? { disabled_refs: [...data.disabled_refs] } : {}),
    ...(Array.isArray(data.refmods) ? { refmods: structuredClone(data.refmods) } : {}),
    ...(Array.isArray(data.audio_clips) ? { audio_clips: structuredClone(data.audio_clips) } : {}),
    ...(Array.isArray(data.pictures) && data.pictures.length ? { pictures: structuredClone(data.pictures) } : {}),
    ...(Array.isArray(data.voice_clips) && data.voice_clips.length
      ? { voice_clips: structuredClone(data.voice_clips) } : {}),
    ...(data.qwen && typeof data.qwen === 'object' ? { qwen: structuredClone(data.qwen) } : {}),
    ...(Array.isArray(data.plates) ? { plates: structuredClone(data.plates).map(({pending, job, ...p}) => p) } : {}),
    ...(record(data.bible) ? { bible: structuredClone(data.bible) } : {}),
    ...(Array.isArray(data.bridges) ? { bridges: structuredClone(data.bridges).filter(record) } : {}),
    ...(record(data.dialogue) ? { dialogue: structuredClone(data.dialogue) } : {}),
    ...(Array.isArray(data.requires) ? { requires: data.requires.filter((item) => typeof item === 'string') } : {}),
    ...(Number.isInteger(data.max_frames) ? { max_frames: data.max_frames } : {}),
    boxes: boxes.map((box, index) => ({
      ...(Object.hasOwn(box,'track') ? {track:box.track,start:box.start} : {}),
      id: String(box.id || `box${index + 1}`),
      frames: Number.isFinite(box.frames) ? Math.round(box.frames)
        : Number.isFinite(box.seconds) ? Math.round(box.seconds * FPS) : null,
      prompt: typeof box.prompt === 'string' ? box.prompt : '',
      seed: seedValue(box.seed),
      ...(box.seed_mode === 'randomize' ? {seed_mode:'randomize'} : {}),
      cut: !!box.cut,
      first: slotName(box.first),
      last: slotName(box.last),
      ...(box.exact === true ? { exact: true } : {}),
      ...(box.flf_refmods === true ? { flf_refmods: true } : {}),
      ...(box.cut && box.new_scene ? { new_scene: true } : {}),
      ...(box.memory ? { memory: box.memory } : {}),
      ...(Array.isArray(box.memories) ? { memories: structuredClone(box.memories) } : {}),
      ...(Array.isArray(box.plate_changes) ? { plate_changes: structuredClone(box.plate_changes) } : {}),
      ...(Array.isArray(box.plate_edits) ? { plate_edits: structuredClone(box.plate_edits).map(({pending, job, ...p}) => p) } : {}),
      ...(Array.isArray(box.previews) && box.previews.length
        ? { previews: structuredClone(box.previews).filter((p) => p && typeof p === 'object')
          .map(({ pending, job, ...p }) => p) } : {}),
      ...(record(box.cast) ? { cast: structuredClone(box.cast) } : {}),
      ...(record(box.schedule) ? { schedule: structuredClone(box.schedule) } : {}),
      ...(record(box.join) ? { join: structuredClone(box.join) } : {}),
      ...(record(box.source) ? { source: structuredClone(box.source) } : {}),
      ...(box.dialogue === 'manual' ? { dialogue: 'manual' } : {}),
      ...parseLayers(box),
    })),
  };
}

export function serialize(state) {
  const requires = requiredFeatures(state);
  return stringifyJSON({
    version: 1,
    ...(requires.length ? { requires } : {}),
    ...(tracks.enabled(state) ? {tracks:state.tracks} : {}),
    ...(state.text_lanes ? {text_lanes:state.text_lanes} : {}),
    ...(state.overlap_switches ? {overlap_switches:state.overlap_switches} : {}),
    prompt: state.prompt,
    ...(state.reference_preparation ? {reference_preparation:state.reference_preparation} : {}),
    ...(state.still_prompt_preparation ? {still_prompt_preparation:state.still_prompt_preparation} : {}),
    ...(state.continuity?{continuity:state.continuity}:{}),
    ...(state.still_requests ? {still_requests:state.still_requests} : {}),
    ...(state.timed_text ? { timed_text: state.timed_text } : {}),
    ...(state.reference_descriptions ? { reference_descriptions: state.reference_descriptions } : {}),
    ...(Object.keys(state.reference_replacements ?? {}).length ? {reference_replacements:state.reference_replacements} : {}),
    ...(state.context_noise === true ? {context_noise: true} : {}),
    ...(state.continuation_guide === false ? {continuation_guide: false} : {}),
    ...(state.audio_feather > 0 ? {audio_feather: state.audio_feather} : {}),
    ...(state.video_slices?.length ? {video_slices: state.video_slices} : {}),
    ...(state.disabled_refs ? { disabled_refs: state.disabled_refs } : {}),
    ...(state.refmods ? { refmods: state.refmods } : {}),
    ...(state.audio_clips ? { audio_clips: state.audio_clips } : {}),
    ...(state.pictures?.length ? { pictures: state.pictures } : {}),
    ...(state.voice_clips?.length ? { voice_clips: state.voice_clips } : {}),
    ...(state.qwen ? { qwen: state.qwen } : {}),
    ...(state.plates ? { plates: state.plates } : {}),
    ...(state.bible ? { bible: state.bible } : {}),
    ...(keptBridges(state).length ? { bridges: keptBridges(state) } : {}),
    ...(state.dialogue ? { dialogue: state.dialogue } : {}),
    ...(Number.isInteger(state.max_frames) ? { max_frames: state.max_frames } : {}),
    boxes: state.boxes.map((box) => ({
      ...(tracks.enabled(state) ? {track:box.track,start:box.start} : {}),
      id: box.id, frames: box.frames, prompt: box.prompt, seed: box.seed, cut: !!box.cut,
      ...(box.seed_mode === 'randomize' ? {seed_mode:'randomize'} : {}),
      first: box.first || '', last: box.last || '',
      ...(box.exact ? { exact: true } : {}),
      ...(box.flf_refmods ? { flf_refmods: true } : {}),
      ...(box.new_scene ? { new_scene: true } : {}),
      ...(box.memory ? { memory: box.memory } : {}),
      ...(box.memories ? { memories: box.memories } : {}),
      ...(box.plate_changes ? { plate_changes: box.plate_changes } : {}),
      ...(box.plate_edits ? { plate_edits: box.plate_edits } : {}),
      ...(box.previews?.length ? { previews: box.previews } : {}),
      ...(box.cast ? { cast: box.cast } : {}),
      ...(box.schedule ? { schedule: box.schedule } : {}),
      ...(box.join ? { join: box.join } : {}),
      ...(box.source ? { source: box.source } : {}),
      ...(box.dialogue === 'manual' ? { dialogue: 'manual' } : {}),
      ...(box.layers?.length ? { layers: box.layers, switch: box.switch } : {}),
    })),
  });
}

export const LAYERS_FEATURE = 'video-layers-1';
// Reader features this editor writes into "requires" when the file depends on them, as timeline.REQUIRES lists them.
export const OWN_FEATURES = ['dialogue-cues-1', 'replacement-bridges-1', AUDIO_WINDOWS_FEATURE, LAYERS_FEATURE, tracks.FEATURE];

// What the Timeline needs a reader to understand: this editor's features in use, and any newer one it was given.
export function requiredFeatures(state) {
  const own = [];
  if (tracks.enabled(state)) own.push(tracks.FEATURE);
  if ((state.audio_clips ?? []).some(clip => Object.hasOwn(clip, 'box_windows'))) own.push(AUDIO_WINDOWS_FEATURE);
  if (state.dialogue?.cues?.length || state.dialogue?.observed?.length
    || (state.audio_clips ?? []).some((clip) => clip.locked === true)) own.push('dialogue-cues-1');
  if (keptBridges(state).some(isReplacement)) own.push('replacement-bridges-1');
  if (hasLayers(state)) own.push(LAYERS_FEATURE);
  return [...new Set([...(state.requires ?? []).filter((item) => !OWN_FEATURES.includes(item)), ...own])].sort();
}

// The features a newer Studio wrote that this one can't read: such a Timeline opens read-only, because saving it
// would drop every field this editor doesn't copy.
export function unknownFeatures(state) {
  return [...new Set((state.requires ?? []).filter((item) => !OWN_FEATURES.includes(item)))];
}

export function readOnlyNote(features) {
  return `This Timeline needs a newer H3 Continuity (${features.join(', ')}). `
    + 'It is open read-only so nothing in it is lost; update the node pack to edit or render it.';
}

export function normalize(state, context) {
  reconcileSceneAnchors(state);
  state.boxes.forEach((box, index) => {
    const fresh = isFresh(state, index);
    // Only what the box already plays: normalizing never shortens or lengthens a box (lip sync and beat cuts depend
    // on its length). A box past the limit keeps its length and reports the problem.
    box.frames = box.frames == null ? defaultFrames(fresh, context) : playedFrames(box.frames, box.exact, fresh);
    clampSwitch(state, index);
  });
  if (state.bridges) state.bridges = keptBridges(state);
  return state;
}

// The bridges timeline.py accepts: the first one into each box after box 1 that starts with Cut or New scene, where
// neither box beside it holds several videos.
export function keptBridges(state) {
  const seen = new Set();
  return (state.bridges ?? []).filter((bridge) => {
    const index = state.boxes.findIndex((box) => box.id === bridge.before);
    // On tracks a bridge leads out of the clip right before this one on its own track, not the previous catalog entry.
    const before = index < 0 ? null : tracks.enabled(state) ? tracks.previousIndex(state, index) : index > 0 ? index - 1 : null;
    if (before === null || !state.boxes[index].cut || seen.has(bridge.before)) return false;
    if (state.boxes[index].layers?.length || state.boxes[before].layers?.length) return false;
    seen.add(bridge.before);
    return true;
  });
}

export function bridgeOf(state, index) {
  return keptBridges(state).find((bridge) => bridge.before === state.boxes[index]?.id);
}

export function isReplacement(bridge) {
  return bridge?.mode === 'replace';
}

// The uploaded, enabled clips locked to the sequence clock, as dialogue.locked_clips reads them.
export function lockedClips(state) {
  return (state.audio_clips ?? []).filter((clip) => clip.locked === true && clip.file && referenceEnabled(state, clip.slot));
}

// A new bridge into box `index` lasts 29 frames from the box's prompt, kept in the order of the boxes. It inserts
// time, or with a locked recording replaces 14 frames before the cut and 15 after.
export function insertBridge(state, index, mode = lockedClips(state).length ? 'replace' : 'insert') {
  const before = state.boxes[index].id, seed = newSeed(), prompt = state.boxes[index].prompt;
  const bridge = mode === 'replace' ? { before, mode: 'replace', left: 14, right: 15, seed, prompt }
    : { before, frames: 29, seed, prompt };
  const position = (item) => state.boxes.findIndex((box) => box.id === item.before);
  state.bridges = [...keptBridges(state).filter((item) => item.before !== bridge.before), bridge]
    .sort((one, other) => position(one) - position(other));
  return bridge;
}

export function removeBridge(state, index) {
  state.bridges = keptBridges(state).filter((bridge) => bridge.before !== state.boxes[index].id);
}

// The bridge into box `index` in `mode`, keeping its length; an insertion has no region to review or select.
export function setBridgeMode(state, index, mode) {
  const bridge = bridgeOf(state, index);
  if (!bridge) return undefined;
  if (mode === 'replace' && !isReplacement(bridge)) {
    const frames = bridge.frames;
    delete bridge.frames;
    Object.assign(bridge, { mode: 'replace', left: Math.floor(frames / 2), right: frames - Math.floor(frames / 2) });
  } else if (mode === 'insert' && isReplacement(bridge)) {
    bridge.frames = bridge.left + bridge.right;
    for (const key of ['mode', 'left', 'right', 'review', 'selected']) delete bridge[key];
  }
  return bridge;
}

// `frames` (snapped to a bridge length) replaced, `left` of them before the cut. A confirmed region stays named in
// `review`; the server compares it with the new region.
export function setCoverage(bridge, frames, left) {
  const length = BRIDGE_FRAMES.reduce((best, item) => Math.abs(item - frames) < Math.abs(best - frames) ? item : best);
  bridge.left = Math.min(length, Math.max(0, Math.round(Number(left) || 0)));
  bridge.right = length - bridge.left;
}

export function confirmRegion(bridge, regionKey) {
  bridge.review = regionKey;
}

export function selectCandidate(bridge, candidate) {
  bridge.selected = candidate;
}

export function useOriginalCut(bridge) {
  delete bridge.selected;
}

// The frames bridges add to the full video: replacements add none.
export function insertedFrames(state) {
  return keptBridges(state).filter((bridge) => !isReplacement(bridge)).reduce((sum, bridge) => sum + bridge.frames, 0);
}

export function setBoxDialogue(state, index, mode) {
  if (mode === 'manual') state.boxes[index].dialogue = 'manual';
  else delete state.boxes[index].dialogue;
}

// Why the bridge into box `index` can't render, as bridges.problem words it: mentions read as words, so its prompt is
// empty only when the shared prompt and its own are. A replacement reads saved footage, so dropped frames don't matter.
export function bridgeProblem(state, index) {
  const existing = bridgeOf(state, index);
  const replacing = existing ? isReplacement(existing) : lockedClips(state).length > 0;
  const dropped = index > 0 && !replacing ? droppedFrames(state, index - 1) : 0;
  if (dropped) {
    return `Box ${index} drops ${dropped} frames, so the bridge before box ${index + 1} can't start from its last frame: `
      + `use a replacement bridge, or give box ${index} a length on the grid, which moves every later box.`;
  }
  const bridge = bridgeOf(state, index);
  if (bridge && !state.prompt.trim() && !String(bridge.prompt ?? '').trim()) {
    return `The bridge before box ${index + 1} has no prompt.`;
  }
  return '';
}

export function totalFrames(state) {
  return tracks.durationFrames(state);
}

export function resolvedAudio(state) {
  const boxes = audioBoxSpans(state);
  return (state.audio_clips ?? []).filter(clip=>referenceEnabled(state,clip.slot))
    .flatMap(clip=>resolveWindows(clip,boxes).map(w=>({...w,slot:clip.slot})));
}

export function activeAudioClips(state, index, context = 0) {
  const frames = tracks.startFrame(state,state.boxes[index].id);
  const start = frames / FPS, end = start + state.boxes[index].frames / FPS;
  let spans;
  return (state.audio_clips ?? []).filter(clip => {
    if (!referenceEnabled(state, clip.slot)) return false;
    const after = start - (clip.box_windows && !isFresh(state, index) ? context / FPS : 0);
    // A clip not locked to boxes has one window, its own placement.
    if (!Object.hasOwn(clip, 'box_windows')) return clip.start < end && clip.start + clip.duration > after;
    return resolveWindows(clip, spans ??= audioBoxSpans(state)).some(w => w.start < end && w.start + w.duration > after);
  });
}

export function audioBoxSpans(state) {
  return tracks.placements(state).map(p=>({id:p.id,start:p.start/FPS,duration:(p.end-p.start)/FPS}));
}

export function audioSourceDuration(clip) {
  return Number.isFinite(clip?.source_duration) && clip.source_duration > 0 ? clip.source_duration : null;
}

export function editAudioClip(clip, mode, delta) {
  if(clip.box_windows)throw Error('Unlock audio from boxes before changing its placement.');
  if (mode !== 'move' && audioSourceDuration(clip) === null) throw Error('Source duration unavailable; read the audio file before trimming.');
  const result = {...clip};
  const minimum = Math.min(1 / FPS, clip.source_duration);
  if (mode === 'move') result.start = Math.max(0, clip.start + delta);
  else if (mode === 'left') {
    const trim = Math.max(-Math.min(clip.start, clip.source_start), Math.min(delta, clip.duration - minimum));
    result.start += trim; result.source_start += trim; result.duration -= trim;
  } else {
    result.duration = Math.max(Math.min(minimum, clip.source_duration - clip.source_start), Math.min(clip.duration + delta, clip.source_duration - clip.source_start));
  }
  return result;
}

export function soundtrackSlots(state) {
  return (state.audio_clips ?? []).filter(clip => clip.in_full_video === true && clip.file).map(clip => clip.slot).sort();
}

export function soundtrackLine(slots) {
  return slots.length ? `Soundtrack: ${slots.map(slot => `@${slot}`).join(', ')}. H3’s own audio is left out.` : '';
}

export function globalFrame(state, index, frame) {
  const box = state.boxes[index];
  const fresh = isFresh(state, index);
  if (!box || !Number.isInteger(frame) || frame < 0 || frame > box.frames - (fresh ? 1 : 0)) return null;
  return tracks.startFrame(state,box.id) + frame - (fresh ? 0 : 1);
}

export function effectivePlates(state, index, frame = 0) {
  const result = {};
  for (let i = 0; i <= index; i++) {
    const changes = state.boxes[i].plate_changes;
    if (!changes?.length) continue;
    for (const change of [...changes].sort((a, b) => a.frame - b.frame)) {
      if(state.reference_replacements?.[change.slot])continue;
      if (i === index && change.frame > frame) continue;
      if (!change.revision) { delete result[change.slot]; continue; }
      const revision = state.plates?.find((p) => p.id === change.revision && p.slot === change.slot);
      if (!revision?.image) throw new Error(`The accepted plate for @${change.slot} is missing. Choose a plate again.`);
      result[change.slot] = revision;
    }
  }
  return result;
}

export function addBox(state, context, frames) {
  const index = state.boxes.length;
  const fresh = index === 0;
  state.boxes.push({
    id: newId(state),
    frames: frames == null ? defaultFrames(fresh, context) : snapFrames(frames, fresh, context),
    prompt: '', seed: newSeed(), cut: false, first: '', last: '', memory: 'scene',
  });
  return index;
}

export function removeBox(state, index, context) {
  const [removed] = state.boxes.splice(index, 1);
  pruneWindows(state);
  const next = state.boxes[index];
  for (const entity of Array.isArray(state.bible?.entities) ? state.bible.entities : []) {
    if (Array.isArray(entity?.pins)) entity.pins = entity.pins.filter((pin) => pin?.box !== removed.id);
    if (!Array.isArray(entity?.looks)) continue;
    const taken = !next || entity.looks.some((look) => look?.from === next.id);
    entity.looks = entity.looks.flatMap((look) => look?.from !== removed.id ? [look]
      : taken ? [] : [{ ...look, from: next.id }]);
  }
  normalize(state, context);
  return Math.min(index, state.boxes.length - 1);
}

// What a deleted clip leaves behind elsewhere in the Timeline: timed windows, Cast pins and looks that name it.
export function forgetBoxes(state, ids) {
  const gone = new Set(ids);
  pruneWindows(state);
  for (const entity of Array.isArray(state.bible?.entities) ? state.bible.entities : []) {
    if (Array.isArray(entity?.pins)) entity.pins = entity.pins.filter((pin) => !gone.has(pin?.box));
    if (Array.isArray(entity?.looks)) entity.looks = entity.looks.filter((look) => !gone.has(look?.from));
  }
}

export function moveBox(state, index, delta, context) {
  const target = index + delta;
  if (target < 0 || target >= state.boxes.length) return index;
  const [box] = state.boxes.splice(index, 1);
  state.boxes.splice(target, 0, box);
  normalize(state, context);
  return target;
}

export function duplicateBox(state, index, context) {
  state.boxes.splice(index + 1, 0, { ...structuredClone(state.boxes[index]), id: newId(state), seed: newSeed(), cut: false });
  const copy = state.boxes[index + 1];
  delete copy.new_scene;
  // The copy follows a clip with several videos, so it starts with a Cut; its videos get ids of their own.
  if (copy.layers?.length) {
    copy.cut = true;
    const ids = new Map();
    for (const layer of copy.layers) {
      const id = newId(state);
      ids.set(layer.id, id);
      Object.assign(layer, {id, seed: newSeed()});
    }
    const sw = copy.switch;
    sw.cuts = sw.cuts.map((cut) => ({...cut, to: ids.get(cut.to) ?? copy.id}));
    if (ids.has(sw.sound)) sw.sound = ids.get(sw.sound);
    if (sw.align) {
      sw.align = Object.fromEntries(Object.entries(sw.align).map(([video, shift]) => [ids.get(video) ?? copy.id, shift]));
    }
  }
  normalize(state, context);
  return index + 1;
}

export function setCut(state, index, cut, context) {
  state.boxes[index].cut = cut;
  if (!cut) delete state.boxes[index].new_scene;
  normalize(state, context);
}

export const JOINS = ['continue', 'transition', 'cut', 'new_scene'];

// The box's join kind: its join's kind when the flags allow it, else the kind its flags give.
export function joinKind(box) {
  const flags = box.cut ? (box.new_scene ? 'new_scene' : 'cut') : 'continue';
  const kind = box.join?.kind;
  return kind === flags || (kind === 'transition' && flags === 'continue') ? kind : flags;
}

// Sets the flags for `kind`; the join is kept only for a transition or a note, as story_bible.saved_join.
export function setJoin(state, index, kind, note, context) {
  setCut(state, index, kind === 'cut' || kind === 'new_scene', context);
  const box = state.boxes[index];
  if (kind === 'new_scene') box.new_scene = true;
  else delete box.new_scene;
  const text = String(note ?? '').trim();
  if (kind === 'transition' || text) box.join = { kind, note: text };
  else delete box.join;
}

// The file `slot` plays now, as reference_replacements.file_for resolves it: a replacement's own file or its source
// slot's, else the slot's own picture or clip. null when nothing plays there or the replacements form a cycle.
export function recordingFile(state, slot) {
  const replacements = state.reference_replacements ?? {}, seen = new Set();
  let name = slot;
  while (replacements[name]) {
    if (seen.has(name)) return null;
    seen.add(name);
    if (replacements[name].file) return replacements[name].file;
    name = replacements[name].source;
  }
  return [...state.pictures ?? [], ...state.voice_clips ?? [], ...state.audio_clips ?? []]
    .find((entry) => entry.slot === name)?.file ?? null;
}

// Cue and clip times are decimal seconds; an edge within this of a frame edge is on it, as dialogue.EPSILON.
const CUE_EPSILON = 1e-6;

// [first frame, end frame, portrayal] of each part of `cue` its bound recording plays, rounded outward as
// dialogue.placed rounds them; [] when the cue is unbound or outside its clip's window.
function cueFrames(state, cue) {
  const slot = cue.recording?.slot, file = recordingFile(state, slot), wanted = cue.recording?.file;
  const clip = (state.audio_clips ?? []).find((item) => item.slot === slot);
  if (!clip || (state.disabled_refs ?? []).includes(slot) || !file || !wanted
      || ['type', 'subfolder', 'filename'].some((key) => (file[key] ?? '') !== (wanted[key] ?? ''))) return [];
  const parts = [];
  let cursor = cue.start;
  for (const span of [...cue.spans ?? []].sort((one, other) => one.start - other.start)) {
    if (span.start > cursor) parts.push([cursor, span.start, cue.portrayal]);
    parts.push([span.start, span.end, span.portrayal]);
    cursor = span.end;
  }
  if (cursor < cue.end) parts.push([cursor, cue.end, cue.portrayal]);
  return resolveWindows(clip,audioBoxSpans(state)).flatMap(window => {
  const start = Math.max(cue.start, window.source_start), end = Math.min(cue.end, window.source_start + window.duration);
  const frame = seconds => (window.start + seconds-window.source_start)*FPS;
  return parts.map(([first, last, portrayal]) => [Math.max(first, start), Math.min(last, end), portrayal])
    .filter(([first, last]) => last - first > CUE_EPSILON)
    .map(([first, last, portrayal]) => [Math.floor(frame(first) + CUE_EPSILON), Math.ceil(frame(last) - CUE_EPSILON), portrayal]);
  });
}

// Whether box `index` asks H3 for speech someone may say on screen, as dialogue.speaks: typed <d>, or a bound cue
// over its frames that isn't all voiceover.
export function speaks(state, index) {
  const box = state.boxes[index];
  if ([state.prompt, box.prompt].some((text) => String(text ?? '').includes('<d>'))) return true;
  if (box.dialogue === 'manual') return false;
  const start = state.boxes.slice(0, index).reduce((sum, item) => sum + item.frames, 0), end = start + box.frames;
  return (state.dialogue?.cues ?? []).some((cue) => cueFrames(state, cue)
    .some(([first, last, portrayal]) => portrayal !== 'voiceover' && first < end && last > start));
}

// What may sound wrong in clip `index` with several videos: a bound line across a swap while the sound follows the
// screen switches voices mid-line.
export function swapWarnings(state, index) {
  const box = state.boxes[index], sw = box?.switch;
  if (!sw || (sw.sound ?? 'screen') !== 'screen') return [];
  const start = state.boxes.slice(0, index).reduce((sum, item) => sum + item.frames, 0);
  const lines = (state.dialogue?.cues ?? []).flatMap((cue) => cueFrames(state, cue));
  return sw.cuts.filter((cut) => lines.some(([first, last]) => first < start + cut.at && last > start + cut.at))
    .map((cut) => `A line crosses the swap at frame ${cut.at} while the sound follows the screen, so the voice `
      + 'switches mid-line. Choose one video’s sound for this clip.');
}

export function memorySources(state, index) {
  const box = state.boxes[index];
  if (!box || !box.memory || box.memory === 'off') return [];
  const sources = box.memory === 'scene' ? sceneSources(state, index)
    : box.memory === 'cast' ? castSources(state, index) : box.memories ?? [];
  const beforeIndex=tracks.previousIndex(state,index,false);
  if (beforeIndex===null || !box.cut) return sources;
  const previous=state.boxes[beforeIndex];
  if (speaks(state,index) || speaks(state,beforeIndex)) {
    const before = {box: previous.id, frame: Math.max(0, previous.frames - 5), label: 'the moment before this cut'};
    return sources.some((item) => item.box === before.box && item.frame === before.frame) ? sources : [...sources, before];
  }
  return [{box: previous.id, frame: 0, label: 'the previous shot before this cut', whole: true},
    ...sources.filter(item => box.memory === 'selected' || item.box !== previous.id)];
}

function sceneSources(state, index) {
  const box = state.boxes[index];
  const indices=tracks.trackIndices(state,index), prior=indices.slice(0,indices.indexOf(index)+1);
  let start=prior[0];
  for(const i of prior) if ((state.boxes[i].cut&&state.boxes[i].new_scene)||state.boxes[i].plate_changes?.length) start=i;
  if(start===index) return [];
  const previous=state.boxes[prior.at(-2)];
  return [{box: state.boxes[start].id, frame: 0, label: 'scene establishing view'}, box.cut
    ? {box: previous.id, frame: Math.max(0, previous.frames - 5), label: 'the moment before this cut'}
    : {box: previous.id, frame: Math.max(0, Math.floor((previous.frames - 5) / 2)), label: 'earlier view of the current scene'}];
}

// The entity's look at box `index`: 0 for its description, or k for looks[k-1], as story_bible.look_at.
export function lookAt(entity, boxes, index) {
  const position = new Map(boxes.map((box, i) => [box.id, i]));
  let chosen = 0, start = -1;
  (entity.looks ?? []).forEach((look, k) => {
    const at = position.get(look?.from);
    if (at !== undefined && start < at && at <= index) [chosen, start] = [k + 1, at];
  });
  return chosen;
}

// Cast memory's windows, as h3_continuity/cast_memory.windows.
function castSources(state, index) {
  const box = state.boxes[index];
  const budget = Math.max(0, 3 - refmodVideos(state, index));
  const schedule = box.schedule;
  if (!state.bible || !record(schedule)) return sceneSources(state, index).slice(0, budget);
  const position = new Map(state.boxes.map((item, i) => [item.id, i]));
  const byId = new Map((Array.isArray(state.bible.entities) ? state.bible.entities : []).filter(record)
    .map((entity) => [entity.id, entity]));
  const found = [];
  for (const id of Array.isArray(schedule.entities) ? schedule.entities : []) {
    const entity = byId.get(id);
    if (entity?.kind === 'character' && !shownAt(state, index, entity))
      found.push(castMoment(state, index, entity, position, characterBox));
  }
  const place = schedule.place == null ? undefined : byId.get(schedule.place);
  const previous = index ? state.boxes[index - 1].schedule : undefined;
  const atPlace = !!place && record(previous) && previous.place === place.id;
  if (place && !(atPlace && !box.cut)) found.push(castMoment(state, index, place, position, placeBox));
  if (atPlace && box.cut) {
    const before = state.boxes[index - 1];
    found.push({box: before.id, frame: Math.max(0, before.frames - 5), label: 'the moment before this cut'});
  }
  const result = [];
  for (const window of found) {
    if (window && !result.some((item) => item.box === window.box && item.frame === window.frame)) result.push(window);
  }
  return result.slice(0, budget);
}

// The box's RefMods videos, as timeline.box_slots counts them.
function refmodVideos(state, index) {
  let plates = {};
  try { plates = effectivePlates(state, index); } catch { plates = {}; }
  const mods = new Map(effectiveRefmods(state).map((ref) => [ref.slot, ref]));
  return mentions(assemblePrompt(state, index))
    .filter((ref) => ref.kind === 'image' && mods.get(ref.name)?.kind === 'video' && !plates[ref.name]).length;
}

function shownAt(state, index, entity) {
  const look = lookAt(entity, state.boxes, index);
  const own = (look ? entity.looks[look - 1].pictures : entity.pictures) ?? [];
  const mentioned = new Set(mentions(assemblePrompt(state, index)).filter((ref) => ref.kind === 'image').map((ref) => ref.name));
  return own.some((slot) => mentioned.has(slot));
}

function castMoment(state, index, entity, position, earlierBox) {
  const look = lookAt(entity, state.boxes, index);
  const start = look ? position.get(entity.looks[look - 1].from) : 0;
  let moment = null;
  for (const pin of Array.isArray(entity.pins) ? entity.pins : []) {
    const at = position.get(pin?.box);
    if (at !== undefined && start <= at && at < index && Number.isInteger(pin.frame) && pin.frame >= 0
        && pin.frame < state.boxes[at].frames && (!moment || at >= moment.at)) moment = {at, frame: pin.frame};
  }
  moment ??= earlierBox(state, index, entity, start);
  if (!moment) return null;
  const label = Object.entries(state.boxes[index].cast ?? {}).find(([, value]) => value === entity.id)?.[0] ?? entity.name;
  return {box: state.boxes[moment.at].id, frame: moment.frame, label: `showing ${label}`};
}

function characterBox(state, index, entity, start) {
  for (let at = start; at < index; at++) {
    const box = state.boxes[at];
    if (Array.isArray(box.schedule?.entities) && box.schedule.entities.includes(entity.id)) {
      const frame = shotMiddle(box.source, entity.id);
      return {at, frame: frame === null ? Math.max(0, box.frames - 5) : Math.min(Math.max(frame, 0), box.frames - 1)};
    }
  }
  return null;
}

function placeBox(state, index, entity, start) {
  for (let at = index - 1; at >= start; at--) {
    if (state.boxes[at].schedule?.place === entity.id) return {at, frame: Math.max(0, state.boxes[at].frames - 5)};
  }
  return null;
}

// Shot times count the replay; the source's frame has the box's frames and carried frames.
function shotMiddle(source, id) {
  const frame = record(source) ? source.frame : null;
  const shots = record(source) && record(source.reply) ? source.reply.shots : null;
  if (!record(frame) || !Array.isArray(shots)) return null;
  const frames = frame.frames, carried = Object.hasOwn(frame, 'carried') ? frame.carried : 0;
  const starts = shots.map((shot) => record(shot) ? shot.start_ms : null);
  if (!Number.isInteger(frames) || !Number.isInteger(carried) || !starts.every(Number.isInteger)) return null;
  for (let number = shots.length - 1; number >= 0; number--) {
    if (!Array.isArray(shots[number].subjects) || !shots[number].subjects.includes(id)) continue;
    const start = Math.max(starts[number], Math.round(carried * 1000 / FPS));
    const end = number + 1 < shots.length ? starts[number + 1] : Math.round(frames * 1000 / FPS);
    return Math.floor((start + end) * FPS / 2000) - carried;
  }
  return null;
}

// Plain parts {text} and mentions {text, name, kind}; the texts of the parts join back to `text`.
export function mentionParts(text) {
  const source = String(text ?? '');
  const parts = [];
  let at = 0;
  for (const match of source.matchAll(MENTION)) {
    if (match.index > at) parts.push({ text: source.slice(at, match.index) });
    const kind = match[1].toLowerCase();
    parts.push({ text: match[0], name: `${kind}${Number(match[2])}`, kind });
    at = match.index + match[0].length;
  }
  if (at < source.length) parts.push({ text: source.slice(at) });
  return parts;
}

export function mentions(text) {
  const found = [];
  for (const match of String(text ?? '').matchAll(MENTION)) {
    const kind = match[1].toLowerCase(), name = `${kind}${Number(match[2])}`;
    if (!found.some((item) => item.name === name)) found.push({ kind, name });
  }
  return found;
}

export function assemblePrompt(state, index) {
  const active = activeAudioClips(state, index);
  const inactive = (state.audio_clips ?? []).filter(clip => !active.includes(clip)).map(clip => clip.slot);
  const view = {disabled_refs: [...state.disabled_refs ?? [], ...inactive]};
  const [shared, prompt] = [state.prompt, state.boxes[index].prompt].map((part) => withoutDisabledRefs((part ?? '').trim(), view));
  if (shared && /^(integrated_multimodal_description:|subject_definitions:|For the target video,|How the reference pictures align)/.test(prompt)
      && prompt.includes('\noverall_soundscape:') && prompt.includes('\nnon_diegetic_music:')
      && prompt.includes('[Shot 1] ')) {
    return prompt.replace('[Shot 1] ', () => `[Shot 1] ${shared} `);
  }
  return [shared, prompt].filter(Boolean).join('\n\n');
}

export function referenceEnabled(state, name) {
  const disabled = state.disabled_refs ?? [];
  return !disabled.includes(name) && !(name?.startsWith('video_audio') && disabled.includes(name.replace('video_audio', 'video')));
}

export function referenceType(name) {
  return /^(image|video_audio|video|audio)[1-9]\d*$/.exec(name)?.[1] ?? '';
}

export function referenceMediaType(state,name) {
  return state.refmods?.some(ref=>ref.slot===name&&ref.kind==='video') ? 'refmod_video' : referenceType(name);
}

export function effectiveRefmods(state,{includeDisabled=false}={}) {
  const mods=new Map((state.refmods??[]).filter(ref=>includeDisabled||(ref.strength??1)>0).map(ref=>[ref.slot,ref]));
  const replacements=state.reference_replacements??{};
  const resolve=(slot,path=[])=> {
    if(path.includes(slot))return null;
    const replacement=replacements[slot];
    if(!replacement)return mods.get(slot);
    if(!replacement.source)return null;
    const source=resolve(replacement.source,[...path,slot]);
    return source?{...source,slot}:null;
  };
  return [...new Set([...mods.keys(),...Object.keys(replacements)])].map(slot=>resolve(slot)).filter(Boolean);
}

const referenceGroup = {image:'images',video:'videos',audio:'audios',video_audio:'video_audios'};

function soundtrackPairingProblems(replacements) {
  const effective={...replacements};
  for(const [slot,value] of Object.entries(replacements)) {
    if(referenceType(slot)==='video')effective[slot.replace('video','video_audio')]??=value.source
      ? {source:value.source.replace('video','video_audio')} : value;
  }
  const origin=(slot,path=[])=> {
    if(path.includes(slot))return null;
    const value=effective[slot];
    return value?.source?origin(value.source,[...path,slot]):value??{source:slot};
  };
  return Object.keys(replacements).filter(slot=>referenceType(slot)==='video_audio').flatMap(slot=> {
    const audio=origin(slot),video=origin(slot.replace('video_audio','video'));
    if(!audio||!video||audio.file)return [];
    const paired=video.source?{source:video.source.replace('video','video_audio')}:video;
    return JSON.stringify(audio)===JSON.stringify(paired)?[]:[[slot,`Replacement soundtrack @${slot} must stay paired with its video.`]];
  });
}

export function referencePools(state, pools, viewUrl) {
  const original = new Map(Object.values(pools).flat().map(ref => [ref.name,ref]));
  const replacements = state.reference_replacements ?? {};
  const pairing=new Map(soundtrackPairingProblems(replacements));
  const names = new Set([...original.keys(),...Object.keys(replacements)]);
  const hasSoundtrack = (slot,path=[]) => {
    if(path.includes(slot))return false;
    const replacement=replacements[slot];
    if(replacement?.file)return true; // Uploaded video audio is validated when its components are decoded.
    if(replacement?.source)return hasSoundtrack(replacement.source,[...path,slot]);
    return original.has(slot.replace('video','video_audio'));
  };
  for (const [name,value] of Object.entries(replacements)) {
    if (referenceType(name) !== 'video') continue;
    const paired = name.replace('video','video_audio');
    if (original.has(paired) || hasSoundtrack(name)) names.add(paired);
  }
  const resolve = (name, path = []) => {
    if(pairing.has(name))return {name,problem:pairing.get(name)};
    if (path.includes(name)) return {name,problem:`Reference replacement cycle: ${[...path,name].join(' → ')}.`};
    let replacement = replacements[name];
    if (!replacement && referenceType(name) === 'video_audio') {
      const video = replacements[name.replace('video_audio','video')];
      if (video) replacement = video.source ? {source:video.source.replace('video','video_audio')} : video;
    }
    if (!replacement) return original.get(name) ?? {name,problem:`@${name} is not connected.`};
    if (replacement.source) {
      if (referenceType(name) !== referenceType(replacement.source)||referenceMediaType(state,name)!==referenceMediaType(state,replacement.source)) return {name,problem:'Replacement must have the same reference type.'};
      const source = resolve(replacement.source,[...path,name]);
      return {...source,name,originalTitle:original.get(name)?.title,replaced:true,replacementSource:replacement.source};
    }
    if(referenceMediaType(state,name)==='refmod_video')return {name,problem:'Replace a video RefMod with a matching video RefMod.'};
    if (!replacement.file?.filename) return {name,problem:`@${name} has an invalid replacement file.`};
    const file = replacement.file;
    return {name,title:file.filename,file:file.filename,mediaFile:file,
      preview:referenceType(name) === 'image' ? viewUrl?.(file) : null,replaced:true};
  };
  const result = {images:[],videos:[],audios:[],video_audios:[]};
  for (const name of names) {
    const group = referenceGroup[referenceType(name)];
    if (group) result[group].push(resolve(name));
  }
  for (const group of Object.values(result)) group.sort((a,b)=>Number(a.name.replace(/\D/g,''))-Number(b.name.replace(/\D/g,'')));
  return result;
}

export function applyImageDescription(state, slot, description) {
  if (referenceType(slot) !== 'image') return;
  if (description) {
    state.reference_descriptions ??= {};
    state.reference_descriptions[slot] = structuredClone(description);
  }
  const text = description?.text ?? '';
  const positions = new Map(state.boxes.map((box,index)=>[box.id,index]));
  for (const entity of state.bible?.entities ?? []) {
    let pictures = entity.pictures ?? [];
    const wording = refs => text || refs.map(name => `"@${name}"`).join(' and ');
    if (pictures.includes(slot) && entity.description !== slot) {
      entity.description = wording(pictures);
    }
    for (const look of [...entity.looks ?? []].sort((a,b)=>(positions.get(a.from)??-1)-(positions.get(b.from)??-1))) {
      if (look.pictures?.length) pictures = look.pictures;
      if (pictures.includes(slot)) look.description = wording(pictures);
    }
  }
  state.prompt = imageDescriptionPrompt(state.prompt, slot, text);
  for (const box of [...state.boxes, ...state.bridges ?? []]) {
    box.prompt = imageDescriptionPrompt(box.prompt, slot, text);
    const entities = (state.bible?.entities ?? []).filter(entity => {
      let pictures = entity.pictures ?? [];
      for (const look of [...entity.looks ?? []].sort((a,b)=>(positions.get(a.from)??-1)-(positions.get(b.from)??-1)))
        if (look.pictures?.length && positions.has(look.from) && positions.get(look.from) <= (positions.get(box.id)??-1)) pictures = look.pictures;
      return pictures.includes(slot);
    }).map(entity=>entity.id);
    imageDescriptionSource(box.source, slot, text, entities);
  }
}

function invalidateReferenceDescriptions(state, slot) {
  const affected = new Set([slot]);
  let changed;
  do {
    changed = false;
    for (const name of [...affected]) {
      if(referenceType(name)==='video'&&!affected.has(name.replace('video','video_audio'))) {
        affected.add(name.replace('video','video_audio'));changed=true;
      }
    }
    for (const [target,value] of Object.entries(state.reference_replacements ?? {})) {
      if (affected.has(value.source) && !affected.has(target)) { affected.add(target); changed = true; }
    }
  } while (changed);
  for (const name of affected) {
    if (referenceType(name) === 'image') applyImageDescription(state, name, null);
    if (state.reference_descriptions) delete state.reference_descriptions[name];
    if (referenceType(name) === 'video' && state.reference_descriptions) delete state.reference_descriptions[name.replace('video','video_audio')];
  }
}

export function setReferenceReplacement(state, slot, replacement, pools) {
  if(audioSourceLocked(state,slot))throw Error('Unlock audio from boxes before replacing its source.');
  if (!referenceType(slot)) throw new Error('Choose a valid reference.');
  if (!!replacement.source === !!replacement.file) throw new Error('Choose a reference or a file.');
  if (replacement.source && referenceType(slot) !== referenceType(replacement.source)) throw new Error('Replacement must have the same reference type.');
  const replacements = {...state.reference_replacements,[slot]:structuredClone(replacement)};
  if(referenceType(slot)==='video'&&replacements[slot.replace('video','video_audio')]?.source)
    delete replacements[slot.replace('video','video_audio')];
  const problem=soundtrackPairingProblems(replacements)[0]?.[1];
  if(problem)throw new Error(problem);
  const next = referencePools({...state,reference_replacements:replacements},pools);
  const resolved = next[referenceGroup[referenceType(slot)]].find(ref=>ref.name===slot);
  if (resolved.problem) throw new Error(resolved.problem);
  state.reference_replacements = replacements;
  invalidateReferenceDescriptions(state,slot);
}

export function restoreReferenceReplacement(state, slot) {
  if(audioSourceLocked(state,slot))throw Error('Unlock audio from boxes before replacing its source.');
  const replacements={...state.reference_replacements};
  delete replacements[slot];
  if(referenceType(slot)==='video'&&replacements[slot.replace('video','video_audio')]?.source)
    delete replacements[slot.replace('video','video_audio')];
  const problem=soundtrackPairingProblems(replacements)[0]?.[1];
  if(problem)throw new Error(problem);
  invalidateReferenceDescriptions(state,slot);
  if (state.reference_replacements) state.reference_replacements=replacements;
  if (!Object.keys(state.reference_replacements ?? {}).length) delete state.reference_replacements;
}

export function switchReference(state, from, to, pools) {
  if(audioSourceLocked(state,from)||audioSourceLocked(state,to))throw Error('Unlock audio from boxes before switching its source.');
  if(from===to || !referenceType(from) || referenceType(from)!==referenceType(to))
    throw new Error('Replacement must have the same reference type.');
  const available=referencePools(state,pools);
  const selected=available[referenceGroup[referenceType(to)]].find(ref=>ref.name===to);
  if(!selected || selected.problem)throw new Error(selected?.problem ?? `@${to} is not connected.`);
  const swaps={[from]:to};
  if(referenceType(from)==='video') {
    const oldAudio=from.replace('video','video_audio'),newAudio=to.replace('video','video_audio');
    const used=[state.prompt,...state.boxes.map(box=>box.prompt)].some(prompt=>mentions(prompt).some(ref=>ref.name===oldAudio));
    if(used&&!available.video_audios.some(ref=>ref.name===newAudio&&!ref.problem))
      throw new Error(`@${to} needs a soundtrack to replace the used @${oldAudio}.`);
    swaps[oldAudio]=newAudio;
  }
  if (referenceType(from) === 'image') applyImageDescription(state, from, null);
  const text=value=>value.replace(MENTION,(tag,kind,number)=> {
    const replacement=swaps[`${kind.toLowerCase()}${Number(number)}`];
    return replacement ? `@${replacement}` : tag;
  });
  // Only authored content is rewritten. Library definitions and generated media retain their original slots.
  const rewrite=(value,key='')=> {
    if(key==='voice_clip'&&swaps[value])return (state.voice_clips??[]).some(clip=>clip.slot===swaps[value]) ? swaps[value] : undefined;
    if(typeof value==='string')return ['first','last','pictures','references','sources','source','audio_slot'].includes(key)
      ? swaps[value] ?? text(value) : text(value);
    if(Array.isArray(value)) {
      const values=value.map(item=>rewrite(item,key));
      return values.every(item=>typeof item==='string'&&referenceType(item)) ? [...new Set(values)] : values;
    }
    if(record(value))return Object.fromEntries(Object.entries(value).map(([key,item])=>
      [key,['id','from','box','cast','schedule','frame','file','image','filename','subfolder','type'].includes(key)?item:rewrite(item,key)]).filter(([,item])=>item!==undefined));
    return value;
  };
  state.prompt=text(state.prompt);
  state.boxes=state.boxes.map(box=> {
    const next=rewrite(box);
    for(const key of ['plate_changes','plate_edits'])if(box[key])next[key]=box[key].filter(item=>!swaps[item.slot]);
    return next;
  });
  if(state.bible)state.bible=rewrite(state.bible);
  if(state.bridges)state.bridges=rewrite(state.bridges);
  if(state.timed_text?.audio_slot)state.timed_text.audio_slot=swaps[state.timed_text.audio_slot]??state.timed_text.audio_slot;
  const disabled=new Set(state.disabled_refs ?? []);
  for(const [old,name] of Object.entries(swaps)){disabled.add(old);disabled.delete(name);}
  if(referenceType(to)==='video_audio')disabled.delete(to.replace('video_audio','video'));
  state.disabled_refs=[...disabled];
  for(const ref of state.refmods ?? [])if(Object.values(swaps).includes(ref.slot)&&(ref.strength??1)<=0)ref.strength=1;
}

export function withoutDisabledRefs(text, state) {
  return text.replace(/(?<![\w@])@(image|audio|video_audio|video)(\d+)(?!\w)/gi, (tag, kind, number) =>
    referenceEnabled(state, `${kind.toLowerCase()}${Number(number)}`) ? tag
      : ['audio', 'video_audio'].includes(kind.toLowerCase()) ? 'the described sound' : 'the described subject');
}

const slotNumber = (name) => Number(name.replace(/\D/g, ''));

export function referenceTags(images, audios = [], refmods = [], plates = {}, videos = [], videoAudios = []) {
  const assigned = new Map(refmods.filter(ref => (ref.strength ?? 1) > 0 && !plates[ref.slot]).map(ref => [ref.slot, ref]));
  const sort = names => [...names].sort((a, b) => slotNumber(a) - slotNumber(b));
  const rawImages = sort(images.filter(name => !assigned.has(name)));
  const rawAudios = sort(audios.filter(name => !assigned.has(name)));
  const rawVideos = sort(videos), soundtracks = sort(videoAudios);
  const tags = [...rawImages.map((name, i) => ({name, tag: `<Picture ${i + 1}>`})),
    ...rawVideos.map((name, i) => ({name, tag: `<Video ${i + 1}>`})),
    ...[...soundtracks, ...rawAudios].map((name, i) => ({name, tag: `<Audio ${i + 1}>`}))];
  const counters = {image: rawImages.length, audio: soundtracks.length + rawAudios.length, video: rawVideos.length};
  for (const name of [...sort(images), ...sort(audios)]) {
    const ref = assigned.get(name);
    if (ref) tags.push({name, tag: `<${{image: 'Picture', video: 'Video', audio: 'Audio'}[ref.kind]} ${++counters[ref.kind]}>`});
  }
  return tags;
}

export function describeBox(state, index, connected, context) {
  const box = state.boxes[index];
  const fresh = isFresh(state, index);
  const first = fresh && referenceEnabled(state, box.first) ? box.first : '';
  const last = referenceEnabled(state, box.last) ? box.last : '';
  const keyframes = [first, last].filter(Boolean);
  const text = assemblePrompt(state, index);
  const found = mentions(text);
  const images = found.filter((item) => item.kind === 'image').map((item) => item.name);
  const audios = [...new Set([...found.filter((item) => item.kind === 'audio').map((item) => item.name),
    ...activeAudioClips(state, index, context).map(clip => clip.slot)])];
  const videoAudios = found.filter(item => item.kind === 'video_audio').map(item => item.name);
  const videos = [...new Set([...found.filter(item => item.kind === 'video').map(item => item.name),
    ...videoAudios.map(name => name.replace('video_audio', 'video'))])];
  const mods = new Map(effectiveRefmods(state).map(ref => [ref.slot, ref]));
  const problems = [];
  for (const memory of memorySources(state, index)) {
    const source = state.boxes.findIndex(item => item.id === memory.box);
    if (source < 0 || (tracks.enabled(state) ? tracks.startFrame(state,memory.box)+memory.frame>=tracks.startFrame(state,box.id) : source>=index)) problems.push('Visual memory needs an earlier source box; choose it again.');
    else if (!Number.isInteger(memory.frame) || memory.frame < 0 || memory.frame >= state.boxes[source].frames)
      problems.push(`Visual memory is past the end of box ${source + 1}, which plays ${state.boxes[source].frames} `
        + 'frames; choose an earlier moment.');
  }
  if (!text) problems.push('The prompt is empty.');
  for (const item of found) {
    if (connected.problems?.has(item.name)) problems.push(connected.problems.get(item.name));
    const pool = connected[{image: 'images', audio: 'audios', video: 'videos', video_audio: 'video_audios'}[item.kind]];
    if (!pool?.has(item.name) && !mods.has(item.name)) problems.push(`@${item.name} is not connected.`);
    if (connected.conflicts?.has(item.name)) problems.push(`@${item.name} has both an image input and a RefMod.`);
  }
  for (const name of videos) {
    if (!connected.videos?.has(name) && !problems.includes(`@${name} is not connected.`)) problems.push(`@${name} is not connected.`);
  }
  for (const [what, name] of [['First frame', first], ['Last frame', last]]) {
    if (name && !connected.images.has(name)) problems.push(`${what} ${name} is not connected.`);
    if (mods.has(name)) problems.push(`${what} needs an image input, not a RefMod.`);
  }
  let mode;
  let tags = [];
  let guides = [];
  const acceptedFrames = box.flf_refmods ? acceptedGuideFrames(state, index, context) : [];
  const acceptedFirst = fresh && acceptedFrames.includes(0);
  const acceptedLast = acceptedFrames.includes(box.frames - (fresh ? 1 : 0))
    || (box.flf_refmods && state.boxes[index + 1] && !isFresh(state, index + 1)
      && acceptedGuideFrames(state, index + 1, context).includes(0));
  // Raw audio rides along as the same audio reference REF2VA builds; raw video has no FLF2VA form.
  if (box.flf_refmods && (!fresh || first || acceptedFirst) && !videos.length) {
    mode = 'FLF2VA';
    const lastPresent = !!(last || acceptedLast) && (!fresh || box.frames > 1 || (last && images.includes(last)));
    const firstPresent = Number(!!(first || acceptedFirst));
    const endpointCount = firstPresent + Number(lastPresent);
    if (first) tags.push({name:first,tag:'<Picture 1>'});
    if (last && lastPresent && last !== first) tags.push({name:last,tag:`<Picture ${firstPresent + 1}>`});
    const ordinary = images.filter(name => !mods.has(name) && !keyframes.includes(name)).sort((a,b) => slotNumber(a)-slotNumber(b));
    const counters = {image:endpointCount*2,video:0,audio:0};
    for (const name of ordinary) tags.push({name,tag:'<Picture ' + (++counters.image) + '>'});
    const rawAudios = audios.filter(name => !mods.has(name)).sort((a,b) => slotNumber(a)-slotNumber(b));
    for (const name of rawAudios) tags.push({name,tag:'<Audio ' + (++counters.audio) + '>'});
    if (rawAudios.length > MAX_REF_AUDIOS) problems.push(`${rawAudios.length} audios; H3 takes at most ${MAX_REF_AUDIOS}.`);
    const labels = {image:'Picture',video:'Video',audio:'Audio'};
    const selected = [...new Set([...images,...audios])].filter(name => mods.has(name))
      .sort((a,b) => Number(a.startsWith('audio'))-Number(b.startsWith('audio')) || slotNumber(a)-slotNumber(b));
    for(const name of selected) {
      const kind=mods.get(name).kind;
      tags.push({name,tag:'<' + labels[kind] + ' ' + (++counters[kind]) + '>'});
    }
  } else if (!audios.length && !videos.length && images.every((name) => !mods.has(name) && keyframes.includes(name))) {
    mode = keyframes.length ? 'FLF2VA' : 'T2VA';
    keyframes.forEach((name, i) => {
      if (!tags.some((item) => item.name === name)) tags.push({ name, tag: `<Picture ${i + 1}>` });
    });
  } else {
    mode = 'REF2VA';
    images.sort((a, b) => slotNumber(a) - slotNumber(b));
    audios.sort((a, b) => slotNumber(a) - slotNumber(b));
    tags = referenceTags(images, audios, effectiveRefmods(state), effectivePlates(state, index), videos, videoAudios);
    guides = [['first', first], ['last', last]].filter(([, name]) => name).map(([frame, name]) => ({ name, frame }));
    const rawImages = images.filter(name => !mods.has(name)).length;
    const rawAudios = audios.filter(name => !mods.has(name)).length;
    if (rawImages > MAX_REF_IMAGES) problems.push(`${rawImages} images; H3 takes at most ${MAX_REF_IMAGES}.`);
    if (rawAudios > MAX_REF_AUDIOS) problems.push(`${rawAudios} audios; H3 takes at most ${MAX_REF_AUDIOS}.`);
    if (videos.length > 3) problems.push(`${videos.length} videos; H3 takes at most 3.`);
  }
  const { max } = limits(fresh, context, maxFrames(state));
  if (box.frames > max) problems.push(`Longer than the ${max} frames allowed.`);
  const conflict = dropConflict(state, index, context);
  if (conflict) problems.push(conflict);
  const carry = carryConflict(state, index, context);
  if (carry) problems.push(carry);
  if (!switchFits(state, index)) problems.push(SWAPS_DONT_FIT);
  if (index > 0 && state.boxes[index - 1].layers?.length && !fresh) {
    problems.push(`Clip ${index + 1} continues from clip ${index}. With several videos in clip ${index}, `
      + `clip ${index + 1} must start with a Cut.`);
  }
  return { mode, tags, guides, problems, warnings: swapWarnings(state, index), fresh };
}

// Whether a clip runs as FLF2VA once `flf_refmods` is on. Its First/Last frames and accepted endpoint guides become the
// start and end frames, raw images become cached image RefMods and raw audio stays an audio reference; raw video has no
// FLF2VA form.
export function flfConversion(state, index, connected, context) {
  const trial = structuredClone(state);
  trial.boxes[index].flf_refmods = true;
  if (describeBox(trial, index, connected, context).mode === 'FLF2VA') return {ok: true, reason: ''};
  const found = mentions(assemblePrompt(state, index));
  const list = names => [...new Set(names)].map(name => `@${name}`).join(', ');
  const reasons = [];
  const videos = found.filter(item => item.kind === 'video' || item.kind === 'video_audio').map(item => item.name);
  if (videos.length) reasons.push(`${list(videos)}: raw video can't be converted to a RefMod here. Make a video RefMod with RefForge, assign it on the RefMods page and mention that slot instead.`);
  const box = state.boxes[index];
  if (isFresh(state, index) && !(box.first && referenceEnabled(state, box.first)) && !acceptedGuideFrames(state, index, context).includes(0))
    reasons.push('A fresh clip needs a First frame: choose one under First & last frame or accept a First guide.');
  return {ok: false, reason: reasons.join(' ') || 'This clip still runs as REF2VA with FLF2VA + cached RefMods on.'};
}

export function seconds(frames) {
  return (frames / FPS).toFixed(1);
}

export function lengthLabel(state, index, context) {
  const { frames } = state.boxes[index];
  const time = `${(frames / FPS).toFixed(2)} s`;
  const dropped = droppedFrames(state, index);
  const generates = dropped ? ` · H3 generates ${frames + dropped}` : '';
  if (isFresh(state, index)) return `${time} · ${frames} frame${frames === 1 ? '' : 's'}${generates}`;
  return `${time} · ${frames} new + ${context} carried = ${frames + context} frames${generates}`;
}

// The mention card: `tags` are the selected box's, and `boxNumber` is null when no box is selected.
export function describeMention(name, refs, tags, boxNumber) {
  const audio = name.startsWith('audio') || name.startsWith('video_audio');
  const pool = name.startsWith('video_audio') ? refs.video_audios : name.startsWith('video') ? refs.videos : audio ? refs.audios : refs.images;
  const ref = pool?.find((item) => item.name === name);
  if (!ref) {
    return { problem: true, title: `@${name} isn't connected, or its node is muted or bypassed.`, detail: null, preview: null };
  }
  const tag = boxNumber ? tags.find((item) => item.name === name)?.tag : null;
  const where = tag ? `${tag} in box ${boxNumber}` : '';
  return {
    problem: false,
    title: ref.title || `@${name}`,
    detail: (audio ? [ref.file, where] : [where]).filter(Boolean).join(' · ') || null,
    preview: audio ? null : ref.preview ?? null,
  };
}

// The file a Load Image or Load Audio node reads, as the parts ComfyUI's /view takes; null for other nodes.
export function referenceFile(node) {
  const type = node?.type;
  if (!Object.hasOwn(FILE_WIDGETS, type)) return null;
  const value = node.widgets?.find((widget) => widget.name === FILE_WIDGETS[type])?.value;
  const text = typeof value === 'string' ? value.trim() : '';
  const annotation = FILE_ANNOTATION.exec(text);
  const path = (annotation ? text.slice(0, annotation.index) : text).trimEnd();
  if (!path) return null;
  const cut = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'));
  return {
    path,
    filename: path.slice(cut + 1),
    subfolder: cut < 0 ? '' : path.slice(0, cut),
    type: annotation?.[1] ?? (type === 'LoadImageOutput' ? 'output' : 'input'),
  };
}

// Follow only wiring nodes; an image processor's input is not its output preview.
export function referenceSource(node, graph, seen = new Set()) {
  if (!node || seen.has(node.id) || node.mode === 2) return null;
  seen.add(node.id);
  if (node.type === 'GetNode') {
    const name = node.widgets?.[0]?.value;
    const setters = (graph?._nodes ?? []).filter(item => item.type === 'SetNode' && item.widgets?.[0]?.value === name);
    return name && setters.length === 1 ? referenceSource(setters[0], graph, seen) : null;
  }
  if (['SetNode', 'Reroute'].includes(node.type) || node.mode === 4) {
    const inputs = (node.inputs ?? []).filter(input => input.link != null && ['IMAGE', 'AUDIO', '*'].includes(input.type));
    if (inputs.length !== 1) return null;
    const link = graph?.links?.get?.(inputs[0].link) ?? graph?.links?.[inputs[0].link];
    return referenceSource(graph?.getNodeById?.(link?.origin_id), graph, seen);
  }
  return node;
}
