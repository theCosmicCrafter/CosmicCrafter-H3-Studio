// Voice clips: sound files uploaded into the Timeline for a character's voice, in slots numbered after the node's
// three wired audio inputs. The Cast page gives each to a character, the Studio lists them among the audio
// references, and the node sends a clip whole to H3 in each box where its character speaks.
import * as model from './h3c_timeline_model.mjs?v=1dfc1612e462';

export const LONG_CLIP_SECONDS = 30;
const FIRST_SLOT = 4;

// The first slot from audio4 up that no clip holds and nothing in the Timeline names (a prompt, a character's clip
// or a reference switch), so a new clip never takes over a removed one's mentions.
export function freeVoiceSlot(state) {
  const used = new Set([...(state.voice_clips ?? []).map((clip) => clip.slot), ...(state.disabled_refs ?? [])]);
  for (const text of [state.prompt, ...state.boxes.map((box) => box.prompt)]) {
    for (const {name} of model.mentions(text)) used.add(name);
  }
  for (const entity of state.bible?.entities ?? []) if (entity.voice_clip) used.add(entity.voice_clip);
  let number = FIRST_SLOT;
  while (used.has(`audio${number}`)) number += 1;
  return `audio${number}`;
}

export function voiceClipOf(state, entity) {
  return (entity?.voice_clip && state.voice_clips?.find((clip) => clip.slot === entity.voice_clip)) || null;
}

export function setVoiceClip(state, slot, file) {
  state.voice_clips ??= [];
  const clip = state.voice_clips.find((item) => item.slot === slot);
  if (clip) clip.file = structuredClone(file);
  else state.voice_clips.push({slot, file: structuredClone(file)});
}

export function dropVoiceClip(state, slot) {
  state.voice_clips = (state.voice_clips ?? []).filter((clip) => clip.slot !== slot);
  if (state.disabled_refs) state.disabled_refs = state.disabled_refs.filter((name) => name !== slot);
}

// The clips as audio references, each titled by the character whose voice it is, or by its file name.
export function voiceRefs(state) {
  const owners = new Map((state.bible?.entities ?? []).filter((entity) => entity.voice_clip)
    .map((entity) => [entity.voice_clip, entity.name]));
  return (state.voice_clips ?? []).map((clip) => ({name: clip.slot,
    title: owners.has(clip.slot) ? `${owners.get(clip.slot)}’s voice` : clip.file.filename,
    file: clip.file.filename, mediaFile: clip.file}));
}
