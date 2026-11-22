"""Reference preparation navigation and asynchronous editing, using isolated catalog data."""
from pathlib import Path
from urllib.parse import urlparse,unquote
from playwright.sync_api import sync_playwright
from studio_fixture import FIXTURE as BASE
import json,os,base64
ROOT=Path.cwd().resolve()
SETUP=r"""
window.referenceRows=[
 {key:'mara',name:'Mara',category:'cast',role:'character',status:'missing',included:true,input_fingerprint:'mara-v1',prompt:'A traveler in a weathered coat, carrying a canvas satchel.',clips:['a1','b2'],candidates:[],existing_images:[]},
 {key:'field',name:'The field',category:'locations',role:'place',status:'approved',included:true,input_fingerprint:'field-v1',prompt:'Sunlit dry grass beneath the overpass. One open view.',clips:['a1','b2','c3'],candidates:[],existing_images:[{file:{type:'input',filename:'field.png'}}]}
];
host.referenceContext=()=> 'fixture';host.stillControls=async()=>({adapter:'pixels',width:1024,height:1024});host.openStillGenerator=async()=>{};
host.referenceCatalog=async()=>window.referenceRows.map(row=>({...row,...JSON.parse(stored).reference_preparation?.assets.find(a=>a.key===row.key)}));
host.generateReference=async()=>{throw Error('Fixture generator unavailable. Choose another generator or upload an image.');};
host.generateSelectedReferences=async()=>{};
"""
FIXTURE=BASE.replace('const editor=new TimelineEditor(host);',SETUP+'const editor=new TimelineEditor(host);')
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE') or 'C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True,args=['--disable-gpu'])
 page=browser.new_page(viewport=dict(width=1440,height=1000));errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 def route(request):
  path=unquote(urlparse(request.request.url).path)
  if path=='/fixture':return request.fulfill(body=FIXTURE,content_type='text/html')
  if path=='/scripts/app.js':return request.fulfill(body='export const app=window.fixtureApp;',content_type='text/javascript')
  if path=='/scripts/api.js':return request.fulfill(body='export const api={apiURL:path=>path,addEventListener(){},fetchApi:async()=>({status:200,ok:true,json:async()=>({revision:0,value:null})})};',content_type='text/javascript')
  if path=='/view':
   image=ROOT/'.tmp'/'studio-fixture-preview.png'
   if image.exists():return request.fulfill(body=image.read_bytes(),content_type='image/png')
   return request.fulfill(body=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aWQAAAABJRU5ErkJggg=='),content_type='image/png')
  target=(ROOT/path.lstrip('/')).resolve()
  if ROOT in target.parents and target.is_file():return request.fulfill(body=target.read_text(encoding='utf-8'),content_type='text/javascript')
  return request.abort()
 page.route('**/*',route);page.goto('https://h3c.test/fixture');page.wait_for_function('window.ready===true');page.evaluate('showStudio()')
 page.get_by_role('tab',name='Cast',exact=True).click();page.wait_for_function('editor.cast.preparation.rows.length===2')
 panel=page.locator('.h3cr-preparation')
 assert panel.get_by_role('textbox',name='Mara image prompt',exact=True).count()==1
 assert panel.get_by_role('textbox',name='The field image prompt',exact=True).count()==0
 assert panel.locator('.h3cr-batch-options').count()==0
 panel.get_by_role('tab',name='Locations',exact=True).click()
 assert panel.get_by_role('switch',name='Prepare locations references',exact=True).get_attribute('aria-checked')=='false'
 assert panel.get_by_role('textbox',name='The field image prompt',exact=True).is_visible()
 assert not page.evaluate('editor.state.reference_preparation?.generate.locations??false')
 panel.get_by_role('tab',name='All',exact=True).click();panel.get_by_role('button',name='Edit Mara reference',exact=True).click()
 prompt=panel.get_by_role('textbox',name='Mara image prompt',exact=True);prompt.fill('A traveler, carrying a red satchel.')
 page.evaluate('editor.cast.preparation.refresh()')
 assert prompt.input_value()=='A traveler, carrying a red satchel.'
 prompt.dispatch_event('change');page.wait_for_function("stored().reference_preparation.assets.find(a=>a.key==='mara').prompt.includes('red satchel')")
 panel.get_by_role('tab',name='Characters',exact=True).click()
 panel.get_by_role('switch',name='Prepare characters references',exact=True).click()
 page.wait_for_function('editor.state.reference_preparation.generate.cast===true')
 assert panel.get_by_role('switch',name='Prepare characters references',exact=True).get_attribute('aria-checked')=='true'
 assert not page.evaluate('editor.state.reference_preparation.generate.locations')
 panel.get_by_role('tab',name='All',exact=True).click();panel.get_by_role('button',name='Edit Mara reference',exact=True).click()
 panel.get_by_role('button',name='Generate reference',exact=True).click()
 page.wait_for_function("editor.cast.preparation.message.includes('Fixture generator unavailable')")
 assert panel.get_by_role('textbox',name='Mara image prompt',exact=True).input_value().endswith('red satchel.')
 page.set_viewport_size(dict(width=390,height=844));page.evaluate("studio.openFocus('cast')")
 panel.get_by_role('button',name='Back to references',exact=True).click()
 assert panel.get_by_role('button',name='Edit The field reference',exact=True).is_visible()
 panel.get_by_role('button',name='Edit The field reference',exact=True).click()
 assert panel.get_by_role('textbox',name='The field image prompt',exact=True).is_visible()
 assert panel.get_by_role('button',name='Back to references',exact=True).is_visible()
 assert not errors,errors
 print(json.dumps(dict(master_detail='pass',draft='pass',category_flags='pass',errors_and_mobile='pass',page_errors=errors)))
 browser.close()
