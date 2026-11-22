// The Story page's Template row: the templates in the user's template folder and the examples, as ComfyUI lists them,
// and what the chosen one loads. Choosing one writes the Story node's hidden template setting, which holds its id.

const ROOT = 'Your templates';
const EXAMPLES = 'Examples';
const MISSING = 'This template isn’t in the folder any more. Write needs it back there, or another choice.';
const LISTING = 'Listing the templates…';
const NONE = {value: '', label: 'None', title: ''};

const count = (value) => Number(value).toLocaleString('en-US');
const option = (item) => ({value: item.id, label: item.name, title: item.id});
const listed = (listing) => [...(listing?.templates ?? []), ...(listing?.examples ?? [])];

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

// The select's groups: None (and `value` when the listing doesn't have it), the user's templates by folder, the root
// folder's first, then the examples. Without a listing yet, `value` stays as it is, not marked missing.
export function templateChoices(listing, value) {
  const missing = Boolean(listing) && Boolean(value) && !listed(listing).some((item) => item.id === value);
  const first = [NONE];
  if (value && (!listing || missing)) first.push({value, label: missing ? `${value} (missing)` : value, title: value});
  const folders = new Map([['', []]]);
  for (const item of listing?.templates ?? []) {
    const folder = item.id.includes('/') ? item.id.slice(0, item.id.lastIndexOf('/')) : '';
    if (!folders.has(folder)) folders.set(folder, []);
    folders.get(folder).push(option(item));
  }
  const groups = [{label: null, options: first}];
  for (const [folder, options] of folders) if (options.length) groups.push({label: folder || ROOT, options});
  if (listing?.examples?.length) groups.push({label: EXAMPLES, options: listing.examples.map(option)});
  return {groups, missing};
}

// What the row says about the chosen template: its description, what it loads, what it skipped, its note and its
// problem; or that it's missing.
export function templateDetails(listing, value) {
  if (!listing || !value) return [];
  const item = listed(listing).find((entry) => entry.id === value);
  if (!item) return [MISSING];
  const size = `${count(item.characters)} characters`;
  const references = item.files?.length ?? 0;
  const loads = item.kind !== 'skill' ? size
    : references ? `SKILL.md and ${references} reference${references === 1 ? '' : 's'}, ${size}` : `SKILL.md, ${size}`;
  return [item.description, loads, item.skipped?.length ? `Not loaded: ${item.skipped.join(', ')}` : '', item.note,
    item.problem].filter(Boolean);
}

// The row for the Studio's Story page. `input.value` is the saved id and `input.load()` fetches the listing, which
// the row asks for when it opens and on Refresh; `set(id)` saves a choice.
export function templateRow(input, set) {
  const row = el('div', 'h3cx-template');
  const select = el('select');
  select.setAttribute('aria-label', input.label);
  const details = el('div', 'h3cx-template-details');
  const folder = el('p', 'h3cx-template-folder');
  const where = el('span');
  const refresh = Object.assign(el('button', 'h3ct-button', 'Refresh'), {type: 'button', title: 'List the templates again'});
  folder.append(where, refresh);
  row.append(select, details, folder);
  let value = input.value ?? '';
  let listing = null;
  let error = null;
  let turn = 0;
  const draw = () => {
    select.replaceChildren(...templateChoices(listing, value).groups.flatMap(({label, options}) => {
      const nodes = options.map((item) => Object.assign(el('option', null, item.label), {value: item.value, title: item.title}));
      if (label == null) return nodes;
      const group = Object.assign(el('optgroup'), {label});
      group.append(...nodes);
      return [group];
    }));
    select.value = value;
    const lines = error ? [`Can’t list the templates: ${error.message}`] : listing ? templateDetails(listing, value) : [LISTING];
    details.replaceChildren(...lines.map((line) => el('p', null, line)));
    where.textContent = listing ? listing.problem ?? `Add templates to ${listing.folder}` : '';
    where.hidden = !listing;
  };
  const load = async () => {
    const mine = ++turn;
    listing = null;
    error = null;
    draw();
    try {
      const found = await input.load();
      if (mine === turn) listing = found;
    } catch (caught) {
      if (mine === turn) error = caught;
    }
    if (mine === turn) draw();
  };
  select.addEventListener('change', () => {
    value = select.value;
    set(value);
    draw();
  });
  refresh.addEventListener('click', (event) => {
    event.preventDefault();
    load();
  });
  load();
  return row;
}
