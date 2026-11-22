import {test} from 'node:test';
import assert from 'node:assert/strict';
import * as library from '../../../js/h3c_story_library.mjs';

const id='11111111-2222-4333-8444-555555555555';
const sequence='api_'+id.replaceAll('-','');
const assets=[{asset_id:'endpoint',bindings:[{kind:'picture',slot:'image17'}]}];
const project={id,sequence,revision:3,profile_sha256:'a'.repeat(64),assets};
const content=()=>({story:{state:'{"title":"Keep exact wording"}'},timeline:'{"boxes":[]}',sequence});

test('stripped Saved stories recover their verified project and missing bindings through a read-only lookup',async()=>{
  const saved=content(),before=structuredClone(saved),calls=[];
  const recovered=await library.recoverSavedStoryContent(saved,async path=>{calls.push(path);return project;});
  assert.deepEqual(calls,[`/h3c/api/v1/projects/${id}`]);
  assert.deepEqual(recovered.project,{mode:'attached',id,revision:3,profile_sha256:project.profile_sha256});
  assert.deepEqual(recovered.asset_bindings,assets);
  assert.equal(recovered.timeline,saved.timeline);assert.deepEqual(recovered.story,saved.story);
  assert.deepEqual(saved,before);
  recovered.asset_bindings[0].bindings[0].slot='image18';assert.equal(assets[0].bindings[0].slot,'image17');
});

test('an existing saved binding registry is preserved during attachment recovery',async()=>{
  const saved={...content(),asset_bindings:[]};
  const recovered=await library.recoverSavedStoryContent(saved,async()=>project);
  assert.deepEqual(recovered.asset_bindings,[]);
});

test('native sequences and intact attachments never perform recovery lookups',async()=>{
  for(const saved of [{...content(),sequence:'native-fork'},{...content(),sequence:'api_invalid'},
    {...content(),project:{mode:'attached',id}}]) {
    assert.equal(await library.recoverSavedStoryContent(saved,async()=>{throw Error('Unexpected lookup');}),saved);
  }
});

test('lookup failure and mismatched identity never downgrade a managed story to native',async()=>{
  const saved=content(),before=structuredClone(saved);
  await assert.rejects(library.recoverSavedStoryContent(saved,async()=>{throw Error('Project not found');}),/Project not found/);
  for(const value of [{...project,id:'other'},{...project,sequence:'api_'+'0'.repeat(32)},
    {...project,profile_sha256:''},{...project,revision:undefined}]) {
    await assert.rejects(library.recoverSavedStoryContent(saved,async()=>value),/does not match/);
  }
  assert.deepEqual(saved,before);
});
