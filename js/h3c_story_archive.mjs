// Keep the native workflow intact: external references and caption subgraphs belong to the snapshot too.
const FORMAT = 'h3-story';

function validate(archive) {
  if (archive?.format !== FORMAT || archive.version !== 1) throw new Error('Choose an H3 Story export (version 1).');
  const workflow = archive.workflow;
  if (!workflow || !Array.isArray(workflow.nodes) || !Array.isArray(workflow.links)
      || !workflow.nodes.some(node => node?.type === 'H3C_Timeline')
      || !workflow.nodes.some(node => node?.type === 'H3C_Story')
      || workflow.nodes.some(node => !node || node.id == null || typeof node.type !== 'string')
      || new Set(workflow.nodes.map(node => String(node.id))).size !== workflow.nodes.length) {
    throw new Error('The export does not contain a valid Story and Timeline workflow.');
  }
}

export function exportStory(graph, title = '') {
  const views = {};
  for (const node of graph._nodes ?? []) {
    if (node.h3cStory?.job) throw new Error('Wait for Story writing to finish, or cancel it, before exporting.');
    const editor = node.h3cTimeline?.editor;
    if (!editor) continue;
    views[node.id] = { selected: editor.selected, shot: editor.selectedShot, tab: editor.activeTab,
      refmods: editor.refmodsEl.open };
  }
  // Do not parse/reserialize the Timeline: that would discard future fields or normalize box timing.
  const archive = { format: FORMAT, version: 1, exported_at: new Date().toISOString(), title,
    workflow: structuredClone(graph.serialize()), views };
  validate(archive);
  return archive;
}

export async function importStory(app, archive) {
  validate(archive); // Reject malformed files before touching the open workflow.
  const workflow = structuredClone(archive.workflow);
  // Every import is an independent snapshot. Reusing the old id would restore later server autosaves/jobs.
  workflow.id = crypto.randomUUID();
  workflow.extra??={};workflow.extra.h3c_story_id=workflow.id;
  for(const node of workflow.nodes)if(node.type==='H3C_Story'&&node.properties)delete node.properties.h3c_library_revision;
  if (await app.loadGraphData(workflow, true, true, null) === false) {
    throw new Error('ComfyUI could not load this Story workflow.');
  }
  for (const node of (app.rootGraph ?? app.graph)._nodes ?? []) {
    const editor = node.h3cTimeline?.editor;
    const view = archive.views?.[node.id];
    if (!editor || !view) continue;
    if (Number.isInteger(view.selected)) editor.selected = Math.max(0, Math.min(view.selected, editor.state.boxes.length - 1));
    if (Number.isInteger(view.shot) && view.shot > 0) editor.selectedShot = view.shot;
    editor.setTab(view.tab);
    editor.render();
    editor.refmodsEl.open = Boolean(view.refmods);
  }
}

export function downloadStory(archive) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(archive, null, 2)], { type: 'application/json' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `${(archive.title || 'story').replace(/[^\p{L}\p{N} _-]/gu, '_').slice(0, 80)}.h3-story.json`;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
