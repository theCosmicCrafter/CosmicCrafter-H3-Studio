import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ProjectSession} from '../../../js/h3c_project.mjs?v=0882b8a6265a';

function fixture({cached=false,matching=false}={}) {
  const server={id:'p',profile_sha256:'profile',revision:2,sequence:'api_p',name:'Project',
    timeline:{boxes:[{id:'a',prompt:'Server prompt',frames:105}]},settings:{width:512},assets:[]};
  const saved=matching?structuredClone(server):{timeline:{boxes:[{id:'a',prompt:'Saved prompt',frames:105}]},
    settings:{width:1024},assets:[{asset_id:'first',bindings:[{kind:'picture',slot:'image17'}]}]};
  let local=structuredClone(saved);
  const calls=[],messages=[];
  const project=new ProjectSession({metadata:{mode:'attached',id:'p',profile_sha256:'profile',revision:1},
    session:cached?{project:structuredClone(server),base:structuredClone(server)}:{},
    read:()=>local,apply:value=>{local=structuredClone(value);},status:(...value)=>messages.push(value),
    request:async(path,options={})=>{calls.push({path,...options});
      if(options.method==='PUT')Object.assign(server,structuredClone(options.body),{revision:server.revision+1});
      return structuredClone(server);}});
  const value=()=>({timeline:local.timeline,settings:local.settings,assets:local.assets});
  return {project,server,saved,calls,messages,value};
}

test('Saved-story attachment preserves differing local content, bindings and settings until conflict resolution', async()=>{
  for(const cached of [false,true]) {
    const f=fixture({cached});
    await f.project.load({preserveLocal:true});
    assert.deepEqual(f.value(),f.saved);
    assert.deepEqual(f.project.base,{timeline:f.server.timeline,settings:f.server.settings,assets:f.server.assets});
    assert.equal(f.project.metadata.revision,2);
    assert.equal(f.project.conflict.id,'p');
    assert.equal(f.messages.at(-1)[1],true);
    await assert.rejects(f.project.save(),/Resolve the project conflict/);
    assert.deepEqual(f.calls.map(call=>call.method??'GET'),['GET']);
  }
});

test('Keep my edits saves the preserved snapshot against the current managed revision', async()=>{
  const f=fixture();await f.project.load({preserveLocal:true});await f.project.resolve(false);
  assert.equal(f.project.conflict,null);
  assert.deepEqual(f.value(),f.saved);
  const write=f.calls.find(call=>call.method==='PUT');
  assert.equal(write.body.expected_revision,2);
  assert.deepEqual(write.body.timeline,f.saved.timeline);
  assert.deepEqual(write.body.assets,f.saved.assets);
  assert.deepEqual(write.body.settings,f.saved.settings);
});

test('Load project edits explicitly replaces the snapshot without writing to the project', async()=>{
  const f=fixture();await f.project.load({preserveLocal:true});assert.equal(f.project.conflict.id,'p');
  await f.project.resolve(true);
  assert.equal(f.project.conflict,null);
  assert.deepEqual(f.value(),{timeline:f.server.timeline,settings:f.server.settings,assets:f.server.assets});
  assert.ok(f.calls.every(call=>!call.method));
});

test('matching Saved stories and ordinary attached workflow loads keep their existing initial-load behavior', async()=>{
  const matching=fixture({matching:true});await matching.project.load({preserveLocal:true});
  assert.equal(matching.project.conflict,null);
  const ordinary=fixture();await ordinary.project.load();
  assert.equal(ordinary.project.conflict,null);
  assert.deepEqual(ordinary.value(),{timeline:ordinary.server.timeline,settings:ordinary.server.settings,assets:ordinary.server.assets});
});
