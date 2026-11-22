// Image sockets are compiled into native image readers, keeping video preparation out of image-only graphs.
import {assemblePrompt,describeBox,droppedFrames,effectivePlates,effectiveRefmods,isFresh,mentions,referenceEnabled,referenceTags} from './h3c_timeline_model.mjs?v=1dfc1612e462';
import {acceptedGuideFrames} from './h3c_shot_preview.mjs?v=1dfc1612e462';
const imageName = name => /^image_([1-9]\d*)$/.exec(name ?? '')?.[1];

function pictureTags(state, index, context) {
  const box=state.boxes?.[index];
  if(!box)return [];
  const layout=describeBox(state,index,{images:new Set()},Number(context));
  let tags=layout.tags.filter(item=>/^<Picture \d+>$/.test(item.tag));
  if(layout.mode!=='REF2VA') {
    const frames=acceptedGuideFrames(state,index,Number(context)),fresh=isFresh(state,index);
    const firstFile=fresh&&frames.includes(0),lastFile=!(fresh&&box.frames===1)&&(
      frames.includes(box.frames-(fresh?1:0))
      ||(state.boxes[index+1]&&!isFresh(state,index+1)&&acceptedGuideFrames(state,index+1,Number(context)).includes(0)));
    const firstName=fresh&&referenceEnabled(state,box.first)?box.first:'',lastName=referenceEnabled(state,box.last)?box.last:'';
    const selectedImages=mentions(assemblePrompt(state,index)).filter(item=>item.kind==='image').map(item=>item.name);
    const referencedLast=selectedImages.includes(lastName);
    const effectiveLast=firstFile&&box.frames===1&&!referencedLast?'':lastName;
    const cached=box.flf_refmods&&(!fresh||firstFile||firstName);
    const lastPresent=!cached||!fresh||box.frames>1||referencedLast;
    const first=firstFile||firstName?{name:firstFile?'':firstName}:null;
    let last=lastPresent&&(lastFile||effectiveLast)?{name:lastFile?'':effectiveLast}:null;
    const end=droppedFrames(state,index)?box.frames+(fresh?0:Number(context))-1:-1;
    if(first&&end===0&&!(effectiveLast&&lastPresent&&(firstFile||cached)))last=null;
    const nativeLast=end===-1||(first&&firstFile)||cached?last:null;
    const ordered=[first,nativeLast].filter(Boolean);
    if(cached) {
      const references=referenceTags(selectedImages.filter(name=>name!==firstName&&name!==lastName),[],
        effectiveRefmods(state),effectivePlates(state,index)).filter(item=>/^<Picture \d+>$/.test(item.tag));
      ordered.push(...[first,last].filter(Boolean),...references);
    }
    tags=ordered.map((item,i)=>({name:item.name,tag:`<Picture ${i+1}>`}));
  }
  return tags;
}

// The highest <Picture N> of the last Timeline text each node counted: every redraw and every graphToPrompt asks,
// and counting describes each clip.
const counted = new WeakMap();

// `text`, when given, is the Timeline text `state` was read from.
export function syncImageOutputs(node, state = {}, text) {
  if (!node.addOutput) return;
  const saved = node.properties?.h3c_image_outputs ?? [];
  const context=node.widgets?.find(widget=>widget.name==='context_frames')?.value??39;
  const last=counted.get(node);
  const maximum=text!=null&&last?.text===text&&last.context===context?last.maximum
    :Math.max(1,...(state.boxes??[]).flatMap((_,i)=>pictureTags(state,i,context).map(item=>Number(/\d+/.exec(item.tag)[0]))));
  if (text!=null) counted.set(node,{text,context,maximum});
  const added=Array.from({length:maximum},(_,i)=>`image${i+1}`);
  for (const slot of [...saved, ...added]) {
    const name = `image_${slot.slice(5)}`;
    if (!node.outputs?.some(output => output.name === name)) node.addOutput(name, 'IMAGE');
  }
  node.properties ??= {};
  node.properties.h3c_image_outputs = node.outputs.filter(output => imageName(output.name)).map(output => `image${imageName(output.name)}`);
}

export function compileImageOutputs(snapshot) {
  const {workflow, output} = snapshot, readers = new Map(), pending = new Set();
  const definitions = new Map((workflow?.definitions?.subgraphs ?? []).map(graph => [graph.id, graph]));
  function locate(id) {
    let graph = workflow, node;
    const path = String(id).split(':');
    for (let i=0;i<path.length;i++) {
      node = graph?.nodes?.find(node => String(node.id) === path[i]);
      if (i < path.length-1) graph = definitions.get(node?.type);
    }
    return node;
  }
  function resolve(value) {
    if (!Array.isArray(value) || value.length !== 2 || typeof value[0] !== 'string' || !Number.isInteger(value[1])) return value;
    const [id, index] = value, origin = output[id];
    if (origin?.class_type !== 'H3C_Timeline' || index < 7) return value;
    const node = locate(id), number = imageName(node?.outputs?.[index]?.name);
    if (!number) throw new Error(`Timeline image output ${id}:${index} is missing. Refresh the workflow.`);
    const key = `${id}:${index}`;
    if (pending.has(key)) throw new Error(`Timeline <Picture ${number}> depends on its own image output.`);
    if (!readers.has(key)) {
      pending.add(key);
      let readerId = `h3c_image_${id}_${number}`;
      while (Object.hasOwn(output, readerId)) readerId += '_';
      const inputs = {picture:Number(number), timeline:resolve(origin.inputs.timeline),
        box:node.properties?.h3c_image_output_box ?? 1, frame:0};
      let source, text = origin.inputs.timeline;
      const controls = new Set();
      while (Array.isArray(text) && text[1] === 0 && /^PrimitiveString(?:Multiline)?$/.test(output[text[0]]?.class_type ?? '')) {
        if (controls.has(text[0])) throw new Error('Timeline text controls contain a cycle.');
        controls.add(text[0]);
        text = output[text[0]].inputs.value;
      }
      if (typeof text === 'string' && !Array.isArray(origin.inputs.context_frames)) {
        const state = JSON.parse(text), seen = new Set();
        source = pictureTags(state,inputs.box-1,origin.inputs.context_frames??39).find(item=>item.tag===`<Picture ${number}>`)?.name || null;
        while (state.reference_replacements?.[source]) {
          if (seen.has(source)) throw new Error(`Timeline reference cycle at @${source}.`);
          seen.add(source);
          source = state.reference_replacements[source].source ?? null;
        }
      }
      for (const [name, input] of Object.entries(origin.inputs)) {
        if (name === 'vae' || name === 'context_frames' || (source === undefined ? /^images\.image[1-9]\d*$/.test(name) : name === `images.${source}`)) inputs[name] = resolve(input);
      }
      output[readerId] = {class_type:'H3C_TimelineImage', inputs, _meta:{title:`Timeline <Picture ${number}>`}};
      readers.set(key, readerId);
      pending.delete(key);
    }
    return [readers.get(key),0];
  }
  for (const node of Object.values(output ?? {})) for (const [name, value] of Object.entries(node.inputs ?? {})) node.inputs[name] = resolve(value);
  return snapshot;
}
