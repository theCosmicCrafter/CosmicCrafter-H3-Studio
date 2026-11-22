"""Isolated settings/host smoke; routes serve checkout modules with mocked ComfyUI services."""
from pathlib import Path
from urllib.parse import urlparse, unquote
from playwright.sync_api import sync_playwright
import json
import os
root=Path.cwd().resolve()
(root/".tmp").mkdir(exist_ok=True)
fixture="""<!doctype html><html><head><style>body{background:#15171b;color:#ddd;font:14px Arial;margin:0}button{padding:10px;color:inherit;background:#343942;border:1px solid #666;border-radius:4px}a{color:#87bfff}</style></head><body><script type=module>
window.fixtureApp={registerExtension(){},extensionManager:{dialog:{confirm:async()=>true}}};
const {Studio}=await import('/web/h3c_studio.mjs');
const {TimelineHost}=await import('/web/h3c_timeline.js');window.Host=TimelineHost;
window.runHost=async attached=>{
 const graph={id:'graph',extra:{h3c_story_id:'old-story'},_nodes:[]};fixtureApp.rootGraph=fixtureApp.graph=graph;
 const timeline={name:'timeline',value:JSON.stringify({version:1,prompt:'shared words',boxes:[{id:'a',frames:107,prompt:'keep exact prompt',seed:7}]})};
 const node={id:1,type:'H3C_Timeline',graph,widgets:[{name:'name',value:'old'},timeline],inputs:[],properties:{h3c_asset_bindings:[{asset_id:'keep-source'}]},setDirtyCanvas(){}};graph._nodes=[node];
 const story={library:{},libraryRevision:5,libraryId:'old',node:{properties:{h3c_library_revision:5}},saved:{flush:async()=>{}},saveLibrary:async()=>{}};
 if(attached)node.properties.h3c_project={mode:'attached',id:'old-api-project'};
 const host=Object.assign(Object.create(TimelineHost.prototype),{node,widget:timeline,project:attached?{project:{sequence:'old'},save:async()=>{}}:null,
 saved:{flush:async()=>{}},editor:{load(){}},story:()=>story,newProjectBusy:()=>null,
 configureProject(){if(attached&&!graph.extra.h3c_story_id)throw Error('missing identity');this.project=null;},changed(){},refresh:async()=>{},
 stillRequest:async(path,body)=>{if(body.timeline!==timeline.value)throw Error('prompts changed');return {ok:true,name:'fresh'};}});
 await host.startGeneration();
 if(node.widgets[0].value!=='fresh'||timeline.value.indexOf('keep exact prompt')<0||node.properties.h3c_asset_bindings[0].asset_id!=='keep-source'||graph.extra.h3c_story_id==='old-story')throw Error('host preservation failed');
 return {attached,name:node.widgets[0].value,promptsPreserved:true,sourcesPreserved:true,newIdentity:true};
};
window.settings=new Studio();settings.layoutChanged=()=>{};settings.resizeViewport=()=>{};
settings.host={history:{endGroup(){}},sequenceName:()=> 'fresh',startGeneration:async()=>true,viewUrl:file=>'/view?filename='+file.filename,
 generationHistory:async()=>({ok:true,generations:[{name:'old',created:'2026-11-06T16:30:00',video:{filename:'old_full.mp4'},clips:[{number:1,file:{filename:'seg_1.mp4'}},{number:2,file:{filename:'seg_2.mp4'}}]}]})};
settings.root.replaceChildren(settings.pages.project);document.body.append(settings.root);settings.root.hidden=false;settings.pages.project.hidden=false;
settings.pages.project.style.cssText='padding:20px;box-sizing:border-box;overflow:auto;width:100%;max-width:100%';
await settings.loadGenerations();window.ready=true;
</script></body></html>"""
with sync_playwright() as p:
 chrome=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE')
 default=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
 if not chrome and default.is_file():chrome=str(default)
 browser=p.chromium.launch(**({'executable_path':chrome} if chrome else {}),headless=True,args=['--disable-gpu'])
 page=browser.new_page(viewport={'width':1440,'height':1000},device_scale_factor=1)
 errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 def route(request):
  path=unquote(urlparse(request.request.url).path)
  if path=='/fixture':return request.fulfill(body=fixture,content_type='text/html')
  if path=='/scripts/app.js':return request.fulfill(body='export const app=window.fixtureApp;',content_type='text/javascript')
  if path=='/scripts/api.js':return request.fulfill(body='export const api={};',content_type='text/javascript')
  target=(root/path.lstrip('/')).resolve()
  if root in target.parents and target.is_file():return request.fulfill(body=target.read_text(encoding='utf-8'),content_type='text/javascript')
  return request.abort()
 page.route('**/*',route);page.goto('https://h3c.test/fixture');page.wait_for_function('window.ready===true')
 print(json.dumps(page.evaluate('async()=>[await runHost(false),await runHost(true)]')))
 assert page.evaluate("()=>{fixtureApp.rootGraph={_nodes:[{h3cStory:{uploading:true}}]};return !!window.Host.prototype.newProjectBusy.call({project:null});}"), 'Story upload must block generation reset'
 assert page.evaluate("async()=>{const original=settings.host;settings.host={...original,sequenceName:()=> 'other',generationHistory:async()=>{throw Error('offline');}};await settings.loadGenerations();const cleared=settings.generationHistory.querySelectorAll('a').length===0;settings.host=original;await settings.loadGenerations();return cleared;}"), 'Different project history must clear on failure'
 for width in (1440,390):
  page.set_viewport_size({'width':width,'height':1000})
  page.get_by_role('button',name='Start a new generation',exact=True).click()
  page.get_by_text('New generation ready.',exact=False).wait_for()
  page.get_by_text('Previous generations',exact=True).wait_for()
  # The Studio remembers an opened section across redraws, so open it only when it isn't already.
  if not page.locator('details').last.evaluate('d=>d.open'):page.locator('details').last.locator('summary').click()
  assert page.get_by_role('link',name='Joined video').count()==1
  assert page.get_by_role('link',name='Clip 1',exact=True).count()==1
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
  page.screenshot(path=str(root/'.tmp'/f'generation-settings-{width}.png'))
 print(json.dumps({'desktop_mobile_settings':'pass','page_errors':errors}))
 assert not errors
 browser.close()
