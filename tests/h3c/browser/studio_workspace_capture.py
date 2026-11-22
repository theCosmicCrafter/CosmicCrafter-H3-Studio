"""Capture the isolated synthetic editing workspace at shipped viewport sizes."""
from pathlib import Path
from urllib.parse import urlparse, unquote
from playwright.sync_api import sync_playwright
from studio_fixture import FIXTURE as BASE
import ast
import json
import os
import re

ROOT = Path.cwd().resolve()
OUT = ROOT / '.impeccable' / 'review'
# Reuse the catalog fixture without running its interaction test.
tree = ast.parse((ROOT / 'tests/browser/reference_preparation.py').read_text())
SETUP = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == 'SETUP' for t in n.targets))
FIXTURE = BASE.replace('<head>', '<head><meta charset="utf-8">').replace("title:()=>'Video layers'", "title:()=>'Studio tracks · synthetic example'")
FIXTURE = FIXTURE.replace('host.sequenceName=', 'host.generationHistory=async()=>({ok:true,generations:[]});host.sequenceName=')
FIXTURE = FIXTURE.replace('const editor=new TimelineEditor(host);', SETUP + 'const editor=new TimelineEditor(host);')
OUT.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE') or
        'C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True, args=['--disable-gpu'])
    page = browser.new_page(viewport=dict(width=1440, height=1000))
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))

    def route(request):
        path = unquote(urlparse(request.request.url).path)
        if path == '/fixture':
            return request.fulfill(body=FIXTURE, content_type='text/html')
        if path == '/scripts/app.js':
            return request.fulfill(body='export const app=window.fixtureApp;', content_type='text/javascript')
        if path == '/scripts/api.js':
            return request.fulfill(body='export const api={apiURL:path=>path,addEventListener(){},fetchApi:async()=>({status:200,ok:true,json:async()=>({revision:0,value:null})})};', content_type='text/javascript')
        if path == '/view':
            movie = 'mp4' in request.request.url
            target = ROOT / ('tests/fixtures/video_layers/02a.mp4' if movie else '.tmp/studio-fixture-preview.png')
            data=target.read_bytes()
            byte_range=request.request.headers.get('range','') if movie else ''
            match=re.match(r'bytes=(\d+)-(\d*)',byte_range)
            if match:
                start=int(match[1]);end=min(len(data)-1,int(match[2]) if match[2] else len(data)-1)
                return request.fulfill(status=206,body=data[start:end+1],headers={'Content-Type':'video/mp4','Accept-Ranges':'bytes','Content-Range':f'bytes {start}-{end}/{len(data)}'})
            return request.fulfill(body=data, content_type='video/mp4' if movie else 'image/png')
        target = (ROOT / path.lstrip('/')).resolve()
        if ROOT in target.parents and target.is_file():
            return request.fulfill(body=target.read_bytes(), content_type='text/javascript')
        return request.abort()

    page.route('**/*', route)
    page.goto('https://h3c.test/fixture')
    page.wait_for_function('window.ready===true')
    page.evaluate('showStudio()')
    page.get_by_role('button', name='Add video lane', exact=True).click()
    page.evaluate('editor.playheadFrame=48;editor.trackEditor.addClip();editor.box().prompt="Close on the traveler’s hands as she opens the satchel. The street continues beneath the elevated train.";editor.commit();')
    for text in ['A new way home', 'Under the elevated train']:
        with page.expect_file_chooser() as chosen:
            page.get_by_role('button', name='Add text lane', exact=True).click()
        chosen.value.set_files(dict(name='words.json', mimeType='application/json',
            buffer=json.dumps(dict(segments=[dict(start=1, end=3, text=text)])).encode()))
        page.wait_for_function('(n)=>stored().text_lanes?.length===n', arg=1 if text == 'A new way home' else 2)
    page.evaluate('editor.select(1);editor.inspectClip();studio.setPage("viewer");studio.refresh()')

    def capture(name):
        page.evaluate('document.activeElement?.blur()')
        page.evaluate('''async()=>{for(const video of document.querySelectorAll('video')){video.pause();if(video.readyState<2)await new Promise(resolve=>{video.addEventListener('loadeddata',resolve,{once:true});setTimeout(resolve,2000)});}}''')
        page.wait_for_timeout(200)
        page.screenshot(path=str(OUT / name), full_page=True, animations='disabled')

    page.evaluate('editor.laneEl.scrollTop=0;studio.root.style.setProperty("--h3cx-track-h","450px")')
    capture('desktop.png')
    page.get_by_role('tab', name='Settings', exact=True).click()
    page.set_viewport_size(dict(width=1440, height=1700))
    capture('desktop-settings.png')
    page.set_viewport_size(dict(width=1440, height=1000))
    page.get_by_role('tab', name='Story', exact=True).click()
    capture('desktop-story.png')
    page.evaluate('studio.setPage("viewer")')
    page.get_by_role('button', name='Collapse video lanes', exact=True).click()
    capture('desktop-combined.png')
    page.get_by_role('tab', name='Cast', exact=True).click()
    page.wait_for_function('editor.cast.preparation.rows.length===2')
    capture('desktop-cast.png')
    page.get_by_role('button', name='Project settings', exact=True).click()
    page.get_by_role('textbox',name='Still prompt conversion instructions',exact=True).scroll_into_view_if_needed()
    capture('desktop-project.png')
    page.evaluate('studio.setPage("viewer")')
    page.set_viewport_size(dict(width=1024, height=768))
    capture('user-1024.png')
    page.set_viewport_size(dict(width=390, height=844))
    capture('mobile.png')
    page.get_by_role('button',name='Timeline',exact=True).click()
    capture('mobile-timeline.png')
    page.evaluate('studio.openFocus("cast")')
    page.get_by_role('button',name='Edit Mara reference',exact=True).click()
    capture('mobile-cast-detail.png')
    page.get_by_role('button', name='Back to references', exact=True).click()
    capture('mobile-cast-list.png')
    assert not errors, errors
    print(json.dumps(dict(captures=sorted(p.name for p in OUT.glob('*.png')), page_errors=errors)))
    browser.close()
