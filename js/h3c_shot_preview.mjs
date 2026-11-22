import { promptShots } from './h3c_prompt_sections.mjs?v=1f35473e5668';
import { isFresh, globalFrame, lookAt, assemblePrompt, referenceEnabled } from './h3c_timeline_model.mjs?v=1dfc1612e462';

import {framePrompt} from './h3c_still_scene.mjs?v=0906bb5de9d7';
import {preparedStillPrompt} from './h3c_still_prompt_preparation.mjs?v=9ea1bfd9b6b5';

const SHOT = /^\[Shot (\d+)\]$/i;
// Every edit and redraw reads the shots of every clip, and parsing a long prompt is slow; the text alone decides them.
const shotTimes = new Map();

function promptShotTimes(prompt) {
  let times = shotTimes.get(prompt);
  if (times) return times;
  const { shots: fields } = promptShots(prompt);
  const shots = fields.length ? fields : [{ label: '[Shot 1]', value: prompt }];
  times = shots.map((shot) => {
    const match = /^At (\d+):(\d+)\.(\d+),/i.exec(shot.value);
    return { number: Number(SHOT.exec(shot.label)[1]),
      generated: match ? Math.round((Number(match[1]) * 60 + Number(match[2]) + Number(match[3]) / 1000) * 24) : null };
  });
  if (shotTimes.size >= 500) shotTimes.clear();
  shotTimes.set(prompt, times);
  return times;
}

export function shotFrames(state, index, context) {
  const box = state.boxes[index];
  const carry = isFresh(state, index) ? 0 : context;
  const last = box.frames - (carry ? 0 : 1);
  return promptShotTimes(box.prompt).map(({ number, generated }) => {
    const frame = number === 1 ? 0 : generated != null ? Math.max(0, generated - (carry ? carry - 1 : 0)) : null;
    return { shot: number, frame: frame != null && frame <= last ? frame : null };
  });
}

function targetFrames(state, index, context) {
  const box = state.boxes[index];
  const last = box.frames - (isFresh(state, index) ? 1 : 0);
  const shots = shotFrames(state, index, context);
  return [{target:{kind:'first'}, frame:0},
    ...shots.filter(s => s.shot !== 1 && s.frame != null && shots.filter(p => p.shot === s.shot).length === 1)
      .map(s => ({target:{kind:'shot',shot:s.shot},frame:s.frame})),
    {target:{kind:'last'},frame:last}];
}

export function frameTargets(state, index, context) {
  return targetFrames(state, index, context).filter(p => p.target.kind !== 'last' || p.frame !== 0)
    .map(p => ({...p,movieFrame:globalFrame(state,index,p.frame)}));
}

// Match the server: explicit targets follow current timing; legacy guides retain their saved frame.
export function acceptedGuideFrames(state, index, context) {
  const targets = targetFrames(state, index, context);
  return (state.boxes[index].previews ?? []).filter(p => p.guide).map(p => {
    if (!p.target) return p.frame;
    const target = p.target.kind === 'shot' && p.target.shot === 1 ? {kind:'first'} : p.target;
    return targets.find(item => item.target.kind === target.kind && item.target.shot === target.shot)?.frame;
  }).filter(Number.isInteger);
}

// The accepted guide that sits on a clip's First or Last frame, whether it is saved against that marker or as a free
// "Frame guide" at the same frame (the renderer reads both the same way). Returns {preview, guide} or null.
export function endpointGuide(state, index, context, kind) {
  const targets = targetFrames(state, index, context);
  const frame = (kind === 'last' ? targets.at(-1) : targets[0])?.frame;
  if (frame == null) return null;
  const owned = (state.boxes[index].previews ?? []).filter(p => p.guide);
  const resolved = p => {
    if (!p.target) return p.frame;
    const target = p.target.kind === 'shot' && p.target.shot === 1 ? {kind: 'first'} : p.target;
    return targets.find(item => item.target.kind === target.kind && item.target.shot === target.shot)?.frame;
  };
  const matches = owned.filter(p => resolved(p) === frame);
  const preview = matches.find(p => p.target) ?? matches[0];
  return preview ? {preview, guide: preview.guide} : null;
}

// Settings endpoints are reference slots, separate from generated/uploaded still guides.
export function endpointReference(state, index, kind, images) {
  if (!['first','last'].includes(kind) || (kind === 'first' && !isFresh(state,index))) return null;
  const slot = state.boxes[index]?.[kind];
  if (!slot || !referenceEnabled(state,slot)) return null;
  return images.find(ref => ref.name === slot && !ref.refmod && !ref.problem && (ref.preview || ref.mediaFile)) ?? null;
}

// Free "Frame guide" stills on a clip's first or last frame become its First and Last stills, so converting to FLF2VA
// leaves one image per endpoint instead of the same picture twice. An endpoint that already owns a guide is left alone.
export function adoptEndpointGuides(state, index, context) {
  const box = state.boxes[index];
  const targets = targetFrames(state, index, context);
  const ends = [['first', targets[0].frame], ['last', targets.at(-1).frame]].filter(([kind, frame]) => kind === 'first' || frame !== 0);
  let changed = false;
  for (const [kind, frame] of ends) {
    const free = (box.previews ?? []).find(p => !p.target && p.guide && p.frame === frame);
    if (!free) continue;
    const owner = box.previews.find(p => p.target && (p.target.kind === kind || (kind === 'first' && p.target.kind === 'shot' && p.target.shot === 1)));
    if (owner?.guide) continue;
    if (owner) {
      owner.guide = free.guide; owner.frame = frame;
      if (free.images?.length) owner.images = [...(owner.images ?? []), ...free.images];
      box.previews = box.previews.filter(p => p !== free);
    } else {
      delete free.shot;
      free.target = {kind}; free.frame = frame;
    }
    changed = true;
  }
  return changed;
}

export function syncTargets(state, context) {
  state.boxes.forEach((box,index) => {
    const targets = targetFrames(state,index,context);
    for (const item of box.previews ?? []) {
      if (!item.target) continue;
      if (item.target.kind === 'shot' && item.target.shot === 1) item.target = {kind:'first'};
      const resolved = targets.find(p => p.target.kind === item.target.kind && p.target.shot === item.target.shot);
      if (resolved) item.frame = resolved.frame;
    }
  });
}

const canonicalTarget = target => target?.kind === 'shot' && target.shot === 1 ? {kind:'first'} : target;
const sameTarget = (a,b) => a?.kind === b?.kind && a?.shot === b?.shot;
const sameFile = (a,b) => !!a && !!b && ['filename','subfolder','type','v','sha256'].every(key => a[key] === b[key]);
const previewTarget = item => item.target ?? (item.shot === 1 ? {kind:'first'} : {kind:'shot',shot:item.shot});

function legacyStillPrompt(state, index, target, {instruction = '', extra = '', references = []} = {}) {
  target = canonicalTarget(target);
  const box = state.boxes[index];
  const {shots, sections, style} = promptShots(box.prompt);
  const selected = target.kind === 'last' ? shots.at(-1) : shots.find(s => Number(SHOT.exec(s.label)?.[1]) === (target.shot ?? 1));
  const visualText = source => (source ?? '')
    .replace(/<d>[\s\S]*?(?:<\/d>|$)/g, '')
    .split(/(?:overall_soundscape|non_diegetic_music):/)[0]
    .replace(/^At \d+:\d+\.\d+,\s*/i, '')
    .replace(/(?:Dialogue delivery|Soundscape|Duration):[^.\n]*(?:\.|$)/gi, '').trim();
  let visual = visualText(selected?.value ?? (!shots.length ? box.prompt : ''));
  const structured=box.source?.reply?.shots??[];
  const number=target.kind==='last'?(structured.at(-1)?.number??structured.length):(target.shot??1);
  const shot=structured.find((item,at)=>(item.number??at+1)===number);
  const explicit=target.kind==='last'?shot?.ending_state:shot?.opening_state;
  if(explicit)visual=[visualText(shot.composition),visualText(explicit)].filter(Boolean).join('\n');
  const moments = visual.split(/\b(?:then|finally)\b[, ]*/i).filter(s => s.trim());
  visual = (target.kind === 'last' ? moments.at(-1) : moments[0])?.trim() ?? '';
  const shared = promptShots(state.prompt ?? '');
  visual = assemblePrompt({...state, prompt:visualText(shared.shots.length || shared.sections ? shared.style : state.prompt),
    boxes:state.boxes.map((item, at) => at === index ? {...box,prompt:[visualText(style),visual].filter(Boolean).join('\n\n')} : item)},index);
  const definitions = sections?.find(s => s.key === 'subject_definitions')?.fields ?? [];
  const owned = definitions.filter(field => visual.includes(field.label));
  const slots = new Set([...`${visual}\n${owned.map(field => field.value).join('\n')}`.matchAll(/@image[1-9]\d*\b/g)].map(m => m[0].slice(1)));
  const descriptions = [...slots].map(slot => {
    const ref = references.find(ref => ref.name === slot);
    const replacement = state.reference_replacements?.[slot]?.source ?? slot;
    const description = state.reference_descriptions?.[replacement]?.text ?? ref?.description ?? '';
    return description ? `@${slot}: ${description}` : '';
  });
  for (const entity of state.bible?.entities ?? []) {
    const chosen = lookAt(entity,state.boxes,index), look = chosen ? entity.looks[chosen-1] : null;
    const pictureLooks = (entity.looks ?? []).filter(item => item.pictures?.length);
    const pictureLook = lookAt({looks:pictureLooks},state.boxes,index);
    const pictures = pictureLook ? pictureLooks[pictureLook-1].pictures : entity.pictures ?? [];
    if (!pictures.some(slot => slots.has(slot))) continue;
    if (look?.description ?? entity.description) descriptions.push(`${entity.name}: ${look?.description ?? entity.description}`);
  }
  return [...owned.map(field => `${field.label} ${field.value}`), ...descriptions,
    visual, `Capture a single frame at the ${target.kind === 'last' ? 'ending' : 'opening'} moment of this scene action.`, instruction, extra].filter(Boolean).join('\n\n');
}

// Project renderer-neutral Story source into one visible state. Motion/audio stay in source for video import.
function pixelStillPrompt(state,index,target,{instruction='',extra='',referenceLabel,sourcePrompt}={}) {
  target=canonicalTarget(target);const box=state.boxes[index],current=sourcePrompt===box.prompt;
  const reply=current?box.source?.reply??{}:{},source=current?box.source?.frame??{}:{};
  const parsed=promptShots(box.prompt??''),shots=reply.shots??[];
  const number=target.kind==='last'?(shots.at(-1)?.number??shots.length):target.shot??1;
  const shot=shots.find((s,i)=>(s.number??i+1)===number);
  const visual=text=>String(text??'').replace(/<d>[\s\S]*?(?:<\/d>|$)/gi,'')
    .replace(/(?:overall_soundscape|non_diegetic_music):[\s\S]*/i,'')
    .replace(/^(?:summary|subject_definitions|shots):[^\n]*(?:\n|$)/gim,'')
    .replace(/At \d+:\d+\.\d+,\s*/gi,'').replace(/From \d+:\d+\.\d+ to \d+:\d+\.\d+:\s*/gi,'')
    .replace(/<scenetrans>/gi,'').replace(/\[(?:Shot|Audio)[^\]]*\]/gi,'').trim();
  const entities=state.bible?.entities??[],wording=source.wording??{},bindings=new Map(),descriptions=[];
  for(const id of new Set([...(source.schedule?.entities??[]),source.schedule?.place,...(shot?.subjects??[]),...Object.keys(wording)].filter(Boolean))) {
    const entity=entities.find(e=>e.id===id),look=entity&&lookAt(entity,state.boxes,index);
    const text=wording[id]??(look?entity.looks[look-1].description:entity?.description)??'';
    const pictures=[...String(text).matchAll(/@image[1-9]\d*\b/g)].map(m=>m[0]);
    const pictureLooks=(entity?.looks??[]).filter(item=>item.pictures?.length),chosenPicture=entity&&lookAt({looks:pictureLooks},state.boxes,index);
    const entityPictures=chosenPicture?pictureLooks[chosenPicture-1].pictures:entity?.pictures??[];
    const refs=pictures.length?pictures:entityPictures.map(slot=>'@'+slot);
    const noun=entity?.kind==='place'?'scene':entity?.kind==='prop'?'object':'subject';
    bindings.set(id,refs.length?`the ${noun} from ${refs.join(' and ')}`:entity?.name??text??id);
    if(!refs.length&&text)descriptions.push(`${entity?.name??id}: ${visual(text)}`);
  }
  const definitions=parsed.sections?.find(s=>s.key==='subject_definitions')?.fields??[];
  for(const field of definitions) {
    const refs=[...field.value.matchAll(/@image[1-9]\d*\b/g)].map(m=>m[0]);
    bindings.set(field.label,refs.length?`the subject from ${refs.join(' and ')}`:visual(field.value.replace(/^is\s+/i,'')));
    if(referenceLabel==='<Picture {index}>'&&/^(?:<(?:Subject|Picture) |@image)/.test(field.label))
      descriptions.push(visual(field.value.replace(/^is\s+/i,'')));
  }
  const words=text=>visual(text).replace(/<Subject [1-9]\d*>|\b(?:e|subject_)[1-9]\d*\b/g,m=>bindings.get(m)??m);
  let stateText;
  if(target.kind==='last')stateText=shot?.ending_state??Object.values(reply.terminal_state??{}).filter(v=>typeof v==='string').join(' ');
  else stateText=shot?.opening_state??shot?.composition;
  // Imported video prose needs the explicit still converter; splitting a motion sequence cannot infer its pose.
  if(!stateText&&parsed.sections&&referenceLabel==='<Picture {index}>')return '';
  if(!stateText) {
    const selected=target.kind==='last'?parsed.shots.at(-1):parsed.shots.find(s=>Number(SHOT.exec(s.label)?.[1])===number);
    const moments=visual(selected?.value??box.prompt).split(/\b(?:then|finally)\b[, ]*/i).filter(s=>s.trim());
    stateText=(target.kind==='last'?moments.at(-1):moments[0])??'';
  }
  const shared=promptShots(state.prompt??'');
  let text=[words(shared.sections?shared.style:state.prompt),words(referenceLabel==='<Picture {index}>'?parsed.style:''),words(state.bible?.style?.look??reply.style),...descriptions,
    words(shot?.viewpoint),words(stateText),visual(instruction),visual(extra),'Create one still image of this visible state.'].filter(Boolean).join('\n\n');
  if(referenceLabel==='<image{index}>')text=text.replace(/@image([1-9]\d*)\b/g,'<image$1>');
  return text;
}
export function buildStillPrompt(state,index,target,options={}) {
  const prepared=preparedStillPrompt(state,state.boxes[index].id,target);
  if(prepared)return prepared.prompt;
  return options.adapter==='pixels'?pixelStillPrompt(state,index,target,options)
    :framePrompt(state,index,target,{...options,base:legacyStillPrompt(state,index,target,options)});
}

export function applyFrameGuide(state, boxId, target, file, {context = 39, boundary} = {}) {
  target = canonicalTarget(target);
  const index = state.boxes.findIndex(box => box.id === boxId);
  if (index < 0) throw new Error('The target clip was removed.');
  const physicalTarget = (at, value) => {
    value = canonicalTarget(value);
    return value?.kind === 'last' && targetFrames(state,at,context).at(-1).frame === 0 ? {kind:'first'} : value;
  };
  target = physicalTarget(index,target);
  const resolved = frameTargets(state,index,context).find(item => sameTarget(item.target,target));
  if (!resolved) throw new Error('This target was removed or its timing is unreadable.');
  if (!file?.filename) throw new Error('Choose an imported PNG.');
  const box = state.boxes[index], previous = state.boxes[index - 1];
  if (boundary?.reuseEnding) {
    const ending = boundary.ending;
    if (target.kind !== 'first' || !previous || boundary.a !== previous.id || boundary.b !== box.id
      || ending?.box !== previous.id || !ending.take || !ending.created || !sameFile(file,ending.file))
      throw new Error('The saved ending provenance changed. Choose the current predecessor ending again.');
    box.cut = false;
    delete box.new_scene;
    delete box.first;
    if (box.join) box.join.kind = 'continue';
    for (const item of box.previews ?? []) if (sameTarget(canonicalTarget(previewTarget(item)),target)) delete item.guide;
    return {changedBoxIds:[box.id]};
  }
  // Resolve collisions before writing anything; distinct Shot labels can own the same moment.
  const assertAvailable = (at, selectedTarget, frame) => {
    const targets = frameTargets(state,at,context);
    for (const item of state.boxes[at].previews ?? []) {
      const owner = physicalTarget(at,previewTarget(item));
      const ownedFrame = targets.find(p => sameTarget(p.target,owner))?.frame;
      if (item.guide && ownedFrame === frame && !sameTarget(owner,selectedTarget) && !sameFile(item.guide,file))
        throw new Error('Conflicting guide ownership at this frame. Remove the other accepted guide first.');
    }
  };
  assertAvailable(index,target,resolved.frame);
  const opening = target.kind === 'first' && index > 0 && !box.cut;
  const next=state.boxes[index+1];
  const ending=target.kind==='last'&&next&&!next.cut;
  const pair=opening||ending;
  const left=opening?index-1:index,right=opening?index:index+1;
  if (pair && (boundary?.a !== state.boxes[left].id || boundary?.b !== state.boxes[right].id
    || typeof boundary.renderedA !== 'boolean' || typeof boundary.renderedB !== 'boolean'))
    throw new Error('The continuation boundary changed. Read its saved takes again.');
  const paired = pair && !boundary.renderedA && !boundary.renderedB;
  const otherIndex=opening?left:right;
  const other=paired?frameTargets(state,otherIndex,context).at(opening?-1:0):null;
  if (paired) assertAvailable(otherIndex,other.target,other.frame);
  const assign = (at, selectedTarget, frame) => {
    const owner = state.boxes[at];
    owner.previews ??= [];
    const aliases = owner.previews.filter(item => sameTarget(physicalTarget(at,previewTarget(item)),selectedTarget));
    const item = Object.assign({}, ...aliases.toReversed());
    const images = aliases.flatMap(alias => alias.images ?? []);
    if (images.length) item.images = images;
    delete item.shot;
    item.target = structuredClone(selectedTarget);item.frame = frame;item.guide = structuredClone(file);
    const position = aliases.length ? owner.previews.indexOf(aliases[0]) : owner.previews.length;
    owner.previews = owner.previews.filter(item => !aliases.includes(item));
    const placed = structuredClone(item);
    owner.previews.splice(position,0,placed);
    // A free "Frame guide" on this very frame would give the clip two guides at one frame, which the renderer rejects.
    // The guide just accepted takes the frame over; the free one keeps only its candidates, if it has any.
    owner.previews = owner.previews.filter(other => {
      if (other === placed || other.target || !other.guide || other.frame !== frame) return true;
      delete other.guide;
      return !!other.images?.length;
    });
  };
  if (opening && !paired) box.cut = true;
  assign(index,target,resolved.frame);
  if (paired) assign(otherIndex,other.target,other.frame);
  return {changedBoxIds:paired ? [state.boxes[left].id,state.boxes[right].id] : [box.id]};
}
