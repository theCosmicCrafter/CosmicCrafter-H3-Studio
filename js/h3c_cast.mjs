import {ReferencePreparationPanel} from './h3c_reference_preparation.mjs?v=d05409662438';
// The Studio's Cast page: the Story bible's characters, places and props, and the boxes each appears in. Every change
// goes through the bible route, which compiles the prompts, and lands as one Timeline edit.
import * as model from './h3c_timeline_model.mjs?v=1dfc1612e462';
import { fillPicturePicker, referenceChip } from './h3c_reference_pictures.mjs?v=8198307be3fa';
import { LONG_CLIP_SECONDS, dropVoiceClip, freeVoiceSlot, setVoiceClip, voiceClipOf } from './h3c_voices.mjs?v=efb0f83d17e1';
import { drawsSame, setText } from './h3c_dom.mjs?v=584a9bf55653';

export const BUILD_SENTENCE = 'Build bible links each clip’s subjects to characters, places and props. Nothing that renders changes.';
const STALE = 'The Timeline changed while the bible was updating; try again.';
const STYLE_SAVED = 'Saved. Write uses the style in the clips it writes.';
const VOICE_SAVED = 'Saved. Write uses the voice in the clips it writes.';
const COMPILE_TITLE = 'Compile this wording into the clips where it is in force';
const SAVE_TITLE = 'Save it; clips written from the bible take it now, and Write uses it from now on';
const PROSE_NOTE = 'The Story’s writer is updating the prose; its progress is in the top bar.';
const LONG_CLIP = 'H3 hears the whole voice recording in every clip it’s sent to, so a shorter sample costs less memory and time.';
const KINDS = ['character', 'place', 'prop'];
const LOOK_COLORS = ['#3d5f8f', '#6b4f8f', '#3f7a5d', '#8f5f3d', '#8f3d62', '#5d7a3f', '#3d7a7a', '#7a3d3d'];
const STYLE_ID = 'h3cc-style';
const CSS = `
.h3cc-cast { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.h3cc-cast [hidden] { display: none !important; }
.h3cc-fieldset { display: flex; flex-direction: column; gap: 8px; min-width: 0; margin: 0; padding: 0; border: 0; }
.h3cc-note, .h3cc-intro { margin: 0; }
.h3cc-unlinked { margin: 0; padding-left: 18px; font-size: 12px; color: #aab1bd; }
.h3cc-list { display: flex; flex-direction: column; gap: 4px; }
.h3ct-button.h3cc-row { display: grid; grid-template-columns: 36px minmax(0, 1fr); column-gap: 8px; align-items: center;
  width: 100%; padding: 4px 8px 4px 4px; text-align: left; white-space: normal; }
.h3cc-row[aria-pressed="true"] { background: #293e60; border-color: #729cdd; }
.h3cc-thumb, .h3cc-mark { grid-row: 1 / span 2; width: 36px; height: 36px; border-radius: 4px; }
.h3cc-thumb { object-fit: cover; background: #181c25; }
.h3cc-mark { display: inline-flex; align-items: center; justify-content: center; background: #262b36; color: #aab1bd; }
.h3cc-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 600; }
.h3cc-meta { display: flex; flex-wrap: wrap; gap: 0 10px; min-width: 0; font-size: 12px; color: #aab1bd; }
.h3cc-differs { color: #f0c674; }
.h3cc-detail { display: flex; flex-direction: column; gap: 8px; padding: 8px; border: 1px solid #343a46; border-radius: 6px;
  background: rgba(0, 0, 0, .15); }
.h3cc-fields, .h3cc-pictures, .h3cc-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; min-width: 0; }
.h3cc-field { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.h3cc-fields .h3cc-field:first-child { flex: 1 1 180px; }
.h3cc-picture { display: inline-flex; align-items: center; gap: 4px; }
.h3cc-strip { display: flex; flex-wrap: wrap; gap: 3px; }
.h3ct-button.h3cc-cell { flex: 1 0 26px; max-width: 64px; height: 26px; padding: 0 2px; font-size: 11px; text-align: center; }
.h3ct-button.h3cc-cell.empty { background: transparent; border-style: dashed; color: #aab1bd; }
.h3ct-button.h3cc-cell.differs { background: #6b5317; border-color: #f0c674; color: #fff3d6; }
.h3cc-cell.selected { outline: 2px solid #8fbcff; outline-offset: 1px; }
.h3cc-look, .h3cc-differ { display: flex; flex-direction: column; gap: 4px; padding: 6px; border: 1px solid #343a46; border-radius: 4px; }
.h3cc-differ { border-color: #8a6d2c; }
.h3cc-line { margin: 0; overflow-wrap: anywhere; color: #f0dca8; }
.h3cc-chips { display: flex; flex-wrap: wrap; gap: 4px; min-width: 0; margin-bottom: 6px; }
.h3cc-chips:empty { display: none; }
.h3ct-button.h3cc-chip { max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.h3ct-button.h3cc-chip.differs { background: #6b5317; border-color: #f0c674; color: #fff3d6; }
.h3cc-chip.unlinked { display: inline-flex; align-items: center; gap: 6px; max-width: 100%; padding: 2px 3px 2px 8px;
  border: 1px dashed #5b6270; border-radius: 4px; background: #23272f; color: #c3c8d1; }
.h3cc-chip.scheduled { display: inline-flex; align-items: center; max-width: 100%; }
.h3cc-chip.scheduled .h3ct-button { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.h3cc-chip.scheduled .h3cc-chip-open { border-radius: 4px 0 0 4px; }
.h3cc-chip.scheduled .h3cc-chip-remove { flex: none; padding: 0 6px; border-left: 0; border-radius: 0 4px 4px 0; }
.h3cc-chip.scheduled.differs .h3ct-button { background: #6b5317; border-color: #f0c674; color: #fff3d6; }
.h3cc-chip-field { display: inline-flex; align-items: center; gap: 4px; }
.h3cc-edited, .h3cc-hint, .h3cc-offer .h3cc-where { align-self: center; font-size: 12px; color: #aab1bd; }
.h3cc-clip { min-width: 0; overflow-wrap: anywhere; }
.h3cc-voice-clip .h3cc-hint { align-self: flex-start; }
`;

function ensureStyle() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement('style');
  style.id = STYLE_ID;
  style.textContent = CSS;
  document.head.append(style);
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function button(label, title, onClick, className = '') {
  const node = el('button', `h3ct-button ${className}`.trim(), label);
  node.type = 'button';
  node.title = title;
  node.addEventListener('click', (event) => {
    event.preventDefault();
    onClick();
  });
  return node;
}

function option(value, label) {
  const node = el('option', null, label);
  node.value = value;
  return node;
}

function field(label, control) {
  const node = el('label', 'h3cc-field');
  node.append(el('span', 'h3ct-label', label), control);
  return node;
}

const numberOf = (boxes, id) => boxes.findIndex((box) => box.id === id) + 1;
const fileKey = (file) => JSON.stringify([file.type, file.subfolder ?? '', file.filename]);
const listed = (numbers) => numbers.length === 1 ? `clip ${numbers[0]}`
  : `clips ${numbers.slice(0, -1).join(', ')} and ${numbers.at(-1)}`;

export function boxRanges(numbers) {
  const sorted = [...new Set(numbers)].sort((a, b) => a - b);
  const parts = [];
  for (let start = 0; start < sorted.length; start += 1) {
    let end = start;
    while (end + 1 < sorted.length && sorted[end + 1] === sorted[end] + 1) end += 1;
    parts.push(end > start ? `${sorted[start]}–${sorted[end]}` : `${sorted[start]}`);
    start = end;
  }
  return parts.join(', ');
}

export function castRows(bible, view, boxes) {
  const subjects = view?.subjects ?? [];
  return (bible?.entities ?? []).map((entity) => {
    const mine = subjects.filter((item) => item.entity === entity.id && numberOf(boxes, item.box));
    return {id: entity.id, name: entity.name, kind: entity.kind, picture: entity.pictures?.[0] ?? null,
      boxes: boxRanges(mine.map((item) => numberOf(boxes, item.box))), looks: (entity.looks?.length ?? 0) + 1,
      differs: new Set(mine.filter((item) => item.state === 'differs').map((item) => item.box)).size};
  });
}

export function stripCells(entity, view, boxes) {
  const subjects = (view?.subjects ?? []).filter((item) => item.entity === entity.id);
  return boxes.map((box, index) => {
    const here = subjects.filter((item) => item.box === box.id);
    return {box: box.id, number: index + 1, look: here.length ? here[0].look : null,
      differs: here.some((item) => item.state === 'differs')};
  });
}

export function chipsFor(bible, view, boxes, boxId) {
  const known = new Map((bible?.entities ?? []).map((entity) => [entity.id, entity]));
  return (view?.subjects ?? []).filter((item) => item.box === boxId).map((item) => {
    const entity = known.get(item.entity);
    if (!entity) return {label: item.label, entity: null, text: `${item.label.slice(1, -1)} · not linked`, state: 'unlinked'};
    const look = item.look > 0 ? entity.looks?.[item.look - 1] : null;
    return {label: item.label, entity: entity.id, state: item.state,
      text: look ? `${entity.name} · from clip ${numberOf(boxes, look.from)}` : entity.name};
  });
}

export function noteFor(result, boxes) {
  const updated = Object.keys(result?.prompts ?? {}).length;
  const differing = [...new Set((result?.differs ?? []).map((item) => numberOf(boxes, item.box)).filter(Boolean))]
    .sort((a, b) => a - b);
  const left = differing.length
    ? `${listed(differing)} ${differing.length === 1 ? 'differs and was' : 'differ and were'} left alone.` : '';
  const text = updated ? `Updated ${updated} ${updated === 1 ? 'clip' : 'clips'}${left ? `; ${left}` : '.'}`
    : left ? `No prompt changed; ${left}` : 'Saved. No prompt changed.';
  return [text, ...(result?.notes ?? [])].join(' ');
}

// The prose update a Cast edit's answer calls for, for its first entity whose wording changed in a box with prose,
// or null.
export function proseOffer(answer, boxes) {
  const found = Object.entries(answer?.reworded ?? {}).find(([, wording]) => wording.length);
  if (!found) return null;
  const [entity, wording] = found;
  return {entity, wording, numbers: wording.map((item) => numberOf(boxes, item.box))};
}

function linkNote(result, boxes) {
  const casts = Object.entries(result?.casts ?? {});
  const linked = casts.reduce((sum, [, cast]) => sum + Object.keys(cast).length, 0);
  const left = (result?.unlinked ?? []).length;
  const where = listed(casts.map(([id]) => numberOf(boxes, id)).filter(Boolean).sort((a, b) => a - b));
  return `Linked ${linked} ${linked === 1 ? 'subject' : 'subjects'} in ${where}`
    + (left ? `; ${left} ${left === 1 ? 'is' : 'are'} not linked.` : '.');
}

// `text` with each picture mention that `swaps` ({from: to}) names going to its new picture.
function swapMentions(text, swaps) {
  return text.replace(/@(image\d+)/g, (mention, name) => swaps[name] ? `@${swaps[name]}` : mention);
}

export function replacePicture(entity, from, to) {
  const rename = (names) => [...new Set(names.map((name) => name === from ? to : name))];
  const swap = (text) => swapMentions(text, {[from]: to});
  return {...structuredClone(entity), pictures: rename(entity.pictures), description: swap(entity.description),
    looks: (entity.looks ?? []).map((look) => ({...structuredClone(look), description: swap(look.description),
      ...(look.pictures ? {pictures: rename(look.pictures)} : {})}))};
}

// The entity's pictures at box `index`: those of its latest look starting at or before the box that has pictures,
// else its own. A look whose box is missing has no effect.
export function picturesAt(entity, boxes, index) {
  let chosen = entity.pictures, start = -1;
  for (const look of (entity.looks ?? [])) {
    const at = boxes.findIndex((box) => box.id === look.from);
    if (look.pictures?.length && at >= 0 && start < at && at <= index) [chosen, start] = [look.pictures, at];
  }
  return [...chosen];
}

export function withLook(entity, boxId, description, boxes,
  pictures = (entity.looks ?? []).find((look) => look.from === boxId)?.pictures) {
  const order = (look) => {
    const index = boxes.findIndex((box) => box.id === look.from);
    return index < 0 ? boxes.length : index;
  };
  const look = pictures?.length ? {from: boxId, description, pictures: [...pictures]} : {from: boxId, description};
  const looks = [...(entity.looks ?? []).filter((item) => item.from !== boxId), look];
  return {...structuredClone(entity), looks: looks.sort((a, b) => order(a) - order(b))};
}

// The look from `boxId` showing `picture`, or no picture of its own when it is empty. Each look whose pictures in
// force change names the new pictures in place of the old, since Build bible's wording names its picture.
export function withLookPicture(entity, boxId, picture, boxes) {
  const looks = (entity.looks ?? []).map((look) => {
    const copy = structuredClone(look);
    if (look.from !== boxId) return copy;
    delete copy.pictures;
    return picture ? {...copy, pictures: [picture]} : copy;
  });
  const next = {...structuredClone(entity), looks};
  next.looks = looks.map((look) => {
    const index = boxes.findIndex((box) => box.id === look.from);
    if (index < 0) return look;
    const [before, after] = [picturesAt(entity, boxes, index), picturesAt(next, boxes, index)];
    const swaps = Object.fromEntries(before.map((name, k) => [name, after[k]]).filter(([name, to]) => to && to !== name));
    return {...look, description: swapMentions(look.description, swaps)};
  });
  return next;
}

export function withoutLook(entity, boxId) {
  return {...structuredClone(entity), looks: (entity.looks ?? []).filter((look) => look.from !== boxId)};
}

// `entity` with the pin {box, frame} last, unless it has that pin.
export function withPin(entity, boxId, frame) {
  const pins = structuredClone(entity.pins ?? []);
  if (!pins.some((pin) => pin.box === boxId && pin.frame === frame)) pins.push({box: boxId, frame});
  return {...structuredClone(entity), pins};
}

// `entity` without the first pin equal to `pin`.
export function withoutPin(entity, pin) {
  const pins = structuredClone(entity.pins ?? []);
  const at = pins.findIndex((item) => item.box === pin.box && item.frame === pin.frame);
  if (at >= 0) pins.splice(at, 1);
  return {...structuredClone(entity), pins};
}

export function mergeLinks(view, from, into) {
  const subjects = view?.subjects ?? [];
  const links = {};
  for (const item of subjects.filter((subject) => subject.entity === from)) {
    const taken = subjects.some((other) => other.box === item.box && other.entity === into);
    (links[item.box] ??= {})[item.label] = taken ? null : into;
  }
  return links;
}

const labelNumber = (label) => Number(/\d+/.exec(label)?.[0] ?? 0);

// The box's schedule, or for a box without one, its linked entities in label order with the first linked place as
// its place.
export function scheduleFor(box, bible) {
  if (box.schedule) return structuredClone(box.schedule);
  const known = new Map((bible?.entities ?? []).map((entity) => [entity.id, entity]));
  const linked = Object.entries(box.cast ?? {}).sort(([a], [b]) => labelNumber(a) - labelNumber(b))
    .map(([, id]) => known.get(id)).filter(Boolean);
  return {entities: [...new Set(linked.filter((entity) => entity.kind !== 'place').map((entity) => entity.id))],
    place: linked.find((entity) => entity.kind === 'place')?.id ?? null};
}

// `schedule` without entity `id`, or with `into` in its place; no entity appears twice.
export function scheduleWithout(schedule, id, into = null) {
  const swap = (name) => (name === id ? into : name);
  return {entities: [...new Set(schedule.entities.map(swap).filter(Boolean))], place: swap(schedule.place)};
}

// `bible` with its style's look set to the trimmed `text`, or without `style` when `text` is empty.
export function withStyle(bible, text) {
  const {style, ...rest} = structuredClone(bible);
  const look = text.trim();
  return look ? {...rest, style: {look}} : rest;
}

// `entity` with its voice set to the trimmed `text`, or without `voice` when `text` is empty.
export function withVoice(entity, text) {
  const {voice, ...rest} = structuredClone(entity);
  const value = text.trim();
  return value ? {...rest, voice: value} : rest;
}

export class CastPage {
  constructor(editor) {
    ensureStyle();
    this.editor = editor;
    this.view = null;
    this.selectedId = null;
    this.note = '';
    this.offer = null;
    this.unlinked = [];
    this.drafts = new Map();
    this.replacing = null;
    this.choosingLook = null;
    this.lengths = new Map();
    this.playing = null;
    this.busy = false;
    this.refreshing = false;
    this.timer = null;
    this.asked = 0;
    this.root = el('div', 'h3cc-cast');
    this.noteEl = el('p', 'h3cc-note');
    this.noteEl.setAttribute('aria-live', 'polite');
    this.fieldset = el('fieldset', 'h3cc-fieldset');
    this.root.append(this.noteEl, this.fieldset);
    this.preparation=editor.host.referenceCatalog?new ReferencePreparationPanel(editor):null;
    if(this.preparation)this.root.prepend(this.preparation.root);
  }

  destroy() {
    this.preparation?.destroy();
    clearTimeout(this.timer);
    this.timer = null;
    this.stopPlaying();
  }

  // The status of the current Timeline, unless it changes before the answer comes. With `link`, boxes without a cast,
  // as Write leaves them, are linked first as one edit. Refreshes after a change or a load (ComfyUI's Undo) don't
  // link, or Undo could never get past a link.
  async refresh({link = true} = {}) {
    clearTimeout(this.timer);
    this.timer = null;
    if (!this.editor.state.bible) {
      this.view = null;
      this.render();
      return;
    }
    const text = model.serialize(this.editor.state);
    const asked = ++this.asked;
    this.refreshing = true;
    let answer;
    try {
      answer = await this.editor.host.bible({action: 'status', timeline: JSON.parse(text)});
    } catch (error) {
      answer = {ok: false, error: error.message};
    }
    if (asked !== this.asked) return;
    this.refreshing = false;
    if (!answer?.ok) this.note = answer?.error ?? 'The bible’s status could not be read.';
    else if (model.serialize(this.editor.state) === text) {
      this.view = answer;
      if (link && answer.unlinked_boxes?.length && !this.busy) {
        await this.change({action: 'link', plan: this.editor.host.storyPlan?.() ?? null, boxes: answer.unlinked_boxes},
          {link: true});
        return;
      }
    }
    this.render();
  }

  changed() {
    this.preparation?.refresh();
    this.offer = null;
    this.render();
    clearTimeout(this.timer);
    this.timer = null;
    if (!this.editor.state.bible) {
      this.view = null;
      return;
    }
    this.timer = setTimeout(() => this.refresh({link: false}), 300);
  }

  open(entityId) {
    this.selectedId = entityId;
    this.render();
    this.root.dispatchEvent(new CustomEvent('h3c-show-page', {bubbles: true, detail: {page: 'cast'}}));
  }

  // Changes

  // Sends `body` with the current Timeline; the answer lands as one edit unless a box it changes, or the bible,
  // changed while it was computed. Returns whether it landed.
  async change(body, {build = false, link = false, clear = [], without = null, note = null} = {}) {
    if (this.busy || this.editor.readOnly?.length) return false;
    this.offer = null;
    const state = this.editor.state;
    const sentPrompts = new Map(state.boxes.map((box) => [box.id, box.prompt]));
    const sentBible = JSON.stringify(state.bible ?? null);
    const timeline = JSON.parse(model.serialize(state));
    const sentText=model.serialize(state), revision=this.editor.editRevision??0;
    this.busy = true;
    this.unlinked = [];
    this.render();
    let answer;
    try {
      answer = await this.editor.host.bible({...body, timeline});
    } catch (error) {
      answer = {ok: false, error: error.message};
    }
    this.busy = false;
    const now = this.editor.state;
    const find = (id) => now.boxes.find((box) => box.id === id);
    const touched = [...Object.keys(answer?.prompts ?? {}), ...Object.keys(answer?.casts ?? {}),
      ...Object.keys(answer?.sources ?? {})];
    if (!answer?.ok) this.note = answer?.error ?? 'The bible could not be updated.';
    else if ((body.action==='assign' && (this.editor.editRevision!==undefined&&this.editor.editRevision!==revision
        ||this.editor.promptForm?.hasDrafts()||model.serialize(now)!==sentText)) || JSON.stringify(now.bible ?? null) !== sentBible || touched.some((id) => find(id)?.prompt !== sentPrompts.get(id))) {
      this.note = STALE;
    } else {
      if(body.action==='assign') {
        if(answer.changed===false) {this.editor.promptForm?.focusSubject(answer.subject);return true;}
        const index=now.boxes.findIndex(b=>b.id===body.box),entity=now.bible.entities.find(e=>e.id===body.entity);
        const pictures=picturesAt(entity,now.boxes,index);
        const refs=this.editor.referenceOptions?.();
        const problem=refs&&pictures.find(name=>!model.referenceEnabled(now,name)||!refs.some(ref=>ref.name===name&&!ref.problem&&!ref.conflict));
        if(problem){this.note=`${problem} is missing, disabled or conflicting. Fix it before adding Cast.`;this.render();return false;}
        if(this.editor.connectedSets) {
          const trial=structuredClone(now);trial.boxes[index].prompt=answer.prompts[body.box];
          const before=model.describeBox(now,index,this.editor.connectedSets(),this.editor.host.context()).problems;
          const problems=model.describeBox(trial,index,this.editor.connectedSets(),this.editor.host.context()).problems.filter(p=>!before.includes(p));
          if(problems.length){this.note=problems.join(' ');this.render();return false;}
        }
      }
      for (const key of clear) this.drafts.delete(key);
      this.note = note && !Object.keys(answer.prompts ?? {}).length ? note
        : build ? answer.summary : link ? linkNote(answer, now.boxes) : noteFor(answer, now.boxes);
      if (build) this.unlinked = answer.unlinked ?? [];
      if (!build || answer.bible) {
        if ('bible' in answer) now.bible = answer.bible;
        for (const [id, cast] of Object.entries(answer.casts ?? {})) find(id).cast = cast;
        for (const [id, prompt] of Object.entries(answer.prompts ?? {})) find(id).prompt = prompt;
        for (const [id, schedule] of Object.entries(answer.schedules ?? {})) find(id).schedule = schedule;
        for (const [id, source] of Object.entries(answer.sources ?? {})) {
          if (source === null) delete find(id).source;
          else find(id).source = source;
        }
        if (without) {
          for (const box of now.boxes) if (box.schedule) box.schedule = scheduleWithout(box.schedule, ...without);
        }
        this.editor.commit();
        // A voice clip's card follows its character; the editor's commit() leaves the reference cards as they were.
        this.editor.renderRefmods();
        this.editor.host.undoStep?.();
        if(body.action==='assign') this.editor.promptForm?.focusSubject(answer.subject);
        if (body.action === 'apply') {
          this.offer = proseOffer(answer, now.boxes);
          this.render();
        }
        return true;
      }
    }
    this.render();
    return false;
  }

  // Asks the Story's writer to update the text the offer names; the revision runs and lands through the Story.
  async updateProse() {
    const {entity, wording} = this.offer;
    this.offer = null;
    this.render();
    try {
      await this.editor.host.editStory({kind: 'bible', entity, wording});
      this.note = PROSE_NOTE;
    } catch (error) {
      this.note = error.message;
    }
    this.render();
  }

  build() {
    return this.change({action: 'build', plan: this.editor.host.storyPlan?.() ?? null}, {build: true});
  }

  applyEntity(next, options) {
    const bible = this.editor.state.bible;
    return this.change({action: 'apply', bible: {...structuredClone(bible),
      entities: bible.entities.map((item) => item.id === next.id ? next : structuredClone(item))}}, options);
  }

  // What box `index` can pin: its scheduled characters, then its place. Nothing remembers props.
  pinTargets(index) {
    const {bible, boxes} = this.editor.state;
    if (!bible || !boxes[index]) return [];
    const schedule = scheduleFor(boxes[index], bible);
    const known = new Map((bible.entities ?? []).map((entity) => [entity.id, entity]));
    const characters = schedule.entities.map((id) => known.get(id)).filter((entity) => entity?.kind === 'character');
    const place = known.get(schedule.place);
    return [...characters, ...(place ? [place] : [])].map(({id, name}) => ({id, name}));
  }

  // Pins `seconds` into box `boxId`'s take for entity `entityId`, as one Cast edit. Returns whether it landed.
  async pin(entityId, boxId, seconds) {
    const {bible, boxes} = this.editor.state;
    const at = boxes.findIndex((box) => box.id === boxId);
    const entity = bible?.entities?.find((item) => item.id === entityId);
    if (at < 0 || !entity) return false;
    const frame = Math.min(Math.max(Math.round(seconds * model.FPS), 0), boxes[at].frames - 1);
    return this.applyEntity(withPin(entity, boxId, frame),
      {note: `Pinned clip ${at + 1} at ${model.seconds(frame)} s for ${entity.name}.`});
  }

  // The kept entity keeps its own voice clip, or takes the merged one's when it is a character without one; any other
  // clip leaves the Timeline.
  async merge(entity, into) {
    const bible = this.editor.state.bible;
    const rest = {...structuredClone(bible), entities: structuredClone(bible.entities.filter((item) => item.id !== entity.id))};
    const kept = rest.entities.find((item) => item.id === into);
    const passed = entity.voice_clip && kept?.kind === 'character' && !kept.voice_clip;
    if (passed) kept.voice_clip = entity.voice_clip;
    const edit = () => this.change({action: 'apply', bible: rest, links: mergeLinks(this.view, entity.id, into),
      merged: {[entity.id]: into}}, {without: [entity.id, into]});
    if (await (entity.voice_clip && !passed ? this.voiceEdit((state) => dropVoiceClip(state, entity.voice_clip), edit)
      : edit())) {
      this.selectedId = into;
      this.render();
    }
  }

  remove(entity) {
    const bible = this.editor.state.bible;
    const links = {};
    for (const item of this.view?.subjects ?? []) {
      if (item.entity === entity.id) (links[item.box] ??= {})[item.label] = null;
    }
    const edit = () => this.change({action: 'apply', bible: {...structuredClone(bible),
      entities: structuredClone(bible.entities.filter((item) => item.id !== entity.id))}, links}, {without: [entity.id]});
    return entity.voice_clip ? this.voiceEdit((state) => dropVoiceClip(state, entity.voice_clip), edit) : edit();
  }

  // A character that becomes a place or a prop leaves its voice clip.
  setKind(entity, kind) {
    const next = {...structuredClone(entity), kind};
    if (kind === 'character' || !entity.voice_clip) return this.applyEntity(next);
    delete next.voice_clip;
    return this.voiceEdit((state) => dropVoiceClip(state, entity.voice_clip), () => this.applyEntity(next));
  }

  // A Cast edit that also changes the Timeline's voice clips: `prepare(state)` changes them before `edit()` sends the
  // Timeline, so they land in its one Timeline edit; when it doesn't land, they and the reference switches go back.
  async voiceEdit(prepare, edit) {
    this.stopPlaying();
    const state = this.editor.state;
    const saved = {voice_clips: structuredClone(state.voice_clips), disabled_refs: structuredClone(state.disabled_refs)};
    prepare(state);
    let landed = false;
    try {
      landed = await edit();
    } finally {
      if (!landed) {
        for (const [key, value] of Object.entries(saved)) {
          if (value === undefined) delete state[key];
          else state[key] = value;
        }
        this.render();
      }
    }
    return landed;
  }

  // Upload… or a file dropped on a character's Voice clip row. The file is uploaded and read first, and a failure
  // shows its reason with nothing changed; then the character's slot, or the first free one, takes the file.
  async uploadClip(entity, file) {
    if (this.busy) return false;
    this.busy = true;
    this.note = 'Uploading the voice clip…';
    this.render();
    let upload = null;
    try {
      upload = await this.editor.host.uploadAudio(file);
    } catch (error) {
      this.note = error.message;
    }
    this.busy = false;
    const now = upload && this.entityNow(entity.id);
    if (!now) {
      if (upload) this.note = `${entity.name} was deleted while the clip was uploading.`;
      this.render();
      return false;
    }
    this.lengths.set(fileKey(upload.file), upload.duration);
    const slot = now.voice_clip ?? freeVoiceSlot(this.editor.state);
    return this.voiceEdit((state) => setVoiceClip(state, slot, upload.file),
      () => this.applyEntity({...structuredClone(now), voice_clip: slot}));
  }

  removeClip(entity) {
    const {voice_clip: slot, ...rest} = structuredClone(entity);
    return this.voiceEdit((state) => dropVoiceClip(state, slot), () => this.applyEntity(rest));
  }

  // Box `boxId` compiled from its source and the bible, dropping the hand edits, as one Timeline edit.
  recompile(boxId) {
    return this.change({action: 'recompile', boxes: [boxId]});
  }

  // Saves box `boxId`'s schedule as one Timeline edit.
  saveSchedule(boxId, schedule) {
    const box = this.editor.state.boxes.find((item) => item.id === boxId);
    if (!box || this.busy) return;
    box.schedule = schedule;
    this.editor.commit();
  }

  async addToClip(boxId,entityId) {
    if(this.editor.promptDraftsReady?.()===false)return false;
    if(this.editor.pickedLayer?.())this.editor.pick(boxId);
    return this.change({action:'assign',box:boxId,entity:entityId});
  }

  // Rendering

  pictures() {
    return this.editor.referenceOptions().filter((ref) => ref.name.startsWith('image'));
  }

  // The wording in force at box `index`, as the last status gave it.
  wordingAt(entity, index) {
    const look = this.view?.in_force?.[entity.id]?.[index] ?? 0;
    return look ? (entity.looks ?? [])[look - 1]?.description ?? entity.description : entity.description;
  }

  // Box `boxId`'s subjects as chips for the Box page: a linked chip opens its entity, an unlinked one offers Link….
  // With a schedule, the chips show its entities instead, each with ×, then Add… and Place; without one, Add… starts
  // one from the linked entities. A box whose prompt is no longer what its source compiles to starts with
  // "Edited by hand" and Recompile from source.
  chips(boxId) {
    const bible = this.editor.state.bible;
    const box = this.editor.state.boxes.find((item) => item.id === boxId);
    if (!bible || !box) return [];
    const names = new Map(bible.entities.map((entity) => [entity.id, entity.name]));
    const found = chipsFor(bible, this.view, this.editor.state.boxes, boxId);
    const unlinked = (chip) => this.unlinkedChip(chip, bible, boxId);
    const edited = this.view?.sources?.[boxId] === 'edited' ? this.editedChips(boxId) : [];
    if (!box.schedule) {
      return [...edited, ...found.map((chip) => (chip.entity ? this.linkedChip(chip, names) : unlinked(chip))),
        this.scheduleAdd(box)];
    }
    const linked = new Map(found.filter((chip) => chip.entity).map((chip) => [chip.entity, chip]));
    return [...edited, ...box.schedule.entities.filter((id) => names.has(id))
      .map((id) => this.scheduledChip(box, id, linked.get(id), names)),
    this.scheduleAdd(box), this.schedulePlace(box), ...found.filter((chip) => !chip.entity).map(unlinked)];
  }

  editedChips(boxId) {
    const recompile = button('Recompile from source',
      'Compile this clip again from the writer’s reply and the bible; your edits to its prompt are dropped',
      () => this.recompile(boxId), 'h3cc-chip');
    recompile.dataset.key = 'recompile';
    recompile.disabled = this.busy;
    return [el('span', 'h3cc-edited', 'Edited by hand'), recompile];
  }

  linkedChip(chip, names) {
    const differs = chip.state === 'differs';
    const node = button('', differs ? `This line differs from the bible; open ${names.get(chip.entity)} to resolve it`
      : `Open ${names.get(chip.entity)} on the Cast page`, () => this.open(chip.entity), 'h3cc-chip');
    node.classList.toggle('differs', differs);
    node.append(el('span', 'h3cc-chip-text', chip.text));
    return node;
  }

  unlinkedChip(chip, bible, boxId) {
    const node = el('span', 'h3cc-chip unlinked');
    const link = el('select', 'h3ct-select');
    link.setAttribute('aria-label', `Link ${chip.label} to an entity`);
    link.append(option('', 'Link…'), ...bible.entities.map((entity) => option(entity.id, entity.name)),
      option('new', 'New entity from this line'));
    link.disabled = this.busy;
    link.addEventListener('change', () => {
      if (link.value) this.change({action: 'apply', bible, links: {[boxId]: {[chip.label]: link.value}}});
    });
    node.append(el('span', 'h3cc-chip-text', chip.text), link);
    return node;
  }

  scheduledChip(box, id, chip, names) {
    const name = names.get(id);
    const node = el('span', 'h3cc-chip scheduled');
    node.classList.toggle('differs', chip?.state === 'differs');
    const open = button('', chip?.state === 'differs' ? `This line differs from the bible; open ${name} to resolve it`
      : `Open ${name} on the Cast page`, () => this.open(id), 'h3cc-chip-open');
    open.append(el('span', 'h3cc-chip-text', chip?.text ?? name));
    const remove = button('×', `Remove ${name} from schedule; prompt text stays in place`, () => this.saveSchedule(box.id,
      scheduleWithout(box.schedule, id)), 'h3cc-chip-remove');
    remove.setAttribute('aria-label', `Remove ${name} from this clip`);
    remove.dataset.key = `schedule-remove-${id}`;
    remove.disabled = this.busy;
    node.append(open, remove);
    return node;
  }

  // Add… lists the characters and props not yet in the box's schedule.
  scheduleAdd(box) {
    const bible = this.editor.state.bible;
    const schedule = scheduleFor(box, bible);
    const choices = bible.entities.filter((entity) => entity.kind !== 'place' &&
      (!schedule.entities.includes(entity.id)||!Object.values(box.cast??{}).includes(entity.id)));
    const add = el('select', 'h3ct-select');
    add.dataset.key = 'schedule-add';
    add.title = 'Add a character or prop to who is in this clip';
    add.setAttribute('aria-label', 'Add from Cast');
    add.append(option('', 'Add from Cast'), ...choices.map((entity) => option(entity.id, entity.name)));
    add.disabled = this.busy || !choices.length;
    add.addEventListener('change', () => {
      if (add.value) this.addToClip(box.id,add.value);
    });
    return add;
  }

  schedulePlace(box) {
    const place = el('select', 'h3ct-select');
    place.dataset.key = 'schedule-place';
    place.setAttribute('aria-label', 'Where this clip takes place');
    place.append(option('', 'No place'), ...this.editor.state.bible.entities.filter((entity) => entity.kind === 'place')
      .map((entity) => option(entity.id, entity.name)));
    place.value = box.schedule.place ?? '';
    place.disabled = this.busy;
    place.addEventListener('change', () => place.value?this.addToClip(box.id,place.value):this.saveSchedule(box.id,{...box.schedule,place:null}));
    const node = el('label', 'h3cc-chip-field');
    node.append(el('span', 'h3ct-label', 'Place'), place);
    return node;
  }

  render() {
    const active = this.root.contains(document.activeElement) ? document.activeElement : null;
    const focused = active?.dataset.key ?? null;
    const range = active && typeof active.selectionStart === 'number' ? [active.selectionStart, active.selectionEnd] : null;
    const bible = this.editor.state.bible ?? null;
    setText(this.noteEl, this.note);
    this.noteEl.hidden = !this.note;
    this.fieldset.disabled = this.busy;
    const parts = [];
    if (!bible) {
      parts.push(el('p', 'h3cc-intro', BUILD_SENTENCE), this.unlinkedList(), el('div', 'h3cc-actions'));
      parts.at(-1).append(button('Build bible', 'Link each clip’s subjects to characters, places and props; no prompt changes',
        () => this.build(), 'h3ct-primary'));
    } else {
      const entities = bible.entities ?? [];
      if (!entities.some((item) => item.id === this.selectedId)) this.selectedId = entities[0]?.id ?? null;
      const selected = entities.find((item) => item.id === this.selectedId);
      parts.push(this.offerRow(bible), this.unlinkedList(), this.styleRow(bible), this.list(bible));
      if (selected) parts.push(this.detail(selected, bible));
    }
    // The controls' listeners hold the state they were drawn from; while it is the same, equal markup keeps them.
    const drawn = parts.filter(Boolean), from = [this.editor.state, bible, this.offer, this.view];
    if (from.every((item, index) => item === this.drawnFrom?.[index]) && drawsSame(this.fieldset, drawn)) {
      this.editor.renderCastChips();
      return;
    }
    this.drawnFrom = from;
    this.fieldset.replaceChildren(...drawn);
    const again = focused && [...this.fieldset.querySelectorAll('[data-key]')].find((node) => node.dataset.key === focused);
    if (again && !this.busy) {
      again.focus();
      if (range && typeof again.setSelectionRange === 'function') again.setSelectionRange(...range);
    }
    this.editor.renderCastChips();
  }

  // While a Story is linked, the prose update the last Cast edit calls for.
  offerRow(bible) {
    const story = this.editor.host.story?.();
    if (!this.offer || !story) return null;
    const name = bible.entities.find((item) => item.id === this.offer.entity)?.name ?? this.offer.entity;
    const where = listed(this.offer.numbers);
    const update = button('Update prose with the writer',
      `Ask the Story’s writer to update the text in ${where} that still describes ${name} the old way`,
      () => this.updateProse(), 'h3ct-primary');
    update.disabled = !!story.job;
    const row = el('div', 'h3cc-actions h3cc-offer');
    row.append(update, el('span', 'h3cc-where', `Sends ${where}`));
    return row;
  }

  unlinkedList() {
    if (!this.unlinked.length) return null;
    const list = el('ul', 'h3cc-unlinked');
    const boxes = this.editor.state.boxes;
    for (const item of this.unlinked) {
      const entry = el('li', null, `Clip ${numberOf(boxes, item.box) || '?'} · ${item.label}: ${item.why}`);
      entry.title = item.line;
      list.append(entry);
    }
    return list;
  }

  thumbnail(picture) {
    const ref = this.pictures().find((item) => item.name === picture);
    if (!ref?.preview) return el('span', 'h3cc-mark', '◇');
    const image = el('img', 'h3cc-thumb');
    image.alt = '';
    image.src = ref.preview;
    return image;
  }

  list(bible) {
    const list = el('div', 'h3cc-list');
    for (const row of castRows(bible, this.view, this.editor.state.boxes)) {
      const item = button('', `Show ${row.name}`, () => {
        this.selectedId = row.id;
        this.replacing = null;
        this.choosingLook = null;
        this.render();
      }, 'h3cc-row');
      item.dataset.entity = row.id;
      item.setAttribute('aria-pressed', String(row.id === this.selectedId));
      const meta = el('span', 'h3cc-meta');
      meta.append(el('span', 'h3cc-kind', row.kind));
      if (row.boxes) meta.append(el('span', 'h3cc-where', `${/[,–]/.test(row.boxes) ? 'clips' : 'clip'} ${row.boxes}`));
      if (row.looks > 1) meta.append(el('span', 'h3cc-looks', `${row.looks} looks`));
      if (row.differs) meta.append(el('span', 'h3cc-differs', `${row.differs} differ${row.differs === 1 ? 's' : ''}`));
      item.append(this.thumbnail(row.picture), el('span', 'h3cc-name', row.name), meta);
      list.append(item);
    }
    return list;
  }

  styleRow(bible) {
    const [text, apply] = this.draft('bible|style', bible.style?.look ?? '', 2, 'Style of every clip',
      (value) => this.change({action: 'apply', bible: withStyle(this.editor.state.bible, value)},
        {clear: ['bible|style'], note: STYLE_SAVED}), 'style-apply', SAVE_TITLE);
    text.placeholder = 'The look every clip shares, such as the medium, light and colour';
    const row = el('div', 'h3cc-field h3cc-bible-style');
    row.append(el('span', 'h3ct-label', 'Style'), text, apply);
    return row;
  }

  // A text control that keeps its draft across renders; Esc puts the saved text back.
  draft(key, saved, rows, label, onApply, applyKey, title = COMPILE_TITLE) {
    const area = el('textarea', 'h3ct-text');
    area.rows = rows;
    area.dataset.key = key.split('|')[1];
    area.setAttribute('aria-label', label);
    area.value = this.drafts.get(key) ?? saved;
    const apply = button('Apply', title, () => onApply(area.value), 'h3ct-primary');
    apply.dataset.key = applyKey;
    apply.hidden = area.value === saved;
    area.addEventListener('input', () => {
      if (area.value === saved) this.drafts.delete(key);
      else this.drafts.set(key, area.value);
      apply.hidden = area.value === saved;
    });
    area.addEventListener('keydown', (event) => {
      if (event.key !== 'Escape') return;
      this.drafts.delete(key);
      area.value = saved;
      apply.hidden = true;
    });
    return [area, apply];
  }

  // The picture of the look from box `at`, or the hint when its boxes keep another one, and the picker to choose it.
  lookPicture(entity, look, at, images) {
    const boxes = this.editor.state.boxes;
    const shown = look.pictures?.[0] ?? '';
    const part = el('div', 'h3cc-pictures h3cc-look-picture');
    if (shown) part.append(referenceChip(images.find((ref) => ref.name === shown) ?? {name: shown, missing: true}));
    else if (picturesAt(entity, boxes, at - 1).length) {
      part.append(el('span', 'h3cc-hint', `No picture: these clips keep ${entity.name}'s picture and say the change in words.`));
    }
    const choose = button('Picture…', 'Choose the picture that shows this look', () => {
      this.choosingLook = this.choosingLook === look.from ? null : look.from;
      this.render();
    });
    choose.dataset.key = `look-picture:${look.from}`;
    part.append(choose);
    if (this.choosingLook !== look.from) return [part];
    const picker = el('div', 'h3cc-picker');
    fillPicturePicker(picker, {value: shown, refs: images, none: true, label: `Picture for the look from clip ${at}`},
      (value) => {
        this.choosingLook = null;
        if (value !== shown) this.applyEntity(withLookPicture(entity, look.from, value, boxes));
        else this.render();
      });
    const upload = this.uploadInto('Upload a picture into the Timeline and make it the picture of this look', (slot) => {
      this.choosingLook = null;
      const now = this.entityNow(entity.id);
      return now?.looks.some((item) => item.from === look.from)
        ? this.applyEntity(withLookPicture(now, look.from, slot, this.editor.state.boxes)) : false;
    });
    return [part, picker, upload];
  }

  entityNow(id) {
    return this.editor.state.bible?.entities?.find((item) => item.id === id);
  }

  // Upload… after a picture picker: the uploaded picture rides in the bible edit `edit(slot)` makes, and leaves again
  // when that edit doesn't land.
  uploadInto(title, edit) {
    const row = el('div', 'h3cc-actions h3cc-upload');
    row.append(button('Upload…', title, () => this.editor.pictures.addTo(edit, (text) => {
      if (!text) return;
      this.note = text;
      this.render();
    })));
    return row;
  }

  // The entity's pins, newest first; a pin whose box is gone, or that is past its box's end, has no effect.
  pinList(entity) {
    const boxes = this.editor.state.boxes;
    const list = el('div', 'h3cc-field h3cc-pins');
    list.append(el('span', 'h3ct-label', 'Pinned moments'));
    for (const pin of [...entity.pins ?? []].reverse()) {
      const at = numberOf(boxes, pin.box);
      const lost = !at || pin.frame >= boxes[at - 1].frames;
      const remove = button('Remove', 'Remove this pinned moment', () => this.applyEntity(withoutPin(entity, pin)));
      remove.dataset.key = `pin-remove:${pin.box}:${pin.frame}`;
      const row = el('div', 'h3cc-actions h3cc-pin');
      row.append(el('span', null, `Clip ${at || 'missing'} · ${model.seconds(pin.frame)} s${lost ? ' · has no effect' : ''}`),
        remove);
      list.append(row);
    }
    if (!entity.pins?.length) {
      list.append(el('span', 'h3cc-hint', 'None yet. Pause a clip’s take in the Studio and use Pin for… to remember '
        + `how ${entity.name} looks there.`));
    }
    return list;
  }

  // The clip's length in seconds, from its upload or asked once per file; null until it is known.
  clipLength(file) {
    const key = fileKey(file);
    if (!this.lengths.has(key)) {
      this.lengths.set(key, null);
      this.editor.host.audioInfo?.(file)?.then((info) => {
        if (!Number.isFinite(info?.duration)) return;
        this.lengths.set(key, info.duration);
        this.render();
      }, () => {});
    }
    return this.lengths.get(key);
  }

  togglePlay(clip) {
    const same = this.playing?.slot === clip.slot;
    this.stopPlaying();
    if (!same) {
      const audio = new Audio(this.editor.host.viewUrl(clip.file));
      const playing = {slot: clip.slot, audio};
      const done = () => {
        if (this.playing !== playing) return;
        this.playing = null;
        this.render();
      };
      this.playing = playing;
      audio.addEventListener('ended', done);
      audio.play().catch(() => {
        if (this.playing === playing) this.note = `Could not play ${clip.file.filename}.`;
        done();
      });
    }
    this.render();
  }

  stopPlaying() {
    this.playing?.audio.pause();
    this.playing = null;
  }

  // A character's voice clip: Upload…, or a file dropped on the row; with a clip, its file name and length, Play,
  // Upload… to replace the file and Remove.
  voiceClipRow(entity) {
    const clip = voiceClipOf(this.editor.state, entity);
    const row = el('div', 'h3cc-field h3cc-voice-clip');
    const input = el('input');
    input.type = 'file';
    input.accept = 'audio/*';
    input.hidden = true;
    input.addEventListener('change', () => {
      const [file] = input.files ?? [];
      input.value = '';
      if (file) this.uploadClip(entity, file);
    });
    // ComfyUI loads a file dropped anywhere on the page, so the row keeps its drops to itself.
    row.addEventListener('dragover', (event) => {
      if (!event.dataTransfer?.types.includes('Files')) return;
      event.preventDefault();
      event.stopPropagation();
    });
    row.addEventListener('drop', (event) => {
      const [file] = event.dataTransfer?.files ?? [];
      if (!file) return;
      event.preventDefault();
      event.stopPropagation();
      this.uploadClip(entity, file);
    });
    const actions = el('div', 'h3cc-actions');
    const length = clip ? this.clipLength(clip.file) : null;
    if (clip) {
      const playing = this.playing?.slot === clip.slot;
      const play = button(playing ? 'Stop' : 'Play', playing ? 'Stop the voice clip' : `Play ${entity.name}’s voice clip`,
        () => this.togglePlay(clip));
      play.dataset.key = 'voice-clip-play';
      actions.append(el('span', 'h3cc-clip', length == null ? clip.file.filename
        : `${clip.file.filename} · ${length.toFixed(1)} s`), play);
    }
    const title = clip ? `Upload another file for ${entity.name}’s voice; the clips keep @${clip.slot}`
      : `Upload a recording of ${entity.name}’s voice, or drop one here; the clips where ${entity.name} speaks send it to H3`;
    const upload = button('Upload…', title, () => input.click());
    upload.dataset.key = 'voice-clip-upload';
    actions.append(upload);
    if (clip) {
      const remove = button('Remove', `Take ${entity.name}’s voice clip out of the Timeline`, () => this.removeClip(entity));
      remove.dataset.key = 'voice-clip-remove';
      actions.append(remove);
    }
    row.append(el('span', 'h3ct-label', 'Voice clip'), actions, input);
    if (length > LONG_CLIP_SECONDS) row.append(el('span', 'h3cc-hint', LONG_CLIP));
    return row;
  }

  detail(entity, bible) {
    const boxes = this.editor.state.boxes;
    const others = bible.entities.filter((item) => item.id !== entity.id);
    const section = el('section', 'h3cc-detail');
    section.setAttribute('aria-label', entity.name);

    const name = el('input', 'h3ct-text');
    name.type = 'text';
    name.dataset.key = 'name';
    name.value = this.drafts.get(`${entity.id}|name`) ?? entity.name;
    name.addEventListener('input', () => this.drafts.set(`${entity.id}|name`, name.value));
    name.addEventListener('change', () => {
      if (name.value.trim() === entity.name) return;
      this.applyEntity({...structuredClone(entity), name: name.value.trim()}, {clear: [`${entity.id}|name`]});
    });
    name.addEventListener('keydown', (event) => {
      if (event.key !== 'Escape') return;
      this.drafts.delete(`${entity.id}|name`);
      name.value = entity.name;
    });
    const kind = el('select', 'h3ct-select');
    kind.dataset.key = 'kind';
    kind.append(...KINDS.map((value) => option(value, value)));
    kind.value = entity.kind;
    kind.addEventListener('change', () => this.setKind(entity, kind.value));
    const fields = el('div', 'h3cc-fields');
    fields.append(field('Name', name), field('Kind', kind));

    const images = this.pictures();
    const pictures = el('div', 'h3cc-pictures');
    for (const picture of entity.pictures) {
      const chip = el('span', 'h3cc-picture');
      chip.dataset.picture = picture;
      chip.append(referenceChip(images.find((ref) => ref.name === picture) ?? {name: picture, missing: true}),
        button('Replace…', `Replace @${picture} with another picture in every line`, () => {
          this.replacing = this.replacing === picture ? null : picture;
          this.render();
        }));
      pictures.append(chip);
    }
    const parts = [fields, field('Pictures', pictures)];
    if (entity.pictures.includes(this.replacing)) {
      const from = this.replacing;
      const picker = el('div', 'h3cc-picker');
      fillPicturePicker(picker, {value: from, refs: images, none: false, label: `Replace @${from}`}, (value) => {
        this.replacing = null;
        if (value && value !== from) this.applyEntity(replacePicture(entity, from, value));
        else this.render();
      });
      parts.push(picker, this.uploadInto(`Upload a picture into the Timeline and use it instead of @${from} in every line`,
        (slot) => {
          this.replacing = null;
          const now = this.entityNow(entity.id);
          return now?.pictures.includes(from) ? this.applyEntity(replacePicture(now, from, slot)) : false;
        }));
    }

    const strip = el('div', 'h3cc-strip');
    strip.setAttribute('aria-label', `Where ${entity.name} appears`);
    for (const cell of stripCells(entity, this.view, boxes)) {
      const look = cell.look ? `look from clip ${numberOf(boxes, (entity.looks ?? [])[cell.look - 1]?.from)}` : 'description';
      const title = cell.look == null ? `Clip ${cell.number} · not linked`
        : cell.differs ? `Clip ${cell.number} differs from the bible` : `Clip ${cell.number} · ${look}`;
      const node = button(String(cell.number), title, () => this.editor.select(cell.number - 1), 'h3cc-cell');
      node.dataset.box = cell.box;
      node.dataset.look = cell.look == null ? '' : String(cell.look);
      node.classList.toggle('empty', cell.look == null);
      node.classList.toggle('differs', cell.differs);
      node.classList.toggle('selected', cell.number - 1 === this.editor.selected);
      if (cell.look != null && !cell.differs) node.style.background = LOOK_COLORS[cell.look % LOOK_COLORS.length];
      strip.append(node);
    }
    parts.push(field('Clips', strip));

    const [description, applyDescription] = this.draft(`${entity.id}|description`, entity.description, 3,
      `${entity.name} description`, (text) => this.applyEntity({...structuredClone(entity), description: text},
        {clear: [`${entity.id}|description`]}), 'description-apply');
    const describe = el('div', 'h3cc-field');
    describe.append(el('span', 'h3ct-label', 'Description'), description, applyDescription);
    const [voice, applyVoice] = this.draft(`${entity.id}|voice`, entity.voice ?? '', 1, `${entity.name} voice`,
      (text) => this.applyEntity(withVoice(entity, text), {clear: [`${entity.id}|voice`], note: VOICE_SAVED}),
      'voice-apply', SAVE_TITLE);
    voice.placeholder = 'How they sound when they speak';
    const speaks = el('div', 'h3cc-field');
    speaks.append(el('span', 'h3ct-label', 'Voice'), voice, applyVoice);
    parts.push(describe, speaks);
    if (entity.kind === 'character') parts.push(this.voiceClipRow(entity));

    for (const look of (entity.looks ?? [])) {
      const row = el('div', 'h3cc-look');
      row.dataset.lookBox = look.from;
      const where = el('select', 'h3ct-select');
      where.dataset.key = `look-box:${look.from}`;
      where.setAttribute('aria-label', 'Look starts at');
      const at = numberOf(boxes, look.from);
      if (!at) where.append(option('', 'clip missing'));
      boxes.forEach((box, index) => {
        const choice = option(box.id, `From clip ${index + 1}`);
        choice.disabled = box.id !== look.from && (entity.looks ?? []).some((other) => other.from === box.id);
        where.append(choice);
      });
      where.value = at ? look.from : '';
      where.addEventListener('change', () => {
        if (where.value && where.value !== look.from) {
          this.applyEntity(withLook(withoutLook(entity, look.from), where.value, look.description, boxes, look.pictures));
        }
      });
      const key = `${entity.id}|look:${look.from}`;
      const [text, apply] = this.draft(key, look.description, 2, `Look from clip ${at || 'missing'}`,
        (value) => this.applyEntity(withLook(entity, look.from, value, boxes), {clear: [key]}), `look-apply:${look.from}`);
      const actions = el('div', 'h3cc-actions');
      actions.append(where, apply, button('Delete', 'Delete this look; its clips take the wording before it',
        () => this.applyEntity(withoutLook(entity, look.from))));
      row.append(actions, text);
      if (at) row.append(...this.lookPicture(entity, look, at, images));
      parts.push(row);
    }
    const index = this.editor.selected;
    const box = boxes[index];
    const addLook = button(`+ Look from clip ${index + 1}`, 'Start a look at the selected clip, from the wording in force there',
      () => this.applyEntity(withLook(entity, box.id, this.wordingAt(entity, index), boxes)));
    addLook.disabled = !box || (entity.looks ?? []).some((look) => look.from === box.id);
    parts.push(addLook);
    if (entity.kind !== 'prop' || entity.pins?.length) parts.push(this.pinList(entity));

    for (const item of (this.view?.subjects ?? []).filter((subject) => subject.entity === entity.id && subject.state === 'differs')) {
      const number = numberOf(boxes, item.box);
      const row = el('div', 'h3cc-differ');
      row.dataset.box = item.box;
      row.dataset.label = item.label;
      const someone = el('select', 'h3ct-select');
      someone.dataset.key = `someone:${item.box}:${item.label}`;
      someone.setAttribute('aria-label', 'Link this subject to someone else');
      someone.append(option('', 'Someone else…'), ...others.map((other) => option(other.id, other.name)),
        option('new', 'New entity from this line'));
      someone.addEventListener('change', () => {
        if (someone.value) this.change({action: 'apply', bible, links: {[item.box]: {[item.label]: someone.value}}});
      });
      const actions = el('div', 'h3cc-actions');
      actions.append(
        button('Use the bible’s wording', 'Write the bible’s wording into this clip', () => this.change({action: 'apply', bible,
          force: [[item.box, item.label]]})),
        button(`Make it a look from clip ${number}`, 'Keep this line and make it the look from this clip on',
          () => this.applyEntity(withLook(entity, item.box, item.text, boxes))),
        someone);
      row.append(el('p', 'h3cc-line', `Clip ${number} · ${item.line}`), actions);
      parts.push(row);
    }

    const merge = el('select', 'h3ct-select');
    merge.dataset.key = 'merge';
    merge.setAttribute('aria-label', `Merge ${entity.name} into another entity`);
    merge.append(option('', 'Merge into…'), ...others.map((other) => option(other.id, other.name)));
    merge.disabled = !others.length;
    merge.addEventListener('change', () => { if (merge.value) this.merge(entity, merge.value); });
    const actions = el('div', 'h3cc-actions');
    actions.append(merge, button('Delete entity', `Delete ${entity.name}; its subjects become unlinked and no prompt changes`,
      () => this.remove(entity)));
    parts.push(actions);
    section.append(...parts);
    return section;
  }
}
