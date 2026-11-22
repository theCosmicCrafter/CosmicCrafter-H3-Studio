// The Box page's continuity check: Check, what the last check of the box's render found, and Retake.
// Plain DOM without ComfyUI imports; the editor's host starts a check through the linked Story.
import {replaceChanged, setText} from './h3c_dom.mjs?v=584a9bf55653';

const STYLE_ID = 'h3ck-style';
const CSS = `
.h3ck-root { display: flex; flex-direction: column; gap: 3px; padding: 6px 8px; min-width: 0;
  background: rgba(0,0,0,.12); border: 1px solid #465066; border-radius: 4px; }
.h3ck-root[hidden], .h3ck-root [hidden] { display: none; }
.h3ck-head { display: flex; align-items: center; gap: 6px; }
.h3ck-title { margin-right: auto; font-weight: 600; }
.h3ck-state { color: #c7cdd8; }
.h3ck-group { display: flex; flex-direction: column; gap: 1px; }
.h3ck-heading { font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: #aab1bd; }
.h3ck-problem { padding-left: 10px; overflow-wrap: anywhere; }
.h3ck-line { overflow-wrap: anywhere; }
.h3ck-note { color: #ff8a80; overflow-wrap: anywhere; }
.h3ck-retake { align-self: flex-start; }
.h3sw-body > .h3ck-root { padding: 0; background: transparent; border: 0; }
.h3sw-body > .h3ck-root .h3ck-title { visibility: hidden; }
`;
const IDLE = "Check this render against the bible with the Story's Vision model, and measure its drift";
const STALE = "Wait for the Timeline's status to catch up with the last edit.";

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function button(label, className, onClick) {
  const node = el('button', `h3ct-button ${className}`, label);
  node.type = 'button';
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

// "<what> (shot N)", the shot inside a closing stop; just "<what>" for shot 0, a problem not in one shot.
const problemText = ({what, shot}) => (shot > 0 ? what.replace(/[.!?]?$/, (end) => ` (shot ${shot})${end}`) : what);

// The problems of `check` under headings: the entities of `schedule` ({entities, place}, the box's) by name in its
// order, any other id (by name while `bible` has it), then Place and Join.
export function checkGroups(check, bible, schedule) {
  const problems = check?.problems ?? [];
  const names = new Map((bible?.entities ?? []).map((entity) => [entity.id, entity.name]));
  const others = problems.map((problem) => problem.about).filter((about) => about !== 'place' && about !== 'join');
  const order = [...new Set([...(schedule?.entities ?? []), ...others, 'place', 'join'])];
  const heading = (about) => (about === 'place' ? 'Place' : about === 'join' ? 'Join' : names.get(about) ?? about);
  return order.map((about) => ({heading: heading(about),
    items: problems.filter((problem) => problem.about === about).map(problemText)})).filter((group) => group.items.length);
}

// The check's state line and the lines under it: "No problems found." or the error, the drift against the scene's
// first box, numbered by `numberOf(id)`, and any still holds. `retake` is whether the current check found something.
export function checkState(check, numberOf = () => null) {
  if (!check) return {state: 'Not checked yet.', lines: [], retake: false};
  if (check.stale) return {state: 'The last check was of an earlier render.', lines: [], retake: false};
  const time = String(check.checked ?? '').slice(11, 16);
  const state = check.model ? `Checked at ${time} with ${check.model}.`
    : `Checked at ${time}: drift only, because the Story has no Vision model.`;
  const lines = [];
  if (check.error) lines.push(check.error);
  else if (Array.isArray(check.problems) && !check.problems.length) lines.push('No problems found.');
  const words = check.drift?.words;
  if (words) {
    const number = numberOf(check.drift.box);
    lines.push(`Drift: ${words} than ${number == null ? "the scene's first box" : `box ${number}`}.`);
  }
  const holds = Array.isArray(check.holds) ? check.holds : [];
  for (const hold of holds) {
    const where = hold.join ? 'at the join' : `at ${(hold.start_ms / 1000).toFixed(1)} s`;
    lines.push(`Holds still: ${hold.frames} frames ${where}.`);
  }
  return {state, lines, retake: !!(check.problems?.length || check.error || words || holds.length)};
}

export class CheckPanel {
  // editor: the Timeline editor, whose host.check(boxes) starts a check and throws why it can't.
  constructor(editor) {
    injectStyle();
    this.editor = editor;
    this.note = null;
    this.root = el('div', 'h3ck-root');
    this.root.setAttribute('aria-label', 'Continuity check');
    this.checkButton = button('Check', '', () => this.check());
    const head = el('div', 'h3ck-head');
    head.append(el('span', 'h3ck-title', 'Continuity check'), this.checkButton);
    this.stateEl = el('div', 'h3ck-state');
    this.groupsEl = el('div', 'h3ck-groups');
    this.linesEl = el('div');
    this.noteEl = el('div', 'h3ck-note');
    this.noteEl.setAttribute('role', 'status');
    this.retakeButton = button('Retake', 'h3ck-retake', () => editor.queueBox());
    this.root.append(head, this.stateEl, this.groupsEl, this.linesEl, this.retakeButton, this.noteEl);
  }

  async check() {
    const box = this.editor.box();
    if (!box) return;
    this.note = this.editor.stale ? {box: box.id, text: STALE} : null;
    this.render();
    if (this.note) return;
    try {
      await this.editor.host.check([box.id]);
    } catch (error) {
      this.note = {box: box.id, text: error?.message ?? String(error)};
      this.render();
    }
  }

  // Why Check is off, or '' when it is on.
  blocked() {
    const editor = this.editor;
    const story = editor.host.story?.();
    if (!story) return 'Link an H3 Story node to check boxes.';
    if (story.job) return "Wait for the Story's job to end.";
    if (editor.queuing) return 'Wait until the box is queued.';
    if (editor.stale) return STALE;
    return '';
  }

  render() {
    const editor = this.editor;
    const box = editor.box();
    const status = box ? editor.statusOf(box) : null;
    this.root.hidden = !status?.video;
    this.onRender?.(!this.root.hidden);
    if (this.root.hidden) return;
    const boxes = editor.state.boxes;
    const numberOf = (id) => {
      const index = boxes.findIndex((item) => item.id === id);
      return index < 0 ? null : index + 1;
    };
    const {state, lines, retake} = checkState(status.check, numberOf);
    setText(this.stateEl, state);
    const groups = status.check?.stale ? [] : checkGroups(status.check, editor.state.bible, box.schedule);
    replaceChanged(this.groupsEl, groups.map(({heading, items}) => {
      const group = el('div', 'h3ck-group');
      group.append(el('div', 'h3ck-heading', heading), ...items.map((text) => el('div', 'h3ck-problem', text)));
      return group;
    }));
    replaceChanged(this.linesEl, lines.map((text) => el('div', 'h3ck-line', text)));
    const why = this.blocked();
    // While the status catches up the button stays as the last one left it, and a press says to wait: switching it
    // off and on for every edit restyles the whole ComfyUI page twice.
    if (why !== STALE) this.checkButton.disabled = !!why;
    this.checkButton.title = why || IDLE;
    if (this.note?.text === STALE && !editor.stale) this.note = null;
    this.retakeButton.hidden = !retake;
    this.retakeButton.disabled = editor.boxRenderButton.disabled;
    this.retakeButton.title = editor.boxRenderButton.title;
    const note = this.note?.box === box.id ? this.note.text : '';
    setText(this.noteEl, note);
    this.noteEl.hidden = !note;
  }
}
