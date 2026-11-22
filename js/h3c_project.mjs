// Project transport owns revisions and jobs; no native graph or owner token enters the browser.
const PREFIX = '/h3c/api/v1';
const same = (a,b) => stringifyJSON(a) === stringifyJSON(b);

/** One status line for a job, naming a held job it waits behind (Timeline API `blocked_by`). */
export function renderStatus(job) {
  const line=`Render ${job.state}: ${job.progress?.completed??0}/${job.progress?.total??0} units`;
  const held=job.blocked_by;
  return held?`${line}; waiting behind held job ${held.job_id} (${held.error_code??held.state}). Resume or abandon that job to continue.`:line;
}
const cloneJSON = value => value === undefined ? undefined : parseJSON(stringifyJSON(value));
const token = () => crypto.randomUUID().replaceAll('-','');

function editFields(original,base,edited) {
  const result=cloneJSON(original??{});
  for(const key of new Set([...Object.keys(base??{}),...Object.keys(edited??{})])) {
    if(same(base?.[key],edited?.[key])) continue;
    if(Object.hasOwn(edited??{},key)) result[key]=cloneJSON(edited[key]);else delete result[key];
  }
  return result;
}

function editedStillItems(original=[],base=[],edited=[],identity) {
  return edited.map(item=>{
    const saved=original.find(value=>identity(value)===identity(item)),before=base.find(value=>identity(value)===identity(item));
    const result=editFields(saved,before,item);
    if(!same(before?.images,item.images) && Array.isArray(item.images)) result.images=editedStillItems(saved?.images,before?.images,item.images,
      image=>stringifyJSON([image.request_id,image.prompt_id,image.batch_index]));
    return result;
  });
}

function editedTimeline(original,base,edited) {
  const result=editFields(original,base,edited);
  if(!same(base.still_requests,edited.still_requests) && Array.isArray(edited.still_requests))
    result.still_requests=editedStillItems(original.still_requests,base.still_requests,edited.still_requests,
      item=>stringifyJSON([item.request_id,item.prompt_id]));
  result.boxes=edited.boxes.map(box=>{
    const saved=original.boxes.find(item=>item.id===box.id),before=base.boxes.find(item=>item.id===box.id);
    const value=editFields(saved,before,box);
    if(!same(before?.previews,box.previews) && Array.isArray(box.previews)) value.previews=editedStillItems(saved?.previews,before?.previews,box.previews,
      item=>stringifyJSON(item.target??(item.shot===1?{kind:'first'}:{kind:'shot',shot:item.shot})));
    return value;
  });
  return result;
}

// Integers past 2^53 (seeds, file stamps) keep every digit as BigInt. Browsers that give a reviver each number's source
// text and accept raw JSON (Chrome 114+) do it without rewriting the whole text; the others use a marker for each.
const SOURCE_TEXT = (() => {
  let source;
  JSON.parse('1', (key, value, context) => { source = context?.source; return value; });
  return source === '1';
})();
const RAW_JSON = typeof JSON.rawJSON === 'function';
const keepInteger = (key, value, context) => typeof value === 'number' && !Number.isSafeInteger(value)
  && /^-?\d+$/.test(context?.source ?? '') ? BigInt(context.source) : value;
const rawInteger = (key, item) => typeof item === 'bigint' ? JSON.rawJSON(item.toString()) : item;

export function parseJSON(text) {
  if (SOURCE_TEXT) return JSON.parse(String(text), keepInteger);
  const integers = [], marker = `__h3c_int_${token()}_`;
  const source = String(text).replace(/"(?:\\.|[^"\\])*"|(-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)/g,(literal,number) => {
    if (!number || !/^-?\d+$/.test(number) || Number.isSafeInteger(Number(number))) return literal;
    integers.push(BigInt(number)); return JSON.stringify(marker+(integers.length-1));
  });
  return JSON.parse(source,(key,value) => typeof value === 'string' && value.startsWith(marker)
    ? integers[Number(value.slice(marker.length))] : value);
}

export function stringifyJSON(value) {
  if (RAW_JSON) return JSON.stringify(value, rawInteger);
  const integers = [], marker = `__h3c_int_${token()}_`;
  const text = JSON.stringify(value,(key,item) => {
    if (typeof item !== 'bigint') return item;
    integers.push(item.toString()); return marker+(integers.length-1);
  });
  return text?.replace(new RegExp(`"${marker}(\\d+)"`,'g'),(literal,index)=>integers[Number(index)]);
}

export function seedValue(value) {
  try {
    if (typeof value === 'number') return Number.isSafeInteger(value) && value >= 0 ? value : undefined;
    if (typeof value !== 'bigint' && !/^\d+$/.test(String(value))) return undefined;
    const seed = BigInt(value);
    if (seed < 0n || seed > 18446744073709551615n) return undefined;
    return seed <= BigInt(Number.MAX_SAFE_INTEGER) ? Number(seed) : seed;
  } catch { return undefined; }
}

const INTEGER_SETTINGS = ['width','height','context_frames','audio_context_frames'];

/** The settings this Timeline node itself holds. A widget fed by a link reads as null: another node owns that value,
 *  so it is left out. A dropdown stores its number as text; the project contract wants the number. */
export function ownedSettings(settings) {
  const result={};
  for(const [key,value] of Object.entries(settings??{})) {
    if(value==null) continue;
    result[key]=INTEGER_SETTINGS.includes(key)&&typeof value==='string'&&/^\d+$/.test(value.trim())?Number(value):value;
  }
  return result;
}

/** A project API refusal as one line, naming the field the server points at. */
export function projectErrorMessage(result,status) {
  const error=result?.error,message=error?.message??`Project HTTP ${status}`;
  return error?.path?`${message} (${error.path})`:message;
}

export function forkProject(node) {
  const properties = node.properties ??= {};
  const widget = node.widgets?.find(item=>item.name==='name');
  if (properties.h3c_project?.mode === 'fork') {
    properties.h3c_fork_sequence ??= 'timeline_'+token();
    if (widget) widget.value=properties.h3c_fork_sequence;
    delete properties.h3c_project;
  }
  return properties.h3c_fork_sequence ?? widget?.value;
}

export class ProjectSession {
  constructor({metadata,request,read,apply,status=()=>{},session={},delay=ms=>new Promise(resolve=>setTimeout(resolve,ms))}) {
    Object.assign(this,{metadata,request,read,apply,status,delay,session});
    if (metadata?.mode !== 'attached') throw new Error('ProjectSession requires explicit attached mode.');
    this.pending=Promise.resolve();
  }
  get project(){return this.session.project;} set project(value){this.session.project=value;}
  get base(){return this.session.base;} set base(value){this.session.base=value;}
  get conflict(){return this.session.conflict;} set conflict(value){this.session.conflict=value;}

  serial(action) {
    const next=this.pending.catch(()=>{}).then(async()=>{
      if(this.gone) throw new Error('Project session closed.');
      this.busy=true;try{return await action();}finally{this.busy=false;}
    });
    this.pending=next; return next;
  }

  path(suffix='') { return `${PREFIX}/projects/${encodeURIComponent(this.metadata.id)}${suffix}`; }
  value() {
    const local=this.read();
    return {timeline:typeof local.timeline==='string'?parseJSON(local.timeline):cloneJSON(local.timeline),
      settings:ownedSettings(cloneJSON(local.settings)),assets:cloneJSON(local.assets??this.project?.assets??[])};
  }
  body() {
    const value=this.value(),timeline=editedTimeline(this.project.timeline,this.base.timeline,value.timeline);
    const semantic=cloneJSON(this.project.semantic_boxes??{});
    for(const box of value.timeline.boxes) {
      if(!same(box.prompt,this.base.timeline.boxes.find(item=>item.id===box.id)?.prompt)) delete semantic[box.id];
    }
    return {...Object.fromEntries(['name','consumer'].filter(key=>this.project?.[key]!==undefined)
      .map(key=>[key,cloneJSON(this.project[key])])),...value,
      // Only what was changed here goes back: the project keeps the settings it was authored with.
      settings:editFields(this.project.settings,this.base.settings,value.settings),
      timeline,semantic_boxes:semantic,expected_revision:this.project.revision};
  }
  install(project, before) {
    if(this.gone) return;
    if(project.profile_sha256!==this.metadata.profile_sha256) throw new Error('Attached project profile does not match this workflow.');
    const edited=before?this.value():null;
    this.project=project; this.metadata.revision=project.revision;
    this.apply({...project,timeline:project.inspection?.timeline??project.timeline,settings:project.inspection?.settings??project.settings});
    this.base=this.value(); this.conflict=null;
    if(before && !same(before,edited)) this.apply({...project,
      timeline:editedTimeline(this.base.timeline,before.timeline,edited.timeline),
      settings:editFields(this.base.settings,before.settings,edited.settings),
      assets:same(before.assets,edited.assets)?this.base.assets:edited.assets});
    this.status(`Project revision ${project.revision} saved on this server`);
  }
  load(options) { return this.serial(()=>this._load(options)); }
  async _load({preserveLocal=false}={}) {
    if(this.project&&!preserveLocal) return this._refresh();
    const before=this.value(); const project=await this.request(this.path());
    const local=this.value();
    if(!preserveLocal&&!same(before,local)) {this.conflict=project; this.status('Local edits changed while loading; choose which edits to keep.',true); return;}
    this.install(project);
    if(preserveLocal&&!this.gone&&!same(local,this.base)) {
      this.apply(local);this.conflict=project;
      this.status('Saved story differs from the project; choose which edits to keep.',true);
    }
    return project;
  }
  save() {return this.serial(()=>this._save());}
  async _save() {
    if(!this.project) await this._load();
    if(this.conflict) throw new Error('Resolve the project conflict before saving.');
    if(same(this.value(),this.base)) return this.project;
    const local=this.value();
    try {
      const saved=await this.request(this.path(),{method:'PUT',body:this.body()});
      // Edits made during an in-flight PUT remain local for the next save.
      this.install(saved,local);
      return saved;
    } catch(error) {
      if(error.status===409) {
        this.conflict=await this.request(this.path());
        this.status(error.code==='project_busy'?'Project busy; local edits are preserved. Resume its job, then resolve this conflict.'
          :'Project changed in another editor; local edits are preserved. Choose which edits to keep.',true);
      } else this.status(`Project not saved: ${error.message}`);
      throw error;
    }
  }
  resolve(useSaved) {return this.serial(async()=>{
    if(!this.conflict) return;
    const current=await this.request(this.path());
    if(current.active_job || current.active_operation) throw new Error('Project is busy; wait for its current operation.');
    if(useSaved) this.install(current);
    else {this.project=current;this.metadata.revision=current.revision;this.conflict=null;await this._save();}
  });}
  refresh() {return this.serial(()=>this._refresh());}
  async _refresh() {
    const current=await this.request(this.path());
    if(!this.project) {this.install(current);return current;}
    if(current.revision!==this.project.revision) {
      if(!same(this.value(),this.base)) {this.conflict=current;this.status('Project changed; local edits are preserved. Choose which edits to keep.',true);}
      else this.install(current);
    } else this.project={...this.project,status:current.status,active_job:current.active_job,active_operation:current.active_operation};
    if(current.active_job) {
      this.job=await this.request(`${PREFIX}/jobs/${encodeURIComponent(current.active_job)}`);
      this.status(renderStatus(this.job));
    } else if(!this.conflict) this.status(current.active_operation?'Project operation is being reconciled.'
      :same(this.value(),this.base)?`Project revision ${current.revision} saved on this server`:'Local edits waiting to save.');
    return current;
  }
  async wait(id,{deadline=3600000}={}) {
    const until=Date.now()+deadline;
    while(!this.gone) {
      const job=await this.request(`${PREFIX}/jobs/${encodeURIComponent(id)}`);this.job=job;
      this.status(renderStatus(job));
      if(job.state==='succeeded') return job;
      if(['failed','needs_reconciliation'].includes(job.state)) throw new Error(job.error?.message??`Render ${job.state}`);
      if(Date.now()>=until) throw new Error('Render polling deadline reached; the job remains available after reload.');
      await this.delay(1000);
    }
    throw new Error('Project session closed; the job remains on the server.');
  }
  render({count=1,boxId,bridgeId,receipt}={}) {return this.serial(async()=>{
    if(!Number.isInteger(count)||count<1||count>10) throw new Error('Choose 1 to 10 takes.');
    if(!this.project) await this._load();
    if(this.metadata.pending_render) {
      const pending=this.metadata.pending_render;
      const existing=await this.request(this.path('/jobs'),{method:'POST',body:pending.body,headers:{'Idempotency-Key':pending.key}});
      this.metadata.job_id=existing.id;delete this.metadata.pending_render;
      const completed=await this.wait(existing.id);await this._refresh();return completed;
    }
    if(this.project.active_job) {await this.wait(this.project.active_job);await this._refresh();}
    let completed;
    for(let run=0;run<count;run++) {
      await this._save();
      const selection=boxId?{kind:'boxes',ids:[boxId],rerender:true}:bridgeId?{kind:'boxes',ids:[bridgeId]}:{kind:'all'};
      if(receipt) selection.rebuild_continuity=receipt;
      const plan=await this.request(this.path('/plan'),{method:'POST',body:{expected_revision:this.project.revision,selection}});
      const key=crypto.randomUUID(); this.metadata.pending_render={key,body:{expected_revision:this.project.revision,selection,plan_sha256:plan.plan_sha256}};
      const job=await this.request(this.path('/jobs'),{method:'POST',body:this.metadata.pending_render.body,headers:{'Idempotency-Key':key}});
      this.metadata.job_id=job.id; delete this.metadata.pending_render;
      completed=await this.wait(job.id);await this._refresh();
      if(run<count-1) {
        const local=this.read(),line=typeof local.timeline==='string'?parseJSON(local.timeline):cloneJSON(local.timeline);
        const selected=bridgeId?line.bridges?.find(item=>item.before===bridgeId):line.boxes.find(item=>item.id===boxId);
        if(!selected) throw new Error('Multiple takes require a selected box or bridge.');
        const previous=selected.seed; do {selected.seed=Math.floor(Math.random()*2**32);} while(selected.seed===previous);
        this.apply({...this.project,...local,timeline:line});
      }
    }
    return completed;
  });}
  takes(action,body) {return this.serial(async()=>{
    if(!this.project) await this._load();
    if(action==='list') return this.request(this.path(`/takes?box=${encodeURIComponent(body.box)}`));
    if(action==='delete') throw new Error('The project API does not delete takes.');
    await this._save();
    const before=this.value();
    const selected=await this.request(this.path('/takes/use'),{method:'POST',body:{expected_revision:this.project.revision,
      kind:body.bridge?'bridge':'box',box:body.box,take_id:body.take_id??body.take}});
    this.install(selected,before);return {ok:true,project:selected};
  });}
  destroy() {this.gone=true;}
}
