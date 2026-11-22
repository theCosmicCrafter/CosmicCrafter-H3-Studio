// Idea images belong to Story, independently of Timeline render references.
import {decorateIcon} from './h3c_icons.mjs';

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function images(raw) {
  try { const value = JSON.parse(raw || '[]'); return Array.isArray(value) ? value : []; }
  catch { return []; }
}

export function ideaImagesRow(input, set) {
  if (!document.getElementById('h3ci-style')) {
    const style = el('style'); style.id = 'h3ci-style';
    style.textContent = `.h3ci-root{display:flex;flex-direction:column;gap:8px;min-width:0}
      .h3ci-grid{display:flex;flex-wrap:wrap;gap:8px}.h3ci-card{width:140px;max-width:100%;min-width:0}
      .h3ci-card img{width:100%;height:90px;object-fit:contain;background:#15171b;border-radius:4px}
      .h3ci-name{font-size:11px;overflow-wrap:anywhere}.h3ci-actions{display:flex;gap:4px;flex-wrap:wrap}
      .h3ci-root button{cursor:pointer}.h3ci-root>.h3cx-idea-add{align-self:flex-start}.h3ci-note{font-size:11px;color:#aab1bd;overflow-wrap:anywhere}`;
    document.head.append(style);
  }
  const root = el('div', 'h3ci-root'), grid = el('div', 'h3ci-grid');
  const note = el('div', 'h3ci-note', 'Optional visual inspiration. Your text idea takes priority.');
  const chooser = Object.assign(el('input'), {type: 'file', accept: 'image/*', multiple: true, hidden: true});
  const add = decorateIcon(el('button', 'h3ct-button h3cx-idea-add'), 'image', 'Add idea images', {text: true}); add.type = 'button';
  let replacing = null, busy = false;
  const read = () => images(input.read ? input.read() : input.value);
  const save = (value) => { input.value = JSON.stringify(value); set(input.value); render(); };
  const pick = (index) => {
    replacing = index; chooser.multiple = index == null; chooser.value = ''; chooser.click();
  };
  add.addEventListener('click', () => pick(null));
  const render = () => {
    const blocked = busy || input.busy?.();
    grid.replaceChildren();
    read().forEach((item, index) => {
      const card = el('div', 'h3ci-card');
      const preview = Object.assign(el('img'), {src: input.viewUrl(item.file), alt: `Idea image ${index + 1}`});
      const name = el('div', 'h3ci-name', `${index + 1}. ${item.file.filename}`);
      const actions = el('div', 'h3ci-actions');
      const replace = el('button', 'h3ct-button', 'Replace'), remove = el('button', 'h3ct-button', 'Remove');
      replace.type = remove.type = 'button'; replace.disabled = remove.disabled = !!blocked;
      replace.addEventListener('click', () => pick(index));
      remove.addEventListener('click', () => save(read().filter((_, position) => position !== index)));
      actions.append(replace, remove); card.append(preview, name, actions); grid.append(card);
    });
    add.disabled = !!blocked;
  };
  chooser.addEventListener('change', async () => {
    const files = [...chooser.files];
    if (!files.length || busy) return;
    const index = replacing, before = index == null ? null : JSON.stringify(read()[index]);
    busy = true; note.textContent = 'Uploading idea images…'; render();
    try {
      const uploads = await input.upload(index == null ? files : files.slice(0, 1));
      const current = read();
      if (index == null) current.push(...uploads);
      else {
        if (JSON.stringify(current[index]) !== before) throw new Error('This idea image changed during upload. Try replacing it again.');
        current[index] = uploads[0];
      }
      save(current);
      note.textContent = 'Optional visual inspiration. Your text idea takes priority.';
    } catch (error) { note.textContent = error.message; }
    finally { busy = false; replacing = null; chooser.value = ''; chooser.multiple = true; render(); }
  });
  input.onChange?.(render);
  root.append(add, chooser, grid, note); render();
  return root;
}
