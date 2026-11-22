import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ProjectSession, ownedSettings, projectErrorMessage} from '../../../js/h3c_project.mjs?v=0882b8a6265a';
import {independentStoryContent, recoverSavedStoryContent} from '../../../js/h3c_story_library.mjs?v=8b88866ede39';

const ID='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
const managed={story:{state:'{}'},timeline:'{"boxes":[]}',sequence:'api_'+'a'.repeat(32),renders:true,
  project:{mode:'attached',id:ID,revision:1,profile_sha256:'profile'},asset_bindings:[{asset_id:'x',bindings:[]}]};

test('a managed story opened in a differently wired workflow loads as an independent copy', async()=>{
  const copy=independentStoryContent({...managed,wiring:false},{sequence:()=>'timeline_new'});
  assert.equal(copy.independent,true);
  assert.equal(copy.sequence,'timeline_new');
  assert.equal(copy.project,undefined);
  assert.equal(copy.asset_bindings,undefined);
  assert.equal(copy.timeline,managed.timeline);
  // Recovery must not attach it again through the reserved sequence.
  let asked=0;
  const recovered=await recoverSavedStoryContent(copy,async()=>{asked++;return {};});
  assert.equal(asked,0);
  assert.equal(recovered.project,undefined);
});

test('a story whose attachment was stripped still loads independently in another workflow', ()=>{
  const {project,asset_bindings,...stripped}=managed;
  const copy=independentStoryContent({...stripped,wiring:false},{sequence:()=>'timeline_new'});
  assert.equal(copy.sequence,'timeline_new');
  assert.equal(copy.independent,true);
});

test('the project\'s own workflow and unmanaged stories load as before', ()=>{
  const own={...managed,wiring:true};
  assert.equal(independentStoryContent(own),own);
  // A workflow whose Timeline is already attached to this project keeps the attachment, also when only its
  // reserved sequence still names the project.
  const edited={...managed,wiring:false};
  assert.equal(independentStoryContent(edited,{attached:ID}),edited);
  const {project,asset_bindings,...stripped}=edited;
  assert.equal(independentStoryContent(stripped,{attached:ID}),stripped);
  assert.equal(independentStoryContent(edited,{attached:'another-project'}).independent,true);
  const native={story:{},timeline:'{}',sequence:'paper_moon',renders:true,wiring:false};
  assert.equal(independentStoryContent(native),native);
});

test('settings fed by a link are left out and dropdown numbers are sent as numbers', ()=>{
  assert.deepEqual(ownedSettings({width:null,height:undefined,context_frames:'39',carry_audio:false,ref_image_size:'max',audio_context_frames:0}),
    {context_frames:39,carry_audio:false,ref_image_size:'max',audio_context_frames:0});
  assert.deepEqual(ownedSettings(undefined),{});
});

function session(local) {
  const server={id:'p',profile_sha256:'profile',revision:1,sequence:'api_p',name:'Project',
    timeline:{boxes:[{id:'a',prompt:'One',frames:107}]},settings:{width:1376,height:768},assets:[],
    inspection:{settings:{width:1376,height:768,context_frames:39,carry_audio:false,ref_image_size:'max',audio_context_frames:0}}};
  const calls=[];
  const project=new ProjectSession({metadata:{mode:'attached',id:'p',profile_sha256:'profile',revision:1},
    read:()=>local.value,apply:value=>{local.value={timeline:structuredClone(value.timeline),assets:structuredClone(value.assets??[]),
      // The node's width and height are fed by links, so those widgets read as null whatever is applied.
      settings:{...structuredClone(value.settings),width:null,height:null}};},
    request:async(path,options={})=>{calls.push({path,...options});
      if(options.method==='PUT')Object.assign(server,structuredClone(options.body),{revision:server.revision+1});
      return structuredClone(server);}});
  return {project,calls,server};
}

test('saving from a workflow with linked size sends only the settings changed here', async()=>{
  const local={value:{timeline:{boxes:[{id:'a',prompt:'One',frames:107}]},settings:{},assets:[]}};
  const f=session(local);
  await f.project.load();
  local.value.timeline.boxes[0].prompt='Two';
  await f.project.save();
  const first=f.calls.find(call=>call.method==='PUT').body;
  assert.deepEqual(first.settings,{width:1376,height:768});
  assert.equal(first.timeline.boxes[0].prompt,'Two');
  local.value.settings.context_frames='90';
  await f.project.save();
  assert.deepEqual(f.calls.filter(call=>call.method==='PUT').at(-1).body.settings,{width:1376,height:768,context_frames:90});
});

test('a project refusal names the field the server points at', ()=>{
  assert.equal(projectErrorMessage({error:{message:'Value does not satisfy type constraint.',path:'/settings/width'}},400),
    'Value does not satisfy type constraint. (/settings/width)');
  assert.equal(projectErrorMessage({error:{message:'Project revision has changed.',path:''}},409),'Project revision has changed.');
  assert.equal(projectErrorMessage({},502),'Project HTTP 502');
});
