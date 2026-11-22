// Dialogue cues: a recording's exact words at its own source times, mirroring h3_continuity/dialogue.py. Boxes speak
// them as <d> lines, and replacement bridges keep the footage where someone speaks on screen. The pure helpers seed
// cues from a transcript or a Story and compute the check key; DialoguePanel edits them on the Audio page.
import * as model from './h3c_timeline_model.mjs?v=1dfc1612e462';
import {resolveWindows,coalesceWindows} from './h3c_audio_windows.mjs?v=cdefbd77b246';
import {setText} from './h3c_dom.mjs?v=584a9bf55653';

export const PORTRAYALS = [['on_screen', 'On screen'], ['voiceover', 'Voiceover'], ['unknown', 'Unknown']];
const SLOTS = ['audio1', 'audio2', 'audio3'];
const CONTROL = /<\/?d>|<\|[^>]*\|>|<\/?(?:scenetrans|cutoff)>/;
// Clip and cue times are decimal seconds; an edge within this of a window edge is on it, as dialogue.EPSILON.
const EPSILON = 1e-6;

// json.dumps(value, separators=(",", ":")) for the strings and numbers a key holds: ASCII only, as Python escapes.
function pythonJSON(value) {
  return JSON.stringify(value).replace(/[\u007f-\uffff]/g, (char) => `\\u${char.charCodeAt(0).toString(16).padStart(4, '0')}`);
}

// dialogue.alignment_key: what a user checks against the recording, its words, source interval and file.
export async function alignmentKey(cue) {
  const file = cue.recording?.file ?? {};
  const value = [cue.recording?.slot, ['type', 'subfolder', 'filename'].map((key) => file[key] ?? ''), cue.start, cue.end, cue.text];
  return sha1Hex(new TextEncoder().encode(pythonJSON(value)));
}

// crypto.subtle exists only in secure contexts (HTTPS or localhost); ComfyUI is often opened over plain http on a LAN
// address, where checking a cue would throw. The key is not a secret, so fall back to a plain SHA-1.
async function sha1Hex(bytes) {
  const subtle = globalThis.crypto?.subtle;
  if (subtle) {
    const digest = await subtle.digest('SHA-1', bytes);
    return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
  }
  return sha1Plain(bytes);
}

export function sha1Plain(bytes) {
  const words = [];
  const total = bytes.length * 8;
  const padded = new Uint8Array(((bytes.length + 8) >> 6 << 6) + 64);
  padded.set(bytes);
  padded[bytes.length] = 0x80;
  const view = new DataView(padded.buffer);
  view.setUint32(padded.length - 8, Math.floor(total / 2 ** 32));
  view.setUint32(padded.length - 4, total >>> 0);
  let h0 = 0x67452301, h1 = 0xefcdab89, h2 = 0x98badcfe, h3 = 0x10325476, h4 = 0xc3d2e1f0;
  const rotl = (x, n) => (x << n) | (x >>> (32 - n));
  for (let offset = 0; offset < padded.length; offset += 64) {
    for (let i = 0; i < 16; i += 1) words[i] = view.getUint32(offset + i * 4);
    for (let i = 16; i < 80; i += 1) words[i] = rotl(words[i - 3] ^ words[i - 8] ^ words[i - 14] ^ words[i - 16], 1);
    let a = h0, b = h1, c = h2, d = h3, e = h4;
    for (let i = 0; i < 80; i += 1) {
      let f, k;
      if (i < 20) { f = (b & c) | (~b & d); k = 0x5a827999; }
      else if (i < 40) { f = b ^ c ^ d; k = 0x6ed9eba1; }
      else if (i < 60) { f = (b & c) | (b & d) | (c & d); k = 0x8f1bbcdc; }
      else { f = b ^ c ^ d; k = 0xca62c1d6; }
      const next = (rotl(a, 5) + f + e + k + words[i]) >>> 0;
      e = d; d = c; c = rotl(b, 30) >>> 0; b = a; a = next;
    }
    h0 = (h0 + a) >>> 0; h1 = (h1 + b) >>> 0; h2 = (h2 + c) >>> 0; h3 = (h3 + d) >>> 0; h4 = (h4 + e) >>> 0;
  }
  return [h0, h1, h2, h3, h4].map((n) => n.toString(16).padStart(8, '0')).join('');
}

export async function isChecked(cue) {
  return !!cue.aligned && cue.aligned === await alignmentKey(cue);
}

export const recordingFile = model.recordingFile;

// Checking says the words and times match the recording as `state` plays it now, so the cue binds to that file.
export async function setChecked(cue, checked, state) {
  const file = checked && state ? recordingFile(state, cue.recording.slot) : null;
  if (file) cue.recording = {...cue.recording, file: structuredClone(file)};
  if (checked) cue.aligned = await alignmentKey(cue);
  else delete cue.aligned;
}

// Why the server would refuse `cue`, or ''.
export function cueProblem(cue) {
  if (!SLOTS.includes(cue.recording?.slot) || !cue.recording?.file) return 'Choose a recording uploaded on audio1, audio2 or audio3.';
  for (const key of ['start', 'end']) {
    if (typeof cue[key] !== 'number' || !Number.isFinite(cue[key]) || cue[key] < 0) return 'Start and end are seconds of the recording, from 0.';
  }
  if (cue.end <= cue.start) return 'The cue must end after its start.';
  if (typeof cue.text !== 'string' || !cue.text.trim()) return 'Write the exact words spoken.';
  const token = CONTROL.exec(cue.text)?.[0];
  if (token) return `Write only the spoken words: remove ${token}.`;
  if (!PORTRAYALS.some(([value]) => value === cue.portrayal)) return 'Choose an on screen, voiceover or unknown portrayal.';
  return '';
}

function freeIds(existing) {
  const used = new Set(existing.map((cue) => cue.id));
  let n = 0;
  return () => {
    do n += 1; while (used.has(`c${n}`));
    used.add(`c${n}`);
    return `c${n}`;
  };
}

const recording = (clip) => ({slot: clip.slot, file: structuredClone(clip.file)});

// A draft cue on `clip`: the first second of its placed window, words still to be written.
export function newCue(existing, clip) {
  return {id: freeIds(existing)(), recording: recording(clip), start: clip.source_start,
    end: Math.min(clip.source_start + 1, clip.source_start + clip.duration), text: '', speaker: '', portrayal: 'unknown',
    origin: 'manual'};
}

// {cues, skipped}: a supplied timed transcript of `clip`'s recording as unchecked cues. Times are the recording's own;
// portrayal is unknown until someone looks at the footage. Segments keep their speaker; empty ones are skipped.
export function cuesFromTranscript(data, clip, existing) {
  const segments = Array.isArray(data) ? data : Array.isArray(data?.segments) ? data.segments
    : Array.isArray(data?.chunks) ? data.chunks : null;
  if (!segments) throw new Error("A transcript needs segments, chunks or a timing array of lines; words alone don't mark lines.");
  const next = freeIds(existing), cues = [];
  let skipped = 0;
  segments.forEach((segment, index) => {
    let start = segment?.start, end = segment?.end;
    if (Array.isArray(segment?.timestamp)) [start, end] = segment.timestamp;
    const text = String(segment?.text ?? segment?.value ?? '').trim();
    const token = CONTROL.exec(text)?.[0];
    if (token) throw new Error(`Transcript segment ${index + 1} contains ${token}; cues hold only the spoken words.`);
    if (!text || !Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end <= start) { skipped += 1; return; }
    cues.push({id: next(), recording: recording(clip), start, end, text,
      speaker: typeof segment.speaker === 'string' ? segment.speaker : '', portrayal: 'unknown', origin: 'transcript'});
  });
  return {cues, skipped};
}

// {cues, skipped}: the dialogue Story planned for each box, mapped from the box's generation clock (its carried
// frames first) through `clip`'s placement onto the recording. Planned timing still needs checking; lines that don't
// lie wholly inside the placed window are skipped.
export function cuesFromStory(state, clip, existing, context) {
  const next = freeIds(existing), cues = [];
  const windows=coalesceWindows(resolveWindows(clip,model.audioBoxSpans(state)));
  const names = new Map((state.bible?.entities ?? []).map((entity) => [entity.id, entity.name]));
  let skipped = 0, start = 0;
  state.boxes.forEach((box, index) => {
    const planned = box.source?.frame?.carried;
    const carried = Number.isFinite(planned) ? planned : model.isFresh(state, index) ? 0 : context;
    const origin = (start - carried) / model.FPS;
    for (const shot of box.source?.reply?.shots ?? []) {
      for (const line of shot.dialogue ?? []) {
        const first = origin + line.start_ms / 1000, last = origin + line.end_ms / 1000;
        const text = String(line.text ?? '').trim();
        const window=windows.find(w=>first>=w.start-EPSILON && last<=w.start+w.duration+EPSILON);
        if (!text || !(last > first) || !window
          || CONTROL.test(text)) { skipped += 1; continue; }
        const offset = window.source_start-window.start;
        cues.push({id: next(), recording: recording(clip), start: Math.max(0, first + offset), end: last + offset, text,
          speaker: String(line.speaker ?? '').trim() || names.get(line.subject) || line.subject || '',
          ...(typeof line.language === 'string' && line.language ? {language: line.language} : {}),
          portrayal: line.voiceover ? 'voiceover' : 'on_screen', origin: 'story'});
      }
    }
    start += box.frames;
  });
  return {cues, skipped};
}

const span = (sequence) => `${sequence[0].toFixed(2)}–${sequence[1].toFixed(2)} s`;

// The server's view of a cue (an item of status.dialogue.cues), in a sentence.
export function cueStatusLine(item) {
  if (!item) return "Waiting for the Timeline's status.";
  if (item.state === 'changed') {
    return `@${item.slot} has a different file than this cue was written for: play it, fix the words and times, then `
      + 'tick Checked to bind the cue to it, or remove the cue.';
  }
  if (item.state === 'missing') return `@${item.slot} isn't in the Timeline or is turned off, so no box speaks this cue.`;
  const checked = item.aligned ? 'Checked' : 'Not checked';
  if (!item.placed) return `${checked} · outside the clip window, so no box speaks it.`;
  return `${checked} · plays ${span(item.sequence)} in the video`
    + (item.cut ? ' · cut by the clip window: extend the clip or edit the words.' : '.');
}

const STYLE_ID = 'h3cd-style';
const CSS = `
.h3cd-list { display: flex; flex-direction: column; gap: 6px; }
.h3cd-cue { display: flex; flex-direction: column; gap: 3px; padding: 5px 6px; border: 1px solid #465066; border-radius: 4px; }
.h3cd-cue.problem { border-color: #e0605a; }
.h3cd-cue .h3ct-number { width: 6.5em; }
.h3cd-state.problem { color: #ff8a80; }
`;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function button(label, title, onClick) {
  const node = el('button', 'h3ct-button', label);
  node.type = 'button';
  node.title = title;
  node.addEventListener('click', (event) => { event.preventDefault(); onClick(); });
  return node;
}

function labelled(label, control) {
  const node = el('label', 'h3ct-field');
  node.append(el('span', 'h3ct-label', label), control);
  return node;
}

function injectStyle() {
  if (document.getElementById(STYLE_ID)) return;
  const style = el('style');
  style.id = STYLE_ID;
  style.textContent = CSS;
  document.head.append(style);
}

export class DialoguePanel {
  // editor: the Timeline editor; its state holds `dialogue`, its status `dialogue.cues`.
  constructor(editor) {
    injectStyle();
    this.editor = editor;
    this.root = el('details', 'h3ct-audio-settings h3cd');
    this.summary = el('summary', null, 'Dialogue cues');
    this.slotSelect = el('select', 'h3ct-select');
    this.slotSelect.setAttribute('aria-label', 'Recording the cues belong to');
    this.slotSelect.addEventListener('change', () => this.render(true));
    this.upload = el('input');
    this.upload.type = 'file'; this.upload.accept = '.json,application/json'; this.upload.hidden = true;
    this.upload.addEventListener('change', () => {
      const file = this.upload.files?.[0]; this.upload.value = '';
      if (file) this.importTranscript(file);
    });
    this.importButton = button('Import transcript…', 'Add cues from a timed transcript of this recording (Whisper-style JSON); '
      + 'segments keep their speaker', () => this.upload.click());
    this.storyButton = button('From Story', "Add cues from the dialogue Story planned for each clip, placed through this recording's clip",
      () => this.fromStory());
    this.lockButton = button('Lock recording', 'Keep this recording on the sequence clock: no bridge may then add time '
      + 'inside it', () => this.lock());
    this.message = el('span', 'h3ct-hint');
    this.message.setAttribute('role', 'status');
    const head = el('div', 'h3ct-row');
    head.append(labelled('Recording', this.slotSelect), this.importButton, this.storyButton, this.lockButton, this.upload, this.message);
    this.list = el('div', 'h3cd-list');
    this.draftEl = el('div', 'h3cd-cue');
    this.player = el('audio');
    this.player.preload = 'none';
    this.player.addEventListener('timeupdate', () => {
      if (this.stopAt != null && this.player.currentTime >= this.stopAt) { this.player.pause(); this.stopAt = null; }
    });
    this.root.append(this.summary, el('p', 'h3ct-hint', "Each cue holds a recording's exact words at its own times. Clips "
      + 'speak them as <d> lines on their own clock, and replacement bridges keep the footage where someone speaks on '
      + 'screen. Check a cue once its words and times match the recording.'), head, this.list, this.draftEl);
  }

  get cues() { return this.editor.state.dialogue?.cues ?? []; }

  clips() { return (this.editor.state.audio_clips ?? []).filter((clip) => clip.file); }

  clip() {
    const clips = this.clips();
    return clips.find((clip) => clip.slot === this.slotSelect.value) ?? clips[0];
  }

  serverCue(id) {
    return this.editor.stale ? undefined : this.editor.status?.dialogue?.cues?.find((item) => item.id === id);
  }

  add(found, what) {
    const state = this.editor.state;
    state.dialogue ??= {version: 1, cues: []};
    state.dialogue.cues = [...(state.dialogue.cues ?? []), ...found.cues];
    this.message.textContent = `Added ${found.cues.length} cue${found.cues.length === 1 ? '' : 's'} from ${what}`
      + `${found.skipped ? `; skipped ${found.skipped}` : ''}. Check each against the recording.`;
    this.editor.commit();
  }

  async importTranscript(file) {
    const clip = this.clip();
    if (!clip) return;
    try {
      this.add(cuesFromTranscript(JSON.parse(await file.text()), clip, this.cues), file.name);
    } catch (error) { this.message.textContent = error.message; }
  }

  fromStory() {
    const clip = this.clip();
    if (clip) this.add(cuesFromStory(this.editor.state, clip, this.cues, this.editor.host.context()), 'the Story');
  }

  lock() {
    const clip = this.clip();
    if (!clip) return;
    clip.locked = true;
    this.editor.commit();
  }

  // `change(copy)` edits a copy of cue `index`; the cue takes it only when the server would accept it.
  edit(index, change) {
    const cue = this.cues[index], copy = structuredClone(cue);
    change(copy);
    const problem = cueProblem(copy);
    if (problem) { this.message.textContent = problem; this.render(true); return; }
    this.message.textContent = '';
    this.editor.state.dialogue.cues[index] = copy;
    this.editor.commit(false);
    this.render(true);
  }

  audition(cue) {
    const clip = (this.editor.state.audio_clips ?? []).find((item) => item.slot === cue.recording.slot);
    const file = clip?.file ?? cue.recording.file;
    const src = this.editor.host.viewUrl(file);
    if (this.player.dataset.source !== src) { this.player.src = src; this.player.dataset.source = src; }
    this.player.currentTime = cue.start;
    this.stopAt = cue.end;
    this.player.play().catch(() => { this.message.textContent = 'The recording could not play here.'; });
  }

  timeInput(label, value, onChange) {
    const input = el('input', 'h3ct-number');
    input.type = 'number'; input.min = '0'; input.step = '0.01'; input.value = String(Number(value.toFixed(3)));
    input.setAttribute('aria-label', label);
    input.addEventListener('change', () => onChange(Number(input.value)));
    return input;
  }

  cueRow(cue, index) {
    const row = el('div', 'h3cd-cue');
    const item = this.serverCue(cue.id);
    const top = el('div', 'h3ct-row');
    const speaker = el('input', 'h3ct-input');
    speaker.value = cue.speaker ?? ''; speaker.placeholder = 'Speaker'; speaker.setAttribute('aria-label', `Cue ${cue.id} speaker`);
    speaker.addEventListener('change', () => this.edit(index, (copy) => { copy.speaker = speaker.value; }));
    const portrayal = el('select', 'h3ct-select');
    portrayal.setAttribute('aria-label', `Cue ${cue.id} portrayal`);
    portrayal.title = 'On screen: the speaker is visible and their lips move. Voiceover: no visible lips move with it. '
      + 'Unknown keeps the footage protected like on-screen speech';
    for (const [value, label] of PORTRAYALS) {
      const option = el('option', null, label); option.value = value; portrayal.append(option);
    }
    portrayal.value = cue.portrayal;
    portrayal.addEventListener('change', () => this.edit(index, (copy) => { copy.portrayal = portrayal.value; }));
    const checked = el('input');
    checked.type = 'checkbox';
    checked.checked = item ? item.aligned && item.state !== 'changed' : !!cue.aligned;
    checked.setAttribute('aria-label', `Cue ${cue.id} checked against the recording`);
    checked.addEventListener('change', async () => {
      const copy = structuredClone(cue);
      await setChecked(copy, checked.checked, this.editor.state);
      if (this.cues[index] !== cue) return;
      this.editor.state.dialogue.cues[index] = copy;
      this.editor.commit(false);
      this.render(true);
    });
    const checkField = labelled('Checked', checked);
    checkField.title = 'The words and times match the recording this slot plays now; editing them clears the check';
    top.append(button('▶', 'Play this cue from the recording', () => this.audition(cue)),
      this.timeInput(`Cue ${cue.id} start`, cue.start, (value) => this.edit(index, (copy) => { copy.start = value; })),
      el('span', 'h3ct-hint', '–'),
      this.timeInput(`Cue ${cue.id} end`, cue.end, (value) => this.edit(index, (copy) => { copy.end = value; })),
      el('span', 'h3ct-hint', `s of @${cue.recording.slot}`), speaker, portrayal, checkField,
      button('Remove', 'Remove this cue', () => {
        this.editor.state.dialogue.cues = this.cues.filter((other) => other !== cue);
        this.editor.commit();
      }));
    const text = el('textarea', 'h3ct-text');
    text.rows = 1; text.value = cue.text; text.setAttribute('aria-label', `Cue ${cue.id} words`);
    text.addEventListener('change', () => this.edit(index, (copy) => { copy.text = text.value; }));
    const line = cueStatusLine(item);
    const problem = !!item && (item.state !== 'bound' || item.cut);
    const state = el('div', `h3cd-state h3ct-hint${problem ? ' problem' : ''}`, line);
    row.classList.toggle('problem', problem);
    row.append(top, text, state);
    return row;
  }

  renderDraft(clip) {
    this.draftEl.replaceChildren();
    if (!clip) return;
    this.draft = this.draft?.recording?.slot === clip.slot ? this.draft : newCue(this.cues, clip);
    const draft = this.draft;
    const text = el('textarea', 'h3ct-text');
    text.rows = 1; text.placeholder = 'The exact words spoken'; text.value = draft.text;
    text.setAttribute('aria-label', 'New cue words');
    text.addEventListener('input', () => { draft.text = text.value; });
    const speaker = el('input', 'h3ct-input');
    speaker.placeholder = 'Speaker'; speaker.value = draft.speaker; speaker.setAttribute('aria-label', 'New cue speaker');
    speaker.addEventListener('input', () => { draft.speaker = speaker.value; });
    const portrayal = el('select', 'h3ct-select');
    portrayal.setAttribute('aria-label', 'New cue portrayal');
    for (const [value, label] of PORTRAYALS) {
      const option = el('option', null, label); option.value = value; portrayal.append(option);
    }
    portrayal.value = draft.portrayal;
    portrayal.addEventListener('change', () => { draft.portrayal = portrayal.value; });
    const row = el('div', 'h3ct-row');
    row.append(el('span', 'h3ct-label', 'New cue'),
      this.timeInput('New cue start', draft.start, (value) => { draft.start = value; }), el('span', 'h3ct-hint', '–'),
      this.timeInput('New cue end', draft.end, (value) => { draft.end = value; }),
      el('span', 'h3ct-hint', `s of @${clip.slot}`), speaker, portrayal,
      button('Add cue', 'Add this cue to the recording', () => {
        draft.id = freeIds(this.cues)();
        const problem = cueProblem(draft);
        if (problem) { this.message.textContent = problem; return; }
        this.draft = null;
        this.add({cues: [draft], skipped: 0}, 'the form');
      }));
    this.draftEl.append(row, text);
  }

  // Rebuilds unless a cue field has focus; `force` rebuilds anyway, after an edit made here.
  render(force = false) {
    const state = this.editor.state, clips = this.clips();
    const cues = this.cues;
    const checked = cues.filter((cue) => this.serverCue(cue.id)?.aligned).length;
    setText(this.summary, `Dialogue cues${cues.length ? ` · ${cues.length}${this.editor.stale ? '' : `, ${checked} checked`}` : ''}`);
    this.root.hidden = !clips.length && !cues.length;
    const signature = JSON.stringify([state.dialogue, clips.map((clip) => [clip.slot, clip.file, clip.locked, clip.box_windows]),
      state.boxes.map(box=>[box.id,box.frames]),
      this.editor.stale ? null : this.editor.status?.dialogue]);
    const typing = this.root.contains(document.activeElement) && ['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName);
    if (!force && (this.signature === signature || typing)) return;
    this.signature = signature;
    const chosen = this.slotSelect.value;
    this.slotSelect.replaceChildren(...clips.map((clip) => {
      const option = el('option', null, `@${clip.slot} · ${clip.title ?? 'Audio'}${clip.locked ? ' · locked' : ''}`);
      option.value = clip.slot;
      return option;
    }));
    if (clips.some((clip) => clip.slot === chosen)) this.slotSelect.value = chosen;
    const clip = this.clip();
    for (const node of [this.importButton, this.storyButton]) node.disabled = !clip;
    this.storyButton.hidden = !state.boxes.some((box) => box.source?.reply?.shots?.some((shot) => shot.dialogue?.length));
    this.lockButton.hidden = !clip || clip.locked === true;
    if (!clip) this.message.textContent = 'Upload a recording to an audio lane to add its cues.';
    this.list.replaceChildren(...cues.map((cue, index) => this.cueRow(cue, index)));
    this.renderDraft(clip);
  }
}
