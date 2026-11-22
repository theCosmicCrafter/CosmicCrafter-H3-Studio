import test from 'node:test';
import assert from 'node:assert/strict';
import {confirmRegeneration} from '../../../js/h3c_regeneration.mjs';
import {TimelineEditor} from '../../../js/h3c_timeline_editor.mjs';

function setup(overrides={}) {
  let current='unchanged', calls=[];
  const options={box:'a',count:1,body:{name:'seq',timeline:'{"boxes":[]}',settings:{}},snapshot:()=>current,
    request:async()=>({ok:true,needs_rebuild:true,number:1,reason:"Clip 2 has no saved overlap.",
      affected:[{id:'b',number:2},{id:'memory',number:5}],bridges:[{id:'memory',number:5}],replacements:[],
      receipt:{box:'a',fingerprint:'a'.repeat(64)}}),
    confirm:async dialog=>{calls.push(dialog);return true;},...overrides};
  return {options,calls,change:()=>{current='changed';}};
}

test('compatible regeneration queues without a dialog or receipt',async()=>{
  const s=setup({request:async()=>({ok:true,needs_rebuild:false})});
  assert.deepEqual(await confirmRegeneration(s.options),{cancelled:false,receipt:null});
  assert.equal(s.calls.length,0);
});

test('cancel returns without authorizing a render',async()=>{
  const s=setup({confirm:async()=>false});
  assert.deepEqual(await confirmRegeneration(s.options),{cancelled:true,receipt:null});
});

test('confirmation names actual affected clips and preservation before returning consent',async()=>{
  const s=setup(), result=await confirmRegeneration(s.options);
  assert.equal(result.receipt.box,'a');
  assert.equal(s.calls[0].title,'Regenerate clip 1 and rebuild continuity?');
  assert.match(s.calls[0].message,/Clips 2 and 5/);
  assert.match(s.calls[0].message,/Takes/);
  assert.match(s.calls[0].message,/successfully saves/);
  assert.match(s.calls[0].message,/Render remaining/);
  assert.match(s.calls[0].message,/bridge/i);
});

test('edits while the dialog or preflight is open reject consent',async()=>{
  const s=setup();s.options.confirm=async()=>{s.change();return true;};
  await assert.rejects(()=>confirmRegeneration(s.options),/changed.*again/);
  const t=setup();t.options.request=async()=>{t.change();return {ok:true,needs_rebuild:false};};
  await assert.rejects(()=>confirmRegeneration(t.options),/changed.*again/);
});

test('preflight failures do not ask for confirmation',async()=>{
  const s=setup({request:async()=>({ok:false,error:'Resolve width first.'})});
  await assert.rejects(()=>confirmRegeneration(s.options),/Resolve width/);
  assert.equal(s.calls.length,0);
});

test('an incompatible batch requires one recovery take before further takes',async()=>{
  const s=setup({count:3});
  await assert.rejects(()=>confirmRegeneration(s.options),/one take/);
  assert.equal(s.calls.length,0);
});

function editor(preflight) {
  const queued=[], state={boxes:[{id:'a',seed:123,seed_mode:'randomize'}]};
  const value=Object.assign(Object.create(TimelineEditor.prototype),{state,selected:0,host:{preflight,
    queue:async(...args)=>queued.push(args)},renderHead(){},renderPanelInfo(){},commit(){},setStatus(status){this.status=status;}});
  return {value,queued};
}

test('real editor cancels before changing the seed or queueing',async()=>{
  const {value,queued}=editor(async()=>({cancelled:true}));
  const outcome=await value.queueBox();
  assert.equal(outcome.queued,0);
  assert.equal(value.state.boxes[0].seed,123);
  assert.deepEqual(queued,[]);
});

test('real editor transports consent after confirmation and seed selection',async()=>{
  const receipt={box:'a',fingerprint:'a'.repeat(64)};
  const {value,queued}=editor(async()=>({cancelled:false,receipt}));
  const outcome=await value.queueBox();
  assert.equal(outcome.queued,1);
  assert.notEqual(value.state.boxes[0].seed,123);
  assert.deepEqual(queued,[[1,1,null,receipt]]);
});

test('real editor stops if selection changes while preflight is open',async()=>{
  const {value,queued}=editor(async()=>{value.state.boxes[0].id='other';return {receipt:{box:'a'}};});
  const outcome=await value.queueBox();
  assert.equal(outcome.queued,0);
  assert.equal(value.state.boxes[0].seed,123);
  assert.deepEqual(queued,[]);
});
