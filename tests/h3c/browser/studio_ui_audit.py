"""Capture every Studio surface with a linked Story, structured prompts and a long outline; no live services."""
from pathlib import Path
from urllib.parse import urlparse, unquote
from playwright.sync_api import sync_playwright
import ast
import json
import os
import re
import sys

sys.path.insert(0, str(Path(__file__).parent))
from studio_fixture import FIXTURE as BASE

ROOT = Path.cwd().resolve()
OUT = ROOT / '.impeccable' / 'audit'
tree = ast.parse((ROOT / 'tests/browser/reference_preparation.py').read_text())
SETUP = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == 'SETUP' for t in n.targets))
FIXTURE = BASE.replace('<head>', '<head><meta charset="utf-8">').replace("title:()=>'Video layers'", "title:()=>'The overpass'")
FIXTURE = FIXTURE.replace('host.sequenceName=', 'host.generationHistory=async()=>({ok:true,generations:[]});host.sequenceName=')
FIXTURE = FIXTURE.replace('const editor=new TimelineEditor(host);', SETUP + 'const editor=new TimelineEditor(host);')
OUT.mkdir(parents=True, exist_ok=True)

BEATS = ['Mara crosses the dry field toward the collapsed overpass.', 'She climbs the fallen deck and finds the crushed bus.',
         'Inside the bus, a child’s drawing of the city before.', 'Wind rises; the grass bends in waves around the pillars.',
         'She hears a radio crackle from the far end of the deck.', 'A stranger in a red scarf watches her from the ridge.',
         'They meet halfway along the deck and trade water for a map.', 'The map shows a second overpass, still standing.',
         'Night falls; they shelter under the deck by a small fire.', 'Dawn: Mara walks on alone toward the standing overpass.']


def prompt(i, beat):
    return (f"subject_definitions:\n<Subject 1> is Mara, a traveler in a weathered coat carrying a canvas satchel.\n"
            f"@image20 is the environment: a collapsed concrete highway overpass in a sea of tall dry grass.\n"
            f"summary:\n{beat}\n"
            f"retention_analysis:\n<Subject 1> keeps her coat, satchel and braid.\n"
            f"detailed_description:\nWarm late-afternoon light, 35mm, shallow depth of field.\n"
            f"[Shot 1] Wide: {beat}\n[Shot 2] Medium on <Subject 1>, wind in the grass.\n"
            f"overall_soundscape:\nWind through dry grass, distant creaking metal.\n"
            f"non_diegetic_music:\nSparse solo cello.\n")


IDS = ['a1', 'b2', 'c3'] + [f'k{i}' for i in range(4, 11)]
STATE = {'version': 1, 'prompt': 'Painterly anime, muted dusk palette.', 'boxes': [
    {'id': box_id, 'frames': 48 + 24 * (i % 3), 'exact': True, 'prompt': prompt(i, BEATS[i]), 'seed': 610001 + i,
     'cut': i in (0, 5, 8), 'memory': 'scene'} for i, box_id in enumerate(IDS)]}
STORY = {'title': 'The overpass', 'outline': [{'box': box_id, 'beat': BEATS[i]} for i, box_id in enumerate(IDS)],
         'sheet': 'Mara: weathered olive coat, canvas satchel, long dark braid.\nStranger: red scarf, grey jacket.\n'
                  'Place: collapsed overpass, dry grass, crushed bus under the deck.',
         'suggestions': [{'what': 'Stranger', 'boxes': ['k6', 'k7'], 'description': 'Red scarf, grey jacket.', 'why': 'Appears in two clips.'}],
         'notes': ['Clip 9 is a night scene; keep the fire as the only light.']}

STORY_JS = r"""async ([state, story]) => {
 editor.host.write(JSON.stringify(state)); editor.load();
 const {StoryPanel} = await import('/web/h3c_story_panel.mjs');
 const idea = {name:'idea_images', label:'Idea images', kind:'images', advanced:false, value:[], read:()=>[], upload:async()=>{},
   busy:()=>false, onChange(){}, viewUrl:()=>''};
 const panel = new StoryPanel({write(){}, rewrite(){}, checkAll(){}, cancel(){}, undo(){}, saveKey(){}, forgetKey(){},
   exportStory(){}, importStory(){}, openStudio(){}, settings:()=>[idea], setInput(){},
   listStories:async()=>({rows:[], names:{}}), autosaveEnabled:()=>true, setAutosave:async()=>{}});
 const inputs = () => [
   {name:'idea', label:'Idea', kind:'text', advanced:false, value:'', linked:'Prompt'}, idea,
   {name:'total_seconds', label:'Total length (seconds)', kind:'number', advanced:false, value:40, min:0, max:600},
   {name:'scope', label:'Scope', kind:'combo', advanced:false, value:'Whole Timeline', options:['Whole Timeline','Selected clip']},
   {name:'pictures', label:'Send pictures to the writer', kind:'boolean', advanced:false, value:true},
   {name:'story_base_url', label:'Story API URL', kind:'string', advanced:true, value:''},
   {name:'model', label:'Box writing model', kind:'string', advanced:true, value:''}];
 const node = {panel, inputs, setInput(){}};
 const ids = state.boxes.map(box => box.id);
 panel.showStory(story, id => ids.includes(id) ? ids.indexOf(id) + 1 : null);
 editor.host.story = () => node;
 studio.showStory(node);
 editor.select(1); editor.inspectClip(); studio.refresh();
}"""

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
            if not target.is_file():
                return request.abort()
            data = target.read_bytes()
            byte_range = request.request.headers.get('range', '') if movie else ''
            match = re.match(r'bytes=(\d+)-(\d*)', byte_range)
            if match:
                start = int(match[1]); end = min(len(data) - 1, int(match[2]) if match[2] else len(data) - 1)
                return request.fulfill(status=206, body=data[start:end + 1], headers={'Content-Type': 'video/mp4', 'Accept-Ranges': 'bytes', 'Content-Range': f'bytes {start}-{end}/{len(data)}'})
            return request.fulfill(body=data, content_type='video/mp4' if movie else 'image/png')
        target = (ROOT / path.lstrip('/')).resolve()
        if ROOT in target.parents and target.is_file():
            return request.fulfill(body=target.read_bytes(), content_type='text/javascript')
        return request.abort()

    page.route('**/*', route)
    page.goto('https://h3c.test/fixture')
    page.wait_for_function('window.ready===true')
    page.evaluate('showStudio()')
    page.evaluate(STORY_JS, [STATE, STORY])

    overflow = {}

    def capture(name, tall=None):
        if tall:
            page.set_viewport_size(dict(width=page.viewport_size['width'], height=tall))
        page.evaluate('document.activeElement?.blur()')
        page.wait_for_timeout(150)
        page.screenshot(path=str(OUT / name), animations='disabled')
        spill = page.evaluate('''() => [...document.querySelectorAll('.h3cx-inspector, .h3cx-focus-body')].flatMap(pane => {
            const edge = pane.getBoundingClientRect().right - (pane.offsetWidth - pane.clientWidth);
            return [...pane.querySelectorAll('*')].filter(n => n.getClientRects().length && n.getBoundingClientRect().right > edge + 1)
              .filter(n => !n.parentElement || n.parentElement.getBoundingClientRect().right <= edge + 1)
              .slice(0, 6).map(n => `${n.tagName.toLowerCase()}.${[...n.classList].join('.')} +${Math.round(n.getBoundingClientRect().right - edge)}px`);
        })''')
        if spill:
            overflow[name] = spill
        for part, selector in (('inspector', '.h3cx-inspector'), ('center', '.h3cx-center')):
            node = page.locator(selector)
            if node.is_visible():
                node.screenshot(path=str(OUT / name.replace('.png', f'-{part}.png')), animations='disabled')
        if tall:
            page.set_viewport_size(dict(width=page.viewport_size['width'], height=1000))

    def tab(name):
        page.locator('.h3cx-inspector [role=tab]').filter(has_text=name).first.click()

    only = set(sys.argv[1:])
    shots = [
        ('prompt', lambda: tab('Prompt'), 1700),
        ('shots', lambda: tab('Shots'), 1700),
        ('takes', lambda: tab('Takes'), None),
        ('settings', lambda: tab('Settings'), 1700),
        ('story', lambda: page.get_by_role('tab', name='Story', exact=True).click(), 1700),
        ('story-outline', lambda: (page.get_by_role('tab', name='Story', exact=True).click(),
                                   page.locator('.h3cx-subtabs [role=tab]').filter(has_text='Outline').click()), None),
        ('story-continuity', lambda: (page.get_by_role('tab', name='Story', exact=True).click(),
                                      page.locator('.h3cx-subtabs [role=tab]').filter(has_text='Continuity').click()), None),
        ('story-saved', lambda: (page.get_by_role('tab', name='Story', exact=True).click(),
                                 page.locator('.h3cx-subtabs [role=tab]').filter(has_text='Saved').click()), None),
        ('cast', lambda: page.get_by_role('tab', name='Cast', exact=True).click(), None),
        ('cast-characters', lambda: (page.get_by_role('tab', name='Cast', exact=True).click(),
                                     page.locator('.h3cr-tabs [role=tab]').filter(has_text='Characters').click()), None),
        ('references', lambda: page.get_by_role('tab', name='References', exact=True).click(), None),
        ('project', lambda: page.get_by_role('button', name='Project settings', exact=True).click(), 1500),
    ]
    for name, go, tall in shots:
        if only and name not in only:
            continue
        go()
        capture(f'{name}.png', tall)
        if name.split('-')[0] in ('story', 'cast', 'references', 'project'):
            page.evaluate('studio.setPage("viewer");studio.backToViewer?.()')
    if not only:
        page.evaluate('studio.setPage("viewer");studio.backToViewer?.()')
        rewrite = page.locator('.h3cx-inspector .h3ct-clip-actions').get_by_role('button', name='Rewrite selected clip', exact=True)
        assert rewrite.is_visible(), 'Rewrite selected clip sits in the clip actions'
        page.get_by_role('tab', name='Story', exact=True).click()
        assert page.locator('.h3cx-story').get_by_role('button', name='Rewrite selected clip').count() == 0
        page.locator('.h3cx-subtabs [role=tab]').filter(has_text='Outline').click()
        page.locator('.h3cs-beat[data-box="k4"]').click()
        assert page.evaluate('editor.box().id') == 'k4'
        assert page.locator('.h3cs-beat[data-box="k4"]').get_attribute('aria-current') == 'true'
        assert page.locator('.h3cx-inspector-title').inner_text() == 'Clip 4'
        page.evaluate('studio.setPage("viewer");studio.backToViewer?.()')
    if not only or 'mobile' in only:
        page.set_viewport_size(dict(width=390, height=844))
        page.get_by_role('button', name='Clip', exact=True).click()
        capture('mobile-clip.png')
    print(json.dumps(dict(captures=len(list(OUT.glob('*.png'))), overflow=overflow, page_errors=errors), indent=1))
    browser.close()
