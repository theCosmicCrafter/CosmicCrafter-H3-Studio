import {promptSections,replacePromptRanges} from './h3c_prompt_sections.mjs?v=1f35473e5668';
import {withoutDialogue,readPromptFields,writePromptField} from './h3c_prompt_fields.mjs?v=5cd5e5206375';
import {FPS,isFresh,playedFrames} from './h3c_timeline_model.mjs?v=1dfc1612e462';
import {layerView} from './h3c_layers.mjs?v=1dfc1612e462';
import {acceptedGuideFrames,frameTargets} from './h3c_shot_preview.mjs?v=1dfc1612e462';

export const promptClock=ms=>{
  ms=Math.round(ms);return `${String(Math.floor(ms/60000)).padStart(2,'0')}:${String(Math.floor(ms/1000)%60).padStart(2,'0')}.${String(ms%1000).padStart(3,'0')}`;
};
const clockPrefix=/^At (\d+):([0-5]\d)\.(\d{3}),\s*/i;
const cutPrefix=/^(?:the camera cuts to|the shot (?:cuts|transitions|changes|switches) to)\s+/i;
const continuePrefix=/^the view continues without a cut\.\s*/i;
const milliseconds=body=>{const m=clockPrefix.exec(body);return m?(Number(m[1])*60+Number(m[2]))*1000+Number(m[3]):null;};

export function shotSpans(source) {
  const parsed=promptSections(source),scene=parsed?.find(s=>['integrated_multimodal_description','detailed_description'].includes(s.key));
  if(parsed&&!scene)return [];
  const start=scene?.bodyStart??0,end=scene?.end??source.length;
  const masked=withoutDialogue(source);
  const markers=[...masked.slice(start,end).matchAll(/^[ \t]*(\[Shot ([1-9]\d*)\])(?=\s|$)/gm)];
  return markers.map((m,i)=>{
    const at=start+m.index+m[0].indexOf(m[1]),limit=start+(markers[i+1]?.index??end-start);
    const bodyStart=at+m[1].length+source.slice(at+m[1].length,limit).match(/^\s*/)[0].length;
    const finish=source.slice(0,limit).trimEnd().length;
    return {number:Number(m[2]),start:at,end:finish,bodyStart,body:source.slice(bodyStart,finish),before:source.slice(at,finish)};
  });
}

export function shotTiming(state,index,context,videoId=null) {
  const view=videoId?layerView(state,index,videoId):state,box=view.boxes[index];
  const carry=isFresh(view,index)?0:context,duration=playedFrames(box.frames,box.exact,isFresh(view,index))/FPS;
  return {duration,carry,shots:shotSpans(box.prompt).map((span,i)=>{
    const nativeMs=i?milliseconds(span.body):0;
    const seconds=i&&nativeMs!==null?Math.round((nativeMs/1000-carry/FPS)*1000)/1000:0;
    const body=span.body.replace(clockPrefix,'');
    return {...span,nativeMs,seconds:i&&nativeMs===null?null:seconds,
      cut:cutPrefix.test(body)?true:continuePrefix.test(body)?false:null,
      editable:i>0&&nativeMs!==null&&seconds>=0,problem:i&&nativeMs===null?'This shot needs a start time.':i&&seconds<0?'This stage is inside replay; edit it in Existing text.':''};
  })};
}

export function editPromptShot(state,index,change,context,videoId=null) {
  const trial=structuredClone(state),view=videoId?layerView(trial,index,videoId):trial;
  const box=view.boxes[index],target=videoId?trial.boxes[index].layers?.find(v=>v.id===videoId):trial.boxes[index];
  if(!target)throw new Error('The selected video no longer exists.');
  const timing=shotTiming(trial,index,context,videoId),shots=timing.shots,source=box.prompt;
  if(new Set(shots.map(s=>s.number)).size!==shots.length)throw new Error('Resolve duplicate shot numbers in Existing text first.');
  const at=shots.findIndex(s=>s.number===change.shot),shot=shots[at];
  const beforeGuides=acceptedGuideFrames(view,index,context);
  let next=source;
  if(change.kind==='set-start'||change.kind==='append') {
    const seconds=change.seconds;
    if(typeof seconds!=='number'||!Number.isFinite(seconds)||seconds<0||seconds>=timing.duration)throw new Error(`Enter seconds inside this clip (before ${timing.duration} s).`);
    if(change.kind==='set-start'&&(at<=0||shot.seconds<0))throw new Error('Shot 1 has no timestamp; replay stages stay in Existing text.');
    const nativeMs=Math.round((seconds+timing.carry/FPS)*1000),frame=Math.round(nativeMs*FPS/1000);
    const previous=change.kind==='append'?shots.at(-1):shots[at-1],following=change.kind==='append'?null:shots[at+1];
    if((previous&&(previous.nativeMs===null||nativeMs<=previous.nativeMs||frame<=Math.round(previous.nativeMs*FPS/1000)))
      ||(!previous&&seconds!==0)||following?.nativeMs!=null&&(nativeMs>=following.nativeMs||frame>=Math.round(following.nativeMs*FPS/1000)))
      throw new Error('Shot starts must increase and stay between their neighbours, on distinct video frames.');
    if(change.kind==='set-start') {
      const prefix=clockPrefix.exec(shot.body);
      const body=`At ${promptClock(nativeMs)}, `+shot.body.slice(prefix?.[0].length??0);
      next=replacePromptRanges(source,[{start:shot.bodyStart,end:shot.end,before:shot.body,text:body}]);
    } else {
      const number=Math.max(0,...shots.map(s=>s.number))+1;
      const opening=number>1?`At ${promptClock(nativeMs)}, `:'';
      const transition=change.cut===true?'the camera cuts to a new shot. ':change.cut===false?'the view continues without a cut. ':'';
      const text=`[Shot ${number}] ${opening}${transition}${change.text??''}`.trimEnd();
      const section=promptSections(source)?.find(s=>['integrated_multimodal_description','detailed_description'].includes(s.key));
      const end=section?.end??source.length,insert=source.slice(0,end).trimEnd().length;
      next=replacePromptRanges(source,[{start:insert,end:insert,before:'',text:(insert?'\n':'')+text}]);
    }
  } else if(change.kind==='set-cut') {
    if(at<=0)throw new Error('Choose a shot after Shot 1.');
    const clock=clockPrefix.exec(shot.body),body=shot.body.slice(clock?.[0].length??0);
    const prefix=cutPrefix.exec(body)??continuePrefix.exec(body);
    if(!clock||!prefix)throw new Error('Edit this custom transition wording in the shot description first.');
    const text=clock[0]+(change.cut?'the camera cuts to a new shot. ':'the view continues without a cut. ')+body.slice(prefix[0].length);
    next=replacePromptRanges(source,[{start:shot.bodyStart,end:shot.end,before:shot.body,text}]);
  } else if(change.kind==='remove') {
    if(!shot)throw new Error('Choose an existing shot.');
    const retention=readPromptFields(source).sections.find(s=>s.key==='retention_analysis')?.entries??[];
    let unknown=withoutDialogue(source).split('');
    const hide=(start,end)=>{for(let p=start;p<end;p++)unknown[p]=' ';};
    for(const s of shots)hide(s.start,s.bodyStart);
    for(const entry of retention.filter(e=>e.kind==='retention')){
      const colon=entry.range.before.indexOf(':');hide(entry.range.start,entry.range.start+colon+1);
    }
    if([...unknown.join('').matchAll(/\[Shot (\d+)\]/g)].some(m=>Number(m[1])>=change.shot))throw new Error('An unstructured shot reference would become ambiguous. Edit that reference first.');
    const mapping=new Map(shots.filter(s=>s.number!==change.shot).map((s,i)=>[s.number,i+1]));
    const patches=shots.flatMap(s=>{
      if(s===shot)return {start:s.start,end:s.end,before:s.before,text:''};
      const number=mapping.get(s.number);if(number===s.number)return [];
      const body=number===1?s.body.replace(clockPrefix,''):s.body;
      const gap=s.before.slice(`[Shot ${s.number}]`.length,s.bodyStart-s.start);
      return {start:s.start,end:s.end,before:s.before,text:`[Shot ${number}]${gap}${body}`};
    });
    next=replacePromptRanges(source,patches);
    for(let i=0;i<retention.length;i++) {
      if(retention[i].kind!=='retention')continue;
      const entry=readPromptFields(next).sections.find(s=>s.key==='retention_analysis').entries[i];
      next=writePromptField(next,{expectedSource:next,section:'retention_analysis',kind:'retention',entry,
        value:{...entry.value,shots:entry.value.shots.filter(n=>mapping.has(n)).map(n=>mapping.get(n))}});
    }
    target.previews=(target.previews??[]).filter(p=>!(p.target?.kind==='shot'&&p.target.shot===change.shot||p.shot===change.shot)).map(p=>{
      if(p.target?.kind==='shot'&&mapping.has(p.target.shot))p.target=mapping.get(p.target.shot)===1?{kind:'first'}:{kind:'shot',shot:mapping.get(p.target.shot)};
      if(mapping.has(p.shot))p.shot=mapping.get(p.shot);
      return p;
    });
  } else throw new Error('Unknown shot edit.');
  target.prompt=next;
  const afterView=videoId?layerView(trial,index,videoId):trial;
  if(JSON.stringify(beforeGuides)!==JSON.stringify(acceptedGuideFrames(afterView,index,context)))throw new Error('An accepted guide would move or be removed. Remove or reassign that guide first.');
  const targets=frameTargets(afterView,index,context);
  for(const p of target.previews??[])if(p.target){const current=targets.find(t=>t.target.kind===p.target.kind&&t.target.shot===p.target.shot);if(current)p.frame=current.frame;}
  return trial;
}
