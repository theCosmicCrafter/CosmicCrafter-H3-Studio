// The Box page's takes: the take in use and the saved takes of the selected box, then of the bridge before it, with
// Play, Use and Delete, Delete other takes and Delete unusable takes in this sequence. Plain DOM without ComfyUI
// imports; the editor's host sends the requests, and Play asks the Studio to show the take.
import * as model from './h3c_timeline_model.mjs?v=1dfc1612e462';
import {parseJSON, stringifyJSON, seedValue} from './h3c_project.mjs?v=0882b8a6265a';
import {drawsSame, setText} from './h3c_dom.mjs?v=584a9bf55653';

export const MAX_TAKES = 10;
const TAKES_URLS = {list: '/h3c/timeline/takes', use: '/h3c/timeline/takes/use', delete: '/h3c/timeline/takes/delete',
  rate: '/h3c/timeline/takes/rate'};
const STYLE_ID = 'h3ctk-style';
const CSS = `
.h3ctk-root { display: flex; flex-direction: column; gap: 5px; padding: 6px 8px; min-width: 0;
  background: rgba(0,0,0,.12); border: 1px solid #465066; border-radius: 4px; }
.h3ctk-root[hidden], .h3ctk-root [hidden] { display: none; }
.h3ctk-head, .h3ctk-row, .h3ctk-confirm { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; min-width: 0; }
.h3ctk-title { margin-right: auto; font-weight: 600; }
.h3ctk-in-use, .h3ctk-note { margin: 0; overflow-wrap: anywhere; }
.h3ctk-row { padding-top: 4px; border-top: 1px solid #343a46; }
.h3ctk-why { margin-right: auto; color: #aab1bd; }
.h3ctk-why.problem, .h3ctk-note.problem { color: #ff8a80; }
.h3ctk-confirm { padding: 4px 6px; border: 1px solid #c49a3a; border-radius: 4px; }
.h3ctk-ask { flex: 1 1 260px; overflow-wrap: anywhere; }
.h3ct-number.h3ctk-count { width: 56px; }
.h3ctk-render { display: inline-flex; align-items: center; gap: 6px; }
.h3ctk-marks { display: inline-flex; align-items: center; gap: 1px; }
.h3ctk-star { padding: 0 3px; min-width: 0; }
.h3ctk-tag { width: 90px; }
`;
const WAIT = 'Wait for the Timeline’s status to catch up with the last edit.';
const BUSY = 'Wait until this sequence’s runs finish.';

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

function injectStyle() {
  if (document.getElementById(STYLE_ID)) return;
  const style = el('style');
  style.id = STYLE_ID;
  style.textContent = CSS;
  document.head.append(style);
}

const when = (created) => (typeof created === 'string' && created.length >= 16
  ? `${created.slice(5, 10)} ${created.slice(11, 16)}` : 'at an unknown time');
const seedText = (seed) => (seedValue(seed) !== undefined ? `seed ${seed}` : 'seed not recorded');

function size(bytes) {
  if (bytes < 1024 ** 2) return `${Math.round(bytes / 1024)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
}

// Where a take came from: "from box 2’s take of 11-04 07:30 (in use)", or '' for a take that carried nothing or
// was saved before takes recorded it. inUse: the box before's take in use, {created} or null.
export function fromText(carriedFrom, number, inUse) {
  if (!carriedFrom || number < 2) return '';
  return `from box ${number - 1}’s take of ${when(carriedFrom)}${inUse?.created === carriedFrom ? ' (in use)' : ''}`;
}

// "★★★★☆ · keeper", "tag: keeper" or '' for a take's rating (0-5) and tag.
export function marksText(rating = 0, tag = '') {
  const stars = rating ? '★'.repeat(rating) + '☆'.repeat(5 - rating) : '';
  return [stars, tag ? (stars ? tag : `tag: ${tag}`) : ''].filter(Boolean).join(' · ');
}

const counted = ({count, bytes}) => `${count} ${count === 1 ? 'take' : 'takes'} (${size(bytes)})`;

export function renderLabel(number, count) {
  return count > 1 ? `Generate ${count} takes` : `Generate clip ${number}`;
}

// The hint after a status put back the takes `followed` names, in order; ids the Timeline no longer has are left out.
export function followNote(state, followed) {
  const parts = (followed ?? []).flatMap((item) => {
    const number = state.boxes.findIndex((box) => box.id === (item.bridge ?? item.box)) + 1;
    if (!number) return [];
    return [item.bridge != null ? `the take of the bridge before box ${number} rendered ${when(item.created)}`
      : `box ${number}’s take rendered ${when(item.created)}`];
  });
  if (!parts.length) return '';
  return `Put back ${parts.length === 1 ? parts[0] : `${parts.slice(0, -1).join(', ')} and ${parts.at(-1)}`}.`;
}

// The host's side of the takes requests. post(url, body) answers the parsed JSON. A status sent while a Use or a
// delete is on its way doesn't follow, and a Use or a delete waits for every status in flight, so a status that still
// names the old seed can't put the old take back.
export class TakesClient {
  constructor(post) {
    this.post = post;
    this.pending = 0;
    this.inFlight = new Set();
  }

  statusBody(body) {
    return JSON.stringify({...body, follow: this.pending === 0});
  }

  watch(request) {
    this.inFlight.add(request);
    const settled = () => this.inFlight.delete(request);
    request.then(settled, settled);
    return request;
  }

  async send(action, body) {
    const moves = action !== 'list';
    if (moves) this.pending += 1;
    try {
      if (moves) await Promise.allSettled([...this.inFlight]);
      return await this.post(TAKES_URLS[action], body);
    } catch (error) {
      return {ok: false, error: `Takes unavailable: ${error?.message ?? error}`};
    } finally {
      if (moves) this.pending -= 1;
    }
  }
}

// One Takes section: the box's, or the bridge's before it.
class Section {
  constructor(panel, bridge) {
    this.panel = panel;
    this.bridge = bridge;
    this.confirm = null;
    this.note = null;
    this.root = el('div', 'h3ctk-root');
    this.root.setAttribute('aria-label', bridge ? 'Bridge takes' : 'Clip takes');
    this.root.hidden = true;
    this.titleEl = el('span', 'h3ctk-title');
    const head = el('div', 'h3ctk-head');
    head.append(this.titleEl);
    this.inUseEl = el('p', 'h3ctk-in-use');
    this.rowsEl = el('div');
    this.otherButton = button('Delete other takes', '', () => panel.remove(this, {scope: 'other'}));
    this.actions = el('div', 'h3ctk-head');
    this.actions.append(this.otherButton);
    if (!bridge) {
      this.unusableButton = button('Delete unusable takes in this sequence', '', () => panel.remove(this, {scope: 'unusable'}));
      this.actions.append(this.unusableButton);
    }
    this.confirmEl = el('div', 'h3ctk-confirm');
    this.askEl = el('span', 'h3ctk-ask');
    this.yesButton = button('', '', () => this.confirm?.go(), 'h3ct-primary');
    this.noButton = button('Cancel', 'Keep the takes as they are', () => {
      this.confirm = null;
      panel.show();
    });
    this.confirmEl.append(this.askEl, this.yesButton, this.noButton);
    this.noteEl = el('p', 'h3ctk-note');
    this.noteEl.setAttribute('role', 'status');
    this.root.append(head, this.inUseEl, this.rowsEl, this.actions, this.confirmEl, this.noteEl);
  }

  // part: the list's {in_use, takes} for this section, {error} when the list failed, or null. off: why Use and the
  // deletes are off, or ''.
  show(part, off) {
    this.root.hidden = !part || (!part.error && !part.in_use && !part.takes?.length && !this.note);
    if (this.root.hidden) return;
    setText(this.titleEl, this.bridge ? 'Bridge takes' : 'Clip takes');
    const inUse = part.in_use, inUseNodes = [];
    if (inUse) {
      const from = this.bridge ? '' : fromText(inUse.carried_from, this.panel.editor.selected + 1, part.before);
      inUseNodes.push(document.createTextNode(`In use: rendered ${when(inUse.created)} · ${seedText(inUse.seed)}${from ? ` · ${from}` : ''} `));
      if (this.panel.editor.host.projectAttached !== true) inUseNodes.push(this.marks(inUse));
    }
    this.inUseEl.hidden = !inUse;
    const rows = (part.takes ?? []).map((take) => this.row(take, off, part.before));
    // The rows' listeners hold the list's takes; while it is the same list, equal markup keeps them.
    if (part !== this.drawnPart || !drawsSame(this.inUseEl, inUseNodes)) this.inUseEl.replaceChildren(...inUseNodes);
    if (part !== this.drawnPart || !drawsSame(this.rowsEl, rows)) this.rowsEl.replaceChildren(...rows);
    this.drawnPart = part;
    this.actions.hidden = !!part.error || this.panel.editor.host.projectAttached === true;
    this.otherButton.disabled = !!off;
    this.otherButton.title = off || `Delete every saved take of this ${this.bridge ? 'bridge' : 'box'}, keeping the take in use`;
    if (this.unusableButton) {
      this.unusableButton.disabled = !!off;
      this.unusableButton.title = off || 'Delete every saved take in this sequence that can’t be used';
    }
    this.confirmEl.hidden = !this.confirm;
    setText(this.askEl, this.confirm?.text);
    setText(this.yesButton, this.confirm?.label);
    const note = part.error ? {text: part.error, problem: true} : this.note;
    setText(this.noteEl, note?.text);
    this.noteEl.classList.toggle('problem', !!note?.problem);
    this.noteEl.hidden = !note;
  }

  row(take, off, before = null) {
    const panel = this.panel;
    const row = el('div', 'h3ctk-row');
    const why = el('span', 'h3ctk-why', take.usable ? 'Can be used' : `Can’t be used: ${take.why}`);
    why.classList.toggle('problem', !take.usable);
    const play = button('Play', take.video ? 'Play this take in the player' : 'This take has no video', () => panel.play(this, take));
    play.disabled = !take.video;
    const use = button('Use', off || (take.usable ? 'Put this take in place of the take in use' : why.textContent),
      () => panel.askUse(this, take));
    use.disabled = !!off || !take.usable;
    const remove = button('Delete', off || 'Delete this take’s files', () => panel.remove(this, {scope: 'take', take: take.folder}));
    remove.disabled = !!off || panel.editor.host.projectAttached === true;
    remove.hidden = panel.editor.host.projectAttached === true;
    const from = this.bridge ? '' : fromText(take.carried_from, panel.editor.selected + 1, before);
    row.append(el('span', 'h3ctk-line', `Rendered ${when(take.created)} · ${seedText(take.seed)}${from ? ` · ${from}` : ''}`));
    if (panel.editor.host.projectAttached !== true) row.append(this.marks(take));
    row.append(why, play, use, remove);
    return row;
  }

  // Five stars (pressing the current rating clears it) and a short tag, saved with the render's time.
  marks(take) {
    const rating = take.rating ?? 0;
    const wrap = el('span', 'h3ctk-marks');
    wrap.title = marksText(rating, take.tag) || 'Not rated';
    for (let n = 1; n <= 5; n += 1) {
      const star = button(n <= rating ? '★' : '☆', n === rating ? 'Clear the rating' : `Rate ${n} of 5`,
        () => this.panel.rate(this, take, n === rating ? 0 : n, take.tag ?? ''), 'h3ctk-star');
      star.setAttribute('aria-pressed', String(n <= rating));
      wrap.append(star);
    }
    const tag = el('input', 'h3ct-input h3ctk-tag');
    tag.value = take.tag ?? '';
    tag.maxLength = 40;
    tag.placeholder = 'tag';
    tag.title = 'A short tag for this take, such as wide or best smile';
    tag.addEventListener('change', () => this.panel.rate(this, take, rating, tag.value));
    wrap.append(tag);
    return wrap;
  }
}

export class TakesPanel {
  // editor: the Timeline editor, whose host's takes(action, body) sends the takes requests.
  constructor(editor) {
    injectStyle();
    this.editor = editor;
    this.ticket = 0;
    this.asked = null;
    this.list = null;
    this.shownBox = null;
    this.boxSection = new Section(this, false);
    this.bridgeSection = new Section(this, true);
    this.root = this.boxSection.root;
    this.bridgeRoot = this.bridgeSection.root;
  }

  // Asks for the list once per fresh status and box on Takes or the legacy Box tab.
  render() {
    const editor = this.editor;
    const box = editor.box();
    if (typeof editor.host.takes !== 'function' || !box) {
      this.root.hidden = this.bridgeRoot.hidden = true;
      return;
    }
    const status = editor.stale ? null : editor.status;
    if ((editor.activeTab === 'takes' || editor.activeTab === 'box') && status?.ok === true && (this.asked?.status !== status || this.asked?.box !== box.id)) {
      this.ask(box.id, status);
    }
    this.show();
  }

  async ask(boxId, status = this.editor.status) {
    const ticket = ++this.ticket;
    this.asked = {status, box: boxId};
    const found = await this.editor.host.takes('list', {box: boxId});
    if (ticket !== this.ticket) return;
    this.list = {box: boxId, found};
    this.show();
    this.root.dispatchEvent(new CustomEvent('h3c-takes-listed', {bubbles:true}));
  }

  show() {
    const editor = this.editor;
    const box = editor.box();
    if (this.shownBox !== box?.id) {
      this.shownBox = box?.id;
      for (const section of [this.boxSection, this.bridgeSection]) section.confirm = section.note = null;
    }
    const found = this.list?.box === box?.id ? this.list.found : null;
    // While the status catches up, Use and the deletes stay as the last one left them and a press says to wait:
    // switching them off and on for every edit restyles the whole ComfyUI page twice.
    const off = editor.status?.ok !== true ? WAIT : found?.busy ? BUSY : '';
    for (const section of [this.boxSection, this.bridgeSection]) {
      if (section.note?.text === WAIT && !editor.stale) section.note = null;
    }
    this.boxSection.show(found && (found.ok ? found.box : {error: found.error}), off);
    this.bridgeSection.show(found?.ok ? found.bridge : null, off);
  }

  setNote(section, boxId, text, problem = false) {
    if (this.editor.box()?.id !== boxId) return;
    section.note = {text, problem};
    this.show();
  }

  play(section, take) {
    const number = this.editor.selected + 1;
    const label = `${section.bridge ? `Bridge before box ${number}` : `Box ${number}`} · take rendered ${when(take.created)}`
      + ` · ${seedText(take.seed)}`;
    section.root.dispatchEvent(new CustomEvent('h3c-play-take', {bubbles: true,
      detail: {box: this.list.box, bridge: section.bridge, video: take.video, label}}));
  }

  // Whether a press must wait for the status, saying so.
  waiting(section) {
    if (this.editor.stale) this.setNote(section, this.list.box, WAIT);
    return this.editor.stale;
  }

  askUse(section, take) {
    if (this.waiting(section)) return;
    const warnings = section.bridge ? [] : this.list.found.box.warnings ?? [];
    if (!warnings.length) return this.use(section, take);
    section.confirm = {text: warnings.join(' '), label: 'Use this take', go: () => this.use(section, take)};
    this.show();
  }

  // The posted Timeline gives the take its seed; the editor's own state takes the seed once the take is in place.
  async use(section, take) {
    const editor = this.editor;
    const boxId = this.list.box;
    const target = (state) => (section.bridge ? state.bridges?.find((bridge) => bridge.before === boxId)
      : state.boxes.find((box) => box.id === boxId));
    const timeline = parseJSON(model.serialize(editor.state));
    if (!target(timeline)) return;
    target(timeline).seed = take.seed;
    section.confirm = null;
    // The Studio keeps plain keys from ComfyUI, so a Use pressed from the keyboard comes with no click that records the
    // edits before it, such as Render box's new seed. Unless they are recorded first, the Use's Undo also undoes them.
    editor.host.undoStep?.();
    await this.change(section, 'use', {box: boxId, bridge: section.bridge, take: take.folder, created: take.created,
      timeline: stringifyJSON(timeline)}, (found) => {
      if (!found?.ok) return this.setNote(section, boxId, found?.error ?? 'Takes unavailable.', true);
      const live = target(editor.state);
      if (live) live.seed = take.seed;
      editor.commit();
      editor.host.undoStep?.();
      const number = editor.state.boxes.findIndex((box) => box.id === boxId) + 1;
      this.setNote(section, boxId, `${section.bridge ? `The bridge before box ${number}` : `Box ${number}`} now uses the take`
        + ` rendered ${when(take.created)}.`);
    });
  }

  async rate(section, take, rating, tag) {
    const boxId = this.list.box;
    const found = await this.editor.host.takes('rate', {created: take.created, rating, tag});
    if (!found?.ok) return this.setNote(section, boxId, found?.error ?? 'Takes unavailable.', true);
    if (this.editor.box()?.id === boxId) this.ask(boxId);
  }

  // Counts what a delete would remove, then asks before removing it.
  async remove(section, request) {
    if (this.waiting(section)) return;
    const boxId = this.list.box;
    const body = {...request, ...(request.scope === 'other' ? {box: boxId, bridge: section.bridge} : {})};
    const found = await this.editor.host.takes('delete', {...body, apply: false});
    if (!found?.ok) return this.setNote(section, boxId, found?.error ?? 'Takes unavailable.', true);
    if (!found.count) return this.setNote(section, boxId, 'No takes to delete.');
    section.confirm = {text: `Delete ${counted(found)}? This can’t be undone.`, label: 'Delete', go: () => this.removeNow(section, boxId, body)};
    this.show();
  }

  async removeNow(section, boxId, body) {
    section.confirm = null;
    await this.change(section, 'delete', {...body, apply: true}, (found) => (found?.ok
      ? this.setNote(section, boxId, `Deleted ${counted(found)}.`)
      : this.setNote(section, boxId, found?.error ?? 'Takes unavailable.', true)));
    if (this.editor.box()?.id === boxId) this.ask(boxId);
  }

  // A request that moves or removes take files: the player lets go of its video first, and takes it back after.
  async change(section, action, body, done) {
    this.show();
    section.root.dispatchEvent(new CustomEvent('h3c-takes-changing', {bubbles: true}));
    try {
      done(await this.editor.host.takes(action, body));
    } finally {
      section.root.dispatchEvent(new CustomEvent('h3c-takes-changed', {bubbles: true}));
    }
  }
}
