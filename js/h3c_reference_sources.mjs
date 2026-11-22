import {referenceFile} from './h3c_timeline_model.mjs?v=1dfc1612e462';

function widgetValue(node, name, graph, owners) {
  const input = node.inputs?.find(input => input.name === name);
  if (input?.link == null) return node.widgets?.find(widget => widget.name === name)?.value;
  const link = graph?.links?.get?.(input.link) ?? graph?.links?.[input.link];
  const owner = owners.at(-1);
  if (!link || link.origin_id !== graph?.inputNode?.id || owner?.subgraph !== graph) return undefined;
  const outer = owner.inputs?.[link.origin_slot];
  return outer ? widgetValue(owner, outer.name, owner.graph, owners.slice(0, -1)) : undefined;
}

// X2 changes detail, not the subject: Studio can describe its source without running the detail VAE.
export function referenceImageFile(node, graph, output = 0, owners = [], seen = new Set()) {
  if (!node || seen.has(node) || node.mode === 2) return null;
  seen = new Set(seen).add(node);
  graph = node.graph ?? graph;
  const follow = input => {
    const link = graph?.links?.get?.(input?.link) ?? graph?.links?.[input?.link];
    return link ? referenceImageFile(graph?.getNodeById?.(link.origin_id), graph, link.origin_slot, owners, seen) : null;
  };
  if (node.type === 'GetNode') {
    const name = node.widgets?.[0]?.value;
    const setters = (graph?._nodes ?? []).filter(item => item.type === 'SetNode' && item.widgets?.[0]?.value === name);
    return name && setters.length === 1 ? referenceImageFile(setters[0], graph, 0, owners, seen) : null;
  }
  if (['SetNode', 'Reroute'].includes(node.type) || node.mode === 4) {
    const inputs = (node.inputs ?? []).filter(input => input.link != null && ['IMAGE', '*'].includes(input.type));
    return inputs.length === 1 ? follow(inputs[0]) : null;
  }
  if (node.subgraph) {
    const source = node.resolveSubgraphOutputLink(output);
    return source ? referenceImageFile(source.outputNode, node.subgraph, source.link.origin_slot, [...owners, node], seen) : null;
  }
  if (node.type === 'MiniMaxH3X2DetailedUpscale') return follow(node.inputs?.find(input => input.name === 'images'));
  if (node.type === 'ComfySwitchNode') {
    const files = ['on_false', 'on_true'].map(name => follow(node.inputs?.find(input => input.name === name)));
    return files[0] && files[1] && files[0].path === files[1].path && files[0].type === files[1].type ? files[0] : null;
  }
  if (!['LoadImage', 'LoadImageOutput'].includes(node.type)) return null;
  return referenceFile({type: node.type, widgets: [{name: 'image', value: widgetValue(node, 'image', graph, owners)}]});
}
