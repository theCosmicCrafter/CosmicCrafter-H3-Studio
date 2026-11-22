import {ReferenceClient,applyReferenceApproval,requiredAssets,preparationOf} from './h3c_reference_preparation.mjs?v=d05409662438';
import {generationControl,setGenerationControl} from './h3c_generation_archive.mjs?v=e9481f050000';
// Mounts the H3 Timeline face on H3C_Timeline nodes, edits the Timeline in the Studio, and keeps its status in sync
// with the server. Browsers may cache the .mjs helpers, so their ?v= tags come from node tools/module_versions.mjs --write.
import { freshProject } from './h3c_new_project.mjs?v=96adbc29f06d';
import { saveBeforeNewProject } from './h3c_story_library.mjs?v=8b88866ede39';
import { app } from '../../scripts/app.js';
import {syncImageOutputs,compileImageOutputs} from './h3c_timeline_images.mjs?v=f276b2ccd8b2';
import { api } from '../../scripts/api.js';
import { mountSavedState, autosaveEnabled, AUTOSAVE_IDLE_MS, AUTOSAVE_OFF, userBusy, releaseUser } from './h3c_saved_state.mjs?v=633682c759bb';
import {setText} from './h3c_dom.mjs?v=584a9bf55653';
import { showOwnElement } from './h3c_dom_widget.mjs?v=961e6d7f3bb7';
import { WATCH_EVENTS, idleWatch, progressText, watchEvent } from './h3c_render_watch.mjs?v=7c8222569836';
import { DEFAULT_AHEAD, QueueFeed, feedNote, queueAhead } from './h3c_queue_feed.mjs?v=9392f926e4e3';
import { studio } from './h3c_studio.mjs?v=44a6bea48e14';
import { FACE_HEIGHT, TimelineFace } from './h3c_timeline_face.mjs?v=f87ad7bf252b';
import { TimelineEditor } from './h3c_timeline_editor.mjs?v=f9e6904cc895';
import { referenceFile, referenceSource, referencePools, referenceType, effectiveRefmods, parseState, serialize, unknownFeatures, readOnlyNote } from './h3c_timeline_model.mjs?v=1dfc1612e462';
import {referenceImageFile} from './h3c_reference_sources.mjs?v=107846e10a11';
import { pictureRefs } from './h3c_pictures.mjs?v=220c235a7923';
import { voiceRefs } from './h3c_voices.mjs?v=efb0f83d17e1';
import {captureRecipe,captureTimelineId,captureStillBody,stillTimelineBody,recipeControls,StillClient,isolateVideoPrompt,videoOutputs,hasVideoOutput as compiledVideoOutput,graphWiring} from './h3c_stills.mjs?v=0925953008c8';
import {boundarySnapshot} from './h3c_frame_images.mjs?v=8328028de648';
import {stillPromptSource,sameStillPromptSource} from './h3c_still_prompt_preparation.mjs?v=9ea1bfd9b6b5';
import { TakesClient } from './h3c_takes.mjs?v=15deab5acdd6';
import {ProjectSession, forkProject, parseJSON, projectErrorMessage, stringifyJSON} from './h3c_project.mjs?v=0882b8a6265a';
import {TimelineHistory, dropReceipts, withLiveReceipts} from './h3c_history.mjs?v=7fd74e6b1728';
import {confirmRegeneration} from './h3c_regeneration.mjs?v=44ff3a1a199c';
import {startGeneration,useGeneration} from './h3c_generations.mjs?v=2ed8014b9ec0';

const NODE_TYPE = 'H3C_Timeline';
const STATUS_URL = '/h3c/timeline/status';
const BIBLE_URL = '/h3c/timeline/bible';
const SETTINGS = ['width', 'height', 'context_frames', 'carry_audio', 'ref_image_size', 'audio_context_frames'];
const MUTED = 2;
const BYPASSED = 4;
// The still panel serializes the workflow (~100 ms on a large one) and asks the server for each clip it opens; it waits
// until the Timeline has been quiet this long, so an edit or a click through the clips never pays for it.
const STILL_QUIET_MS = 600;
// A workflow's video-output answer is reused while its graph keeps the same version, for at most this long (a node muted or
// bypassed does not change the version).
const VIDEO_ANSWER_MS = 2000;
// A still or reference request the server could not report on is asked about again this often; one it is running, every 3 s.
const UNKNOWN_RECHECK_MS = 30000;
const QUEUE_AHEAD_SETTING = 'H3C.Timeline.QueueAhead';
const RUN_ENDS = new Set(['execution_success', 'execution_error', 'execution_interrupted']);
const mounted = new Set();
const projectSessions = new Map();

// The Studio fills the page, so the graph canvas under it stops drawing while it is open: ComfyUI redraws the whole
// workflow after each edit, behind the Studio, before the edit can show.
let pausedBefore = null;
function coverCanvas(covered) {
  const canvas = app.canvas;
  if (!canvas) return;
  if (covered) {
    pausedBefore ??= !!canvas.pause_rendering;
    canvas.pause_rendering = true;
  } else if (pausedBefore != null) {
    canvas.pause_rendering = pausedBefore;
    pausedBefore = null;
    canvas.setDirty?.(true, true);
  }
}

// Resolves once the next frame has painted, or after 100 ms on a page that draws no frames (one in the background).
function afterPaint() {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, 100);
    requestAnimationFrame(() => { clearTimeout(timer); setTimeout(resolve, 0); });
  });
}
// ComfyUI's render progress for the whole page; every Timeline face and the Studio read it.
let watch = idleWatch();

function findWidget(node, name) {
  return node.widgets?.find((widget) => widget.name === name);
}

function isLinked(node, name) {
  const input = node.inputs?.find((slot) => slot.name === name || slot.widget?.name === name);
  return input?.link != null;
}

function widgetValue(node, name) {
  return isLinked(node, name) ? null : (findWidget(node, name)?.value ?? null);
}

function hide(widget) {
  widget.hidden = true;
  widget.computeSize = () => [0, -4];
  widget.computeLayoutSize = () => ({ minHeight: 0, maxHeight: 0, minWidth: 0 });
  widget.options = widget.options || {};
  widget.options.hidden = true;
}

function linkOf(graph, id) {
  const links = graph?.links;
  return links?.get?.(id) ?? links?.[id];
}

function nodePreview(node) {
  const image = node?.imgs?.[0] ?? node?.img;
  if (typeof image === 'string') return image;
  return image?.src ?? image?.url ?? null;
}

// Whether `link` delivers a value when the prompt runs: muted nodes send nothing, and a bypassed node only
// passes on a linked input of the same type.
function delivers(graph, link, depth = 0) {
  const origin = graph?.getNodeById?.(link.origin_id);
  if (!origin || depth > 16) return Boolean(origin);
  if (origin.mode === MUTED) return false;
  if (origin.mode !== BYPASSED) return true;
  const type = origin.outputs?.[link.origin_slot]?.type;
  const input = origin.inputs?.find((slot) => slot.link != null && slot.type === type);
  const next = input ? linkOf(graph, input.link) : null;
  return next ? delivers(graph, next, depth + 1) : false;
}

function connectedRefs(node) {
  const refs = { images: [], audios: [], videos: [], video_audios: [] };
  for (const input of node.inputs || []) {
    const match = /(?:^|\.)(image|audio|video_audio|video)(\d+)$/.exec(input.name || '');
    if (!match || input.link == null) continue;
    const link = linkOf(node.graph, input.link);
    if (!link || !delivers(node.graph, link)) continue;
    const origin = node.graph?.getNodeById?.(link.origin_id);
    const source = referenceSource(origin, node.graph);
    const image = match[1] === 'image';
    const file = image ? referenceImageFile(origin, node.graph, link.origin_slot) : referenceFile(source);
    refs[{image: 'images', audio: 'audios', video: 'videos', video_audio: 'video_audios'}[match[1]]].push({ name: `${match[1]}${Number(match[2])}`, title: source?.title || origin?.title || '',
      file: file?.path ?? null, mediaFile: file, preview: image ? file ? viewUrl(file) : nodePreview(source) : null });
  }
  const byNumber = (a, b) => Number(a.name.replace(/\D/g, '')) - Number(b.name.replace(/\D/g, ''));
  for (const pool of Object.values(refs)) pool.sort(byNumber);
  return refs;
}

function viewUrl(file) {
  if (file.download_url) return api.apiURL(file.download_url);
  const query = new URLSearchParams({ filename: file.filename, subfolder: file.subfolder, type: file.type, v: file.v ?? '' });
  return api.apiURL(`/view?${query}`);
}

function undoHistory() {
  return app.extensionManager?.workflow?.activeWorkflow?.changeTracker;
}

function recordStep() {
  const tracker = undoHistory();
  (tracker?.captureCanvasState ?? tracker?.checkState)?.call(tracker);
}

export class TimelineHost {
  constructor(node) {
    this.node = node;
    this.timer = null;
    this.request = 0;
    this.widget = findWidget(node, 'timeline');
    hide(this.widget);
    this.history = new TimelineHistory({
      read: () => this.historyState(),
      identity: () => `${this.sequenceName()}/${this.node.properties?.h3c_project?.id ?? ''}`,
      apply: value => this.restoreHistory(value),
      notify: () => { const shown = studio(); if (shown.host === this) shown.refreshHistory(); },
      group: () => {
        const field = document.activeElement;
        return field?.matches('textarea, input[type="text"], input:not([type]), [contenteditable="true"]') ? field : null;
      },
      flush: () => { document.activeElement?.blur?.(); this.editor?.flushTyping(); },
      fresh: true,
    });
    this.takesClient = new TakesClient(async (url, body) => {
      if (this.project) {
        if (url.endsWith('/rate')) return {ok: false, error: 'Rate takes on the H3 Timeline node’s own sequence.'};
        const action = url.endsWith('/use') ? 'use' : url.endsWith('/delete') ? 'delete' : 'list';
        const found = await this.project.takes(action, body);
        if (action === 'list') {
          for (const kind of ['box', 'bridge']) for (const take of found[kind]?.takes ?? []) take.folder = take.id;
          return {ok: true, ...found};
        }
        return found;
      }
      const response = await api.fetchApi(url, {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({...this.requestBody(), ...body})});
      if (response.status === 404) throw new Error('Restart ComfyUI, then refresh this page.');
      return response.json();
    });
    const editor = new TimelineEditor({
      read: () => this.widget.value,
      write: (text, typing = false) => {
        this.writeTimeline(text, typing);
        if (!typing) node.setDirtyCanvas?.(true, true);
      },
      context: () => Number.parseInt(widgetValue(node, 'context_frames') ?? '39', 10) || 39,
      connected: () => this.connected(),
      referenceSources: () => this.referenceSources(true),
      uploadReference: (file,kind) => this.uploadReference(file,kind),
      describeImage: (action,ref,text) => this.describeImage(action,ref,text),
      refmodChoices: () => this.refmodChoices ?? [],
      refreshRefmods: () => this.loadRefmods(),
      uploadAudio: (file) => this.uploadAudio(file),
      uploadPicture: (file) => this.uploadPicture(file),
      importGuide: file => this.importGuide(file),
      pinGuide: async file => {const result=await this.stillRequest('/h3c/stills/pin',{file});if(!result.ok)throw Error(result.error??'Cannot verify guide.');return result;},
      referenceState:()=>this.referenceState(),referenceContext:()=>this.referenceContext(),
      referenceCatalog:()=>this.referenceCatalog(),referenceBusy:()=>this.referenceClient?.busy,
      referenceBatch:()=>this.referenceClient?.batch,
      generateReference:key=>this.generateReference(key),
      generateSelectedReferences:keys=>this.referenceClient.generateSelected(keys),
      stopReferencePreparation:()=>this.referenceClient.stopAfterCurrent(),
      approveReference:request=>this.approveReference(request),reuseReferenceScene:(key,source)=>this.reuseReferenceScene(key,source),
      referenceReadiness:boxId=>this.referenceReadiness(boxId),
      openReferencePreparation:keys=>this.editor.cast.preparation.open(keys),
      stillSources: (request, options) => this.stillSources(request, options),
      touchStills: () => this.touch(),
      stillsSettled: signal => this.settled(signal),
      prepareStill: request => this.prepareStill(request),
      stillControls: () => this.stillControls(),
      prepareStillPrompts: (instructions,onProgress) => this.prepareStillPrompts(instructions,onProgress),
      stillPromptInstructions: () => this.stillPromptInstructions(),
      stillPromptJob: () => this.stillPromptJob,
      cancelStillPrompts: () => this.cancelStillPrompts(),
      generateStill: request => this.generateStill(request),
      openStillGenerator: () => this.openStillGenerator(),
      hasVideo: () => this.hasVideoOutput(),
      readBoundary: boxId => this.readBoundary(boxId),
      uploadWhisper: (file, hash) => this.project ? this.uploadProjectAsset(file, 'whisper', hash) : Promise.resolve(),
      audioInfo: (file) => this.audioInfo(file),
      confirmAudioUnlock: () => this.confirmAudioUnlock(),
      queue: (count, box, bridge, receipt) => this.queue(count, box, bridge, receipt),
      preflight: (box, count) => this.prepareRegeneration(box, count),
      refresh: () => this.refresh(),
      takes: (action, body) => this.takesClient.send(action, body),
      viewUrl,
      changed: () => this.changed(),
      loaded: () => this.history.capture(true),
      story: () => this.story(),
      bible: async (body) => (await api.fetchApi(BIBLE_URL, {method: 'POST',
        headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)})).json(),
      storyPlan: () => {
        const state = this.story()?.state?.();
        return state && String(state.timeline) === String(this.node.id) ? state.plan ?? null : null;
      },
      // ComfyUI's Undo history records the graph on clicks and keys, and a Cast edit lands after its click. Unless the
      // edit is recorded when it lands, an Undo right after it also undoes the change before, and Redo loses the edit.
      undoStep: recordStep,
      editStory: async (edit) => {
        const controller = this.story();
        if (!controller) throw new Error('Connect an H3 Story node to revise this story.');
        const started = await controller.write(false, false, edit);
        if (!started) throw new Error(controller.panel.messageEl.textContent || 'Story could not start.');
      },
      check: async (boxes) => {
        const controller = this.story();
        if (!controller) throw new Error('Link an H3 Story node to check boxes.');
        const started = await controller.checkBoxes(boxes);
        if (!started) throw new Error(controller.panel.messageEl.textContent || 'The check could not start.');
      },
      rendered: () => this.showProgress(),
    });
    this.editor = editor;
    this.stillClient=new StillClient({context:()=>stringifyJSON([this.node.graph?.id,findWidget(this.node,'name')?.value,this.project?.project?.sequence,!!this.removed]),capture:request=>this.prepareStill(request),read:()=>this.readState(),
      write:(state,options)=>this.writeStillState(state,options),request:(url,body)=>this.stillRequest(url,body)});
    this.referenceHost={referenceState:()=>this.readState(),referenceContext:()=>this.referenceContext(),
      writeReferenceState:(state,options)=>this.writeStillState(state,options),referenceCatalog:()=>this.referenceCatalog(),
      prepareReference:request=>this.prepareReference(request),request:async(url,body)=>this.stillRequest(url,url==='/h3c/reference-assets/approve'?{...await this.referenceSnapshot(body.timeline),...body}:body),
      referenceChanged:()=>this.editor.cast.preparation?.refresh(),undoStep:recordStep,
      referenceReady:async()=>{await this.saved.ready;if(this.project?.conflict)throw Error('Resolve project edits before approving a reference.');}};
    this.referenceClient=new ReferenceClient(this.referenceHost);
    const loadRefmods = () => this.loadRefmods().catch(error => { editor.refmodMessage.textContent = error.message; });
    editor.refmodsEl.addEventListener('toggle', () => {
      if (editor.refmodsEl.open && !this.refmodChoices) loadRefmods();
    });
    if (editor.state.refmods?.length) loadRefmods();
    const face = this.face = new TimelineFace({
      editor,
      open: () => this.openStudio(),
      renderNext: () => editor.queueNext(),
      renderAll: () => editor.queue(),
    });
    this.saved = mountSavedState(node, face.root, { app, api, loaded: () => {
      editor.load(); this.schedule(0);
    } });
    this.configureProject();
    node.h3cTimeline = this;
    const dom = node.addDOMWidget('h3c_timeline_editor', 'custom', face.root, {
      serialize: false,
      hideOnZoom: false,
      getMinHeight: () => face.height(),
      getMaxHeight: () => face.height(),
    });
    dom.serialize = false;
    if (dom.options) dom.options.serialize = false;
    dom.computeSize = (width) => [width ?? node.size?.[0] ?? 420, face.height()];
    dom.computeLayoutSize = () => ({ minHeight: face.height(), maxHeight: face.height(), minWidth: 0 });
    face.mountWidgets(node);
    for (const name of ['name', ...SETTINGS]) this.chain(findWidget(node, name), () => this.settingChanged(name));
    this.hook('onConfigure', () => {
      this.configureProject();
      hide(this.widget);
      editor.load();
      this.schedule(0);
      this.fit();
      setTimeout(() => showOwnElement(node, face.root, '.h3ct-face', app.canvas?.graph), 0);
    });
    this.hook('onConnectionsChange', () => {
      editor.render();
      this.changed();
    });
    this.hook('onExecuted', (message) => {
      const status = message?.h3c_timeline?.[0];
      if (status) this.schedule(0);
    });
    this.hook('onRemoved', () => {
      mounted.delete(this);
      clearTimeout(this.timer);
      clearTimeout(this.stillTimer);
      clearTimeout(this.referenceTimer);
      this.referenceClient.stopAfterCurrent();
      this.removed = true;
      if (studio().host === this) this.handOver();
      this.saved.destroy();
      this.observer?.disconnect();
      editor.destroy();
    });
    if (typeof ResizeObserver === 'function') {
      this.observer = new ResizeObserver(() => this.relayout());
      this.observer.observe(face.root);
    }
    mounted.add(this);
    this.showProgress();
  }

  // The Studio's view of this Timeline.

  sequenceName() {
    return widgetValue(this.node, 'name');
  }

  title() {
    if (this.project?.project) return this.project.project.name;
    const name = this.sequenceName();
    return name || this.node.title || 'Timeline';
  }

  get savedBar() {
    return this.saved.bar;
  }

  watch() {
    return watch;
  }

  runningBox() {
    if (this.requestedBridge != null) return null;
    return this.requested ?? this.editor.nextBox();
  }

  titleOf(id) {
    return (app.rootGraph ?? app.graph)?.getNodeById?.(id)?.title ?? '';
  }

  newProjectBusy() {
    const graph = app.rootGraph ?? app.graph;
    const busy = this.project?.busy || this.project?.project?.active_job || this.project?.project?.active_operation
      || watch.running || watch.turn || watch.remaining > 0
      || (graph?._nodes ?? []).some(node => (node.h3cStory?.job || node.h3cStory?.starting || node.h3cStory?.uploading || node.h3cStory?.forkingLibrary) || node.h3cTimeline?.editor.queuing
        || node.h3cTimeline?.editor.queueBatch || node.h3cTimeline?.submitting || node.h3cTimeline?.feed
        || node.h3cTimeline?.referenceClient?.busy || node.h3cTimeline?.stillClient?.active.size || node.h3cTimeline?.stillClient?.recovering || node.h3cTimeline?.editor.frameImages.generating
        || node.h3cTimeline?.editor.pictures.busy || node.h3cTimeline?.editor.cast.busy);
    return busy ? 'Finish or cancel Story writing/checking, or use Stop & clear queue, before creating a project.' : null;
  }

  async newProject() {
    if (this.projectLoading) throw new Error('A project is already being reset.');
    const graph = app.rootGraph ?? app.graph;
    if (this.node.graph !== graph) throw new Error('Open a root H3 workflow to start a project.');
    const check = () => {
      const reason = this.newProjectBusy();
      if (reason) throw new Error(reason);
      if ((app.rootGraph ?? app.graph) !== graph || this.removed) throw new Error('The open workflow changed. Open its Studio and try again.');
    };
    check();
    freshProject(this.widget.value); // Validate before flushing or changing this Timeline.
    this.projectLoading = true;
    try {
      const story = this.story();
      await story?.graphDeleted?.();
      if(!story||story.libraryDeleted!==story.graphId()) {
        await saveBeforeNewProject(story,this.saved);
      }
      check();
      const fresh = freshProject(this.widget.value);
      recordStep();
      // Keep the native workflow/tab in place, with an independent server autosave identity for each story.
      if(story?.library) {
        graph.extra??={};graph.extra.h3c_story_id=crypto.randomUUID();
        story.libraryId=story.librarySignature=story.libraryDeleted=story.finishedJob=null;
        story.libraryRevision=undefined;
        if(story.node.properties)delete story.node.properties.h3c_library_revision;
      }
      // Only stored project content/identity may override this reset; source wiring remains connected.
      for (const [node, names] of [[this.node, ['name','timeline']], [story?.node, ['state']]]) {
        for (const [index, input] of (node?.inputs ?? []).entries()) {
          if (names.includes(input.widget?.name ?? input.name) && input.link != null) node.disconnectInput(index);
        }
      }
      const properties = this.node.properties ??= {};
      if (this.project || properties.h3c_fork_sequence) properties.h3c_fork_sequence = fresh.name;
      delete properties.h3c_project;
      delete properties.h3c_asset_bindings;
      findWidget(this.node, 'name').value = fresh.name;
      this.widget.value = fresh.timeline;
      if (story) {
        story.widget.value = '';
        story.showState();
        story.panel.say('');
        story.saved.changed();
      }
      this.configureProject();
      this.editor.feedbackInput.value = '';
      this.editor.load();
      this.changed(); // Invalidates any status response from the previous sequence.
      const shown = studio();
      shown.close();
      shown.remembered = null;
      this.openStudio('box', {link:false});
      this.node.setDirtyCanvas?.(true, true);
      recordStep();
      try { await this.saved.flush(); }
      catch (error) { throw new Error(`The Timeline was reset, but is not saved yet: ${error?.message ?? error}`); }
    } finally { this.projectLoading = false; }
  }

  async startGeneration() {
    const graph=app.rootGraph??app.graph;
    if(this.node.graph!==graph) throw new Error('Open a root H3 workflow to start a new generation.');
    const check=()=>{
      const reason=this.newProjectBusy();
      if(reason) throw new Error(reason);
      if(this.removed||(app.rootGraph??app.graph)!==graph) throw new Error('The open workflow changed.');
    };
    return startGeneration({check,body:()=>this.generationBody(),
      snapshot:()=>stringifyJSON({identity:graph.extra?.h3c_story_id,
        nodes:(graph._nodes??[this.node]).map(node=>({id:node.id,type:node.type,
          inputs:(node.inputs??[]).map(input=>[input.name,input.link]),
          widgets:(node.widgets??[]).map(widget=>[widget.name,widget.value])}))}),
      confirm:options=>app.extensionManager?.dialog?.confirm?.(options)??window.confirm(`${options.title}\n\n${options.message}`),
      save:async()=>{
        if(this.project)await this.project.save();
        await saveBeforeNewProject(this.story(),this.saved);
      },
      request:(url,body)=>this.stillRequest(url,body),
      apply:async result=>{
        recordStep();
        const story=this.story();
        graph.extra??={};graph.extra.h3c_story_id=crypto.randomUUID();
        if(story?.library){
          story.libraryId=story.librarySignature=story.libraryDeleted=null;
          story.libraryRevision=undefined;
          if(story.node.properties)delete story.node.properties.h3c_library_revision;
        }
        useGeneration(this.node,result.name);
        this.configureProject();
        this.editor.load();this.changed();
        const shown=studio();
        if(shown.host===this){shown.chosen=shown.candidate=null;shown.remembered=null;shown.setView('full');shown.openFocus('project',{link:false});}
        this.node.setDirtyCanvas?.(true,true);recordStep();
        try {await this.saved.flush();}
        catch(error){throw new Error(`The new generation is open but not saved yet: ${error.message}`);}
        await this.refresh();
      }});
  }

  async generationBody() {
    const body=this.requestBody();
    if(body.name==null){
      const snapshot=await app.graphToPrompt();
      body.workflow=snapshot.output;
      body.timeline_node=captureTimelineId(snapshot,this.node.id,{root:this.node.graph===(app.rootGraph??app.graph)});
    }
    return body;
  }

  async generationHistory() {return this.stillRequest('/h3c/generations/history',await this.generationBody());}

  // Clearing the queue first means the next pending run can't start between the two calls.
  async stop() {
    if (this.project) throw new Error('API jobs retain their queue receipts. Follow this job in the project status.');
    this.feed?.stop();
    await api.clearItems('queue');
    await api.interrupt();
  }

  viewUrl(file) {
    return viewUrl(file);
  }

  openStudio(page, options) {
    const shown = studio();
    shown.cover ??= coverCanvas;
    shown.open(this, page, options);
    this.editor.frameImages.refreshControls();
  }

  // A Timeline from a newer Studio is kept as written, or undoing back to it would drop what this one doesn't know.
  historyState() {
    const state = this.readState(), text = unknownFeatures(state).length ? this.widget.value : serialize(state);
    return {timeline: dropReceipts(parseJSON(text)),
      settings: Object.fromEntries(SETTINGS.map(name => [name, widgetValue(this.node, name)]))};
  }

  restoreHistory(value) {
    generationControl(this.node, 'timeline');
    recordStep();
    const box = this.editor.box()?.id;
    for (const [name, setting] of Object.entries(value.settings)) {
      const widget = findWidget(this.node, name);
      if (widget && !isLinked(this.node, name) && setting != null) widget.value = setting;
    }
    this.writeTimeline(stringifyJSON(withLiveReceipts(value.timeline, parseState(this.widget.value))), false, true);
    this.editor.selected = Math.max(0, (value.timeline.boxes ?? []).findIndex(item => item.id === box));
    this.editor.selectedShot = 1;
    this.editor.load();
    this.node.setDirtyCanvas?.(true, true);
    this.changed();
    recordStep();
  }

  jumpHistory(index) { this.history.restore(index); }
  undo() { this.history.undo(); }
  redo() { this.history.redo(); }

  // Whether a Render is still posting runs to ComfyUI a few at a time.
  feeding() { return !!this.feed; }

  // What Render shows beside the buttons: ComfyUI's progress, and how a Render that queues runs a few at a time stands.
  progress() {
    return progressText(watch, this.runningBox(), (id) => this.titleOf(id),
      {held: this.feed?.held ?? 0, note: this.feedMessage});
  }

  showProgress() {
    syncImageOutputs(this.node, this.editor?.state, this.editor ? this.widget.value : undefined);
    if (!this.face) return;
    const editor = this.editor;
    this.face.update({
      summary: editor.summaryEl.textContent,
      progress: this.progress(),
      allLabel: editor.renderButton.textContent,
      canRender: !editor.renderButton.disabled,
    });
    const shown = studio();
    if (shown.host === this) shown.refresh();
  }

  // An undo or redo replaces this node with a new one of the same id. The Studio closes, then moves to the new node
  // if it appears within a second, keeping the page, the selected box and its tab. It doesn't link boxes without a
  // cast, or Undo could never get past a link.
  handOver() {
    const shown = studio();
    const snapshot = shown.snapshot();
    const id = this.node.id;
    shown.close();
    const revision = shown.openRevision;
    const started = Date.now();
    const look = () => {
      if (!shown.root.hidden || shown.openRevision !== revision || Date.now() - started >= 1000) return;
      const next = (app.rootGraph ?? app.graph)?.getNodeById?.(id)?.h3cTimeline;
      if (next && next !== this && !next.removed) {
        next.openStudio('box', {link:false});
        shown.restoreSnapshot(snapshot, {link:false});
      } else if (Date.now() - started < 1000) setTimeout(look, 50);
    };
    setTimeout(look, 50);
  }

  story() {
    const input = this.node.inputs?.find(input => input.name === 'story');
    const link = linkOf(this.node.graph, input?.link);
    if (!link || !delivers(this.node.graph, link)) return null;
    return this.node.graph?.getNodeById?.(link.origin_id)?.h3cStory ?? null;
  }

  connected() {
    const state=this.editor?.state??parseJSON(this.widget.value);
    return referencePools(state,this.referenceSources(),viewUrl);
  }

  referenceSources(includeInactive = false, stateOverride) {
    const connected = connectedRefs(this.node);
    let state = stateOverride ?? this.editor?.state;
    if (!state) { try { state = JSON.parse(this.widget.value); } catch { state = {}; } }
    for (const clip of state.audio_clips ?? []) {
      if (!clip.file) continue;
      connected.audios.push({name: clip.slot, title: clip.title || clip.file.filename,
        file: clip.file.filename, mediaFile: clip.file, conflict: connected.audios.some(ref => ref.name === clip.slot)});
    }
    connected.audios.push(...voiceRefs(state));
    connected.images.push(...pictureRefs(state, viewUrl));
    for (const ref of state.refmods ?? []) {
      if (!includeInactive && (ref.strength ?? 1) <= 0) continue;
      const choice = this.refmodChoices?.find(item => item.name === ref.name && item.member === (ref.member ?? -1));
      const pool = ref.kind === 'audio' ? connected.audios : connected.images;
      const conflict = pool.some(item => item.name === ref.slot);
      pool.push({name: ref.slot, title: choice?.title || ref.name, refmod: true, conflict,
        preview: choice?.thumbnail ? api.apiURL(`/h3c/refmods/thumbnail?${new URLSearchParams({name: ref.name})}`) : null});
    }
    return connected;
  }

  async audioInfo(file) {
    const response = await api.fetchApi('/h3c/audio/info', {method: 'POST',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify({file})});
    if (response.status === 404) throw new Error('Restart ComfyUI to enable Timeline audio, then refresh this page.');
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not read this audio file.');
    return result;
  }

  async uploadAudio(file) {
    if (this.project) return this.uploadProjectAsset(file, 'audio');
    const body = new FormData();
    body.append('image', file);
    body.append('type', 'input');
    body.append('subfolder', 'h3_audio');
    const response = await api.fetchApi('/upload/image', {method: 'POST', body});
    if (!response.ok) throw new Error(`Could not upload audio (HTTP ${response.status}).`);
    const result = await response.json();
    const mediaFile = {filename: result.name, subfolder: result.subfolder, type: result.type};
    return {file: mediaFile, title: file.name, ...await this.audioInfo(mediaFile)};
  }

  async stillRequest(url,body,{signal}={}) {
    const response=await api.fetchApi(url,{method:'POST',headers:{'Content-Type':'application/json'},signal,
      body:stringifyJSON(url==='/prompt'?{...body,client_id:api.clientId}:body)});
    return parseJSON(await response.text());
  }

  // A Timeline from a newer Studio is replaced only whole, by undo and redo: every other write is made from
  // parseState, which drops what this Studio doesn't know. Whether the text was written.
  writeTimeline(text,typing=false,whole=false) {
    if(!whole&&text!==this.widget.value&&unknownFeatures(this.readState()).length)return false;
    setGenerationControl(generationControl(this.node,'timeline'),text);
    this.widget.value=text;
    if(!typing)this.history.capture();
    return true;
  }

  // A request's result read back from the server (`recovered`) is saved as every other edit is, by Autosave; one the user
  // asked for is saved now.
  async writeStillState(state,{recovered=false}={}) {
    if(!this.writeTimeline(serialize(state)))throw Error(readOnlyNote(unknownFeatures(this.readState())));
    this.node.setDirtyCanvas?.(true,true);
    this.editor.load();this.saved.changed();
    if(!recovered)await this.saved.flush();
  }

  // Asked by each Render button on every redraw; reading the graph's wiring takes ~15 ms on a large workflow. The answer
  // stands while the graph's version (bumped by every node or link added, removed or connected) is the same, and for at
  // most VIDEO_ANSWER_MS; a graph without a version is asked again after each redraw.
  hasVideoOutput() {
    const versions=[app.rootGraph??app.graph,this.node.graph].map(graph=>graph?._version),versioned=versions.every(Number.isFinite),
      key=versions.join('/'),now=performance.now();
    if(this.videoAnswer!==undefined&&versioned&&key===this.videoKey&&now-this.videoAt<VIDEO_ANSWER_MS)return this.videoAnswer;
    this.videoAnswer=this.findVideoOutput();this.videoKey=key;this.videoAt=now;
    if(!versioned)queueMicrotask(()=>{this.videoAnswer=undefined;});
    return this.videoAnswer;
  }

  findVideoOutput() {
    const pending=[this.node],seen=new Set();let direct=false;
    while(pending.length) {
      const node=pending.pop();if(!node||seen.has(node)||node.mode===2)continue;seen.add(node);
      if(['H3C_SaveSegment','SaveVideo','VHS_VideoCombine'].includes(node.type)){direct=true;break;}
      for(const port of node.outputs??[])for(const id of port.links??[]) {
        const link=node.graph?.links?.get?.(id)??node.graph?.links?.[id];
        if(link)pending.push(node.graph.getNodeById(link.target_id));
      }
    }
    const graph=app.rootGraph??app.graph,{nested,signature}=graphWiring(graph);
    if(!nested)return direct;
    if(signature!==this.videoCapabilityKey&&!this.videoCapabilityPreparing) {
      this.videoCapabilityKey=signature;this.videoCapabilityPreparing=true;
      app.graphToPrompt().then(snapshot=>{
        if(this.removed)return;
        const id=captureTimelineId(snapshot,this.node.id,{root:this.node.graph===graph});
        this.videoCapability=compiledVideoOutput(snapshot,id);this.videoAnswer=undefined;
      }).catch(()=>{this.videoCapability=false;this.videoAnswer=undefined;}).finally(()=>{this.videoCapabilityPreparing=false;if(!this.removed)this.editor.render();});
    }
    return signature===this.videoCapabilityKey&&this.videoCapability!=null?this.videoCapability:direct;
  }

  referenceContext() {return stringifyJSON([this.node.graph?.id,findWidget(this.node,'name')?.value,this.project?.project?.sequence,!!this.removed]);}
  referenceState() {return parseState(this.widget.value);}
  // The Timeline parsed once per text, shared by readers that never change it (they copy before editing).
  readState() {
    const text=this.widget.value;
    if(this.parsed?.text!==text)this.parsed={text,state:parseState(text)};
    return this.parsed.state;
  }
  async referenceSnapshot(timeline=this.widget.value) {
    const snapshot=await app.graphToPrompt();
    const id=captureTimelineId(snapshot,this.node.id,{root:this.node.graph===(app.rootGraph??app.graph)});
    const body=captureStillBody(snapshot,id,{});body.timeline=timeline;body.workflow.api[id].inputs.timeline=timeline;return body;
  }
  async referenceCatalog() {
    const result=await this.stillRequest('/h3c/reference-assets/catalog',await this.referenceSnapshot());
    if(!result.ok)throw Error(result.error??'Could not read reference assets.');return result.assets;
  }
  async referenceReadiness(boxId) {return requiredAssets(this.referenceState(),boxId,await this.referenceCatalog());}
  async prepareReference(request) {
    const snapshot=await app.graphToPrompt();
    const id=captureTimelineId(snapshot,this.node.id,{root:this.node.graph===(app.rootGraph??app.graph)});
    const recipe=captureRecipe(snapshot,id);if(!recipe)throw Error("Connect an image workflow to the Timeline's still_image input before generating references.");
    const body=captureStillBody(snapshot,id,{...request,request_id:request.request_id??crypto.randomUUID(),recipe});
    if(this.project?.project){body.name=this.project.project.sequence;body.workflow.api[id].inputs.name=body.name;}
    const result=await this.stillRequest('/h3c/reference-assets/prepare',body);
    if(!result.ok)throw Error(result.error??'Could not prepare the reference.');return {...result,request:body};
  }

  async stillPromptInstructions() {
    const answer=await this.stillRequest('/h3c/still-prompts/instructions',{});
    if(!answer.ok)throw Error(answer.error??'Could not read still prompt instructions.');
    return answer.instructions;
  }

  async prepareStillPrompts(instructions,onProgress) {
    if(this.stillPromptPolling||this.stillPromptJob?.starting)throw Error('Still prompt preparation is already running.');
    await this.saved.ready;await this.saved.flush();
    if(this.project?.conflict)throw Error('Resolve project edits before preparing prompts.');
    const controller=this.story();if(!controller)throw Error('Connect a Story node to prepare still prompts.');
    const context=this.referenceContext(),line=this.widget.value;
    const frames=this.editor.host.context(),references=this.connected().images;
    const captured=stillPromptSource(parseState(line),instructions,frames,references);
    const check=()=>{
      if(this.removed||context!==this.referenceContext()||!sameStillPromptSource(captured,stillPromptSource(parseState(this.widget.value),instructions,this.editor.host.context(),this.connected().images)))
        throw Error('The Timeline changed during prompt preparation; current edits were preserved.');
    };
    const snapshot=await app.graphToPrompt();check();
    const id=captureTimelineId(snapshot,this.node.id,{root:this.node.graph===(app.rootGraph??app.graph)});
    const story=snapshot.output[id]?.inputs?.story?.[0];
    if(!story||snapshot.output[story]?.class_type!=='H3C_Story')throw Error('Connect the Story writer to this Timeline.');
    snapshot.output[id].inputs.timeline=serialize(parseState(line));
    this.stillPromptPolling=true;let terminal=false;
    try {
      const identity={graph:controller.graphId(),story};
      if(!this.stillPromptJob?.id) {
        const query=new URLSearchParams({...identity,client:controller.clientId()});
        const current=await api.fetchApi('/h3c/story/current?'+query).then(response=>response.json());
        if(current.kind==='still_prompts'&&current.job&&String(current.timeline)===String(id))this.stillPromptJob={id:current.job};
      }
      if(!this.stillPromptJob?.id) {
        check();this.stillPromptJob={starting:true};
        const started=await this.stillRequest('/h3c/still-prompts/prepare',{prompt:snapshot.output,story,
          graph:controller.graphId(),client:controller.clientId(),instructions,context:frames,references,source:captured});
        if(!started.ok){this.stillPromptJob=null;throw Error(started.error??'Could not start still prompt preparation.');}
        this.stillPromptJob={id:started.job};
      }
      let missed=0;
      while(true) {
        const query=new URLSearchParams({id:this.stillPromptJob.id,...identity});let view;
        try {
          const response=await api.fetchApi('/h3c/story/job?'+query);view=await response.json();missed=0;
        } catch(error) {
          if(++missed>=3)throw Error('ComfyUI is not answering. Resume this preparation to recover its result; no new batch was submitted.');
          onProgress?.('Reconnecting to the existing preparation…');await new Promise(resolve=>setTimeout(resolve,900));continue;
        }
        if(view.source&&!sameStillPromptSource(view.source,captured)) {
          terminal=view.state!=='running';
          if(!terminal)await this.cancelStillPrompts();
          throw Error('The earlier preparation used a different Timeline. Its result was preserved; prepare the current prompts again.');
        }
        if(view.state==='running') {
          if(!this.removed&&context===this.referenceContext())onProgress?.(view.progress??'Preparing still prompts…');
          await new Promise(resolve=>setTimeout(resolve,900));continue;
        }
        terminal=['done','failed','cancelled','interrupted','partial','unknown'].includes(view.state);
        if(view.state!=='done'||!view.result)throw Error(view.error??view.progress??'Still prompt preparation was interrupted.');
        check();
        if(!sameStillPromptSource(view.result.source,captured))throw Error('Prepared prompts do not match the captured Timeline.');
        return view.result;
      }
    } finally {
      const job=this.stillPromptJob?.id;this.stillPromptPolling=false;
      if(terminal){this.stillPromptJob=null;if(job)await this.stillRequest('/h3c/story/taken',{job}).catch(()=>{});}
      else if(this.stillPromptJob?.starting)this.stillPromptJob=null;
    }
  }

  async cancelStillPrompts() {
    const job=this.stillPromptJob?.id;
    if(job)await this.stillRequest('/h3c/story/cancel',{job});
  }
  async generateReference(key) {
    const result=await this.referenceClient.generateAsset(key);this.recoverReferences();return result;
  }
  async approveReference(request) {return applyReferenceApproval(this.referenceHost,request);}
  recoverImageResult(promptId) {
    if(this.removed||!promptId)return;
    const state=this.readState();
    const pending=receipt=>receipt.prompt_id===promptId&&!receipt.historical&&!['complete','failed','cancelled'].includes(receipt.state);
    if(preparationOf(state).requests.some(pending))this.recoverReferences();
    if((state.still_requests??[]).some(pending))this.recoverStills();
  }
  async recoverReferences() {
    clearTimeout(this.referenceTimer);this.referenceTimer=null;
    try{await this.referenceClient.recover();}catch(error){const panel=this.editor.cast.preparation;if(panel){panel.message=error.message;panel.render();}}
    const waiting=preparationOf(this.readState()).requests.filter(r=>!r.historical&&!['complete','failed','cancelled'].includes(r.state));
    if(!this.removed&&waiting.length)
      this.referenceTimer=setTimeout(()=>this.recoverReferences(),waiting.some(r=>r.state!=='unknown')?3000:UNKNOWN_RECHECK_MS);
  }
  async reuseReferenceScene(key,source) {
    const before=this.widget.value,context=this.referenceContext(),rows=await this.referenceCatalog();
    if(before!==this.widget.value||context!==this.referenceContext())throw Error('The scene changed before reference reuse.');
    const target=rows.find(r=>r.key===key),origin=rows.find(r=>r.key===source);
    const candidate=origin?.candidates.find(c=>c.id===origin.approved?.candidate_id);
    if(!target||target.role!=='scene_layout'||origin?.status!=='approved'||!candidate)throw Error('Select an approved composed scene.');
    const state=this.referenceState(),preparation=state.reference_preparation??=preparationOf(state);
    let row=preparation.assets.find(r=>r.key===key);if(!row)preparation.assets.push(row=structuredClone(target));
    const copy={...structuredClone(candidate),id:'reuse:'+crypto.randomUUID(),input_fingerprint:target.input_fingerprint,
      provenance:{...candidate.provenance,reused_asset:source,reused_revision:origin.approved.revision}};
    row.candidates.push(copy);await this.writeStillState(state);
    return this.approveReference({asset_key:key,candidate_id:copy.id,expected_revision:row.approved?.revision??0});
  }

  async openStillGenerator() {
    const snapshot=await app.graphToPrompt();
    const id=captureTimelineId(snapshot,this.node.id,{root:this.node.graph===(app.rootGraph??app.graph)});
    const recipe=captureRecipe(snapshot,id);if(!recipe)throw Error("Connect an image workflow to the Timeline's still_image input first.");
    const root=app.rootGraph??app.graph,rootId=recipe.output[0].split(':')[0];
    const node=root.getNodeById(rootId);if(!node)throw Error('The connected generator is missing.');
    studio().close();if(app.canvas.graph!==root)app.canvas.setGraph(root);
    app.canvas.deselectAllNodes();app.canvas.selectNode(node);app.canvas.centerOnNode(node);
  }

  // stillControls and stillSources are asked as the Studio draws a clip; the workflow is serialized after that draw shows.
  // A sources load the panel replaced in the meantime (a graph load redraws it once per link) stops there.
  // The still panel asks as it opens a clip (see STILL_QUIET_MS). Asks made while one waits share its reading.
  touch() {this.touchedAt=performance.now();}

  // Resolves once nothing has opened a clip in the panel for STILL_QUIET_MS; rejects when `signal` aborts or the node goes.
  settled(signal) {
    return new Promise((resolve,reject)=>{
      const check=()=>{
        if(signal?.aborted)return reject(signal.reason);
        if(this.removed)return reject(new DOMException('The Timeline was removed.','AbortError'));
        const wait=(this.touchedAt??-Infinity)+STILL_QUIET_MS-performance.now();
        if(wait>0)setTimeout(check,wait);else resolve();
      };
      check();
    });
  }

  // What stillTimelineBody finds in the compiled workflow, read from the node when its name, text and context frames are its own
  // widgets on an active node of the root graph, which the compiled workflow could only copy. Null when it has to be compiled
  // (a linked input, a muted or bypassed node, a subgraph).
  literalTimelineBody(request) {
    const node=this.node,graph=app.rootGraph??app.graph;
    if(node.graph!==graph||node.mode===MUTED||node.mode===BYPASSED||isLinked(node,'timeline'))return null;
    const {name,timeline,settings}=this.requestBody(),frames=settings.context_frames;
    if(name==null||frames==null||typeof name==='object'||typeof frames==='object'||typeof timeline!=='string')return null;
    return {...structuredClone(request),name,timeline,settings:{context_frames:frames}};
  }

  stillControls() {
    if(this.controlsRead)return this.controlsRead;
    const read=this.controlsRead=(async()=>{
      await this.settled();await afterPaint();
      this.controlsRead=null;
      // Without a connected still recipe or still_image workflow there is nothing to read; compiling the workflow would only say so.
      if(this.node.graph===(app.rootGraph??app.graph)&&this.node.mode!==MUTED&&this.node.mode!==BYPASSED&&!isLinked(this.node,'still_recipe')&&!isLinked(this.node,'still_image'))return null;
      const snapshot=await app.graphToPrompt();
      const id=captureTimelineId(snapshot,this.node.id,{root:this.node.graph===(app.rootGraph??app.graph)});
      const recipe=captureRecipe(snapshot,id);
      return recipe?{...recipeControls(snapshot,recipe),seedScope:recipe.adapter==='pixels'&&!compiledVideoOutput(snapshot,id)?'box':'native'}:null;
    })();
    read.catch(()=>{if(this.controlsRead===read)this.controlsRead=null;});
    return read;
  }

  async generateStill(request) {
    if(this.editor?.promptDraftsReady?.()===false)throw new Error('Finish or discard the unsaved prompt fields before generating.');
    const receipt=await this.stillClient.generate(request);
    this.recoverStills();return receipt;
  }

  async recoverStills() {
    clearTimeout(this.stillTimer);this.stillTimer=null;
    try {await this.stillClient.recover();} catch(error) {this.editor.frameImages.note(error.message);}
    const waiting=this.readState().still_requests?.filter(item=>!['complete','failed','cancelled'].includes(item.state));
    if(!this.removed && waiting?.length)
      this.stillTimer=setTimeout(()=>this.recoverStills(),waiting.some(item=>item.state!=='unknown')?3000:UNKNOWN_RECHECK_MS);
  }

  async stillSources(request,{signal}={}) {
    await this.settled(signal);
    await afterPaint();
    signal?.throwIfAborted();
    let body=this.literalTimelineBody(request);
    if(!body) {
      const snapshot=await app.graphToPrompt();
      signal?.throwIfAborted();
      const id=captureTimelineId(snapshot,this.node.id,{root:this.node.graph===(app.rootGraph??app.graph)});
      body=stillTimelineBody(snapshot,id,request);
    }
    if(this.project?.project) body.name=this.project.project.sequence;
    return this.stillRequest('/h3c/stills/sources',body,{signal});
  }

  async prepareStill(request) {
    const snapshot=await app.graphToPrompt();
    const id=captureTimelineId(snapshot,this.node.id,{root:this.node.graph===(app.rootGraph??app.graph)});
    const recipe=captureRecipe(snapshot,id);
    if (!recipe) throw new Error("Connect an image workflow to this Timeline's still_image input.");
    const body=captureStillBody(snapshot,id,{...request,request_id:request.request_id ?? crypto.randomUUID(),recipe});
    if(this.project?.project) {
      body.name=this.project.project.sequence;
      body.workflow.api[id].inputs.name=body.name;
    }
    const result=await this.stillRequest('/h3c/stills/prepare',body);
    if (!result.ok) throw new Error(result.error ?? 'Could not prepare the still recipe.');
    return {...result,request:body};
  }

  async importGuide(file) {
    const body = new FormData();body.append('image',file);
    const response = await api.fetchApi('/h3c/stills/import',{method:'POST',body});
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error ?? 'Could not import the guide.');
    this.node.properties??={};
    const guides=this.node.properties.h3c_manual_guides??=[];
    if(!guides.some(guide=>JSON.stringify(guide)===JSON.stringify(result.file)))guides.push(structuredClone(result.file));
    return result.file;
  }

  async readBoundary(boxId) {
    for (let attempt=0;attempt<3;attempt++) {
      const body=this.requestBody(), snapshot=JSON.stringify(body), revision=this.project?.project?.revision;
      const state=parseJSON(body.timeline), index=state.boxes?.findIndex(box=>box.id===boxId);
      if (index==null || index<0) throw new Error('The target clip was removed.');
      const ids=[state.boxes[index-1]?.id,boxId].filter(Boolean);
      let status;
      if (this.project) {
        const current=await this.project.refresh();
        if (this.project.conflict) throw new Error('The attached project changed. Resolve its edits before accepting a guide.');
        status=current.status;
      } else {
        const response=await api.fetchApi(STATUS_URL,{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({...body,follow:false})});
        status=await response.json();
      }
      if (!status?.ok) throw new Error(status?.error ?? 'Could not read saved boundary takes.');
      const found=await Promise.all(ids.map(async id=>[id,await this.takesClient.send('list',{box:id})]));
      if (snapshot!==JSON.stringify(this.requestBody()) || revision!==this.project?.project?.revision) continue;
      const failed=found.find(([,list])=>!list.ok);
      if (failed) throw new Error(failed[1].error ?? 'Could not read archived boundary takes.');
      return boundarySnapshot(state,boxId,status,Object.fromEntries(found.map(([id,list])=>[id,list.box])));
    }
    throw new Error('The Timeline changed while reading saved takes. Try accepting the guide again.');
  }

  async uploadPicture(file) {
    if (this.project) return this.uploadProjectAsset(file, 'picture');
    const body = new FormData();
    body.append('image', file);
    body.append('type', 'input');
    body.append('subfolder', 'h3_pictures');
    const response = await api.fetchApi('/upload/image', {method: 'POST', body});
    if (!response.ok) throw new Error(`Could not upload the picture (HTTP ${response.status}).`);
    const result = await response.json();
    return {file: {filename: result.name, subfolder: result.subfolder, type: result.type}};
  }

  async uploadReference(file,kind) {
    if(kind==='image')return this.uploadPicture(file);
    if(kind==='audio'||kind==='video_audio')return this.uploadAudio(file);
    if(kind!=='video')throw new Error('Choose an image, video or audio reference.');
    if(this.project)return this.uploadProjectAsset(file,'video');
    const body=new FormData();body.append('image',file);body.append('type','input');body.append('subfolder','h3_references');
    const response=await api.fetchApi('/upload/image',{method:'POST',body});
    if(!response.ok)throw new Error(`Could not upload the video (HTTP ${response.status}).`);
    const result=await response.json();
    return {file:{filename:result.name,subfolder:result.subfolder,type:result.type}};
  }

  async describeImage(action,ref,text) {
    const body={action,text};
    const source=ref=> {
      if(ref?.mediaFile) {
        const file=ref.mediaFile;
        return {file:{filename:file.filename,subfolder:file.subfolder??'',type:file.type??'input'}};
      }
      if(ref?.refmod) {
        const mod=effectiveRefmods(this.editor.state,{includeDisabled:true}).find(item=>item.slot===ref.name);
        if(mod)return {refmod:{name:mod.name,member:mod.member??-1,description:mod.description}};
      }
      return {};
    };
    Object.assign(body,source(ref));
    if(action==='clear_all')body.images=this.editor.referenceOptions().filter(ref=>ref.name.startsWith('image'))
      .map(ref=>({slot:ref.name,...source(ref)}));
    if(['resolve','regenerate'].includes(action)) {
      const controller=this.story();
      if(controller) {
        const {output}=await app.graphToPrompt();
        body.prompt=output;body.story=String(controller.node.id);
      }
    }
    const response=await api.fetchApi('/h3c/images/description',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    if(response.status===404)throw new Error('Restart ComfyUI, then refresh this page to enable image descriptions.');
    const result=await response.json();
    if(!response.ok||!result.ok)throw new Error(result.error??'Could not update the image description.');
    return result;
  }

  async loadRefmods() {
    const response = await api.fetchApi('/h3c/refmods');
    if (response.status === 404) throw new Error('The RefMod route is unavailable. Restart ComfyUI, then refresh the library.');
    const result = await response.json().catch(() => null);
    if (!response.ok) throw new Error(result?.error || `Could not read the RefMod library (HTTP ${response.status}).`);
    if (!Array.isArray(result?.entries)) throw new Error('ComfyUI returned an invalid RefMod library.');
    this.refmodChoices = result.entries;
    this.editor.renderRefmods();
    this.editor.render();
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

  hook(name, extra) {
    const previous = this.node[name];
    this.node[name] = function (...args) {
      const result = previous?.apply(this, args);
      extra(...args);
      return result;
    };
  }

  relayout() {
    const node = this.node;
    if (!node.size || typeof node.computeSize !== 'function') return;
    const needed = Number(node.computeSize()?.[1]) || 0;
    if (needed > node.size[1] + 1) node.setSize?.([node.size[0], needed]);
    node.setDirtyCanvas?.(true, true);
  }

  // Nodes saved with the full editor on them shrink to the face; the width stays.
  fit() {
    const node = this.node;
    if (!node.size || typeof node.computeSize !== 'function') return;
    const needed = Number(node.computeSize()?.[1]) || 0;
    if (needed && node.size[1] > needed) node.setSize?.([node.size[0], needed]);
  }

  replaceTimeline(text) {
    if (!this.writeTimeline(text)) throw Error(readOnlyNote(unknownFeatures(this.readState())));
    this.editor.load();
    this.saved.changed();
    this.schedule(0);
    this.node.setDirtyCanvas?.(true, true);
  }

  confirmAudioUnlock() {
    const options={title:'Return to continuous audio?',message:'Box-specific gaps and audio ordering will be removed.'};
    return app.extensionManager?.dialog?.confirm?.(options) ?? window.confirm(`${options.title}\n\n${options.message}`);
  }

  async prepareRegeneration(box, count) {
    if(this.project) await this.project.save();
    else await this.saved.flush();
    const id=this.editor.state.boxes[box-1]?.id;
    const body=this.project?{name:this.project.project.sequence,
      timeline:stringifyJSON(this.project.project.inspection.timeline),settings:this.project.project.inspection.settings}:this.requestBody();
    if(!this.project) {
      body.editor={graph:String(this.node.graph?.extra?.h3c_story_id??this.node.graph?.id??''),node:String(this.node.id)};
      if(Object.values(body.settings).some(value=>value==null)) {
        const snapshot=await app.graphToPrompt();
        body.workflow=snapshot.output;
        body.timeline_node=captureTimelineId(snapshot,this.node.id,{root:this.node.graph===(app.rootGraph??app.graph)});
      }
    }
    return confirmRegeneration({body,box:id,count,snapshot:()=>JSON.stringify([this.requestBody(),this.project?.project?.revision]),
      request:(url,body)=>this.stillRequest(url,body),
      confirm:options=>app.extensionManager?.dialog?.confirm?.(options)??window.confirm(`${options.title}\n\n${options.message}`)});
  }

  // `layer` renders one of a clip's other videos by its id instead of a box or bridge.
  async queue(count, box, bridge, receipt, layer = null) {
    if(this.editor?.promptDraftsReady?.()===false)throw new Error('Finish or discard the unsaved prompt fields before generating.');
    if (this.feed) throw new Error('A Render is still queueing runs. Press Stop first, or wait for it to finish.');
    if (this.project && layer != null) throw new Error("Managed jobs can't render a clip's other videos yet. "
      + 'Render this Timeline from its node in ComfyUI.');
    this.submitting = true;
    this.requested = box ?? null;
    this.requestedBridge = bridge ?? null;
    this.feedMessage = null;
    const one = layer != null ? 'one video' : bridge != null ? 'one bridge' : 'one box';
    try {
      if (this.project) return await this.project.render({count: box == null && bridge == null ? 1 : count,
        boxId: box != null ? this.editor.state.boxes[box - 1]?.id : undefined, bridgeId: bridge, receipt});
      const definitions=await (await api.fetchApi('/object_info')).json();
      const post = () => this.postRun(definitions, box, bridge, one, receipt, layer);
      const ahead = queueAhead(app.ui?.settings?.getSettingValue?.(QUEUE_AHEAD_SETTING));
      if (!ahead || count <= ahead) {
        for (let run = 0; run < count; run++) await post();
        return;
      }
      // Each run renders the next box that needs it, so a failure repeats down a long queue. Keep a few in ComfyUI.
      this.feed = new QueueFeed({total: count, ahead, post,
        cancel: ids => api.fetchApi('/queue', {method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({delete: ids})}),
        lookup: id => this.runState(id),
        listen: (type, handler) => {
          const listener = event => handler(event.detail);
          api.addEventListener(type, listener);
          return () => api.removeEventListener(type, listener);
        },
        onChange: () => this.showProgress(),
        onEnd: outcome => {
          this.feed = null;
          this.feedMessage = feedNote(outcome);
          if (!this.removed) this.editor.renderHead();
          this.showProgress();
        }});
      await this.feed.start();
    } catch (error) {
      this.requested = null;
      this.requestedBridge = null;
      this.feed = null;
      throw error;
    } finally { this.submitting = false; this.showProgress(); }
  }

  // Posts one run of the Timeline's video outputs to ComfyUI and returns its prompt id.
  async postRun(definitions, box, bridge, one, receipt, layer = null) {
    if(receipt?.editor) await this.saved.flush();
    const snapshot=await app.graphToPrompt();
    const id=captureTimelineId(snapshot,this.node.id,{root:this.node.graph===(app.rootGraph??app.graph)});
    const outputs=videoOutputs(snapshot,id,definitions),prompt=isolateVideoPrompt(snapshot,id,outputs);
    const target=prompt.output[id];
    if(box!=null || bridge!=null || layer!=null) {
      if(typeof target.inputs.timeline!=='string') throw new Error(`The Timeline boxes must be editable here to render ${one}.`);
      const request=layer!=null?{render_layer:layer}:bridge!=null?{render_bridge:bridge}:{render_box:box};
      if(receipt) request.rebuild_continuity=receipt;
      target.inputs.timeline=stringifyJSON({...parseJSON(target.inputs.timeline),...request});
    }
    const promptId=crypto.randomUUID();
    const queued=await this.stillRequest('/prompt',{prompt_id:promptId,prompt:prompt.output,
      partial_execution_targets:outputs,extra_data:{extra_pnginfo:{workflow:prompt.workflow}}});
    if(queued.error) throw new Error(queued.error.message??String(queued.error));
    return queued.prompt_id??promptId;
  }

  // Where ComfyUI has a run: still in its queue, or finished in its history.
  async runState(id) {
    const queue = await (await api.fetchApi('/queue')).json();
    if ([...(queue.queue_running ?? []), ...(queue.queue_pending ?? [])].some(row => row[1] === id)) return 'queued';
    const item = (await (await api.fetchApi(`/history/${id}`)).json())[id];
    if (!item) return 'gone';
    return item.status?.status_str === 'success' ? 'success' : 'error';
  }

  settingChanged(name) {
    if (name === 'context_frames') this.editor.contextChanged();
    this.history.capture();
    this.changed();
  }

  changed() {
    this.editor.markStale();
    this.saved.changed();
    this.schedule();
    this.showProgress();
  }

  schedule(delay = 300) {
    ++this.request;
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.refresh(), delay);
  }

  // The Timeline's name, text and render settings, as every status and takes request sends them.
  requestBody() {
    return { name: this.project?.project?.sequence ?? widgetValue(this.node, 'name'), timeline: this.widget.value ?? '',
      settings: Object.fromEntries(SETTINGS.map((key) => [key, widgetValue(this.node, key)])) };
  }

  async refresh() {
    await this.saved.ready;
    // Requests still waiting are checked by their own timers; an edit does not need to ask again.
    if(!this.stillTimer)this.recoverStills();
    if(!this.referenceTimer)this.recoverReferences();
    if (this.project) {
      try {
        await this.saved.ready;
        if (!this.project.busy) await this.project.refresh();
        const status = this.project.project?.status;
        if (status && !this.project.conflict) this.editor.setStatus(status);
      } catch (error) {this.editor.setStatus({ok: false, error: error.message});}
      return;
    }
    const name = widgetValue(this.node, 'name');
    const request = ++this.request;
    if (!name) {
      this.editor.setStatus(null);
      return;
    }
    const body = this.requestBody();
    // The Timeline text is compared as it is; serializing it again copies the whole Timeline.
    const unchanged = () => {
      const now = this.requestBody();
      return now.timeline === body.timeline && JSON.stringify([now.name, now.settings]) === JSON.stringify([body.name, body.settings]);
    };
    // A status for a Timeline that changed while it was asked for leaves the drawn one, now stale, until the next.
    const show = (status) => {
      if (request !== this.request || this.removed) return;
      if (unchanged()) this.editor.setStatus(status);
      else this.editor.markStale();
    };
    try {
      const status = await this.takesClient.watch(api.fetchApi(STATUS_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: this.takesClient.statusBody(body),
      }).then((response) => response.json()));
      show(status);
      // While the full video or the video so far builds in the background, check again now and then in case its event is missed.
      if ((status?.full_video_building || status?.preview_video_building) && request === this.request && !this.removed) this.schedule(15000);
    } catch (error) {
      show({ ok: false, error: `Status unavailable: ${error?.message ?? error}` });
    }
  }

  configureProject({preserveLocal=false}={}) {
    const node = this.node;
    forkProject(node);
    const metadata = node.properties?.h3c_project;
    if (metadata?.mode !== 'attached' && !this.project) return;
    if (metadata?.mode === 'attached' && this.project?.metadata === metadata) return;
    const shown = studio(), page = shown.page, reopen = shown.host === this && !shown.root.hidden;
    if (reopen) shown.close();
    if (metadata?.mode !== 'attached') {
      this.saved.destroy(); this.project = null; this.editor.host.projectAttached = false;
      // Detaching the same node must also leave the reserved native sequence.
      if (!node.properties.h3c_fork_sequence) {
        node.properties.h3c_project = {mode: 'fork'}; forkProject(node);
      }
      this.saved = mountSavedState(node, this.face.root, {app, api, loaded: () => {
        this.editor.load(); this.schedule(0);
      }});
      if (reopen) this.openStudio(page, {link: false});
      return;
    }
    this.saved?.destroy(); this.project?.destroy();
    const bar = document.createElement('div'), label = document.createElement('span'), choices = document.createElement('span');
    bar.style.cssText = 'font-size:11px;padding:4px 0;display:flex;gap:6px;align-items:center;flex-wrap:wrap';
    bar.append(label, choices); this.face.root.append(bar);
    const key = `${node.graph?.id ?? ''}/${node.id}/${metadata.id}`;
    if (!projectSessions.has(key)) projectSessions.set(key, {});
    const project = this.project = new ProjectSession({metadata, session: projectSessions.get(key),
      read: () => ({timeline: this.widget.value, settings: this.requestBody().settings,
        assets: node.properties.h3c_asset_bindings ?? []}),
      apply: value => {
        this.widget.value = stringifyJSON(value.timeline);
        for (const name of SETTINGS) if (findWidget(node, name) && value.settings?.[name] != null)
          findWidget(node, name).value = value.settings[name];
        if (value.sequence) findWidget(node, 'name').value = value.sequence;
        node.properties.h3c_asset_bindings = structuredClone(value.assets ?? []);
        this.editor.load(); node.setDirtyCanvas?.(true, true);
      },
      status: (message, conflict = false) => {setText(label, message); choices.hidden = !conflict;},
      request: async (path, options = {}) => {
        if (options.method === 'PUT') await this.registerProjectFiles(options.body);
        const response = await api.fetchApi(path, {...options,
          headers: {'Content-Type': 'application/json', ...options.headers},
          ...(options.body ? {body: stringifyJSON(options.body)} : {})});
        const result = parseJSON(await response.text());
        if (!response.ok) {const error = new Error(projectErrorMessage(result, response.status));
          Object.assign(error, {status: response.status, code: result.error?.code}); throw error;}
        return result;
      }});
    this.editor.host.projectAttached = true;
    for (const [text, saved] of [['Load project edits', true], ['Keep my edits', false]]) {
      const button = document.createElement('button'); button.textContent = text;
      button.onclick = () => project.resolve(saved).catch(error => {label.textContent = error.message;}); choices.append(button);
    }
    choices.hidden = true;
    const ready = project.load({preserveLocal}); ready.catch(error => {label.textContent = error.message;});
    let timer, editedAt = 0, dirty = false;
    // Saves after a pause in editing, or when focus leaves the field the edit was made in.
    const save = () => {
      dirty = false;
      if (autosaveEnabled(app)) project.save().catch(() => {});
    };
    const later = () => {
      if (!autosaveEnabled(app)) return;
      if (userBusy(editedAt)) {timer = setTimeout(later, AUTOSAVE_IDLE_MS); return;}
      save();
    };
    const leave = () => {
      releaseUser();
      if (!dirty) return;
      clearTimeout(timer); save();
    };
    document.addEventListener('focusout', leave, true);
    this.saved = {bar, ready,
      flush: async () => {await ready; await project.save();},
      changed: () => {
        editedAt = Date.now();
        clearTimeout(timer);
        if(!autosaveEnabled(app)){setText(label,AUTOSAVE_OFF);return;}
        dirty = true;
        timer = setTimeout(later, AUTOSAVE_IDLE_MS);
      },
      destroy: () => {clearTimeout(timer); document.removeEventListener('focusout', leave, true); project.destroy(); bar.remove();}};
    if (reopen) this.openStudio(page, {link: false});
  }

  async uploadProjectAsset(file, kind, expectedHash) {
    const body = new FormData(); body.append('kind', kind); body.append('file', file);
    if (expectedHash) body.append('expected_sha256', expectedHash);
    const response = await api.fetchApi('/h3c/api/v1/assets', {method: 'POST', body});
    const asset = parseJSON(await response.text());
    if (!response.ok) throw new Error(asset.error?.message ?? 'Could not upload project source.');
    const uploaded = this.node.properties.h3c_uploaded_assets ??= [];
    const sourceFile = asset.files[kind]; uploaded.push({asset_id: asset.id, file: sourceFile});
    return {file: sourceFile, title: file.name ?? sourceFile.filename,
      ...(kind === 'audio' ? await this.audioInfo(sourceFile) : {})};
  }

  async registerProjectFiles(body) {
    const line = body.timeline;
    const old = this.project.project?.inspection?.timeline ?? this.project.project?.timeline ?? {};
    const fileKey = file => stringifyJSON([file?.type, file?.subfolder ?? '', file?.filename]);
    const targets = value => [
      ...Object.entries(value.reference_replacements??{}).map(([slot,item])=>({file:item.file,binding:{kind:'reference_replacement',slot}})),
      ...(value.pictures ?? []).map(item => ({file: item.file, binding: {kind: 'picture', slot: item.slot, ...(item.title ? {title: item.title} : {})}})),
      ...(value.audio_clips ?? []).map(item => ({file: item.file, binding: {kind: 'audio_clip', slot: item.slot}})),
      ...(value.voice_clips ?? []).map(item => ({file: item.file, binding: {kind: 'voice_clip', slot: item.slot}})),
      ...(value.plates ?? []).map(item => ({file: item.image, binding: {kind: 'plate', id: item.id}})),
      ...(value.boxes ?? []).flatMap(box => (box.previews ?? []).map(item => ({file: item.guide,
        binding: {kind: 'guide', box: box.id, ...(item.target ? {target: item.target} : {shot: item.shot})}}))),
      ...[...(value.boxes ?? []).flatMap(box=>(box.previews ?? []).flatMap(item=>item.images ?? [])),
          ...(value.still_requests ?? []).flatMap(item=>item.images ?? []),
          ...(value.reference_preparation?.assets??[]).flatMap(item=>item.candidates??[])].map(image=>({file: image.file,
        binding:{kind:'candidate',request_id:image.request_id,prompt_id:image.prompt_id,batch_index:image.batch_index}}))
    ].filter(item => item.file);
    const identity = binding => stringifyJSON([binding.kind, binding.slot, binding.id, binding.box,
      binding.kind==='guide' ? binding.target ?? (binding.shot===1?{kind:'first'}:{kind:'shot',shot:binding.shot}) : null,
      binding.request_id,binding.prompt_id,binding.batch_index]);
    const desired = [...new Map(targets(line).map(item=>[identity(item.binding),item])).values()], prior = targets(old);
    let bindings = structuredClone(body.assets ?? []);
    for (const target of desired) {
      const was = prior.find(item => identity(item.binding) === identity(target.binding));
      const registered = bindings.some(asset => asset.bindings.some(binding => identity(binding) === identity(target.binding)));
      if (registered && was && fileKey(was.file) === fileKey(target.file)) {
        if (target.binding.kind === 'picture') for (const asset of bindings) for (const binding of asset.bindings) {
          if (identity(binding) !== identity(target.binding)) continue;
          if (target.binding.title) binding.title = target.binding.title; else delete binding.title;
        }
        continue;
      }
      let upload = this.node.properties.h3c_uploaded_assets?.find(item => fileKey(item.file) === fileKey(target.file));
      if (!upload) {
        const response = await api.fetchApi(`/view?${new URLSearchParams(target.file)}`);
        if (!response.ok) throw new Error('Could not read the selected source for this project.');
        const role = target.binding.kind==='reference_replacement'
          ? {image:'picture',video:'video',audio:'audio',video_audio:'audio'}[referenceType(target.binding.slot)]
          : ['audio_clip', 'voice_clip'].includes(target.binding.kind) ? 'audio'
          : ['plate', 'guide', 'candidate'].includes(target.binding.kind) ? 'guide' : 'picture';
        const source = await response.blob();
        await this.uploadProjectAsset(new File([source], target.file.filename), role);
        upload = this.node.properties.h3c_uploaded_assets.at(-1);
      }
      bindings = bindings.map(asset => ({...asset, bindings: asset.bindings.filter(binding => identity(binding) !== identity(target.binding))}));
      bindings.push({asset_id: upload.asset_id, bindings: [target.binding]});
      // Use the registered role file in the editable document after ingestion.
      for(const authored of targets(line).filter(item=>identity(item.binding)===identity(target.binding)))
        Object.assign(authored.file, upload.file);
    }
    const active = new Set(desired.map(item => identity(item.binding)));
    const textHash = line.timed_text?.source_sha256;
    bindings = bindings.map(asset => ({...asset, bindings: asset.bindings.filter(binding => binding.kind !== 'whisper'
      || binding.source_sha256 === textHash)}));
    if (textHash && !bindings.some(asset => asset.bindings.some(binding => binding.kind === 'whisper'))) {
      // Asset IDs identify original bytes; this also restores a prior source on Undo.
      bindings.push({asset_id: `asset_${textHash}`, bindings: [{kind: 'whisper', source_sha256: textHash}]});
    }
    body.assets = bindings.map(asset => ({...asset, bindings: asset.bindings.filter(binding => binding.kind === 'whisper'
      || (binding.kind === 'picture' && Number(binding.slot.slice(5)) <= 16) || active.has(identity(binding)))})).filter(asset => asset.bindings.length);
  }
}

app.registerExtension({
  name: 'h3c.timeline',
  settings: [{
    id: QUEUE_AHEAD_SETTING,
    category: ['H3 Continuity', 'Timeline', 'Runs kept in the queue'],
    name: 'Runs kept in ComfyUI’s queue while Render all works',
    tooltip: 'Render all queues the next runs as earlier ones finish and stops at the first failure, so a failing box is not '
      + 'retried down a long queue. Keep this page open while it works. 0 queues every run at once.',
    type: 'number',
    attrs: {min: 0, max: 100, step: 1},
    defaultValue: DEFAULT_AHEAD,
  }],
  setup() {
    const graphToPrompt = app.graphToPrompt;
    app.graphToPrompt = async function (...args) {
      for (const host of mounted) {
        syncImageOutputs(host.node, host.editor.state, host.widget?.value);
        host.node.properties ??= {};
        host.node.properties.h3c_image_output_box = Math.max(1, host.editor.selected + 1);
      }
      return compileImageOutputs(await graphToPrompt.apply(this, args));
    };
    for (const type of WATCH_EVENTS) {
      api.addEventListener(type, (event) => {
        watch = watchEvent(watch, type, event.detail);
        for (const host of mounted) {
          if (RUN_ENDS.has(type)) {
            host.requested = host.requestedBridge = null;
            host.recoverImageResult(event.detail?.prompt_id);
          }
          host.showProgress();
        }
      });
    }
    api.addEventListener('execution_success', () => {
      for (const host of mounted) host.schedule(0);
    });
    // A full video built in the background is ready (or failed): ask for status again.
    api.addEventListener('h3c-full-video', (event) => {
      for (const host of mounted) if (host.requestBody().name === event.detail?.name) host.schedule(0);
    });
  },
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData?.name !== NODE_TYPE) return;
    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function (...args) {
      const result = onNodeCreated?.apply(this, args);
      if (!findWidget(this, 'timeline')) return result;
      const host = new TimelineHost(this);
      host.editor.startIfEmpty();
      host.history.reset(host.historyState());
      this.setSize?.([Math.max(this.size?.[0] ?? 0, 420), Number(this.computeSize?.()?.[1]) || FACE_HEIGHT]);
      host.schedule(0);
      return result;
    };
  },
});
