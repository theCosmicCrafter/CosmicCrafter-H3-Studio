import {decorateIcon,setIconLabel} from './h3c_icons.mjs';
// One explicit batch owns the editable prompts; previews and render jobs do not invalidate its source.
import {replaceChanged,setText} from './h3c_dom.mjs?v=584a9bf55653';
const canonical = target => target?.kind==='shot'&&target.shot===1?{kind:'first'}:target;
const sameTarget = (a,b) => {a=canonical(a);b=canonical(b);return a?.kind===b?.kind&&a?.shot===b?.shot;};
const copy = value => structuredClone(value);
function equal(a,b) {
  if(a===b)return true;
  if(!a||!b||typeof a!=='object'||typeof b!=='object'||Array.isArray(a)!==Array.isArray(b))return false;
  const keys=Object.keys(a);return keys.length===Object.keys(b).length&&keys.every(key=>Object.hasOwn(b,key)&&equal(a[key],b[key]));
}
export const sameStillPromptSource=equal;

export function stillPromptSource(state,instructions='',context=39,references=[]) {
  return {version:1,instructions,context,prompt:state.prompt??'',bible:copy(state.bible??null),
    reference_descriptions:copy(state.reference_descriptions??{}),reference_replacements:copy(state.reference_replacements??{}),
    disabled_refs:copy(state.disabled_refs??[]),pictures:copy(state.pictures??[]),
    refmods:copy(state.refmods??[]),approved_references:(state.reference_preparation?.assets??[]).filter(asset=>asset.approved)
      .map(asset=>({key:asset.key??'',slot:asset.slot??'',included:asset.included!==false,
        candidate_id:asset.approved.candidate_id??'',revision:asset.approved.revision??0})).sort((a,b)=>a.key>b.key?1:a.key<b.key?-1:0),
    boxes:(state.boxes??[]).map(box=>({id:box.id,prompt:box.prompt??'',frames:box.frames??null,exact:!!box.exact,cut:!!box.cut,
      new_scene:!!box.new_scene,first:box.first??'',last:box.last??'',source:copy(box.source??null),
      schedule:copy(box.schedule??null),cast:copy(box.cast??null),join:copy(box.join??null)})),
    references:references.map(ref=>({name:ref.name,file:copy(ref.mediaFile??(ref.file&&typeof ref.file==='object'?ref.file:null)),description:ref.description??''}))};
}
export function preparedStillPrompt(state={},boxId,target) {
  return state.still_prompt_preparation?.prompts?.find(record=>record.members.some(member=>member.box===boxId&&sameTarget(member.target,target)));
}
export function setPreparedStillPrompt(state,boxId,target,prompt) {
  const record=preparedStillPrompt(state,boxId,target);if(!record)return false;
  record.prompt=prompt;
  for(const member of record.members)for(const item of state.boxes.find(box=>box.id===member.box)?.previews??[]) {
    const target=item.target??{kind:'shot',shot:item.shot};
    if(sameTarget(target,member.target)&&Object.hasOwn(item,'still_prompt')) {
      item.previous_still_prompt=item.still_prompt;delete item.still_prompt;
    }
  }
  return true;
}
export function usePreparedStillPrompts(state) {
  let count=0;
  for(const record of state.still_prompt_preparation?.prompts??[])for(const member of record.members)
    for(const item of state.boxes.find(box=>box.id===member.box)?.previews??[]) {
      if(Object.hasOwn(item,'still_prompt')&&sameTarget(item.target??{kind:'shot',shot:item.shot},member.target)) {
        item.previous_still_prompt=item.still_prompt;delete item.still_prompt;count++;
      }
    }
  return count;
}
export function stillPromptsStale(state,source) {
  return !!state.still_prompt_preparation?.prompts?.length&&!equal(state.still_prompt_preparation.source,source);
}
const currentSource = (editor,instructions) => stillPromptSource(editor.state,instructions,editor.host.context(),editor.host.connected().images);
const manualPrompts = state => state.boxes.map(box=>({box:box.id,prompts:(box.previews??[]).filter(item=>Object.hasOwn(item,'still_prompt'))
  .map(item=>({target:canonical(item.target??{kind:'shot',shot:item.shot}),prompt:item.still_prompt}))}));

export async function prepareStillPromptBatch(editor,instructions,{onProgress,sync=()=>{},isCurrent=()=>true}={}) {
  sync();const host=editor.host,source=currentSource(editor,instructions),context=host.referenceContext?.();
  const preparation=copy(editor.state.still_prompt_preparation),manual=manualPrompts(editor.state);
  const result=await host.prepareStillPrompts(instructions,onProgress);sync();
  if(!isCurrent()||context!==host.referenceContext?.()||!equal(source,currentSource(editor,instructions))
    ||!equal(preparation,editor.state.still_prompt_preparation)||!equal(manual,manualPrompts(editor.state)))return false;
  if(result?.version!==1||!Array.isArray(result.prompts)||!equal(result.source,source))throw Error('The prepared prompts do not match the current Timeline. Prepare them again.');
  host.undoStep?.();editor.state.still_prompt_preparation=copy(result);editor.commit(false);host.undoStep?.();return true;
}

function el(tag,text,className) {const node=document.createElement(tag);if(text!=null)node.textContent=text;if(className)node.className=className;return node;}
export class StillPromptPreparation {
  constructor(editor,refresh=()=>{}) {
    this.editor=editor;this.host=editor.host;this.refresh=refresh;this.revision=0;
    this.root=el('div',null,'h3ct-still-prompt-preparation');
    this.root.setAttribute('aria-label','Still prompts for all Timeline clips');
    this.button=el('button','Prepare all still prompts','h3ct-button');this.button.type='button';
    this.button.addEventListener('click',()=>this.prepare().catch(error=>{this.status.textContent=error.message;}));
    this.cancelButton=el('button','Cancel preparation','h3ct-button');this.cancelButton.type='button';
    this.cancelButton.addEventListener('click',()=>this.cancel().catch(error=>{this.status.textContent=error.message;}));
    this.useAllButton=el('button','Use prepared prompts for all targets','h3ct-button');this.useAllButton.type='button';
    this.useAllButton.addEventListener('click',()=>this.usePrepared());
    this.status=el('p',null,'h3ct-hint');this.status.setAttribute('role','status');
    this.instructionsEl=el('textarea',null,'h3ct-text');this.instructionsEl.rows=5;this.instructionsEl.setAttribute('aria-label','Still prompt conversion instructions');
    this.instructionsEl.addEventListener('input',()=>this.invalidate());
    this.instructionsEl.addEventListener('change',()=>this.editInstructions(this.instructionsEl.value));
    const details=this.instructionsRoot=el('section',null,'h3ct-project-instructions');details.append(el('h3','Still prompt conversion instructions','h3cx-title'),
      el('p','Prepare all First, Last and Shot prompts in one batch. Review or edit each final prompt before generating images.','h3ct-hint'),this.instructionsEl);
    this.components=el('details',null,'h3ct-image-details');this.components.append(el('summary','Prepared visual details'));
    this.componentBody=el('div');this.components.append(this.componentBody);
    decorateIcon(this.button,'stills','Prepare all still prompts');
    this.root.append(this.button,this.cancelButton,this.useAllButton,this.status,details);
    this.context=this.host.referenceContext?.();
  }
  invalidate() {this.revision++;}
  editInstructions(value) {
    this.invalidate();this.editor.frameImages?.live();this.host.undoStep?.();
    const saved=this.editor.state.still_prompt_preparation??={version:1,instructions:'',source:currentSource(this.editor,value),prompts:[]};
    saved.instructions=value;this.editor.commit(false);this.host.undoStep?.();this.render();
  }
  usePrepared() {
    this.editor.frameImages?.live();const state=copy(this.editor.state),count=usePreparedStillPrompts(state);if(!count)return;
    this.invalidate();this.host.undoStep?.();this.editor.state=state;this.editor.commit(false);this.host.undoStep?.();this.refresh();this.render();
  }
  async cancel() {
    if(this.cancelling||!this.host.cancelStillPrompts)return;
    const token=this.cancelling={},context=this.context;this.invalidate();this.render();
    let cancelled=false;
    try {
      await this.host.cancelStillPrompts();
      cancelled=true;
    } finally {if(this.cancelling===token){this.cancelling=null;this.render();
      if(cancelled&&context===this.host.referenceContext?.())this.status.textContent='Cancellation requested. Existing still prompts were kept.';}}
  }
  async loadInstructions() {
    if(!this.host.stillPromptInstructions||this.instructionsLoaded||this.instructionsLoading)return;
    const token=this.instructionsLoading={},revision=this.revision,context=this.context;
    this.button.disabled=true;
    try {
      const value=await this.host.stillPromptInstructions();
      if(this.instructionsLoading!==token||context!==this.host.referenceContext?.())return;
      this.instructionsLoaded=true;
      if(revision===this.revision&&!this.editor.state.still_prompt_preparation)this.instructionsEl.value=value;
    } catch(error) {if(this.instructionsLoading===token){this.instructionsLoaded=true;this.status.textContent=error.message;}}
    finally {if(this.instructionsLoading===token){this.instructionsLoading=null;this.button.disabled=!!this.busy||!!this.cancelling||!this.editor.state.boxes.length;}}
  }
  render(boxId=this.boxId,target=this.target) {
    this.boxId=boxId;this.target=target;
    const context=this.host.referenceContext?.();
    if(context!==this.context) {
      this.context=context;this.busy=null;this.cancelling=null;this.instructionsLoading=null;this.instructionsLoaded=false;this.invalidate();
      this.instructionsEl.value=this.editor.state.still_prompt_preparation?.instructions??'';
    }
    this.root.hidden=!this.host.prepareStillPrompts;this.instructionsRoot.hidden=this.root.hidden;
    const saved=this.editor.state.still_prompt_preparation;
    const knownJob=this.host.stillPromptJob?.();
    this.cancelButton.hidden=!this.busy&&!knownJob;
    this.cancelButton.disabled=!!this.cancelling||!this.host.cancelStillPrompts;
    this.useAllButton.hidden=!manualPrompts(this.editor.state).some(row=>row.prompts.some(item=>preparedStillPrompt(this.editor.state,row.box,item.target)));
    this.useAllButton.disabled=!!this.busy;
    if(saved&&document.activeElement!==this.instructionsEl)this.instructionsEl.value=saved.instructions;
    this.button.disabled=!!this.busy||!!this.cancelling||!!this.instructionsLoading||!this.editor.state.boxes.length;
    setIconLabel(this.button,this.busy?'Preparing all still prompts…':knownJob?'Resume still prompt preparation':saved?.prompts?.length?'Regenerate all still prompts':'Prepare all still prompts');
    if(!this.busy) {
      const stale=stillPromptsStale(this.editor.state,currentSource(this.editor,this.instructionsEl.value));
      setText(this.status,stale?'Still prompts are out of date. Regenerate to use the current Timeline; existing prompts and images remain available.':
        saved?.prompts?.length?`${saved.prompts.length} prepared prompts across all clips. Continuous Last and next First share their prompt.`:
          `${this.editor.state.boxes.length} clips`);
    }
    const selected=preparedStillPrompt(this.editor.state,boxId,target);this.components.hidden=!selected;
    const body=[];
    if(selected) {
      if(selected.members.length>1)body.push(el('p','Editing this prompt also edits its shared continuous endpoint.','h3ct-hint'));
      for(const issue of selected.issues??[])body.push(el('p',issue,'h3ct-hint'));
      for(const [name,label] of [['subject','Subject and visible state'],['setting','Setting'],['style','Visual style'],['lighting','Lighting'],['color','Color palette'],['camera','Camera and composition']]) {
        if(selected.components?.[name])body.push(el('strong',label),el('p',selected.components[name]));
      }
    }
    replaceChanged(this.componentBody,body);
    this.loadInstructions();
  }
  async prepare() {
    if(this.busy||this.cancelling||this.instructionsLoading)return false;
    const token=this.busy={},revision=this.revision,context=this.context;
    this.render();this.status.textContent='Preparing all unique still prompts…';
    let applied;
    try {
      applied=await prepareStillPromptBatch(this.editor,this.instructionsEl.value,{sync:()=>this.editor.frameImages?.live(),
        isCurrent:()=>this.busy===token&&this.revision===revision&&context===this.host.referenceContext?.(),
        onProgress:message=>{if(this.busy===token)this.status.textContent=String(message??'Preparing still prompts…');}});
      if(this.busy===token)this.refresh();
      return applied;
    } finally {if(this.busy===token){this.busy=null;this.render();
      if(applied===false)this.status.textContent='The Timeline or prompts changed while preparation worked. Your edits were kept; prepare again.';}}
  }
}
