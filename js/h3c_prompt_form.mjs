import {readPromptFields,writePromptField,SECTION_TITLES,RETENTION_VISUAL,RETENTION_AUDIO,SUMMARY_TASKS,SHOT_FIELDS} from './h3c_prompt_fields.mjs?v=5cd5e5206375';
import {promptSections,promptShots,replacePromptRanges} from './h3c_prompt_sections.mjs?v=1f35473e5668';
import {SwitchSection} from './h3c_switch_section.mjs?v=c253500f4908';
import {MentionLayer} from './h3c_mentions.mjs?v=7d543c4a1ce8';
import {shotTiming,editPromptShot} from './h3c_prompt_shots.mjs?v=17aa67525854';
import {decorateIcon} from './h3c_icons.mjs?v=62c964e1ecbe';
const el=(tag,cls,text)=>{const node=document.createElement(tag);if(cls)node.className=cls;if(text!==undefined)node.textContent=text;return node;};
const button=(text,action)=>{const node=el('button','h3ct-button',text);node.type='button';node.addEventListener('click',action);return node;};
const SECTION_ICONS={subject_definitions:'cast',summary:'story',retention_analysis:'refs',integrated_multimodal_description:'shots',
  detailed_description:'shots',overall_soundscape:'sound',non_diegetic_music:'audio'};
let ids=0;
const style=()=>{
  if(document.getElementById('h3pf-style'))return;
  const node=el('style');node.id='h3pf-style';node.textContent=`
.h3pf{border:0;padding:0;margin:0;min-width:0}.h3pf [hidden]{display:none!important}.h3pf>legend{width:100%;padding:0;margin:0 0 8px}
.h3pf-tabs{display:flex;flex-wrap:wrap;gap:4px;margin-bottom:12px}.h3pf-tabs [aria-selected=true]{border-color:#809fcc;background:#293545}.h3pf-tabs .empty>.h3ci-caption{opacity:.6}
.h3pf-row{padding:10px 0;border-bottom:1px solid #343a46;min-width:0}.h3pf-fields{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(150px,100%),1fr));gap:8px}
.h3pf-field{display:flex;flex-direction:column;gap:4px;margin:6px 0;min-width:0}.h3pf-field>span{font-size:12px;color:var(--h3b-muted,#aab2bf)}
.h3pf :is(input,select,textarea){box-sizing:border-box;width:100%;min-width:0;max-width:100%}.h3pf textarea{resize:vertical}
.h3pf-actions{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}.h3pf-error{color:#ffc2bb;white-space:pre-wrap;overflow-wrap:anywhere}
.h3pf :is(input,textarea,select,button):focus-visible{outline:2px solid #8fbcff;outline-offset:2px}.h3pf input[type=checkbox]{width:auto}
`;document.head.append(node);
};

export class PromptFormPanel {
  constructor(editor) {
    style();this.editor=editor;this.root=el('fieldset','h3pf');this.drafts=new Map();this.newRows=[];this.marks=[];
    this.section=null;this.controls=new Map();this.serial=++ids;this.message='';this.sectionStash=new Map();
    this.advanced=false;this.newDetails=new Map();this.advancedPins=new Map();this.advancedKept=new Map();this.customRelationships=new Set();
  }
  // As the Studio's Story Advanced: on while the clip has advanced details or after the user turns it on; off removes
  // them from the prompt, kept until it comes back on. A read-only Timeline only shows or hides them.
  toggleAdvanced(on,cues) {
    const video=this.editor.video(),id=video.id;
    if(this.editor.readOnly?.length){this.advancedPins.set(id,on);this.render();return;}
    if(on) {
      this.advancedPins.set(id,true);
      const kept=this.advancedKept.get(id);this.advancedKept.delete(id);
      if(kept)this.restoreAdvanced(video,kept);
      this.render();return;
    }
    if(!this.canLeave())return;
    if(cues.length) {
      const names=[...new Set(cues.map(({entry})=>SHOT_FIELDS.find(f=>f.key===entry.value.key).prefix.replace(' N','')))].join(', ');
      if(!globalThis.confirm?.(`Remove ${names} from this clip's prompt? Turning Advanced on again brings them back.`)){this.render();return;}
      const source=video.prompt;
      const next=replacePromptRanges(source,cues.map(({entry})=>{
        const start=entry.range.start-(source[entry.range.start-1]==='\n'?1:0);
        return {start,end:entry.range.end,before:source.slice(start,entry.range.end),text:''};
      }));
      if(this.editor.applyPrompt(source,next,{structural:true})===false){this.message='This prompt is read-only or changed.';this.render();return;}
      this.advancedKept.set(id,{before:source,after:next,cues:cues.map(({section,entry})=>({section,shot:entry.shot,value:entry.value}))});
      this.source=next;
    }
    this.advancedPins.delete(id);
    for(const [key,item] of this.newDetails)if(key.startsWith(id+':')&&SHOT_FIELDS.find(f=>f.key===item.value.key)?.advanced)this.newDetails.delete(key);
    this.render();
  }
  restoreAdvanced(video,kept) {
    const source=video.prompt;let next=kept.before,lost=0;
    if(source!==kept.after) {
      next=source;
      for(const cue of kept.cues) {
        try{next=writePromptField(next,{expectedSource:next,section:cue.section,kind:'cue',shot:cue.shot,entry:null,value:cue.value},{tags:this.tags()});}
        catch{lost++;}
      }
    }
    if(next!==source&&this.editor.applyPrompt(source,next,{structural:true})!==false)this.source=next;
    this.message=lost?`${lost} advanced detail${lost===1?'':'s'} could not be restored because ${lost===1?'its shot is':'their shots are'} gone.`:'';
  }
  tags(){return this.editor.pickedInfo?.().tags??[];}
  hasDrafts(){return this.drafts.size>0;}
  canLeave(){if(!this.hasDrafts())return true;this.message='Finish or discard the unsaved field before leaving this clip.';this.render();return false;}
  discardDrafts(message=''){this.drafts.clear();this.newRows=[];this.newShot=false;this.message=message;this.render();}
  destroy(){for(const mark of this.marks)mark.destroy();this.marks=[];}
  focusSubject(label){this.section='subject_definitions';this.editor.setTab?.('prompt');this.render();this.controls.get(`${label} description`)?.focus?.();}
  field(parent,label,value,onChange,{options=null,multiple=false,area=false,suggestions=null}={}) {
    const wrap=el('label','h3pf-field'),name=el('span',null,label);
    const input=el(options?'select':area?'textarea':'input',options?'h3ct-select':'h3ct-text');
    input.setAttribute('aria-label',label);input.id=`h3pf-${this.serial}-${this.controls.size}`;input.dataset.key=label;
    if(options) {
      input.multiple=multiple;
      if(!multiple)options=[['','Choose…'],...options];
      for(const item of options){const [key,title]=Array.isArray(item)?item:[item,item];const option=el('option',null,title);option.value=String(key);option.selected=multiple?(value??[]).includes(key):key===value;input.append(option);}
    }
    if(!multiple)input.value=String(value??'');if(area)input.rows=3;
    input.addEventListener(options?'change':'input',()=>onChange(multiple?[...input.options].filter(o=>o.selected)
      .map(o=>options.map(item=>Array.isArray(item)?item[0]:item).find(key=>String(key)===o.value)):input.value));
    if(suggestions){const list=el('datalist');list.id=input.id+'-options';for(const s of suggestions){const o=el('option');o.value=s;list.append(o);}input.setAttribute('list',list.id);wrap.append(list);}
    wrap.append(name);
    if(area&&this.editor.mentionHooks){const mark=new MentionLayer(input,this.editor.mentionHooks());this.marks.push(mark);wrap.append(mark.root);}
    else wrap.append(input);
    input.addEventListener('focus',()=>{this.editor.activePromptEl=input;});
    wrap.append();parent.append(wrap);this.controls.set(label,input);return input;
  }
  edit(section,index,key,kind,patch) {
    const source=this.editor.video().prompt;
    if(source!==this.source||this.drafts.get(key)?.source&&this.drafts.get(key).source!==source){this.draftMessage('The prompt changed. Discard this draft before editing.');return;}
    const parsed=readPromptFields(source,{tags:this.tags()});
    const entry=index==null?null:parsed.sections.filter(s=>s.key===section).flatMap(s=>s.entries)[index];
    const base=this.drafts.get(key)?.value??entry?.value??this.newRows.find(r=>r.key===key)?.value??{};
    const value=patch===null?null:{...base,...(typeof patch==='function'?patch(base):patch)};
    try {
      if(kind==='dialogue'&&this.editor.video().dialogue!=='manual')throw new Error('Switch to Typed in the prompt before editing manual dialogue.');
      if(value===null&&kind==='definition'&&this.editor.box()?.cast?.[entry.value.target])throw new Error('Unlink this subject from Cast before deleting its definition.');
      const shot=entry?.shot??this.newRows.find(r=>r.key===key)?.shot??this.newDetails.get(key)?.shot;
      const next=writePromptField(source,{expectedSource:source,section,kind,shot,entry,value},{tags:this.tags()});
      if(index==null&&kind==='dialogue'&&value&&!value.text?.trim()) {
        const pending=this.newRows.find(r=>r.key===key);if(pending)pending.value=value;
        this.drafts.delete(key);this.draftMessage('');return;
      }
      const removedCue=(kind==='cue'||kind==='dialogue')&&!value?.text?.trim();
      if(removedCue&&entry&&value) {
        if(kind==='cue')this.newDetails.set(`${this.editor.video().id}:${entry.shot}:${value.key}:${value.index??0}`,{shot:entry.shot,value});
        else this.newRows.push({section,kind:'dialogue',shot:entry.shot,key:'dialogue:new:'+ ++ids,value});
      }
      if(this.editor.applyPrompt(source,next,{structural:index==null||value===null||removedCue})===false)throw new Error('This prompt is read-only or changed.');
      this.source=next;this.drafts.delete(key);this.message='';
      if(index==null||value===null||removedCue){this.newRows=this.newRows.filter(r=>r.key!==key);this.render();}
      else {const note=this.note; if(note)note.textContent='';}
    } catch(error){this.drafts.set(key,{value,source});this.draftMessage(error.message);}
  }
  draftMessage(message) {
    this.message=message;if(this.note)this.note.textContent=message;
    if(this.discardButton)this.discardButton.hidden=!this.hasDrafts();
  }
  applyShot(change,key='shot:new') {
    const editor=this.editor,source=editor.video().prompt;
    if(editor.readOnly?.length)return;
    try {
      if(source!==this.source||this.drafts.get(key)?.source&&this.drafts.get(key).source!==source)throw new Error('The prompt changed. Discard this draft and reopen the field.');
      const trial=editPromptShot(editor.state,editor.selected,change,editor.host.context(),editor.pickedLayer?.()?.id??null);
      const next=editor.pickedLayer?.()?trial.boxes[editor.selected].layers.find(v=>v.id===editor.video().id):trial.boxes[editor.selected];
      if(change.kind==='append'&&!promptSections(next.prompt))next.prompt='integrated_multimodal_description:\n'+next.prompt;
      const previews=editor.video().previews;
      this.drafts.delete(key);this.newShot=false;this.message='';
      editor.video().previews=next.previews;
      if(editor.applyPrompt(source,next.prompt,{structural:true})===false){editor.video().previews=previews;throw new Error('The prompt is read-only or changed.');}
      this.render();
    } catch(error){this.draftMessage(error.message);}
  }
  shotCards(parent,entries) {
    const editor=this.editor,timing=shotTiming(editor.state,editor.selected,editor.host.context(),editor.pickedLayer?.()?.id??null);
    if(timing.carry)parent.append(el('p','h3ct-hint',`Times are in this clip’s playback. H3’s prompt also includes ${(timing.carry/24).toFixed(3)} s of replay.`));
    if(editor.video().dialogue!=='manual') {
      parent.append(el('p','h3ct-hint','Dialogue comes from recording cues. Choose Typed in the prompt to add or edit manual dialogue.'));
      parent.append(button('Use typed dialogue',()=>{if(!this.canLeave()||editor.readOnly?.length)return;editor.host.undoStep?.();editor.video().dialogue='manual';editor.commit();editor.host.undoStep?.();this.render();}));
    }
    for(const entry of entries.filter(e=>e.shot===null))this.row(parent,this.section,entry,entries.indexOf(entry),this.section+':'+entries.indexOf(entry));
    for(const shot of timing.shots) {
      const row=el('section','h3pf-row');row.setAttribute('aria-label',`Shot ${shot.number}`);row.append(el('strong',null,`Shot ${shot.number}`));parent.append(row);
      if(shot.number!==1) {
        const key='shot-start:'+shot.number,draft=this.drafts.get(key);
        const input=this.field(row,`Shot ${shot.number} start (seconds)`,draft?.text??shot.seconds??'',text=>{
          this.drafts.set(key,{text,source:this.source});this.draftMessage('Start not applied yet. Leave the field or press Apply start to apply it.');
        });
        input.type='number';input.min='0';input.max=String(timing.duration);input.step='0.001';input.disabled=shot.seconds!==null&&shot.seconds<0;
        const apply=()=>this.applyShot({kind:'set-start',shot:shot.number,seconds:input.value.trim()===''?NaN:Number(input.value)},key);
        input.addEventListener('change',apply);input.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();apply();}});
        row.append(button('Apply start',apply));
        if(shot.problem)row.append(el('p','h3ct-hint',shot.problem));
        this.field(row,`Shot ${shot.number} change`,shot.cut===null?'custom':shot.cut?'cut':'continue',value=>{
          if(value!=='custom')this.applyShot({kind:'set-cut',shot:shot.number,cut:value==='cut'},'shot-change:'+shot.number);
        },{options:[['cut','Cut'],['continue','Continue without a cut'],['custom','Existing wording']]});
      }
      const index=entries.findIndex(e=>e.kind==='narrative'&&e.shot===shot.number);
      if(index>=0) {
        const entry=entries[index],body=entry.value.text.replace(/^At \d+:[0-5]\d\.\d{3},\s*/i,'');
        this.field(row,`Shot ${shot.number} description`,body,text=>this.edit(this.section,index,this.section+':'+index,'narrative',{text}),{area:true});
      }
      this.shotDetails(row,shot.number,entries);
      row.append(button(`Delete Shot ${shot.number}`,()=>this.applyShot({kind:'remove',shot:shot.number},'shot-remove:'+shot.number)));
    }
    if(this.newShot) {
      const key='shot:new',draft=this.drafts.get(key)??{text:''};
      const input=this.field(parent,'New shot start (seconds)',draft.text??'',text=>{this.drafts.set(key,{...draft,text});this.draftMessage('Enter a start after the previous shot, then apply it.');});
      input.type='number';input.step='0.001';input.min='0';input.max=String(timing.duration);
      const apply=()=>this.applyShot({kind:'append',seconds:input.value.trim()===''?NaN:Number(input.value),text:''},key);
      input.addEventListener('change',apply);parent.append(button('Apply new shot',apply));
    }
    parent.append(button('Add shot',()=>{
      if(!this.canLeave())return;
      if(!timing.shots.length)return this.applyShot({kind:'append',seconds:0,text:''});
      this.newShot=true;this.drafts.set('shot:new',{text:''});this.render();
    }));
  }
  shotDetails(parent,shot,entries) {
    const existing=entries.filter(e=>e.shot===shot&&e.kind==='cue');
    const pending=[...this.newDetails.entries()].filter(([id,item])=>id.startsWith(this.editor.video().id+':')&&item.shot===shot
      &&!existing.some(e=>e.value.key===item.value.key&&e.value.index===item.value.index));
    const show=(value,entry,index,key)=>{
      const field=SHOT_FIELDS.find(f=>f.key===value.key);if(!field||field.advanced&&!this.advanced)return;
      const label=`Shot ${shot} ${field.prefix.replace(' N',' '+value.index)}${field.repeatable&&value.index?' '+value.index:''}`;
      this.field(parent,label,value.text,text=>{
        if(field.advanced)this.advancedPins.set(this.editor.video().id,true);
        this.edit(this.section,index,key,'cue',{...value,text});
      },{area:!field.suggestions.length,suggestions:field.suggestions.length?field.suggestions:null});
    };
    for(const entry of existing)show(entry.value,entry,entries.indexOf(entry),this.section+':'+entries.indexOf(entry));
    for(const [id,item] of pending)show(item.value,null,null,id);
    for(const entry of entries.filter(e=>e.shot===shot&&e.kind==='existing'))this.row(parent,this.section,entry,entries.indexOf(entry),this.section+':'+entries.indexOf(entry));
    const dialogues=entries.filter(e=>e.shot===shot&&e.kind==='dialogue');
    dialogues.forEach((entry,i)=>this.dialogueRow(parent,shot,entry,entries.indexOf(entry),this.section+':'+entries.indexOf(entry),i+1));
    this.newRows.filter(r=>r.kind==='dialogue'&&r.shot===shot).forEach((entry,i)=>this.dialogueRow(parent,shot,entry,null,entry.key,dialogues.length+i+1));
    if(this.editor.video().dialogue==='manual')parent.append(button('Add dialogue',()=>{
      this.newRows.push({section:this.section,kind:'dialogue',shot,key:'dialogue:new:'+ ++ids,
        value:{speakers:[],identity:'',language:'',text:'',index:null}});this.render();
    }));
    const options=SHOT_FIELDS.filter(f=>f.key!=='dialogue'&&(this.advanced||!f.advanced)&&(f.repeatable||f.prefix.includes(' N')||!existing.some(e=>e.value.key===f.key)));
    this.field(parent,`Shot ${shot} add detail`,'',key=>{
      if(!key)return;
      const field=SHOT_FIELDS.find(f=>f.key===key);
      let index=null;
      if(field.repeatable)index=existing.some(e=>e.value.key===key)?Math.max(1,...existing.filter(e=>e.value.key===key).map(e=>e.value.index??1))+1:null;
      if(field.prefix.includes(' N')){index=Math.max(1,...existing.filter(e=>e.value.key.startsWith('effect')).map(e=>e.value.index??1));if(existing.some(e=>e.value.key===key&&e.value.index===index))index++;}
      const id=`${this.editor.video().id}:${shot}:${key}:${index??0}`;this.newDetails.set(id,{shot,value:{key,index,text:''}});this.render();
    },{options:options.map(f=>[f.key,f.prefix.replace(' N','')])});
  }
  dialogueRow(parent,shot,entry,index,key,ordinal) {
    const value=this.drafts.get(key)?.value??entry.value,title=`Shot ${shot} dialogue ${value.index??ordinal}`;
    const row=el('fieldset','h3pf-row');row.disabled=this.editor.video().dialogue!=='manual';row.append(el('legend',null,title));parent.append(row);
    const edit=patch=>this.edit(this.section,index,key,'dialogue',patch);
    const ids=[...new Set([...this.source.replace(/<d>[\s\S]*?(?:<\/d>|$)/g,'').matchAll(/\((S\d+(?:,S\d+)*)\)/g)].flatMap(m=>m[1].split(',')))];
    const next='S'+(Math.max(0,...ids.map(s=>Number(s.slice(1))))+1);
    this.field(row,title+' speaker IDs',value.speakers.join(', '),text=>edit({speakers:text.split(/[,\s]+/).filter(Boolean)}),{suggestions:[...ids,next]});
    const subjects=(readPromptFields(this.source).sections.find(s=>s.key==='subject_definitions')?.entries??[]).filter(e=>e.kind==='definition').map(e=>e.value.target);
    this.field(row,title+' speaker',value.identity,identity=>edit({identity}),{suggestions:subjects});
    this.field(row,title+' language',value.language,language=>edit({language}),{suggestions:['English','Spanish','Portuguese','French','Dutch','German','Japanese','Chinese','Korean']});
    this.field(row,title+' words',value.text,text=>edit({text}),{area:true});
    this.field(row,title+' delivery',value.delivery??'',delivery=>edit({delivery}),{suggestions:['Quietly','Whispering','Shouting','Breathless','Measured']});
    for(const [name,label] of [['voiceover','Off-screen voiceover'],['singing','Singing'],['fromPrevious','Continues from previous shot'],['toNext','Continues into next shot'],['cutoff','Cut off at the end']]) {
      const wrap=el('label','h3pf-actions'),input=el('input');input.type='checkbox';input.checked=!!value[name];input.setAttribute('aria-label',title+' '+label);
      input.addEventListener('change',()=>edit({[name]:input.checked,...(input.checked?{voiceover:{singing:false},singing:{voiceover:false},toNext:{cutoff:false},cutoff:{toNext:false}}[name]??{}:{})}));
      wrap.append(input,el('span',null,label));row.append(wrap);
    }
    row.append(button('Remove dialogue',()=>edit(null)));
  }
  row(parent,section,entry,index,key) {
    const row=el('div','h3pf-row');parent.append(row);
    const kind=entry.kind,value=this.drafts.get(key)?.value??entry.value;
    const edit=patch=>this.edit(section,index,key,kind,patch);
    if(kind==='definition') {
      if(index==null) {
        this.field(row,'Definition type',value.type??'subject',type=>{
          const target=type==='subject'?`<Subject ${Math.max(0,...[...`${this.source} ${this.editor.state.prompt??''}`.matchAll(/<Subject (\d+)>/g)].map(m=>Number(m[1])))+1}>`:'';
          this.drafts.set(key,{value:{...value,type,target}});this.render();
        },{options:[['subject','Subject'],['image','Picture'],['video','Video'],['audio','Audio']]});
        if(value.type&&value.type!=='subject')this.field(row,'Definition target',value.target,target=>edit({target}),{
          options:(this.editor.referenceOptions?.()??[]).filter(r=>r.name.startsWith(value.type)).map(r=>['@'+r.name,r.title||r.name])});
      }
      row.append(el('strong',null,value.target));
      this.field(row,`${value.target} description`,value.description,description=>edit({description}),{area:true});
      for(const [at,source] of (value.sources??[]).entries()) {
        const update=patch=>this.edit(section,index,key,kind,current=>({sources:current.sources.map((s,i)=>i===at?{...s,...patch}:s)}));
        this.field(row,`${value.target} source ${at+1}`,source.slot,slot=>update({slot}),{options:(this.editor.referenceOptions?.()??[]).map(r=>[r.name,r.title||r.name])});
        this.field(row,`${value.target} source ${at+1} role`,source.role,role=>update({role}),{suggestions:['appearance','environment','clothing','style','object','pose']});
      }
      row.append(button('Add source',()=>{this.drafts.set(key,{value:{...value,sources:[...(value.sources??[]),{slot:'',role:''}]}});this.render();}));
      if(this.editor.box()?.cast?.[value.target])row.append(button('Unlink from Cast',async()=>{
        await this.editor.cast.change({action:'apply',bible:this.editor.state.bible,links:{[this.editor.box().id]:{[value.target]:null}}});
      }));
    } else if(kind==='retention') {
      const targets=[...new Set([...(readPromptFields(this.source).sections.find(s=>s.key==='subject_definitions')?.entries??[]).filter(e=>e.kind==='definition').map(e=>e.value.target),
        ...(this.editor.referenceOptions?.()??[]).map(r=>'@'+r.name),value.target].filter(Boolean))];
      this.field(row,'Reference',value.target,target=>edit({target}),{options:targets});
      const numbers=promptShots(this.source).shots.map(s=>Number(/\d+/.exec(s.label)[0]));
      this.field(row,'Appears in shots',value.shots,shots=>edit({shots}),{options:numbers.map(n=>[n,`Shot ${n}`]),multiple:true});
      this.field(row,'Reference role or scope',value.scope,scope=>edit({scope}),{suggestions:['first frame','keyframe','last frame','composition','storyboard','cut and pacing structure']});
      const markers=/^@(?:audio|video_audio)/.test(value.target)?RETENTION_AUDIO:RETENTION_VISUAL;
      const custom=this.customRelationships.has(key)||!!value.relationship&&!markers.includes(value.relationship);
      this.field(row,'Relationship',custom?'__custom':value.relationship,relationship=>{
        if(relationship==='__custom'){this.customRelationships.add(key);this.render();return;}
        this.customRelationships.delete(key);edit({relationship});if(custom)this.render();
      },{options:[...markers.map(m=>[m,m[0].toUpperCase()+m.slice(1).replaceAll('_',' ')]),['__custom','Custom…']]});
      if(custom) {
        this.field(row,'Custom relationship',markers.includes(value.relationship)?'':value.relationship,relationship=>edit({relationship}));
        row.append(el('small','h3ct-hint','Outside the expected H3 vocabulary; written as typed.'));
      }
      this.field(row,'Retention details',value.detail,detail=>edit({detail}),{area:true});
    } else if(kind==='summary') {
      this.field(row,'Task types',value.taskTypes??[],chosen=>this.edit(section,index,key,kind,current=>({taskTypes:[...chosen,...current.taskTypes.filter(t=>!SUMMARY_TASKS.includes(t))]})),{options:SUMMARY_TASKS,multiple:true});
      const custom=(value.taskTypes??[]).filter(t=>!SUMMARY_TASKS.includes(t));
      this.field(row,'Custom task types',custom.join(' + '),text=>this.edit(section,index,key,kind,current=>({taskTypes:[...current.taskTypes.filter(t=>SUMMARY_TASKS.includes(t)),...text.split(/\s*\+\s*/).filter(Boolean)]})));
      this.field(row,'Summary',value.text,text=>edit({text}),{area:true});
    } else {
      this.field(row,entry.shot?`Shot ${entry.shot} Existing text`:section==='overall_soundscape'?'Soundscape':section==='non_diegetic_music'?'Background music':'Existing text',value.text,text=>edit({text}),{area:true});
    }
    if(kind!=='narrative')row.append(button('Remove entry',()=>edit(null)));
  }
  render() {
    this.destroy();const video=this.editor.video?.();if(!video)return;
    const active=document.activeElement,key=this.root.contains(active)?active.dataset?.key:null;
    const selection=key&&typeof active.selectionStart==='number'?[active.selectionStart,active.selectionEnd]:null;
    this.source=video.prompt;this.root.disabled=!!this.editor.readOnly?.length;this.controls.clear();this.root.replaceChildren();
    const parsed=readPromptFields(this.source,{tags:this.tags()});
    const cues=parsed.sections.flatMap(s=>s.entries.map(entry=>({section:s.key,entry})))
      .filter(({entry})=>entry.kind==='cue'&&SHOT_FIELDS.find(f=>f.key===entry.value.key)?.advanced&&entry.value.text.trim());
    const pin=this.advancedPins.get(video.id);
    this.advanced=this.editor.readOnly?.length&&pin!==undefined?pin:cues.length>0||pin===true;
    const visual=parsed.sections.some(s=>s.key==='detailed_description')?'detailed_description':'integrated_multimodal_description';
    const keys=['subject_definitions','summary','retention_analysis',visual,'overall_soundscape','non_diegetic_music'];
    if(parsed.sections.some(s=>s.key==='existing'||s.key==='alignment'))keys.push('existing');
    this.section??=parsed.sections[0]?.key??visual;if(this.section==='alignment')this.section='existing';
    if(!keys.includes(this.section))this.section=visual;
    const tabs=el('div','h3pf-tabs h3ct-section-tabs');tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','Prompt sections');
    for(const name of keys) {
      const tab=button('',()=>{if(!this.canLeave())return;this.section=name;this.render();});
      decorateIcon(tab,SECTION_ICONS[name]??'text',SECTION_TITLES[name]??'Existing text',{text:true});
      tab.classList.toggle('empty',!parsed.sections.filter(s=>s.key===name).some(s=>s.entries.some(e=>e.range.before.trim())));
      tab.setAttribute('role','tab');tab.setAttribute('aria-selected',String(name===this.section));tab.tabIndex=name===this.section?0:-1;
      tab.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();
        const at=keys.indexOf(this.section),next=event.key==='Home'?0:event.key==='End'?keys.length-1:(at+(event.key==='ArrowRight'?1:-1)+keys.length)%keys.length;
        if(this.canLeave()){this.section=keys[next];this.render();}});tabs.append(tab);
    }
    // In the fieldset's legend so a read-only Timeline, which disables the fieldset, can still browse sections and details.
    const legend=el('legend'),advanced=new SwitchSection('Advanced',{onToggle:on=>this.toggleAdvanced(on,cues)});
    advanced.body.hidden=true;advanced.head.dataset.key='Advanced';this.controls.set('Advanced',advanced.head);
    advanced.set(this.advanced,{state:!this.advanced&&cues.length?`${cues.length} hidden`:''});
    legend.append(advanced.root,tabs);this.root.append(legend);
    this.note=el('p','h3pf-error',this.message);this.note.setAttribute('role','status');this.root.append(this.note);
    this.discardButton=button('Discard draft',()=>this.discardDrafts());this.discardButton.hidden=!this.hasDrafts();this.root.append(this.discardButton);
    let body=el('div');body.setAttribute('role','tabpanel');body.setAttribute('aria-label',SECTION_TITLES[this.section]??'Existing text');this.root.append(body);
    if(['summary','overall_soundscape','non_diegetic_music'].includes(this.section)) {
      const selected=promptSections(this.source)?.find(s=>s.key===this.section);
      const stashKey=video.id+':'+this.section;
      const block=new SwitchSection('Include in prompt',{onToggle:on=>{
        const current=promptSections(video.prompt)?.find(s=>s.key===this.section);
        if(!current||this.editor.readOnly?.length)return;
        const before=video.prompt.slice(current.bodyStart,current.end);
        if(!on)this.sectionStash.set(stashKey,before);
        const text=on?this.sectionStash.get(stashKey)??before:'\n\n';
        const source=video.prompt,next=replacePromptRanges(source,[{start:current.bodyStart,end:current.end,before,text}]);
        this.editor.applyPrompt(source,next,{structural:true});this.render();
      }});
      block.set(!selected||selected.fields.some(f=>f.value.trim()));
      body.append(block.root);body=block.body;
    }
    const sections=parsed.sections.filter(s=>s.key===this.section||(this.section==='existing'&&s.key==='alignment'));
    if(['integrated_multimodal_description','detailed_description'].includes(this.section)) {
      this.shotCards(body,sections.flatMap(s=>s.entries));
      const restored=this.controls.get(key);if(restored){restored.focus?.();if(selection)restored.setSelectionRange?.(...selection);}return;
    }
    let shown=0;
    for(const section of sections) {
      const entries=sections.filter(s=>s.key===section.key).flatMap(s=>s.entries);
      for(const entry of section.entries){const index=entries.indexOf(entry);this.row(body,section.key,entry,index,section.key+':'+index);shown++;}
    }
    for(const draft of this.newRows.filter(r=>r.section===this.section)){this.row(body,draft.section,draft,null,draft.key);shown++;}
    if(!shown)body.append(el('p','h3ct-hint','Empty. Add only the fields this clip needs.'));
    if(this.section==='subject_definitions') {
      if(this.editor.state.bible&&this.editor.cast)body.append(this.editor.cast.scheduleAdd(this.editor.box()));
      else body.append(button('Open Cast',()=>this.editor.cast?.open?.(null)));
    }
    const kind=this.section==='subject_definitions'?'definition':this.section==='retention_analysis'?'retention':this.section==='summary'?'summary':'existing';
    if(this.section!=='existing')body.append(button(kind==='definition'?'Add definition':kind==='retention'?'Add retention':kind==='summary'?'Add summary':'Add text',()=>{
      const max=Math.max(0,...[...`${this.source} ${this.editor.state.prompt??''}`.matchAll(/<Subject (\d+)>/g)].map(m=>Number(m[1])));
      const value=kind==='definition'?{target:`<Subject ${max+1}>`,description:'',sources:[]}:kind==='retention'?{target:'',shots:[],scope:'',relationship:'',detail:''}:kind==='summary'?{taskTypes:[],text:''}:{text:''};
      const draft={section:this.section,kind,key:'new:'+ ++ids,value};this.newRows.push(draft);this.drafts.set(draft.key,{value});this.render();
    }));
    const restored=this.controls.get(key);if(restored){restored.focus?.();if(selection)restored.setSelectionRange?.(...selection);}
  }
}
