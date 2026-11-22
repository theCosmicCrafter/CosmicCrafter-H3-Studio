"""Real Studio form workflow against local modules and in-memory services; no live host or generation."""
import json
import os
from pathlib import Path
from urllib.parse import unquote, urlparse
from playwright.sync_api import sync_playwright

ROOT = Path.cwd().resolve()
OUT = ROOT / '.tmp'
OUT.mkdir(exist_ok=True)
FIXTURE = r'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{margin:0;background:#15171b;color:#ddd;font:14px Arial}*{box-sizing:border-box}</style></head><body>
<script>window.fixtureApp={registerExtension(){},ui:{settings:{getSettingValue:()=>false}},extensionManager:{dialog:{confirm:async()=>true}}};</script>
<script type="module">
import {TimelineEditor} from '/web/h3c_timeline_editor.mjs';
import {TimelineHost} from '/web/h3c_timeline.js';
import {Studio} from '/web/h3c_studio.mjs';
import {TimelineHistory} from '/web/h3c_history.mjs';
import {parseJSON,stringifyJSON} from '/web/h3c_project.mjs';
import * as model from '/web/h3c_timeline_model.mjs';
import * as layers from '/web/h3c_layers.mjs';
const original='integrated_multimodal_description:\n[Shot 1] A quiet café.\n\noverall_soundscape: Rain on the window.';
const picture={name:'image17',title:'Mara identity',description:'Mara in a cobalt raincoat',file:{filename:'mara.png',subfolder:'',type:'input'}};
const entity={id:'e1',name:'Mara',kind:'character',description:'Mara in a cobalt raincoat',pictures:['image17'],looks:[]};
const pixel='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aWWQAAAAASUVORK5CYII=';
let text=JSON.stringify({version:1,prompt:'',bible:{entities:[entity]},boxes:[
 {id:'a',frames:192,exact:true,seed:7,cut:true,prompt:original},
 {id:'b',frames:192,exact:true,seed:8,cut:true,prompt:'A second scene.'}]});
window.queued=[];window.apiLeaks=0;
const host={read:()=>text,write:value=>{text=value;},context:()=>39,settings:()=>({width:512,height:512,context_frames:39}),
 connected:()=>({images:[picture],audios:[],videos:[],video_audios:[]}),viewUrl:()=>pixel,watch:()=>({running:false}),runningBox:()=>null,
 title:()=>'Prompt forms',sequenceName:()=>'prompt-forms-fixture',titleOf:id=>id,story:()=>null,hasVideo:()=>true,
 node:{id:1,widgets:[],inputs:[]},queue:async(...args)=>queued.push(args),preflight:async()=>({})};
host.bible=async body=>{
 const doc=body.timeline;
 if(body.action==='status')return {ok:true,unlinked_boxes:[],in_force:{e1:doc.boxes.map(()=>0)},
  sources:Object.fromEntries(doc.boxes.filter(b=>b.source).map(b=>[b.id,'edited'])),
  subjects:doc.boxes.flatMap(box=>Object.entries(box.cast??{}).map(([label,id])=>({box:box.id,label,entity:id,look:0,state:'in_step',text:'Mara'})))};
 if(body.action==='assign'){
  const box=doc.boxes.find(b=>b.id===body.box),known=Object.entries(box.cast??{}).find(([,id])=>id===body.entity);
  if(known)return {ok:true,changed:false,subject:known[0],prompts:{},casts:{},schedules:{}};
  const max=Math.max(0,...[...`${doc.prompt} ${box.prompt}`.matchAll(/<Subject (\d+)>/g)].map(m=>Number(m[1]))),label=`<Subject ${max+1}>`;
  const definition=`${label} is Mara in a cobalt raincoat in @image17.`;
  let prompt=box.prompt.replace('integrated_multimodal_description:','detailed_description:');
  if(prompt.includes('subject_definitions:'))prompt=prompt.replace('subject_definitions:','subject_definitions:\n'+definition);
  else prompt='subject_definitions:\n'+definition+'\n\n'+(prompt.includes('detailed_description:')?prompt:'detailed_description:\n'+prompt);
  return {ok:true,changed:true,subject:label,prompts:{[box.id]:prompt},casts:{[box.id]:{...box.cast,[label]:body.entity}},
   schedules:{[box.id]:{entities:[...new Set([...(box.schedule?.entities??[]),body.entity])],place:box.schedule?.place??null}}};
 }
 if(body.action==='apply')return {ok:true,bible:body.bible,prompts:{},casts:Object.fromEntries(Object.entries(body.links??{}).map(([id,links])=>[id,
  Object.fromEntries(Object.entries({...doc.boxes.find(b=>b.id===id).cast,...links}).filter(([,value])=>value))]))};
 return {ok:false,error:'Fixture action unsupported'};
};
const editor=new TimelineEditor(host);host.editor=editor;document.body.append(editor.root);
host.history=new TimelineHistory({read:()=>({timeline:parseJSON(text),settings:{}}),identity:()=>'prompt-forms',
 apply:value=>{text=stringifyJSON(value.timeline);editor.load();},notify(){},group:()=>null,flush:()=>editor.flushTyping()});
host.changed=()=>host.history.capture();host.undoStep=()=>host.history.capture();
const studio=new Studio();studio.open(host);editor.select(0);editor.inspectClip();studio.setInspectorVisible(true);
window.editor=editor;window.studio=studio;window.host=host;window.stored=()=>text;window.doc=()=>parseJSON(text);window.original=original;
window.directQueue=async()=>{try{await TimelineHost.prototype.queue.call({editor},1,1);return false;}catch(error){return error.message.includes('unsaved');}};
window.directStill=async()=>{try{await TimelineHost.prototype.generateStill.call({editor,stillClient:{generate(){apiLeaks++;}}},{});return false;}catch(error){return error.message.includes('unsaved');}};
window.reload=()=>{editor.load();editor.inspectClip();studio.setInspectorVisible(true);};
window.addAlternate=()=>{const id=layers.addVideo(editor.state,1);Object.assign(editor.state.boxes[1].layers.find(v=>v.id===id),{prompt:'Alternate view.',dialogue:'manual'});editor.commit();editor.select(1);editor.pick(id);};
window.loadMany=()=>{
 const value=doc();value.boxes=Array.from({length:88},(_,i)=>({id:'c'+i,frames:192,exact:true,seed:i+1,cut:true,prompt:original}));
 text=JSON.stringify(value);editor.load();editor.select(0);editor.inspectClip();studio.setInspectorVisible(true);
};
window.ready=true;
</script></body></html>'''


def run(page, width, height):
    errors = []
    page.on('pageerror', lambda error: (errors.append(str(error)), print('page error:', str(error))))
    page.set_default_timeout(10000)

    def route(request):
        path = unquote(urlparse(request.request.url).path)
        if path == '/fixture':
            return request.fulfill(body=FIXTURE, content_type='text/html')
        if path == '/scripts/app.js':
            return request.fulfill(body='export const app=window.fixtureApp;', content_type='text/javascript')
        if path == '/scripts/api.js':
            return request.fulfill(body='export const api={apiURL:path=>path,addEventListener(){},fetchApi:async()=>({status:200,ok:true,json:async()=>({revision:0,value:null})})};', content_type='text/javascript')
        target = (ROOT / path.lstrip('/')).resolve()
        if ROOT in target.parents and target.is_file():
            return request.fulfill(body=target.read_text(encoding='utf-8'), content_type='text/javascript')
        return request.abort()

    page.route('**/*', route)
    page.goto('https://h3c.test/fixture')
    page.wait_for_function('window.ready===true')
    page.evaluate("studio.setInspectorVisible(true); if(innerWidth<900)studio.setMobilePage('clip')")
    switch = page.locator('.h3pf > legend [role=switch]')

    def advanced(on):
        if (switch.get_attribute('aria-checked') == 'true') != on:
            switch.click()
        assert switch.get_attribute('aria-checked') == ('true' if on else 'false')

    before = page.evaluate('stored()')
    advanced(True)
    advanced(False)
    page.get_by_role('button', name='Raw text', exact=True).click()
    page.get_by_role('button', name='Sections', exact=True).click()
    assert page.evaluate('stored()') == before
    history_before = page.evaluate('host.history.entries.length')
    page.get_by_label('Add from Cast', exact=True).first.select_option('e1')
    page.wait_for_function("doc().boxes[0].cast?.['<Subject 1>']==='e1'")
    assert page.evaluate('host.history.entries.length') == history_before + 1
    page.evaluate('host.history.undo()')
    assert page.evaluate('doc().boxes[0].prompt===original && !doc().boxes[0].cast')
    page.evaluate('host.history.redo()')
    assert page.evaluate("doc().boxes[0].schedule.entities.join(',')==='e1'")
    page.get_by_role('tab', name='Reference retention', exact=True).click()
    page.get_by_role('button', name='Add retention', exact=True).click()
    page.get_by_label('Reference', exact=True).select_option('<Subject 1>')
    page.get_by_label('Relationship', exact=True).select_option('fully_preserved')
    page.get_by_label('Appears in shots', exact=True).select_option('1')
    page.get_by_label('Retention details', exact=True).fill('Her face and coat remain unchanged.')
    assert page.evaluate("doc().boxes[0].prompt.includes('<Subject 1> (appears in [Shot 1]): fully_preserved - Her face and coat remain unchanged.')")
    page.locator('.h3pf').screenshot(path=str(OUT / f'prompt-forms-retention-{width}.png'))
    page.locator('.h3pf').get_by_role('tab', name='Shots', exact=True).click()
    page.get_by_role('button', name='Add shot', exact=True).click()
    new_start = page.get_by_label('New shot start (seconds)', exact=True)
    new_start.fill('2.5')
    new_start.dispatch_event('change')
    page.get_by_label('Shot 2 description', exact=True).fill('the camera cuts to a close-up of her hands.')
    assert page.evaluate("doc().boxes[0].prompt.includes('[Shot 2] At 00:02.500, the camera cuts to a close-up of her hands.')"), page.evaluate('doc().boxes[0].prompt')
    valid_prompt = page.evaluate('doc().boxes[0].prompt')
    start = page.get_by_label('Shot 2 start (seconds)', exact=True)
    start.fill('-1')
    start.dispatch_event('change')
    page.evaluate('editor.select(1)')
    assert page.evaluate('editor.selected') == 0
    assert page.evaluate('directQueue()') and page.evaluate('directStill()')
    assert page.evaluate('doc().boxes[0].prompt') == valid_prompt
    page.get_by_role('button', name='Discard draft', exact=True).click()
    start = page.get_by_label('Shot 2 start (seconds)', exact=True)
    start.fill('3.125')
    start.dispatch_event('change')
    advanced(True)
    page.get_by_label('Shot 2 add detail', exact=True).select_option('camera_movement')
    camera = page.get_by_label('Shot 2 Camera movement', exact=True)
    camera.press_sequentially('A slow spiral around her left shoulder', delay=1)
    assert page.evaluate("doc().boxes[0].prompt.includes('Camera movement: A slow spiral around her left shoulder')")
    page.get_by_label('Shot 2 add detail', exact=True).select_option('lighting')
    page.get_by_label('Shot 2 Lighting', exact=True).fill('Warm side light')
    advanced_prompt = page.evaluate('doc().boxes[0].prompt')
    page.evaluate('reload()')
    assert switch.get_attribute('aria-checked') == 'true'
    page.once('dialog', lambda dialog: dialog.accept())
    advanced(False)
    assert page.evaluate('doc().boxes[0].prompt') == advanced_prompt.replace('\nLighting: Warm side light', '')
    assert page.get_by_label('Shot 2 Lighting', exact=True).count() == 0
    assert page.get_by_label('Shot 2 Camera movement', exact=True).is_visible()
    advanced(True)
    assert page.evaluate('doc().boxes[0].prompt') == advanced_prompt
    assert page.get_by_label('Shot 2 Lighting', exact=True).input_value() == 'Warm side light'
    page.get_by_role('button', name='Use typed dialogue', exact=True).click()
    shot_two = page.locator('section[aria-label="Shot 2"]')
    shot_two.get_by_role('button', name='Add dialogue', exact=True).click()
    for label, value in [('speaker IDs', 'S1'), ('speaker', '<Subject 1>'), ('language', 'English'), ('words', 'Yes. Café 雨.')]:
        page.get_by_label('Shot 2 dialogue 1 ' + label, exact=True).fill(value)
    page.get_by_label('Shot 2 dialogue 1 Off-screen voiceover', exact=True).check()
    assert page.evaluate("doc().boxes[0].prompt.includes('<d>[English] Yes. Café 雨.</d>') && doc().boxes[0].prompt.includes('lips remain completely closed')")
    page.evaluate('editor.flushTyping()')
    saved = page.evaluate('stored()')
    page.evaluate('reload()')
    assert page.evaluate('stored()') == saved
    assert page.evaluate('modelExport=JSON.stringify(doc()); JSON.stringify(JSON.parse(modelExport))===JSON.stringify(doc())')
    page.evaluate("editor.state.boxes[0].source={reply:{},frame:{}};editor.commit()")
    page.get_by_label('Shot 1 description', exact=True).fill('The quiet café stays still.')
    assert page.evaluate('JSON.stringify(doc().boxes[0].source)') == '{"reply":{},"frame":{}}'
    page.evaluate("editor.state.boxes[0].previews=[{target:{kind:'shot',shot:2},frame:75,guide:{filename:'guide.png',type:'output',subfolder:'h3_previews'}}];editor.commit()")
    protected = page.evaluate('doc().boxes[0].prompt')
    start = page.get_by_label('Shot 2 start (seconds)', exact=True)
    start.fill('4')
    start.dispatch_event('change')
    assert page.evaluate('doc().boxes[0].prompt') == protected
    assert page.evaluate('doc().boxes[0].previews[0].frame') == 75
    assert 'guide' in page.locator('.h3pf-error').inner_text().lower()
    page.get_by_role('button', name='Discard draft', exact=True).click()
    advanced(True)
    page.screenshot(path=str(OUT / f'prompt-forms-{width}.png'))
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.evaluate('addAlternate()')
    main = page.evaluate('doc().boxes[1].prompt')
    page.get_by_label('Existing text', exact=True).fill('New alternate view.')
    assert page.evaluate('doc().boxes[1].prompt') == main
    assert page.evaluate('doc().boxes[1].layers[0].prompt') == 'New alternate view.'
    page.get_by_label('Add from Cast', exact=True).first.select_option('e1')
    page.wait_for_function("doc().boxes[1].cast?.['<Subject 1>']==='e1'")
    assert page.evaluate('editor.pickedLayer()===null')
    assert page.evaluate('doc().boxes[1].layers[0].prompt') == 'New alternate view.'
    page.evaluate('loadMany()')
    page.locator('.h3pf').get_by_role('tab', name='Shots', exact=True).click()
    rest = page.evaluate('doc().boxes.slice(1).map(b=>b.prompt)')
    page.get_by_label('Shot 1 description', exact=True).fill('One edited clip in a long Timeline.')
    assert page.evaluate('doc().boxes.slice(1).map(b=>b.prompt)') == rest
    page.evaluate("const value=doc();value.boxes[0].prompt=value.boxes[0].prompt.replace('\\n\\noverall_soundscape','\\nLighting: Low amber light\\n\\noverall_soundscape');value.requires=['future-prompt-99'];value.future={kept:true};host.write(JSON.stringify(value));reload()")
    readonly = page.evaluate('stored()')
    page.locator('.h3pf').get_by_role('tab', name='Shots', exact=True).click()
    assert page.get_by_label('Shot 1 description', exact=True).is_disabled()
    assert switch.get_attribute('aria-checked') == 'true'
    advanced(False)
    assert page.get_by_label('Shot 1 Lighting', exact=True).count() == 0
    assert '1 hidden' in switch.inner_text()
    advanced(True)
    assert page.get_by_label('Shot 1 Lighting', exact=True).input_value() == 'Low amber light'
    assert page.evaluate('stored()') == readonly
    page.evaluate("editor.applyPrompt(editor.video().prompt,'BAD',{structural:true});editor.cast.addToClip(editor.box().id,'e1')")
    assert page.evaluate('stored()') == readonly
    assert page.evaluate('queued.length===0 && apiLeaks===0')
    assert not errors, errors
    return {'viewport': [width, height], 'workflow': 'pass', 'history': 'pass', 'drafts': 'pass', 'guides': 'pass', 'long_timeline': 'pass', 'readonly': 'pass', 'page_errors': errors}


with sync_playwright() as p:
    executable = os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE')
    chrome = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
    if not executable and chrome.is_file():
        executable = str(chrome)
    browser = p.chromium.launch(**({'executable_path': executable} if executable else {}), headless=True, args=['--disable-gpu'])
    results = []
    try:
        for width, height in [(1440, 1000), (390, 844)]:
            page = browser.new_page(viewport={'width': width, 'height': height}, device_scale_factor=1)
            try:
                results.append(run(page, width, height))
            except Exception:
                page.screenshot(path=str(OUT / f'prompt-forms-failed-{width}.png'))
                print(json.dumps({'viewport': width, 'page_errors': page.evaluate('window.ready?[]:["fixture not ready"]')}))
                raise
            finally:
                page.close()
        print(json.dumps(results))
        print('pass')
    finally:
        browser.close()
