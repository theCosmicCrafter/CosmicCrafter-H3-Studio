import {promptShots} from './h3c_prompt_sections.mjs?v=1f35473e5668';
const sameTarget=(a,b)=>a?.kind===b?.kind&&a?.shot===b?.shot;
const sameFile=(a,b)=>a&&b&&['filename','subfolder','type'].every(key=>a[key]===b[key]);
export function sceneStart(state,index){while(index>0&&!state.boxes[index].new_scene&&state.boxes[index].join?.kind!=='new_scene')index--;return state.boxes[index]?.id;}
export function reconcileSceneAnchors(state){
 if(!state.continuity)return;
 const scenes=new Set(state.boxes.map((_,index)=>sceneStart(state,index)));
 state.continuity.anchors=state.continuity.anchors.filter(anchor=>scenes.has(anchor.scene)&&accepted(state,anchor.box,anchor.target,anchor.file)&&
   (anchor.target.kind!=='shot'||promptShots(state.boxes.find(box=>box.id===anchor.box).prompt??'').shots.some(shot=>shot.label===`[Shot ${anchor.target.shot}]`)));
}
export function sceneAnchor(state,index){
 const scene=sceneStart(state,index);
 return state.continuity?.anchors?.find(anchor=>anchor.scene===scene&&state.boxes.some(box=>box.id===anchor.box))??null;
}
function accepted(state,boxId,target,file){
 return state.boxes.find(box=>box.id===boxId)?.previews?.some(item=>sameTarget(item.target??(item.shot===1?{kind:'first'}:{kind:'shot',shot:item.shot}),target)&&sameFile(item.guide,file));
}
function validate(state,boxId,target,image){
 if(!accepted(state,boxId,target,image.file))throw Error('Only an accepted guide can become a scene anchor.');
 if(!/^[a-f0-9]{64}$/.test(image.sha256??''))throw Error('Verify the scene anchor image before acceptance.');
}
export function acceptSceneAnchor(state,boxId,target,image){
 if(target.kind!=='first')return null;
 validate(state,boxId,target,image);
 const index=state.boxes.findIndex(box=>box.id===boxId),scene=sceneStart(state,index),old=sceneAnchor(state,index);
 if(old&&old.box!==boxId)return old;
 state.continuity??={version:1,anchors:[]};
 const anchor={scene,box:boxId,target:structuredClone(target),file:structuredClone(image.file),sha256:image.sha256,revision:(old?.revision??0)+1,
   ...(state.boxes[index].schedule?.place?{place:state.boxes[index].schedule.place}:{}),...(image.look!=null?{look:image.look}:{})};
 state.continuity.anchors=state.continuity.anchors.filter(a=>a.scene!==scene);state.continuity.anchors.push(anchor);return anchor;
}
export function selectSceneAnchor(state,boxId,anchor){
 validate(state,anchor.box,anchor.target,anchor);
 const index=state.boxes.findIndex(box=>box.id===boxId);if(index<0)throw Error('Scene anchor target was removed.');
 const scene=sceneStart(state,index),old=sceneAnchor(state,index);
 state.continuity??={version:1,anchors:[]};state.continuity.anchors=state.continuity.anchors.filter(a=>a.scene!==scene);
 state.continuity.anchors.push({...structuredClone(anchor),scene,revision:(old?.revision??0)+1});
}
const clean=text=>String(text??'').replace(/<d>[\s\S]*?(?:<\/d>|$)/gi,'').replace(/\[(?:Audio|Shot)[^\]]*\]/gi,'')
 .replace(/(?:overall_soundscape|non_diegetic_music):[\s\S]*/i,'').replace(/At \d+:\d+\.\d+,\s*/gi,'')
 .replace(/From \d+:\d+\.\d+ to \d+:\d+\.\d+:\s*/gi,'').replace(/<scenetrans>/gi,'').trim();
export function framePrompt(state,index,target,{base='',instruction='',extra=''}={}){
 const box=state.boxes[index];if(!box)throw Error('The still target box was removed.');
 const structured=box.source?.reply?.shots??[],shots=promptShots(box.prompt??'').shots;
 const number=target.kind==='last'?(structured.at(-1)?.number??shots.length??1):(target.shot??1);
 const shot=structured.find((s,i)=>(s.number??i+1)===number);
 const explicit=target.kind==='last'?shot?.ending_state:shot?.opening_state;
 if(explicit&&base)return base+'\n\nOne still image of this state. Preserve scene geometry and lighting; obey the requested viewpoint.';
 if(explicit)return [clean(shot.composition),clean(explicit),instruction,extra,'One still image of this state. Preserve scene geometry and lighting; obey the requested viewpoint.'].filter(Boolean).join('\n\n');
 let text=clean(base);
 if(!text){
   const selected=target.kind==='last'?shots.at(-1):shots.find((s,i)=>i+1===number);
   const visual=clean(selected?.value??box.prompt),moments=visual.split(/\b(?:then|finally)\b[, ]*/i).filter(s=>s.trim());
   text=[clean(state.prompt),target.kind==='last'?moments.at(-1):moments[0],instruction,extra].filter(Boolean).join('\n\n');
 }
 return text+(target.kind==='last'?'\n\nShow the completed final state of the selected action. Review this editable description when the Story has no explicit final state.':'');
}
