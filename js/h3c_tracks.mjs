// Independent typed tracks. This module has no model/DOM dependencies: frame lengths are supplied by callers.
export const FEATURE = 'timeline-tracks-1';
export const TYPES = ['video', 'audio', 'text'];
export const enabled = state => Object.hasOwn(state, 'tracks');
const fail = message => { throw new Error(`Timeline tracks: ${message}`); };
const list = value => Array.isArray(value) ? value : fail('expected a list');
const length = box => box.frames;

export function placements(state, duration = length) {
  let cursor = 0;
  return state.boxes.map((box, index) => {
    const start = enabled(state) ? box.start : cursor, count = duration(box, index);
    cursor = start + count;
    return {id: box.id, track: box.track ?? 'legacy', start, end: start + count};
  });
}
export const durationFrames = (state, duration) => Math.max(0, ...placements(state, duration).map(p => p.end));
export const startFrame = (state, id) => placements(state).find(p=>p.id===id)?.start ?? 0;
export function trackIndices(state,index) {
  if (!enabled(state)) return state.boxes.map((_,i)=>i);
  return state.boxes.map((_,i)=>i).filter(i=>state.boxes[i].track===state.boxes[index].track).sort((a,b)=>state.boxes[a].start-state.boxes[b].start);
}
export function previousIndex(state,index,adjacent=true) {
  if (!enabled(state)) return index ? index-1 : null;
  const indices=trackIndices(state,index), position=indices.indexOf(index), before=indices[position-1];
  return position>0 && (!adjacent || state.boxes[before].start+state.boxes[before].frames===state.boxes[index].start) ? before : null;
}
export function followingIndex(state,index) {
  if (!enabled(state)) return index+1<state.boxes.length ? index+1 : null;
  const indices=trackIndices(state,index), after=indices[indices.indexOf(index)+1];
  return after!==undefined && state.boxes[index].start+state.boxes[index].frames===state.boxes[after].start ? after : null;
}
export function outputSpans(state) {
  const events=(state.bridges??[]).filter(b=>b.mode!=='replace').map(b=>({at:startFrame(state,b.before),frames:b.frames,id:b.before})).sort((a,b)=>a.at-b.at);
  const result=[]; let frame=0, output=0;
  for (const event of events) {
    if (event.at>frame) { result.push({start:frame,end:event.at,outputStart:output,outputEnd:output+event.at-frame,bridgeId:null}); output+=event.at-frame; }
    result.push({start:event.at,end:event.at,outputStart:output,outputEnd:output+event.frames,bridgeId:event.id});
    output+=event.frames; frame=event.at;
  }
  const end=durationFrames(state);
  if (end>frame) result.push({start:frame,end,outputStart:output,outputEnd:output+end-frame,bridgeId:null});
  return result;
}
export function outputFrame(state, frame) {
  return frame+outputSpans(state).filter(s=>s.bridgeId && s.start<=frame).reduce((n,s)=>n+s.outputEnd-s.outputStart,0);
}
export function timelineFrame(state, frame) {
  const spans=outputSpans(state), span=spans.find(s=>frame>=s.outputStart&&frame<s.outputEnd);
  return span ? {frame:span.start+(span.bridgeId?0:frame-span.outputStart),bridgeId:span.bridgeId} : {frame:durationFrames(state),bridgeId:null};
}
export function predecessor(state, id, duration) {
  const spans = placements(state, duration), at = spans.find(p => p.id === id);
  return at ? spans.find(p => p.id !== id && p.track === at.track && p.end === at.start)?.id ?? null : null;
}
export function validate(state, duration = length) {
  if (!enabled(state)) {
    if (state.boxes.some(b => 'track' in b || 'start' in b) || state.text_lanes || state.overlap_switches) fail('placement needs tracks');
    return;
  }
  const tracks = new Map(), ids = new Set();
  const identity = id => { if (typeof id !== 'string' || !id || ids.has(id)) fail('IDs must be nonempty and unique'); ids.add(id); };
  for (const track of list(state.tracks)) {
    if (!track || !TYPES.includes(track.type) || typeof track.name !== 'string') fail('invalid track');
    identity(track.id); tracks.set(track.id, track.type);
  }
  const type = (id, wanted) => { if (tracks.get(id) !== wanted) fail(`unknown or wrong-type ${wanted} track ${id}`); };
  for (const box of state.boxes) {
    identity(box.id); type(box.track, 'video');
    if (!Number.isSafeInteger(box.start) || box.start < 0) fail(`clip ${box.id} start must be a nonnegative integer`);
    for (const layer of box.layers ?? []) identity(layer.id);
  }
  const spans = placements(state, duration);
  for (const track of state.tracks.filter(t => t.type === 'video')) {
    const sorted = spans.filter(p => p.track === track.id).sort((a,b) => a.start-b.start);
    for (let i=1;i<sorted.length;i++) if (sorted[i].start < sorted[i-1].end) fail(`clips overlap on ${track.name}`);
  }
  const occupied = new Set();
  for (const audio of state.audio_clips ?? []) {
    type(audio.track, 'audio'); if (occupied.has(audio.track)) fail('audio track already has a source'); occupied.add(audio.track);
  }
  for (const text of state.text_lanes ?? []) {
    type(text.track, 'text'); if (occupied.has(text.track)) fail('text track already has an attachment'); occupied.add(text.track);
  }
  const windows = [];
  for (const sw of list(state.overlap_switches ?? [])) {
    identity(sw.id);
    const a=spans.find(p=>p.id===sw.from), b=spans.find(p=>p.id===sw.to);
    if (!a || !b || a.track===b.track) fail('switch needs clips on different video tracks');
    const start=Math.max(a.start,b.start), end=Math.min(a.end,b.end);
    if (!Number.isInteger(sw.at) || !Number.isInteger(sw.fade) || sw.fade<0 || sw.fade>12
      || sw.at-Math.floor(sw.fade/2)<start || sw.at+Math.ceil(sw.fade/2)>end || sw.at>=end || sw.at<=start) fail('switch fade must fit its overlap');
    if (!['screen',sw.from,sw.to].includes(sw.sound)) fail('invalid switch sound');
    if (windows.some(w=>w.start<end && start<w.end && [sw.from,sw.to].some(id=>w.ids.includes(id)))) fail('conflicting overlap switches');
    windows.push({start,end,ids:[sw.from,sw.to]});
  }
}
function nextId(state, prefix) {
  const used = new Set([...(state.tracks ?? []).map(t=>t.id), ...state.boxes.flatMap(b=>[b.id,...(b.layers??[]).map(l=>l.id)]),...(state.overlap_switches??[]).map(s=>s.id)]);
  let n=1; while (used.has(`${prefix}${n}`)) n++;
  return `${prefix}${n}`;
}
export function enableTracks(state) {
  if (enabled(state)) return;
  const spans=placements(state); state.tracks=[];
  const video={id:nextId(state,'v'),type:'video',name:'Video 1'}; if(state.boxes.length)state.tracks.push(video);
  state.boxes.forEach((box,i)=>Object.assign(box,{track:video.id,start:spans[i].start}));
  for (const audio of state.audio_clips ?? []) { const id=addTrack(state,'audio'); audio.track=id; }
  if (state.timed_text) { const id=addTrack(state,'text'); state.text_lanes=[{track:id,attachment:state.timed_text}]; delete state.timed_text; }
}
export function addTrack(state, type) {
  if (!TYPES.includes(type)) fail('unknown track type');
  enableTracks(state);
  const id=nextId(state,type[0]), n=state.tracks.filter(t=>t.type===type).length+1;
  state.tracks.push({id,type,name:`${type[0].toUpperCase()+type.slice(1)} ${n}`}); return id;
}
export function trackContents(state, id) {
  return {clips:state.boxes.filter(b=>b.track===id).length,audio:(state.audio_clips??[]).filter(c=>c.track===id).length,text:(state.text_lanes??[]).filter(t=>t.track===id).length};
}
export function removeTrack(state, id) {
  const gone=new Set(state.boxes.filter(b=>b.track===id).map(b=>b.id));
  state.tracks=state.tracks.filter(t=>t.id!==id); state.boxes=state.boxes.filter(b=>!gone.has(b.id));
  if (state.audio_clips) state.audio_clips=state.audio_clips.filter(c=>c.track!==id);
  if (state.text_lanes) state.text_lanes=state.text_lanes.filter(t=>t.track!==id);
  if (state.overlap_switches) state.overlap_switches=state.overlap_switches.filter(s=>!gone.has(s.from)&&!gone.has(s.to));
  if (state.bridges) state.bridges=state.bridges.filter(b=>!gone.has(b.before));
  for (const box of state.boxes) if (box.memories) box.memories=box.memories.filter(m=>!gone.has(m.box));
}
