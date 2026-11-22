import {icon,iconButton} from './h3c_icons.mjs';
import {SHEET_LAYOUT_CHOICES,sheetLayoutPicture} from './h3c_sheet_layouts.mjs?v=0db8977322c8';
import {stringifyJSON,seedValue} from './h3c_project.mjs?v=0882b8a6265a';
import {ImageJobClient} from './h3c_image_jobs.mjs?v=c02f98fb5ed8';
export const REFERENCE_CATEGORIES = ['cast','locations','props'];

export function preparationOf(state) {
  return state.reference_preparation ?? {version:1, generate:{cast:false,locations:false,props:false}, assets:[], requests:[]};
}

export function setPreparationCategory(state, category, enabled) {
  if (!REFERENCE_CATEGORIES.includes(category) || typeof enabled !== 'boolean') throw new Error('Unknown reference category');
  const preparation = state.reference_preparation ??= preparationOf(state);
  preparation.generate[category] = enabled;
}

export function independentReferences(rows) {
  return rows.filter(row=>!row.from&&!['appearance','scene_layout'].includes(row.role)&&row.status!=='orphan');
}

export function requiredAssets(state, boxId, catalog) {
  const flags = preparationOf(state).generate;
  return independentReferences(catalog).filter(row => flags[row.category] && row.included !== false && row.clips.includes(boxId)
    && !['approved','orphan'].includes(row.status)).map(row => row.key);
}


export class ReferenceClient {
  constructor(host) {
    this.host=host;this.batch=null;
    this.jobs=new ImageJobClient({request:(path,body)=>host.request(path,body),
      capture:request=>host.prepareReference(request),context:()=>host.referenceContext(),
      receipts:()=>preparationOf(host.referenceState()).requests,
      save:(receipt,context,options)=>this.save(receipt,context,options),resultPath:'/h3c/reference-assets/result',
      identify:prepared=>({asset_key:prepared.request.asset_key,input_fingerprint:prepared.request.input_fingerprint})});
  }
  get busy() {return !!this.batch || !!this.jobs.active.size || !!this.jobs.recovering;}
  async save(receipt,context,options={}) {
    const check=()=>{if(context!==this.host.referenceContext())throw Error('The generation changed while preparing references.');};
    check();
    let row;
    if(receipt.state==='complete'||receipt.state==='submitting') {
      const before=this.host.referenceState();
      row=(await this.host.referenceCatalog()).find(row=>row.key===receipt.asset_key);
      check();
      if(stringifyJSON(before)!==stringifyJSON(this.host.referenceState()))throw Error('References changed while recovering this image.');
    }
    if(receipt.state==='submitting') {
      if(!row||row.status==='orphan'||row.input_fingerprint!==receipt.input_fingerprint)throw Error('The reference design changed before submission.');
      if(!preparationOf(this.host.referenceState()).generate[row.category])throw Error('Reference preparation was disabled before submission.');
    }
    const state=structuredClone(this.host.referenceState()),preparation=state.reference_preparation??=preparationOf(state);
    const index=preparation.requests.findIndex(r=>r.request_id===receipt.request_id&&r.prompt_id===receipt.prompt_id);
    if(index<0)preparation.requests.push(structuredClone(receipt));
    else preparation.requests[index]={...preparation.requests[index],...structuredClone(receipt)};
    const asset=preparation.assets.find(a=>a.key===receipt.asset_key);
    // A finished image is kept even when the reference was edited while it rendered; it shows as out of date and cannot be approved.
    if(receipt.state==='complete' && asset && row?.status!=='orphan') {
      for(const image of receipt.images??[]) {
        const id=image.prompt_id+':'+image.batch_index;
        if(!asset.candidates.some(c=>c.id===id))asset.candidates.push({id,file:structuredClone(image.file),sha256:image.sha256,
          provenance:structuredClone(receipt.provenance),input_fingerprint:receipt.input_fingerprint,
          request_id:receipt.request_id,prompt_id:receipt.prompt_id,batch_index:image.batch_index});
      }
    }
    await this.host.writeReferenceState(state,options);check();
    if(receipt.state==='submitting'&&!preparationOf(this.host.referenceState()).generate[row.category])throw Error('Reference preparation was disabled before submission.');
    this.host.referenceChanged();return receipt;
  }
  async generateAsset(key) {
    const context=this.host.referenceContext(),before=this.host.referenceState();
    const rows=await this.host.referenceCatalog();
    if(context!==this.host.referenceContext()||stringifyJSON(before)!==stringifyJSON(this.host.referenceState()))throw Error('The references changed before preparation.');
    const row=rows.find(row=>row.key===key);
    if(!row||row.status==='orphan')throw Error('Choose an existing Story reference.');
    const preparation=preparationOf(before);
    if(!preparation.generate[row.category])throw Error('Enable '+row.category+' reference preparation first.');
    if(preparation.requests.some(r=>r.asset_key===key&&!r.historical&&!['complete','failed','cancelled'].includes(r.state)))throw Error('This reference already has a submitted image; recover it before generating another.');
    const state=structuredClone(before),stored=state.reference_preparation??=preparationOf(state);
    const index=stored.assets.findIndex(a=>a.key===key);
    const {prompt_parts,...plain}=structuredClone(row);
    if(index<0)stored.assets.push(plain);else stored.assets[index]={...stored.assets[index],...plain};
    await this.host.writeReferenceState(state);
    return this.jobs.generate({asset_key:key,input_fingerprint:row.input_fingerprint,prompt:row.prompt,...(row.seed!=null?{seed:row.seed}:{}),...(row.size?{size:row.size}:{})});
  }
  // The panel is told when a request changed, or the check failed, not after every check.
  // A finished image whose candidate was never saved (the reference was edited while it rendered, before this was kept).
  async adoptFinished() {
    const context=this.host.referenceContext(),state=structuredClone(this.host.referenceState()),preparation=preparationOf(state);
    let added=0;
    for(const receipt of preparation.requests) {
      const asset=receipt.state==='complete'?preparation.assets.find(a=>a.key===receipt.asset_key):null;
      for(const image of asset?receipt.images??[]:[]) {
        const id=image.prompt_id+':'+image.batch_index;
        if(asset.candidates?.some(c=>c.id===id))continue;
        (asset.candidates??=[]).push({id,file:structuredClone(image.file),sha256:image.sha256,provenance:structuredClone(receipt.provenance),
          input_fingerprint:receipt.input_fingerprint,request_id:receipt.request_id,prompt_id:receipt.prompt_id,batch_index:image.batch_index});
        added++;
      }
    }
    if(!added||context!==this.host.referenceContext())return 0;
    await this.host.writeReferenceState(state);
    return added;
  }
  async recover() {
    let changed=true;
    try {changed=await this.adoptFinished()+await this.jobs.recover();return changed;}
    finally {if(changed)this.host.referenceChanged();}
  }
  stopAfterCurrent() {if(this.batch&&!this.batch.stop){this.batch.stop=true;this.host.referenceChanged();}}
  async generateSelected(keys) {
    if(this.batch)throw Error('Reference preparation is already running.');
    const context=this.host.referenceContext();
    this.batch={keys:[...keys],completed:0,current:null,stop:false};this.host.referenceChanged();
    try {
      for(const key of keys) {
        if(this.batch.stop||context!==this.host.referenceContext())break;
        const row=(await this.host.referenceCatalog()).find(row=>row.key===key);
        if(!row||row.status==='orphan'||!preparationOf(this.host.referenceState()).generate[row.category])break;
        if(row.status==='approved'||row.candidates?.some(c=>c.input_fingerprint===row.input_fingerprint)){this.batch.completed++;continue;}
        this.batch.current=row.name;this.host.referenceChanged();
        let receipt=await this.generateAsset(key);
        while(!['complete','failed','cancelled'].includes(receipt.state)) {
          await this.recover();
          if(context!==this.host.referenceContext())return;
          receipt=preparationOf(this.host.referenceState()).requests.find(r=>r.prompt_id===receipt.prompt_id)??receipt;
          if(receipt.state==='unknown')throw Error('The image acknowledgement is unknown. Recover the existing request before resuming preparation.');
          if(!['complete','failed','cancelled'].includes(receipt.state))await new Promise(resolve=>setTimeout(resolve,3000));
        }
        if(receipt.state!=='complete')throw Error((row.name??key)+' generation '+receipt.state+'. Earlier candidates are retained.');
        this.batch.completed++;
      }
    } finally {this.batch=null;this.host.referenceChanged();}
  }
}

export function settledPreparation(value) {
  if(!value)return value;
  const result=structuredClone(value);delete result.batch;
  result.requests=(result.requests??[]).filter(r=>r.state==='complete').map(r=>({...r,historical:true}));
  return result;
}


export async function applyReferenceApproval(host,request) {
  if(host.referenceReady)await host.referenceReady();
  const context=host.referenceContext(),timeline=stringifyJSON(host.referenceState());
  const result=await host.request('/h3c/reference-assets/approve',{...request,timeline});
  if(context!==host.referenceContext()||timeline!==stringifyJSON(host.referenceState()))throw Error('The Timeline changed during reference approval; current edits were preserved.');
  if(!result.ok)throw Error(result.error??'Could not approve the reference.');
  if(host.referenceCatalog) {
    const candidate=preparationOf(host.referenceState()).assets.find(a=>a.key===request.asset_key)?.candidates?.find(c=>c.id===request.candidate_id);
    const row=(await host.referenceCatalog()).find(r=>r.key===request.asset_key);
    if(context!==host.referenceContext()||timeline!==stringifyJSON(host.referenceState()))throw Error('The Timeline changed during reference approval; current edits were preserved.');
    if(!row||!candidate||row.input_fingerprint!==candidate.input_fingerprint)throw Error('The reference source or design changed during approval; review a current candidate.');
  }
  host.undoStep?.();
  const saved=host.writeReferenceState(result.timeline);
  host.undoStep?.();
  await saved;host.referenceChanged();return result;
}


export function addObjectReference(state,{name,description,boxId,wholeScene=false}) {
  if(!name.trim()||!description.trim())throw Error('Give the object a name and visual description.');
  const index=state.boxes.findIndex(box=>box.id===boxId);
  if(index<0)throw Error('Select a Story clip for this object.');
  const bible=state.bible??={next:1,entities:[]},used=new Set(bible.entities.map(e=>e.id));
  let number=bible.next??1;while(used.has('e'+number))number++;
  const id='e'+number;bible.next=number+1;
  bible.entities.push({id,kind:'prop',name:name.trim(),description:description.trim(),pictures:[],looks:[]});
  let start=index;if(wholeScene)while(start>0&&!state.boxes[start].new_scene)start--;
  for(let at=start;at<state.boxes.length;at++) {
    if(at>start&&(!wholeScene||state.boxes[at].new_scene))break;
    const schedule=state.boxes[at].schedule??={entities:[]};schedule.entities=[...new Set([...(schedule.entities??[]),id])];
  }
  return id;
}

const element=(tag,className,text)=>{const node=document.createElement(tag);if(className)node.className=className;if(text!=null)node.textContent=text;return node;};
const action=(text,run)=>{const node=element('button','h3ct-button',text);node.type='button';node.addEventListener('click',()=>run());return node;};
// Character and location sheets are drawn 16:9 unless the reference sets a size; objects and composed scenes follow the workflow.
const sheetSized=row=>(row.category==='cast'||row.category==='locations')&&row.role!=='scene_layout';

export class ReferencePreparationPanel {
  constructor(editor) {
    this.editor=editor;this.host=editor.host;this.rows=[];this.asked=0;this.busy=false;this.message='';this.capability=null;this.selectedKey=null;this.filter='all';this.search='';this.mobileDetail=false;this.drafts=new Map();this.showObject=false;this.context=this.host.referenceContext?.();
    this.root=element('details','h3cr-preparation');
    this.root.append(element('summary',null,'Reference images'));
    this.body=element('div','h3cr-body');this.root.append(this.body);
    this.root.addEventListener('toggle',()=>{if(this.root.open)this.refresh();});
    if(!document.getElementById('h3cr-preparation-style')) {
      const style=element('style');style.id='h3cr-preparation-style';style.textContent=`
      .h3cr-preparation{min-width:0;border:1px solid #343a46;border-radius:6px;padding:8px}
      .h3cr-preparation summary{cursor:pointer;font-weight:600}.h3cr-body{display:flex;flex-direction:column;gap:8px;padding-top:8px;min-width:0}
      .h3cr-preparation .h3cr-switches,.h3cr-preparation .h3cr-actions{display:flex;flex-wrap:wrap;gap:6px;align-items:center}.h3cr-preparation .h3cr-switches label{display:flex;gap:4px;align-items:center}
      .h3cr-asset{display:flex;flex-direction:column;gap:6px;min-width:0;border-top:1px solid #343a46;padding-top:8px}
      .h3cr-preparation textarea,.h3cr-preparation input:not([type=checkbox]),.h3cr-preparation select{max-width:100%;box-sizing:border-box;min-width:0}
      .h3cr-preparation textarea{width:100%;resize:vertical}.h3cr-preparation img{width:112px;max-width:100%;height:84px;object-fit:contain;background:#151923;border-radius:4px}
      .h3cr-candidates{display:flex;flex-wrap:wrap;gap:8px}.h3cr-candidate{display:flex;flex-direction:column;gap:4px;max-width:100%}
      .h3cr-preparation .h3cr-title{display:flex;flex-wrap:wrap;gap:6px;align-items:center}.h3cr-status,.h3cr-note{font-size:12px;color:#aab1bd;overflow-wrap:anywhere;margin:0}
      .h3cr-preparation .h3ct-text{flex:1 1 130px}.h3cr-object{display:flex;flex-wrap:wrap;gap:6px;min-width:0}

      .h3cr-preparation{padding:12px;border-radius:3px}.h3cr-toolbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.h3cr-toolbar .h3cr-count{margin-right:auto;color:#c3cad4;font-size:12px}
      .h3cr-filters{display:flex;gap:4px;flex-wrap:wrap;align-items:center;padding:6px 0}.h3cr-filters input{margin-left:auto;min-width:140px;flex:1 1 160px;max-width:260px!important}
      .h3cr-tabs{display:flex;flex-wrap:wrap;gap:2px;padding:2px;border-radius:7px;background:#ffffff08}
      .h3cr-tabs [role=tab]{display:inline-flex;align-items:center;gap:6px;min-height:28px;padding:3px 10px;border:0;border-radius:5px;background:transparent;color:#aab1bd;font-size:12px;font-weight:500;cursor:pointer}
      .h3cr-tabs [role=tab]:hover{color:#e8ecf2;background:#ffffff0d}.h3cr-tabs [role=tab][aria-selected=true]{background:#2a3a55;color:#e3edff}
      .h3cr-tabs [role=tab]:focus-visible{outline:2px solid #8fbcff;outline-offset:-2px}
      .h3cr-tab-count{min-width:18px;padding:0 5px;border-radius:9px;background:#ffffff14;color:#c9d1dd;font-size:11px;line-height:16px;text-align:center;font-variant-numeric:tabular-nums}
      .h3cr-prepare{display:inline-flex;align-items:center;gap:8px;min-height:28px;padding:2px 4px;border:0;background:transparent;color:#d6dae2;font:inherit;font-size:13px;cursor:pointer}
      .h3cr-prepare:disabled{cursor:default;opacity:.6}.h3cr-prepare:focus-visible{outline:2px solid #8fbcff;outline-offset:2px;border-radius:4px}
      .h3cr-track{flex:0 0 26px;height:14px;border-radius:7px;background:#3a404c;box-shadow:inset 0 0 0 1px #4a5160;position:relative;transition:background .15s}
      .h3cr-track::after{content:'';position:absolute;top:2px;left:2px;width:10px;height:10px;border-radius:50%;background:#8b93a1;transition:transform .15s,background .15s}
      .h3cr-prepare[aria-checked=true] .h3cr-track{background:#3f6fbf;box-shadow:none}.h3cr-prepare[aria-checked=true] .h3cr-track::after{transform:translateX(12px);background:#fff}
      .h3cr-workspace{display:grid;grid-template-columns:minmax(170px,240px) minmax(0,1fr);gap:16px;align-items:start;min-width:0}
      .h3cr-master{max-height:55vh;overflow-y:auto;border-top:1px solid #343a46;min-width:0}.h3cr-item{display:flex;align-items:center;gap:10px;width:100%;text-align:left;padding:8px;border:0;border-bottom:1px solid #343a46;background:transparent;color:inherit;cursor:pointer;font:inherit;min-height:68px}
      .h3cr-item:hover{background:#262c37}.h3cr-item[aria-pressed=true]{background:#2a3c55}.h3cr-item:focus-visible{outline:2px solid #9dbef1;outline-offset:-2px}
      .h3cr-item img,.h3cr-item .h3cr-thumb{width:48px;height:48px;flex:0 0 48px;object-fit:cover;background:#252b35;border-radius:3px;display:flex;align-items:center;justify-content:center}
      .h3cr-item-meta{display:flex;flex-direction:column;gap:3px;min-width:0}.h3cr-item-name{font-weight:500;overflow-wrap:anywhere}.h3cr-item-status{font-size:12px;color:#bec7d6}
      .h3cr-detail{min-width:0}.h3cr-detail .h3cr-asset{border:0;padding:0;gap:10px}.h3cr-detail .h3cr-title{gap:10px}.h3cr-detail .h3cr-title>strong{font-size:16px;font-weight:600;margin-right:auto}
      .h3cr-include{display:flex;align-items:center;gap:5px;font-size:12px;color:#c3cad4}.h3cr-detail textarea{font:13px/1.5 system-ui;min-height:110px;max-width:75ch;box-sizing:border-box}
      .h3cr-detail .h3cr-candidates{gap:10px;align-items:flex-start}.h3cr-detail .h3cr-candidate{flex:1 1 160px;max-width:320px}.h3cr-detail .h3cr-candidate img{width:100%;height:180px;border-radius:3px;background:#10131a}
      .h3cr-detail .h3cr-candidate:only-child img{height:220px}.h3cr-parts{border-top:1px solid #343a46;padding-top:8px}.h3cr-parts summary{font-size:13px;font-weight:400}.h3cr-part-head{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.h3cr-part{display:flex;flex-direction:column;gap:6px;align-items:flex-start;margin-top:10px}.h3cr-part textarea{width:100%}.h3cr-layouts{display:flex;flex-wrap:wrap;gap:10px}.h3cr-layout{display:flex;flex-direction:column;gap:4px;width:168px;padding:6px;border:2px solid #343a46;border-radius:6px;background:#10131a;color:#c9d1dd;font:inherit;font-size:12px;text-align:left;cursor:pointer}.h3cr-layout img{width:100%;aspect-ratio:16/9;display:block;border-radius:3px}.h3cr-layout[aria-checked=true]{border-color:#8ab4ff;background:#1a2230}.h3cr-layout:disabled{opacity:.55;cursor:default}.h3cr-layout-text{width:100%}.h3cr-layout-text summary{font-size:12px;cursor:pointer}.h3cr-advanced{border-top:1px solid #343a46;padding-top:8px}.h3cr-advanced summary{font-size:13px;font-weight:400}
      .h3cr-advanced .h3cr-actions{margin-top:8px}.h3cr-advanced label{display:flex;flex-direction:column;gap:4px;flex:1 1 100px;font-size:12px;color:#c3cad4}
      .h3cr-used{display:flex;gap:5px;flex-wrap:wrap;font-size:12px}.h3cr-used .h3ct-button{font-size:12px;padding:2px 6px}.h3cr-back{display:none!important}.h3cr-batch-options{border-top:1px solid #343a46;padding-top:6px}.h3cr-batch-options summary{font-size:12px;font-weight:400}
      .h3cr-object{padding:10px 0;border-bottom:1px solid #343a46}.h3cr-empty{padding:20px 8px;color:#c3cad4;font-size:13px}
      @media(max-width:600px){.h3cr-workspace{display:block}.h3cr-mobile-detail .h3cr-master{display:none}.h3cr-workspace:not(.h3cr-mobile-detail) .h3cr-detail{display:none}.h3cr-back{display:inline-flex!important}.h3cr-filters input{max-width:100%!important}.h3cr-item{min-height:72px}.h3cr-toolbar{gap:6px}}
      `;document.head.append(style);
    }
    this.render();
  }
  destroy() {this.asked++;}
  async open(keys=[]) {
    this.highlight=new Set(keys);this.root.open=true;await this.refresh();
    this.root.dispatchEvent(new CustomEvent('h3c-show-page',{bubbles:true,detail:{page:'cast'}}));
    this.root.scrollIntoView?.({block:'nearest'});
  }
  async refresh() {
    if(!this.root.open)return;
    const asked=++this.asked,context=this.host.referenceContext?.(),before=stringifyJSON(this.editor.state);
    if(context!==this.context){this.context=context;this.rows=[];this.drafts.clear();this.selectedKey=null;}
    this.loading=true;if(!this.rows.length)this.render();
    try {
      const [rows,controls]=await Promise.all([this.host.referenceCatalog(),this.host.stillControls?.()]);
      if(asked!==this.asked||context!==this.host.referenceContext?.()||before!==stringifyJSON(this.editor.state))return;
      this.rows=independentReferences(rows);this.controls=controls;this.capability=controls?.adapter==='pixels';this.message='';for(const row of this.rows)if(this.drafts.get(row.key)===row.prompt)this.drafts.delete(row.key);
    } catch(error) {if(asked===this.asked)this.message=error.message;}
    finally{if(asked===this.asked){this.loading=false;this.render();}}
  }
  commit(edit) {
    if(this.editor.readOnly?.length)return;
    this.host.undoStep?.();edit(this.editor.state);this.editor.commit();this.host.undoStep?.();
    this.refresh();
  }
  editRow(row,values) {
    const current=this.rows.find(r=>r.key===row.key);
    if(!current||current.input_fingerprint!==row.input_fingerprint){this.message='This reference changed while editing. Review its current description before saving.';this.render();return;}
    this.commit(state=>{
      const preparation=state.reference_preparation??=preparationOf(state);
      let stored=preparation.assets.find(a=>a.key===row.key);
      if(!stored){const {prompt_parts,...plain}=row;preparation.assets.push(stored=structuredClone(plain));}
      Object.assign(stored,values);
    });
  }
  // Everything the Studio adds around the description, each part editable and switchable for this reference only.
  partsPanel(row,readonly) {
    const parts=row.prompt_parts??[],box=element('details','h3cr-parts');
    if(!parts.length)return box;
    const edit=(id,change)=>{
      const next=structuredClone(row.part_overrides??{}),own={...next[id],...change},part=parts.find(p=>p.id===id);
      if(own.enabled!==false)delete own.enabled;
      if(own.choice===part.choices?.[0])delete own.choice;
      if(own.text==null||own.text.trim()===part.default)delete own.text;
      if(Object.keys(own).length)next[id]=own;else delete next[id];
      this.editRow(row,{part_overrides:Object.keys(next).length?next:undefined});
    };
    const off=parts.filter(p=>!p.enabled).length,changed=parts.filter(p=>p.edited||(p.choice&&p.choice!==p.choices?.[0])).length;
    box.open=this.partsOpen?.has(row.key)??(off>0||changed>0);
    box.addEventListener('toggle',()=>{(this.partsOpen??=new Set())[box.open?'add':'delete'](row.key);});
    box.append(element('summary',null,'Also sent with this prompt'+(off||changed?` (${[changed&&changed+' edited',off&&off+' off'].filter(Boolean).join(', ')})`:'')));
    box.append(element('p','h3cr-note','The Studio adds this text before and after the description above. Changes apply to this reference only; switch a part off to leave it out.'));
    for(const part of parts) {
      const item=element('div','h3cr-part'),head=element('div','h3cr-part-head'),send=element('button','h3cr-prepare');
      send.type='button';send.setAttribute('role','switch');send.setAttribute('aria-checked',String(part.enabled));send.disabled=readonly;
      send.setAttribute('aria-label','Send '+part.label.toLowerCase()+' with '+row.name);
      send.addEventListener('click',()=>edit(part.id,{enabled:!part.enabled}));
      send.append(element('span','h3cr-track'),element('span',null,part.label+(part.where==='before'?' (before the description)':' (after the description)')));
      head.append(send);
      if(part.edited)head.append(element('span','h3cr-status','edited'));
      item.append(head);
      // A part that is switched off shows nothing else: no layout pictures, no text to edit.
      if(!part.enabled){box.append(item);continue;}
      const custom=part.choice==='custom';
      // A character sheet follows one of the layouts below; the pictures only show where the studies sit.
      if(part.choices) {
        const group=element('div','h3cr-layouts');group.setAttribute('role','radiogroup');group.setAttribute('aria-label','Sheet layout for '+row.name);
        for(const choice of SHEET_LAYOUT_CHOICES.filter(c=>part.choices.includes(c.id))) {
          const pick=element('button','h3cr-layout');pick.type='button';pick.setAttribute('role','radio');pick.setAttribute('aria-checked',String(part.choice===choice.id));
          pick.setAttribute('aria-label',choice.label);pick.disabled=readonly||!part.enabled;pick.dataset.layout=choice.id;
          const picture=element('img');picture.src=sheetLayoutPicture(choice.id);picture.alt='';picture.draggable=false;
          pick.append(picture,element('span',null,choice.label));
          pick.addEventListener('click',()=>{if(part.choice!==choice.id)edit(part.id,{choice:choice.id,text:null});});
          group.append(pick);
        }
        item.append(group);
      }
      const text=element('textarea','h3ct-text');text.rows=part.id==='layout'?(custom?8:14):3;text.value=this.drafts.get(row.key+':'+part.id)??part.text;
      text.disabled=readonly||!part.enabled;text.setAttribute('aria-label',part.label+' for '+row.name);text.dataset.focus=row.key+':part:'+part.id;
      if(custom)text.placeholder='Describe how the sheet is laid out. Put {description} where the character description should go, or leave it out and the description follows your text.';
      text.addEventListener('input',()=>this.drafts.set(row.key+':'+part.id,text.value));
      text.addEventListener('change',()=>{this.drafts.delete(row.key+':'+part.id);edit(part.id,{text:text.value});});
      if(part.choices&&!custom) {
        const more=element('details','h3cr-layout-text');more.open=part.edited;more.append(element('summary',null,'Edit the layout text'),text);
        if(part.edited){const reset=action('Reset to default',()=>edit(part.id,{text:null}));reset.disabled=readonly;more.append(reset);}
        item.append(more);
      } else {
        item.append(text);
        if(part.edited){const reset=action('Reset to default',()=>edit(part.id,{text:null}));reset.disabled=readonly;item.append(reset);}
      }
      box.append(item);
    }
    return box;
  }
  async run(operation) {
    if(this.busy)return;this.busy=true;this.message='';this.render();
    try {await operation();}catch(error){this.message=error.message;}
    finally{this.busy=false;const message=this.message;await this.refresh();if(message)this.message=message;this.render();}
  }
  async upload(row,file) {
    if(!file)return;
    const context=this.host.referenceContext?.(),fingerprint=row.input_fingerprint;
    const image=await this.host.importGuide(file),pin=await this.host.pinGuide(image);
    const rows=await this.host.referenceCatalog(),current=rows.find(r=>r.key===row.key);
    if(context!==this.host.referenceContext?.()||current?.input_fingerprint!==fingerprint)throw Error('The reference changed during upload.');
    const request_id=crypto.randomUUID(),prompt_id=crypto.randomUUID();
    this.editRow(current,{candidates:[...(current.candidates??[]),{id:prompt_id+':0',file:pin.file,sha256:pin.sha256,
      input_fingerprint:fingerprint,request_id,prompt_id,batch_index:0,provenance:{origin:'uploaded'}}]});
  }
  choose(key){this.selectedKey=key;this.mobileDetail=true;this.render();}
  setFilter(category){this.filter=category;this.mobileDetail=false;this.render();}
  render() {
    const focus=this.body.contains(document.activeElement)?document.activeElement:null,focusKey=focus?.dataset.focus;
    const selection=focus&&typeof focus.selectionStart==='number'?[focus.selectionStart,focus.selectionEnd]:null;
    const state=this.editor.state,flags=preparationOf(state).generate,busy=this.busy||this.host.referenceBusy?.();
    const readonly=!!this.editor.readOnly?.length;
    const categories=[['all','All'],['cast','Characters'],['locations','Locations'],['props','Objects']];
    const filtered=this.rows.filter(row=>(this.filter==='all'||row.category===this.filter)&&row.name.toLowerCase().includes(this.search.toLowerCase()));
    if(!filtered.some(r=>r.key===this.selectedKey))this.selectedKey=filtered[0]?.key??null;
    const selected=filtered.find(r=>r.key===this.selectedKey);
    const toolbar=element('div','h3cr-toolbar'),names=Object.fromEntries(categories);
    const needed=this.rows.filter(r=>(this.filter==='all'||r.category===this.filter)&&flags[r.category]&&r.included!==false&&['missing','outdated'].includes(r.status));
    const scope=this.filter==='all'?'':` ${names[this.filter].toLowerCase()}`;
    const generate=action(`Generate missing${scope} (${needed.length})`,()=>this.run(()=>this.host.generateSelectedReferences(needed.map(r=>r.key))));
    generate.classList.add('h3ct-primary');generate.disabled=!!busy||readonly||this.capability!==true||!needed.length;
    generate.title=this.capability!==true?'Connect a pixel image recipe to generate references.'
      :this.filter!=='all'&&!flags[this.filter]?`Turn on Prepare ${names[this.filter].toLowerCase()} to generate them.`
      :!Object.values(flags).some(Boolean)?'Open a category and turn on its preparation.':!needed.length?'Included references are ready.':'Generate included missing or outdated references.';
    const settings=iconButton('settings','Generator settings',()=>this.run(()=>this.host.openStillGenerator()));settings.dataset.action='generator-settings';settings.disabled=!this.host.openStillGenerator;
    const stop=action('Stop after current image',()=>this.host.stopReferencePreparation());stop.hidden=!this.host.referenceBatch?.();
    const addObject=action(this.showObject?'Close object form':'Add object',()=>{this.showObject=!this.showObject;this.render();});addObject.disabled=readonly;
    const filters=element('div','h3cr-filters');
    const tabs=element('div','h3cr-tabs');tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','Reference categories');
    for(const [category,label] of categories){
      const count=category==='all'?this.rows.length:this.rows.filter(row=>row.category===category).length;
      const tab=action('',()=>this.setFilter(category));tab.setAttribute('role','tab');tab.setAttribute('aria-label',label);
      tab.setAttribute('aria-selected',String(category===this.filter));tab.tabIndex=category===this.filter?0:-1;
      tab.append(element('span',null,label),element('span','h3cr-tab-count',String(count)));
      tab.addEventListener('keydown',event=>{
        if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();
        const index=categories.findIndex(([key])=>key===category),next=event.key==='Home'?0:event.key==='End'?categories.length-1:(index+(event.key==='ArrowRight'?1:-1)+categories.length)%categories.length;
        this.setFilter(categories[next][0]);this.body.querySelector(`[role=tab][aria-label="${categories[next][1]}"]`)?.focus();
      });
      tabs.append(tab);
    }
    const search=element('input','h3ct-text');search.type='search';search.placeholder='Find a reference';search.value=this.search;search.setAttribute('aria-label','Search references');search.dataset.focus='reference-search';search.addEventListener('input',()=>{this.search=search.value;this.render();});
    filters.append(tabs,search);
    if(this.filter==='all') {
      const on=categories.filter(([key])=>key!=='all'&&flags[key]).map(([,label])=>label);
      toolbar.append(element('span','h3cr-count',on.length?`Preparing ${on.join(', ').toLowerCase()}`:'No category is prepared yet. Open one to turn it on.'));
    } else {
      const category=this.filter,on=!!flags[category];
      const prepare=element('button','h3cr-prepare');prepare.type='button';prepare.setAttribute('role','switch');prepare.setAttribute('aria-checked',String(on));
      prepare.setAttribute('aria-label',`Prepare ${names[category].toLowerCase()} references`);prepare.disabled=readonly;
      prepare.title=`When on, clips that use ${names[category].toLowerCase()} need their approved references before stills generate. Off keeps their images as they are.`;
      prepare.append(element('span','h3cr-track'),element('span',null,`Prepare ${names[category].toLowerCase()}`));
      prepare.addEventListener('click',()=>this.commit(state=>setPreparationCategory(state,category,!on)));
      toolbar.append(prepare,element('span','h3cr-count'));
    }
    toolbar.append(generate,settings,stop,addObject);
    const parts=[filters,toolbar];
    if(this.capability===false)parts.push(element('p','h3cr-note','Connect a pixel image recipe to generate references. You can still upload images.'));
    const batch=this.host.referenceBatch?.();if(batch){const progress=element('progress');progress.max=batch.keys.length;progress.value=batch.completed;progress.setAttribute('aria-label','Reference preparation progress');parts.push(progress,element('p','h3cr-note',`Preparing ${batch.current??'references'}: ${batch.completed} of ${batch.keys.length}${batch.stop?' (stopping after this image)':''}`));}
    if(this.message){const note=element('p','h3cr-note',this.message);note.setAttribute('role','status');parts.push(note);}
    if(this.showObject)parts.push(this.objectForm());
    const workspace=element('div','h3cr-workspace');workspace.classList.toggle('h3cr-mobile-detail',this.mobileDetail);
    const master=element('div','h3cr-master');master.setAttribute('aria-label','Reference list');
    const statusLabel=row=>row.existing_images?.length&&row.status==='missing'?'Ready':({approved:'Approved',missing:row.candidates?.length?'Needs approval':'Missing',outdated:'Out of date',candidates:'Needs approval'}[row.status]??row.status);
    for(const row of filtered){const button=action('',()=>this.choose(row.key));button.className='h3cr-item';button.setAttribute('aria-label',`Edit ${row.name} reference`);button.setAttribute('aria-pressed',String(row.key===this.selectedKey));
      const approved=row.candidates?.find(c=>c.id===row.approved?.candidate_id),picture=approved??row.existing_images?.[0]??row.candidates?.[0];
      if(picture){const image=element('img');image.src=this.host.viewUrl(picture.file);image.alt='';button.append(image);}else{const placeholder=element('span','h3cr-thumb');placeholder.append(icon('stills'));button.append(placeholder);}
      const text=element('span','h3cr-item-meta');text.append(element('span','h3cr-item-name',row.name),element('span','h3cr-item-status',statusLabel(row)));button.append(text);master.append(button);
    }
    if(!filtered.length)master.append(element('p','h3cr-empty',this.loading?'Loading reference images…':this.rows.length?'No references match this filter.':'References appear here when characters, locations or objects are linked to clips.'));
    const detail=this.detail=element('div','h3cr-detail');workspace.append(master,detail);
    const back=action('Back to references',()=>{this.mobileDetail=false;this.render();});back.classList.add('h3cr-back');detail.append(back);
    if(!selected)detail.append(element('p','h3cr-empty','Select a reference to edit its description or choose an image.'));
    for(const row of selected?[selected]:[]) {
      const card=element('section','h3cr-asset');card.dataset.asset=row.key;
      const title=element('div','h3cr-title'),include=element('input');include.type='checkbox';include.checked=row.included!==false;
      include.disabled=readonly;include.setAttribute('aria-label','Include '+row.name+' in batch');include.addEventListener('change',()=>this.editRow(row,{included:include.checked}));
      const inclusion=element('label','h3cr-include');inclusion.append(include,element('span',null,'Include in batch'));title.append(element('strong',null,row.name),element('span','h3cr-status',statusLabel(row)),inclusion);card.append(title);
      const used=element('div','h3cr-used');used.append(element('span',null,'Used in'));for(const id of row.clips??[]){const index=state.boxes.findIndex(b=>b.id===id);if(index<0)continue;const link=action(`Clip ${index+1}`,()=>{this.editor.select?.(index);this.editor.inspectClip?.();this.root.dispatchEvent(new CustomEvent('h3c-show-page',{bubbles:true,detail:{page:'box'}}));});used.append(link);}card.append(used);
      const prompt=element('textarea','h3ct-text');prompt.rows=4;prompt.value=this.drafts.get(row.key)??row.prompt??'';prompt.disabled=readonly;prompt.setAttribute('aria-label',row.name+' image prompt');prompt.dataset.focus=row.key+':prompt';
      prompt.addEventListener('input',()=>this.drafts.set(row.key,prompt.value));prompt.addEventListener('change',()=>this.editRow(row,{prompt:prompt.value}));const description=element('label','h3cr-note','Visual description');description.htmlFor=`h3cr-prompt-${row.key}`;prompt.id=description.htmlFor;card.append(description,prompt);
      const fields=element('div','h3cr-actions');
      const seed=element('input','h3ct-text');seed.type='text';seed.inputMode='numeric';seed.placeholder='Seed: native generator';seed.value=row.seed==null?'':String(row.seed);seed.setAttribute('aria-label',row.name+' seed');seed.dataset.focus=row.key+':seed';
      seed.addEventListener('change',()=>{const value=seed.value===''?undefined:seedValue(seed.value);if(seed.value!==''&&value===undefined){this.message='Image seed must be an unsigned 64-bit integer.';this.render();return;}this.editRow(row,{seed:value});});
      const seedLabel=element('label',null,'Seed');seedLabel.append(seed);fields.append(seedLabel);
      for(const dimension of ['width','height']) {
        const size=element('input','h3ct-text');size.type='number';size.min='1';size.placeholder=dimension+(sheetSized(row)?' (16:9, native size)':' (native)');size.value=row.size?.[dimension]??'';size.setAttribute('aria-label',row.name+' '+dimension);size.dataset.focus=row.key+':'+dimension;
        size.addEventListener('change',()=>{if(size.value===''){this.editRow(row,{size:undefined});return;}const base=sheetSized(row)&&!row.size?(dimension==='width'?{height:Math.max(32,Math.round(Number(size.value)*9/16/32)*32)}:{width:Math.max(32,Math.round(Number(size.value)*16/9/32)*32)}):this.controls??{},width=Number(dimension==='width'?size.value:row.size?.width??base.width),height=Number(dimension==='height'?size.value:row.size?.height??base.height);if(Number.isInteger(width)&&width>0&&Number.isInteger(height)&&height>0)this.editRow(row,{size:{width,height}});else {this.message='Choose positive width and height, or use Generator settings.';this.render();}});const dimensionLabel=element('label',null,dimension==='width'?'Width':'Height');dimensionLabel.append(size);fields.append(dimensionLabel);
      }
      const advanced=element('details','h3cr-advanced');advanced.append(element('summary',null,'Advanced: seed and dimensions'),fields);
      const controls=element('div','h3cr-actions'),generateOne=action(row.status==='approved'?'Regenerate reference':row.candidates.length?'Regenerate candidate':'Generate reference',()=>this.run(()=>this.host.generateReference(row.key)));
      generateOne.disabled=readonly||!!busy||!flags[row.category]||this.capability!==true||row.status==='orphan';
      const upload=element('input');upload.type='file';upload.accept='image/*';upload.setAttribute('aria-label','Upload '+row.name+' reference');upload.hidden=true;upload.addEventListener('change',()=>this.run(()=>this.upload(row,upload.files[0])));
      const uploadButton=action('Upload candidate',()=>upload.click());uploadButton.disabled=readonly||!!busy||row.status==='orphan';
      controls.append(generateOne,uploadButton,upload);card.append(controls);
      const candidates=element('div','h3cr-candidates');
      for(const original of row.existing_images??[]) {
        const item=element('div','h3cr-candidate'),image=element('img');image.src=this.host.viewUrl(original.file);image.alt=row.name+' uploaded reference';
        item.append(image,element('span','h3cr-status','Uploaded reference — ready'));candidates.append(item);
      }
      for(const candidate of row.candidates??[]) {
        const item=element('div','h3cr-candidate'),image=element('img');image.src=this.host.viewUrl(candidate.file);image.alt=row.name+' candidate';
        const accept=action(row.approved?.candidate_id===candidate.id?'Approved reference':'Use as reference',()=>this.run(()=>this.host.approveReference({asset_key:row.key,candidate_id:candidate.id,expected_revision:row.approved?.revision??0})));
        accept.disabled=readonly||!!busy||row.status==='orphan'||candidate.input_fingerprint!==row.input_fingerprint||row.approved?.candidate_id===candidate.id;
        item.append(image,accept);if(candidate.input_fingerprint!==row.input_fingerprint)item.append(element('span','h3cr-status','Out of date'));candidates.append(item);
      }
      card.replaceChildren(title,used,candidates,description,prompt,this.partsPanel(row,readonly),controls,advanced);detail.append(card);
    }
    parts.push(workspace);this.body.replaceChildren(...parts);
    if(readonly)for(const input of this.body.querySelectorAll?.('input,textarea,select')??[])input.disabled=true;
    const again=focusKey&&[...this.body.querySelectorAll('[data-focus]')].find(n=>n.dataset.focus===focusKey);
    if(again){again.focus();if(selection&&again.setSelectionRange)again.setSelectionRange(...selection);}
  }
  objectForm() {
    if(this.objectEl)return this.objectEl;
    const form=element('div','h3cr-object'),name=element('input','h3ct-text'),description=element('input','h3ct-text');
    name.placeholder='Object name (weapon, car, prop…)';name.setAttribute('aria-label','New object reference name');
    description.placeholder='Visual description';description.setAttribute('aria-label','New object reference description');
    const label=element('label'),whole=element('input');whole.type='checkbox';whole.checked=true;label.append(whole,element('span',null,'Use throughout this scene'));
    const add=action('Add object reference',()=>{try{this.commit(state=>addObjectReference(state,{name:name.value,description:description.value,boxId:state.boxes[this.editor.selected]?.id,wholeScene:whole.checked}));}catch(error){this.message=error.message;this.render();}});
    form.append(name,description,label,add);this.objectEl=form;return form;
  }
}
