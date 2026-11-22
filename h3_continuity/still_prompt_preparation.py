"""One explicit Story-model batch projecting current Timeline targets into editable still prompts."""

import asyncio
import copy
import dataclasses
import json
import re

from . import image_descriptions, reference_replacements, story_bible, story_bible_write, story_context, story_instructions, story_prompts, story_vision, stills, timeline as rules
from .timing import FPS

COMPONENTS = ('subject', 'setting', 'style', 'lighting', 'color', 'camera')
BOX_FIELDS = ('id', 'prompt', 'frames', 'exact', 'cut', 'new_scene', 'first', 'last', 'source', 'schedule', 'cast', 'join')
DEFAULT_INSTRUCTIONS = """Prepare one rich prompt for a single visible instant at each supplied target.
Describe six concrete components: subject and visible state; setting and approved spatial layout; visual style
and material detail; lighting and atmosphere; color palette; camera and composition. The prompt combines them
into natural image prose. Preserve the supplied identity, outfit schedule, location geometry, props and camera.
Enrich expression, composition, texture, light and color within the authored scene.
Treat identity pictures as identity evidence, not as a fixed reference pose, expression, camera or lighting.
Describe the requested pose and expression actively. Integrate people and objects into the scene with coherent
perspective and scale, illumination direction and color, reflected light, cast and contact shadows, depth of
field and physically plausible occlusion. Preserve location geometry while adapting the view to the requested
camera. Describe one unified scene, with every subject illuminated and grounded within that environment.

Each context contains only its selected source shot and applicable visual context. First is its opening visible
moment; an interior Shot is its requested moment; Last is the reached state at the supplied actual box end.
Freeze action into one visible state. Exclude future events, motion sequences, dialogue, sound, music, timestamps
and H3 markup from prompt prose. Shot markers are temporal stages; they do not imply a cut or a new camera.
Continuous Last and next First share one canonical record and must receive the exact same prompt. Compare both
contexts, preserving reached state, screen direction, prop ownership and appearance. If their states conflict or
the endpoint is ambiguous, list the issue for review instead of inventing an event. Keep logical @imageN names;
never write native <Picture N> tokens, Qwen image ordinals or subject placeholder labels in the saved prose.
Return exactly the requested IDs and members. Do not rewrite the story, timing, cast, schedule or instructions.
Reply only with the JSON object required by the response schema."""
NATIVE = re.compile(r'<(?:Subject|Picture|Audio|Video|Speaker)\s+\d+>|</?d>|<scenetrans>|\[(?:Shot|Audio)\b', re.I)


def projection(document, instructions=None, context=39, references=()):
    """Semantic snapshot shared with the synchronous UI stale check; render state is deliberately absent."""
    if instructions is None:
        instructions = (document.get('still_prompt_preparation') or {}).get('instructions', DEFAULT_INSTRUCTIONS)
    boxes = []
    for box in document.get('boxes', []):
        boxes.append({key: copy.deepcopy(box.get(key, False if key in ('exact', 'cut', 'new_scene') else
                      '' if key in ('first', 'last', 'prompt') else None)) for key in BOX_FIELDS})
    return dict(version=1, instructions=instructions, context=int(context), prompt=document.get('prompt', ''),
                bible=copy.deepcopy(document.get('bible')), reference_descriptions=copy.deepcopy(document.get('reference_descriptions', {})),
                reference_replacements=copy.deepcopy(document.get('reference_replacements', {})),
                disabled_refs=copy.deepcopy(document.get('disabled_refs', [])), pictures=copy.deepcopy(document.get('pictures', [])),
                refmods=copy.deepcopy(document.get('refmods', [])),
                approved_references=sorted([dict(key=asset.get('key', ''), slot=asset.get('slot', ''),
                    included=asset.get('included') is not False, candidate_id=asset['approved'].get('candidate_id', ''),
                    revision=asset['approved'].get('revision', 0))
                    for asset in (document.get('reference_preparation') or {}).get('assets', []) if asset.get('approved')],
                    key=lambda asset: asset['key']),
                boxes=boxes, references=[dict(name=ref['name'], file=copy.deepcopy(ref.get('file')),
                                             description=ref.get('description', '')) for ref in references])


def _shots(prompt):
    # Use exactly the marker/header boundaries of rules._shot_frames and the browser's promptShots.
    dialogue = list(re.finditer(r'<d>[\s\S]*?(?:</d>|$)', prompt))
    base = ['integrated_multimodal_description', 'overall_soundscape', 'non_diegetic_music']
    ref = ['subject_definitions', 'summary', 'retention_analysis', 'detailed_description', *base[1:]]
    headers = [m for m in re.finditer(r'^[ \t]*(' + '|'.join(dict.fromkeys(base + ref)) + r'):', prompt, re.M)
               if not any(d.start() <= m.start() < d.end() for d in dialogue)]
    structured = [m[1] for m in headers] in (base, ref)
    start, end = 0, len(prompt)
    if structured:
        at = next(i for i, m in enumerate(headers) if m[1] in ('detailed_description', base[0]))
        start, end = headers[at].end(), headers[at + 1].start()
    source = prompt[start:end]
    marked = source if structured else re.sub(r'<d>[\s\S]*?(?:</d>|$)', lambda m: ' ' * len(m[0]), source)
    markers = [m for m in re.finditer(r'^[ \t]*\[Shot ([1-9]\d*)\](?=\s|$)', marked, re.M if structured else re.M | re.I)
               if not structured or not any(d.start() <= start + m.start() < d.end() for d in dialogue)]
    shots = [dict(number=int(m[1]), text=source[m.end():markers[i + 1].start() if i + 1 < len(markers) else len(source)].strip())
             for i, m in enumerate(markers)]
    return shots or [dict(number=1, text=source.strip())], source[:markers[0].start()].strip() if markers else ''


def _visual(text):
    return re.sub(r'<d>[\s\S]*?(?:</d>|$)', '', text, flags=re.I).split('overall_soundscape:')[0].split('non_diegetic_music:')[0].strip()


def _context(document, parsed, index, target, context, shots, style, frames):
    box = document['boxes'][index]
    frame = stills._target_frame(parsed, index, target, context)
    played, carried = rules.box_length(parsed, index, context)
    chosen = target.get('shot', 1)
    issues = []
    if target['kind'] == 'last':
        timed = [shot for shot in shots if shot['number'] in frames and frames[shot['number']] <= frame]
        chosen = timed[-1]['number'] if timed else shots[-1]['number']
        if len(shots) > 1 and any(shot['number'] not in frames for shot in shots):
            issues.append('Some source shot timing is missing, duplicated or beyond the actual box end; review the ending state.')
    selected = next((shot for shot in shots if shot['number'] == chosen), shots[0])
    later = [value for number, value in frames.items() if value > frames.get(chosen, 0)]
    shot = dict(number=selected['number'], text=_visual(selected['text']), start_frame=frames.get(chosen, 0),
                end_frame=min(later) if later else played - (0 if carried else 1))
    ids = [item['id'] for item in document['boxes']]
    bible = document.get('bible') or {'entities': []}
    made = story_bible_write.compiled(box, bible, ids, index) if box.get('source') else None
    shape = (box.get('source') or {}).get('frame') or {}
    current = (made is not None and made[0] == box['prompt'] and shape.get('frames') == played + carried
               and shape.get('carried') == carried)
    semantic = (box['source']['reply'].get('shots') or []) if current else []
    selected_semantic = semantic[chosen - 1] if chosen <= len(semantic) else None
    if selected_semantic:
        shot['semantic'] = {key: copy.deepcopy(selected_semantic[key]) for key in
                            ('start_ms', 'cut', 'visible_people', 'subjects', 'composition', 'actions', 'camera',
                             'opening_state', 'ending_state', 'viewpoint') if key in selected_semantic}
        for action in shot['semantic'].get('actions', []):
            action.pop('sound', None)
    labels = set(re.findall(r'<Subject [1-9]\d*>', shot['text']))
    definitions = {label: text for label, (_, _, text) in story_bible.subject_lines(box['prompt']).items() if label in labels}
    selected_ids = set(selected_semantic.get('subjects', [])) if selected_semantic else set()
    selected_ids.update((box.get('cast') or {}).get(label) for label in labels)
    schedule = box.get('schedule') or {}
    selected_ids.add(schedule.get('place'))
    selected_ids.update(entity['id'] for entity in bible['entities'] if entity.get('name', '') and
                        re.search(r'\b' + re.escape(entity['name']) + r'\b', shot['text'], re.I))
    entities = [dict(id=entity['id'], kind=entity['kind'], name=entity['name'],
                     description=story_bible.wording(entity, ids, index), pictures=story_bible.pictures_at(entity, ids, index))
                for entity in bible['entities'] if entity['id'] in selected_ids]
    visual = '\n'.join([document.get('prompt', ''), style, shot['text'], *definitions.values(),
                        *(entity['description'] for entity in entities)])
    refs = list(dict.fromkeys([slot for kind, slot in rules.mentions(visual) if kind == 'image'] +
                            [slot for entity in entities for slot in entity['pictures']]))
    endpoint = box.get(target['kind'], '') if target['kind'] == 'last' or target['kind'] == 'first' and rules.is_fresh(parsed, index) else ''
    if endpoint and endpoint not in refs:
        refs.append(endpoint)
    refs = [slot for slot in refs if not rules.reference_disabled(slot, parsed.disabled_refs)]
    result = dict(box=box['id'], target=dict(target), frame=frame, generated_ms=round((frame + max(0, carried - 1)) * 1000 / FPS),
                  end_ms=round((played + carried) * 1000 / FPS), delivered_ms=round(played * 1000 / FPS),
                  shot=shot, subject_definitions=definitions, entities=entities, references=refs,
                  shared_visual_context=_visual(document.get('prompt', '')), style=_visual(style),
                  endpoint_reference=endpoint if endpoint in refs else '',
                  schedule=dict(entities=[item['id'] for item in entities if item['kind'] != 'place'], place=schedule.get('place')),
                  issues=issues)
    if current and target['kind'] == 'last' and chosen == len(semantic):
        result['terminal_state'] = copy.deepcopy(box['source']['reply'].get('terminal_state', {}))
    return result


def plan(document, instructions=DEFAULT_INSTRUCTIONS, context=39, references=()):
    """Pure selected-shot tasks, with one canonical Last/next-First row on native continuous boundaries."""
    parsed = rules.parse(json.dumps(document))
    if not parsed.boxes or any(not box.prompt.strip() for box in parsed.boxes):
        raise ValueError('Write a prompt for every Timeline box before preparing still prompts.')
    records = []
    for index, box in enumerate(parsed.boxes):
        played, carried = rules.box_length(parsed, index, context)
        last = played - (0 if carried else 1)
        shots, style = _shots(box.prompt)
        frames = rules._shot_frames(box.prompt, carried, last)
        targets = [dict(kind='first'), *[dict(kind='shot', shot=shot['number']) for shot in shots
                   if shot['number'] != 1 and shot['number'] in frames], *([dict(kind='last')] if last else [])]
        for target in targets:
            member = dict(box=box.id, target=target)
            item = _context(document, parsed, index, target, context, shots, style, frames)
            if target['kind'] == 'first' and index and not rules.is_fresh(parsed, index):
                record = next(record for record in records if record['id'] == parsed.boxes[index - 1].id + ':last')
                record['members'].append(member)
                record['contexts'].append(item)
            else:
                records.append(dict(id=_identifier(member), members=[member], contexts=[item]))
    return dict(source=projection(document, instructions, context, references), prompts=records)


def _identifier(member):
    target = member['target']
    return member['box'] + ':' + target['kind'] + (':' + str(target['shot']) if target['kind'] == 'shot' else '')


def _records(value, *, generated=False):
    if not isinstance(value, list):
        raise ValueError('Still prompts must be a list.')
    identifiers, members = set(), set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {'id', 'members', 'prompt', 'components', 'issues'}:
            raise ValueError('Each still prompt needs id, members, prompt, components and issues.')
        if not isinstance(item['id'], str) or not item['id'] or item['id'] in identifiers:
            raise ValueError('Still prompt IDs must be unique.')
        identifiers.add(item['id'])
        if not isinstance(item['members'], list) or not item['members']:
            raise ValueError('Still prompt members must name at least one target.')
        for member in item['members']:
            if not isinstance(member, dict) or set(member) != {'box', 'target'} or not isinstance(member['box'], str) or not member['box']:
                raise ValueError('Still prompt members need a box and a target.')
            target = rules._preview_target(member['target'], 1)
            if target != member['target'] or target.get('shot') == 1:
                raise ValueError('Still prompt members must use the canonical First target.')
            key = _identifier(member)
            if key in members:
                raise ValueError('Still prompt members must be unique across records.')
            members.add(key)
        if item['id'] != _identifier(item['members'][0]):
            raise ValueError('Still prompt id must identify the first of its canonical members.')
        if not isinstance(item['prompt'], str) or generated and not item['prompt'].strip():
            raise ValueError('Still prompt prose must be text, nonempty for a generated reply.')
        components = item['components']
        if not isinstance(components, dict) or set(components) != set(COMPONENTS) or any(
                not isinstance(text, str) or generated and not text.strip() for text in components.values()):
            raise ValueError('Still prompt components need subject, setting, style, lighting, color and camera text.')
        if generated and NATIVE.search('\n'.join([item['prompt'], *components.values()])):
            raise ValueError('Still prompt prose must be renderer-neutral; keep logical @imageN references.')
        if not isinstance(item['issues'], list) or any(not isinstance(issue, str) for issue in item['issues']):
            raise ValueError('Still prompt issues must be a list of text.')
    return copy.deepcopy(value)


def validate(value):
    """Validate persisted metadata without re-preparing it; stale snapshots remain editable and portable."""
    if (not isinstance(value, dict) or set(value) - {'version', 'instructions', 'source', 'prompts'}
            or value.get('version') != 1 or not isinstance(value.get('instructions'), str)):
        raise ValueError('Still prompt preparation needs version 1, instructions, source and prompts.')
    result = dict(version=1, instructions=value['instructions'], source=value.get('source'), prompts=value.get('prompts', []))
    _records(result['prompts'])
    if result['source'] is None and not result['prompts']:
        return copy.deepcopy(result)
    if not isinstance(result['source'], dict) or result['source'].get('version') != 1:
        raise ValueError('Still prompt preparation instructions and source are invalid.')
    boxes = result['source'].get('boxes')
    if not isinstance(boxes, list) or any(not isinstance(box, dict) or set(box) != set(BOX_FIELDS)
            or not isinstance(box['id'], str) or not isinstance(box['prompt'], str) for box in boxes):
        raise ValueError('Still prompt preparation source needs its semantic box snapshots.')
    ids = [box['id'] for box in boxes]
    if len(set(ids)) != len(ids):
        raise ValueError('Still prompt preparation source box IDs must be unique.')
    for item in result['prompts']:
        members = item['members']
        if any(member['box'] not in ids for member in members):
            raise ValueError('Still prompt members must belong to the saved source snapshot.')
        if len(members) > 1:
            at = ids.index(members[0]['box'])
            if (len(members) != 2 or members[0]['target'] != {'kind': 'last'} or members[1]['target'] != {'kind': 'first'}
                    or at + 1 >= len(boxes) or members[1]['box'] != ids[at + 1] or boxes[at + 1]['cut']):
                raise ValueError('Shared still prompt members must be one continuous source boundary.')
    return copy.deepcopy(result)


def parse(reply, prepared):
    data = story_prompts.reply_data(reply)
    if set(data) != {'prompts'}:
        raise ValueError('The model must return only the still prompt records.')
    records = _records(data['prompts'], generated=True)
    expected = {item['id']: item for item in prepared['prompts']}
    if set(item['id'] for item in records) != set(expected):
        raise ValueError('The model changed the requested still prompt IDs.')
    for item in records:
        original = expected[item['id']]
        if item['members'] != original['members']:
            raise ValueError('The model changed the requested still prompt members.')
        allowed = {slot for context in original['contexts'] for slot in context['references']}
        found = rules.mentions('\n'.join([item['prompt'], *item['components'].values()]))
        if any(kind != 'image' or slot not in allowed for kind, slot in found):
            raise ValueError('The model invented a reference outside this still target context.')
        item['issues'] = list(dict.fromkeys([*item['issues'], *(issue for context in original['contexts'] for issue in context['issues'])]))
    ordered = {item['id']: item for item in records}
    return dict(version=1, instructions=prepared['source']['instructions'], source=copy.deepcopy(prepared['source']),
                prompts=[ordered[key] for key in expected])


def response_format(prepared):
    text = {'type': 'string'}
    target = {'anyOf': [story_prompts._object({'kind': {'type': 'string', 'enum': ['first', 'last']}}),
                       story_prompts._object({'kind': {'type': 'string', 'enum': ['shot']}, 'shot': {'type': 'integer', 'minimum': 2}})]}
    row = story_prompts._object(dict(id={'type': 'string', 'enum': [item['id'] for item in prepared['prompts']]},
        members={'type': 'array', 'items': story_prompts._object(dict(box=text, target=target))}, prompt=text,
        components=story_prompts._object({key: text for key in COMPONENTS}), issues={'type': 'array', 'items': text}))
    return story_prompts._reply_format('h3_still_prompts', story_prompts._object({'prompts': {'type': 'array', 'items': row}}))


def read(body):
    snapshot = copy.deepcopy(body.get('prompt'))
    if not isinstance(snapshot, dict):
        raise ValueError('The still prompt request has no workflow snapshot.')
    story, _, _ = story_context.find_nodes(snapshot, body.get('story'))
    # Conversion consumes the finished Timeline, including imported/rendered stories; it never writes an idea.
    story['inputs'].update(idea='Prepare still prompts from the current Timeline.', guide='', template='',
                           idea_images='[]', vision_model='', vision_base_url='', story_thinking='same as boxes',
                           story_model='', story_base_url='')
    ctx = story_context.read(snapshot, body.get('story'), rewrite_all=True)
    settings = body['prompt'][ctx.timeline_id]['inputs']
    document = json.loads(settings['timeline'])
    instructions = body.get('instructions', (document.get('still_prompt_preparation') or {}).get('instructions', DEFAULT_INSTRUCTIONS))
    if not isinstance(instructions, str) or not instructions.strip():
        raise ValueError('Still prompt conversion instructions must be nonempty text.')
    source = body.get('source')
    references = source.get('references', []) if isinstance(source, dict) else []
    if not isinstance(references, list) or any(not isinstance(ref, dict) or set(ref) != {'name', 'file', 'description'}
            or not isinstance(ref['name'], str) or not isinstance(ref['description'], str)
            or ref['file'] is not None and not isinstance(ref['file'], dict) for ref in references):
        raise ValueError('Still prompt source references are invalid.')
    prepared = plan(document, instructions, ctx.context_frames, references)
    if source is not None and source != prepared['source']:
        raise ValueError('The Timeline or conversion instructions changed before still prompt preparation. Try again.')
    return ctx, prepared


def _descriptions(ctx, wanted):
    descriptions = dict(ctx.descriptions)
    replacements = reference_replacements.effective(ctx.timeline)
    for ref in ctx.references:
        if ref.name not in wanted or descriptions.get(ref.name):
            continue
        original = reference_replacements.origin(ref.name, replacements).get('source', ref.name)
        try:
            stamp = image_descriptions.checksum(ref.path) if ref.path else story_vision.source(ctx, dataclasses.replace(ref, name=original))
        except OSError:
            continue
        if not stamp:
            continue
        shared = image_descriptions.lookup(stamp)
        # A shared manual Clear is authoritative even when the Timeline retains older saved text.
        if shared is not None:
            descriptions[ref.name] = shared['text']
            continue
        for name in dict.fromkeys([ref.name, original]):
            saved = ctx.reference_descriptions.get(name)
            if not saved:
                continue
            source = saved.get('source', '')
            matches = source == stamp
            if not matches and source.startswith('['):
                try:
                    scene = json.loads(source)
                    matches = isinstance(scene, list) and len(scene) == 4 and scene[0] == 'idea-scene-v1' and scene[-1] == stamp
                except ValueError:
                    pass
            if matches:
                descriptions[ref.name] = saved['text']
                break
    return descriptions


async def convert(job, chat):
    prepared = job.still_plan
    job.report('Preparing still prompts...')
    contexts = copy.deepcopy(prepared['prompts'])
    wanted = {slot for record in contexts for context in record['contexts'] for slot in context['references']}
    described = await asyncio.to_thread(_descriptions, job.ctx, wanted)
    references = [dict(name=ref.name, description=described.get(ref.name, ''))
                  for ref in job.ctx.references if ref.name in wanted]
    pictures = [dict(label=ref.label, path=ref.path) for ref in job.ctx.references if ref.name in wanted and ref.path]
    system = DEFAULT_INSTRUCTIONS
    model_instructions = story_instructions.image_model_instructions(job.ctx.image_model)
    if model_instructions:
        system += '\n\n' + model_instructions
    messages = [dict(role='system', content=system),
                dict(role='user', content=json.dumps(dict(instructions=prepared['source']['instructions'],
                     references=references, targets=contexts), ensure_ascii=False), pictures=pictures)]
    reply = await chat.ask(messages, response_format(prepared))
    return parse(reply, prepared)
