// Mention highlights for the H3 Timeline's text boxes: a layer behind a textarea repeats its text with each @image
// and @audio mention marked, and a card shows which reference the mention under the pointer is. Plain DOM without
// ComfyUI imports.
import { mentionParts } from './h3c_timeline_model.mjs?v=1dfc1612e462';

const STYLE_ID = 'h3cm-style';
const TEXT_NODE = 3;
const SHOW_DELAY_MS = 150;
const GAP = 6;
// What decides where the textarea's lines wrap. The layer fills the same box, and with the overflow settings copied
// as well it grows the same scrollbar, so its lines wrap at the same width.
const COPIED = ['overflowX', 'overflowY', 'scrollbarWidth', 'scrollbarGutter', 'fontFamily', 'fontSize', 'fontStyle',
  'fontVariant', 'fontWeight', 'fontStretch', 'lineHeight', 'letterSpacing', 'wordSpacing', 'textIndent',
  'textTransform', 'textAlign', 'tabSize', 'whiteSpace', 'wordBreak', 'overflowWrap', 'direction', 'paddingTop',
  'paddingRight', 'paddingBottom', 'paddingLeft', 'borderTopWidth', 'borderRightWidth', 'borderBottomWidth',
  'borderLeftWidth', 'borderTopLeftRadius', 'borderTopRightRadius', 'borderBottomRightRadius',
  'borderBottomLeftRadius'];
const CSS = `
.h3cm-wrap { position: relative; }
.h3cm-wrap > textarea { position: relative; display: block; margin: 0; }
.h3cm-layer { position: absolute; inset: 0; margin: 0; border-style: solid; border-color: transparent;
  color: transparent; white-space: pre-wrap; overflow-wrap: break-word; pointer-events: none; user-select: none; }
.h3cm-mark { border-radius: 3px; background: rgba(91, 143, 232, .35); }
.h3cm-mark.missing { background: rgba(224, 96, 90, .35); }
.h3cm-card { position: fixed; z-index: 10000; display: flex; flex-direction: column; gap: 3px; max-width: 280px;
  padding: 6px 8px; font: 13px/1.45 system-ui, sans-serif; color: #ddd; background: #1d2029;
  border: 1px solid #3a414d; border-radius: 6px; box-shadow: 0 4px 14px rgba(0, 0, 0, .45); pointer-events: none; }
.h3cm-card.problem { border-color: #e0605a; }
.h3cm-card img { display: block; max-width: 160px; max-height: 120px; object-fit: contain; border-radius: 3px; }
.h3cm-card [hidden] { display: none; }
.h3cm-title { font-weight: 600; overflow-wrap: anywhere; }
.h3cm-detail { color: #aab1bd; overflow-wrap: anywhere; }
`;

function el(tag, className) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  return node;
}

function injectStyle() {
  if (document.getElementById(STYLE_ID)) return;
  const style = el('style');
  style.id = STYLE_ID;
  style.textContent = CSS;
  document.head.append(style);
}

function inside(rect, x, y) {
  return x >= rect.left && x < rect.right && y >= rect.top && y < rect.bottom;
}

// Layers drawn since the last frame. Reading a textarea's style or scroll position after the page changed restyles
// the whole ComfyUI page, so the layers read theirs together before the next frame, once the redraw has written all
// of them, and share that one restyle.
const waiting = new Set();

function followWaiting() {
  const layers = [...waiting].filter((layer) => layer.area.isConnected);
  waiting.clear();
  const reads = layers.map((layer) => layer.read(!layer.painted));
  layers.forEach((layer, index) => layer.apply(reads[index]));
}

function followLater(layer) {
  if (!waiting.size) {
    if (typeof requestAnimationFrame === 'function') requestAnimationFrame(followWaiting);
    else queueMicrotask(followWaiting);
  }
  waiting.add(layer);
}

export class MentionLayer {
  // area: a textarea that fills the width it's given, as the editor's do. hooks: live() -> Set of the names whose
  // reference delivers a value, onHover(part, rect) when the pointer comes onto a mention, onLeave() when it leaves it.
  constructor(area, { live, onHover, onLeave }) {
    injectStyle();
    this.area = area;
    this.live = live;
    this.onHover = onHover;
    this.onLeave = onLeave;
    this.marks = [];
    this.hovered = null;
    this.painted = false;
    this.layer = el('div', 'h3cm-layer');
    this.layer.setAttribute('aria-hidden', 'true');
    this.root = el('div', 'h3cm-wrap');
    this.root.append(this.layer, area);
    area.addEventListener('input', () => this.render());
    area.addEventListener('scroll', () => {
      this.leave();
      this.follow();
    });
    area.addEventListener('pointermove', (event) => this.hover(event.clientX, event.clientY));
    area.addEventListener('pointerleave', () => this.leave());
    area.addEventListener('blur', () => this.leave());
    if (typeof ResizeObserver === 'function') {
      this.observer = new ResizeObserver(() => this.follow());
      this.observer.observe(area);
    }
  }

  destroy() {
    waiting.delete(this);
    this.observer?.disconnect();
    this.leave();
  }

  render() {
    this.leave();
    const live = this.live();
    const parts = mentionParts(this.area.value);
    // a textarea shows a line after a final newline; a div only when that line holds something
    if (this.area.value.endsWith('\n')) parts.push({ text: ' ' });
    const nodes = this.layer.childNodes;
    this.marks = [];
    // Adding or removing nodes restyles the whole ComfyUI page, slow enough to lag each key; while the mentions stay
    // where they are, only their text changes.
    if (nodes.length === parts.length && parts.every((part, index) => (nodes[index].nodeType === TEXT_NODE) === !part.name)) {
      parts.forEach((part, index) => {
        const node = nodes[index];
        const text = part.name ? node.firstChild : node;
        if (text.data !== part.text) text.data = part.text;
        if (!part.name) return;
        const className = live.has(part.name) ? 'h3cm-mark' : 'h3cm-mark missing';
        if (node.className !== className) node.className = className;
        this.marks.push({ part, mark: node });
      });
    } else {
      this.layer.textContent = '';
      for (const part of parts) {
        if (!part.name) {
          this.layer.append(part.text);
          continue;
        }
        const mark = el('span', live.has(part.name) ? 'h3cm-mark' : 'h3cm-mark missing');
        mark.append(part.text);
        this.layer.append(mark);
        this.marks.push({ part, mark });
      }
    }
    // The textarea's look changes only when it resizes, so once painted the layer follows only its scroll position.
    followLater(this);
  }

  follow() {
    if (this.area.isConnected) this.apply(this.read(true));
  }

  // What the layer copies from its textarea: the look that decides where lines wrap (`look`), and the scroll position.
  read(look) {
    const area = this.area, style = look ? getComputedStyle(area) : null;
    return {
      background: style?.backgroundColor,
      look: style && COPIED.map((name) => style[name]),
      top: area.scrollTop,
      left: area.scrollLeft,
    };
  }

  apply({background, look, top, left}) {
    if (look) {
      if (!this.painted) {
        this.painted = true;
        this.layer.style.backgroundColor = background;
        this.area.style.backgroundColor = 'transparent';
      }
      COPIED.forEach((name, index) => { this.layer.style[name] = look[index]; });
    }
    this.layer.scrollTop = top;
    this.layer.scrollLeft = left;
  }

  hover(x, y) {
    const found = this.marks.find(({ mark }) => [...mark.getClientRects()].some((rect) => inside(rect, x, y))) ?? null;
    if (found === this.hovered) return;
    this.leave();
    if (!found) return;
    this.hovered = found;
    this.onHover(found.part, found.mark.getBoundingClientRect());
  }

  leave() {
    if (!this.hovered) return;
    this.hovered = null;
    this.onLeave();
  }
}

export class MentionCard {
  constructor() {
    injectStyle();
    this.timer = null;
    this.rect = null;
    this.failed = false;
    this.root = el('div', 'h3cm-card');
    this.image = el('img');
    this.image.alt = '';
    this.image.addEventListener('load', () => this.place());
    this.image.addEventListener('error', () => {
      this.failed = true;
      this.image.hidden = true;
      this.place();
    });
    this.titleEl = el('div', 'h3cm-title');
    this.detailEl = el('div', 'h3cm-detail');
    this.root.append(this.image, this.titleEl, this.detailEl);
  }

  // info: {problem, title, detail, preview} from describeMention; rect: where the mention is on the screen.
  show(info, rect) {
    this.hide();
    this.timer = setTimeout(() => {
      this.timer = null;
      this.fill(info);
      this.rect = rect;
      document.body.append(this.root);
      this.place();
    }, SHOW_DELAY_MS);
  }

  fill(info) {
    this.root.classList.toggle('problem', info.problem);
    this.titleEl.textContent = info.title;
    this.detailEl.textContent = info.detail ?? '';
    this.detailEl.hidden = !info.detail;
    const preview = info.preview ?? '';
    if (preview && this.image.getAttribute('src') !== preview) {
      this.failed = false;
      this.image.src = preview;
    }
    this.image.hidden = !preview || this.failed;
  }

  place() {
    if (!this.root.isConnected || !this.rect) return;
    const card = this.root.getBoundingClientRect();
    let top = this.rect.bottom + GAP;
    if (top + card.height > window.innerHeight - GAP) top = Math.max(GAP, this.rect.top - card.height - GAP);
    const left = Math.max(GAP, Math.min(this.rect.left, window.innerWidth - card.width - GAP));
    this.root.style.left = `${left}px`;
    this.root.style.top = `${top}px`;
  }

  hide() {
    clearTimeout(this.timer);
    this.timer = null;
    this.root.remove();
  }
}
