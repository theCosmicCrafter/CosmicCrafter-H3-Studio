"""Optional approved Story reference images and their entity/look/scene scopes."""
import copy
import hashlib
import json
import math
import re

from . import image_recipe, stills, story_bible, timeline as rules

CATEGORIES = ('cast', 'locations', 'props')
ROLES = ('identity', 'appearance', 'location', 'prop', 'scene_layout')
HASH = re.compile(r'[a-f0-9]{64}')
NO_TEXT = 'The image contains no text, letters or numbers.'
# Character and location sheets are 16:9 at the workflow's own area unless the reference sets a size (Advanced: seed and
# dimensions); this is the size when that area cannot be read.
SHEET_SIZE = {'width': 2048, 'height': 1152}
# {description} marks where the character description goes; {look} is filled in for a look or a first design.
HUMAN_SHEET = 'A 16:9 landscape character reference sheet{look}, on a plain ivory background. The left third holds two large head studies stacked one above the other. The right two thirds hold four whole-figure studies standing side by side in four equal columns. Thin lines separate the panels. There is no text anywhere.\n\nTHE CHARACTER\n{description}\n\nLEFT THIRD, TOP HALF: HEAD, FRONT\nA close-up of the head and neck seen straight on, from the top of the head to the base of the neck, with every feature, covering and accessory exactly as described above.\n\nLEFT THIRD, BOTTOM HALF: HEAD, LEFT PROFILE\nDirectly below, the same head and neck at the same size in exact left profile, facing left.\n\nTHE FOUR FIGURES (right two thirds)\nFour whole-body views of the same character, head to feet, each as tall as its column, all the same size and standing on the same floor line, in the same neutral standing pose with the arms slightly away from the body and the feet flat on the floor.\nColumn 3, FRONT: facing the viewer.\nColumn 4, LEFT SIDE: in exact profile facing the left edge of the panel, showing the outside of the left arm and leg.\nColumn 5, BACK: with the back to the viewer.\nColumn 6, RIGHT SIDE: in exact profile facing the right edge of the panel, showing the outside of the right arm and leg.\n\nFINAL CHECK\nTwo stacked close-ups on the left: front above, left profile below. Four whole figures on the right: front, left side, back, right side. The same head, build, skin, outfit and carried items in every view, exactly as described. Nothing is added that the description does not give.'
CREATURE_SHEET = "A 16:9 landscape creature reference sheet{look}, on a plain ivory background. The left third is one tall panel; the right two thirds are a grid of 2 rows and 2 columns of wide panels. Thin lines separate the panels. There is no text anywhere.\n\nTHE CREATURE\n{description}\n\nLEFT PANEL: HEAD\nOne close study of the head and the start of the neck, in three-quarter view turned towards the left of the panel, filling the width of the panel, with every feature exactly as described above. It is the only head on the sheet.\n\nTHE FOUR BODY VIEWS (right two thirds)\nThe same body in four panels, seen without its head: the neck ends at the edge of the panel and nothing continues past it. Neutral standing pose in the creature's natural stance, feet or paws flat on the floor, with clear space around every foot.\nRow 1, column 1: left side view. The neck meets the left edge of the panel. The far legs are a half-step offset, so every leg can be seen.\nRow 1, column 2: right side view at the same scale and floor line. The neck meets the right edge of the panel.\nRow 2, column 1: back view from directly behind.\nRow 2, column 2: top-down view of the back, with the neck meeting the top edge of the panel.\n\nFINAL CHECK\nOne head study on the left. Four headless body views on the right: left side, right side, back, top-down. The same hide, markings, proportions and scale throughout. Nothing is added that the description does not give."
# The layout a reference's sheet follows; 'custom' sends only the text the user writes.
SHEET_LAYOUTS = {'human': HUMAN_SHEET, 'creature': CREATURE_SHEET, 'custom': ''}
LOCATION_GRID = ('A location reference sheet: one image divided into a grid of 2 rows and 2 columns by thin ivory gutters, '
                 'showing the same place from four clearly different camera positions: in row 1, column 1, a wide establishing '
                 'view from the front; in row 1, column 2, the reverse view from the opposite side, looking back the other way; '
                 'in row 2, column 1, a low ground-level view from one side; in row 2, column 2, a high view looking down on the '
                 'whole place. If the place has an interior (a booth, stall, room, building or vehicle you can step into), one of '
                 'the four panels, row 2, column 2, instead shows that interior from the inside, with its fittings, surfaces and '
                 'the way in visible; otherwise row 2, column 2 stays the high view. No two panels repeat the same viewpoint. '
                 'All four panels show one moment: the same time of day, '
                 'lighting, layout and materials. The location is empty: '
                 'no people, characters, animals or creatures appear in any panel. ' + NO_TEXT + '\nLocation: {description}')
LOCATION_LAYOUTS = {'grid': LOCATION_GRID, 'custom': ''}
# The layouts a reference can pick, the first one being the default. Objects and composed scenes have a single built-in layout.
LAYOUT_CHOICES = {'cast': tuple(SHEET_LAYOUTS), 'locations': tuple(LOCATION_LAYOUTS)}
OBJECT_GRID = ('An object reference sheet: one image on a plain ivory background, divided into a grid of 2 rows and 2 columns by '
               'thin rules and generous gutters, showing the same single object from four clearly different angles, each panel '
               'floating alone in blank ivory: in row 1, column 1, a front view; in row 1, column 2, a true side profile view; '
               'in row 2, column 1, a back view; in row 2, column 2, a three-quarter view from slightly above. Only the object '
               'appears: no hands, people, scenery, table, shadows or other props. The object keeps the same size, shape, '
               'colours, materials, wear and markings in every panel, with an equal scale and clear ivory space around it. '
               'Flat, even studio lighting. ' + NO_TEXT + '\nObject: ')
PEOPLE = re.compile(r'\b(characters?|people|persons?|figures?|actors?|crowds?)\b', re.I)


def validate(value):
    if value is None:
        return {'version': 1, 'generate': dict.fromkeys(CATEGORIES, False), 'assets': [], 'requests': []}
    if not isinstance(value, dict) or value.get('version') != 1:
        raise ValueError('Reference preparation needs version 1.')
    flags = value.get('generate', {})
    if not isinstance(flags, dict) or any(k not in CATEGORIES or type(v) is not bool for k,v in flags.items()):
        raise ValueError('Reference preparation switches must be cast, locations or props booleans.')
    rows = value.get('assets', [])
    if not isinstance(rows, list):
        raise ValueError('Reference preparation assets must be a list.')
    keys = set()
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get('key'), str) or not row['key']
                or row['key'] in keys or row.get('category') not in CATEGORIES or row.get('role') not in ROLES):
            raise ValueError('Reference asset needs a unique key, category and role.')
        keys.add(row['key'])
        if 'included' in row and type(row['included']) is not bool:
            raise ValueError('Reference asset inclusion must be a boolean.')
        if 'input_fingerprint' in row and not HASH.fullmatch(str(row['input_fingerprint'])):
            raise ValueError('Reference asset design fingerprint is invalid.')
        if 'seed' in row:
            if type(row['seed']) is not int or not 0 <= row['seed'] <= rules.MAX_SEED:
                raise ValueError('Reference seed must be an unsigned 64-bit integer.')
        edits = row.get('part_overrides', {})
        if not isinstance(edits, dict) or any(
                id not in PART_IDS or not isinstance(own, dict) or set(own)-{'text','enabled','choice'}
                or ('choice' in own and (id!='layout' or own['choice'] not in LAYOUT_CHOICES.get(row['category'], ())))
                or ('text' in own and not isinstance(own['text'], str))
                or ('enabled' in own and type(own['enabled']) is not bool) for id,own in edits.items()):
            raise ValueError('Reference prompt part edits must give text or enabled for layout, style, empty or unoccupied.')
        if not isinstance(row.get('candidates', []), list):
            raise ValueError('Reference candidates must be a list.')
        ids = set()
        for candidate in row.get('candidates', []):
            if (not isinstance(candidate, dict) or not isinstance(candidate.get('id'), str)
                    or candidate['id'] in ids or not HASH.fullmatch(str(candidate.get('sha256', '')))
                    or not HASH.fullmatch(str(candidate.get('input_fingerprint', '')))):
                raise ValueError('Reference candidate identity or hash is invalid.')
            rules.preview_file(candidate.get('file'))
            ids.add(candidate['id'])
        accepted = row.get('approved')
        if accepted is not None and (not isinstance(accepted, dict) or accepted.get('candidate_id') not in ids
                                    or type(accepted.get('revision')) is not int or accepted['revision'] < 1):
            raise ValueError('Reference approval must name a candidate and positive revision.')
    requests = value.get('requests', [])
    if not isinstance(requests, list) or any(not isinstance(r,dict) for r in requests):
        raise ValueError('Reference image requests must be a list of native receipts.')
    result = copy.deepcopy(value)
    result.update(generate={**dict.fromkeys(CATEGORIES, False), **flags}, assets=copy.deepcopy(rows),
                  requests=copy.deepcopy(requests))
    return result


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def scene_start(document, index):
    boxes = document.get('boxes', [])
    while index > 0 and not boxes[index].get('new_scene'):
        index -= 1
    return boxes[index]['id'] if boxes else ''


def _source_hashes(document, row, slots, body):
    hashes = dict(row.get('input_sources') or {})
    originals = {}
    for slot in slots:
        descriptor = document.get('reference_replacements', {}).get(slot)
        file = descriptor.get('file') if isinstance(descriptor,dict) else None
        file = file or next((p.get('file') for p in document.get('pictures',[]) if p['slot']==slot),None)
        if file:
            try:
                pin = stills.pin_image(file)
                hashes[slot] = pin['sha256']
                originals[slot] = dict(pin, slot=slot)
            except (ValueError,OSError):hashes[slot] = {'unavailable':file}
        elif slot not in hashes:hashes[slot] = None
    if body and body.get('workflow') and slots:
        parsed = rules.parse(body['timeline'])
        index = next((i for i,b in enumerate(parsed.boxes) if b.id in row['clips']),0)
        for slot in slots:
            if slot in document.get('disabled_refs',[]):continue
            try:
                refs = stills._pixel_references(dict(body,prompt='@'+slot),parsed,index,0,body['workflow']['api'])
                match = next((r for r in refs if r.get('slot')==slot),None)
                hashes[slot] = match.get('sha256', match.get('graph_sha256')) if match else None
                if match and 'file' in match:
                    originals[slot] = {k:match[k] for k in ('slot','file','sha256')}
                else:
                    originals.pop(slot, None)
            except (ValueError,OSError,KeyError) as error:
                hashes[slot] = {'unavailable':str(error)}
                originals.pop(slot, None)
    row['existing_images'] = [originals[s] for s in row['pictures']
                              if s in originals and s not in document.get('disabled_refs', [])]
    return {slot:hashes.get(slot) for slot in slots}


def catalog(document, body=None):
    state = validate(document.get('reference_preparation'))
    saved = {row['key']:row for row in state['assets']}
    boxes = document.get('boxes', [])
    ids = [box['id'] for box in boxes]
    entities = story_bible.entities(document['bible']) if document.get('bible') else []
    disabled = set(document.get('disabled_refs', []))
    rows = []
    for entity in entities:
        category = {'character':'cast', 'place':'locations', 'prop':'props'}[entity['kind']]
        visible = []
        for i,box in enumerate(boxes):
            schedule = box.get('schedule') or {}
            used = {*schedule.get('entities', []), schedule.get('place'), *(box.get('cast') or {}).values()}
            if entity['id'] in used:
                visible.append(i)
        versions = [(None, entity), *[(look['from'],look) for look in entity['looks']]]
        for start,version in versions:
            key = 'entity:' + entity['id'] + (':look:' + start if start else '')
            role = ('appearance' if start else 'identity') if category == 'cast' else ('location' if category == 'locations' else 'prop')
            active = [ids[i] for i in visible if (category=='cast' and start is None)
                      or (entity['looks'][story_bible.look_at(entity,ids,i)-1]['from']
                          if story_bible.look_at(entity,ids,i) else None)==start]
            rows.append({'key':key, 'category':category, 'role':role, 'entity':entity['id'], 'from':start,
                         'name':entity['name'] + (' — from ' + start if start else ''),
                         'description':version['description'], 'pictures':list(version.get('pictures', [])),
                         'identity_pictures':list(entity['pictures']) if category=='cast' else [],
                         'clips':active, 'included':True, 'candidates':[]})
    for index,box in enumerate(boxes):
        if index and not box.get('new_scene'):
            continue
        members = [b for i,b in enumerate(boxes) if scene_start(document,i)==box['id']]
        used = set()
        for member in members:
            schedule = member.get('schedule') or {}
            used.update([*schedule.get('entities', []), schedule.get('place'), *(member.get('cast') or {}).values()])
        sources = [row['key'] for row in rows if row.get('entity') in used
                   and row['category']!='cast' and any(b['id'] in row['clips'] for b in members)]
        rows.append({'key':'scene:'+box['id'], 'category':'locations', 'role':'scene_layout', 'scene':box['id'],
                     'name':'Composed scene — '+box['id'], 'description':'An unoccupied scene with the approved location and objects. '
                     'Keep room geometry, materials, lighting and object placement consistent.',
                     'sources':sources, 'pictures':[], 'clips':[b['id'] for b in members], 'included':False, 'candidates':[]})
    for row in rows:
        stored = saved.pop(row['key'], {})
        for key in ('included','prompt','seed','size','candidates','approved','slot','sources','include_character','input_sources','part_overrides'):
            if key in stored:
                row[key] = copy.deepcopy(stored[key])
        row.setdefault('prompt', row['description'])
        source_pictures = [s for s in row['pictures'] if s!=row.get('slot')]
        identity = row.get('identity_pictures', []) if row['role']=='appearance' else []
        requested = re.sub(r'<image([1-9]\d*)>',lambda m:'@image'+m[1],row['prompt'],flags=re.I)
        prompt_slots = [slot for kind,slot in rules.mentions(requested) if kind=='image'] if row['role']!='scene_layout' else []
        descriptors = _source_hashes(document, row, list(dict.fromkeys([*source_pictures,*identity,*prompt_slots])), body)
        row['input_sources'] = descriptors
        row['input_fingerprint'] = fingerprint({k:row.get(k) for k in ('key','role','description','prompt','clips','sources','include_character')}
                                               | {'pictures':source_pictures,'identity':identity,'files':descriptors,
                                                  'style':story_bible.style(document.get('bible'))}
                                               | ({'parts':row['part_overrides']} if row.get('part_overrides') else {}))
        row['prompt_parts'] = resolve_parts(document, row)
        accepted = row.get('approved') or {}
        candidate = next((c for c in row['candidates'] if c['id']==accepted.get('candidate_id')), None)
        enabled = [s for s in row['pictures'] if s not in disabled]
        if candidate:
            row['status'] = 'approved' if candidate['input_fingerprint']==row['input_fingerprint'] and row.get('slot') not in disabled else 'outdated'
        elif enabled and (not body or not body.get('workflow') or any(isinstance(descriptors.get(s), str) for s in enabled)):
            row['status'] = 'approved'
        else:
            row['status'] = 'candidates' if row['candidates'] else 'missing'
    by_key = {r['key']:r for r in rows}
    for row in rows:
        if row['role']!='scene_layout':
            continue
        dependencies = []
        for key in row.get('sources', []):
            source = by_key.get(key)
            if source is not None:
                dependencies.append({'key':key,'design':source['input_fingerprint'],'approval':source.get('approved'),
                                     'pictures':source.get('pictures')})
        row['input_fingerprint'] = fingerprint({'design':row['input_fingerprint'],'dependencies':dependencies})
        accepted = row.get('approved') or {}
        candidate = next((c for c in row['candidates'] if c['id']==accepted.get('candidate_id')), None)
        if candidate:
            row['status'] = 'approved' if candidate['input_fingerprint']==row['input_fingerprint'] and row.get('slot') not in disabled else 'outdated'
    rows.extend(dict(copy.deepcopy(row), status='orphan', clips=[]) for row in saved.values())
    return rows


def required(document, box_id, body=None):
    flags = validate(document.get('reference_preparation'))['generate']
    return [r['key'] for r in catalog(document,body) if not r.get('from') and r['role'] not in ('appearance','scene_layout')
            and flags[r['category']] and r.get('included', True)
            and box_id in r['clips'] and r['status'] not in ('approved','orphan')]


def _row(document, key, body=None):
    row = next((r for r in catalog(document,body) if r['key']==key), None)
    if not row or row['status']=='orphan':
        raise ValueError('Reference owner was removed; choose a current Story entity or scene.')
    return row


def _approved_pixels(document, row, body):
    if row['status']!='approved':
        raise ValueError('Approve '+row['name']+' before composing the scene.')
    accepted = row.get('approved') or {}
    candidate = next((c for c in row['candidates'] if c['id']==accepted.get('candidate_id')), None)
    if candidate:
        pin = stills.pin_image(candidate['file'])
        if pin['sha256']!=candidate['sha256']:
            raise ValueError('Approved '+row['name']+' image bytes changed.')
        return [dict(pin, roles=[row['role']+': '+row['name']], asset_key=row['key'],
                     approval_revision=accepted['revision'], **({'slot':row['slot']} if row.get('slot') else {}))]
    parsed = rules.parse(body['timeline'])
    selection = dict(body, prompt=' '.join('@'+s for s in row['pictures']))
    index = next((i for i,b in enumerate(parsed.boxes) if b.id in row['clips']), 0)
    return [dict(ref,roles=[row['role']+': '+row['name']],asset_key=row['key'])
            for ref in stills._pixel_references(selection,parsed,index,0,body['workflow']['api'])]


def prepare(body):
    try:
        recipe = body['recipe']
        if recipe.get('version')!=2 or recipe.get('adapter')!='pixels':
            raise ValueError('Reference generation needs a connected version-2 pixel recipe. Import images or connect an image generator.')
        document = json.loads(body['timeline'])
        parsed = rules.parse(body['timeline'])
        row = _row(document, body['asset_key'], body)
        for slot,value in row['input_sources'].items():
            if isinstance(value,dict) and 'unavailable' in value:
                raise ValueError('Reference @'+slot+' is unavailable: '+str(value['unavailable']))
        if row['input_fingerprint']!=body.get('input_fingerprint'):
            raise ValueError('Reference design changed; refresh preparation before generating.')
        if not isinstance(body.get('prompt'),str) or not body['prompt'].strip():
            raise ValueError('Write a still-image reference prompt before generating.')
        refs = []
        prompt = body['prompt']
        if row['role']=='scene_layout':
            for key in row['sources']:
                source = _row(document,key,body)
                if source['category']=='cast' and not row.get('include_character'):
                    continue
                refs.extend(_approved_pixels(document,source,body))
            if not refs:
                raise ValueError('Choose and approve location/object references before composing the scene.')
        elif row['category']=='locations':
            pass
        else:
            # Only explicit asset inputs: never shot anchors, prior frames or video memory.
            identity = row['identity_pictures'] if row['role']=='appearance' else []
            requested = re.sub(r'<image([1-9]\d*)>',lambda m:'@image'+m[1],prompt,flags=re.I)
            selection = dict(body,prompt=' '.join('@'+s for s in identity)+' '+requested)
            index = next((i for i,b in enumerate(parsed.boxes) if b.id in row['clips']),0)
            refs = stills._pixel_references(selection,parsed,index,0,body['workflow']['api'])
            for ref in refs:
                ref['roles'] = ['identity' if ref['slot'] in identity else 'reference for '+row['name']]
            if row['role']=='appearance':
                if not identity:
                    base = _row(document,'entity:'+row['entity'],body)
                    refs = _approved_pixels(document,base,body)+refs
                if not refs:
                    raise ValueError('Import or approve the original identity image for '+row['name']+' first.')
        parts = [p for p in resolve_parts(document, row) if p['enabled']]
        lines = lambda where: [p['text'].strip() for p in parts if p['where']==where and p['text'].strip()]
        before = lines('before')
        # A layout that says where the description goes gets it there; any other text comes first and the description follows.
        placed = any('{description}' in text for text in before)
        before = [text.replace('{description}', prompt) for text in before]
        planned = dict(body,prompt='\n'.join([*before, *([] if placed else [prompt]), *lines('after')]),frame=0)
        # Character and location sheets are 16:9 unless the reference sets a size; a composed scene follows the workflow.
        sheet = row['role']!='scene_layout' and row['category'] in ('cast','locations') and any(p['id']=='layout' for p in parts)
        if sheet and not body.get('size') and all(recipe.get('bindings',{}).get('size',{}).get(d) for d in SHEET_SIZE):
            planned['size'] = sheet_size(recipe, body['workflow'].get('api', {}))
        return image_recipe.prepare(recipe,body['workflow'],planned,refs)
    except (ValueError,OSError,KeyError,TypeError) as error:
        return {'ok':False,'error':str(error)}


def sheet_size(recipe, graph):
    """A size that is exactly 16:9; the aspect ratio is all a sheet asks for.

    Sizes are multiples of 32 and an exact 16:9 pair on that grid comes in steps of 512 x 288, so the step nearest the
    size the workflow's width and height are set to is used. A workflow that works from a megapixel setting only reads the
    ratio and renders at its own size. Falls back to SHEET_SIZE when the workflow's values cannot be read."""
    area = None
    try:
        bound = recipe['bindings']['size']
        width, height = [image_recipe._scalar(graph, graph[bound[d][-1]['node']]['inputs'][bound[d][-1]['input']])
                         for d in ('width', 'height')]
        if all(type(v) in (int, float) and v > 0 for v in (width, height)):
            area = width * height
    except (KeyError, IndexError, TypeError, ValueError):
        pass
    if not area or area < 512 * 512:
        return dict(SHEET_SIZE)
    steps = range(1, 16384 // 512 + 1)
    step = min(steps, key=lambda k: abs(math.log(k * k * 512 * 288 / area)))
    return {'width': 512 * step, 'height': 288 * step}


PART_IDS = ('layout', 'unoccupied', 'empty', 'style')


def _parts(document, row, layout='human'):
    """Text the Studio adds around a reference's own description, in the order it is sent."""
    parts = []
    def add(id, label, where, text):
        parts.append({'id':id, 'label':label, 'where':where, 'text':text.strip()})
    if row['role']=='scene_layout':
        if not row.get('include_character'):
            add('unoccupied', 'Empty scene', 'before', 'An unoccupied location, with no people.')
    elif row['category']=='locations':
        add('layout', 'Location sheet layout', 'before', LOCATION_LAYOUTS.get(layout, LOCATION_GRID))
    elif row['category']=='props':
        add('layout', 'Object sheet layout', 'before', OBJECT_GRID)
    else:
        look = (' of the same character as the identity reference, wearing the appearance described below'
                if row['role']=='appearance' else ' for the character described below')
        add('layout', 'Character sheet layout', 'before', SHEET_LAYOUTS.get(layout, HUMAN_SHEET).replace('{look}', look))
    style = _style(document, row)
    if style:
        add('style', 'Visual style', 'after', 'Visual style: '+style)
    if row['role']=='location':
        add('empty', 'Empty place', 'after', 'The place is empty in every panel.')
    return parts


def resolve_parts(document, row):
    """The parts with this reference's own edits applied; `default` is what the Studio would send without them."""
    overrides = row.get('part_overrides') or {}
    choices = LAYOUT_CHOICES.get(row['category'], ())
    layout = (overrides.get('layout') or {}).get('choice')
    layout = layout if layout in choices else (choices[0] if choices else None)
    result = []
    for part in _parts(document, row, layout):
        own = overrides.get(part['id']) or {}
        text = own['text'] if isinstance(own.get('text'), str) else part['text']
        part = dict(part, default=part['text'], text=text, enabled=own.get('enabled') is not False,
                    edited=text.strip()!=part['text'])
        if part['id']=='layout' and choices:
            part.update(choice=layout, choices=list(choices))
        result.append(part)
    return result


def _style(document, row):
    """The Story style without sentences that would paint another character, or any figure into an empty place."""
    bible = document.get('bible')
    style = story_bible.style(bible)
    if not style or row.get('include_character'):
        return style
    names = [e['name'].strip() for e in story_bible.entities(bible) if e['kind']=='character' and e['id']!=row.get('entity')]
    patterns = [re.compile(r'(?<!\w)'+re.escape(name)+r'(?!\w)', re.I) for name in names if name]
    if row['category']!='cast':
        patterns.append(PEOPLE)
    # A sentence about another character that never names them ("only the curator wears a cobalt coat")
    # shares several distinctive words with that character's description.
    others = [_words(e.get('description', '')) for e in story_bible.entities(bible)
              if e['kind']=='character' and e['id']!=row.get('entity')]
    sentences = re.split(r'(?<=[.!?])\s+', style.strip())
    return ' '.join(s for s in sentences if not any(p.search(s) for p in patterns)
                    and not any(len(_words(s) & words)>=2 for words in others))


_COMMON = frozenset('with that this from over into onto than then them they their there where which while also only each both '
                    'more most very without around across along about after before under above between'.split())


def _words(text):
    return {w for w in re.findall(r'[a-z]{4,}', text.lower()) if w not in _COMMON}


def result(body):
    answer = stills.result(body)
    if answer.get('ok') and answer.get('state')=='complete':
        try:
            answer['images'] = [dict(image, **stills.pin_image(image['file'])) for image in answer['images']]
        except (ValueError,OSError) as error:
            return {'ok':False,'error':str(error)}
    return answer


def require_ready(document, box_id, body=None):
    missing = required(document,box_id,body)
    if missing:
        rows = {r['key']:r for r in catalog(document,body)}
        raise ValueError('Prepare and approve references before generating this still: '+', '.join(rows[k]['name'] for k in missing)+'. Or disable their preparation requirement.')


def _candidate(row):
    accepted = row.get('approved') or {}
    return next((c for c in row.get('candidates',[]) if c['id']==accepted.get('candidate_id')),None)


def references(document, box_id, body=None, *, entities=None):
    if not document.get('reference_preparation') and body is None:
        return []
    disabled = document.get('disabled_refs', [])
    refs = []
    rows = catalog(document)
    if entities is not None:
        locations = {row['key'] for row in rows if row['role']=='location' and row.get('entity') in entities
                     and box_id in row['clips']}
        rows = [row for row in rows if row.get('entity') in entities or
                (row['role']=='scene_layout' and locations.intersection(row.get('sources', [])))]
    for row in rows:
        candidate = _candidate(row)
        if not candidate or box_id not in row['clips'] or row.get('slot') in disabled:
            continue
        pin = stills.pin_image(candidate['file'])
        if pin['sha256']!=candidate['sha256']:
            raise ValueError('Approved '+row['name']+' image bytes changed.')
        refs.append(dict(pin,roles=[row['role']+': '+row['name']],slot=row['slot'],asset_key=row['key'],
                         approval_revision=row['approved']['revision']))
    if body is not None:
        owners = [(row, slot) for row in rows if box_id in row['clips'] for slot in row.get('pictures', [])
                  if slot != row.get('slot') and slot not in disabled]
        if owners:
            parsed = rules.parse(body['timeline'])
            index = next(i for i, box in enumerate(parsed.boxes) if box.id == box_id)
            selection = dict(body, prompt=' '.join('@'+slot for _,slot in owners))
            pixels = {r['slot']:r for r in stills._pixel_references(selection, parsed, index, body.get('frame', 0), body['workflow']['api'])}
            for row,slot in owners:
                refs.append(dict(copy.deepcopy(pixels[slot]), roles=[row['role']+': '+row['name']], asset_key=row['key']))
    return refs


def identity_slots(document, box_id, *, entities=None):
    if not document.get('reference_preparation'):
        return []
    return list(dict.fromkeys(slot for row in catalog(document) if row['role']=='appearance' and _candidate(row)
                             and (entities is None or row.get('entity') in entities)
                             and box_id in row['clips'] and row.get('slot') not in document.get('disabled_refs',[])
                             for slot in row['identity_pictures']))


def _free_slot(document):
    used = set()
    def visit(value):
        if isinstance(value,dict):
            for key,child in value.items():
                visit(key);visit(child)
        elif isinstance(value,list):
            for child in value:visit(child)
        elif isinstance(value,str):
            used.update(int(n) for n in re.findall(r'(?<![\w])@?image([1-9]\d*)(?!\w)',value))
    visit(document)
    number = 17
    while number in used:number+=1
    return 'image'+str(number)


def approve(document, asset_key, candidate_id, expected_revision, body=None):
    row = _row(document,asset_key,body)
    current = (row.get('approved') or {}).get('revision',0)
    if type(expected_revision) is not int or current!=expected_revision:
        raise ValueError('Reference approval changed; review the current candidates again.')
    candidate = next((c for c in row['candidates'] if c['id']==candidate_id),None)
    if not candidate or candidate['input_fingerprint']!=row['input_fingerprint']:
        raise ValueError('Reference design changed; generate or upload a current candidate.')
    pin = stills.pin_image(candidate['file'])
    if pin['sha256']!=candidate['sha256']:
        raise ValueError('Reference candidate image bytes changed.')
    for source in candidate.get('provenance',{}).get('references',[]):
        if source.get('file') and stills.pin_image(source['file'])['sha256']!=source['sha256']:
            raise ValueError('A source reference image changed since this candidate was generated.')
    result = copy.deepcopy(document)
    state = validate(result.get('reference_preparation'))
    result['reference_preparation'] = state
    stored = next(a for a in state['assets'] if a['key']==asset_key)
    slot = stored.get('slot') or _free_slot(result)
    picture = {'slot':slot,'file':copy.deepcopy(candidate['file']),'title':row['name']}
    existing = next((i for i,p in enumerate(result.get('pictures',[])) if p['slot']==slot),None)
    if existing is None:result.setdefault('pictures',[]).append(picture)
    else:result['pictures'][existing]=picture
    if row.get('entity'):
        bible = copy.deepcopy(result['bible'])
        entity = next(e for e in bible['entities'] if e['id']==row['entity'])
        owner = next(look for look in entity['looks'] if look['from']==row['from']) if row.get('from') else entity
        owner['pictures'] = [s for s in owner.get('pictures',[]) if s!=stored.get('slot')]+[slot]
        answer = story_bible.apply(result,bible)
        result['bible'] = answer['bible']
        for box in result.get('boxes',[]):
            for field,mapping in (('prompt','prompts'),('cast','casts'),('source','sources')):
                if box['id'] in answer[mapping]:box[field]=answer[mapping][box['id']]
    stored.update(input_sources=copy.deepcopy(row['input_sources']),slot=slot,approved={'candidate_id':candidate_id,'revision':current+1})
    rules.parse(json.dumps(result))
    return result


def native_prompt(parsed, index):
    """Deliver approved scoped assets through the existing H3 mention/transport path."""
    if not parsed.reference_preparation:return ''
    document = {'bible':parsed.bible,'reference_preparation':parsed.reference_preparation,
                'pictures':parsed.pictures,'reference_replacements':parsed.reference_replacements,
                'disabled_refs':parsed.disabled_refs,'boxes':[
                    {'id':box.id,'new_scene':box.new_scene,**parsed.story[i]} for i,box in enumerate(parsed.boxes)]}
    labels=[]
    for row in catalog(document):
        if _candidate(row) and parsed.boxes[index].id in row['clips'] and row.get('slot') not in parsed.disabled_refs:
            role='scene layout' if row['role']=='scene_layout' else row['role']
            labels.append('@'+row['slot']+' is the approved '+role+' reference for '+row['name']+'.')
    return '\n'.join(labels)
