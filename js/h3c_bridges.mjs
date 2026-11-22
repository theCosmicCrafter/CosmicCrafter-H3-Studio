// The Box page's bridge into the selected box: the Bridge field on a cut, then the panel. An insertion bridge adds
// frames between the two boxes; a replacement regenerates a reviewed region around the cut with exactly as many frames,
// so the video keeps its length and recordings stay in place. Plain DOM without ComfyUI imports; the editor's host
// queues the run, and Play asks the Studio to show a take or candidate. Every region, protection and choice comes from
// the Timeline's status.
import * as model from './h3c_timeline_model.mjs?v=1dfc1612e462';
import {decorateIcon} from './h3c_icons.mjs';

const STYLE_ID = 'h3cb-style';
const CSS = `
.h3cb-wrap { display: flex; flex-direction: column; gap: 4px; }
.h3cb-wrap[hidden], .h3cb-wrap [hidden] { display: none; }
.h3cb-root { display: flex; flex-direction: column; gap: 5px; padding: 6px 8px; min-width: 0;
  background: rgba(0,0,0,.12); border: 1px solid #465066; border-radius: 4px; }
.h3cb-root.problem { border-color: #e0605a; }
.h3cb-head, .h3cb-row { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; min-width: 0; }
.h3cb-title { margin-right: auto; font-weight: 600; }
.h3cb-prompt { display: flex; flex-direction: column; gap: 3px; }
.h3cb-state { color: #c7cdd8; overflow-wrap: anywhere; }
.h3cb-state.problem, .h3cb-list .problem { color: #ff8a80; }
.h3cb-list { display: flex; flex-direction: column; gap: 3px; margin: 0; padding: 0; list-style: none; }
.h3cb-list li { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; overflow-wrap: anywhere; }
.h3cb-note { color: #f0c674; }
`;
const WAIT = "Wait for the Timeline's status to catch up with the last edit.";
const WAITING = "Waiting for the Timeline's status.";
const RENDER = 'Render only this bridge with its saved seed, keeping both boxes';
const CANDIDATE = 'Render a candidate for the confirmed region with the saved seed. It is kept beside the boxes and '
  + 'plays only once you select it';
const ORIGINAL = ' The full video plays the original cut.';
const EXPERIMENTAL = 'Experimental: replacement joins are not yet validated with real generations. Watch both joins '
  + 'and the dialogue against the recording before selecting a candidate.';
const LOCKED = 'A locked recording keeps its place, so a bridge here replaces footage instead of adding time';
const KEEP_CUT = 'A locked recording keeps its place, so this join stays a cut: a bridge would add time, and replacement '
  + 'bridges are unavailable';

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

function field(label, ...controls) {
  const node = el('label', 'h3ct-field');
  node.append(el('span', 'h3ct-label', label), ...controls);
  return node;
}

function injectStyle() {
  if (document.getElementById(STYLE_ID)) return;
  const style = el('style');
  style.id = STYLE_ID;
  style.textContent = CSS;
  document.head.append(style);
}

const sentence = (note) => `${note.charAt(0).toUpperCase()}${note.slice(1)}.`;
const clock = (frames) => (frames / model.FPS).toFixed(2);
const span = (start, end) => `${clock(start)}–${clock(end)} s`;

// The replacement panel's state line for its status `item`; `problem` is the editor's own reason, first.
export function replacementLine(item, problem = '') {
  if (problem) return {text: problem, problem: true};
  if (!item) return {text: WAITING, problem: false};
  if (item.status === 'unavailable') return {text: sentence(item.note), problem: true};
  const lost = item.selection === 'stale' ? ' The selected candidate is stale, so the full video plays the original cut.'
    : item.selection === 'missing' ? " The selected candidate's file is missing, so the full video plays the original cut." : '';
  if (['problem', 'waiting', 'review'].includes(item.status)) {
    return {text: sentence(item.note) + (lost || ORIGINAL), problem: item.status === 'problem' || !!lost};
  }
  if (item.status === 'done') {
    if (item.plays) return {text: 'The selected candidate plays in the full video in place of the original cut.', problem: false};
    if (lost) return {text: lost.trim(), problem: true};
    return {text: 'Review the candidates, then select one or keep the original cut.', problem: false};
  }
  if (item.plays) {
    return {text: 'The selected candidate plays in the full video; its prompt or seed changed since, so render a new '
      + 'candidate to compare.', problem: false};
  }
  return {text: 'Region confirmed: render a candidate.' + (lost || ORIGINAL), problem: !!lost};
}

// The panel's state line for the bridge's status `item`, undefined until the status catches up. `problem` is the
// editor's own reason the bridge can't render, and comes first.
export function bridgeLine(item, problem = '') {
  if (item?.mode === 'replace') return replacementLine(item, problem);
  if (problem) return {text: problem, problem: true};
  if (!item) return {text: WAITING, problem: false};
  if (item.status === 'problem') return {text: sentence(item.note), problem: true};
  if (item.status === 'done') return {text: `Rendered, ${item.video.frames} frames.`, problem: false};
  if (item.status === 'waiting') return {text: sentence(item.note), problem: false};
  if (item.note) return {text: `Needs a render: ${item.note}.`, problem: false};
  return {text: 'Plays as a cut until it renders.', problem: false};
}

// The region a replacement into box `index` covers (status `region`), in each box's own frames.
export function regionText(region, index) {
  const parts = [];
  if (region.left) parts.push(`box ${index} frames ${region.before[1]}–${region.before[2] - 1}`);
  if (region.right) parts.push(`box ${index + 1} frames ${region.after[1]}–${region.after[2] - 1}`);
  return `Replaces ${parts.join(' and ')}: ${region.frames} frames (${clock(region.frames)} s) from ${clock(region.start)} s `
    + `to ${clock(region.end)} s. The video keeps its length and every recording stays in place.`;
}

// The frames before the cut that `options` ([[N, [left…]]]) allows for a replacement of `frames`, as ranges.
export function allowedRanges(options, frames) {
  const lefts = (options ?? []).find(([length]) => length === frames)?.[1] ?? [];
  const ranges = [];
  for (const left of lefts) {
    const last = ranges.at(-1);
    if (last && left === last[1] + 1) last[1] = left;
    else ranges.push([left, left]);
  }
  return ranges.map(([low, high]) => low === high ? String(low) : `${low}–${high}`).join(', ');
}

// One item of status `protected`; `number` is the box number an observed mark belongs to.
export function protectionLine(mark, number) {
  if (mark.kind === 'changed') return `@${mark.slot} has a different file than cue ${mark.id} was written for`;
  if (mark.kind === 'observed') {
    return `Protected footage: ${mark.label} ${span(mark.start, mark.end)}`
      + (mark.current === false ? ` · marked on an earlier take of box ${number}` : '');
  }
  const how = {on_screen: 'speaks on screen', voiceover: 'speaks off screen', unknown: 'speaks (portrayal unknown)'}[mark.kind];
  return `${mark.speaker} ${how} ${span(mark.start, mark.end)}: “${mark.text}”`
    + (mark.kind === 'voiceover' ? ' · may continue over the replacement' : '') + (mark.checked ? '' : ' · not checked');
}

export function candidateLine(candidate, number, selected) {
  const state = candidate.state === 'stale' ? ' · stale: its region, takes or settings changed'
    : candidate.state === 'missing' ? ' · file missing' : candidate.recipe ? '' : ' · earlier prompt or seed';
  return `Candidate ${number} · seed ${candidate.seed} · ${candidate.frames} frames${selected ? ' · selected' : ''}${state}`;
}

function timeInput(label) {
  const input = el('input', 'h3ct-number');
  input.type = 'number'; input.min = '0'; input.step = '0.01';
  input.setAttribute('aria-label', label);
  return input;
}

export class BridgePanel {
  // editor: the Timeline editor, whose queueBridge() renders the selected box's bridge or replacement candidate.
  constructor(editor) {
    injectStyle();
    this.editor = editor;
    this.insertButton = button('Insert bridge', '', () => this.add('insert'));
    this.replaceButton = button('Replace around the cut', '', () => this.add('replace'));
    this.field = el('div', 'h3ct-field');
    this.field.append(el('span', 'h3ct-label', 'Bridge'), this.insertButton, this.replaceButton);
    this.hint = el('p', 'h3ct-hint');
    this.titleEl = el('span', 'h3cb-title');
    this.modeSelect = el('select', 'h3ct-select');
    this.modeSelect.setAttribute('aria-label', 'Bridge mode');
    for (const [value, label] of [['insert', 'Insert time'], ['replace', 'Replace around the cut']]) {
      const option = el('option', null, label); option.value = value; this.modeSelect.append(option);
    }
    this.modeSelect.addEventListener('change', () => {
      model.setBridgeMode(editor.state, editor.selected, this.modeSelect.value);
      editor.commit();
    });
    this.renderButton = button('Render bridge', RENDER, () => editor.queueBridge(), 'h3ct-primary');
    this.playButton = button('Play', '', () => this.root.dispatchEvent(new CustomEvent('h3c-play-bridge',
      {bubbles: true, detail: {box: editor.box().id}})));
    this.removeButton = button('Remove bridge', 'Take the bridge out, so the join plays as a cut', () => {
      model.removeBridge(editor.state, editor.selected);
      editor.commit();
    });
    const head = el('div', 'h3cb-head');
    head.append(this.titleEl, this.modeSelect, this.renderButton, this.playButton, this.removeButton);
    this.lengthSelect = el('select', 'h3ct-select');
    this.lengthSelect.setAttribute('aria-label', 'Bridge length');
    for (const frames of model.BRIDGE_FRAMES) {
      const choice = el('option', null, `${frames} frames · ${clock(frames)} s`);
      choice.value = String(frames);
      this.lengthSelect.append(choice);
    }
    this.lengthSelect.addEventListener('change', () => this.edit((bridge) => {
      const frames = Number(this.lengthSelect.value);
      if (model.isReplacement(bridge)) model.setCoverage(bridge, frames, Math.round(bridge.left * frames / (bridge.left + bridge.right)));
      else bridge.frames = frames;
    }));
    this.leftInput = el('input', 'h3ct-number');
    this.leftInput.type = 'number'; this.leftInput.min = '0'; this.leftInput.step = '1';
    this.leftInput.setAttribute('aria-label', 'Frames replaced before the cut');
    this.leftInput.addEventListener('change', () => this.edit((bridge) => {
      model.setCoverage(bridge, bridge.left + bridge.right, Number(this.leftInput.value));
    }));
    this.rightEl = el('span', 'h3ct-hint');
    this.leftField = field('Before the cut', this.leftInput, this.rightEl);
    this.leftField.title = 'How many of the replaced frames come from the end of the box before the cut; the rest come '
      + 'from the start of this box';
    this.suggestButton = button('Use suggested', '', () => this.edit((bridge) => {
      const [frames, left] = this.item()?.proposal ?? [];
      if (frames != null) model.setCoverage(bridge, frames, left);
    }));
    this.seedInput = el('input', 'h3ct-number');
    this.seedInput.type = 'number';
    this.seedInput.min = '0';
    this.seedInput.step = '1';
    this.seedInput.placeholder = 'auto';
    this.seedInput.setAttribute('aria-label', 'Bridge seed');
    this.seedInput.addEventListener('change', () => this.edit((bridge) => {
      const seed = Number(this.seedInput.value);
      if (this.seedInput.value !== '' && Number.isSafeInteger(seed) && seed >= 0) bridge.seed = seed;
      else delete bridge.seed;
    }));
    const roll = decorateIcon(button('', '', () => this.edit((bridge) => { bridge.seed = model.newSeed(); })),
      'shuffle', 'Choose a new seed for the next render');
    const row = el('div', 'h3cb-row');
    row.append(field('Length', this.lengthSelect), this.leftField, this.suggestButton, field('Seed', this.seedInput, roll));
    this.allowedEl = el('div', 'h3ct-hint');
    this.regionEl = el('div', 'h3cb-state');
    this.protectedEl = el('ul', 'h3cb-list');
    this.protectedEl.setAttribute('aria-label', 'Footage kept around the cut');
    this.protectForm = this.buildProtectForm();
    this.previewButton = button('Play region in the full video', '', () => this.playRegion());
    this.confirmButton = button('Confirm region', '', () => this.edit((bridge) => {
      model.confirmRegion(bridge, this.item().region_key);
    }), 'h3ct-primary');
    this.useOriginalButton = button('Use original cut', 'Play the original footage at this cut; the candidates stay saved', () =>
      this.edit((bridge) => model.useOriginalCut(bridge)));
    const review = el('div', 'h3cb-row');
    review.append(this.previewButton, this.confirmButton, this.useOriginalButton);
    this.candidatesEl = el('ul', 'h3cb-list');
    this.candidatesEl.setAttribute('aria-label', 'Replacement candidates');
    this.noteEl = el('div', 'h3ct-hint h3cb-note', EXPERIMENTAL);
    this.replaceRoot = el('div', 'h3cb-prompt');
    this.replaceRoot.append(this.allowedEl, this.regionEl, this.protectedEl, this.protectForm, review, this.candidatesEl, this.noteEl);
    this.promptEl = el('textarea', 'h3ct-text');
    this.promptEl.rows = 3;
    this.promptEl.setAttribute('aria-label', 'Bridge prompt');
    this.promptEl.placeholder = 'How the shot moves from the box before into this one';
    this.promptEl.title = 'Sent after the shared prompt, with no pictures or sounds: a mention reads as the described subject or sound';
    this.promptEl.addEventListener('input', () => {
      const bridge = model.bridgeOf(this.editor.state, this.editor.selected);
      if (!bridge) return;
      bridge.prompt = this.promptEl.value;
      this.editor.typed();
    });
    const prompt = el('div', 'h3cb-prompt');
    prompt.append(el('span', 'h3ct-label', 'Bridge prompt'), this.promptEl);
    this.stateEl = el('div', 'h3cb-state');
    this.stateEl.setAttribute('role', 'status');
    this.panel = el('div', 'h3cb-root');
    this.panel.setAttribute('aria-label', 'Bridge');
    this.panel.append(head, row, this.replaceRoot, prompt, this.stateEl);
    this.root = el('div', 'h3cb-wrap');
    this.root.append(this.hint, this.panel);
  }

  buildProtectForm() {
    const form = el('details', 'h3cb-prompt');
    form.append(el('summary', null, 'Protect footage'));
    this.protectBox = el('select', 'h3ct-select');
    this.protectBox.setAttribute('aria-label', 'Box whose footage to protect');
    this.protectFrom = timeInput('Protect from (s of the box)');
    this.protectTo = timeInput('Protect to (s of the box)');
    this.protectLabel = el('input', 'h3ct-input');
    this.protectLabel.placeholder = 'What happens there';
    this.protectLabel.setAttribute('aria-label', 'Protected footage label');
    const add = button('Protect', 'Keep this footage out of any replacement region, on the take it plays now', () => this.protect());
    this.protectMessage = el('span', 'h3ct-hint problem');
    this.protectMessage.setAttribute('role', 'status');
    const row = el('div', 'h3cb-row');
    row.append(this.protectBox, field('From', this.protectFrom), field('To', this.protectTo), this.protectLabel, add,
      this.protectMessage);
    form.append(el('p', 'h3ct-hint', 'Mark a gesture, reaction or other moment the region must not take. Times are '
      + "seconds of the box's own footage; the mark belongs to the take it plays now."), row);
    return form;
  }

  item() {
    return this.editor.stale ? undefined : this.editor.bridgeStatusOf(this.editor.box()?.id);
  }

  add(mode) {
    model.insertBridge(this.editor.state, this.editor.selected, mode);
    this.editor.commit();
  }

  edit(change, renderPanel = true) {
    const bridge = model.bridgeOf(this.editor.state, this.editor.selected);
    if (!bridge) return;
    change(bridge);
    this.editor.commit(renderPanel);
  }

  protect() {
    const editor = this.editor, item = this.item();
    const index = editor.state.boxes.findIndex((box) => box.id === this.protectBox.value);
    const take = item?.takes?.[this.protectBox.value];
    if (index < 0 || !take) { this.protectMessage.textContent = 'Render this box first.'; return; }
    const start = Math.floor(Number(this.protectFrom.value) * model.FPS + 1e-6);
    const end = Math.ceil(Number(this.protectTo.value) * model.FPS - 1e-6);
    const frames = editor.state.boxes[index].frames;
    if (this.protectFrom.value === '' || this.protectTo.value === '' || !Number.isFinite(start) || !Number.isFinite(end)
      || start < 0 || end <= start || end > frames) {
      this.protectMessage.textContent = `Choose a range inside box ${index + 1}'s ${clock(frames)} s.`;
      return;
    }
    this.protectMessage.textContent = '';
    const value = editor.state.dialogue ??= {version: 1, cues: []};
    const used = new Set((value.observed ?? []).map((mark) => mark.id));
    let n = 1;
    while (used.has(`o${n}`)) n += 1;
    value.observed = [...value.observed ?? [], {id: `o${n}`, box: this.protectBox.value, take, start, end,
      label: this.protectLabel.value.trim()}];
    this.protectLabel.value = '';
    editor.commit();
  }

  unprotect(id) {
    const value = this.editor.state.dialogue;
    if (!value?.observed) return;
    value.observed = value.observed.filter((mark) => mark.id !== id);
    this.editor.commit();
  }

  // The region with a second either side, on the full video's clock, which rendered insertion bridges lengthen.
  playRegion() {
    const editor = this.editor, region = this.item()?.region;
    if (!region) return;
    const index = editor.selected;
    const inserted = model.keptBridges(editor.state).filter((bridge) => !model.isReplacement(bridge)
      && editor.state.boxes.findIndex((box) => box.id === bridge.before) <= index
      && editor.bridgeStatusOf(bridge.before)?.status === 'done').reduce((sum, bridge) => sum + bridge.frames, 0);
    this.root.dispatchEvent(new CustomEvent('h3c-play-region', {bubbles: true, detail: {
      start: Math.max(0, region.start + inserted - model.FPS) / model.FPS, end: (region.end + inserted + model.FPS) / model.FPS}}));
  }

  playCandidate(file, label) {
    this.root.dispatchEvent(new CustomEvent('h3c-play-candidate', {bubbles: true,
      detail: {box: this.editor.box().id, file, label}}));
  }

  // Why the server renders no replacement bridges, or ''.
  unavailable() {
    return this.editor.status?.replacement_unavailable ?? '';
  }

  // Why the Bridge field's buttons are off, or '' when they are on. An insertion needs both boxes rendered, and the one
  // before plays all it generates; a replacement waits for its region in the status instead.
  blocked(mode) {
    const editor = this.editor;
    if (editor.stale || !editor.status?.ok) return WAIT;
    const index = editor.selected;
    if (mode === 'replace') return this.unavailable() && sentence(this.unavailable());
    if (model.lockedClips(editor.state).length) return this.unavailable() ? KEEP_CUT : LOCKED;
    const problem = model.bridgeProblem(editor.state, index);
    if (problem) return problem;
    const waiting = [index, index + 1].filter((n) => editor.statusOf(editor.state.boxes[n - 1])?.status !== 'done');
    return waiting.length ? `Render ${waiting.map((n) => `box ${n}`).join(' and ')} first.` : '';
  }

  renderField(index) {
    const insert = this.blocked('insert'), replace = this.blocked('replace');
    this.insertButton.disabled = !!insert;
    this.insertButton.title = insert || `Add new frames that move from box ${index}'s end into this box's start. `
      + 'Both boxes keep their renders, and the full video gets longer';
    this.replaceButton.hidden = !!this.unavailable();
    this.replaceButton.disabled = !!replace;
    this.replaceButton.title = replace || `Regenerate a reviewed region around this cut with exactly as many frames: the `
      + 'video keeps its length and recordings stay in place. Experimental';
    const hint = !this.unavailable() ? replace || (insert && insert !== LOCKED ? `Insert bridge: ${insert}` : '')
      : insert === KEEP_CUT ? `${KEEP_CUT}.` : insert && insert !== WAIT ? `Insert bridge: ${insert}` : insert;
    this.hint.textContent = hint;
    this.hint.hidden = !hint;
  }

  renderReplacement(bridge, item, index, problem) {
    const editor = this.editor;
    const frames = bridge.left + bridge.right;
    this.leftInput.max = String(frames);
    if (document.activeElement !== this.leftInput) this.leftInput.value = String(bridge.left);
    this.rightEl.textContent = `· after: ${bridge.right}`;
    const proposal = item?.proposal;
    const proposed = proposal && (proposal[0] !== frames || proposal[1] !== bridge.left);
    this.suggestButton.hidden = !proposed;
    this.suggestButton.title = proposed ? `Replace ${proposal[0]} frames, ${proposal[1]} before the cut: the most even split `
      + 'that keeps protected footage' : '';
    const allowed = allowedRanges(item?.options, frames);
    this.allowedEl.textContent = !item ? '' : allowed ? `Allowed before the cut for ${frames} frames: ${allowed}.`
      : `No split of ${frames} frames fits here.${item.proposal ? '' : ' Keep the cut, or shorten or move what protects the footage.'}`;
    this.regionEl.textContent = item?.region ? regionText(item.region, index) : '';
    const number = (id) => editor.state.boxes.findIndex((box) => box.id === id) + 1;
    this.protectedEl.replaceChildren(...(item?.protected ?? []).map((mark) => {
      const line = el('li', mark.kind === 'voiceover' ? '' : 'problem');
      line.append(el('span', null, protectionLine(mark, number(mark.box))));
      if (mark.kind === 'observed') line.append(button('Remove', 'Stop protecting this footage', () => this.unprotect(mark.id)));
      return line;
    }));
    this.protectedEl.hidden = !item?.protected?.length;
    const ends = [editor.state.boxes[index - 1], editor.state.boxes[index]];
    const chosen = this.protectBox.value;
    this.protectBox.replaceChildren(...ends.map((box, n) => {
      const option = el('option', null, `Box ${index + n}`); option.value = box.id; return option;
    }));
    if (ends.some((box) => box.id === chosen)) this.protectBox.value = chosen;
    this.protectForm.hidden = !item?.takes;
    this.previewButton.disabled = !item?.region || !editor.status?.full_video;
    this.previewButton.title = !editor.status?.full_video ? 'Render every clip first; the region plays in the full video'
      : 'Play the region, with a second either side, in the full video with its recordings';
    const confirmable = item?.status === 'review' && !!item.region_key && !problem;
    this.confirmButton.disabled = !confirmable;
    this.confirmButton.textContent = item?.reviewed ? 'Region confirmed ✓' : 'Confirm region';
    this.confirmButton.title = item?.reviewed ? 'You confirmed this exact region; changing it asks again'
      : confirmable ? 'Confirm these exact frames for replacement, after watching them with the recording'
        : item ? replacementLine(item, problem).text : WAIT;
    this.useOriginalButton.hidden = !bridge.selected;
    this.candidatesEl.replaceChildren(...(item?.candidates ?? []).map((candidate, n) => {
      const selected = bridge.selected === candidate.candidate;
      const line = el('li', candidate.state === 'current' ? '' : 'problem');
      line.append(el('span', null, candidateLine(candidate, n + 1, selected)));
      const label = `Candidate ${n + 1} before box ${index + 1}`;
      if (candidate.preview) {
        line.append(button('In context', 'Play the candidate between the surviving footage, with the recording',
          () => this.playCandidate(candidate.preview.file, `${label} · in context`)),
        button('Original', 'Play the original footage of the same moment, with the same recording',
          () => this.playCandidate(candidate.preview.original, `${label} · original cut`)));
      }
      if (candidate.video) {
        line.append(button('Candidate', 'Play only the replaced frames', () => this.playCandidate(candidate.video, label)));
      }
      const select = button(selected ? 'Selected' : 'Select', selected ? 'This candidate plays in the full video while it stays current'
        : 'Play this candidate in the full video in place of the original footage', () => this.edit((record) => {
        model.selectCandidate(record, candidate.candidate);
      }));
      select.disabled = selected || candidate.state !== 'current' || !item.reviewed;
      line.append(select);
      return line;
    }));
    this.candidatesEl.hidden = !item?.candidates?.length;
  }

  render() {
    const editor = this.editor;
    const index = editor.selected;
    const box = editor.box();
    const fresh = index > 0 && !!box?.cut;
    const bridge = fresh ? model.bridgeOf(editor.state, index) : undefined;
    this.field.hidden = !fresh || !!bridge;
    this.panel.hidden = !bridge;
    if (fresh && !bridge) this.renderField(index);
    else this.hint.hidden = true;
    if (!bridge) return;
    const replacing = model.isReplacement(bridge);
    const item = editor.stale ? undefined : editor.bridgeStatusOf(box.id);
    const problem = model.bridgeProblem(editor.state, index);
    const line = replacing ? replacementLine(item, problem) : bridgeLine(item, problem);
    this.titleEl.textContent = `${replacing ? 'Replacement' : 'Bridge'} before box ${index + 1}`;
    this.modeSelect.value = replacing ? 'replace' : 'insert';
    const locked = model.lockedClips(editor.state).length > 0;
    this.modeSelect.options[0].disabled = locked && replacing;
    this.modeSelect.options[1].disabled = !!this.unavailable();
    this.modeSelect.title = this.unavailable() ? sentence(this.unavailable()) : locked ? LOCKED
      : 'Insert time adds frames between the boxes; Replace around the cut keeps the video length';
    this.lengthSelect.value = String(replacing ? bridge.left + bridge.right : bridge.frames);
    this.leftField.hidden = !replacing;
    this.suggestButton.hidden = !replacing;
    this.replaceRoot.hidden = !replacing || item?.status === 'unavailable';
    this.seedInput.value = bridge.seed ?? '';
    if (this.promptEl.value !== (bridge.prompt ?? '')) this.promptEl.value = bridge.prompt ?? '';
    this.stateEl.textContent = line.text;
    this.stateEl.classList.toggle('problem', line.problem);
    this.panel.classList.toggle('problem', line.problem);
    if (replacing) this.renderReplacement(bridge, item, index, problem);
    this.renderButton.textContent = replacing ? 'Render candidate' : 'Render bridge';
    let why;
    if (editor.queuing) why = 'Wait until the run is queued.';
    else if (problem) why = problem;
    else if (!item) why = WAIT;
    else if (replacing) {
      why = editor.host.projectAttached === true ? 'Replacement candidates render from the graph; this project renders '
        + 'through the API, which leaves replacements to the Studio.'
        : ['unavailable', 'problem', 'waiting', 'review'].includes(item.status) ? line.text : '';
    } else why = item.status === 'problem' || item.status === 'waiting' ? line.text : '';
    this.renderButton.disabled = !!why;
    this.renderButton.title = why || (replacing ? CANDIDATE : RENDER);
    const take = replacing ? null : editor.bridgeStatusOf(box.id)?.video;
    this.playButton.hidden = replacing;
    this.playButton.disabled = !take;
    this.playButton.title = take ? 'Play the bridge’s take in the player' : 'The bridge has no take yet';
  }
}
