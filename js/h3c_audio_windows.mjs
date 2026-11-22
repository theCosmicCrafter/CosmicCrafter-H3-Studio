// Mirrors audio_windows.py; source ownership never depends on current box order.
export const AUDIO_WINDOWS_FEATURE = 'box-audio-windows-1';
const keys = ['start', 'source_start', 'duration'];
const placement = clip => Object.fromEntries(keys.map(key => [key, clip[key]]));
const stable = value => JSON.stringify(value, (_, item) => item && typeof item === 'object' && !Array.isArray(item)
  ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => a.localeCompare(b))) : item);

export function validateWindows(clip, boxes, origin) {
  if (!Object.hasOwn(clip, 'box_windows')) return;
  const saved = clip.box_windows;
  if (!saved || typeof saved !== 'object' || saved.version !== 1) throw Error('Unsupported audio windows version.');
  if (stable(saved.source) !== stable(origin) || stable(saved.placement) !== stable(placement(clip))) {
    throw Error('Unlock audio windows before changing the source or placement.');
  }
  if (!saved.by_box || typeof saved.by_box !== 'object' || Array.isArray(saved.by_box)) throw Error('Audio windows need a box mapping.');
  const ids = new Set(boxes.map(box => box.id));
  for (const [id, window] of Object.entries(saved.by_box)) {
    if (!ids.has(id) || !window || typeof window !== 'object') throw Error('Audio window refers to an unknown box.');
    for (const key of ['offset', 'source_start', 'duration']) {
      if (typeof window[key] !== 'number' || !Number.isFinite(window[key]) || window[key] < 0 || (key === 'duration' && window[key] === 0)) {
        throw Error('Audio windows need finite nonnegative times and positive durations.');
      }
    }
    if (window.source_start < clip.source_start - 1e-9 || window.source_start + window.duration > clip.source_start + clip.duration + 1e-9) {
      throw Error('Audio window is outside its captured source selection.');
    }
  }
}

export function captureWindows(clip, boxes, origin) {
  const bindings = [];
  for (const box of boxes) {
    const first = Math.max(box.start, clip.start), last = Math.min(box.start + box.duration, clip.start + clip.duration);
    if (last > first) bindings.push([box.id,{offset:first-box.start, source_start:clip.source_start+first-clip.start, duration:last-first}]);
  }
  return {version:1, source:structuredClone(origin), placement:placement(clip), by_box:Object.fromEntries(bindings)};
}

export function resolveWindows(clip, boxes) {
  if (!Object.hasOwn(clip, 'box_windows')) return [{box:null, offset:0, ...placement(clip)}];
  return boxes.flatMap(box => {
    const window = Object.hasOwn(clip.box_windows.by_box, box.id) ? clip.box_windows.by_box[box.id] : null;
    if (!window) return [];
    const duration = Math.min(window.duration, box.duration-window.offset);
    return duration > 0 ? [{box:box.id, ...window, start:box.start+window.offset, duration}] : [];
  });
}

export function pruneWindows(state) {
  const ids = new Set(state.boxes.map(box => box.id));
  for (const clip of state.audio_clips ?? []) if (clip.box_windows) {
    clip.box_windows.by_box = Object.fromEntries(Object.entries(clip.box_windows.by_box).filter(([id]) => ids.has(id)));
  }
}

export function splitWindows(state, oldId, leftId, rightId, cutSeconds) {
  for (const clip of state.audio_clips ?? []) {
    const map = clip.box_windows?.by_box;
    if (!map || !Object.hasOwn(map, oldId)) continue;
    const window = map[oldId], trim = Math.max(0, cutSeconds-window.offset);
    const left = Math.min(window.duration, trim), right = window.duration-trim;
    delete map[oldId];
    clip.box_windows.by_box = {...map,
      ...(leftId && left > 0 ? {[leftId]:{...window, duration:left}} : {}),
      ...(rightId && right > 0 ? {[rightId]:{offset:Math.max(0,window.offset-cutSeconds), source_start:window.source_start+trim, duration:right}} : {})};
  }
}

export function unlockWindows(clip) {
  if (!clip.box_windows) return;
  Object.assign(clip, clip.box_windows.placement);
  delete clip.box_windows;
}

export function coalesceWindows(windows) {
  const result = [];
  for (const window of [...windows].sort((a,b)=>a.start-b.start)) {
    const last = result.at(-1);
    if (last && last.slot === window.slot && ['start','source_start'].every(key=>Math.abs(last[key]+last.duration-window[key])<1e-9)) last.duration += window.duration;
    else result.push({...window});
  }
  return result;
}

export function outputWindows(clip, windows, parts) {
  const total=parts.reduce((n,p)=>n+p.frames,0)/24;
  if (!Object.hasOwn(clip,'box_windows') && !Object.hasOwn(clip,'windows')) {
    let movie=0,output=0,shift=0;
    for(const part of parts) {
      if(part.coverage.length) { if(movie<=clip.start)shift=output-movie; movie+=part.frames/24; }
      output+=part.frames/24;
    }
    const start=clip.start+shift,duration=Math.min(clip.duration,total-start);
    return clip.start<movie && duration>0 ? [{box:null,offset:0,start,source_start:clip.source_start,duration}] : [];
  }
  const result=[];let output=0;
  for(const part of parts) {
    let cursor=0;
    for(const cover of part.coverage) {
      const first=cover.first/24,last=(cover.first+cover.frames)/24;
      for(const window of windows) {
        if(window.box!==cover.box)continue;
        const left=Math.max(first,window.offset),right=Math.min(last,window.offset+window.duration);
        if(right>left)result.push({box:window.box,offset:left,start:output+cursor/24+left-first,source_start:window.source_start+left-window.offset,duration:right-left});
      }
      cursor+=cover.frames;
    }
    output+=part.frames/24;
  }
  return result;
}

export function equivalentWindows(left,right) {
  left=coalesceWindows(left);right=coalesceWindows(right);
  return left.length===right.length && left.every((a,i)=>keys.every(key=>Math.abs(a[key]-right[i][key])<1e-9));
}

export function timelineAudioParts(state) {
  return state.boxes.flatMap((box,index)=>{
    const bridge=index>0 && box.cut ? (state.bridges??[]).find(b=>b.before===box.id && b.mode!=='replace') : null;
    return [...(bridge?[{frames:bridge.frames,coverage:[]}]:[]),{frames:box.frames,coverage:[{box:box.id,first:0,frames:box.frames}]}];
  });
}

export function sourceOrigin(state, clip) {
  let slot=clip.slot;const seen=new Set();
  while(state.reference_replacements?.[slot]) {
    if(seen.has(slot))throw Error('Audio replacement cycle.');seen.add(slot);
    const replacement=state.reference_replacements[slot];
    if(replacement.file)return {file:structuredClone(replacement.file)};
    slot=replacement.source;
  }
  const file=(state.audio_clips??[]).find(c=>c.slot===slot)?.file;
  return file?{file:structuredClone(file)}:{source:slot};
}

export function audioSourceLocked(state, slot) {
  return (state.audio_clips??[]).some(clip=>{
    if(!clip.box_windows)return false;
    let name=clip.slot;const seen=new Set();
    while(!seen.has(name)) {
      if(name===slot)return true;seen.add(name);
      const source=state.reference_replacements?.[name]?.source;
      if(!source)return false;name=source;
    }
    return false;
  });
}

export function lockEligibility(state, clip) {
  if(!state.boxes.length)return {ok:false,conflicts:['Add boxes before locking their audio ranges.']};
  const parts=timelineAudioParts(state);let start=0;
  const boxes=state.boxes.map(box=>{const span={id:box.id,start,duration:box.frames/24};start+=span.duration;return span;});
  const candidate={...clip,box_windows:captureWindows(clip,boxes,sourceOrigin(state,clip))};
  const conflicts=[];
  if(clip.in_full_video && !equivalentWindows(outputWindows(clip,resolveWindows(clip,boxes),parts),outputWindows(candidate,resolveWindows(candidate,boxes),parts))) {
    for(let index=1;index<state.boxes.length;index++)if((state.bridges??[]).some(b=>b.before===state.boxes[index].id && b.mode!=='replace')) {
      conflicts.push(`Resolve the inserted bridge before box ${index+1} before locking: locking would change this soundtrack's playback.`);
    }
  }
  return {ok:!conflicts.length,conflicts};
}
