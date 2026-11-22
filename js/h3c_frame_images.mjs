// Marker images own editable still prompts, candidates and the acceptance transaction. Queue recovery belongs to the host.
import {frameTargets, applyFrameGuide, endpointGuide, endpointReference} from './h3c_shot_preview.mjs?v=1dfc1612e462';
import {parseState, serialize, newSeed} from './h3c_timeline_model.mjs?v=1dfc1612e462';
import {StillPromptPreparation,preparedStillPrompt} from './h3c_still_prompt_preparation.mjs?v=9ea1bfd9b6b5';

import {seedValue, stringifyJSON} from './h3c_project.mjs?v=0882b8a6265a';
import {decorateIcon,icon,setIconLabel} from './h3c_icons.mjs';
import {setText} from './h3c_dom.mjs?v=584a9bf55653';
import {SwitchSection} from './h3c_switch_section.mjs?v=c253500f4908';
import {promptSections} from './h3c_prompt_sections.mjs?v=1f35473e5668';

const key = target => target.kind === 'shot' ? `shot:${target.shot}` : target.kind;
export const targetLabel = target => target.kind === 'shot' ? `Shot ${target.shot}` : target.kind === 'last' ? 'Last' : 'First';
const itemTarget = item => item.target ?? (item.shot === 1 ? {kind:'first'} : {kind:'shot',shot:item.shot});
import {acceptSceneAnchor,selectSceneAnchor,sceneAnchor} from './h3c_still_scene.mjs?v=0906bb5de9d7';

const guideLabel = (state, guide) => {
  const index=state.boxes.findIndex(box=>box.id===guide.box);
  return `Clip ${index<0?guide.box:index+1} · ${targetLabel(guide.target)}`;
};

// A status flag describes matching settings. Saved video presence (also in archived takes) answers the boundary question.
export function boundarySnapshot(state, boxId, status, lists) {
  const index = state.boxes.findIndex(box => box.id === boxId);
  const a = state.boxes[index - 1]?.id, b = state.boxes[index]?.id;
  const rendered = id => !!status?.boxes?.find(box => box.id === id)?.video?.file
    || !!lists[id]?.in_use || (lists[id]?.takes ?? []).some(take => !!take.video);
  const result = {a,b,renderedA:!!a && rendered(a),renderedB:!!b && rendered(b)};
  const previous = status?.boxes?.find(box => box.id === a), selected = lists[a]?.in_use;
  if (selected?.created && previous?.video?.file?.v === selected.created && previous.thumb?.v === selected.created)
    result.ending = {box:a,take:String(selected.created),created:selected.created,file:structuredClone(previous.thumb)};
  return result;
}

function el(tag, text, className) {
  const node = document.createElement(tag);if (text != null) node.textContent=text;if (className) node.className=className;return node;
}
function field(label, control) {
  const node=el('label',null,'h3ct-field');node.hidden=control.hidden;node.style.cssText='flex-direction:column;align-items:stretch';node.append(el('span',label,'h3ct-label'),control);return node;
}
function button(label, run) {
  const node=el('button',label,'h3ct-button');node.type='button';
  node.addEventListener('click',event=>{event.preventDefault();Promise.resolve().then(run).catch(error=>node.dispatchEvent(
    new CustomEvent('h3c-image-error',{bubbles:true,detail:error.message})));});return node;
}

// An image file dropped on `node` goes to onFile. The zone keeps file drops to itself: ComfyUI loads a file dropped
// anywhere else on the page.
export function imageDrop(node, onFile) {
  const files=event=>event.dataTransfer?.types?.includes('Files');
  const over=on=>node.classList.toggle('h3ct-drop-over',on);
  node.addEventListener('dragover',event=>{if(!files(event))return;event.preventDefault();event.stopPropagation();event.dataTransfer.dropEffect='copy';over(true);});
  node.addEventListener('dragleave',event=>{if(!node.contains(event.relatedTarget))over(false);});
  node.addEventListener('drop',event=>{
    over(false);if(!files(event))return;event.preventDefault();event.stopPropagation();
    const file=[...event.dataTransfer.files].find(item=>item.type.startsWith('image/'));
    if(file)onFile(file);
  });
}

export class FrameImages {
  constructor(editor) {
    this.editor=editor;this.host=editor.host;this.target={kind:'first'};this.boxId=null;
    this.root=el('div',null,'h3ct-frame-images');
    this.root.addEventListener('h3c-image-error',event=>this.note(event.detail));
    this.titleEl=el('strong');this.titleEl.tabIndex=-1;this.promptEl=el('textarea',null,'h3ct-text');this.promptEl.rows=5;
    this.promptEl.setAttribute('aria-label','Frame image prompt');
    this.promptEl.placeholder='Leave blank to use the clip video prompt.';
    this.sourcePins=[];this.sourceEl=el('select',null,'h3ct-note');
    this.sourceEl.setAttribute('aria-label','Pinned still source');
    this.sourceEl.hidden=typeof this.host.stillSources!=='function';
    this.guideSourceEl=el('p',null,'h3ct-hint');this.guideSourceEl.hidden=true;
    this.boundaryHintEl=el('p',null,'h3ct-hint');
    this.momentEl=el('input',null,'h3ct-note');this.momentEl.type='number';this.momentEl.min='0';this.momentEl.step='1';
    this.momentEl.setAttribute('aria-label','Delivered source frame');this.momentEl.hidden=this.sourceEl.hidden;
    this.sourceEl.addEventListener('change',()=>{
      const pin=this.sourceEl.value===''?null:this.sourcePins[Number(this.sourceEl.value)];
      this.saveSource(pin);this.momentEl.disabled=!pin;this.momentEl.value=pin?String(pin.moment):'';
    });
    this.momentEl.addEventListener('change',()=>{
      const pin=this.sourcePins[Number(this.sourceEl.value)],moment=Number(this.momentEl.value);
      if (this.sourceEl.value==='' || !pin || !Number.isInteger(moment) || moment<0) {this.note('Choose a nonnegative delivered source frame.');return;}
      const edited={...structuredClone(pin),moment};this.sourcePins[Number(this.sourceEl.value)]=edited;this.saveSource(edited);
    });
    this.seedEl=el('input',null,'h3ct-note');this.seedEl.type='text';this.seedEl.inputMode='numeric';
    this.seedEl.setAttribute('aria-label','Image seed');this.seedEl.placeholder='Random for each candidate';
    this.seedEl.addEventListener('change',()=>{
      this.seedEdited=true;
      const seed=this.seedEl.value===''?undefined:seedValue(this.seedEl.value);
      if(this.seedEl.value!==''&&seed===undefined) {this.note('Image seed must be an unsigned 64-bit integer.');return;}
      this.saveField('still_seed',seed);
    });
    this.promptEl.addEventListener('input',()=>{this.promptEditing=true;this.preparation.invalidate();this.renderGenerateControls();});
    this.promptEl.addEventListener('change',()=>{this.promptEditing=false;this.saveField('still_prompt',this.promptEl.value);});
    this.uploadButton=decorateIcon(button('',()=>this.chooseUpload()),'upload','Upload guide…');
    this.uploadButton.title='Upload a picture as this frame’s guide. You can also drop one on the image.';
    this.generateButton=decorateIcon(button('',()=>this.generate()),'stills','Generate candidates',{text:true});
    this.settingsButton=decorateIcon(button('',async()=>{try{await this.host.openStillGenerator?.();}catch(error){this.note(error.message);}}),'settings','Generator settings');
    this.settingsButton.title='Open the connected generator in the graph to change models, sampler settings or LoRAs.';
    this.settingsButton.hidden=!this.host.openStillGenerator;
    this.generateButton.classList.add('h3ct-primary');
    const actions=el('div',null,'h3ct-row h3ct-image-actions');actions.append(this.generateButton,this.uploadButton,this.settingsButton);
    this.additionalReferencesEl=el('p',null,'h3ct-hint');this.additionalReferencesEl.hidden=true;
    this.acceptedEl=el('div',null,'h3ct-image-hero');imageDrop(this.acceptedEl,file=>this.upload(file).catch(error=>this.note(error.message)));
    this.candidatesEl=el('div',null,'h3ct-candidates');this.endingEl=el('div',null,'h3ct-row');
    this.recoveryEl=el('div');
    this.noteEl=el('p',null,'h3ct-hint');this.noteEl.setAttribute('role','status');
    this.preparation=new StillPromptPreparation(editor,()=>{this.promptEditing=false;this.render();});
    this.promptExcerpt=el('p',null,'h3ct-prompt-excerpt');
    this.promptSummary=el('div',null,'h3ct-prompt-summary');
    this.promptSummary.append(field('Frame image prompt',this.promptEl),this.promptExcerpt);
    this.seedSection=new SwitchSection('Fixed image seed',{className:'h3ct-image-seed',onToggle:on=>{
      this.seedEdited=true;this.seedEl.value=on?String(newSeed()):'';this.saveField('still_seed',on?seedValue(this.seedEl.value):undefined);
    }});
    this.seedSection.body.append(field('Image seed',this.seedEl));
    this.candidateTitle=el('strong',null,'h3ct-candidate-title');
    this.candidateHint=el('p','Candidates stay separate until you choose Use as guide.','h3ct-hint');
    const head=el('div',null,'h3ct-row h3ct-image-head');head.append(this.titleEl);
    // Candidates sit right under the image so a finished generation can be chosen without scrolling past the prompt.
    this.candidatePicker=el('div',null,'h3ct-candidate-picker');this.candidatePicker.append(this.candidateTitle,this.candidatesEl,this.candidateHint);
    this.root.append(head,this.acceptedEl,this.candidatePicker,actions,this.noteEl,this.guideSourceEl,this.boundaryHintEl,this.endingEl,this.additionalReferencesEl,this.promptSummary,
      this.seedSection.root,this.recoveryEl);
    this.candidateCounts=new Map();
  }
  note(text) {
    setText(this.noteEl,text);
    if (this.editor.uploadNote) {setText(this.editor.uploadNote,text);this.editor.uploadNote.hidden=!text;}
  }
  live() {
    const editor=this.editor, selectedId=editor.box()?.id;
    const saved=parseState(this.host.read());
    if (serialize(saved)!==serialize(editor.state)) {
      editor.state=saved;
      const index=saved.boxes.findIndex(box=>box.id===selectedId);
      editor.selected=index>=0?index:Math.min(editor.selected,Math.max(0,saved.boxes.length-1));
    }
    return editor.state;
  }
  location(boxId=this.boxId,target=this.target) {
    const state=this.editor.state,index=state.boxes.findIndex(box=>box.id===boxId);
    const resolved=index<0?null:frameTargets(state,index,this.host.context()).find(item=>key(item.target)===key(target));
    if (!resolved) throw new Error('The selected target was removed or its timing is unreadable.');
    return {box:state.boxes[index],index,...resolved};
  }
  open(boxId,target) {
    this.host.touchStills?.();
    if (target.kind==='shot'&&target.shot===1) target={kind:'first'};
    const moved=this.boxId!==boxId||key(this.target)!==key(target);
    this.boxId=boxId;this.target=structuredClone(target);
    if (moved) {
      this.promptEditing=false;
      this.previousGuide=null;
      const saved=this.location().box.previews?.find(item=>key(itemTarget(item))===key(target));
      this.recipeAvailable=undefined;this.seedEdited=false;this.seedEl.value=saved?.still_seed==null?'':String(saved.still_seed);
      this.note('');
      for(const details of this.root.querySelectorAll(':scope > details')) details.open=false;
      this.refreshControls();
    }
    this.render();
    if (moved) {
      this.sourcePins=[];this.sourceEl.replaceChildren();
      this.showEnding().catch(error=>this.note(error.message));
    }
    const sourcesReady=this.sourcesReady=this.loadSources();sourcesReady.catch(error=>{
      if(this.sourcesReady===sourcesReady&&this.boxId===boxId&&key(this.target)===key(target)) this.note(error.message);
    });
  }
  refreshControls() {
    const box=this.editor.state.boxes.find(box=>box.id===this.boxId);
    if(!box) return;
    const boxId=this.boxId,stamp=key(this.target);
    const ready=this.controlsReady=this.loadControls();
    ready.catch(error=>{
      if(this.controlsReady===ready&&this.boxId===boxId&&key(this.target)===stamp) this.note(error.message);
    });
    return ready;
  }
  async loadControls() {
    if(!this.host.stillControls) return;
    const boxId=this.boxId,stamp=key(this.target);
    const generation=this.host.referenceContext?.(),load=this.controlLoad={};
    this.controlsFailed=false;
    let controls;
    try {controls=await this.host.stillControls();}
    catch(error) {if(this.controlLoad===load&&generation===this.host.referenceContext?.()&&boxId===this.boxId&&stamp===key(this.target)) this.controlsFailed=true;throw error;}
    if(this.controlLoad!==load||generation!==this.host.referenceContext?.()||boxId!==this.boxId||stamp!==key(this.target)) return;
    this.recipeAvailable=!!controls;
    this.generatorLabel=controls?.label;this.adapter=controls?.adapter;this.referenceLabel=controls?.referenceLabel;this.seedScope=controls?.seedScope;
    this.additionalReferences=controls?.additionalReferences??[];
    this.render();
  }
  saveField(field,value) {
    this.live();const {box,frame}=this.location();
    if(field==='still_prompt'&&typeof value==='string') {
      this.promptEditing=false;
    }
    this.host.undoStep?.();
    let saved=box.previews?.find(item=>key(itemTarget(item))===key(this.target));
    if(!saved) (box.previews??=[]).push(saved={target:structuredClone(this.target),frame});
    if(value===undefined) delete saved[field];else saved[field]=value;
    this.editor.commit(false);this.host.undoStep?.();this.render();
  }
  saveSource(pin) {
    this.live();const {box,frame}=this.location();
    this.host.undoStep?.();
    let saved=box.previews?.find(item=>key(itemTarget(item))===key(this.target));
    if (!saved) (box.previews??=[]).push(saved={target:structuredClone(this.target),frame});
    saved.still_source=structuredClone(pin ?? null);this.editor.commit(false);this.host.undoStep?.();this.render();
  }
  async loadSources() {
    if (!this.host.stillSources) return;
    const box=this.boxId,target=structuredClone(this.target),stamp=key(target),{frame}=this.location(),load=new AbortController();
    const generation=this.host.referenceContext?.();
    this.sourceLoad?.abort();this.sourceLoad=load;this.sourcesFailed=false;this.sourceEl.disabled=true;
    if(!this.sourcePins?.length) {
      const loading=el('option','Loading saved continuity sources…');loading.value='';this.sourceEl.replaceChildren(loading);this.momentEl.disabled=true;
    }
    let result;
    try {
      result=await this.host.stillSources({box,target,frame},{signal:load.signal});
      if (!result.ok) throw new Error(result.error ?? 'Could not read saved continuity sources.');
    } catch(error) {
      if(generation!==this.host.referenceContext?.()||this.sourceLoad!==load||this.boxId!==box||key(this.target)!==stamp) return;
      this.sourcesFailed=true;
      const failed=el('option','Saved sources unavailable; Generate retries.');failed.value='';this.sourceEl.replaceChildren(failed);this.momentEl.disabled=true;
      throw error;
    }
    if (generation!==this.host.referenceContext?.()||this.sourceLoad!==load || this.boxId!==box || key(this.target)!==stamp) return;
    this.sourceEl.disabled=false;
    this.live?.();
    const saved=this.location().box?.previews?.find(item=>key(itemTarget(item))===stamp);
    this.previousGuide=structuredClone(result.guide_source??null);
    const selected=null;
    if (!Object.hasOwn(saved ?? {},'still_source')) this.saveSource(selected);
    this.sourcePins=structuredClone(result.choices ?? []);
    const equal=(a,b)=>['sequence','box','take','created','layout','latent_stamp','pixel_stamp'].every(field=>stringifyJSON(a?.[field])===stringifyJSON(b?.[field]));
    let chosen=selected?this.sourcePins.findIndex(pin=>equal(pin,selected)):-1;
    const missing=selected && chosen<0;
    if (missing) {chosen=this.sourcePins.length;this.sourcePins.push(structuredClone(selected));}
    else if (selected) this.sourcePins[chosen]=structuredClone(selected);
    const none=el('option','Prompt and references only');none.value='';
    this.sourceEl.replaceChildren();this.sourceEl.append(none);
    this.sourcePins.forEach((pin,index)=>{
      const option=el('option',`${pin.box} · ${pin.created ?? pin.take} · ${this.adapter==='pixels'?'Delivered video pixels':pin.latent_stamp?'Original H3 latent':'Pixels only'} · frame ${pin.moment}${missing&&index===chosen?' · missing or changed':''}`);
      option.value=String(index);this.sourceEl.append(option);
    });
    this.sourceEl.value=chosen<0?'':String(chosen);
    this.momentEl.disabled=!selected;this.momentEl.value=selected?String(selected.moment):'';
    if (missing) this.note('The selected saved source is missing or changed. Choose another source or clear it.');
    this.render();
  }
  render() {
    const box=this.editor.state.boxes.find(box=>box.id===this.boxId);
    this.renderRecovery();
    this.root.hidden=!box && !(this.editor.state.still_requests?.length);if (!box) return;
    const stillName=this.target.kind!=='shot'&&this.editor.runsFlf?.(this.editor.state.boxes.indexOf(box))?`${targetLabel(this.target)} frame`:targetLabel(this.target);
    setText(this.titleEl,`Clip ${this.editor.state.boxes.indexOf(box)+1} · ${stillName} image${this.generatorLabel?` · ${this.generatorLabel}`:''}`);
    this.uploadButton.disabled=typeof this.host.importGuide!=='function';
    const additionalReferences=this.additionalReferences??[];
    this.additionalReferencesEl.hidden=!additionalReferences.length;
    setText(this.additionalReferencesEl,additionalReferences.length?`Connected picture aliases: ${additionalReferences.join(', ')}. Mention an alias in the frame image prompt to include that picture.`:'');
    const saved=box.previews?.find(item=>key(itemTarget(item))===key(this.target));
    if(!this.promptEditing) {
      const prompt=this.framePrompt();
      if(this.promptEl.value!==prompt) this.promptEl.value=prompt;
    }
    this.renderGenerateControls();
    this.preparation.render(this.boxId,this.target);
    this.seedSection.set(this.seedEl.value!=='',{state:this.seedEl.value?'':'Random for each candidate'});
    this.guideSourceEl.hidden=true;
    setText(this.guideSourceEl,this.previousGuide?`Continuity: ${guideLabel(this.editor.state,this.previousGuide)} accepted guide. The requested scene controls the new image.`:'');
    const index=this.editor.state.boxes.indexOf(box),next=this.editor.state.boxes[index+1];
    const paired=this.target.kind==='first'&&index>0&&!box.cut?`Clip ${index} Last`:
      this.target.kind==='last'&&next&&!next.cut?`Clip ${index+2} First`:null;
    this.boundaryHintEl.hidden=!paired;
    setText(this.boundaryHintEl,paired?`Continuous boundary: using a guide also sets ${paired} while both clips are unrendered.`:'');
    this.acceptedEl.replaceChildren();this.candidatesEl.replaceChildren();
    const guide=this.currentGuide(saved)?.guide;
    const reference=!guide?endpointReference(this.editor.state,index,this.target.kind,this.host.connected().images):null;
    const frameMode=this.target.kind!=='shot'&&!!this.editor.runsFlf?.(index);
    const preview=guide??reference?.mediaFile??saved?.images?.[0]?.file??saved?.image;
    if(preview||reference?.preview) {
      this.acceptedEl.append(this.image(preview,reference?`Frame @${reference.name}`:guide?(frameMode?'Accepted frame':'Accepted guide'):'Candidate',reference?.preview));
      const caption=el('div',null,'h3ct-row');caption.append(el('span',reference?`Frame in use · @${reference.name} · Change in Settings`:guide?(frameMode?'Frame in use':'Guide in use'):'Candidate preview',guide||reference?'h3ct-guide-status':'h3ct-hint'));
      const previewed=!guide&&!reference?saved?.images?.[0]:null;
      if(previewed){const use=button('Use as guide',()=>this.accept(previewed.file,{candidate:previewed}));use.classList.add('h3ct-primary');caption.append(use);}
      if(guide) caption.append(button(frameMode?'Remove frame':'Remove guide',()=>this.removeGuide()),button('Use as scene anchor',()=>this.useSceneAnchor(guide)));
      this.acceptedEl.append(caption);
    } else {
      const empty=el('div',null,'h3ct-image-empty');
      const art=el('span',null,'h3ct-image-empty-icon');art.append(icon('image'));
      empty.append(art,el('span','No image yet'),el('small','Generate candidates, upload a guide or drop an image here.'));
      this.acceptedEl.append(empty);
    }
    const anchors=this.editor.state.continuity?.anchors??[];
    if(anchors.length&&this.host.pinGuide){
      const select=el('select',null,'h3ct-note');select.setAttribute('aria-label','Accepted scene anchor');
      const empty=el('option','Choose an accepted scene anchor');empty.value='';select.append(empty);
      anchors.forEach((anchor,at)=>{const option=el('option',guideLabel(this.editor.state,anchor)+(anchor.place?` · ${anchor.place}`:''));option.value=String(at);select.append(option);});
      const choose=button('Use selected scene anchor',()=>{if(select.value==='')throw Error('Choose an accepted scene anchor.');return this.useAcceptedAnchor(structuredClone(anchors[Number(select.value)]));});
      const row=el('div',null,'h3ct-row');row.append(select,choose);this.acceptedEl.append(row);
    }
    const count=saved?.images?.length??0,countKey=`${this.boxId}:${key(this.target)}`,before=this.candidateCounts.get(countKey);
    this.candidateCounts.set(countKey,count);
    this.root.classList.toggle('h3ct-has-candidates',count>0);
    setText(this.candidateTitle,`Candidates · ${count} · choose one to use as the guide`);
    this.candidatePicker.hidden=!count;
    this.candidateTitle.hidden=!count;
    this.candidateHint.hidden=!count;
    if(before!==undefined&&count>before) {
      // A generation just finished: say so and bring the new candidates into view.
      this.note(`${count-before} new candidate${count-before===1?'':'s'} ready. Choose Use as guide on the one you want.`);
      queueMicrotask(()=>this.candidatePicker.scrollIntoView?.({block:'nearest',behavior:'smooth'}));
    }
    for (const [index,candidate] of (saved?.images ?? []).entries()) {
      const card=el('article',null,'h3ct-candidate');
      const use=button('Use as guide',()=>this.accept(candidate.file,{candidate}));use.classList.add('h3ct-primary');
      card.append(this.image(candidate.file,'Candidate'),el('strong',`Candidate ${index+1}`),use);
      const changed=[];
      const anchor=sceneAnchor(this.editor.state,this.editor.state.boxes.findIndex(b=>b.id===this.boxId));
      const used=(candidate.references??[]).find(ref=>ref.roles?.includes('scene anchor'));
      if(used&&(used.sha256!==anchor?.sha256||used.revision!==anchor?.revision))changed.push('scene anchor');
      if ((candidate.prompt??'')!==this.candidatePrompt()) changed.push('prompt');
      if (String(candidate.seed??'')!==this.seedEl.value) changed.push('seed');
      const details=el('details',null,'h3ct-image-details h3ct-hint'),source=candidate.source;
      details.append(el('summary','Render details'),el('p',`Seed: ${candidate.seed??'Native default'} · Batch index ${candidate.batch_index??'unknown'}`),
        el('p',source?`Source: ${source.sequence} / ${source.box} · ${source.created} · frame ${source.moment}`:
          candidate.guide_source?`Source: Accepted guide · ${guideLabel(this.editor.state,candidate.guide_source)}`:'Source: Prompt and references only'));
      if(candidate.references?.length)details.append(el('p','References: '+candidate.references.map(ref=>`${ref.label??ref.slot??'Image'} — ${(ref.roles??[]).join(', ')}`).join('; ')));
      const prompt=el('p',`Original prompt: ${candidate.prompt??''}`);prompt.style.whiteSpace='pre-wrap';details.append(prompt);
      if (candidate.effective_prompt && candidate.effective_prompt!==candidate.prompt) {
        const conditioning=el('details'),text=el('p',candidate.effective_prompt);text.style.whiteSpace='pre-wrap';
        conditioning.append(el('summary','Executed image prompt'),text);details.append(conditioning);
      }
      details.append(button('Remove candidate',()=>this.removeCandidate(index)));
      if (changed.length) card.append(el('span',`Differs from current ${changed.join(', ')}.`,'h3ct-hint'));
      card.append(details);this.candidatesEl.append(card);
    }
  }
  framePrompt() {
    if(this.promptEditing) return this.promptEl.value;
    const {box}=this.location();
    const saved=box.previews?.find(item=>key(itemTarget(item))===key(this.target));
    return saved?.still_prompt??preparedStillPrompt(this.editor.state,this.boxId,this.target)?.prompt??'';
  }
  candidatePrompt() {
    const prompt=this.framePrompt();
    return prompt.trim()?prompt:this.location().box.prompt;
  }
  renderGenerateControls() {
    const source=this.candidatePrompt(),empty=!source.trim();
    this.promptExcerpt.hidden=!!this.framePrompt().trim();
    if(!this.promptExcerpt.hidden) {
      const summary=promptSections(source)?.find(section=>section.key==='summary');
      const excerpt=summary?summary.fields.map(part=>part.value.trim()).filter(Boolean).join(' '):source.trim();
      setText(this.promptExcerpt,excerpt?`Using video prompt: ${excerpt}`:'Enter a frame image prompt or a clip video prompt.');
    }
    this.generateButton.disabled=!!this.generating||empty||typeof this.host.generateStill!=='function'||this.recipeAvailable===false;
    setIconLabel(this.generateButton,this.generating?'Generating candidates…':'Generate candidates');
    this.generateButton.title=this.generating?'Preparing or submitting still candidates.':empty?'Enter a frame image prompt or a clip video prompt.':
      this.generateButton.disabled?'Configure a local still recipe to generate images.':'Generate image candidates for this frame';
  }
  renderRecovery() {
    const owner=this.editor.state.boxes.length?this.root:this.editor.root;
    if(this.recoveryEl.parentElement!==owner) owner.append(this.recoveryEl);
    this.recoveryEl.replaceChildren();
    for(const receipt of this.editor.state.still_requests??[]) {
      const index=this.editor.state.boxes.findIndex(box=>box.id===receipt.box);
      const assigned=index>=0 && frameTargets(this.editor.state,index,this.host.context()).some(item=>key(item.target)===key(receipt.target));
      if(receipt.state!=='complete') this.recoveryEl.append(el('p',`Still ${receipt.box} / ${targetLabel(receipt.target)}: ${receipt.state}${receipt.error?' - '+receipt.error:''}`));
      if(!assigned) for(const candidate of receipt.images??[]) {
        const link=el('a','Open unassigned candidate');link.href=this.host.viewUrl(candidate.file);link.target='_blank';link.rel='noopener';
        const row=el('div',null,'h3ct-row');row.append(this.image(candidate.file,'Unassigned candidate'),el('span',`Unassigned candidate: ${receipt.box} / ${targetLabel(receipt.target)}`),link,
          button('Copy candidate prompt',()=>navigator.clipboard.writeText(candidate.prompt??'')));
        this.recoveryEl.append(row);
      }
    }
  }
  image(file,label,url) {
    const img=el('img');img.src=url??this.host.viewUrl(file);img.alt=label;img.draggable=false;
    const thumbnail=button('',()=>this.previewImage(file,label,thumbnail,url));thumbnail.classList.add('h3ct-image-thumbnail');
    thumbnail.setAttribute('aria-label',`Preview ${label}`);thumbnail.setAttribute('aria-haspopup','dialog');thumbnail.title=`Preview ${label}`;
    thumbnail.append(img);return thumbnail;
  }
  previewImage(file,label,opener,url) {
    this.destroy();
    const dialog=this.previewDialog=el('dialog',null,'h3ct-image-preview');dialog.setAttribute('aria-label',`${label} preview`);
    dialog.style.cssText='width:min(1200px,calc(100vw - 24px));max-width:calc(100vw - 24px);max-height:calc(100dvh - 24px);padding:12px;box-sizing:border-box;overflow:auto;background:#15171c;color:var(--input-text,#ddd);border:1px solid #535b6c;border-radius:8px;font:14px/1.45 system-ui,sans-serif';
    const finish=()=>{
      dialog.remove();
      if(this.previewDialog===dialog) {this.previewDialog=null;(opener.isConnected?opener:this.uploadButton.disabled?this.titleEl:this.uploadButton).focus({preventScroll:true});}
    };
    const dismiss=()=>{dialog.close();finish();};
    const head=el('div');head.style.cssText='display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:8px';
    const close=button('Close',dismiss);head.append(el('strong',label),close);
    const img=el('img');img.src=url??this.host.viewUrl(file);img.alt=label;
    img.style.cssText='display:block;width:auto;height:auto;max-width:100%;max-height:calc(100dvh - 96px);margin:auto;object-fit:contain';
    dialog.append(head,img);
    dialog.addEventListener('keydown',event=>{event.stopPropagation();if(event.key==='Escape') {event.preventDefault();dismiss();}});
    dialog.addEventListener('cancel',event=>{event.preventDefault();event.stopPropagation();dismiss();});
    dialog.addEventListener('close',finish);
    document.body.append(dialog);dialog.showModal();close.focus();
  }
  destroy() {
    const dialog=this.previewDialog;this.previewDialog=null;dialog?.close();dialog?.remove();
  }
  chooseUpload() {
    const input=el('input');input.type='file';input.accept='image/*';
    const boxId=this.boxId,target=structuredClone(this.target);
    input.addEventListener('change',()=>{if(input.files[0]) this.upload(input.files[0],boxId,target).catch(error=>this.note(error.message));});input.click();
  }
  async upload(file,boxId=this.boxId,target=structuredClone(this.target)) {
    const imported=await this.host.importGuide(file);
    return this.accept(imported,{boxId,target});
  }
  async accept(file,{boxId=this.boxId,target=structuredClone(this.target),reuseEnding=false,candidate}={}) {
    let boundary,pinned;
    const checkAnchor=()=>{const anchor=sceneAnchor(this.editor.state,this.editor.state.boxes.findIndex(b=>b.id===boxId)),used=(candidate?.references??[]).find(ref=>ref.roles?.includes('scene anchor'));
      if(used&&(used.sha256!==anchor?.sha256||used.revision!==anchor?.revision))throw Error('The scene anchor changed. Regenerate this candidate before using it as a guide.');};
    for (let attempt=0;attempt<3;attempt++) {
      this.live();checkAnchor();const {index}=this.location(boxId,target);
      const before=serialize(this.editor.state);
      const next=this.editor.state.boxes[index+1];
      [boundary,pinned]=await Promise.all([this.host.readBoundary?.(target.kind==='last'&&next&&!next.cut?next.id:boxId),this.host.pinGuide?.(file)]);
      this.live();checkAnchor();this.location(boxId,target);
      if (before===serialize(this.editor.state)) break;
      if (attempt===2) throw new Error('The Timeline keeps changing. Accept this guide again after the edit settles.');
    }
    checkAnchor();
    // Validate and build on a copy; no mutation or undo entry on rejection.
    const state=structuredClone(this.editor.state);
    const result=applyFrameGuide(state,boxId,target,file,{context:this.host.context(),boundary:reuseEnding?{...boundary,reuseEnding}:boundary});
    if(pinned&&!reuseEnding)acceptSceneAnchor(state,boxId,target,pinned);
    this.host.undoStep?.();this.editor.state=state;this.editor.commit();this.host.undoStep?.();
    this.render();this.note(reuseEnding?'Using the verified predecessor ending.':'Guide accepted.');return result;
  }
  async useSceneAnchor(file) {
    this.live();const boxId=this.boxId,target=structuredClone(this.target),before=serialize(this.editor.state);
    if(!this.host.pinGuide)throw Error('Scene anchor pinning is unavailable.');
    const image=await this.host.pinGuide(file);this.live();
    if(before!==serialize(this.editor.state))throw Error('The accepted scene changed. Select its anchor again.');
    const state=structuredClone(this.editor.state);selectSceneAnchor(state,boxId,{...image,box:boxId,target});
    this.host.undoStep?.();this.editor.state=state;this.editor.commit();this.host.undoStep?.();this.render();this.note('Scene anchor selected.');
  }

  async useAcceptedAnchor(anchor) {
    this.live();const boxId=this.boxId,before=serialize(this.editor.state);
    const image=await this.host.pinGuide(anchor.file);this.live();
    if(before!==serialize(this.editor.state)||image.sha256!==anchor.sha256)throw Error('The accepted scene anchor changed. Select it again.');
    const state=structuredClone(this.editor.state);selectSceneAnchor(state,boxId,{...anchor,...image});
    this.host.undoStep?.();this.editor.state=state;this.editor.commit();this.host.undoStep?.();this.render();this.note('Scene anchor selected for this scene.');
  }

  async showEnding() {
    this.endingEl.replaceChildren();
    if (this.target.kind!=='first'||!this.host.readBoundary
      || this.editor.state.boxes.findIndex(box=>box.id===this.boxId)<1) return;
    const boxId=this.boxId;
    // Reading the boundary asks the server for the Timeline's status and two clips' takes, so it waits like the sources do.
    await this.host.stillsSettled?.();
    if (this.boxId!==boxId||this.target.kind!=='first') return;
    const boundary=await this.host.readBoundary(boxId);
    if (this.boxId!==boxId||this.target.kind!=='first'||!boundary?.ending) return;
    const file=boundary.ending.file;
    this.endingEl.append(this.image(file,'Verified predecessor ending'),button('Use saved predecessor ending',()=>this.accept(file,{boxId,target:{kind:'first'},reuseEnding:true})));
  }
  async generate() {
    if(this.generating) return;
    const boxId=this.boxId,target=structuredClone(this.target);
    this.generating=true;this.render();this.note('Preparing still candidate generation…');
    try {
      if(this.sourcesFailed) this.sourcesReady=this.loadSources();
      this.refreshControls();
      let sourcesReady;
      do {
        sourcesReady=this.sourcesReady;
        try {await Promise.all([sourcesReady,this.controlsReady]);}
        catch(error) {if(sourcesReady===this.sourcesReady) throw error;}
      } while(sourcesReady!==this.sourcesReady);
      if(boxId!==this.boxId || key(target)!==key(this.target)) throw new Error('The selected still target changed. Generate from the current target.');
      const missing=await this.host.referenceReadiness?.(boxId)??[];
      if(missing.length){await this.host.openReferencePreparation(missing);this.note('Prepare and approve the missing references, or disable their preparation requirement.');return;}
      if(boxId!==this.boxId || key(target)!==key(this.target)) throw new Error('The selected still target changed. Generate from the current target.');
      this.live();
      const {frame}=this.location(boxId,target);
      const seed=this.seedEl.value===''?undefined:seedValue(this.seedEl.value);
      if(this.seedEl.value!=='' && seed===undefined) throw new Error('Image seed must be an unsigned 64-bit integer.');
      const prompt=this.candidatePrompt();if(!prompt.trim())throw new Error('Enter a frame image prompt or a clip video prompt before generating candidates.');
      const request={box:boxId,target,frame,prompt,seed:seed??newSeed(),source:null};
      this.note('Submitting still candidates…');
      const receipt=await this.host.generateStill(request);
      this.live();this.note(`Still request ${receipt.state}. Results remain candidates until accepted.`);
      return receipt;
    } catch(error) {this.note(error.message);throw error;}
    finally {this.generating=false;this.render();}
  }
  removeCandidate(index) {
    this.live();const {box}=this.location();const saved=box.previews?.find(item=>key(itemTarget(item))===key(this.target));
    if (!saved?.images?.[index]) return;
    this.host.undoStep?.();saved.images.splice(index,1);this.editor.commit();this.host.undoStep?.();this.render();
  }
  // The guide shown for the current target: its own, or for First/Last a free Frame guide on that same frame.
  currentGuide(saved) {
    if(saved?.guide) return {preview:saved,guide:saved.guide};
    if(this.target.kind==='shot') return null;
    const index=this.editor.state.boxes.findIndex(box=>box.id===this.boxId);
    return index<0?null:endpointGuide(this.editor.state,index,this.host.context(),this.target.kind);
  }
  removeGuide() {
    this.live();const {box}=this.location();
    const current=this.currentGuide(box.previews?.find(item=>key(itemTarget(item))===key(this.target)));
    const saved=current?.preview;
    if (!saved?.guide) return;
    this.host.undoStep?.();delete saved.guide;
    if(!saved.target&&!saved.images?.length&&!saved.image) box.previews=box.previews.filter(item=>item!==saved);
    if(this.editor.state.continuity)this.editor.state.continuity.anchors=this.editor.state.continuity.anchors.filter(anchor=>!(anchor.box===box.id&&key(anchor.target)===key(this.target)));
    this.editor.commit();this.host.undoStep?.();this.render();
  }
}
