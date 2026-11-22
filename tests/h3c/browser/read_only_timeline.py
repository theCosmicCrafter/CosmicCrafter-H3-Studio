"""A Timeline from a newer Studio stays byte for byte through the real host, story writer, undo and editor UI."""
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
import * as model from '/web/h3c_timeline_model.mjs';
import * as storyModel from '/web/h3c_story_model.mjs';
import {TimelineHost} from '/web/h3c_timeline.js';
import {StoryHost} from '/web/h3c_story.js';
const file=name=>({filename:`${name}.png`,subfolder:'h3_previews',type:'output'});
const NEWER=JSON.stringify({version:1,prompt:'',requires:['video-layers-99'],future:{kept:true},boxes:[
 {id:'a',frames:71,exact:true,prompt:'A walk.',seed:1,cut:false,flf_refmods:true,
  previews:[{shot:1000,frame:0,guide:file('start')},{shot:1001,frame:70,guide:file('end')}]},
 {id:'b',frames:71,prompt:'Two angles.',seed:1,seed_mode:'randomize',cut:true,
  layers:[{id:'l1',prompt:'The other angle.'}],switch:{at:0.5,fade:6}}]});
const EDITABLE=JSON.stringify({...JSON.parse(NEWER),requires:['dialogue-cues-1']});
const NOTE='This Timeline needs a newer H3 Continuity (video-layers-99). It is open read-only so nothing in it is lost; update the node pack to edit or render it.';
window.NOTE=NOTE;window.NEWER=NEWER;
const methods=['configureProject','relayout','showProgress','schedule','changed'];
async function withHosts(run){
 const originals=Object.fromEntries(methods.map(name=>[name,TimelineHost.prototype[name]]));
 for(const name of methods)TimelineHost.prototype[name]=()=>{};
 const made=[];
 try{
  const graph={id:'read-only',_nodes:[]};fixtureApp.graph=fixtureApp.rootGraph=graph;
  const host=text=>{
   const node={id:made.length+1,type:'H3C_Timeline',graph,properties:{},inputs:[],size:[500,400],setDirtyCanvas(){},
    widgets:[{name:'name',value:'read-only'},{name:'timeline',value:text},{name:'context_frames',value:39}],
    addDOMWidget:(name,type,element,options)=>({name,type,options}),addWidget(type,name,value,callback,options){const widget={type,name,value,callback,options};this.widgets.push(widget);return widget;}};
   graph._nodes.push(node);const real=new TimelineHost(node);made.push(real);return real;
  };
  return await run(host);
 }finally{for(const real of made)real.node.onRemoved?.();for(const name of methods)TimelineHost.prototype[name]=originals[name];}
}
const failed=[];
const check=(name,ok)=>{if(!ok)failed.push(name);};
const refuses=async(name,action)=>{try{await action();failed.push(`${name}: no error`);}catch(error){if(error.message!==NOTE)failed.push(`${name}: ${error.message}`);}};
window.hostPaths=()=>withHosts(async host=>{
 const real=host(NEWER),widget=real.widget,editor=real.editor;
 check('construction and load keep the text',widget.value===NEWER);
 check('the editor is read-only',JSON.stringify(editor.readOnly)==='["video-layers-99"]');
 check('the new form refuses read-only edits',editor.applyPrompt(editor.video().prompt,'BAD',{structural:true})===false&&widget.value===NEWER);
 check('Cast assignment refuses a read-only Timeline',await editor.cast.addToClip(editor.box().id,'e1')===false&&widget.value===NEWER);
 editor.state.boxes[1].prompt='Changed.';editor.commit();
 check('an edit is not written',widget.value===NEWER);
 check('an edit is undone',editor.state.boxes[1].prompt==='Two angles.');
 editor.host.write(model.serialize(model.parseState(NEWER)));
 check('a direct editor-host write is refused',widget.value===NEWER);
 check('writeTimeline answers false',real.writeTimeline('{"version":1,"boxes":[]}')===false&&widget.value===NEWER);
 await refuses('still state',()=>real.writeStillState(model.parseState(NEWER)));
 await refuses('host replaceTimeline',()=>real.replaceTimeline('{"version":1,"boxes":[]}'));
 real.node.widgets.find(item=>item.name==='context_frames').value=24;editor.contextChanged();
 check('a context change is not written',widget.value===NEWER);
 check('the undo snapshot is exact',stringifyJSON(real.historyState().timeline)===NEWER);
 check('the text is unchanged at the end',widget.value===NEWER);
 // Undo and redo between whole Timelines: an editable one, edited, then one from a newer Studio loaded over it.
 const other=host(EDITABLE),text=()=>other.widget.value;
 other.editor.state.boxes[1].prompt='Edited.';other.editor.commit();
 const edited=text();
 other.widget.value=NEWER;other.editor.load();
 check('the newer Timeline is loaded as is',text()===NEWER);
 other.history.undo();
 check('undo goes back to the edited Timeline',text()===edited);
 other.history.redo();
 check('redo brings the newer Timeline back byte for byte',text()===NEWER);
 other.history.undo();
 check('undo leaves a newer Timeline for an earlier one',text()===edited);
 return failed.splice(0);
});
window.storyPaths=()=>{
 const said=[];
 const story=(found,state)=>Object.assign(Object.create(StoryHost.prototype),{panel:{say:(text,error)=>said.push({text,error})},
  state:()=>state,timeline:()=>found,setState(next){this.next=next;}});
 const state=()=>storyModel.parseStoryState(JSON.stringify({timeline:'1',written:{b:'Two angles.'},undo:{b:'Old.'}}));
 for(const [kind,withEditor] of [['with an editor',true],['without an editor',false]]){
  const widget={name:'timeline',value:NEWER};
  const node={widgets:[widget,{name:'context_frames',value:39}],setDirtyCanvas(){},
   ...(withEditor?{h3cTimeline:{replaceTimeline(text){widget.value=text;}}}:{})};
  const writer=story({node,widget},state());
  try{writer.replaceTimeline({node,widget},'{"version":1,"boxes":[]}');failed.push(`story replace ${kind}: no error`);}
  catch(error){check(`story replace ${kind} names the feature`,error.message===NOTE);}
  said.length=0;writer.undo();
  check(`story undo ${kind} keeps the text`,widget.value===NEWER);
  check(`story undo ${kind} says why`,said.length===1&&said[0].text===NOTE&&said[0].error===true);
  check(`story undo ${kind} keeps its undo`,writer.next===undefined);
 }
 const widget={name:'timeline',value:EDITABLE},node={widgets:[widget],setDirtyCanvas(){}};
 story({node,widget},state()).undo();
 check('story undo still restores an editable Timeline',model.parseState(widget.value).boxes[1].prompt==='Old.');
 return failed.splice(0);
};
window.showEditor=()=>{
 let stored=NEWER;
 const host={read:()=>stored,write:text=>{stored=text;},context:()=>39,settings:()=>({width:512,height:512,context_frames:39}),
  connected:()=>({images:[],audios:[],videos:[],video_audios:[]}),viewUrl:()=>'/none',watch:()=>({running:false}),runningBox:()=>null,
  title:()=>'Read-only Timeline',titleOf:id=>id,changed(){},story:()=>null,node:{id:1,widgets:[],inputs:[]},hasVideo:()=>true};
 const editor=new TimelineEditor(host);host.editor=editor;document.body.append(editor.root);
 host.history=new TimelineHistory({read:()=>({timeline:parseJSON(stored),settings:{}}),identity:()=>'read-only',
  apply:value=>{stored=stringifyJSON(value.timeline);editor.load();},notify:()=>{},group:()=>null,flush:()=>{}});
 const studio=new Studio();studio.open(host);
 window.editor=editor;window.stored=()=>stored;
 return true;
};
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
    host_failures=page.evaluate('hostPaths()')
    story_failures=page.evaluate('storyPaths()')
    page.evaluate('showEditor()')
    note=page.evaluate('NOTE')
    hint=page.get_by_text(note,exact=True)
    shown=hint.count()==1 and hint.is_visible() and page.evaluate("()=>{const box=editor.readOnlyEl.getBoundingClientRect();return box.top>=0&&box.bottom<=innerHeight;}")
    buttons=page.evaluate("()=>Object.fromEntries(['addButton','renderButton','renderNextButton','boxRenderButton'].map(name=>[name,editor[name].disabled]))")
    prompt=page.locator('textarea:visible').first
    before=prompt.input_value()
    if not prompt.is_disabled():
        prompt.click();page.keyboard.type('xy')
    else:
                assert page.locator('.h3pf').evaluate('(form)=>form.disabled'), 'the whole prompt form must be disabled'
    typed={'kept':page.evaluate('stored()===NEWER'),'field':prompt.input_value()==before}
    page.screenshot(path=str(ROOT/'.tmp'/'read-only-timeline-1440.png'))
    page.set_viewport_size({'width':390,'height':844})
    page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
    phone=hint.is_visible() and page.evaluate("()=>{const box=editor.readOnlyEl.getBoundingClientRect();return box.top>=0&&box.bottom<=innerHeight&&document.documentElement.scrollWidth<=innerWidth;}")
    page.screenshot(path=str(ROOT/'.tmp'/'read-only-timeline-390.png'))
    result={'host':host_failures,'story':story_failures,'note_shown':shown,'note_shown_phone':phone,'disabled':buttons,'typing':typed,'page_errors':errors}
    print(json.dumps(result))
    assert not host_failures and not story_failures,result
    assert shown and phone and all(buttons.values()) and all(typed.values()),result
    assert not errors,result
    print('pass')
    browser.close()
