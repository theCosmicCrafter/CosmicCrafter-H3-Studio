// Shared controls; the linked Timeline owns the saved reference selection.
const CSS = `
.h3cr-switches { min-width:0; padding:8px; border:1px solid var(--border-color,#444); border-radius:8px; }
.h3cr-switches > summary { cursor:pointer; font-weight:600; }
.h3cx-library .h3cr-switches > summary { display:none; }
.h3cr-hint { margin:6px 0; font-size:11px; color:#aab1bd; }
.h3cr-actions { display:flex; gap:6px; margin:8px 0; }
.h3cr-actions button { padding:3px 8px; font:inherit; color:inherit; background:var(--comfy-input-bg,#222); border:1px solid var(--border-color,#444); border-radius:5px; cursor:pointer; }
.h3cr-actions button:hover { border-color:#8fbcff; }
.h3cr-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(min(100%,112px),1fr)); gap:8px; }
.h3cr-card { display:block; min-width:0; overflow:hidden; border:2px solid var(--border-color,#444); border-radius:8px; background:var(--comfy-input-bg,#222); }
.h3cr-card:hover { border-color:#8fbcff; }
.h3cr-card:has(input:checked) { border-color:#74a7ff; }
.h3cr-card:focus-within { outline:2px solid #b7d2ff; outline-offset:2px; }
.h3cr-preview { position:relative; display:flex; width:100%; padding:0; border:0; color:inherit; align-items:center; justify-content:center; aspect-ratio:4/3; background:#141820; cursor:pointer; }
.h3cr-kind { font-size:11px; color:#aab1bd; }
.h3cr-preview img { position:absolute; inset:0; width:100%; height:100%; object-fit:contain; }
.h3cr-enable { display:flex; align-items:center; gap:4px; padding:4px 7px; font-size:11px; cursor:pointer; }
.h3cr-enable input { width:18px; height:18px; margin:0; color-scheme:dark; accent-color:#74a7ff; cursor:pointer; }
.h3cr-card .h3cr-actions { flex-wrap:wrap; margin:4px 7px; font-size:11px; }
.h3cr-group-head { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; margin:10px 0 6px; }
.h3cr-group-head h3 { margin:0; font-size:12px; }
.h3cr-group-head button { border:0; padding:0; background:transparent; color:#a9c8ff; text-decoration:underline; font-size:11px; }
.h3cr-replaced { display:block; padding:0 7px 4px; font-size:11px; color:#aab1bd; }
.h3cr-slot { position:absolute; bottom:6px; left:6px; max-width:calc(100% - 12px); padding:2px 5px; border-radius:4px; background:rgba(10,13,19,.85); color:#e7edfa; font-size:11px; font-weight:600; }
.h3cr-title { display:block; padding:6px 7px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:11px; }
`;

export function fillReferenceSwitches(root, refs, disabled, changed, {replace, restore, preview: showPreview, clearDescriptions, replacementProblem} = {}) {
  const element = (tag, text) => { const node = document.createElement(tag); if (text) node.textContent = text; return node; };
  if (!document.getElementById('h3cr-style')) {
    const style = element('style', CSS); style.id = 'h3cr-style'; document.head.append(style);
  }
  root.classList.add('h3cr-switches');
  const unique = [...new Map(refs.map(ref => [ref.name, ref])).values()];
  const blocked = name => name.startsWith('video_audio') && disabled.includes(name.replace('video_audio', 'video'));
  root.replaceChildren(element('summary', 'References'));
  if(clearDescriptions&&unique.some(ref=>ref.name.startsWith('image'))) {
    const clear=element('button','Clear all cached descriptions');clear.type='button';clear.className='h3ct-button';
    clear.addEventListener('click',clearDescriptions);root.append(clear);
  }
  if (!unique.length) {
    const hint = element('p', 'Connect references to the linked Timeline to enable or disable them here.');
    hint.className = 'h3cr-hint'; root.append(hint); return;
  }
  const groups = {};
  for (const name of ['enabled', 'disabled']) {
    const group = element('section'); group.className = 'h3cr-group'; group.dataset.group = name;
    const heading = element('div'); heading.className = 'h3cr-group-head h3cr-actions';
    const button = element('button', name === 'enabled' ? 'Disable all' : 'Enable all'); button.type = 'button';
    button.addEventListener('click', () => changed(unique.map(ref => ref.name), name === 'disabled'));
    heading.append(element('h3', name === 'enabled' ? 'Enabled' : 'Disabled'), button); group.append(heading);
    const grid = element('div'); grid.className = 'h3cr-grid'; group.append(grid);
    groups[name] = grid; root.append(group);
  }
  for (const ref of unique) {
    const card = element('div'); card.className = 'h3cr-card'; card.dataset.name = ref.name;
    card.title = `@${ref.name} · ${ref.refmod ? 'RefMod · ' : ''}${ref.title || ref.name}`;
    const preview = element('button'); preview.type = 'button'; preview.className = 'h3cr-preview';
    preview.setAttribute('aria-label', `Preview reference ${ref.name}`);
    preview.addEventListener('click', () => showPreview?.(ref));
    const kind = element('span', ref.refmod ? 'RefMod' : ref.name.startsWith('video_audio') ? 'Video soundtrack'
      : ref.name.startsWith('video') ? 'Video' : ref.name.startsWith('audio') ? 'Audio' : 'Image');
    kind.className = 'h3cr-kind';
    const input = element('input'); input.type = 'checkbox'; input.checked = !disabled.includes(ref.name) && !blocked(ref.name);
    input.disabled = blocked(ref.name);
    if (input.disabled) card.title += ' · Enable its video to use this soundtrack.';
    input.setAttribute('aria-label', `Enable reference ${ref.name}`);
    input.addEventListener('change', () => changed([ref.name], input.checked));
    const slot = element('span', `@${ref.name}`); slot.className = 'h3cr-slot';
    preview.append(kind, slot);
    if (ref.preview) {
      const image = element('img'); image.alt = `Reference @${ref.name}`;
      image.addEventListener('load', () => kind.remove(), {once: true});
      preview.prepend(image);
      image.src = ref.preview;
    }
    const title = element('span', ref.title || ref.name); title.className = 'h3cr-title';
    const enable = element('label'); enable.className = 'h3cr-enable';
    enable.append(input, element('span', input.checked ? 'Enabled' : 'Enable'));
    card.append(preview, title, enable);
    if (ref.replaced) {
      const marker = element('span', `Replaced${ref.replacementSource ? ` · ${ref.replacementSource}` : ''}`);
      marker.className = 'h3cr-replaced'; card.append(marker);
    }
    if (replace || (restore && ref.replaced)) {
      const controls = element('div'); controls.className = 'h3cr-actions';
      for (const [label, action] of [['Replace', replace], ['Restore', ref.replaced && restore]]) {
        if (!action) continue;
        const control = element('button', label); control.type = 'button';
        control.setAttribute('aria-label', `${label} reference ${ref.name}`);
        control.title=replacementProblem?.(ref)??'';control.disabled=!!control.title;
        control.addEventListener('click', () => action(ref)); controls.append(control);
      }
      card.append(controls);
    }
    groups[input.checked ? 'enabled' : 'disabled'].append(card);
  }
}
