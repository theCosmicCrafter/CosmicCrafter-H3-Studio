"""A clip with two videos in the Studio: the video rows, the picker, editing the picked video, the switch settings and
the Viewer playing the stack or the picked video, at desktop and phone widths."""
from pathlib import Path
from urllib.parse import urlparse, unquote
from playwright.sync_api import sync_playwright
import json
import os

ROOT=Path.cwd().resolve()
(ROOT/'.tmp').mkdir(exist_ok=True)

FIXTURE=r'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0;background:#15171b;color:#ddd;font:14px Arial}*{box-sizing:border-box}</style></head><body><script>window.fixtureApp={registerExtension(){},ui:{settings:{getSettingValue:()=>false}},extensionManager:{dialog:{confirm:async()=>true}}};</script><script type="module">
import {TimelineEditor} from '/web/h3c_timeline_editor.mjs';
import {Studio} from '/web/h3c_studio.mjs';
import {TimelineHistory} from '/web/h3c_history.mjs';
import {parseJSON,stringifyJSON} from '/web/h3c_project.mjs';
const LAYER={id:'b2v1',seed:5101,prompt:'Close on her hands.',first:'',last:'',previews:[],memory:'off',memories:[],dialogue:'cues'};
const DOC=JSON.stringify({version:1,prompt:'',requires:['video-layers-1'],boxes:[
 {id:'a1',frames:48,exact:true,prompt:'The street.',seed:7,cut:false},
 {id:'b2',frames:90,exact:true,prompt:'Wide on the kitchen.',seed:1,cut:true,layers:[LAYER],
  switch:{cuts:[{at:27,to:'b2v1'}],fade:6,sound:'screen'}},
 {id:'c3',frames:48,exact:true,prompt:'The door.',seed:2,cut:true}]});
const file=name=>({filename:name,subfolder:'h3_continuity',type:'output'});
const STATUS={ok:true,message:'',boxes:[
 {id:'a1',status:'done',video:{file:file('a1.mp4'),frames:48,fps:24}},
 {id:'b2',status:'done',video:{file:file('b2.mp4'),frames:90,fps:24},stack:{file:file('stack@b2.mp4'),frames:90,fps:24},
  videos:[{id:'b2v1',status:'done',seed:5101,video:{file:file('b2v1.mp4'),frames:90,fps:24}}]},
 {id:'c3',status:'next'}],layers_remaining:0};
window.showStudio=()=>{
 let stored=DOC;
 const queued=[];
 const host={read:()=>stored,write:text=>{stored=text;},context:()=>39,settings:()=>({width:512,height:512,context_frames:39}),
  connected:()=>({images:[],audios:[],videos:[],video_audios:[]}),viewUrl:file=>`/view?filename=${file.filename}`,
  watch:()=>({running:false}),runningBox:()=>null,title:()=>'Video layers',titleOf:id=>id,changed(){},story:()=>null,
  node:{id:1,widgets:[],inputs:[]},hasVideo:()=>true,queue:async(...args)=>{queued.push(args);}};
 const editor=new TimelineEditor(host);host.editor=editor;document.body.append(editor.root);
 host.history=new TimelineHistory({read:()=>({timeline:parseJSON(stored),settings:{}}),identity:()=>'video-layers',
  apply:value=>{stored=stringifyJSON(value.timeline);editor.load();},notify:()=>{},group:()=>null,flush:()=>{}});
 const studio=new Studio();studio.open(host);
 editor.setStatus(STATUS);editor.select(1);editor.inspectClip();studio.refresh();
 Object.assign(window,{editor,studio,stored:()=>JSON.parse(stored),queued});
 return true;
};
window.screenVideo=()=>studio.screen.querySelector('video:not(.h3cx-live)')?.getAttribute('src')??'';
window.ready=true;
</script></body></html>'''

with sync_playwright() as p:
    executable=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE')
    chrome=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
    if not executable and chrome.is_file(): executable=str(chrome)
    browser=p.chromium.launch(**({'executable_path':executable} if executable else {}),headless=True,args=['--disable-gpu'])
    page=browser.new_page(viewport={'width':1440,'height':1000},device_scale_factor=1)
    errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    def route(request):
        path=unquote(urlparse(request.request.url).path)
        if path=='/fixture':return request.fulfill(body=FIXTURE,content_type='text/html')
        if path=='/scripts/app.js':return request.fulfill(body='export const app=window.fixtureApp;',content_type='text/javascript')
        if path=='/scripts/api.js':return request.fulfill(body='export const api={apiURL:path=>path,addEventListener(){},fetchApi:async()=>({status:200,ok:true,json:async()=>({revision:0,value:null})})};',content_type='text/javascript')
        target=(ROOT/path.lstrip('/')).resolve()
        if ROOT in target.parents and target.is_file():return request.fulfill(body=target.read_text(encoding='utf-8'),content_type='text/javascript')
        return request.abort()
    page.route('**/*',route);page.goto('https://h3c.test/fixture');page.wait_for_function('window.ready===true')
    page.evaluate('showStudio()')
    settle=lambda:page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
    settle()
    rows=page.locator('.h3ct-stack-row:visible')
    picker=page.locator('.h3ct-video-picker:visible')
    found={
        'rows':rows.count()==2,
        'picker':picker.locator('button').all_inner_texts()==['2 · main','2b','+ Video'],
        'stack plays':page.evaluate('screenVideo()').endswith('stack@b2.mp4'),
        'videos together':page.locator('text=Clip 2 · videos together').count()>0,
    }
    page.screenshot(path=str(ROOT/'.tmp'/'video-layers-1440.png'))
    picker.get_by_role('button',name='2b',exact=True).click();settle()
    prompt=page.locator('textarea[aria-label="Clip prompt (raw text)"]')
    found['picked prompt']=prompt.input_value()=='Close on her hands.'
    found['picked row']=page.locator('.h3ct-stack-row.picked[data-video="b2v1"]').count()==1
    found['layer plays']=page.evaluate('screenVideo()').endswith('b2v1.mp4')
    found['generate label']=page.evaluate('editor.boxRenderButton.textContent')=='Generate video 2b'
    prompt.fill('Close on her hands, flour.');settle()
    page.wait_for_function("stored().boxes[1].layers[0].prompt==='Close on her hands, flour.'",timeout=3000)
    found['typed into the layer']=page.evaluate("stored().boxes[1].prompt==='Wide on the kitchen.'")
    page.evaluate("editor.setTab('box');editor.renderPanel()");settle()
    fade=page.locator('input[aria-label="Fade frames"]')
    found['switch shown']=fade.is_visible() and page.locator('select[aria-label="Sound"]').is_visible()
    fade.fill('4');fade.dispatch_event('change');settle()
    found['fade written']=page.evaluate('stored().boxes[1].switch.fade')==4
    page.screenshot(path=str(ROOT/'.tmp'/'video-layers-settings-1440.png'))
    page.evaluate("editor.boxRenderButton.click()")
    page.wait_for_function('queued.length===1',timeout=3000)
    found['generate asks for the video']=page.evaluate('JSON.stringify(queued[0])')=='[1,null,null,null,"b2v1"]'
    page.set_viewport_size({'width':390,'height':844});settle()
    found['phone fits']=page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.screenshot(path=str(ROOT/'.tmp'/'video-layers-390.png'))
    page.get_by_role('button',name='Clip',exact=True).last.click()
    page.evaluate("editor.setTab('prompt');editor.renderPanel()");settle()
    found['phone picker']=page.locator('.h3ct-video-picker').is_visible()
    found['phone clip fits']=page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.screenshot(path=str(ROOT/'.tmp'/'video-layers-clip-390.png'))
    result={'checks':found,'page_errors':errors}
    print(json.dumps(result))
    assert all(found.values()),result
    assert not errors,result
    print('pass')
    browser.close()
