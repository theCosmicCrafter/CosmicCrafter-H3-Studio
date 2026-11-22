"""Actual Saved stories host methods against synthetic storage; no ComfyUI, uploads or rendering."""
from pathlib import Path
from urllib.parse import unquote, urlparse
import os

from playwright.sync_api import sync_playwright

ROOT = Path.cwd().resolve()
FIXTURE = r'''<!doctype html><html><body><script>
window.fixtureApp={registerExtension(){},ui:{settings:{getSettingValue:()=>false}}};
window.fixtureApi={fetchApi:(...args)=>window.request(...args)};
</script><script type="module">
import {StoryHost} from '/web/h3c_story.js';
import {TimelineHost} from '/web/h3c_timeline.js';
import {parseJSON,stringifyJSON} from '/web/h3c_project.mjs';
const assert=(ok,message)=>{if(!ok)throw Error(message);};
const project={mode:'attached',id:'11111111-2222-4333-8444-555555555555',profile_sha256:'synthetic-profile',revision:1};
const assets=[{asset_id:'first',bindings:[{kind:'picture',slot:'image17'}]},
 {asset_id:'last',bindings:[{kind:'picture',slot:'image18'}]}];
const line=stringifyJSON({version:1,boxes:Array.from({length:8},(_,i)=>({id:`b${i}`,frames:105,
 prompt:`Exact prompt ${i}`,first:'image17',last:'image18',...(i?{}:{cut:true}),seed:18446744073709551615n})),
 audio_clips:[{slot:'audio1',file:{filename:'synthetic.wav',type:'input'},duration:35}],
 timed_text:{cues:Array.from({length:19},(_,i)=>({text:`Lyric ${i}`,start:i,end:i+1}))}});
const storyFields={state:JSON.stringify({title:'Synthetic',timeline:'2'}),idea:'Keep the idea',idea_images:'[]',template:'custom'};
const serialized=(id,type,fields,properties={})=>({id,type,properties,
 inputs:Object.keys(fields).map(name=>({name,widget:{name}})),widgets_values:Object.values(fields)});
const saved={workflow:{nodes:[serialized(1,'H3C_Story',storyFields),
 serialized(2,'H3C_Timeline',{name:'api_11111111222243338444555555555555',timeline:line,width:512},
 {h3c_project:project,h3c_asset_bindings:assets})],links:[]},story:'1',sequence:'api_11111111222243338444555555555555',
 graph:'saved-graph',id:'saved-library',workflow_revision:4};
window.run=async()=>{
 const calls=[];
 const server={id:project.id,profile_sha256:project.profile_sha256,revision:1,sequence:saved.sequence,
  timeline:parseJSON(line),settings:{width:1024},assets,status:{ok:true,next:'b0'},active_job:null,active_operation:null};
 window.request=async(path,options={})=>{
  calls.push([path,options.method??'GET']);
  assert(path===`/h3c/api/v1/projects/${project.id}`,'Unexpected transport: '+path);
  assert(!options.method||options.method==='GET','Loading must not mutate the project');
  return {ok:true,status:200,text:async()=>stringifyJSON(server)};
 };
 const graph={id:'synthetic-graph',extra:{},links:{101:[101,30,0,20,0],102:[102,31,0,20,1]},getNodeById(id){return this._nodes.find(n=>n.id===id);},
  serialize(){return {nodes:this._nodes.map(n=>({...serialized(n.id,n.type,Object.fromEntries(n.widgets.map(w=>[w.name,w.value])),n.properties),inputs:n.inputs})),
   links:Object.values(this.links)};}};
 const make=(id,type,fields)=>({id,type,graph,properties:{},inputs:Object.keys(fields).map(name=>({name,widget:{name}})),
  widgets:Object.entries(fields).map(([name,value])=>({name,value})),setDirtyCanvas(){}});
 const node=make(20,'H3C_Timeline',{name:'old-native',timeline:'{"version":1,"boxes":[]}',width:1024});
 const source=make(10,'H3C_Story',storyFields);
 const textName=make(30,'PrimitiveString',{value:'old-native'}),textLine=make(31,'PrimitiveStringMultiline',{value:node.widgets[1].value});
 node.inputs[0].link=101;node.inputs[1].link=102;
 const generator=make(40,'SyntheticGenerator',{steps:8});
 graph._nodes=[source,node,textName,textLine,generator];fixtureApp.graph=fixtureApp.rootGraph=graph;
 const host=Object.assign(Object.create(TimelineHost.prototype),{node,widget:node.widgets[1],face:{root:document.createElement('div')},
  saved:{ready:Promise.resolve(),destroy(){},changed(){}},editor:{host:{},load(){},markStale(){},setStatus(value){this.status=value;}},
  schedule(){},showProgress(){},recoverStills(){},recoverReferences(){}});
 node.h3cTimeline=host;
 const story=Object.assign(Object.create(StoryHost.prototype),{node:source,timelines:()=>[node],
  saved:{suspend:async()=>()=>{},changed(){}},panel:{say(){},showLibraryConflict(){}},libraryBusy:()=>false,
  openStudio(){},showState(){}});
 try {
  // A managed story loaded into another workflow runs there as an independent copy; the project is never contacted.
  await story.loadLibrary(structuredClone(saved));
  assert(!host.project&&!node.properties.h3c_project&&!node.properties.h3c_asset_bindings,'Another workflow attached to the managed project');
  assert(/^timeline_[a-f0-9]{32}$/.test(node.properties.h3c_fork_sequence)&&textName.widgets[0].value===node.properties.h3c_fork_sequence,'Independent copy kept the managed sequence');
  assert(stringifyJSON(parseJSON(host.widget.value))===line&&textLine.widgets[0].value===line,'Independent copy changed the Timeline');
  assert(graph.extra.h3c_story_id!==saved.graph&&!story.libraryId,'Independent copy took over the managed story entry');
  assert(node.widgets[2].value===1024&&generator.widgets[0].value===8,'Independent copy changed destination settings');
  assert(calls.length===0,'Independent copy contacted the managed project');

  // The project's own workflow, already attached to it, keeps the attachment.
  node.properties.h3c_project=structuredClone(project);
  await story.loadLibrary(structuredClone(saved));
  assert(node.properties.h3c_project?.id===project.id,'Saved stories dropped attached project metadata');
  assert(stringifyJSON(node.properties.h3c_asset_bindings)===stringifyJSON(assets),'Saved stories dropped bindings');
  assert(node.properties.h3c_fork_sequence===undefined,'Managed sequence must not become a native fork');
  await host.saved.ready;await host.refresh();
  assert(host.project&&host.editor.host.projectAttached,'Managed ProjectSession not configured');
  assert(host.editor.status?.ok&&host.editor.status.next==='b0','Managed status not displayed');
  assert(calls.length===2,'Expected only managed load and refresh GETs');
  assert(stringifyJSON(parseJSON(host.widget.value))===line,'Timeline content changed');
  assert(textLine.widgets[0].value===line&&textName.widgets[0].value===saved.sequence,'Connected text controls not updated');
  assert(node.inputs[0].link===101&&node.inputs[1].link===102&&generator.widgets[0].value===8,'Generator wiring changed');
  assert(parseJSON(source.widgets[0].value).timeline==='20','Story target was not remapped');
  assert(graph.extra.h3c_story_id===saved.graph&&story.libraryId===saved.id,'Library identity not retained');
  assert(project.revision===1&&assets[0].bindings[0].slot==='image17','Saved snapshot mutated');

  const stripped=structuredClone(saved);
  stripped.workflow.nodes[1].properties={h3c_fork_sequence:saved.sequence};
  await story.loadLibrary(stripped);await host.saved.ready;await host.refresh();
  assert(node.properties.h3c_project?.id===project.id,'Previously stripped Saved story stayed detached');
  assert(stringifyJSON(node.properties.h3c_asset_bindings)===stringifyJSON(assets),'Previously stripped bindings not recovered');
  assert(host.editor.status?.ok&&host.editor.status.next==='b0','Recovered project status not displayed');
  assert(stringifyJSON(parseJSON(host.widget.value))===line&&textLine.widgets[0].value===line,'Recovery replaced saved content');
  assert(!stripped.workflow.nodes[1].properties.h3c_project,'Recovery mutated saved snapshot');
  assert(calls.length===5,'Expected recovery lookup plus managed load/status GETs');

  // A differing API snapshot must offer the existing conflict choices, preserving local content/settings.
  server.timeline.boxes[0].prompt='Newer API prompt';server.settings.width=512;server.assets=[];
  await story.loadLibrary(structuredClone(saved));await host.saved.ready;
  assert(host.project.conflict,'Differing API snapshot must require a choice');
  assert(stringifyJSON(parseJSON(host.widget.value))===line,'API attachment overwrote saved Timeline');
  assert(node.widgets[2].value===1024,'API attachment overwrote destination settings');
  assert(stringifyJSON(node.properties.h3c_asset_bindings)===stringifyJSON(assets),'API attachment overwrote saved bindings');
  let blocked=false;try{await host.project.save();}catch(error){blocked=/Resolve the project conflict/.test(error.message);}
  assert(blocked&&calls.length===6,'Unresolved saved-story conflict wrote to API project');

  // A generation archive result deliberately has no project attachment or asset registry.
  story.applyGeneration({story:storyFields,timeline:line,sequence:'native-import'});
  assert(!host.project&&!host.editor.host.projectAttached,'Archive import stayed attached');
  assert(!node.properties.h3c_project&&!node.properties.h3c_asset_bindings,'Archive import kept obsolete metadata');
  assert(node.properties.h3c_fork_sequence==='native-import','Archive import lost its native sequence');
  assert(node.inputs[0].link===101&&node.inputs[1].link===102,'Archive import broke text wiring');

  const native=structuredClone(saved);native.sequence='native-saved';
  native.workflow.nodes[1].properties={h3c_project:{mode:'fork',id:project.id},h3c_asset_bindings:assets};
  await story.loadLibrary(native);
  assert(!host.project&&!node.properties.h3c_project,'Native saved fork reattached to original project');
  assert(node.properties.h3c_fork_sequence==='native-saved','Native saved sequence changed');
  assert(stringifyJSON(node.properties.h3c_asset_bindings)===stringifyJSON(assets),'Native saved bindings lost');
  assert(calls.length===6,'Native transfers contacted managed project');
  node.properties.h3c_project=structuredClone(project);
  const beforeFailure=JSON.stringify(graph.serialize());
  window.request=async path=>{calls.push([path,'GET']);return {ok:false,status:404,text:async()=>'{"error":{"message":"Project no longer exists"}}'};};
  let failed=false;try{await story.loadLibrary(stripped);}catch(error){failed=error.message==='Project no longer exists';}
  assert(failed&&JSON.stringify(graph.serialize())===beforeFailure,'Failed recovery changed the destination');
  window.request=async path=>{calls.push([path,'GET']);generator.widgets[0].value=9;return {ok:true,text:async()=>stringifyJSON(server)};};
  let changed=false;try{await story.loadLibrary(stripped);}catch(error){changed=/open story changed while loading/i.test(error.message);}
  assert(changed&&node.properties.h3c_fork_sequence==='native-saved'&&!host.project&&stringifyJSON(parseJSON(host.widget.value))===line,'Recovery overwrote edits made during lookup');
  assert(calls.length===8,'Unexpected recovery requests');
  return {managed_requests:calls,boxes:8,cues:19,native_import:true,native_saved_fork:true,text_wiring:true};
 } finally {host.saved.destroy();}
};
window.ready=true;
</script></body></html>'''

with sync_playwright() as p:
    executable = os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE')
    chrome = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
    if not executable and chrome.is_file():
        executable = str(chrome)
    browser = p.chromium.launch(**({'executable_path': executable} if executable else {}),
                                headless=True, args=['--disable-gpu'])
    try:
        page = browser.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))

        def route(request):
            path = unquote(urlparse(request.request.url).path)
            if path == '/fixture':
                return request.fulfill(body=FIXTURE, content_type='text/html')
            if path == '/scripts/app.js':
                return request.fulfill(body='export const app=window.fixtureApp;', content_type='text/javascript')
            if path == '/scripts/api.js':
                return request.fulfill(body='export const api=window.fixtureApi;', content_type='text/javascript')
            target = (ROOT / path.lstrip('/')).resolve()
            if ROOT in target.parents and target.is_file():
                return request.fulfill(body=target.read_text(encoding='utf-8'), content_type='text/javascript')
            return request.abort()

        page.route('**/*', route)
        page.goto('https://h3c.test/fixture')
        page.wait_for_function('window.ready===true')
        print(page.evaluate('run()'))
        assert not errors, errors
    finally:
        browser.close()
