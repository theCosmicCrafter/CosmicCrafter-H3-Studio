// Update only linked subject definitions. Timing, dialogue and shot prose remain authored text.
export function imageDescriptionPrompt(prompt, slot, text = '') {
  if (typeof prompt !== 'string') return prompt;
  return prompt.replace(/(^[ \t]*subject_definitions:[\s\S]*?)(?=^[ \t]*(?:summary|retention_analysis|detailed_description|integrated_multimodal_description|overall_soundscape|non_diegetic_music):|$(?![\s\S]))/gm,
    section => {
      const entries = [...section.matchAll(/<Subject [1-9]\d*>\s+is\b/g)];
      let result = section;
      for (let index = entries.length - 1; index >= 0; index--) {
        const entry = entries[index], start = entry.index + entry[0].length;
        const end = entries[index + 1]?.index ?? section.length;
        const body = section.slice(start, end);
        const references = [...new Set([...body.matchAll(/(?<![\w@])@image([1-9]\d*)(?!\w)/gi)]
          .map(match => `image${Number(match[1])}`))];
        if (!references.includes(slot)) continue;
        const bindings = references.map(name => `"@${name}"`).join(' and ');
        const description = references.length === 1 ? String(text).trim().replace(/[.\s]+$/, '') : '';
        const next = ` ${description ? `${description}, in ` : ''}${bindings}.`;
        result = result.slice(0, start) + next + (body.match(/\s*$/)?.[0] ?? '') + result.slice(end);
      }
      return result;
    });
}

export function imageDescriptionSource(source, slot, text = '', entities = []) {
  if (!source || typeof source !== 'object') return;
  const affected = new Set(entities);
  const visit = value => {
    if (!value || typeof value !== 'object') return;
    if (Array.isArray(value.references) && value.references.includes(slot)) {
      for (const key of ['description','definition','wording']) if (typeof value[key] === 'string') value[key] = text;
      if (value.id) affected.add(value.id);
    }
    for (const child of Object.values(value)) if (child && typeof child === 'object') visit(child);
  };
  visit(source.frame);
  for (const id of entities) if (typeof source.frame?.wording?.[id] === 'string')
    source.frame.wording[id] = text || `"@${slot}"`;
  const subjects = source.frame?.subjects;
  if (subjects && !Array.isArray(subjects)) for (const [id, subject] of Object.entries(subjects))
    if (subject.references?.includes(slot)) affected.add(id);
  if (Array.isArray(source.reply?.subject_updates)) source.reply.subject_updates = source.reply.subject_updates
    .filter(update => !affected.has(update.subject));
  if (Array.isArray(source.reply?.analysis?.subjects)) for (const subject of source.reply.analysis.subjects)
    if (subject.sources?.some(picture => picture.reference === slot)) subject.definition = text || `"@${slot}"`;
}
