import { promptShots } from './h3c_prompt_sections.mjs?v=1f35473e5668';
import { FPS, GRID, isFresh, limits, newId, newSeed } from './h3c_timeline_model.mjs?v=1dfc1612e462';
import {splitWindows} from './h3c_audio_windows.mjs?v=cdefbd77b246';

const number = (shot) => Number(/\d+/.exec(shot.label)[0]);
// A later shot's cut time in milliseconds of generated video (replay included), or null when it has none.
const start = (shot) => {
  const m = /^At (\d+):(\d{2})\.(\d{3}),/i.exec(shot.value);
  return m ? (Number(m[1]) * 60 + Number(m[2])) * 1000 + Number(m[3]) : null;
};
const prose = (text, fn) => text.split(/(<d>[\s\S]*?(?:<\/d>|$))/g)
  .map((part) => part.startsWith('<d>') ? part : fn(part)).join('');
const clock = (ms) => `${String(Math.floor(ms / 60000)).padStart(2, '0')}:`
  + `${String(Math.floor(ms / 1000) % 60).padStart(2, '0')}.${String(Math.round(ms) % 1000).padStart(3, '0')}`;
const shift = (text, ms) => prose(text, (part) => part.replace(/\b(\d+):(\d{2})\.(\d{3})\b/g,
  (_, m, s, f) => clock(Math.max(0, Number(m) * 60000 + Number(s) * 1000 + Number(f) - ms))));

// Round up to H3's grid (17k+5 fresh, 17k continuing): a split must not steal performance time.
const roundUp = (frames, fresh, context) => Math.max(limits(fresh, context).min,
  Math.ceil((frames - (fresh ? 5 : 0) - 1e-6) / GRID) * GRID + (fresh ? 5 : 0));

export function splitTiming(state, index, shotNumber, context) {
  const box = state.boxes[index];
  if (box.layers?.length) throw new Error('Split is not available on a clip with several videos.');
  const { shots } = promptShots(box.prompt);
  const at = shots.findIndex((s) => number(s) === shotNumber);
  if (at <= 0) throw new Error('Choose a shot after the first one.');
  if (new Set(shots.map(number)).size !== shots.length) throw new Error('Give each shot a unique number before splitting.');
  const ms = start(shots[at]);
  const fresh = isFresh(state, index), carry = fresh ? 0 : context;
  let cut = ms == null ? null : ms * FPS / 1000 - carry;
  // Replay timestamps are rounded to milliseconds, which may fall either side of the exact frame.
  if (carry && ms === Math.round(carry * 1000 / FPS)) cut = 0;
  if (cut == null || cut < 0 || (!carry && cut === 0) || cut >= box.frames) {
    throw new Error('Give this shot a cut timestamp inside the box’s new time (format: “At MM:SS.mmm,”).');
  }
  const times = shots.map((s, i) => i === 0 ? 0 : start(s));
  if (times.some((t, i) => t == null || (i && t <= times[i - 1]) || t * FPS / 1000 >= box.frames + carry)) {
    throw new Error('Every later shot needs an increasing cut timestamp inside this box before splitting.');
  }
  // The second half is a cut, so exact halves need no grid: each plays its own frames.
  if (box.exact) {
    const left = cut === 0 ? 0 : Math.min(Math.max(1, Math.round(cut)), box.frames - 1);
    return { at, ms, cut: left, carry, left, right: box.frames - left, added: 0 };
  }
  // Round up both halves: a split must not steal performance time to fit H3's frame grid.
  const left = cut === 0 ? 0 : roundUp(cut, fresh, context), right = roundUp(box.frames - cut, true, context);
  if (left > limits(fresh, context).max || right > limits(true, context).max) {
    throw new Error('This cut cannot fit both halves within H3’s clip limit.');
  }
  return { at, ms, cut, carry, left, right, added: left + right - box.frames };
}

// One half's prompt from the kept shots. `offset` (ms) is subtracted from timestamps and drops the first kept cut time.
function halfPrompt(parsed, kept, shared, offset, first, last, duration) {
  const { sections, style } = parsed;
  const fields = (key) => sections?.find((s) => s.key === key)?.fields ?? [];
  const body = (key) => fields(key).map((p) => p.value).join('\n') || 'N/A';
  const shotMap = new Map(kept.map((s, i) => [number(s), i + 1]));
  const renumberShots = (text) => prose(text, (part) => part.replace(/\[Shot \d+\](?:,\s*\[Shot \d+\])*/gi,
    (list) => [...list.matchAll(/\d+/g)].map((m) => shotMap.get(Number(m[0])))
      .filter(Boolean).map((n) => `[Shot ${n}]`).join(', ')));
  const scene = kept.map((s, i) => {
    let text = shift(s.value, offset);
    if (i === 0 && offset) text = text.replace(/^At \d+:\d+\.\d+, the camera cuts to (?:a new shot\.\s*)?/i, '')
      .replace(/^At \d+:\d+\.\d+,\s*/i, '');
    return `[Shot ${i + 1}] ${renumberShots(text)}`;
  }).join('\n');
  if (!sections) return [style, scene].filter(Boolean).join('\n');

  const sound = body('overall_soundscape'), music = body('non_diegetic_music');
  const definitions = fields('subject_definitions');
  function usedBy(text) {
    const chosen = new Set();
    for (let pass = 0; pass <= definitions.length; pass++) {
      for (const part of definitions) {
        // Audio roles describe their subject in the definition, rather than in every spoken line.
        const voice = /^@audio\d+$/.test(part.label) && /voice/.test(part.value)
          && [...chosen].some((label) => label.startsWith('<Subject ') && part.value.includes(label));
        if (!chosen.has(part.label) && (text.includes(part.label) || voice)) {
          chosen.add(part.label);
          text += ` ${part.value}`;
        }
      }
    }
    return chosen;
  }
  const common = [shared, style, sound, music].join('\n');
  const used = kept.map((s) => usedBy(`${common}\n${s.value}`));
  const selected = new Set(used.flatMap((set) => [...set]));
  const defs = definitions.filter((p) => selected.has(p.label));
  const retained = fields('retention_analysis').filter((p) => selected.has(p.label)).map((p) => {
    const where = used.flatMap((set, i) => set.has(p.label) ? [`[Shot ${i + 1}]`] : []);
    const value = p.value.replace(/^\s*\([^)]*\):/, (prefix) => prefix.includes('appears in')
      ? ` (appears in ${where.join(', ')}):` : renumberShots(prefix));
    return `${p.label} ${value.trim()}`;
  });
  let prompt;
  if (defs.length) {
    const types = ['reference generation'];
    if (first || last || defs.some((p) => /(?:first|last|key)[ -]frame/.test(p.value))) types.push('keyframe completion');
    if (defs.some((p) => /^@audio/.test(p.label) && /audio reuse/.test(p.value))) types.push('audio reuse');
    if (defs.some((p) => /^@audio/.test(p.label) && /voice|sound|music/.test(p.value))) types.push('audio reference');
    // The old summary describes the whole box and often lists all its cast. Rebuild it from these shots.
    prompt = `subject_definitions:\n${defs.map((p) => `${p.label} ${renumberShots(p.value)}`).join('\n')}\n\n`
      + `summary: [${types.join(' + ')}] ${kept.length} shot${kept.length === 1 ? '' : 's'} featuring ${defs.map((p) => p.label).join(', ')}.\n\n`
      + `retention_analysis:\n${retained.join('\n')}\n\ndetailed_description:\n${[style, scene].filter(Boolean).join('\n')}`;
  } else {
    // Native frame guides belong only to the appropriate half, never both through the old alignment header.
    const alignment = [first && `@${first} (from [Shot 1]) aligns with the 0.00-second mark`,
      last && `@${last} (from [Shot ${kept.length}]) aligns with the ${duration.toFixed(2)}-second mark`].filter(Boolean);
    prompt = (alignment.length ? `How the reference pictures align with the target video — ${alignment.join('; ')}.\n\n` : '')
      + `integrated_multimodal_description:\n${[style, scene].filter(Boolean).join('\n')}`;
  }
  prompt += `\n\noverall_soundscape: ${sound}\n\nnon_diegetic_music: ${music}`;
  const subjects = new Map(defs.filter((p) => p.label.startsWith('<Subject ')).map((p, i) => [p.label, `<Subject ${i + 1}>`]));
  const speakers = new Map();
  // Speaker order comes from the surviving dialogue, not the reference definitions.
  for (const m of scene.matchAll(/\((S\d+(?:,S\d+)*)\)/g)) {
    for (const id of m[1].split(',')) if (!speakers.has(id)) speakers.set(id, `S${speakers.size + 1}`);
  }
  return prose(prompt, (text) => text.replace(/<Subject \d+>/g, (tag) => subjects.get(tag) ?? tag)
    .replace(/\((S\d+(?:,S\d+)*)\)/g, (_, ids) => {
      const kept = ids.split(',').map((id) => speakers.get(id)).filter(Boolean);
      return kept.length ? `(${kept.join(',')})` : '';
    }));
}

export function splitBox(state, index, shotNumber, context) {
  const timing = splitTiming(state, index, shotNumber, context);
  const original = state.boxes[index], parsed = promptShots(original.prompt);
  const halves = [parsed.shots.slice(0, timing.at), parsed.shots.slice(timing.at)];
  const left = { ...structuredClone(original), frames: timing.left, last: '' };
  const right = { ...structuredClone(original), id: timing.left ? newId(state) : original.id,
    seed: newSeed(), frames: timing.right, cut: true, first: '' };
  if (timing.left) {
    delete right.new_scene;
    delete right.join;
  }
  // Each half renumbers its <Subject N> labels, so the cast no longer matches either, and its prompt is new text.
  for (const half of [left, right]) {
    delete half.cast;
    delete half.source;
  }
  for (const [side, box] of [left, right].entries()) {
    if (!box.frames) continue;
    const offset = side ? timing.ms : 0;
    box.prompt = halfPrompt(parsed, halves[side], state.prompt, offset, side || timing.carry ? '' : box.first,
      box.last, (box.frames + (side ? 0 : timing.carry)) / FPS);
    const shotMap = new Map(halves[side].map((s, i) => [number(s), i + 1]));
    // A saved guide can sit outside its named shot: partition by position.
    const boundary = timing.cut + (timing.carry ? 1 : 0);
    const last = box.frames - (side || !timing.carry ? 1 : 0);
    for (const key of ['plate_changes', 'plate_edits']) {
      if (!original[key]) continue;
      box[key] = original[key].filter(p => (p.frame >= boundary ? 1 : 0) === side)
        .map(p => ({...structuredClone(p), frame: p.frame - (side ? boundary : 0)}));
      if (!timing.left) {
        for (const item of original[key].filter(p => p.frame === 0)) {
          if (!box[key].some(p => p.slot === item.slot && p.frame === 0)) box[key].unshift(structuredClone(item));
        }
      }
    }
    box.previews = [];
    let orphan = halves[side].length;
    for (const preview of original.previews ?? []) {
      const belongs = preview.guide || !parsed.shots.some((s) => number(s) === preview.shot)
        ? (preview.frame >= boundary ? 1 : 0) === side : shotMap.has(preview.shot);
      if (!belongs) continue;
      const saved = structuredClone(preview);
      if (saved.target) {
        // A targeted record is found by its target, not a shot number: renumber the target with its shot.
        if (saved.target.kind === 'shot' && shotMap.has(saved.target.shot)) {
          const shot = shotMap.get(saved.target.shot);
          saved.target = shot === 1 ? { kind: 'first' } : { kind: 'shot', shot };
        }
      } else saved.shot = shotMap.get(preview.shot) ?? ++orphan;
      const rebase = (frame) => Math.max(0, Math.min(last, Math.round(frame - (side ? boundary : 0))));
      saved.frame = preview.frame === original.frames - (timing.carry ? 0 : 1) && side ? last : rebase(preview.frame);
      if (saved.target_frame != null) saved.target_frame = rebase(saved.target_frame);
      // A saved still whose shot is gone stays listed in the Shots tab, where it can be removed.
      box.previews.push(saved);
    }
    if (!box.previews.length) delete box.previews;
  }
  // At the replay boundary the preceding box already contains the entire left half.
  splitWindows(state, original.id, timing.left ? left.id : null, right.id, timing.cut / FPS);
  state.boxes.splice(index, 1, ...(timing.left ? [left, right] : [right]));
  return timing;
}
