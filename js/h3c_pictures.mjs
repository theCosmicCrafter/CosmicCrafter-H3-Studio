// Studio pictures: files uploaded into the Timeline itself, in slots numbered after the node's 16 wired inputs,
// with no last slot. Every picture list shows them through the host's connected(), and the node loads them with
// ComfyUI's Load Image.
import * as model from './h3c_timeline_model.mjs?v=1dfc1612e462';
import { referenceChip } from './h3c_reference_pictures.mjs?v=8198307be3fa';
import { decorateIcon } from './h3c_icons.mjs';

const FIRST_SLOT = 17;
const STYLE_ID = 'h3cq-style';
const CSS = '.h3ct-text.h3cq-title { flex: 1 1 160px; width: auto; min-width: 120px; }';

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

function button(label, title, onClick) {
  const node = el('button', 'h3ct-button', label);
  node.type = 'button';
  node.title = title;
  node.addEventListener('click', (event) => {
    event.preventDefault();
    onClick();
  });
  return node;
}

// A slot something still names is not free, so a new picture never takes over a removed one's mentions.
function namedSlots(state) {
  const names = new Set();
  for (const text of [state.prompt, ...state.boxes.map((box) => box.prompt)]) {
    for (const {name} of model.mentions(text)) names.add(name);
  }
  for (const box of state.boxes) for (const name of [box.first, box.last]) if (name) names.add(name);
  for (const entity of state.bible?.entities ?? []) {
    for (const name of entity.pictures ?? []) names.add(name);
    for (const look of entity.looks ?? []) for (const name of look.pictures ?? []) names.add(name);
  }
  return names;
}

const heldSlots = (state) => [...(state.pictures ?? []), ...(state.refmods ?? [])].map((item) => item.slot);

// The first `count` slots from image17 up that no picture or RefMod holds and nothing in the Timeline names.
export function freeSlots(state, count = 1) {
  const used = new Set([...heldSlots(state), ...namedSlots(state)]);
  const free = [];
  for (let number = FIRST_SLOT; free.length < count; number++) {
    if (!used.has(`image${number}`)) free.push(`image${number}`);
  }
  return free;
}

// The number of the highest image slot the Timeline holds or names, or 0.
export function highestSlot(state) {
  let highest = 0;
  for (const name of [...heldSlots(state), ...namedSlots(state)]) {
    const number = /^image([1-9]\d*)$/.exec(name)?.[1];
    if (number) highest = Math.max(highest, Number(number));
  }
  return highest;
}

export function pictureRefs(state, viewUrl) {
  return (state.pictures ?? []).map((picture) => ({name: picture.slot, title: picture.title || picture.file.filename,
    file: picture.file.filename, mediaFile: picture.file, preview: viewUrl(picture.file), studio: true}));
}

export function usedBy(state, slot) {
  const numbers = state.boxes.flatMap((box, index) => box.first === slot || box.last === slot
    || model.mentions(box.prompt).some((item) => item.name === slot) ? [index + 1] : []);
  if (!numbers.length) return '';
  const last = numbers.at(-1);
  const boxes = numbers.length === 1 ? `Box ${last}` : numbers.length === 2 ? `Box ${numbers[0]} and box ${last}`
    : `Boxes ${numbers.slice(0, -1).join(', ')} and ${last}`;
  return `${boxes} used @${slot}.`;
}

export function addPictures(state, uploads) {
  const free = freeSlots(state, uploads.length);
  state.pictures ??= [];
  return uploads.map((upload, index) => {
    state.pictures.push({slot: free[index], file: upload.file});
    return free[index];
  });
}

export function removePicture(state, slot) {
  state.pictures = (state.pictures ?? []).filter((picture) => picture.slot !== slot);
  if (state.disabled_refs) state.disabled_refs = state.disabled_refs.filter((name) => name !== slot);
  if (state.reference_descriptions) delete state.reference_descriptions[slot];
}

export class PicturesPanel {
  constructor(editor) {
    this.editor = editor;
    this.root = el('details', 'h3ct-advanced');
    this.input = el('input');
    this.input.type = 'file';
    this.input.accept = 'image/*';
    this.input.hidden = true;
    this.input.addEventListener('change', () => {
      const files = [...(this.input.files ?? [])];
      const chosen = this.chosen;
      this.input.value = '';
      this.chosen = null;
      if (chosen && files.length) this.run(chosen, files);
    });
    this.busy = false;
    this.note = '';
    this.problem = false;
  }

  get state() { return this.editor.state; }

  // Opens the file chooser. What `task(files)` changes lands as one Timeline edit, recorded when the upload ends,
  // unless `task` returns false because it committed the edit itself. `report(text)` hears the progress and any
  // error too, for an Upload… button on another page than this panel.
  choose(multiple, task, report) {
    if (this.busy) return;
    this.chosen = {task, report};
    this.input.multiple = multiple;
    this.input.click();
  }

  async run({task, report}, files) {
    const say = (text, problem = false) => {
      this.note = text;
      this.problem = problem;
      report?.(text, problem);
    };
    this.busy = true;
    say(files.length > 1 ? `Uploading ${files.length} pictures…` : 'Uploading the picture…');
    this.render();
    try {
      const committed = await task(files) === false;
      say('');
      if (!committed) {
        this.editor.commit();
        this.editor.host.undoStep?.();
      }
    } catch (error) {
      say(error.message, true);
    } finally {
      this.busy = false;
      this.editor.renderRefmods();
    }
  }

  async upload(files) {
    const uploads = [];
    for (const file of files) uploads.push(await this.editor.host.uploadPicture(file));
    return uploads;
  }

  // + Picture adds every chosen file, in file-name order; Upload… beside a frame adds one and passes its slot to `use`.
  add(use, report) {
    this.choose(!use, async (files) => {
      const sorted = [...files].sort((a, b) => a.name.localeCompare(b.name, undefined, {numeric: true}));
      const slots = addPictures(this.state, await this.upload(sorted));
      use?.(slots[0]);
    }, report);
  }

  // Upload… in a Cast page picker: `edit(slot)` makes the bible edit that uses the new picture and commits the picture
  // with it, resolving to whether it landed. When it didn't, the picture leaves again.
  addTo(edit, report) {
    this.choose(false, async ([file]) => {
      const [slot] = addPictures(this.state, await this.upload([file]));
      let landed = false;
      try {
        landed = await edit(slot);
      } finally {
        if (!landed) removePicture(this.state, slot);
      }
      return false;
    }, report);
  }

  replace(slot) {
    this.choose(false, async ([file]) => {
      const [upload] = await this.upload([file]);
      const picture = this.state.pictures?.find((item) => item.slot === slot);
      if (!picture) throw new Error(`@${slot} was removed while its new file was uploading.`);
      picture.file = upload.file;
    });
  }

  remove(slot) {
    const used = usedBy(this.state, slot);
    removePicture(this.state, slot);
    this.note = used ? `${used} Its mentions now show as missing; Undo brings the picture back.` : '';
    this.problem = false;
    this.editor.commit();
    this.editor.renderRefmods();
  }

  setTitle(slot, value) {
    const picture = this.state.pictures?.find((item) => item.slot === slot);
    if (!picture) return;
    if (value.trim()) picture.title = value.trim();
    else delete picture.title;
    this.editor.commit();
    this.editor.renderRefmods();
  }

  render() {
    ensureStyle();
    const pictures = this.state.pictures ?? [];
    const opened = this.root.open;
    this.root.replaceChildren(el('summary', null, `Pictures${pictures.length ? ` (${pictures.length})` : ''}`));
    this.root.open = opened;
    const add = decorateIcon(button('', '', () => this.add()), 'upload', 'Add pictures', {text: true});
    add.title = 'Upload pictures into the Timeline, each in the next free slot from @image17';
    add.disabled = this.busy;
    const actions = el('div', 'h3ct-row');
    actions.append(add, this.input);
    const hint = el('p', this.problem ? 'h3ct-hint problem' : 'h3ct-hint',
      this.note || 'Pictures saved in the Timeline work like connected ones, in any box.');
    hint.setAttribute('role', 'status');
    this.root.append(actions, hint);
    const refs = new Map(this.editor.host.connected().images.map((ref) => [ref.name, ref]));
    for (const picture of pictures) {
      const card = el('div', 'h3ct-refmod');
      card.dataset.slot = picture.slot;
      const title = el('input', 'h3ct-text h3cq-title');
      title.type = 'text';
      title.value = picture.title ?? '';
      title.placeholder = 'Title';
      title.setAttribute('aria-label', `Title of @${picture.slot}`);
      title.addEventListener('change', () => this.setTitle(picture.slot, title.value));
      const row = el('div', 'h3ct-row');
      row.append(referenceChip(refs.get(picture.slot) ?? {name: picture.slot, title: picture.title || picture.file.filename}));
      // Without a title the chip shows the file name already.
      if (picture.title) row.append(el('span', 'h3ct-hint', picture.file.filename));
      row.append(title,
        button('Replace…', `Upload another file into @${picture.slot}; mentions and frames keep pointing at it`,
          () => this.replace(picture.slot)),
        button('Remove', `Remove @${picture.slot} from the Timeline`, () => this.remove(picture.slot)));
      card.append(row);
      this.root.append(card);
    }
  }
}
