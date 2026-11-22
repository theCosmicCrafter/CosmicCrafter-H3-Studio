import {referencePools, referenceType, referenceMediaType, setReferenceReplacement, restoreReferenceReplacement, switchReference, applyImageDescription, effectiveRefmods} from './h3c_timeline_model.mjs?v=1dfc1612e462';
import {referenceChip} from './h3c_reference_pictures.mjs?v=8198307be3fa';
import {audioSourceLocked} from './h3c_audio_windows.mjs?v=cdefbd77b246';

const ACCEPT = {image:'image/*',video:'video/*,.mkv,.mov,.webm,.mp4',audio:'audio/*,.wav,.flac,.mp3,.ogg,.m4a',video_audio:'audio/*,video/*,.wav,.flac,.mp3,.mp4'};
const element = (tag,text) => { const node=document.createElement(tag); if(text)node.textContent=text; return node; };
const button = (text,action) => {const node=element('button',text);node.type='button';node.className='h3ct-button';node.addEventListener('click',action);return node;};

export class ReferenceReplacements {
  constructor(editor) {
    this.editor=editor;
    this.busy=false;
    this.operation=0;
    this.readRevision=0;
    this.dialog=element('dialog');this.dialog.className='h3cr-replacement';
    this.dialog.setAttribute('aria-label','Reference replacement');
    this.dialog.addEventListener('cancel',event=>{event.preventDefault();this.close();});
    this.input=element('input');this.input.type='file';this.input.hidden=true;
    this.input.addEventListener('change',()=>{
      const file=this.input.files?.[0];this.input.value='';
      if(file)this.upload(file);
    });
    if(!document.getElementById('h3cr-replacement-style')) {
      const style=element('style',`
        .h3cr-replacement{width:min(560px,calc(100vw - 48px));max-height:calc(100vh - 48px);overflow:auto;padding:20px;color:#e7edfa;background:#1a1c22;border:1px solid #526078;border-radius:12px;font:14px system-ui;}
        .h3cr-replacement::backdrop{background:#0009;}
        .h3cr-replacement-head{display:flex;align-items:center;justify-content:space-between;gap:12px;}
        .h3cr-replacement-head h2{margin:0;font-size:18px;}
        .h3cr-replacement-actions{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0;}
        .h3cr-replacement-choices{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:8px;}
        .h3cr-replacement-choices button{padding:10px;min-width:0;text-align:left;}
        .h3cr-replacement-choices img{width:100%;height:100px;object-fit:contain;}
        .h3cr-replacement-media img,.h3cr-replacement-media video{width:100%;max-height:260px;object-fit:contain;}
        .h3cr-replacement-media audio{width:100%;}
        .h3cr-replacement p{line-height:1.5;overflow-wrap:anywhere;}
        .h3cr-replacement .problem{color:#ffabab;}
      `);style.id='h3cr-replacement-style';document.head.append(style);
    }
  }

  sources() {return this.editor.host.referenceSources?.() ?? this.editor.host.connected();}

  sourceSignature(slot) {
    const ref=this.editor.referenceOptions().find(value=>value.name===slot);
    const mod=ref?.refmod?effectiveRefmods(this.editor.state,{includeDisabled:true}).find(value=>value.slot===slot):null;
    return JSON.stringify({file:ref?.mediaFile??null,refmod:mod??null,problem:ref?.problem??null});
  }

  open(slot,{preview=false}={}) {
    if(this.busy)return;
    this.close();
    this.slot=slot;this.state=this.editor.state;this.returnFocus=document.activeElement;
    this.original=JSON.stringify(this.state.reference_replacements?.[slot] ?? null);
    this.input.accept=ACCEPT[referenceType(slot)];
    const heading=element('div');heading.className='h3cr-replacement-head';
    heading.append(element('h2',`${preview?'Reference':'Replace'} @${slot}`),button('Close',()=>this.close()));
    const media=element('div');media.className='h3cr-replacement-media';
    const ref=this.editor.referenceOptions().find(value=>value.name===slot);
    this.originalSource=this.sourceSignature(slot);
    if(ref?.preview) {const image=element('img');image.src=ref.preview;image.alt=ref.title??`@${slot}`;media.append(image);}
    else if(ref?.mediaFile) {
      const player=element(referenceType(slot)==='video'?'video':'audio');
      player.controls=true;player.preload='metadata';player.src=this.editor.host.viewUrl(ref.mediaFile);media.append(player);
    }
    media.append(element('p',ref?.title??slot));
    this.message=element('p',preview?'':`Choosing a reference switches every use to its name, enables it and disables @${slot}. Uploading replaces the media under @${slot}.`);
    this.message.setAttribute('role','status');
    const actions=element('div');actions.className='h3cr-replacement-actions';
    this.uploadButton=button('Upload replacement…',()=>this.input.click());
    this.uploadButton.disabled=referenceMediaType(this.state,slot)==='refmod_video';
    if(this.uploadButton.disabled)this.uploadButton.title='Choose a matching video RefMod from the reference sources.';
    actions.append(this.uploadButton);
    if(this.state.reference_replacements?.[slot])actions.append(button('Restore original source',()=>this.restore(slot)));
    const choices=element('div');choices.className='h3cr-replacement-choices';
    if(preview)actions.replaceChildren(button('Replace…',()=>this.open(slot)));
    else for(const source of Object.values(referencePools(this.state,this.sources(),this.editor.host.viewUrl)).flat()) {
      if(source.name===slot||source.problem||referenceType(source.name)!==referenceType(slot))continue;
      const replacement={source:source.name};
      try {switchReference(structuredClone(this.state),slot,source.name,this.sources());}
      catch {continue;}
      const choose=button('',()=>this.apply(replacement));choose.dataset.source=source.name;
      choose.setAttribute('aria-label',`Use ${source.name} for ${slot}`);choose.append(referenceChip(source));choices.append(choose);
    }
    const description=this.descriptionControls(ref);
    this.dialog.replaceChildren(heading,media,this.message,...description?[description]:[],actions,choices,this.input);
    if(!this.dialog.isConnected)document.body.append(this.dialog);
    this.dialog.showModal();
    if(description)this.readDescription(ref);
  }

  descriptionControls(ref) {
    if(referenceType(this.slot)!=='image'||!this.editor.host.describeImage)return null;
    const section=element('section');
    const label=element('label','Description');
    this.descriptionInput=element('textarea');this.descriptionInput.rows=3;this.descriptionInput.maxLength=12000;
    this.descriptionInput.style.cssText='box-sizing:border-box;width:100%;margin-top:8px';
    this.descriptionInput.setAttribute('aria-label','Image description');
    this.descriptionInput.value=this.state.reference_descriptions?.[this.slot]?.text??'';
    label.append(this.descriptionInput);section.append(label);
    const actions=element('div');actions.className='h3cr-replacement-actions';
    for(const [action,title] of [['edit','Save description'],['clear','Clear'],['regenerate','Regenerate'],['clear_all','Clear all cached descriptions']]) {
      const control=button(title,()=>action==='clear_all'?this.clearAll():this.describe(action,ref));
      control.dataset.description=action;actions.append(control);
    }
    section.append(actions);return section;
  }

  async readDescription(ref) {
    const operation=this.operation,revision=this.readRevision,input=this.descriptionInput,original=input.value;
    try {
      const result=await this.editor.host.describeImage('read',ref);
      if(operation===this.operation&&revision===this.readRevision&&this.valid()&&input.value===original&&!this.busy)input.value=result.description?.text??'';
    } catch(error) {if(operation===this.operation&&revision===this.readRevision&&this.valid())this.message.textContent=error.message;}
  }

  async describe(action,ref) {
    if(this.busy||!this.valid())return;
    this.readRevision++;
    const operation=this.operation,state=this.state,slot=this.slot,original=JSON.stringify(state);
    this.busy=true;this.message.classList.remove('problem');this.message.textContent=action==='regenerate'?'Describing image…':'Saving description…';
    try {
      const result=await this.editor.host.describeImage(action,ref,this.descriptionInput.value);
      if(operation!==this.operation||!this.valid()||JSON.stringify(state)!==original)return;
      applyImageDescription(state,slot,result.description);
      this.editor.commit();this.editor.renderRefmods();this.editor.host.undoStep?.();
      this.descriptionInput.value=result.description?.text??'';
      this.message.textContent=result.notes?.join(' ')||'Description saved.';
    } catch(error) {if(operation===this.operation){this.message.textContent=error.message;this.message.classList.add('problem');}}
    finally {this.busy=false;}
  }

  async clearAll() {
    if(this.busy||!this.editor.host.describeImage)return;
    this.readRevision++;
    const state=this.editor.state,original=JSON.stringify(state);
    const sources=JSON.stringify(this.editor.referenceOptions().filter(ref=>referenceType(ref.name)==='image').map(ref=>[ref.name,this.sourceSignature(ref.name)]));
    this.busy=true;
    try {
      const result=await this.editor.host.describeImage('clear_all');
      if(this.editor.state!==state||JSON.stringify(state)!==original||sources!==JSON.stringify(this.editor.referenceOptions().filter(ref=>referenceType(ref.name)==='image').map(ref=>[ref.name,this.sourceSignature(ref.name)])))return;
      for(const ref of this.editor.referenceOptions().filter(ref=>referenceType(ref.name)==='image')) {
        const saved=state.reference_descriptions?.[ref.name];
        applyImageDescription(state,ref.name,result.descriptions?.[ref.name]??{source:saved?.source??'',text:'',format:'manual'});
      }
      this.editor.commit();this.editor.renderRefmods();this.editor.host.undoStep?.();
      if(this.dialog.open&&this.descriptionInput)this.descriptionInput.value='';
      this.editor.refmodMessage.textContent='Cached image descriptions cleared.';
    } catch(error) {this.editor.refmodMessage.textContent=error.message;}
    finally {this.busy=false;}
  }

  async resolveDescription(slot) {
    if(referenceType(slot)!=='image'||!this.editor.host.describeImage)return;
    const state=this.editor.state,original=JSON.stringify(state);
    const source=this.sourceSignature(slot);
    const ref=this.editor.referenceOptions().find(ref=>ref.name===slot);
    try {
      const result=await this.editor.host.describeImage('resolve',ref);
      if(this.editor.state!==state||JSON.stringify(state)!==original||this.sourceSignature(slot)!==source)return;
      applyImageDescription(state,slot,result.description);
      this.editor.commit();this.editor.renderRefmods();this.editor.host.undoStep?.();
      this.editor.refmodMessage.textContent=result.notes?.join(' ')||'';
    } catch(error) {if(this.editor.state===state)this.editor.refmodMessage.textContent=error.message;}
  }

  preview(ref) {this.open(ref.name,{preview:true});}

  valid() {
    return this.dialog.open&&this.editor.state===this.state
      &&JSON.stringify(this.state.reference_replacements?.[this.slot]??null)===this.original
      &&this.sourceSignature(this.slot)===this.originalSource;
  }

  apply(replacement) {
    if(!this.valid())return;
    try {
      if(replacement.source)switchReference(this.state,this.slot,replacement.source,this.sources());
      else {
        setReferenceReplacement(this.state,this.slot,replacement,this.sources());
        this.state.disabled_refs=(this.state.disabled_refs??[]).filter(name=>name!==this.slot);
      }
      this.editor.commit();this.editor.renderRefmods();this.editor.host.undoStep?.();this.close();
      this.resolveDescription(replacement.source??this.slot);
    }catch(error){this.message.textContent=error.message;this.message.classList.add('problem');}
  }

  async upload(file) {
    if(this.busy||!this.valid()||audioSourceLocked(this.state,this.slot))return;
    const operation=this.operation,slot=this.slot;
    this.busy=true;this.uploadButton.disabled=true;this.message.classList.remove('problem');this.message.textContent='Uploading replacement…';
    try {
      const uploaded=await this.editor.host.uploadReference(file,referenceType(slot));
      if(operation===this.operation&&this.valid())this.apply({file:uploaded.file});
    }catch(error){if(operation===this.operation){this.message.textContent=error.message;this.message.classList.add('problem');}}
    finally{this.busy=false;this.uploadButton.disabled=false;}
  }

  restore(slot) {
    if(this.busy)return;
    try {
      restoreReferenceReplacement(this.editor.state,slot);
      this.editor.commit();this.editor.renderRefmods();this.editor.host.undoStep?.();this.close();
      this.resolveDescription(slot);
    } catch(error){
      if(!this.dialog.open||this.slot!==slot||!this.message)this.open(slot);
      this.message.textContent=error.message;this.message.classList.add('problem');
    }
  }

  close() {
    this.operation++;
    for(const media of this.dialog.querySelectorAll('video,audio'))media.pause();
    if(this.dialog.open)this.dialog.close();
    if(this.returnFocus?.isConnected)this.returnFocus.focus();
  }

  destroy(){this.close();this.dialog.remove();}
}
