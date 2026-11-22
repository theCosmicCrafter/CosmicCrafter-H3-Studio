function isLegacyDescription(input) {
  return input.type === 'STRING' && (!input.group || input.group === 'descriptions')
    && /^(?:descriptions\.)?image[1-9]\d*$/.test(input.name);
}

// Runs on root workflow data before native schema/autogrow can move or unlink old slots.
export function migrateSerializedStoryDescriptionInputs(graph) {
  if (!Array.isArray(graph?.nodes) || !Array.isArray(graph.links)) return {removed: 0};
  const links = graph.links.map(raw => ({raw, data: Array.isArray(raw)
    ? {id: raw[0], origin_id: raw[1], origin_slot: raw[2], target_id: raw[3], target_slot: raw[4], type: raw[5]}
    : raw}));
  if (links.some(({data}) => !data || data.id == null || data.origin_id == null || data.target_id == null
    || !Number.isInteger(data.origin_slot) || !Number.isInteger(data.target_slot))) return {removed: 0};
  const same = (a, b) => String(a) === String(b);
  const removedLinks = new Set();
  let removed = 0;
  for (const node of graph.nodes) {
    if (node.type !== 'H3C_Story') continue;
    const legacy = (node.inputs ?? []).map((input, index) => ({input, index}))
      .filter(({input}) => isLegacyDescription(input));
    if (!legacy.length) continue;
    for (const entry of legacy) {
      entry.link = entry.input.link == null ? null : links.find(({data}) => same(data.id, entry.input.link))?.raw;
    }
    // Keep malformed/scoped data intact rather than disconnect a different input's link.
    if (legacy.some(({input, index, link}) => input.link != null && (!link || !links.some(({raw, data}) =>
      raw === link && same(data.target_id, node.id) && data.target_slot === index)))) continue;
    node.properties ??= {};
    node.properties.h3c_legacy_descriptions ??= JSON.parse(JSON.stringify(legacy));
    const indices = legacy.map(({index}) => index);
    for (const {link} of legacy) if (link) removedLinks.add(link);
    node.inputs = node.inputs.filter((_, index) => !indices.includes(index));
    for (const {raw, data} of links) {
      if (removedLinks.has(raw) || !same(data.target_id, node.id)) continue;
      const slot = data.target_slot - indices.filter(index => index < data.target_slot).length;
      if (Array.isArray(raw)) raw[4] = slot;
      else raw.target_slot = slot;
    }
    removed += legacy.length;
  }
  for (const {raw, data} of links) {
    if (!removedLinks.has(raw)) continue;
    const output = graph.nodes.find(node => same(node.id, data.origin_id))?.outputs?.[data.origin_slot];
    if (Array.isArray(output?.links)) output.links = output.links.filter(id => !same(id, data.id));
  }
  if (removed) graph.links = graph.links.filter(link => !removedLinks.has(link));
  return {removed};
}

export function migrateStoryDescriptionInputs(node) {
  if (node.type !== 'H3C_Story') return {removed: 0};
  const legacy = [];
  for (const [index, input] of (node.inputs ?? []).entries()) {
    // The old Story schema had only one imageN STRING group; bare saved names lack its prefix.
    if (!isLegacyDescription(input)) continue;
    const link = node.graph?.links?.get?.(input.link) ?? node.graph?.links?.[input.link];
    legacy.push({index, input, link: link?.asSerialisable?.() ?? link ?? null});
  }
  if (!legacy.length) return {removed: 0};
  node.properties ??= {};
  node.properties.h3c_legacy_descriptions ??= JSON.parse(JSON.stringify(legacy));
  const before = node.inputs.length;
  for (const {index} of legacy.reverse()) node.removeInput(index);
  return {removed: before - node.inputs.length};
}
