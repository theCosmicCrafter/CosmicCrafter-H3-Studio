// Mounts the H3 Story face on H3C_Story nodes; the Studio of the one linked Timeline shows its actions, story and
// files, and edits its inputs on the Story page. Write posts the workflow snapshot to the server, polls the job and
// writes the result into the linked H3 Timeline. A continuity check, from Check all or a Box page's Check, runs as a
// job the same way; it writes nothing into the Timeline, whose status shows the results. A Write belongs to the page
// and the graph that started it, so the
// panel of a story node that comes back after an undo, a tab switch or a reload follows it again. The API key only
// ever goes to the server's key route. While base_url is linked, the host line and the key box use the base URL that
// the last Write in this page got.
// ?v= tags come from node tools/module_versions.mjs --write, so cached .mjs files cannot mix frontend versions.
import { app } from '../../scripts/app.js';
import { api } from '../../scripts/api.js';
import { mountSavedState, AUTOSAVE_SETTING, autosaveEnabled, userBusy } from './h3c_saved_state.mjs?v=633682c759bb';
import { migrateStoryDescriptionInputs, migrateSerializedStoryDescriptionInputs } from './h3c_story_inputs.mjs?v=46d6a455ab9a';
import { showOwnElement } from './h3c_dom_widget.mjs?v=961e6d7f3bb7';
import * as story from './h3c_story_model.mjs?v=f498e4660a19';
import { StoryPanel } from './h3c_story_panel.mjs?v=790aad382bc2';
import { StoryLibrary, isWiringConflict, saveBeforeNewProject, savedStoryContent, recoverSavedStoryContent, independentStoryContent } from './h3c_story_library.mjs?v=8b88866ede39';
import { exportStory, importStory, downloadStory } from './h3c_story_archive.mjs?v=b07a438d2dc4';
import { parseState, serialize, unknownFeatures, readOnlyNote } from './h3c_timeline_model.mjs?v=1dfc1612e462';

import {exportGeneration,importGeneration,downloadGeneration,generationControl,setGenerationControl} from './h3c_generation_archive.mjs?v=e9481f050000';
import {captureRecipe,hasVideoOutput as compiledVideoOutput} from './h3c_stills.mjs?v=0925953008c8';
import {parseJSON,stringifyJSON} from './h3c_project.mjs?v=0882b8a6265a';

const NODE_TYPE = 'H3C_Story';
const WRITE_URL = '/h3c/story/write';
const CHECK_URL = '/h3c/story/check';
const JOB_URL = '/h3c/story/job';
const CANCEL_URL = '/h3c/story/cancel';
const KEY_URL = '/h3c/story/key';
const KEYS_URL = '/h3c/story/keys';
const CURRENT_URL = '/h3c/story/current';
const TAKEN_URL = '/h3c/story/taken';
const TEMPLATES_URL = '/h3c/story/templates';
const POLL_MS = 750;
const MISSED_POLLS = 20;
const NO_TIMELINE = 'Link this Story to an H3 Timeline’s story input to open the Studio.';
const SEVERAL_TIMELINES = 'This Story feeds several Timelines; open the Studio from one of them.';
// The inputs the Studio's Story page shows: widget name, label, kind and whether it is advanced.
const STUDIO_INPUTS = [['idea', 'Idea', 'text'], ['idea_images', 'Idea images', 'images'], ['template', 'Template', 'template'],
  ['total_seconds', 'Total length (seconds)', 'number'], ['scope', 'Scope', 'combo'],
  ['pictures', 'Send pictures to the writer', 'boolean'],
  ['story_base_url', 'Story API URL', 'string', true], ['story_model', 'Initial story model', 'string', true],
  ['story_thinking', 'Initial story thinking', 'combo', true],
  ['base_url', 'Box API URL', 'string', true], ['model', 'Box writing model', 'string', true],
  ['thinking', 'Box writing thinking', 'combo', true], ['vision_base_url', 'Vision API URL', 'string', true],
  ['vision_model', 'Vision model', 'string', true]];
// The base URL each story node's last Write got while base_url was linked, by graph and node id, until a reload.
const writtenUrls = new Map();
const storyUrls = new Map();
const visionUrls = new Map();
const libraryRevisions = new Map();

function findWidget(node, name) {
  return node.widgets?.find((widget) => widget.name === name);
}

function hide(widget) {
  if (!widget) return;
  widget.hidden = true;
  widget.computeSize = () => [0, -4];
  widget.computeLayoutSize = () => ({ minHeight: 0, maxHeight: 0, minWidth: 0 });
  widget.options = widget.options || {};
  widget.options.hidden = true;
}

// Every Write uses Fast. The retired widget stays so saved workflows still validate.
function retireWritingMode(node) {
  const mode = findWidget(node, 'writing_mode');
  if (mode) { mode.value = 'fast'; hide(mode); }
}

function contextOf(node) {
  return Number.parseInt(findWidget(node, 'context_frames')?.value ?? '39', 10) || 39;
}

function hostOf(url) {
  try {
    return new URL(String(url ?? '').trim()).host.toLowerCase() || null;
  } catch {
    return null;
  }
}

async function readJson(response) {
  if (response.status === 404) throw new Error('ComfyUI has no H3 Story routes yet; restart ComfyUI.');
  if (!response.ok) throw new Error(`ComfyUI answered ${response.status}.`);
  return response.json();
}

async function post(url, body) {
  return readJson(await api.fetchApi(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }));
}

export class StoryHost {
  constructor(node, inputDefinitions) {
    this.node = node;
    this.inputDefinitions = inputDefinitions;
    this.job = null;
    this.starting = false;
    this.uploading = false;
    this.timer = null;
    this.missed = 0;
    this.gone = false;
    this.widget = findWidget(node, 'state');
    hide(this.widget);
    hide(findWidget(node, 'template'));
    hide(findWidget(node, 'idea_images'));
    retireWritingMode(node);
    const panel = new StoryPanel({
      write: (selected) => this.write(selected),
      rewrite: () => this.write(false, true),
      checkAll: () => this.checkAll(),
      cancel: () => this.cancel(),
      undo: () => this.undo(),
      saveKey: (key) => this.saveKey(key),
      saveVisionKey: (key) => this.saveKey(key, 'vision_base_url'),
      saveStoryKey: (key) => this.saveKey(key, 'story_base_url'),
      forgetKey: () => this.saveKey(''),
      exportStory: () => this.exportStory(),
      importStory: (file) => this.importStory(file),
      exportGeneration: () => this.exportGeneration(),
      importGeneration: file => this.importGeneration(file),
      forkGeneration: () => this.forkGeneration(),
      openStudio: () => this.openStudio(),
      settings: () => this.inputs().filter(input => input.name === 'idea_images'),
      setInput: (name, value) => this.setInput(name, value),
      listStories: async () => {
        const {stories,names}=await this.library.refresh(),graph=this.graphId();
        this.libraryId=stories.find(row=>row.graph===graph)?.id;
        return {rows:stories.map(row=>({...row,current:row.graph===graph})),names};
      },
      openSavedStory: id => this.libraryAction(() => this.library.open(id)),
      saveCheckpoint: () => this.libraryAction(() => this.saveCheckpoint()),
      autosaveEnabled: () => autosaveEnabled(app),
      setAutosave: enabled => app.ui.settings.setSettingValue(AUTOSAVE_SETTING, enabled),
      deleteSavedStory: entry => this.libraryAction(async () => { if(await this.library.remove(entry))await panel.refreshStories(); }),
      deleteSavedStoryGroup: group => this.libraryAction(async () => {
        try {if(await this.library.removeAll(group))await panel.refreshStories();}
        catch(error) {if(error.partial)await panel.refreshStories().catch(()=>{});throw error;}
      }),
      renameSavedStory: group => this.libraryAction(async () => {
        const name=await this.library.ask(group);
        if(name!==null&&await this.library.rename(group.key,name))await panel.refreshStories();
      }),
      keepWorkflow: () => this.libraryAction(async () => {
        await this.forkLibrary();
        panel.say('This workflow and its prompts are saved as an independent story. The previous saved story was kept.');
      }),
    });
    this.panel = panel;
    node.h3cStory = this;
    this.saved = mountSavedState(node, panel.root, { app, api, loaded: () => {
      this.showState(); this.showTarget();
    } });
    this.library = new StoryLibrary({
      busy: () => this.libraryBusy(),
      save: () => saveBeforeNewProject(this,this.generationDestination().host.saved),
      request: (url, body) => this.libraryRequest(url, body),
      load: value => this.loadLibrary(value),
      confirm: message => app.extensionManager?.dialog?.confirm?.({title:'Delete saved story',message}) ?? window.confirm(message),
      prompt: (message, value) => app.extensionManager?.dialog?.prompt?.({title:'Rename saved story',message,defaultValue:value}) ?? window.prompt(message,value),
      deleted: async id => {
        if(id===this.libraryId){this.libraryDeleted=this.graphId();this.panel.say('Story permanently deleted. Start a new project before writing again.');}
      },
      revision: () => structuredClone(this.node.graph.serialize()),
    });
    // Saving serializes the workflow twice and sends all of it, so it waits for a pause in typing.
    this.libraryTimer=setInterval(()=>{if(!userBusy())this.saveLibrary().catch(error=>this.panel.say(error.message,true));},5000);
    for (const widget of node.widgets ?? []) this.chain(widget, () => {
      this.saved.changed(); panel.refreshSettings(); this.syncTemplateWidget();
    });
    this.wake = () => {
      if (!this.gone && document.visibilityState !== 'hidden') {
        if (this.job) this.check();
        else this.resume();
      }
    };
    document.addEventListener('visibilitychange', this.wake);
    window.addEventListener('focus', this.wake);
    this.updated = (event) => {
      if (event.detail?.job === this.job?.id) this.check();
    };
    api.addEventListener('h3c-story', this.updated);
    const dom = node.addDOMWidget('h3c_story_panel', 'custom', panel.root, {
      serialize: false,
      hideOnZoom: false,
      getMinHeight: () => panel.height(),
      getMaxHeight: () => panel.height(),
    });
    dom.serialize = false;
    if (dom.options) dom.options.serialize = false;
    dom.computeSize = (width) => [width ?? node.size?.[0] ?? 420, panel.height()];
    dom.computeLayoutSize = () => ({ minHeight: panel.height(), maxHeight: panel.height(), minWidth: 0 });
    this.mountTemplateWidget();
    if (findWidget(node, 'idea_images')) {
      const settingsHeight = () => {
        showOwnElement(node, panel.settingsEl, '.h3cs-settings', app.canvas?.graph);
        return panel.settingsHeight();
      };
      const images = this.imagesWidget = node.addDOMWidget('h3c_story_images', 'custom', panel.settingsEl, {
        serialize:false, hideOnZoom:false, getMinHeight:settingsHeight, getMaxHeight:settingsHeight,
      });
      images.advanced = true; images.serialize = false;
      images.options ??= {}; images.options.advanced = true; images.options.serialize = false;
      images.computeSize = width => [width ?? node.size?.[0] ?? 420, settingsHeight()];
      images.computeLayoutSize = () => ({minHeight:settingsHeight(),maxHeight:settingsHeight(),minWidth:0});
    }
    for (const name of ['base_url', 'story_base_url', 'pictures', 'vision_base_url', 'vision_model']) this.chain(findWidget(node, name), () => this.showTarget());
    this.hook('onConnectionsChange', () => { this.showTarget(); this.relayout(true); });
    this.hook('onConfigure', () => {
      retireWritingMode(this.node);
      hide(this.widget);
      hide(findWidget(this.node, 'template'));
      hide(findWidget(this.node, 'idea_images'));
      this.fixThinking();
      this.showState();
      this.showTarget();
      setTimeout(() => {
        showOwnElement(node, panel.root, '.h3cs-root', app.canvas?.graph);
        if (this.imagesWidget) showOwnElement(node, panel.settingsEl, '.h3cs-settings', app.canvas?.graph);
        // A loading workflow can configure this node before the Timeline it feeds gets its links back.
        this.showTarget();
        this.resume();
      }, 0);
    });
    // Undo, redo, a tab switch and loading a workflow remove every node; the Write goes on for the node that comes
    // back.
    this.hook('onRemoved', () => {
      this.gone = true;
      this.saved.destroy();
      clearInterval(this.libraryTimer);
      clearTimeout(this.timer);
      this.observer?.disconnect();
      document.removeEventListener('visibilitychange', this.wake);
      window.removeEventListener('focus', this.wake);
      api.removeEventListener('h3c-story', this.updated);
    });
    if (typeof ResizeObserver === 'function') {
      this.observer = new ResizeObserver(() => requestAnimationFrame(() => {
        if (!this.gone) this.relayout(true);
      }));
      this.observer.observe(panel.root);
      if (this.imagesWidget) this.observer.observe(panel.settingsEl);
    }
    this.showState();
    this.showTarget();
    this.loadHosts();
  }

  chain(widget, extra) {
    if (!widget) return;
    const previous = widget.callback;
    widget.callback = function (...args) {
      const result = previous?.apply(this, args);
      extra();
      return result;
    };
  }

  libraryBusy() {
    return !!(this.job || this.starting || this.uploading || this.timelines().some(node => node.h3cTimeline?.newProjectBusy()));
  }

  get libraryRevision() {
    const graph=this.node.graph;
    return libraryRevisions.get(graph?.extra?.h3c_story_id??graph?.id)??this.node.properties?.h3c_library_revision;
  }

  set libraryRevision(revision) {
    const graph=this.node.graph,key=graph?.extra?.h3c_story_id??graph?.id;
    if(key&&revision!==undefined)revision=Math.max(revision,libraryRevisions.get(key)??revision);
    if(key) {
      if(revision===undefined)libraryRevisions.delete(key);else libraryRevisions.set(key,revision);
    }
    this.node.properties??={};
    if(revision===undefined)delete this.node.properties.h3c_library_revision;
    else this.node.properties.h3c_library_revision=revision;
  }

  async libraryRequest(url, body) {
    const response=await api.fetchApi(url,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:undefined);
    if(response.status===404)throw Error('Saved stories need a ComfyUI backend restart.');
    const value=await response.json();
    if(!response.ok) {
      const error=Error(value.error??'Could not access saved stories.');
      error.code=value.code;throw error;
    }
    return value;
  }

  async graphDeleted() {
    const result=await this.libraryRequest('/h3c/stories?graph='+encodeURIComponent(this.graphId()));
    if(result.deleted)this.libraryDeleted=this.graphId();return !!result.deleted;
  }

  async saveLibrary(force=false,attempt=0) {
    if(!force&&!autosaveEnabled(app))return;
    if(this.gone||this.node.graph!==(app.rootGraph??app.graph)||this.libraryDeleted===this.graphId())return;
    if(this.library?.pending&&!force)return;
    if(this.forkingLibrary&&!force)return;
    if(force&&await this.graphDeleted())return;
    if(this.savingLibrary){await this.savingLibrary;if(force)return this.saveLibrary(true);return;}
    if(!force&&(!this.state().title||this.starting||this.job))return;
    const save=async()=>{
      await this.saved.flush();
      if(this.gone||this.libraryDeleted===this.graphId())return;
      const graph=this.node.graph;graph.extra??={};graph.extra.h3c_story_id??=this.graphId();
      const workflow=structuredClone(graph.serialize());
      const signature=JSON.stringify(workflow);if(signature===this.librarySignature)return;
      const linked=this.timelines();if(linked.length!==1)throw Error('Connect this Story to one Timeline to save it in the library.');
      const captured=await app.graphToPrompt?.();
      if(!force&&!autosaveEnabled(app))return;
      if(signature!==JSON.stringify(graph.serialize()))return;
      const sequence=findWidget(linked[0],'name')?.value;
      const result=await this.libraryRequest('/h3c/stories',{graph:this.graphId(),story:String(this.node.id),workflow,sequence,
        ...(captured?{prompt:captured.output}:{}),revision:this.saved.revision,library_revision:this.libraryRevision});
      this.libraryRevision=result.revision;this.libraryId=result.id;
      this.libraryConflict=null;this.pendingLibraryFork=null;
      this.panel.showLibraryConflict?.(false);
      const savedNode=workflow.nodes.find(node=>String(node.id)===String(this.node.id));
      savedNode.properties??={};savedNode.properties.h3c_library_revision=this.libraryRevision;
      this.librarySignature=JSON.stringify(workflow);
    };
    this.savingLibrary=save();
    try{await this.savingLibrary;}catch(error) {
      if(isWiringConflict(error)) {
        error.code='h3c_story_wiring_conflict';
        error.message='This workflow differs from the saved story. Use Keep this workflow to save this version, or open a saved story.';
        this.libraryConflict=error;this.panel.showLibraryConflict?.(true);
      }
      throw error;
    }finally{this.savingLibrary=null;}
    if(force&&this.librarySignature!==JSON.stringify(this.node.graph.serialize())) {
      if(attempt>=3)throw Error('The story kept changing while saving. Finish editing and try switching again.');
      return this.saveLibrary(true,attempt+1);
    }
  }

  async forkLibrary() {
    if(this.forkingLibrary)return this.forkingLibrary;
    if(this.libraryBusy())throw Error('Wait for writing, uploads and rendering to finish before keeping this workflow.');
    const graph=this.node.graph;
    const check=()=>{if(this.gone||graph!==(app.rootGraph??app.graph))throw Error('The open workflow changed. Return to it and try again.');};
    check();
    const fork=async()=>{
      if(this.savingLibrary) {
        try{await this.savingLibrary;}catch(error){if(!isWiringConflict(error))throw error;}
      }
      const resume=await this.saved.suspend();
      try {
        check();
        if(this.pendingLibraryFork!==this.graphId()) {
          graph.extra??={};graph.extra.h3c_story_id=crypto.randomUUID();
          this.libraryRevision=undefined;
          this.libraryId=this.librarySignature=this.libraryDeleted=null;
          this.pendingLibraryFork=this.graphId();
        }
        this.node.setDirtyCanvas?.(true,true);
        app.extensionManager?.workflow?.activeWorkflow?.changeTracker?.checkState?.();
        await this.saved.flush();check();
        await this.saveLibrary(true);check();
      } finally {resume();}
    };
    this.forkingLibrary=fork();
    try{return await this.forkingLibrary;}finally{this.forkingLibrary=null;}
  }

  async saveCheckpoint() {
    if(this.library.pending)return;
    this.library.check();
    const message='Name this checkpoint. It preserves this Timeline and its current videos.';
    const name=await (app.extensionManager?.dialog?.prompt?.({title:'Save checkpoint',message,
      defaultValue:this.state().title||'Checkpoint'})??window.prompt(message,this.state().title||'Checkpoint'));
    if(name==null)return;
    if(this.library.pending)return;
    if(!name.trim()||name.trim().length>120)throw Error('Give the checkpoint a name of 1–120 characters.');
    this.library.check();
    const graph=this.node.graph,workflow=structuredClone(graph.serialize());
    workflow.extra??={};workflow.extra.h3c_story_id=this.graphId();
    const {node}=this.generationDestination(),sequence=generationControl(node,'name').value.value;
    this.library.pending=true;
    this.panel.checkpointButton.disabled=true;
    this.panel.say('Saving checkpoint and copying its videos…');
    let resume;
    try {
      resume=await this.saved.suspend();
      if(this.gone||graph!==(app.rootGraph??app.graph))throw Error('Return to the workflow you want to checkpoint.');
      await this.libraryRequest('/h3c/stories/checkpoint',{graph:workflow.extra.h3c_story_id,
        story:String(this.node.id),workflow,sequence,name:name.trim()});
      await this.panel.refreshStories();
      this.panel.say(`Checkpoint “${name.trim()}” saved with its videos. You can keep editing this workflow.`);
    } finally {
      resume?.();this.library.pending=false;this.panel.checkpointButton.disabled=false;
    }
  }

  async libraryAction(action) {
    try {await action();}catch(error){this.panel.say(error.message,true);}
  }

  async loadLibrary(value) {
    if(value.restored_checkpoint) {
      if(await app.loadGraphData(structuredClone(value.workflow),true,true,null)===false)
        throw Error('ComfyUI could not load the checkpoint. Its saved copy is still available.');
      const loaded=(app.rootGraph??app.graph)?._nodes?.find(node=>node.type===NODE_TYPE&&String(node.id)===String(value.story))?.h3cStory;
      loaded?.openStudio();
      loaded?.panel.say('Checkpoint opened as an editable copy with its videos. The saved checkpoint is kept.');
      return;
    }
    const graph=this.node.graph,revision=JSON.stringify(graph.serialize());
    const attached=this.timelines()[0]?.properties?.h3c_project;
    const content=await recoverSavedStoryContent(independentStoryContent(savedStoryContent(value,graph.serialize()),
      {attached:attached?.mode==='attached'?attached.id:undefined}),async path=>{
      const response=await api.fetchApi(path),project=parseJSON(await response.text());
      if(!response.ok)throw Error(project.error?.message??'Could not reconnect the saved story to its managed project.');
      return project;
    });
    const resume=await this.saved.suspend();
    try {
      if(this.gone||graph!==(app.rootGraph??app.graph)||revision!==JSON.stringify(graph.serialize()))
        throw Error('The open story changed while loading. Your edits were kept; load again.');
      if(this.libraryBusy())throw Error('Wait for writing, uploads and rendering to finish before switching stories.');
      // An independent copy starts its own library entry; the managed story keeps its saved workflow.
      const samePair=!content.independent&&graph._nodes.filter(node=>['H3C_Story','H3C_Timeline'].includes(node.type)).length===2;
      // Continue the saved story itself (its library entry and autosaves), never a new copy of it.
      this.applyGeneration(content,samePair?{graphId:value.graph,revision:value.workflow_revision,libraryId:value.id}:{});
      this.openStudio();
      this.panel.say(content.independent?'Story loaded into this workflow as an independent copy. It renders with this workflow\u2019s models and settings; the managed project it came from is unchanged.'
        :content.wiring?'Story loaded into this workflow.':'Story loaded into this workflow with its rendered clips. The wiring of this workflow differs from the saved one; clips whose render settings changed show as outdated.');
    } finally {resume();}
  }

  generationDestination() {
    const nodes=this.timelines();
    if(nodes.length!==1)throw Error('Connect this Story to one selected Timeline before transferring a generation.');
    const node=nodes[0],host=node.h3cTimeline;
    if(!host)throw Error('The destination Studio is not ready.');
    for(const [owner,names]of [[node,['name','timeline']],[this.node,['idea','state','idea_images','template']]])
      for(const name of names)generationControl(owner,name);
    return {node,host};
  }

  async generationRenderer() {
    const {node}=this.generationDestination(),snapshot=await app.graphToPrompt();
    return captureRecipe(snapshot,String(node.id))?.adapter==='pixels'&&!compiledVideoOutput(snapshot,String(node.id))?'image':'video';
  }

  generationRevision() {
    const graph=structuredClone(this.node.graph.serialize());
    for(const node of graph.nodes??[])if(node.properties)delete node.properties.h3c_generation_import;
    return stringifyJSON(graph);
  }

  generationBusy() {return this.generationDestination().host.newProjectBusy();}

  async generationReady() {
    const {host}=this.generationDestination();
    const busy=host.newProjectBusy();if(busy)throw Error(busy);
    await this.saved.flush();await host.saved.flush();
    await this.saveLibrary(true);
    if(host.newProjectBusy())throw Error('The destination became busy during transfer.');
    this.generationPending=this.node.properties?.h3c_generation_import??this.generationPending;
  }

  setGenerationPending(value) {
    this.node.properties??={};
    if(value)this.node.properties.h3c_generation_import=structuredClone(value);else delete this.node.properties.h3c_generation_import;
  }

  async requestGeneration(path,body) {
    const response=await api.fetchApi(path,{method:'POST',headers:{'Content-Type':'application/json'},body:stringifyJSON(body)});
    const result=parseJSON(await response.text());if(!response.ok||!result.ok)throw Error(result.error??'Generation transfer failed.');return result;
  }

  async readGeneration() {
    await this.generationReady();const {node,host}=this.generationDestination();
    const timeline=generationControl(node,'timeline').value.value,references={},line=parseState(timeline);
    for(const refs of Object.values(host.referenceSources(true,line)))for(const ref of refs) {
      if(ref.refmod||line.disabled_refs?.includes(ref.name)||line.reference_replacements?.[ref.name])continue;
      references[ref.name]=ref.mediaFile?{file:ref.mediaFile}:{computed:true};
    }
    const fields={};for(const name of ['idea','state','idea_images','template']){const widget=findWidget(this.node,name);if(widget)fields[name]=generationControl(this.node,name).value.value;}
    const snapshot=await app.graphToPrompt();
    return {name:host.project?.project?.sequence??generationControl(node,'name').value.value,timeline,story:fields,references,
      writing:!!(this.job||this.starting),origin:{workflow: snapshot.workflow,renderer:snapshot.output}};
  }

  applyGeneration(result, {graphId=crypto.randomUUID(),revision,libraryId}={}) {
    const {node,host}=this.generationDestination(),graph=this.node.graph;
    const state=parseJSON(result.story.state||'{}');state.timeline=String(node.id);
    const updates=[[node,'name',result.sequence],[node,'timeline',result.timeline],[this.node,'state',stringifyJSON(state)],
      ...Object.entries(result.story).filter(([name])=>['idea','idea_images','template'].includes(name)&&findWidget(this.node,name)).map(([name,value])=>[this.node,name,value])];
    const writes=updates.map(([owner,name,value])=>({control:generationControl(owner,name),value}));
    const values=new Map();for(const {control,value}of writes){if(values.has(control.value)&&values.get(control.value)!==value)throw Error(`${control.label} shares a text control with another imported field. Give these fields separate Text controls.`);values.set(control.value,value);}
    const tracker=app.extensionManager?.workflow?.activeWorkflow?.changeTracker;
    (tracker?.captureCanvasState??tracker?.checkState)?.call(tracker);
    // Keep autosaves with this story while retaining every node, link and generator control.
    graph.extra??={};graph.extra.h3c_story_id=graphId;this.libraryRevision=revision;
    this.libraryId=libraryId??null;
    this.librarySignature=this.libraryDeleted=this.finishedJob=this.libraryConflict=this.pendingLibraryFork=null;
    this.panel.showLibraryConflict?.(false);
    node.properties??={};
    if(result.project?.mode==='attached') {
      node.properties.h3c_project=structuredClone(result.project);
      delete node.properties.h3c_fork_sequence;
    } else {
      node.properties.h3c_fork_sequence=result.sequence;
      delete node.properties.h3c_project;
    }
    if(result.asset_bindings!==undefined)node.properties.h3c_asset_bindings=structuredClone(result.asset_bindings);
    else delete node.properties.h3c_asset_bindings;
    for(const {control,value}of writes)setGenerationControl(control,value);
    host.configureProject({preserveLocal:result.project?.mode==='attached'});host.editor.load();host.changed();this.showState();this.saved.changed();
    graph.setDirtyCanvas?.(true,true);(tracker?.captureCanvasState??tracker?.checkState)?.call(tracker);
  }

  async exportGeneration() {
    try {downloadGeneration(await exportGeneration(this));this.panel.say('Generation exported with verified local media.');}
    catch(error){this.panel.say(error.message,true);}
  }

  async importGeneration(file) {
    try {const archive=parseJSON(await file.text());await importGeneration(this,archive);this.panel.say('Generation imported into this workflow. Its generator is ready.');}
    catch(error){this.panel.say(error.message,true);}
  }

  // Branch the film: the current generation downloads as a file (the way back to it), then this workflow continues on
  // a copy with every render and take, so alternative continuations never touch the original sequence.
  async forkGeneration() {
    try {
      const archive=await exportGeneration(this);downloadGeneration(archive);
      const result=await importGeneration(this,archive);
      this.panel.say(`Forked into ${result.sequence}. The original stays as it was; import the downloaded file to go back to it.`);
    }
    catch(error){this.panel.say(error.message,true);}
  }

  async exportStory() {
    try {
      await this.saved.flush();
      downloadStory(exportStory(app.rootGraph ?? app.graph, this.state().title));
      this.panel.say('Story exported, including the Timeline and workflow wiring.');
    } catch (error) { this.panel.say(error.message, true); }
  }

  async importStory(file) {
    try {
      let archive;
      try { archive = JSON.parse(await file.text()); }
      catch { throw new Error('This file is not valid JSON. Choose an H3 Story export.'); }
      await importStory(app, archive);
    } catch (error) { this.panel.say(error.message, true); }
  }

  hook(name, extra) {
    const previous = this.node[name];
    this.node[name] = function (...args) {
      const result = previous?.apply(this, args);
      extra(...args);
      return result;
    };
  }

  relayout(fit = false) {
    const node = this.node;
    if (!node.size || typeof node.computeSize !== 'function') return;
    // Nodes 2.0 measures its visible widgets. Keep only the panel's intrinsic minimum;
    // the classic estimate includes advanced widgets even while Vue hides them.
    const needed = app.ui?.settings?.getSettingValue('Comfy.VueNodes.Enabled')
      ? this.panel.height() : Number(node.computeSize()?.[1]) || 0;
    if (fit || needed > node.size[1] + 1) node.setSize?.([node.size[0], needed]);
    node.setDirtyCanvas?.(true, true);
  }

  state() {
    return story.parseStoryState(this.widget?.value);
  }

  setState(state) {
    this.widget.value = story.serializeStoryState(state);
    this.saved.changed();
    this.showState();
    this.node.setDirtyCanvas?.(true, true);
    app.extensionManager?.workflow?.activeWorkflow?.changeTracker?.checkState?.();
  }

  timeline(id) {
    const graph = app.rootGraph ?? app.graph;
    const node = graph?.getNodeById?.(id) ?? graph?.getNodeById?.(Number(id));
    const widget = node && findWidget(node, 'timeline');
    return widget ? { node, widget } : null;
  }

  numberOf(state) {
    const found = state.timeline ? this.timeline(state.timeline) : null;
    const boxes = found ? parseState(found.widget.value).boxes : [];
    const numbers = new Map(boxes.map((box, index) => [box.id, index + 1]));
    return (id) => numbers.get(id) ?? null;
  }

  showState() {
    const state = this.state();
    this.panel.showStory(state, this.numberOf(state));
    if (!this.job && !this.starting) this.panel.idle(story.canUndo(state));
  }

  showTarget() {
    this.panel.refreshSettings();
    this.syncTemplateWidget();
    const timelines = this.timelines().length;
    this.panel.showStudio(timelines === 1 ? null : timelines ? SEVERAL_TIMELINES : NO_TIMELINE);
    const vision = findWidget(this.node, 'pictures')?.value === false
      && (!!findWidget(this.node, 'vision_model')?.value || this.linked('vision_model'));
    const hosts = [...new Set((vision ? [this.baseUrl('vision_base_url')]
      : [this.baseUrl('story_base_url'), this.baseUrl()]).map(hostOf))];
    this.panel.showTarget(story.targetText({
      pictures: vision || findWidget(this.node, 'pictures')?.value !== false,
      host: hosts.every(Boolean) ? hosts.join(' and ') : null,
    }));
  }

  // The Timeline nodes whose story input this node feeds.
  timelines() {
    const graph = this.node.graph;
    return (graph?._nodes ?? []).filter(node => {
      if (node.type !== 'H3C_Timeline') return false;
      const input = node.inputs?.find(input => input.name === 'story');
      const link = graph.links?.get?.(input?.link) ?? graph.links?.[input?.link];
      return link && String(link.origin_id) === String(this.node.id);
    });
  }

  openStudio() {
    const timelines = this.timelines();
    if (timelines.length === 1) timelines[0].h3cTimeline?.openStudio('story');
  }

  // The inputs the Studio's Story page edits. linked is the title of the node a linked input comes from, or null;
  // a template input's load() lists the templates.
  inputs() {
    return STUDIO_INPUTS.flatMap(([name, label, kind, advanced = false]) => {
      const widget = findWidget(this.node, name);
      if (!widget) return [];
      const options = widget.options ?? {};
      const values = typeof options.values === 'function' ? options.values() : options.values;
      return [{ name, label, kind, advanced, tooltip: this.inputDefinitions[name]?.[1]?.tooltip ?? '',
        value: widget.value, linked: this.linkedTitle(name),
        ...(kind === 'combo' ? { options: values ?? [] } : {}),
        ...(kind === 'number' ? { min: options.min ?? 0, max: options.max ?? 600 } : {}),
        ...(kind === 'template' ? { load: () => this.templates() } : {}),
        ...(kind === 'images' ? {read: () => widget.value, upload: (files) => this.uploadIdeaImages(files),
          busy: () => this.uploading, onChange: (refresh) => { this.refreshIdeaImages = refresh; },
          viewUrl: (file) => api.apiURL(`/view?${new URLSearchParams(file)}`)} : {}) }];
    });
  }

  async uploadIdeaImages(files) {
    this.uploading = true;
    this.refreshIdeaImages?.();
    try {
      const uploaded = [];
      for (const file of files) {
        const body = new FormData();
        body.append('image', file); body.append('type', 'input'); body.append('subfolder', 'h3_ideas');
        const result = await readJson(await api.fetchApi('/upload/image', {method: 'POST', body}));
        uploaded.push({file: {filename: result.name, subfolder: result.subfolder, type: result.type}});
      }
      return uploaded;
    } catch (error) {
      this.panel.say(`Could not upload idea images: ${error.message}`, true);
      throw error;
    } finally { this.uploading = false; this.refreshIdeaImages?.(); }
  }

  // The template folder and the examples, as ComfyUI lists them.
  async templates() {
    return readJson(await api.fetchApi(TEMPLATES_URL));
  }

  mountTemplateWidget() {
    if (!findWidget(this.node, 'template')) return;
    const add = (type, name, value, callback, options) => {
      const widget = this.node.addWidget(type,name,value,callback,{...options,serialize:false,advanced:true});
      widget.advanced = true; widget.serialize = false;
      return widget;
    };
    this.emptyTemplateChoice = 'None';
    this.templateWidget = add('combo','h3c_template','None', value => this.setInput('template',value === this.emptyTemplateChoice ? '' : value), {values:['None']});
    this.templateWidget.label = 'Template';
    this.templateRefresh = add('button','h3c_refresh_templates',null, () => this.loadTemplateOptions(), {});
    this.templateRefresh.label = 'Refresh templates';
    this.loadTemplateOptions();
  }

  syncTemplateWidget() {
    if (!this.templateWidget) return;
    const value = String(findWidget(this.node,'template').value || '');
    const ids = [...(this.templateListing?.templates ?? []),...(this.templateListing?.examples ?? [])].map(item => item.id);
    const choices = [...new Set([...ids,...(value ? [value] : [])])];
    let empty = 'None';
    while (choices.includes(empty)) empty = `(${empty})`;
    this.emptyTemplateChoice = empty;
    this.templateWidget.options.values = [empty,...choices];
    this.templateWidget.value = value || empty;
    const linked = this.linkedTitle('template');
    this.templateWidget.disabled = linked != null; this.templateWidget.options.disabled = linked != null;
    this.templateWidget.tooltip = linked != null ? `Linked from ${linked}` : this.templateListing?.problem ?? 'Template used to write this Story.';
  }

  async loadTemplateOptions() {
    if (this.gone || this.loadingTemplates) return;
    this.loadingTemplates = true; this.templateRefresh.disabled = this.templateRefresh.options.disabled = true;
    try { this.templateListing = await this.templates(); this.syncTemplateWidget(); }
    catch (error) { this.templateWidget.tooltip = `Could not list templates: ${error.message}`; }
    finally { this.loadingTemplates = false; this.templateRefresh.disabled = this.templateRefresh.options.disabled = false; this.node.setDirtyCanvas?.(true,true); }
  }

  setInput(name, value) {
    if (this.linkedTitle(name) != null) return;
    const widget = findWidget(this.node, name);
    if (!widget) return;
    widget.value = value;
    widget.callback?.(value);
    if (name === 'idea_images') this.refreshIdeaImages?.();
    this.node.setDirtyCanvas?.(true, true);
    app.extensionManager?.workflow?.activeWorkflow?.changeTracker?.checkState?.();
  }

  linkedTitle(name) {
    const input = this.node.inputs?.find((slot) => slot.name === name || slot.widget?.name === name);
    if (input?.link == null) return null;
    const graph = this.node.graph;
    const link = graph?.links?.get?.(input.link) ?? graph?.links?.[input.link];
    const origin = link ? graph.getNodeById?.(link.origin_id) : null;
    return origin?.title || origin?.type || 'another node';
  }

  linked(name) {
    return this.node.inputs?.find((input) => input.name === name)?.link != null;
  }

  urlKey() {
    return `${this.graphId()}:${this.node.id}`;
  }

  baseUrl(name = 'base_url') {
    const written = name === 'story_base_url' ? storyUrls : name === 'vision_base_url' ? visionUrls : writtenUrls;
    return story.panelBaseUrl({
      linked: this.linked(name),
      typed: findWidget(this.node, name)?.value || (name === 'base_url' ? '' : this.baseUrl()),
      written: written.get(this.urlKey()),
    });
  }

  // A workflow saved while vision_model was the story node's last input has that value where thinking is now.
  fixThinking() {
    const widget = findWidget(this.node, 'thinking');
    if (widget && ['on', 'model default'].includes(widget.value)) widget.value = 'medium';
    const choices = widget?.options?.values;
    if (Array.isArray(choices) && !choices.includes(widget.value)) widget.value = 'medium';
  }

  async loadHosts() {
    try {
      this.panel.showHosts((await readJson(await api.fetchApi(KEYS_URL))).hosts ?? []);
    } catch {
      this.panel.showHosts(null);
    }
  }

  async saveKey(key, name = 'base_url') {
    const baseUrl = this.baseUrl(name);
    if (!baseUrl && (this.linked(name) || this.linked('base_url'))) {
      const linked = this.linked(name) ? name : 'base_url';
      this.panel.say(`${linked} is linked; press Write once so the panel knows its host.`, true);
      return;
    }
    try {
      const answer = await post(KEY_URL, { base_url: baseUrl, key });
      if (!answer.ok) throw new Error(answer.error);
      this.panel.showHosts(answer.hosts);
      this.panel.say(`${key ? 'Saved' : 'Forgot'} the key for ${hostOf(baseUrl)}.`);
    } catch (error) {
      this.panel.say(error?.message ?? String(error), true);
    }
  }

  async write(selected = false, rewriteAll = false, edit = null) {
    if(this.libraryDeleted===this.graphId()){this.panel.say('This story was permanently deleted. Start a new project to write again.',true);return false;}
    if (this.uploading) { this.panel.say('Wait for the idea images to finish uploading.'); return; }
    if (this.job || this.starting) return;
    this.starting = true;
    try {
      this.panel.busy('Starting...');
      await this.saved.flush();
      const inRoot = this.node.graph === (app.rootGraph ?? app.graph);
      const { output } = await app.graphToPrompt();
      let box;
      if (selected) {
        const linked = Object.entries(output).find(([, item]) => item.class_type === 'H3C_Timeline'
          && String(item.inputs?.story?.[0]) === String(this.node.id));
        box = linked && this.timeline(linked[0])?.node.h3cTimeline?.editor.box()?.id;
        if (!box) throw new Error('Select a box in the linked H3 Timeline first.');
      }
      const answer = await post(WRITE_URL, {
        prompt: output,
        story: inRoot ? String(this.node.id) : `subgraph:${this.node.id}`,
        client: this.clientId(),
        graph: this.graphId(),
        ...(inRoot ? {workflow:{...structuredClone(this.node.graph.serialize()),extra:{...this.node.graph.extra,h3c_story_id:this.graphId()}},revision:this.saved.revision,library_revision:this.libraryRevision} : {}),
        ...(box ? { box } : {}),
        ...(rewriteAll ? {rewrite_all: true} : {}),
        ...(edit ? {edit} : {}),
      });
      if (!answer.ok) throw new Error(answer.error);
      if(answer.library){this.libraryRevision=answer.library.revision;this.libraryId=answer.library.id;}
      this.job = { id: answer.job, timeline: answer.timeline };
      this.missed = 0;
      this.redraw(answer.timeline);
      this.poll();
      return true;
    } catch (error) {
      this.finish(error?.message ?? String(error), true);
      return false;
    } finally { this.starting = false; }
  }

  // Checks the boxes with ids `boxes` of the linked Timeline, or with null every rendered box without a current check.
  async checkBoxes(boxes = null) {
    if (this.job || this.starting) return false;
    this.starting = true;
    try {
      this.panel.busy('Starting the check...');
      await this.saved.flush();
      const inRoot = this.node.graph === (app.rootGraph ?? app.graph);
      const { output } = await app.graphToPrompt();
      const answer = await post(CHECK_URL, {
        prompt: output,
        story: inRoot ? String(this.node.id) : `subgraph:${this.node.id}`,
        client: this.clientId(),
        graph: this.graphId(),
        ...(boxes ? { boxes } : {}),
      });
      if (!answer.ok) throw new Error(answer.error);
      this.job = { id: answer.job, timeline: answer.timeline, kind: 'check' };
      this.missed = 0;
      this.redraw(answer.timeline);
      this.poll();
      return true;
    } catch (error) {
      this.finish(error?.message ?? String(error), true);
      return false;
    } finally { this.starting = false; }
  }

  checkAll() {
    return this.checkBoxes(null);
  }

  // The Box page's Check and the feedback button of Timeline `id` turn off while a job runs.
  redraw(id) {
    if (id != null) this.timeline(id)?.node.h3cTimeline?.editor?.renderHead();
  }

  clientId() {
    return String(api.clientId ?? api.initialClientId ?? '');
  }

  graphId() {
    const graph=app.rootGraph??app.graph;return String(graph?.extra?.h3c_story_id??graph?.id??'');
  }

  // Follows the Write that this page started from this node, when no panel has shown how it ended.
  async resume() {
    if (this.job || this.starting || this.gone || this.node.graph !== (app.rootGraph ?? app.graph)) return;
    try { await this.saved.flush(); } catch { return; }
    if (this.job || this.starting || this.gone) return;
    const query = new URLSearchParams({ client: this.clientId(), graph: this.graphId(), story: String(this.node.id),
      recover: 'true' });
    let found;
    try {
      found = await readJson(await api.fetchApi(`${CURRENT_URL}?${query}`));
    } catch {
      return;
    }
    if (!found?.job || found.kind === 'still_prompts' || found.job === this.finishedJob || this.job || this.starting || this.gone) return;
    this.job = { id: found.job, timeline: found.timeline, ...(found.kind ? { kind: found.kind } : {}) };
    this.missed = 0;
    this.panel.busy('');
    this.check();
  }

  poll() {
    clearTimeout(this.timer);
    if (!this.gone) this.timer = setTimeout(() => this.check(), POLL_MS);
  }

  async check() {
    const job = this.job;
    if (!job || this.gone || this.checking) return;
    this.checking = true;
    let view;
    try {
      const query = new URLSearchParams({ id: job.id, graph: this.graphId(), story: String(this.node.id) });
      view = await readJson(await api.fetchApi(`${JOB_URL}?${query}`));
      this.missed = 0;
    } catch {
      if (this.gone) return;
      this.missed += 1;
      if (this.missed >= MISSED_POLLS) this.finish("ComfyUI isn't answering.", true);
      else this.poll();
      return;
    } finally {
      this.checking = false;
    }
    if (job !== this.job || this.gone) return;
    if (job.kind === 'check') {
      this.followCheck(job, view);
      return;
    }
    if (view.base_url && this.linked('base_url') && view.base_url !== writtenUrls.get(this.urlKey())) {
      writtenUrls.set(this.urlKey(), view.base_url);
      this.showTarget();
    }
    if (view.vision_base_url && this.linked('vision_base_url')) {
      visionUrls.set(this.urlKey(), view.vision_base_url);
      this.showTarget();
    }
    if (view.story_base_url && this.linked('story_base_url')) {
      storyUrls.set(this.urlKey(), view.story_base_url);
      this.showTarget();
    }
    const vram = view.vram ? ` ${view.vram}` : '';
    let outcome;
    try {
      outcome = view.result ? this.apply(job, view.result) : null;
      if (view.drafts && !view.result) {
        const state = this.state();
        this.setState({...state, drafts: {...state.drafts, ...view.drafts}});
      }
    } catch (error) {
      this.finish(`Could not validate the current workflow: ${error?.message ?? error}`, true);
      return;
    }
    if (view.state === 'running') {
      this.panel.busy(view.progress);
      this.poll();
      return;
    }
    this.finishedJob = job.id;
    if (view.state === 'interrupted') this.finish(view.progress);
    else if (outcome?.dropped) this.finish(`${story.DROPPED}${vram}`);
    else if (view.state === 'done' || view.state === 'partial') {
      this.finish(outcome ? `${story.resultMessage(outcome, outcome.timeline)}${vram}`
        : `The linked Timeline is gone, so nothing was written.${vram}`, !outcome || outcome.failed > 0);
    } else if (view.state === 'cancelled') this.finish(`Cancelled. Completed box prompts were kept.${vram}`);
    else if (view.state === 'unknown') this.finish('The Write was lost, probably because ComfyUI restarted.', true);
    else this.finish(`${view.error ?? 'Write failed.'}${vram}`, true);
    if (view.state !== 'unknown') post(TAKEN_URL, { job: job.id }).catch(() => {});
  }

  // A check saves its results on the server; when it ends, the Timeline's status is read again to show them.
  followCheck(job, view) {
    if (view.state === 'running') {
      this.panel.busy(view.progress);
      this.poll();
      return;
    }
    this.finishedJob = job.id;
    const vram = view.vram ? ` ${view.vram}` : '';
    const notes = view.notes?.length ? ` ${view.notes.join(' ')}` : '';
    if (view.state === 'done' || view.state === 'cancelled') this.finish(`${view.progress}${notes}${vram}`);
    else if (view.state === 'unknown') this.finish('The check was lost, probably because ComfyUI restarted.', true);
    else this.finish(`${view.error ?? 'The check failed.'}${notes}${vram}`, true);
    if (view.state !== 'unknown') post(TAKEN_URL, { job: job.id }).catch(() => {});
    this.redraw(job.timeline);
    this.timeline(job.timeline)?.node.h3cTimeline?.schedule(0);
  }

  // Apply the cumulative result once per box, retaining Undo across polls and reconnects.
  apply(job, result) {
    const found = this.timeline(job.timeline);
    if (!found) return null;
    const timeline = parseState(found.widget.value);
    const outcome = story.applyResult(timeline, this.state(), result, job.timeline, contextOf(found.node));
    if (outcome.dropped) return outcome;
    if (outcome.applied || outcome.planned || outcome.metadataChanged) this.replaceTimeline(found, serialize(timeline));
    const editor = found.node.h3cTimeline?.editor;
    if (outcome.applied && editor && !editor.box()?.prompt) {
      const written = timeline.boxes.findIndex((box) => result.prompts?.[box.id]?.text);
      if (written >= 0) editor.select(written);
    }
    if (story.serializeStoryState(outcome.state) !== this.widget.value) this.setState(outcome.state);
    const state = outcome.state;
    return { ...outcome, timeline, planned: state.created.length,
      applied: Object.keys(state.undo).length + state.created.filter((id) => state.written[id]).length };
  }

  // Write and Undo make the text from parseState, which drops what this Studio doesn't know, so a Timeline from a
  // newer one is never replaced.
  replaceTimeline({ node, widget }, text) {
    const unknown = unknownFeatures(parseState(widget.value));
    if (unknown.length) throw new Error(readOnlyNote(unknown));
    if (node.h3cTimeline?.replaceTimeline) {
      node.h3cTimeline.replaceTimeline(text);
    } else {
      widget.value = text;
      node.setDirtyCanvas?.(true, true);
    }
  }

  async cancel() {
    if (!this.job) return;
    try {
      await post(CANCEL_URL, { job: this.job.id });
    } catch {
      // The next poll reports how the Write ended.
    }
  }

  undo() {
    const state = this.state();
    const found = state.timeline ? this.timeline(state.timeline) : null;
    if (!found) {
      this.panel.say('The Timeline of the last Write is gone, so there is nothing to undo.', true);
      return;
    }
    const timeline = parseState(found.widget.value);
    const { restored, state: next } = story.undo(timeline, state, contextOf(found.node));
    try {
      if (restored) this.replaceTimeline(found, serialize(timeline));
    } catch (error) {
      this.panel.say(error.message, true);
      return;
    }
    this.setState(next);
    this.panel.say(next.notes.length ? 'Undone, except the boxes in the notes.' : 'Undone.');
  }

  finish(message, error = false) {
    clearTimeout(this.timer);
    this.job = null;
    this.panel.idle(story.canUndo(this.state()));
    this.panel.say(message, error);
    const linked = this.state().timeline;
    if (linked) this.timeline(linked)?.node.h3cTimeline?.editor?.renderHead();
  }
}

app.registerExtension({
  name: 'h3c.story',
  settings: [{id:AUTOSAVE_SETTING, name:'Autosave Story and Timeline edits', type:'boolean', defaultValue:true,
    category:['H3 Continuity','Story','Autosave'],
    tooltip:'Save edits and the current Story library entry automatically. Turn off to save only when you explicitly save a checkpoint or run an action that requires saving.'}],
  beforeConfigureGraph(graphData) {
    migrateSerializedStoryDescriptionInputs(graphData);
  },
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData?.name !== NODE_TYPE) return;
    const onConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function (...args) {
      migrateStoryDescriptionInputs(this);
      return onConfigure?.apply(this, args);
    };
    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function (...args) {
      const result = onNodeCreated?.apply(this, args);
      if (!findWidget(this, 'state')) return result;
      const host = new StoryHost(this, {...nodeData.input?.required, ...nodeData.input?.optional});
      this.setSize?.([Math.max(this.size?.[0] ?? 0, 420), Number(this.computeSize?.()?.[1]) || host.panel.height()]);
      return result;
    };
  },
});
