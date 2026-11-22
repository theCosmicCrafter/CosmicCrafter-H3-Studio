import {parseJSON,stringifyJSON} from './h3c_project.mjs?v=0882b8a6265a';
import {settledPreparation} from './h3c_reference_preparation.mjs?v=d05409662438';
import {applyResult,parseStoryState,serializeStoryState} from './h3c_story_model.mjs?v=f498e4660a19';
import {reconcileSceneAnchors} from './h3c_still_scene.mjs?v=0906bb5de9d7';

const CONTENT_FIELDS=new Set(['name','timeline','idea','state','idea_images','template']);

function savedFields(workflow,node,textNodes=new Set()) {
  if(!node)throw Error('The saved story has no linked Story and Timeline.');
  const fields={};
  for(const [index,input]of (node.inputs??[]).filter(input=>input.widget).entries()) {
    const name=input.widget.name;
    let value=node.widgets_values?.[index];
    let port=input;
    const seen=new Set();
    while(port?.link!=null&&!seen.has(port.link)) {
      seen.add(port.link);
      const raw=workflow.links.find(link=>String(Array.isArray(link)?link[0]:link.id)===String(port.link));
      const source=workflow.nodes.find(node=>String(node.id)===String(Array.isArray(raw)?raw[1]:raw?.origin_id));
      if(!['PrimitiveString','PrimitiveStringMultiline'].includes(source?.type))break;
      textNodes.add(String(source.id));
      value=source.widgets_values?.[0];port=source.inputs?.find(input=>(input.widget?.name??input.name)==='value');
    }
    if(value!==undefined)fields[name]=value;
  }
  return fields;
}

export function sameStoryWiring(a,b) {
  const wiring=workflow=>{
    const graph=structuredClone(workflow);
    const graphs=[graph];
    while(graphs.length) {
      const current=graphs.pop();
      graphs.push(...(current.definitions?.subgraphs??[]));
      const textNodes=new Set();
      for(const node of current.nodes??[])if(['H3C_Story','H3C_Timeline'].includes(node.type))savedFields(current,node,textNodes);
      if(current.extra)delete current.extra.ds;
      for(const node of current.nodes??[]) {
        for(const key of ['pos','size','order','title','showAdvanced'])delete node[key];
        if(['H3C_Story','H3C_Timeline'].includes(node.type)) {
          node.widgets_values=Object.fromEntries(Object.entries(savedFields(current,node)).filter(([name])=>!CONTENT_FIELDS.has(name)));
          delete node.widgets_values_named;
          // Uploaded guide and asset registries record media, not generator wiring.
          for(const key of ['h3c_library_revision','h3c_fork_sequence','h3c_project','h3c_asset_bindings','h3c_generation_import','h3c_manual_guides','h3c_uploaded_assets'])
            if(node.properties)delete node.properties[key];
        }
        if(textNodes.has(String(node.id))){delete node.widgets_values;delete node.widgets_values_named;}
        if(node.properties&&!Object.keys(node.properties).length)delete node.properties;
      }
    }
    // Layout and native tab identity do not determine whether saved takes belong to this generator.
    return stringifyJSON({nodes:graph.nodes,links:graph.links,definitions:graph.definitions});
  };
  return wiring(a)===wiring(b);
}

export function savedStoryContent(value,current) {
  const workflow=value.workflow,source=workflow?.nodes?.find(node=>node.type==='H3C_Story'&&String(node.id)===String(value.story));
  const story=savedFields(workflow,source),state=parseJSON(story.state||'{}');
  if(!state||typeof state!=='object'||Array.isArray(state))throw Error('The saved Story state is invalid.');
  const linked=workflow.links?.find(link=>String(Array.isArray(link)?link[1]:link.origin_id)===String(source.id)
    &&workflow.nodes.some(node=>node.type==='H3C_Timeline'&&String(node.id)===String(Array.isArray(link)?link[3]:link.target_id)));
  const targetId=state.timeline||value.job?.timeline||(Array.isArray(linked)?linked[3]:linked?.target_id);
  const target=workflow.nodes.find(node=>node.type==='H3C_Timeline'&&String(node.id)===String(targetId));
  const fields=savedFields(workflow,target),timeline=parseJSON(fields.timeline);
  if(!Array.isArray(timeline?.boxes))throw Error('The saved story has no valid Timeline.');
  const before=stringifyJSON(timeline),result=value.job?.view?.result;
  if(result) {
    const recovered=applyResult(timeline,parseStoryState(story.state),result,String(target.id),Number(fields.context_frames)||39);
    story.state=serializeStoryState(recovered.state);
  }
  // The saved story always keeps its own sequence folder, so its rendered clips come with it. Whether each clip still
  // matches is the Timeline status's call, box by box (layout, settings and references are saved with every take);
  // a wiring difference elsewhere in the workflow never hides them or starts an empty folder.
  const wiring=sameStoryWiring(current,workflow);
  if(!wiring) {
    delete timeline.still_requests;
    if(timeline.reference_preparation)timeline.reference_preparation=settledPreparation(timeline.reference_preparation);
    // In-flight still jobs belong to the other workflow's queue; their finished candidates and guides are kept.
    for(const box of timeline.boxes)for(const preview of box.previews??[])
      for(const key of ['pending','job'])delete preview[key];
  }
  return {story,timeline:before===stringifyJSON(timeline)?fields.timeline:stringifyJSON(timeline),
    sequence:value.sequence,renders:true,wiring,
    project:target.properties?.h3c_project?.mode==='attached'?structuredClone(target.properties.h3c_project):undefined,
    asset_bindings:structuredClone(target.properties?.h3c_asset_bindings)};
}

const MANAGED_SEQUENCE=/^api_([a-f0-9]{8})([a-f0-9]{4})([a-f0-9]{4})([a-f0-9]{4})([a-f0-9]{12})$/;

/** The managed project a saved story belongs to, from its attachment or its reserved sequence; null for a native story. */
export function managedProjectId(content) {
  if(content.project?.mode==='attached'&&content.project.id)return content.project.id;
  const match=MANAGED_SEQUENCE.exec(content.sequence??'');
  return match?match.slice(1).join('-'):null;
}

/** A managed story saves and renders through its project's own saved workflow, never through the open one. Loaded
 *  into another workflow it therefore becomes an independent copy that runs there: its own sequence, no project,
 *  that workflow's models and settings. The project itself is left as it is. The story stays attached in the
 *  project's own workflow: one wired the same, or one whose Timeline is already attached to that project. */
export function independentStoryContent(content,{attached,sequence=()=>'timeline_'+crypto.randomUUID().replaceAll('-','')}={}) {
  const id=managedProjectId(content);
  if(!id||content.wiring||attached===id)return content;
  const {project,asset_bindings,...copy}=content;
  return {...copy,sequence:sequence(),renders:false,independent:true};
}

export function isWiringConflict(error) {
  return error?.code==='h3c_story_wiring_conflict'||/Workflow wiring changed in another browser/.test(error?.message??'');
}

export async function recoverSavedStoryContent(content,request) {
  const match=/^api_([a-f0-9]{8})([a-f0-9]{4})([a-f0-9]{4})([a-f0-9]{4})([a-f0-9]{12})$/.exec(content.sequence);
  if(content.project||!match)return content;
  // Records.create_project derives the public project UUID from its reserved sequence.
  const id=match.slice(1).join('-'),project=await request(`/h3c/api/v1/projects/${id}`);
  if(project?.id!==id||project.sequence!==content.sequence||!Number.isInteger(project.revision)||project.revision<1
    ||typeof project.profile_sha256!=='string'||!project.profile_sha256)
    throw Error('The managed project does not match this saved story. Its local content was kept.');
  return {...content,project:{mode:'attached',id,revision:project.revision,profile_sha256:project.profile_sha256},
    asset_bindings:structuredClone(content.asset_bindings??project.assets??[])};
}

// New project promises to preserve the current project before clearing it.
// A stale imported workflow must save an independent copy, never replace the
// other browser's wiring or discard the local prompts to load that snapshot.
export async function saveBeforeNewProject(story, saved) {
  try {
    await saved.flush();
    await story?.saved.flush();
    await story?.saveLibrary?.(true);
  } catch(error) {
    if(!story?.forkLibrary||!isWiringConflict(error))throw error;
    await story.forkLibrary();
  }
}

export class StoryLibrary {
  constructor(host) { this.host=host; this.pending=false; }
  check() { if(this.host.busy())throw Error('Wait for writing, uploads and rendering to finish before switching stories.'); }
  async refresh() {
    const {stories,names}=await this.host.request('/h3c/stories');
    return {stories,names:names??{}};
  }
  // The name the user wants for a story, null if they cancel; an empty name goes back to the story's own title.
  async ask(group) {
    const name=await this.host.prompt('Name this story. Leave it empty to use its own title.',group.name||group.title);
    return typeof name==='string'?name:null;
  }
  async rename(key,name) {
    if(this.pending)return false;
    this.pending=true;
    try {await this.host.request('/h3c/stories/rename',{key,name});return true;}
    finally {this.pending=false;}
  }
  async open(id) {
    if(this.pending)return;
    this.check();this.pending=true;
    try {
      await this.host.save();
      this.check();
      const revision=this.host.revision?.();
      let value=await this.host.request('/h3c/stories?id='+encodeURIComponent(id));this.check();
      if(value.checkpoint_name) {
        value=await this.host.request('/h3c/stories/restore',{id});this.check();
        value.restored_checkpoint=true;
      }
      if(revision!==undefined&&JSON.stringify(revision)!==JSON.stringify(this.host.revision()))throw Error('The open story changed while loading. Your edits were kept; load again.');
      await this.host.load(value);
    } finally {this.pending=false;}
  }
  async remove(entry) {
    if(this.pending)return false;
    this.check();this.pending=true;
    try {
      if(!await this.host.confirm(`Permanently delete “${entry.title}” and its generated videos, stills and takes? Shared uploads and RefMods are kept. This cannot be undone.`))return false;
      this.check();await this.host.request('/h3c/stories/delete',{id:entry.id});
      await this.host.deleted(entry.id);return true;
    } finally {this.pending=false;}
  }
  // Every version of one story, after one confirmation. Stops at the first failure and says how many were removed.
  async removeAll(group) {
    if(this.pending)return false;
    this.check();this.pending=true;
    let removed=0;
    try {
      const count=group.versions.length;
      if(!await this.host.confirm(`Permanently delete “${group.label}”, all ${count} ${count===1?'version':'versions'}, and their generated videos, stills and takes? Shared uploads and RefMods are kept. This cannot be undone.`))return false;
      for(const entry of group.versions) {
        this.check();await this.host.request('/h3c/stories/delete',{id:entry.id});
        removed++;await this.host.deleted(entry.id);
      }
      // The name belonged to this story only; a failure to clear it leaves a harmless label.
      if(group.name)await this.host.request('/h3c/stories/rename',{key:group.key,name:''}).catch(()=>{});
      return true;
    } catch(error) {
      error.message=`${error.message} (${removed} of ${group.versions.length} versions deleted.)`;
      error.partial=removed>0;throw error;
    } finally {this.pending=false;}
  }
}
