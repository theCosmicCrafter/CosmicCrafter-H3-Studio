// Just enough of the DOM for the Studio's plain-DOM panels to build, render and handle clicks under node --test.
const dataKey = (name) => name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase());

class FakeElement {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.nodeType = tag === '#text' ? 3 : 1;
    this.childNodes = [];
    this.parentNode = null;
    this.attributes = new Map();
    this.listeners = new Map();
    this.style = {};
    this.dataset = {};
    Object.assign(this, {hidden: false, disabled: false, checked: false, open: false, value: '', title: '', className: '',
      id: '', text: ''});
  }

  get children() { return this.childNodes.filter((node) => node.tagName !== '#TEXT'); }
  get firstChild() { return this.childNodes[0] ?? null; }
  get lastChild() { return this.childNodes.at(-1) ?? null; }
  get firstElementChild() { return this.children[0] ?? null; }
  get options() { return this.children.filter((node) => node.tagName === 'OPTION'); }

  get classList() {
    const node = this, names = () => node.className.split(/\s+/).filter(Boolean);
    const list = {
      contains: (name) => names().includes(name),
      add: (...added) => { node.className = [...new Set([...names(), ...added])].join(' '); },
      remove: (...removed) => { node.className = names().filter((name) => !removed.includes(name)).join(' '); },
      toggle: (name, force = !names().includes(name)) => { (force ? list.add : list.remove)(name); return force; },
    };
    return list;
  }

  append(...nodes) {
    for (const node of nodes) {
      if (node == null) continue;
      const child = typeof node === 'string' ? Object.assign(new FakeElement('#text'), {text: node}) : node;
      child.parentNode?.removeChild(child);
      child.parentNode = this;
      this.childNodes.push(child);
    }
  }

  prepend(...nodes) {
    const rest = this.childNodes;
    this.childNodes = [];
    this.append(...nodes);
    this.childNodes.push(...rest);
  }

  removeChild(child) {
    this.childNodes = this.childNodes.filter((node) => node !== child);
    child.parentNode = null;
  }

  remove() { this.parentNode?.removeChild(this); }

  after(...nodes) {
    const parent = this.parentNode;
    if (!parent) return;
    for (const node of nodes) node.parentNode?.removeChild(node);
    parent.childNodes.splice(parent.childNodes.indexOf(this) + 1, 0, ...nodes);
    for (const node of nodes) node.parentNode = parent;
  }

  replaceChild(node, old) {
    node.parentNode?.removeChild(node);
    this.childNodes[this.childNodes.indexOf(old)] = node;
    node.parentNode = this;
    old.parentNode = null;
    this.replaced = (this.replaced ?? 0) + 1;
  }

  // Markup equality: everything this fake keeps as attributes, plus the children.
  isEqualNode(other) {
    const own = (node) => JSON.stringify([node.tagName, node.text, node.className, node.title, node.id, node.hidden,
      [...node.attributes].sort(), Object.entries(node.dataset).sort(), Object.entries(node.style).sort()]);
    return own(this) === own(other) && this.childNodes.length === other.childNodes.length
      && this.childNodes.every((child, index) => child.isEqualNode(other.childNodes[index]));
  }

  replaceChildren(...nodes) {
    for (const node of [...this.childNodes]) this.removeChild(node);
    this.append(...nodes);
  }

  get data() { return this.text; }
  set data(value) { this.text = String(value); }

  get textContent() { return this.text + this.childNodes.map((node) => node.textContent).join(''); }
  // As in a browser, an element's words are a text node, so a redraw that patches nodes (h3c_dom.patch) reaches them.
  set textContent(value) {
    for (const node of [...this.childNodes]) this.removeChild(node);
    const text = value == null ? '' : String(value);
    if (this.nodeType === 3) this.text = text;
    else {
      this.text = '';
      if (text) this.append(text);
    }
  }

  get nodeName() { return this.tagName; }

  // class, title, id, hidden, style and data-* live in properties here; as attributes they read and write those.
  getAttributeNames() {
    const reflected = [['class', this.className], ['title', this.title], ['id', this.id], ['hidden', this.hidden],
      ['style', Object.keys(this.style).length]].filter(([, value]) => value).map(([name]) => name);
    return [...reflected, ...Object.keys(this.dataset).map((name) => `data-${name.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`)}`),
      ...this.attributes.keys()];
  }

  setAttribute(name, value) {
    value = String(value);
    if (name === 'class') this.className = value;
    else if (name === 'title' || name === 'id') this[name] = value;
    else if (name === 'hidden') this.hidden = true;
    else if (name === 'style') this.style = JSON.parse(value);
    else if (name.startsWith('data-')) this.dataset[dataKey(name)] = value;
    else this.attributes.set(name, value);
  }

  getAttribute(name) {
    if (name === 'class') return this.className || null;
    if (name === 'title' || name === 'id') return this[name] || null;
    if (name === 'hidden') return this.hidden ? '' : null;
    if (name === 'style') return Object.keys(this.style).length ? JSON.stringify(this.style) : null;
    if (name.startsWith('data-')) return this.dataset[dataKey(name)] ?? null;
    return this.attributes.get(name) ?? null;
  }

  removeAttribute(name) {
    if (name === 'class' || name === 'title' || name === 'id') this[name === 'class' ? 'className' : name] = '';
    else if (name === 'hidden') this.hidden = false;
    else if (name === 'style') this.style = {};
    else if (name.startsWith('data-')) delete this.dataset[dataKey(name)];
    else this.attributes.delete(name);
  }

  addEventListener(type, listener) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(listener);
  }

  removeEventListener(type, listener) {
    this.listeners.set(type, (this.listeners.get(type) ?? []).filter((item) => item !== listener));
  }

  dispatchEvent(event) {
    for (let node = this; node; node = event.bubbles ? node.parentNode : null) {
      for (const listener of [...(node.listeners.get(event.type) ?? [])]) listener(event);
    }
    return true;
  }

  contains(other) {
    for (let node = other; node; node = node.parentNode) if (node === this) return true;
    return false;
  }

  click() {
    if (!this.disabled) this.dispatchEvent({type: 'click', bubbles: true, button: 0, preventDefault() {}, stopPropagation() {}});
  }

  // The event a user's edit of a field sends.
  fire(type) {
    this.dispatchEvent({type, bubbles: true, preventDefault() {}});
  }
}

export function installDom() {
  const head = new FakeElement('head');
  const find = (node, id) => node.id === id ? node : node.children.map((child) => find(child, id)).find(Boolean) ?? null;
  globalThis.document = {head, activeElement: null, createElement: (tag) => new FakeElement(tag),
    createElementNS: (namespace, tag) => new FakeElement(tag),
    createTextNode: (text) => Object.assign(new FakeElement('#text'), {text: String(text)}),
    getElementById: (id) => find(head, id)};
}

// Every element under `root` that `test` accepts, in document order.
export function findAll(root, test) {
  return [...(test(root) ? [root] : []), ...root.children.flatMap((child) => findAll(child, test))];
}

export function buttonNamed(root, label) {
  const found = findAll(root, (node) => node.tagName === 'BUTTON' && node.textContent === label);
  if (!found.length) throw new Error(`no ${label} button`);
  return found[0];
}
