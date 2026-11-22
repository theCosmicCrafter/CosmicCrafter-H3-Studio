import * as tracks from './h3c_tracks.mjs';
import {iconButton} from './h3c_icons.mjs';
const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n;};
const matches=(s,a,b)=>[a,b].includes(s.from)&&[a,b].includes(s.to);
export function overlapDraft(state,from,to) {
 const spans=tracks.placements(state),a=spans.find(p=>p.id===from),b=spans.find(p=>p.id===to);
 if(!a||!b||a.track===b.track)throw Error('Select clips on two different video lanes.');
 const start=Math.max(a.start,b.start),end=Math.min(a.end,b.end);
 if(end-start<2)throw Error('The clips need at least two overlapping frames for a switch. Move or trim a clip.');
 const existing=state.overlap_switches?.find(s=>matches(s,from,to));
 return {start,end,existing:!!existing,value:structuredClone(existing??{from,to,at:Math.floor((start+end)/2),fade:Math.min(6,end-start-2),sound:'screen'})};
}
export function editOverlap(state,from,to,value) {
 const trial=structuredClone(state);trial.overlap_switches=(trial.overlap_switches??[]).filter(s=>!matches(s,from,to));
 if(value)trial.overlap_switches.push(structuredClone(value));tracks.validate(trial);state.overlap_switches=trial.overlap_switches;
}
export class OverlapInspector {
 constructor(editor){this.editor=editor;this.root=el('div','h3ct-overlap-inspector');this.root.hidden=true;}
 show(from,to){this.target={from,to};this.render();this.root.hidden=false;this.editor.inspect({kind:'overlap',from,to});}
 // Removing a focused field blurs it, which can fire its change again while the children are being replaced.
 render(){
  if(this.rendering)return;
  this.rendering=true;
  try{this.draw();}finally{this.rendering=false;}
 }
 draw(){
  if(!this.target)return;
  const {from,to}=this.target,state=this.editor.state;
  this.root.replaceChildren();
  let draft;try{draft=overlapDraft(state,from,to);}catch(error){this.root.append(el('p','h3cx-note',error.message));return;}
  const label=id=>`Clip ${state.boxes.findIndex(b=>b.id===id)+1}`;
  const title=el('h3','h3cx-title',`${label(from)} / ${label(to)}`),note=el('p','h3cx-note',`${(draft.start/24).toFixed(2)}–${(draft.end/24).toFixed(2)} s on the Timeline`);
  const message=el('p','h3ct-hint');message.setAttribute('role','status');
  const apply=value=>{
   const ok=this.editor.trackEditor.mutate(next=>editOverlap(next,from,to,value));
   if(ok)this.render();else message.textContent=this.editor.trackEditor.message.textContent;
  };
  const enabled=el('input');enabled.type='checkbox';enabled.checked=draft.existing;enabled.disabled=this.editor.readOnly.length>0;enabled.setAttribute('aria-label','Use overlap switch');
  const toggle=el('label','h3ct-overlap-toggle');toggle.append(enabled,el('span',null,'Use switch'));
  enabled.addEventListener('change',()=>apply(enabled.checked?{...draft.value,id:draft.value.id??`switch-${crypto.randomUUID()}`} :null));
  this.root.append(title,note,toggle);
  if(!draft.existing){this.root.append(el('p','h3cx-note','The upper lane is on screen. Turn on the switch to choose when the picture changes.'));return;}
  const field=(text,control)=>{const label=el('label','h3ct-field');label.append(el('span',null,text),control);this.root.append(label);};
  const source=el('div','h3ct-overlap-sources',`${label(draft.value.from)} to ${label(draft.value.to)}`);
  const swap=iconButton('undo','Reverse overlap sources',()=>apply({...draft.value,from:draft.value.to,to:draft.value.from}));swap.disabled=this.editor.readOnly.length>0;source.append(swap);this.root.append(source);
  for(const [key,text,min,max] of [['at','Switch at frame',draft.start+1,draft.end-1],['fade','Fade frames',0,12]]){
   const input=el('input','h3ct-number');input.type='number';input.min=String(min);input.max=String(max);input.step='1';input.value=String(draft.value[key]);input.setAttribute('aria-label',`Overlap ${text.toLowerCase()}`);input.disabled=this.editor.readOnly.length>0;
   input.addEventListener('change',()=>{if(!input.validity.valid){message.textContent=`Choose ${text.toLowerCase()} from ${min} to ${max}.`;return;}apply({...draft.value,[key]:Number(input.value)});});field(text,input);
  }
  const sound=el('select','h3ct-select');sound.setAttribute('aria-label','Overlap sound');sound.disabled=this.editor.readOnly.length>0;
  for(const [value,text] of [['screen','The video on screen'],[from,label(from)],[to,label(to)]]){const option=el('option',null,text);option.value=value;sound.append(option);}sound.value=draft.value.sound;
  sound.addEventListener('change',()=>apply({...draft.value,sound:sound.value}));field('Sound',sound);
  this.root.append(el('p','h3cx-note','Fade is centered on the switch. Clips on higher lanes can cover this pair.'),message);
 }
}
