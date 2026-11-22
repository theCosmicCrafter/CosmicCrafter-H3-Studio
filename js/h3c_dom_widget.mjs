// Where a node's DOM widget shows. Nodes 2.0 (ComfyUI frontend 1.53) keeps a node's widget slot when an undo, a redo or
// a workflow switch brings back a node with the same id, so the slot goes on showing the element of the node that was
// removed; classic nodes get a new slot.

// Puts `element`, the DOM widget element of `node`, where the page shows another `selector` element for the node with
// its id, when `node` is in `graph`, the graph on the canvas. Returns whether it did.
export function showOwnElement(node, element, selector, graph) {
  if (element.isConnected || !node.graph || node.graph !== graph) return false;
  const id = String(node.id).replace(/["\\]/g, '\\$&');
  for (const box of document.querySelectorAll(`[data-node-id="${id}"]`)) {
    const stale = box.querySelector(selector);
    if (stale && stale !== element) {
      stale.replaceWith(element);
      return true;
    }
  }
  return false;
}
