// Redraws that touch only what changed. ComfyUI's stylesheets use :has() on the page root, so adding or removing any
// node, even a text node with the same words, restyles the whole page (about 70 ms with a large workflow); changing a
// text node's words or an element's attributes restyles only that element.
const TEXT_NODE = 3;

export function setText(element, text) {
  text = text == null ? '' : String(text);
  const only = element.firstChild;
  if (only && only === element.lastChild && only.nodeType === TEXT_NODE && text) {
    if (only.data !== text) only.data = text;
  } else if (element.textContent !== text) element.textContent = text;
}

// The same element apart from its tooltip, which then follows the new one.
function sameButTitle(current, next) {
  if (current.nodeType !== 1 || next.nodeType !== 1 || current.title === next.title) return false;
  const title = next.title;
  next.title = current.title;
  const same = current.isEqualNode(next);
  next.title = title;
  if (same) current.title = title;
  return same;
}

// The same elements and text nodes, nested the same way, whatever their attributes and words.
function sameShape(current, next) {
  if (current.nodeType !== next.nodeType || current.nodeName !== next.nodeName) return false;
  const a = current.childNodes, b = next.childNodes;
  return a.length === b.length && [...a].every((child, index) => sameShape(child, b[index]));
}

// An image drawn for replaceChanged names its file in data-src instead of src, and loads it once placed. A src starts
// loading the file even when the redraw throws the new node away, and in Chrome every thrown-away image lengthens the
// next garbage collection's pause: with a long Timeline's track and stills, by seconds.
const deferred = node => node.nodeName === 'IMG' && node.getAttribute('data-src') != null;

function load(image) {
  const source = image.getAttribute('data-src');
  if (image.getAttribute('src') !== source) image.setAttribute('src', source);
}

// Starts loading the deferred images of a node now in the page.
export function showImages(node) {
  if (node.nodeType !== 1) return;
  if (deferred(node)) load(node);
  for (const child of node.childNodes) showImages(child);
}

// Gives `current` the attributes and words of `next`, which has the same shape.
function patch(current, next) {
  if (current.nodeType === TEXT_NODE) {
    if (current.data !== next.data) current.data = next.data;
    return;
  }
  const image = deferred(current);
  for (const name of current.getAttributeNames()) {
    if (next.getAttribute(name) == null && !(image && name === 'src')) current.removeAttribute(name);
  }
  for (const name of next.getAttributeNames()) {
    const value = next.getAttribute(name);
    if (current.getAttribute(name) !== value) current.setAttribute(name, value);
  }
  if (deferred(current)) load(current);
  [...current.childNodes].forEach((child, index) => patch(child, next.childNodes[index]));
}

// Makes `parent`'s children `nodes`, keeping each child that already equals the new node drawn for its place. A kept
// child keeps its listeners, so whatever they use must show in its markup (the clip number in its label, say). A node
// that is already in the page (a playhead) is always the one placed.
// key(node), when given, names what a child's listeners use: a child with the same key and shape as the new node takes
// its attributes and words instead of being replaced, as when a longer clip moves every later clip along the track. A
// child with deferred images never equals its new node (only the kept one has src), so it needs a key to be kept.
export function replaceChanged(parent, nodes, key) {
  nodes.forEach((node, index) => {
    const current = parent.childNodes[index];
    if (current === node) return;
    if (!current) { parent.append(node); showImages(node); }
    else if (node.parentNode) parent.replaceChild(node, current);
    else if (current.isEqualNode(node) || sameButTitle(current, node)) return;
    else if (key && current.nodeType === 1 && key(current) === key(node) && sameShape(current, node)) patch(current, node);
    else { parent.replaceChild(node, current); showImages(node); }
  });
  while (parent.childNodes.length > nodes.length) parent.lastChild.remove();
}

// Whether `parent` already shows exactly `nodes`.
export function drawsSame(parent, nodes) {
  const current = parent.childNodes;
  return nodes.length === current.length && nodes.every((node, index) => node === current[index] || node.isEqualNode(current[index]));
}
