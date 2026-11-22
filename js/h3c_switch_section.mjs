// Inspector sections headed by an on/off switch, as in DaVinci Resolve: off hides the section's controls and dims its
// header, on always shows them. The caller owns what on means: render() passes the state the project data gives, and
// a press calls onToggle(on), which changes that data and draws again.
const STYLE_ID = 'h3sw-style';
const CSS = `
.h3sw-section { min-width: 0; border-top: 1px solid #343a46; }
.h3sw-section[hidden] { display: none; }
.h3sw-head { display: flex; align-items: center; gap: 8px; width: 100%; min-height: 36px; padding: 6px 0; margin: 0;
  font: inherit; font-size: 13px; font-weight: 500; text-align: left; color: #d6dae2; background: transparent; border: 0;
  border-radius: 0; cursor: pointer; }
.h3sw-head:disabled { cursor: default; }
.h3sw-head:focus-visible { outline: 2px solid #8fbcff; outline-offset: -2px; }
.h3sw-track, .h3cx-studio details > summary::before { flex: 0 0 26px; height: 14px; border-radius: 7px; background: #3a404c;
  box-shadow: inset 0 0 0 1px #4a5160; position: relative; transition: background .15s; }
.h3sw-track::after { content: ''; position: absolute; top: 2px; left: 2px; width: 10px; height: 10px; border-radius: 50%;
  background: #8b93a1; transition: transform .15s, background .15s; }
.h3sw-section.on > .h3sw-head .h3sw-track { background: #3f6fbf; box-shadow: none; }
.h3sw-section.on > .h3sw-head .h3sw-track::after { transform: translateX(12px); background: #fff; }
.h3sw-title { flex: 0 1 auto; }
.h3sw-state { flex: 1 1 0; min-width: 0; font-size: 12px; font-weight: 400; color: #8b93a1; text-align: right;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.h3sw-section:not(.on) > .h3sw-head { color: #858c99; }
.h3sw-section:not(.on) > .h3sw-head .h3sw-track { opacity: .75; }
.h3sw-section.auto > .h3sw-head .h3sw-track { opacity: .55; }
.h3sw-body { display: flex; flex-direction: column; gap: 6px; padding: 0 0 10px 34px; min-width: 0; }
.h3sw-section:not(.on) > .h3sw-body { display: none; }
.h3sw-subhead { margin: 6px 0 0; font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: #aab1bd; }
.h3cx-studio details > summary { display: flex; align-items: center; gap: 8px; list-style: none; cursor: pointer; }
.h3cx-studio details > summary::-webkit-details-marker { display: none; }
.h3cx-studio details > summary::marker { content: ''; }
.h3cx-studio details > summary::before { content: ''; background: #3a404c radial-gradient(circle at 7px 50%, #8b93a1 5px, transparent 5.5px); }
.h3cx-studio details[open] > summary::before { background: #3f6fbf radial-gradient(circle at 19px 50%, #fff 5px, transparent 5.5px); box-shadow: none; }
.h3cx-studio details:not([open]) > summary { color: #858c99; }
@media (pointer: coarse) { .h3sw-head { min-height: 44px; } }
`;

function injectStyle() {
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

export class SwitchSection {
  // onToggle(on): the press; without one the switch only shows or hides the body. auto: the switch shows a state the
  // Studio sets by itself and cannot be pressed.
  constructor(title, {onToggle = null, auto = false, className = ''} = {}) {
    injectStyle();
    this.onToggle = onToggle;
    this.auto = auto;
    this.on = false;
    this.root = el('section', `h3sw-section ${className}`.trim());
    this.root.h3swSection = this;
    this.head = el('button', 'h3sw-head');
    this.head.type = 'button';
    this.head.setAttribute('role', 'switch');
    this.track = el('span', 'h3sw-track');
    this.track.setAttribute('aria-hidden', 'true');
    this.titleEl = el('span', 'h3sw-title', title);
    this.stateEl = el('span', 'h3sw-state');
    this.head.append(this.track, this.titleEl, this.stateEl);
    this.body = el('div', 'h3sw-body');
    this.root.append(this.head, this.body);
    this.root.classList.toggle('auto', auto);
    this.head.addEventListener('click', (event) => {
      event.preventDefault();
      if (this.auto || this.head.disabled) return;
      const next = !this.on;
      if (this.onToggle) this.onToggle(next);
      else this.set(next);
    });
    this.set(false);
  }

  get open() { return this.on; }
  set open(value) { this.set(!!value); }
  get hidden() { return this.root.hidden; }
  set hidden(value) { this.root.hidden = !!value; }

  // A section being typed in stays on, so clearing its last field doesn't hide the field.
  set(on, {disabled = false, title = '', state = ''} = {}) {
    on = !!on || (!!this.root.isConnected && this.body.contains(document.activeElement));
    const changed = on !== this.on;
    this.on = on;
    this.root.classList.toggle('on', on);
    this.head.setAttribute('aria-checked', String(on));
    this.head.disabled = !!disabled;
    if (this.auto) this.head.setAttribute('aria-disabled', 'true');
    this.head.title = title;
    if (this.stateEl.textContent !== state) this.stateEl.textContent = state;
    if (changed) this.root.dispatchEvent(new CustomEvent('toggle'));
    return on;
  }
}

// Sections the user switched on while their data is still empty, by key, until switched off.
export class Pins {
  constructor() { this.keys = new Set(); }
  has(key) { return this.keys.has(key); }
  set(key, on) { if (on) this.keys.add(key); else this.keys.delete(key); }
}

// Remembers which plain <details> sections under `root` the user opened or closed, by class and title, so a redraw
// that builds a section again keeps the user's choice instead of the default it was built with.
export function rememberDisclosures(root, storage = globalThis.localStorage) {
  const KEY = 'h3sw-disclosures';
  let saved = {};
  try { saved = JSON.parse(storage?.getItem(KEY) ?? '{}') ?? {}; } catch { saved = {}; }
  const keyOf = (details) => {
    const summary = [...details.children].find((child) => child.tagName === 'SUMMARY');
    const title = summary?.firstChild?.nodeType === 3 ? summary.firstChild.data : summary?.textContent ?? '';
    // A count or detail after "·" or "(" changes as the project does; the words before it name the section.
    return `${details.className}|${title.replace(/\s*[·(].*$/s, '').trim()}`;
  };
  root.addEventListener('click', (event) => {
    const summary = event.target.closest?.('summary');
    const details = summary?.parentElement;
    if (!details || details.tagName !== 'DETAILS' || !root.contains(details)) return;
    // The click toggles after this listener; read the state once it has.
    setTimeout(() => {
      saved[keyOf(details)] = details.open;
      try { storage?.setItem(KEY, JSON.stringify(saved)); } catch {}
    }, 0);
  }, true);
  const apply = (node) => {
    if (node.nodeType !== 1) return;
    const found = node.tagName === 'DETAILS' ? [node] : [...node.querySelectorAll('details')];
    for (const details of found) {
      const want = saved[keyOf(details)];
      if (want !== undefined && details.open !== want) details.open = want;
    }
  };
  const observer = new MutationObserver((records) => {
    for (const record of records) for (const node of record.addedNodes) apply(node);
  });
  observer.observe(root, {childList: true, subtree: true});
  return observer;
}
