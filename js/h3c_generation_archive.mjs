import {settledPreparation} from './h3c_reference_preparation.mjs?v=d05409662438';
import {parseJSON,stringifyJSON} from './h3c_project.mjs?v=0882b8a6265a';
function validate(archive){
 if(archive?.format!=='h3-generation'||archive.version!==1||typeof archive.timeline!=='string'||!archive.story||!Array.isArray(archive.assets))throw Error('Choose a generation export version 1.');
 const line=parseJSON(archive.timeline);if(!Array.isArray(line.boxes))throw Error('Generation Timeline is invalid.');
}
async function request(host,path,body){const result=await host.requestGeneration('/h3c/generations/'+path,body);if(!result?.ok)throw Error(result?.error??'Generation transfer failed.');return result;}
export async function exportGeneration(host){
 const busy=host.generationBusy?.();if(busy)throw Error(busy);
 const body=await host.readGeneration();if(body.writing)throw Error('Wait for Story writing before exporting a generation.');
 const revision=host.generationRevision();const result=await request(host,'export',body);
 if(revision!==host.generationRevision())throw Error('The generation changed during export. Export again after edits settle.');
 validate(result.archive);return result.archive;
}
export async function importGeneration(host,archive){
 validate(archive);await host.generationReady?.();
 const revision=host.generationRevision();
 const check=()=>{const busy=host.generationBusy?.();if(busy)throw Error(busy);if(revision!==host.generationRevision())throw Error('The destination changed during import; current edits were preserved.');};
 const renderer=await host.generationRenderer?.();check();
 await request(host,'preflight',{archive});check();
 const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(stringifyJSON(renderer?{archive,renderer}:archive))))).map(v=>v.toString(16).padStart(2,'0')).join('');check();
 const pending=host.generationPending?.archive_sha256===digest?host.generationPending:{request_id:crypto.randomUUID(),archive_sha256:digest};
 host.generationPending=pending;host.setGenerationPending?.(pending);
 const result=await request(host,'import',{archive,request_id:pending.request_id,...(renderer?{renderer}:{})});check();
 const line=parseJSON(result.timeline);line.still_requests=(line.still_requests??[]).filter(r=>r.state==='complete').map(r=>({...r,historical:true}));
 if(line.reference_preparation)line.reference_preparation=settledPreparation(line.reference_preparation);
 // One synchronous application after all asynchronous reads and checks have finished.
 host.applyGeneration({...result,timeline:stringifyJSON(line)});
 host.generationPending=null;host.setGenerationPending?.(null);return result;
}
export function downloadGeneration(archive){
 const url=URL.createObjectURL(new Blob([stringifyJSON(archive)],{type:'application/json'})),link=document.createElement('a');
 link.href=url;link.download='story.h3-generation.json';document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
}


// Imports change project data through native text controls, preserving graph connections.
export function generationControl(node,name) {
 const local=node.widgets?.find(w=>w.name===name),input=node.inputs?.find(i=>(i.widget?.name??i.name)===name);
 const label=`${node.type==='H3C_Timeline'?'Timeline':'Story'} ${name}`;
 let owner=node,port=input,seen=new Set();
 while(port?.link!=null) {
  if(seen.has(owner.id))throw Error(`${label} has a cyclic text connection.`);seen.add(owner.id);
  const links=owner.graph?.links,wire=links?.get?.(port.link)??links?.[port.link];
  owner=owner.graph?.getNodeById(Array.isArray(wire)?wire[1]:wire?.origin_id);
  if(!owner||!['PrimitiveString','PrimitiveStringMultiline'].includes(owner.type))
   throw Error(`${label} is computed by ${owner?.type??'a missing node'}. Connect a Text or Text (Multiline) control to import into this field.`);
  port=owner.inputs?.find(i=>(i.widget?.name??i.name)==='value');
 }
 const value=owner===node?local:owner.widgets?.find(w=>w.name==='value');
 if(!value)throw Error(`${label} has no editable text control.`);
 return {local,value,label};
}
export function setGenerationControl(control,value) {
 control.value.value=value;if(control.local)control.local.value=value;
}
