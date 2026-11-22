import {OverlapInspector} from './h3c_overlap_inspector.mjs';
import * as tracks from './h3c_tracks.mjs';
import * as model from './h3c_timeline_model.mjs';
import {icon,iconButton} from './h3c_icons.mjs';
const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n;};
// A lane's type as an icon and its number, with the full name for screen readers and as a tooltip.
function laneLabel(track) {
 const label=el('span','h3ct-track-name');label.title=track.name;
 if(!['video','audio','text'].includes(track.type)){label.textContent=track.name;return label;}
 label.append(icon(track.type));
 const number=/\d+$/.exec(track.name??'')?.[0];if(number)label.append(el('span','h3ct-track-number',number));
 label.append(el('span','h3ci-sr',track.name));return label;
}
const laneAction=(name,label,action)=>{const button=iconButton(name,label,action);button.classList.add('h3ct-lane-action');return button;};

export function snapPlacement(state,{id,track,start,end,tolerance=4,bypass=false,playhead=null,edge='move'}) {
 const duration=end-start;start=Math.max(0,Math.round(start));end=start+duration;
 if(bypass)return {start,end,guide:null};
 const points=tracks.placements(state).filter(p=>p.id!==id).flatMap(p=>[p.start,p.end]);if(playhead!=null)points.push(playhead);
 let best=null;
 for(const point of points)for(const anchor of edge==='end'?[end]:[start,end]) {
  const delta=point-anchor;if(Math.abs(delta)<=tolerance&&(!best||Math.abs(delta)<Math.abs(best.delta)))best={delta,point};
 }
 if(!best)return {start,end,guide:null};
 return edge==='end'?{start,end:Math.max(start+1,end+best.delta),guide:best.point}:{start:Math.max(0,start+best.delta),end:Math.max(0,start+best.delta)+duration,guide:best.point};
}
export function placeClip(state,id,track,start) {
 const trial=structuredClone(state),box=trial.boxes.find(b=>b.id===id);
 if(!box)throw Error('This clip no longer exists.');Object.assign(box,{track,start:Math.max(0,Math.round(start))});tracks.validate(trial);
 Object.assign(state.boxes.find(b=>b.id===id),{track:box.track,start:box.start});
}
// Each kept bridge as the clip it leaves and the clip it leads into, to notice an edit that pulls them apart.
function bridgeEnds(state){return model.keptBridges(state).map(b=>{const index=state.boxes.findIndex(x=>x.id===b.before);return {after:b.before,before:state.boxes[tracks.previousIndex(state,index)]?.id};});}
export function visibleSpans(state) {
 const spans=tracks.placements(state),priority=new Map((state.tracks??[{id:'legacy'}]).map((t,i)=>[t.id,i])),result=[];
 const boundaries=[...new Set([0,...spans.flatMap(p=>[p.start,p.end]),...(state.overlap_switches??[]).map(s=>s.at)])].sort((a,b)=>a-b);
 for(let i=0;i<boundaries.length-1;i++) {
  const start=boundaries[i],end=boundaries[i+1],active=spans.filter(p=>p.start<=start&&p.end>start).sort((a,b)=>priority.get(a.track)-priority.get(b.track));
  let top=active.at(-1);
  for(const sw of state.overlap_switches??[])if(top&&[sw.from,sw.to].includes(top.id)&&[sw.from,sw.to].every(id=>active.some(p=>p.id===id)))top=active.find(p=>p.id===(start<sw.at?sw.from:sw.to));
  const id=top?.id??null,last=result.at(-1);if(last&&last.id===id)last.end=end;else result.push({start,end,id});
 }
 return result;
}
const CSS=`
.h3ct-still-prompt-preparation>.h3ct-project-instructions{display:none}.h3ct-still-prompt-preparation{display:flex;align-items:center;gap:6px;flex-wrap:wrap}.h3ct-still-prompt-preparation>.h3ct-hint{margin:0;font-size:12px}.h3ct-project-instructions textarea{width:100%;min-height:140px}.h3ci-button{display:inline-flex;align-items:center;justify-content:center;gap:5px;min-width:28px;min-height:28px;padding:4px 6px!important;flex-shrink:0}
.h3ci-button svg{flex-shrink:0;pointer-events:none}.h3ci-sr{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap}
.h3ci-button:focus-visible,.h3ct-track-clip:focus-visible{outline:2px solid #9dbef1;outline-offset:2px}
.h3ct-track-editor{position:relative;min-height:48px;background:#15171c;--track-head:var(--h3ct-track-head,96px)}
.h3ct-track-row{display:grid;grid-template-columns:var(--track-head) minmax(0,1fr);min-height:48px;border-bottom:1px solid #343a46}
.h3ct-track-head{position:sticky;left:0;z-index:3;display:flex;align-items:center;gap:2px;padding:0 2px 0 8px;background:#242932;min-width:0;font-size:12px;color:#aab1bd}
.h3ct-track-name{flex:1;display:flex;align-items:center;gap:3px;min-width:0;overflow:hidden;white-space:nowrap}.h3ct-track-name svg{flex:0 0 auto;width:15px;height:15px}
.h3ct-track-number{font:600 11px/1 system-ui;color:#c3cad4}.h3ct-track-body{position:relative;min-height:48px;min-width:0;background:#13161b}
.h3ct-lane .h3ci-button.h3ct-lane-action{min-width:22px;min-height:22px;padding:3px!important;color:#8b93a1;background:transparent;border-color:transparent}
.h3ct-lane .h3ci-button.h3ct-lane-action:hover:not(:disabled){color:#e8ecf2;background:#ffffff14;filter:none}.h3ct-lane-action svg{width:14px;height:14px}
.h3ct-lane-action.h3ct-lane-delete{opacity:0}.h3ct-track-head:hover .h3ct-lane-delete,.h3ct-lane-header:hover .h3ct-lane-delete,.h3ct-lane-delete:focus-visible{opacity:1}
.h3ct-track-row.selected>.h3ct-track-head{background:#30405a}.h3ct-track-clip{position:absolute;top:4px;bottom:4px;background:#34584f;border:1px solid #63857c;border-radius:3px;overflow:hidden;color:#edf5f0;cursor:grab;touch-action:none;padding:3px 6px;text-align:left;font:12px/1.3 system-ui}
.h3ct-track-row:nth-child(even) .h3ct-track-clip{background:#5c5130;border-color:#9a8951}.h3ct-track-clip.selected{outline:2px solid #9dbef1;outline-offset:-2px}
.h3ct-track-clip img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:.45;pointer-events:none}.h3ct-track-clip span{position:relative}
.h3ct-track-clip .h3ct-handle{position:absolute;right:0;top:0;bottom:0;width:8px;cursor:ew-resize;background:#ffffff18}.h3ct-track-add{display:flex;align-items:center;gap:6px;position:sticky;left:0;padding:6px 8px;width:max-content;color:#c3cad4;font-size:12px}
.h3ct-track-footer{flex:0 0 auto;background:#1d2027;border-top:1px solid #3c4350}.h3ct-track-message{margin:0;padding:0 8px;max-width:80ch;color:#edbd83;font-size:12px}.h3ct-track-message:empty{display:none}.h3ct-snap-guide{position:absolute;top:0;bottom:0;width:1px;background:#c8dfff;pointer-events:none;z-index:5}
.h3ct-track-editor .h3ct-empty{position:static;padding:8px;display:inline-flex;align-items:center;gap:6px;pointer-events:auto}.h3ct-track-editor .h3ct-button{white-space:nowrap}
.h3ct-lane.h3ct-independent>.h3ct-track{display:none!important}
.h3ct-lane.h3ct-independent>.h3ct-stills,.h3ct-lane.h3ct-independent>.h3ct-ruler{margin-left:var(--h3ct-track-head,96px);width:calc(100% * var(--h3ct-zoom,1) - var(--h3ct-track-head,96px))}
.h3ct-lane>.h3ct-track-editor{width:calc(100% * var(--h3ct-zoom,1))}
.h3ct-independent>.h3ct-audio .h3ct-audio-lanes>.h3ct-audio-lane{margin-left:var(--h3ct-track-head,96px);overflow:visible}
.h3ct-independent .h3ct-lane-header{position:sticky;left:0;margin-left:calc(-1 * var(--h3ct-track-head,96px));width:var(--h3ct-track-head,96px);height:40px;display:flex;align-items:center;gap:2px;background:#242932;padding:0 2px 0 8px;z-index:3;font-size:12px;color:#aab1bd}
.h3ct-lane.h3ct-independent{--h3ct-track-head:68px}
.h3ct-independent .h3ct-audio>.h3ct-row,.h3ct-independent .h3ct-text-lane{display:none!important}
.h3ct-independent .h3ct-audio .h3ct-audio-lanes>.h3ct-row{display:none!important}
.h3cx-track{display:flex;flex-direction:column}.h3cx-track>.h3ct-lane{flex:1;min-height:0;overflow:auto;display:flex;flex-direction:column;border-radius:3px}.h3cx-track>.h3ct-lane>*{flex-shrink:0}.h3cx-track>.h3ct-lane>.h3ct-track-editor{flex:0 0 auto;min-height:0}.h3cx-track>.h3ct-hint{margin-bottom:0}.h3ct-track-editor .h3ct-text-cue{position:absolute;top:8px;bottom:8px;background:#4b405e;color:#f0e7fc;border:1px solid #847297;padding:3px;overflow:hidden;font:12px system-ui}
@media(pointer:coarse){.h3ci-button,.h3ct-lane .h3ci-button.h3ct-lane-action{min-height:44px;min-width:44px}.h3ct-lane,.h3ct-lane.h3ct-independent{--h3ct-track-head:96px}.h3ct-track-row,.h3ct-track-body{min-height:56px}.h3ct-lane-action.h3ct-lane-delete{opacity:1}}
`;
export class TrackEditor {
 constructor(editor) {
  this.editor=editor;this.expanded=false;this.selectedTrack=null;
  this.root=el('div','h3ct-track-editor');this.rows=el('div');this.add=el('div','h3ct-track-add');this.message=el('p','h3ct-track-message');this.message.setAttribute('role','status');
  this.add.append(el('span',null,'Add lane'));
  for(const type of tracks.TYPES){const button=iconButton(type,`Add ${type} lane`,()=>this.addLane(type));button.dataset.laneType=type;this.add.append(button);}
  this.footer=el('div','h3ct-track-footer');this.footer.append(this.add,this.message);
  this.overlap=new OverlapInspector(editor);this.root.append(this.rows,this.overlap.root);
  if(!document.getElementById('h3ct-track-editor-style')){const style=el('style');style.id='h3ct-track-editor-style';style.textContent=CSS;document.head.append(style);}
 }
 mutate(operation) {
  if(this.editor.promptDraftsReady?.()===false)return false;
  if(this.editor.readOnly.length)return false;
  const state=structuredClone(this.editor.state),id=this.editor.box()?.id,bridged=bridgeEnds(state);
  try{const selected=operation(state);tracks.validate(state);
   const kept=new Set(model.keptBridges(state).map(b=>b.before));
   if(bridged.some(({before,after})=>[before,after].every(x=>state.boxes.some(b=>b.id===x))&&!kept.has(after)))throw Error('That would separate a clip from its insertion bridge. Remove the bridge first.');this.editor.host.undoStep?.();this.editor.state=state;this.editor.selected=Math.max(0,state.boxes.findIndex(b=>b.id===(selected??id)));this.editor.commit();this.editor.host.undoStep?.();this.message.textContent='';return true;}
  catch(error){this.message.textContent=error.message;return false;}
 }
 addLane(type) {
  let id;
  if(!this.mutate(state=>{id=tracks.addTrack(state,type);this.selectedTrack=id;}))return;
  this.expanded=true;this.render(this.span);
  if(type==='audio'){this.editor.audioLanes.pendingTrack=id;this.editor.audioLanes.upload.click();}
  if(type==='text'){this.editor.audioLanes.selectedTextTrack=id;this.editor.audioLanes.textUpload.click();}
 }
 removeLane(id) {
  if(this.editor.readOnly.length)return;
  const state=this.editor.state,track=state.tracks.find(t=>t.id===id),contents=tracks.trackContents(state,id);
  if(Object.values(contents).some(Boolean)&&!globalThis.confirm?.(`Delete ${track.name} and its contents? ${contents.clips} video clips, ${contents.audio} audio sources, ${contents.text} text attachments. Media files will be kept.`))return;
  this.mutate(state=>{const gone=state.boxes.filter(b=>b.track===id).map(b=>b.id);tracks.removeTrack(state,id);model.forgetBoxes(state,gone);});
 }
 addClip() {
  this.mutate(state=>{
   const track=state.tracks.find(t=>t.id===this.selectedTrack&&t.type==='video')??state.tracks.find(t=>t.type==='video');
   const id=track?.id??tracks.addTrack(state,'video');this.selectedTrack=id;
   const start=Math.max(0,Math.round(this.editor.playheadFrame??tracks.durationFrames(state)));
   const box={id:model.newId(state),track:id,start,frames:model.defaultFrames(true,this.editor.host.context()),cut:true,prompt:'',seed:model.newSeed(),first:'',last:''};
   state.boxes.push(box);return box.id;
  });this.editor.inspectClip();
 }
 move(delta) {
  this.mutate(state=>{
   const index=this.editor.selected,indices=tracks.trackIndices(state,index),target=indices[indices.indexOf(index)+delta];
   if(target===undefined)return;
   const box=state.boxes[index],other=state.boxes[target],first=delta<0?other:box,last=delta<0?box:other;
   const gap=last.start-first.start-first.frames,start=first.start;
   last.start=start;first.start=start+last.frames+gap;
  });this.editor.inspectClip();
 }
 duplicate() {
  this.mutate(state=>{
   const original=state.boxes[this.editor.selected],index=model.duplicateBox(state,this.editor.selected,this.editor.host.context()),copy=state.boxes[index];
   copy.cut=true;copy.start=original.start+original.frames;
   for(const p of tracks.placements(state).filter(p=>p.track===copy.track&&p.id!==copy.id).sort((a,b)=>a.start-b.start))if(p.end>copy.start&&p.start<copy.start+copy.frames)copy.start=p.end;
   return copy.id;
  });this.editor.inspectClip();
 }
 removeClip() {
  this.mutate(state=>{
   const id=state.boxes[this.editor.selected].id;
   model.removeBox(state,this.editor.selected,this.editor.host.context());
   state.overlap_switches=state.overlap_switches?.filter(s=>s.from!==id&&s.to!==id)??[];
  });this.editor.inspectClip();
 }
 decorateAudio() {
  const audio=this.editor.audioLanes,state=this.editor.state;
  audio.header.hidden=true;audio.textLane.hidden=!audio.text||tracks.enabled(state);
  const lanes=[...audio.lanes.children].filter(n=>n.classList.contains('h3ct-audio-lane')&&!n.classList.contains('h3ct-row'));
  for(const [index,lane] of lanes.entries()){
   const recording=audio.clips[index];if(!recording)continue;
   const track=state.tracks?.find(t=>t.id===recording.track);
   // Taking a header out and putting a new one in restyles the whole ComfyUI page, so one that already says the same stays.
   const signature=JSON.stringify([recording.slot,recording.track,track?.name??index,tracks.enabled(state)]);
   if(lane._trackHeader?.parentNode===lane&&lane._trackSignature===signature)continue;
   lane._trackHeader?.remove();
   const header=el('div','h3ct-lane-header');
   header.append(laneLabel({type:'audio',name:track?.name??`Audio ${index+1}`}));
   const remove=laneAction('trash',`Delete ${track?.name??'audio lane'}`,()=>{
    if(!globalThis.confirm?.(`Delete this audio lane and its recording? Media files will be kept.`))return;
    this.mutate(state=>{tracks.enableTracks(state);const clip=state.audio_clips.find(c=>c.slot===recording.slot);if(clip)tracks.removeTrack(state,clip.track);});
   });
   remove.classList.add('h3ct-lane-delete');header.append(remove);
   if(!tracks.enabled(state)){header.style.marginLeft='0';header.style.position='absolute';header.style.right='0';}
   lane._trackHeader=header;lane._trackSignature=signature;lane.prepend(header);
  }
 }
 render(span) {
  this.span=span??Math.max(1,model.totalFrames(this.editor.state));
  const state=this.editor.state,active=tracks.enabled(state),rows=[];
  this.editor.laneEl.classList.toggle('h3ct-independent',active);
  this.add.querySelectorAll?.('button').forEach(b=>b.disabled=this.editor.readOnly.length>0);
  if(!active){if(this.rows.firstChild)this.rows.replaceChildren();return;}
  const videoTracks=state.tracks.filter(t=>t.type==='video');
  const master=this.row({id:'combined',type:'video',name:'All video lanes'},false);
  const toggle=laneAction(this.expanded?'collapse':'expand',this.expanded?'Collapse video lanes':'Expand video lanes',()=>{this.expanded=!this.expanded;this.render(this.span);});toggle.setAttribute('aria-expanded',String(this.expanded));master.head.append(toggle);
  for(const p of visibleSpans(state))if(p.id)this.clip(master.body,state.boxes.findIndex(b=>b.id===p.id),p.start,p.end,false);
  rows.push(master.root);
  const placements=tracks.placements(state),pairs=[];
  for(let i=0;i<placements.length;i++)for(let j=i+1;j<placements.length;j++){
   const a=placements[i],b=placements[j],start=Math.max(a.start,b.start),end=Math.min(a.end,b.end);
   if(a.track!==b.track&&end>start)pairs.push({a,b,start,end});
  }
  if(pairs.length){
   const row=this.row({id:'overlaps',name:'Overlaps'},false);row.root.classList.add('h3ct-overlap-row');
   for(const pair of pairs){const ai=state.boxes.findIndex(b=>b.id===pair.a.id)+1,bi=state.boxes.findIndex(b=>b.id===pair.b.id)+1;
    const button=iconButton('video',`Edit overlap between clips ${ai} and ${bi}`,()=>this.overlap.show(pair.a.id,pair.b.id));button.classList.add('h3ct-overlap-mark');button.append(el('span',null,`${ai} / ${bi}`));button.style.left=`${100*pair.start/this.span}%`;button.style.maxWidth=`${Math.max(28,100*(pair.end-pair.start)/this.span)}%`;row.body.append(button);
   }rows.push(row.root);
  }
  if(this.expanded)for(const track of [...videoTracks].reverse()){
   const row=this.row(track);
   row.root.classList.toggle('selected',this.selectedTrack===track.id);
   row.head.addEventListener('click',()=>{this.selectedTrack=track.id;this.render(this.span);});
   for(const p of tracks.placements(state).filter(p=>p.track===track.id))this.clip(row.body,state.boxes.findIndex(b=>b.id===p.id),p.start,p.end,true);
   if(!state.boxes.some(b=>b.track===track.id)){const add=iconButton('plus',`Add clip to ${track.name}`,()=>{this.selectedTrack=track.id;this.addClip();});add.classList.add('h3ct-empty');row.body.append(add);}
   rows.push(row.root);
  }
  for(const track of state.tracks.filter(t=>t.type==='text')){
   const row=this.row(track),attachment=state.text_lanes?.find(t=>t.track===track.id)?.attachment;
   row.head.addEventListener('click',()=>{this.editor.audioLanes.selectedTextTrack=track.id;this.editor.audioLanes.renderText();this.editor.audioLanes.selectText();});
   if(attachment)for(const cue of attachment.cues??[]){const mark=el('button','h3ct-text-cue',cue.text);mark.title=cue.text;const clock=attachment.sync_audio?state.audio_clips?.find(c=>c.slot===attachment.audio_slot):attachment;if(!clock)continue;const start=(clock.start+cue.start-clock.source_start)*24;mark.style.left=`${100*start/this.span}%`;mark.style.width=`${100*(cue.end-cue.start)*24/this.span}%`;mark.addEventListener('click',()=>row.head.click());row.body.append(mark);}
   else row.body.append(iconButton('upload',`Import timed text into ${track.name}`,()=>{this.editor.audioLanes.selectedTextTrack=track.id;this.editor.audioLanes.textUpload.click();}));rows.push(row.root);
  }
  for(const track of state.tracks.filter(t=>t.type==='audio'&&!state.audio_clips?.some(c=>c.track===t.id))){const row=this.row(track);row.body.append(iconButton('upload',`Add audio to ${track.name}`,()=>{this.editor.audioLanes.pendingTrack=track.id;this.editor.audioLanes.upload.click();}));rows.push(row.root);}
  this.rows.replaceChildren(...rows);
 }
 row(track,deletable=true) {
  const root=el('div','h3ct-track-row'),head=el('div','h3ct-track-head'),body=el('div','h3ct-track-body');root.dataset.track=track.id;
  head.append(laneLabel(track));if(deletable){const remove=laneAction('trash',`Delete ${track.name}`,()=>this.removeLane(track.id));remove.classList.add('h3ct-lane-delete');remove.disabled=this.editor.readOnly.length>0;head.append(remove);}
  root.append(head,body);return {root,head,body};
 }
 clip(body,index,start,end,editable) {
  const box=this.editor.state.boxes[index];if(!box)return;
  const item=el('div','h3ct-track-clip');item.tabIndex=0;item.setAttribute('role','button');item.setAttribute('aria-label',`Clip ${index+1}`);item.classList.toggle('selected',index===this.editor.selected);
  item.style.left=`${100*start/this.span}%`;item.style.width=`${100*(end-start)/this.span}%`;item.title=`Clip ${index+1}: ${box.prompt||'Enter a prompt'}`;
  const thumb=this.editor.statusOf(box)?.thumb;if(thumb){const img=el('img');img.src=this.editor.host.viewUrl(thumb);img.alt='';img.draggable=false;item.append(img);}
  item.append(el('span',null,`#${index+1}  ${model.seconds(box.frames)} s`));
  item.addEventListener('click',()=>{this.selectedTrack=box.track;this.editor.select(index);});item.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();this.editor.select(index);}});
  if(editable){item.addEventListener('pointerdown',event=>this.drag(event,index,item,body));const handle=el('div','h3ct-handle');handle.addEventListener('pointerdown',event=>this.drag(event,index,item,body,true));item.append(handle);}
  body.append(item);
 }
 drag(event,index,item,body,resize=false) {
  if(event.button!==0||this.editor.readOnly.length)return;event.preventDefault();event.stopPropagation();
  const box=this.editor.state.boxes[index],initial={...box},rect=body.getBoundingClientRect(),origin=event.clientX;
  item.setPointerCapture(event.pointerId);const guide=el('div','h3ct-snap-guide');body.append(guide);let target=null;
  const move=e=>{const delta=Math.round((e.clientX-origin)*this.span/rect.width);target=snapPlacement(this.editor.state,{id:box.id,track:box.track,start:resize?initial.start:initial.start+delta,end:initial.start+initial.frames+delta,tolerance:Math.ceil(7*this.span/rect.width),bypass:e.shiftKey,playhead:this.editor.playheadFrame,edge:resize?'end':'move'});if(resize){const fresh=model.isFresh(this.editor.state,index),context=this.editor.host.context();const count=target.end-target.start;target.end=target.start+(box.exact?model.fitExact(count,fresh,context,model.maxFrames(this.editor.state)):model.snapFrames(count,fresh,context,model.maxFrames(this.editor.state)));}const over=document.elementFromPoint(e.clientX,e.clientY)?.closest('.h3ct-track-row')?.dataset.track;target.track=!resize&&this.editor.state.tracks.some(t=>t.id===over&&t.type==='video')?over:box.track;item.style.left=`${100*target.start/this.span}%`;item.style.width=`${100*(target.end-target.start)/this.span}%`;guide.hidden=target.guide===null;guide.style.left=`${100*(target.guide??0)/this.span}%`;};
  const finish=e=>{item.removeEventListener('pointermove',move);item.removeEventListener('pointerup',finish);item.removeEventListener('pointercancel',cancel);guide.remove();if(target)this.mutate(state=>{const b=state.boxes.find(b=>b.id===initial.id);b.frames=target.end-target.start;placeClip(state,b.id,target.track,target.start);});this.render(this.span);};
  const cancel=()=>{item.removeEventListener('pointermove',move);item.removeEventListener('pointerup',finish);item.removeEventListener('pointercancel',cancel);guide.remove();this.render(this.span);};
  item.addEventListener('pointermove',move);item.addEventListener('pointerup',finish);item.addEventListener('pointercancel',cancel);
 }
}
