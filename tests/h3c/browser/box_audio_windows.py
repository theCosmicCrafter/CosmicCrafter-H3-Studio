"""Real Studio/editor controls with isolated native and attached host storage; no ComfyUI or model run."""
from pathlib import Path
from urllib.parse import urlparse, unquote
from playwright.sync_api import sync_playwright, expect
import io
import json
import os
import wave

ROOT=Path.cwd().resolve()
(ROOT/'.tmp').mkdir(exist_ok=True)
sound=io.BytesIO()
with wave.open(sound,'wb') as wav:
    wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(8000);wav.writeframes(b'\0\0'*80000)

FIXTURE=r'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0;background:#15171b;color:#ddd;font:14px Arial}*{box-sizing:border-box}</style></head><body><script>window.fixtureApp={registerExtension(){},ui:{settings:{getSettingValue:()=>false}},extensionManager:{dialog:{confirm:async()=>{window.realConfirmCalls++;return true;}}}};</script><script type="module">
import {TimelineEditor} from '/web/h3c_timeline_editor.mjs';
import {Studio} from '/web/h3c_studio.mjs';
import {TimelineHistory} from '/web/h3c_history.mjs';
import {ProjectSession,parseJSON,stringifyJSON} from '/web/h3c_project.mjs';
import * as model from '/web/h3c_timeline_model.mjs';
import {splitBox} from '/web/h3c_shot_split.mjs';
import {TimelineHost} from '/web/h3c_timeline.js';
window.realHostUnlock=async()=>{
 const methods=['configureProject','relayout','showProgress','schedule','changed'];
 const originals=Object.fromEntries(methods.map(name=>[name,TimelineHost.prototype[name]]));
 for(const name of methods)TimelineHost.prototype[name]=()=>{};
 let real;
 try{
  const graph={id:'real-host',_nodes:[]};fixtureApp.graph=fixtureApp.rootGraph=graph;
  const value=stringifyJSON({version:1,boxes:[{id:'a',frames:96,exact:true},{id:'b',frames:96,cut:true,exact:true}],audio_clips:[{slot:'audio1',file:{type:'input',filename:'voice.wav'},start:0,source_start:0,duration:8,source_duration:8}]});
  const node={id:9,type:'H3C_Timeline',graph,properties:{},inputs:[],widgets:[{name:'name',value:'real'},{name:'timeline',value},{name:'context_frames',value:39}],size:[500,400],setDirtyCanvas(){},
   addDOMWidget:(name,type,element,options)=>({name,type,options}),addWidget(type,name,value,callback,options){const widget={type,name,value,callback,options};this.widgets.push(widget);return widget;}};
  graph._nodes=[node];real=new TimelineHost(node);window.realConfirmCalls=0;
  const lanes=real.editor.audioLanes;lanes.selected='audio1';await lanes.setBoxLock(true);real.editor.state.boxes[0].frames=144;real.editor.commit();
  const unlocked=await lanes.setBoxLock(false);
  return {unlocked,calls:realConfirmCalls,bound:!!real.editor.state.audio_clips[0].box_windows};
 }finally{real?.node.onRemoved?.();for(const name of methods)TimelineHost.prototype[name]=originals[name];}
};
window.make=attached=>{
 window.studio?.close();document.querySelector('.fixture-editor')?.remove();
 let stored=stringifyJSON({version:1,boxes:[{id:'a',frames:96,exact:true,prompt:'[Shot 1] Walk.\n[Shot 2] At 00:01.000, turn.'},{id:'b',frames:96,exact:true,cut:true,prompt:'Wait.'}],audio_clips:[]});
 const settings={width:512,height:512,context_frames:39};let session,server;
 const host={projectAttached:attached,read:()=>stored,write:text=>stored=text,context:()=>39,settings:()=>settings,
 connected:()=>({images:[],audios:[],videos:[],video_audios:[]}),viewUrl:()=>'/sample.wav',
 uploadAudio:async()=>({file:{type:'input',filename:'voice.wav',subfolder:'h3_audio'},title:'Voice recording',duration:8,peaks:[.2,.5]}),
 confirmAudioUnlock:async()=>{window.confirmCalls++;return window.confirmAnswer;},watch:()=>({running:false}),runningBox:()=>null,title:()=>attached?'Attached audio project':'Native audio project',titleOf:id=>id,
 changed(){host.history?.capture();window.studio?.refresh();},story:()=>null,node:{id:1,widgets:[],inputs:[]}};
 const editor=new TimelineEditor(host);host.editor=editor;editor.root.classList.add('fixture-editor');document.body.append(editor.root);
 host.history=new TimelineHistory({read:()=>({timeline:parseJSON(stored),settings}),identity:()=>attached?'attached':'native',
 apply:value=>{stored=stringifyJSON(value.timeline);editor.load();},notify:()=>{},group:()=>null,flush:()=>{}});
 if(attached){server={id:'p',revision:1,profile_sha256:'test',timeline:parseJSON(stored),settings,assets:[]};
 session=new ProjectSession({metadata:{mode:'attached',id:'p',profile_sha256:'test'},read:()=>({timeline:stored,settings}),apply:value=>{stored=stringifyJSON(value.timeline);editor.load();},
 request:async(_,options)=>{server={...server,...options.body,revision:server.revision+1};return structuredClone(server);}});session.install(server);}
 const studio=new Studio();window.studio=studio;studio.open(host);
 window.editor=editor;window.host=host;window.lanes=editor.audioLanes;window.confirmAnswer=true;window.confirmCalls=0;
 window.showAudio=()=>{lanes.selectAudio('audio1','a');studio.setInspectorVisible(true);studio.setMobilePage('clip');};
 window.roundtrip=async()=>{const before=model.serialize(editor.state);if(session)await session.save();editor.load();if(model.serialize(editor.state)!==before)throw Error('save/reload lost editor data');if(session&&server.timeline.audio_clips[0].box_windows===undefined)throw Error('attached save lost bindings');};
 window.actions={resize:()=>{editor.state.boxes[0].frames=144;editor.commit();},duplicate:()=>{editor.selected=0;editor.duplicate();},
 insert:()=>{const index=model.addBox(editor.state,39);const added=editor.state.boxes.splice(index,1)[0];editor.state.boxes.splice(1,0,added);editor.commit();},
 split:()=>{splitBox(editor.state,0,2,39);editor.commit();},move:()=>{model.moveBox(editor.state,0,1,39);editor.commit();},
 undo:()=>host.history.undo(),redo:()=>host.history.redo()};
 return true;
};
window.make(false);window.ready=true;
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
        if path in ('/sample.wav','/view'):return request.fulfill(body=sound.getvalue(),content_type='audio/wav')
        if path=='/scripts/app.js':return request.fulfill(body='export const app=window.fixtureApp;',content_type='text/javascript')
        if path=='/scripts/api.js':return request.fulfill(body='export const api={apiURL:path=>path,addEventListener(){},fetchApi:async()=>({status:200,ok:true,json:async()=>({revision:0,value:null})})};',content_type='text/javascript')
        target=(ROOT/path.lstrip('/')).resolve()
        if ROOT in target.parents and target.is_file():return request.fulfill(body=target.read_text(encoding='utf-8'),content_type='text/javascript')
        return request.abort()
    page.route('**/*',route);page.goto('https://h3c.test/fixture');page.wait_for_function('window.ready===true')
    for attached in (False,True):
        page.evaluate('(attached)=>make(attached)',attached)
        page.evaluate("async()=>{await lanes.addFile(new File(['source'],'voice.wav',{type:'audio/wav'}));showAudio();}")
        toggle=page.get_by_role('checkbox',name='Lock audio to boxes',exact=True)
        page.evaluate("()=>{editor.state.audio_clips[0].in_full_video=true;editor.state.boxes[0].frames=107;editor.state.boxes[0].exact=false;editor.state.bridges=[{before:'b',frames:12}];editor.commit();showAudio();}")
        assert toggle.is_disabled()
        assert page.get_by_text('Resolve the inserted bridge before box 2',exact=False).is_visible()
        page.evaluate("()=>{delete editor.state.audio_clips[0].in_full_video;delete editor.state.bridges;editor.state.boxes[0].frames=96;editor.state.boxes[0].exact=true;editor.commit();showAudio();}")
        toggle.check();page.wait_for_function('!!editor.state.audio_clips[0].box_windows')
        assert page.locator('.h3ct-audio-clip[data-box]').count()==2
        page.evaluate('actions.resize()')
        assert page.evaluate("()=>editor.state.audio_clips[0].box_windows.by_box.b.source_start===4")
        assert page.locator('.h3ct-audio-gap').count()>=1
        page.locator('.h3ct-audio-clip[data-box="b"]').scroll_into_view_if_needed()
        page.screenshot(path=str(ROOT/'.tmp'/f'box-audio-segments-{attached}.png'))
        assert page.evaluate("()=>{editor.state.boxes[0].frames=48;editor.commit();lanes.selectAudio('audio1','a');const player=lanes.settings.querySelector('audio');const clipped=player.audioWindow.duration===2;editor.state.boxes[0].frames=144;editor.commit();return clipped&&lanes.settings.querySelector('audio').audioWindow.duration===4;}")
        assert page.get_by_role('spinbutton',name='Video start (s)',exact=True).is_disabled()
        page.evaluate("()=>{editor.state.timed_text={version:1,source_name:'words',source_sha256:'0'.repeat(64),enabled:true,sync_audio:true,audio_slot:'audio1',start:0,source_start:0,duration:8,direction:'',cues:[{id:'x',start:5,end:6,text:'Hello'}]};editor.commit();lanes.selectText();}")
        sync=page.get_by_role('checkbox',name='Sync text to audio',exact=True)
        sync.click()
        assert sync.is_checked()
        assert page.evaluate("lanes.textSummary.textContent.includes('Unlock audio')")
        page.evaluate('()=>{delete editor.state.timed_text;editor.commit();showAudio();}')
        page.evaluate('actions.insert();actions.duplicate()')
        assert page.evaluate("()=>Object.keys(editor.state.audio_clips[0].box_windows.by_box).length===2")
        page.evaluate('actions.split();actions.move();actions.undo();actions.redo()')
        assert page.evaluate("()=>Object.keys(editor.state.audio_clips[0].box_windows.by_box).length===3")
        page.evaluate('roundtrip()')
        page.evaluate('showAudio();window.confirmAnswer=false')
        toggle.click();page.wait_for_function('!lanes.boxLockBusy')
        assert page.evaluate('!!editor.state.audio_clips[0].box_windows')
        page.evaluate('window.confirmAnswer=true');toggle.uncheck();page.wait_for_function('!editor.state.audio_clips[0].box_windows')
        assert page.evaluate('confirmCalls')==2
        toggle.check();page.wait_for_function('!!editor.state.audio_clips[0].box_windows')
        for width in (1440,390):
            page.set_viewport_size({'width':width,'height':1000})
            page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
            page.evaluate('showAudio()')
            expect(toggle).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), f'overflow at {width}'
            page.screenshot(path=str(ROOT/'.tmp'/f'box-audio-{attached}-{width}.png'))
        page.set_viewport_size({'width':1440,'height':1000})
    actual=page.evaluate('realHostUnlock()')
    assert actual=={'unlocked':True,'calls':1,'bound':False},actual
    assert not errors,errors
    print(json.dumps({'native_attached':True,'actual_host_unlock':actual,'viewports':[1440,390],'page_errors':errors,'workflow':'add/lock/resize/insert/duplicate/split/move/undo/redo/save/cancel/unlock/relock'}))
    browser.close()
