import test from 'node:test';
import assert from 'node:assert/strict';
import {startGeneration,useGeneration} from '../../../js/h3c_generations.mjs';

function setup(overrides={}) {
  const calls=[];let revision=1;
  const options={body:()=>({name:'old',timeline:'exact prompts and Timeline',settings:{width:64}}),
    snapshot:()=>revision,check:()=>{},confirm:async()=>true,save:async()=>calls.push('save'),
    request:async(path,body)=>{calls.push({path,body});return {ok:true,name:'new'};},
    apply:async result=>calls.push({apply:result.name}),...overrides};
  return {options,calls,change:()=>{revision++;}};
}

test('cancel keeps the current generation without saving or requesting a new one',async()=>{
  const s=setup({confirm:async()=>false});
  assert.equal(await startGeneration(s.options),false);
  assert.deepEqual(s.calls,[]);
});

test('saves first and changes identity only after the server preserves the old generation',async()=>{
  const s=setup();
  assert.equal(await startGeneration(s.options),true);
  assert.equal(s.calls[0],'save');
  assert.equal(s.calls[1].path,'/h3c/generations/start');
  assert.equal(s.calls[1].body.timeline,'exact prompts and Timeline');
  assert.deepEqual(s.calls[2],{apply:'new'});
});

test('failure and edits during a request leave current generation active',async()=>{
  const s=setup({request:async()=>({ok:false,error:'disk full'})});
  await assert.rejects(()=>startGeneration(s.options),/disk full/);
  assert.equal(s.calls.length,1);
  const t=setup();t.options.request=async()=>{t.change();return {ok:true,name:'new'};};
  await assert.rejects(()=>startGeneration(t.options),/changed/);
  assert.deepEqual(t.calls,['save']);
});

test('busy work blocks a new generation before confirmation',async()=>{
  let asked=false;
  const s=setup({check:()=>{throw Error('Rendering is busy');},confirm:async()=>{asked=true;return true;}});
  await assert.rejects(()=>startGeneration(s.options),/busy/);
  assert.equal(asked,false);
});

test('changing identity preserves Timeline, prompts, seeds, references and source bindings',()=>{
  const timeline={name:'timeline',value:'exact JSON including seeds and references'};
  const assets=[{asset_id:'old-source'}];
  const node={widgets:[{name:'name',value:'old'},timeline],
    properties:{h3c_project:{mode:'attached',id:'old-api-project'},h3c_asset_bindings:assets},
    inputs:[{name:'name',link:1},{name:'timeline',link:2}],disconnectInput(index){this.inputs[index].link=null;}};
  useGeneration(node,'fresh');
  assert.equal(node.widgets[0].value,'fresh');
  assert.equal(timeline.value,'exact JSON including seeds and references');
  assert.equal(node.properties.h3c_asset_bindings,assets);
  assert.equal(node.properties.h3c_fork_sequence,'fresh');
  assert.equal(node.properties.h3c_project,undefined);
  assert.equal(node.inputs[0].link,null);
  assert.equal(node.inputs[1].link,2);
});
