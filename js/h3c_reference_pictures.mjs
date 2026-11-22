// Reference chips and picture pickers: each @reference shows its picture and title, not only its name.
const STYLE_ID = 'h3cp-style';
const CSS = `
.h3cp-chip { display: inline-flex; align-items: center; gap: 5px; min-width: 0; max-width: 100%; font-size: 12px; line-height: 1.3; }
.h3ct-chip.h3cp-chip { padding: 2px 8px 2px 2px; font-size: 12px; }
.h3cp-thumb, .h3cp-mark { flex: none; width: 22px; height: 22px; border-radius: 4px; }
.h3cp-thumb { object-fit: cover; background: #181c25; }
.h3cp-mark { display: inline-flex; align-items: center; justify-content: center; background: #262b36; color: #aab1bd; }
.h3cp-chip b { font-weight: 600; white-space: nowrap; }
.h3cp-title { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #aab1bd; }
.h3cp-chip.missing .h3cp-title { color: #ff8a80; }
.h3cp-choices, .h3cp-strip { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; min-width: 0; }
.h3cp-strip[hidden], .h3cp-filter[hidden] { display: none; }
.h3cp-picker { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.h3cp-choices { max-height: 220px; overflow-y: auto; padding: 4px; margin: -4px; }
.h3cp-filter { width: 220px; max-width: 100%; box-sizing: border-box; padding: 4px 8px; font: inherit; font-size: 13px; color: inherit;
  background: var(--comfy-input-bg, #222); border: 1px solid var(--border-color, #444); border-radius: 6px; }
.h3cp-choice { display: inline-flex; align-items: center; min-height: 30px; padding: 2px 8px 2px 2px; font: inherit; color: inherit;
  cursor: pointer; background: var(--comfy-input-bg, #222); border: 1px solid var(--border-color, #444); border-radius: 6px; }
.h3cp-choice.none { padding: 2px 10px; }
.h3cp-choice:hover { filter: brightness(1.25); }
.h3cp-choice[aria-checked="true"] { background: #293e60; border-color: #729cdd; }
.h3cp-choice:focus-visible { outline: 2px solid #8fbcff; outline-offset: 2px; }
.h3cp-choice .h3cp-thumb, .h3cp-choice .h3cp-mark { width: 30px; height: 30px; }
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

const mark = (name) => el('span', 'h3cp-mark', name.startsWith('audio') || name.startsWith('video_audio') ? '♪'
  : name.startsWith('video') ? '▶' : '◇');

export function pictureChoices(value, refs, { none = true } = {}) {
  const choices = none ? [{ value: '', name: '', title: 'None', preview: null, missing: false }] : [];
  for (const ref of refs) {
    choices.push({ value: ref.name, name: ref.name, title: ref.title ?? '', preview: ref.preview ?? null, missing: false });
  }
  if (value && !refs.some((ref) => ref.name === value)) {
    choices.push({ value, name: value, title: 'not connected', preview: null, missing: true });
  }
  return choices;
}

export function mentionedReferences(names, refs) {
  const byName = new Map(refs.map((ref) => [ref.name, ref]));
  return [...new Set(names)].map((name) => byName.get(name) ?? { name, title: 'not connected', preview: null, missing: true });
}

export function referenceChip(ref, { onClick, title } = {}) {
  ensureStyle();
  const chip = el(onClick ? 'button' : 'span', onClick ? 'h3ct-button h3ct-chip h3cp-chip' : 'h3cp-chip');
  chip.dataset.ref = ref.name;
  chip.classList.toggle('missing', !!ref.missing);
  if (ref.preview) {
    const image = el('img', 'h3cp-thumb');
    image.alt = '';
    // Set before src, or the picture loads at once.
    image.loading = 'lazy';
    image.src = ref.preview;
    image.addEventListener('error', () => image.replaceWith(mark(ref.name)));
    chip.append(image);
  } else chip.append(mark(ref.name));
  chip.append(el('b', null, `@${ref.name}`));
  const label = ref.missing ? 'not connected' : ref.title;
  if (label) chip.append(el('span', 'h3cp-title', label));
  if (onClick) {
    chip.type = 'button';
    chip.title = title ?? '';
    chip.addEventListener('click', (event) => {
      event.preventDefault();
      onClick();
    });
  } else if (title) chip.title = title;
  return chip;
}

const FILTER_AFTER = 12;

// Past FILTER_AFTER pictures a filter field narrows the choices by @slot or title; None and the chosen picture stay.
// Filling the same root again keeps what the filter holds.
export function fillPicturePicker(root, { value, refs, none = true, label }, onPick) {
  ensureStyle();
  root.classList.add('h3cp-picker');
  let filter = root.querySelector(':scope > .h3cp-filter');
  let list = root.querySelector(':scope > .h3cp-choices');
  if (!filter || !list) {
    filter = el('input', 'h3cp-filter');
    filter.type = 'search';
    filter.placeholder = 'Filter pictures';
    filter.setAttribute('aria-label', 'Filter pictures');
    filter.addEventListener('input', () => root.h3cpShow?.());
    list = el('div', 'h3cp-choices');
    list.setAttribute('role', 'radiogroup');
    root.replaceChildren(filter, list);
  }
  if (label) list.setAttribute('aria-label', label);
  filter.hidden = refs.length <= FILTER_AFTER;
  if (filter.hidden) filter.value = '';
  const current = value || '';
  const choices = pictureChoices(value, refs, { none });
  root.h3cpShow = () => {
    const query = filter.value.trim().toLowerCase();
    const shown = choices.filter((choice) => !query || !choice.value || choice.value === current
      || `@${choice.name} ${choice.title}`.toLowerCase().includes(query));
    list.replaceChildren(...shown.map((choice) => {
      const option = el('button', choice.value ? 'h3cp-choice' : 'h3cp-choice none');
      option.type = 'button';
      option.dataset.value = choice.value;
      option.setAttribute('role', 'radio');
      option.setAttribute('aria-checked', String(choice.value === current));
      option.title = choice.value ? `@${choice.name}${choice.title ? ` · ${choice.title}` : ''}` : 'None';
      option.append(choice.value ? referenceChip(choice) : 'None');
      option.addEventListener('click', (event) => {
        event.preventDefault();
        onPick(choice.value);
      });
      return option;
    }));
  };
  root.h3cpShow();
}
