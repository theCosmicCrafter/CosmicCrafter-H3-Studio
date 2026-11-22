// Videos in one clip: up to four H3 generations sharing the clip's time, and the switch plan that says which one is
// on screen. The main video is the box itself; the others live in its `layers`. Mirrors h3_continuity/layers.py.
import {isFresh, newId, playedFrames} from './h3c_timeline_model.mjs?v=1dfc1612e462';
export {LAYERS_FEATURE as FEATURE} from './h3c_timeline_model.mjs?v=1dfc1612e462';

export const MAX_VIDEOS = 4;
export const MAX_FADE = 12;
export const DEFAULT_FADE = 6;
export const LAYER_FIELDS = ['id', 'seed', 'prompt', 'first', 'last', 'previews', 'memory', 'memories', 'dialogue'];
const LETTERS = 'bcd';

const played = (state, index) => {
  const box = state.boxes[index];
  return playedFrames(box.frames, box.exact, isFresh(state, index));
};

export function hasLayers(state) {
  return state.boxes.some((box) => box.layers?.length);
}

export function layerIds(state) {
  return state.boxes.flatMap((box) => (box.layers ?? []).map((layer) => layer.id));
}

export function videosOf(state, index) {
  const box = state.boxes[index], n = index + 1;
  return [{id: box.id, label: `${n} · main`, main: true},
    ...(box.layers ?? []).map((layer, i) => ({id: layer.id, label: `${n}${LETTERS[i]}`, main: false}))];
}

// Who is on screen from which frame to which: an incoming video is on screen from its swap frame on.
export function onScreenBars(box, frames) {
  const bars = [{id: box.id, start: 0, end: frames}];
  for (const cut of box.switch?.cuts ?? []) {
    bars.at(-1).end = cut.at;
    bars.push({id: cut.to, start: cut.at, end: frames});
  }
  return bars;
}

export function closingVideo(box, frames) {
  return onScreenBars(box, frames).findLast((bar) => bar.start <= frames - 1)?.id ?? box.id;
}

// The frames every video renders: a clip with several videos renders its time once per video.
export function renderFrames(state) {
  return state.boxes.reduce((sum, box, index) => sum + played(state, index) * (1 + (box.layers?.length ?? 0)), 0);
}

// The fade room of a swap: half the fade before it and half after, inside the clip, before its last frame.
function room(fade, frames) {
  return {lo: 1 + Math.floor(fade / 2), hi: Math.min(frames - Math.ceil(fade / 2), frames - 1), gap: Math.max(fade, 1)};
}

// Moves the swaps into the fade room and apart by the fade; whether they all fit there.
export function clampSwitch(state, index) {
  const sw = state.boxes[index].switch;
  if (!sw) return true;
  const cuts = Array.isArray(sw.cuts) ? sw.cuts : [];
  const {lo, hi, gap} = room(sw.fade, played(state, index));
  cuts.forEach((cut, i) => { cut.at = Math.max(Math.round(cut.at), i ? cuts[i - 1].at + gap : lo); });
  for (let i = cuts.length - 1; i >= 0; i -= 1) cuts[i].at = Math.min(cuts[i].at, i < cuts.length - 1 ? cuts[i + 1].at - gap : hi);
  return cuts.every((cut, i) => cut.at >= lo && cut.at <= hi && (!i || cut.at - cuts[i - 1].at >= gap));
}

export const SWAPS_DONT_FIT = 'The swaps no longer fit this length; move them apart or shorten the fade.';

// Whether clip `index`'s swaps fit its length and fade, without moving them.
export function switchFits(state, index) {
  const box = state.boxes[index];
  if (!box?.switch) return true;
  const boxes = [...state.boxes];
  boxes[index] = {...box, switch: structuredClone(box.switch)};
  return clampSwitch({...state, boxes}, index);
}

// The Timeline as video `id` of clip `index` renders it, as layers.view: the clip becomes a Cut that plays exactly its
// frames with the video's prompt, seed, endpoints and memory.
export function layerView(state, index, id) {
  const {layers, switch: _switch, ...clip} = state.boxes[index];
  const layer = layers?.find((item) => item.id === id);
  if (!layer) return state;
  const boxes = [...state.boxes];
  boxes[index] = {...clip, ...Object.fromEntries(LAYER_FIELDS.slice(1).map((key) => [key, layer[key]])),
    frames: played(state, index), exact: true, cut: true};
  return {...state, boxes};
}

export function addVideo(state, index) {
  const box = state.boxes[index];
  if ((box.layers?.length ?? 0) >= MAX_VIDEOS - 1) return null;
  const id = newId(state), frames = played(state, index);
  (box.layers ??= []).push({id, seed: box.seed, prompt: box.prompt, first: '', last: '', previews: [], memory: 'off',
    memories: [], dialogue: 'cues'});
  box.switch ??= {cuts: [], fade: DEFAULT_FADE, sound: 'screen'};
  const last = onScreenBars(box, frames).at(-1);
  box.switch.cuts.push({at: box.switch.cuts.length ? Math.round((last.start + last.end) / 2) : Math.round(frames / 2),
    to: id});
  clampSwitch(state, index);
  return id;
}

export function removeVideo(state, index, id) {
  const box = state.boxes[index];
  box.layers = (box.layers ?? []).filter((layer) => layer.id !== id);
  if (!box.layers.length) {
    delete box.layers;
    delete box.switch;
    return;
  }
  const sw = box.switch;
  let screen = box.id;
  sw.cuts = sw.cuts.filter((cut) => {
    if (cut.to === id || cut.to === screen) return false;
    screen = cut.to;
    return true;
  });
  if (sw.sound === id) sw.sound = 'screen';
  if (sw.align) {
    delete sw.align[id];
    if (!Object.keys(sw.align).length) delete sw.align;
  }
}

export function setSwap(state, index, cut, at) {
  const sw = state.boxes[index].switch, cuts = sw.cuts;
  const {lo, hi, gap} = room(sw.fade, played(state, index));
  const low = cut ? cuts[cut - 1].at + gap : lo, high = cut < cuts.length - 1 ? cuts[cut + 1].at - gap : hi;
  cuts[cut].at = Math.min(Math.max(Math.round(Number(at) || 0), low), high);
}

export function setFade(state, index, fade) {
  state.boxes[index].switch.fade = Math.min(Math.max(Math.round(Number(fade) || 0), 0), MAX_FADE);
  return clampSwitch(state, index);
}

export function setSound(state, index, sound) {
  state.boxes[index].switch.sound = sound;
}

// The question for the clip after stacked clip `index` when it continues it, as layers.continue_after words it.
// `adding` asks it before clip `index` gets its first other video.
export function continueAfterStack(state, index, adding = false) {
  if (!state.boxes[index] || (!adding && !state.boxes[index].layers?.length) || index + 1 >= state.boxes.length
    || isFresh(state, index + 1)) return '';
  return `Clip ${index + 2} continues from clip ${index + 1}. With several videos in clip ${index + 1}, `
    + `clip ${index + 2} must start with a Cut. Change it?`;
}
