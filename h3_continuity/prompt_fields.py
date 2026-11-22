"""Read an H3 prompt into the Sections form's fields, as web/h3c_prompt_sections.mjs and
web/h3c_prompt_fields.mjs do. Offsets are Python string indices (code points), not the browser's UTF-16 units.
tests/fixtures/prompt_field_cases.json holds the browser's results for both parsers to match."""
import json
import re

TITLES = {
    'subject_definitions': 'Subjects & references', 'summary': 'Summary', 'retention_analysis': 'Reference retention',
    'detailed_description': 'Shots', 'integrated_multimodal_description': 'Shots',
    'overall_soundscape': 'Soundscape', 'non_diegetic_music': 'Background music',
}
SHOTS = ('detailed_description', 'integrated_multimodal_description')


def _field(key, prefix, advanced=True, repeatable=False):
    return dict(key=key, prefix=prefix, advanced=advanced, repeatable=repeatable)


SHOT_FIELDS = [
    _field('style', 'Style', False), _field('composition', 'Composition', False), _field('initial_state', 'Initial state'),
    _field('trigger', 'Trigger'), _field('action', 'Action', False, True), _field('contact', 'Contact'), _field('reaction', 'Reaction'),
    _field('shot_size', 'Shot size'), _field('camera_position', 'Camera position'), _field('camera_movement', 'Camera movement', False),
    _field('camera_direction', 'Camera direction'), _field('camera_speed', 'Camera speed', False),
    _field('camera_amplitude', 'Camera amplitude', False), _field('camera_subject', 'Camera subject'), _field('focus', 'Focus'),
    _field('effect_trigger', 'Effect N trigger'), _field('effect', 'Effect N'), _field('effect_motion', 'Effect N motion'),
    _field('effect_response', 'Effect N response'), _field('physical_response', 'Physical response'), _field('lighting', 'Lighting'),
    _field('light_direction', 'Light direction'), _field('colour_contrast', 'Colour and contrast'), _field('reflections', 'Reflections'),
    _field('atmosphere', 'Atmosphere'), _field('materials', 'Materials'), _field('depth_of_field', 'Depth of field'), _field('gaze', 'Gaze'),
    _field('expression', 'Expression'), _field('breathing', 'Breathing'), _field('posture', 'Posture'), _field('hands', 'Hands'),
    _field('continuity', 'Continuity'), _field('recovery', 'Recovery'), _field('end_state', 'End state'),
    _field('dialogue', 'Dialogue', False, True), _field('scene_sound', 'Scene sound', False),
]
ADVANCED = {field['key'] for field in SHOT_FIELDS if field['advanced']}

# JavaScript's \d, \w and non-multiline $ differ from Python's; these patterns spell out the browser's meaning.
DIALOGUE = re.compile(r'<d>[\s\S]*?(?:</d>|\Z)')
REFERENCE = re.compile(r'(?:^[ \t]*|(?<=[.;])[ \t]+)(<(?:Subject|Picture|Audio|Video) [1-9][0-9]*>|@(?:image|audio|video_audio|video)[0-9]+(?![A-Za-z0-9_]))', re.M)
HEADER = re.compile(r'^[ \t]*(' + '|'.join(TITLES) + r'|[a-z]+_[a-z_]*|[a-z]+(?=:[ \t]*\r?$)):', re.M)
SHOT = re.compile(r'^[ \t]*(\[Shot [1-9][0-9]*\])(?=\s|$)', re.M)
LABEL = r'(?:<(?:Subject|Picture|Video|Audio) [1-9][0-9]*>|@(?:image|video_audio|video|audio)[1-9][0-9]*)'
DEFINITION = re.compile(r'(' + LABEL + r')\s+is\s+([\s\S]+)\Z')
SOURCE = re.compile(r'; (?:([^;\r\n]*?) )?reference: @((?:image|video_audio|video|audio)[0-9]+)\Z')
RETENTION = re.compile(r'(' + LABEL + r')\s*(?:\(([^)]*)\))?\s*:\s*([^\n]+?)(?:\s+-\s+([\s\S]*))?\Z')
CLOCK = re.compile(r'^At [0-9]+:[0-5][0-9]\.[0-9]{3},\s*', re.I)
SPEECH = re.compile(r'([\s\S]*?)\((S[1-9][0-9]*(?:,S[1-9][0-9]*)*)\)(?:,\s*([\s\S]*?),)?\s+(says in an off-screen voiceover|sings|says):\s*<d>\[([^\]\r\n]+)\] ?')
VOICEOVER = re.compile(r" while (?:the corresponding on-screen characters'|his|her|their|the character's) lips remain completely closed\.")
SPEAKER = re.compile(r'<Subject [1-9][0-9]*>(?: and <Subject [1-9][0-9]*>)* \(S[1-9][0-9]*(?:,S[1-9][0-9]*)*\)')
AUDIO_TAILS = (' The audio continues seamlessly across the cut.', ' The audio continues seamlessly.')


def _cue_pattern(field):
    pattern = field['prefix'].replace(' N', ' ([1-9][0-9]*)', 1)
    if field['repeatable']:
        pattern += '(?: ([1-9][0-9]*))?'
    return re.compile('^' + pattern + ':[ \t]*', re.M)


CUES = [(field, _cue_pattern(field)) for field in SHOT_FIELDS]


def without_dialogue(text):
    return DIALOGUE.sub(lambda match: ' ' * len(match.group(0)), text)


def _strip_end(text):
    return len(text.rstrip())


def sections(source):
    """The browser's promptSections: None unless a known section header is present."""
    dialogue = [match.span() for match in DIALOGUE.finditer(source)]

    def matches(pattern, start=0, end=None):
        end = len(source) if end is None else end
        found = ({'index': start + match.start(), 'text': match.group(0), 'label': match.group(1)}
                 for match in pattern.finditer(source[start:end]))
        return [item for item in found if not any(a <= item['index'] < b for a, b in dialogue)]

    headers = matches(HEADER)
    if not any(header['label'] in TITLES for header in headers):
        return None
    counts = {}
    for header in headers:
        counts[header['label']] = counts.get(header['label'], 0) + 1

    def field(start, end, label):
        body = source[start:end]
        if not body.strip():
            at = start + len(re.match(r'[ \t]*', body).group(0))
            return {'start': at, 'end': at, 'label': label, 'value': ''}
        leading = len(body) - len(body.lstrip())
        trailing = len(body) - len(body.rstrip())
        return {'start': start + leading, 'end': end - trailing, 'label': label, 'value': body.strip()}

    result = []
    if source[:headers[0]['index']].strip():
        result.append({'key': 'alignment', 'title': 'Frame alignment', 'fields': [field(0, headers[0]['index'], 'Frame alignment')]})
    for i, header in enumerate(headers):
        key = header['label'] if header['label'] in TITLES and counts[header['label']] == 1 else 'existing'
        start = header['index'] + len(header['text'])
        end = headers[i + 1]['index'] if i + 1 < len(headers) else len(source)
        if key == 'existing':
            result.append({'key': key, 'title': 'Existing text', 'fields': [field(header['index'], end, 'Existing text')]})
            continue
        shots = key in SHOTS
        refs = key in ('subject_definitions', 'retention_analysis')
        entries = matches(SHOT, start, end) if shots else matches(REFERENCE, start, end) if refs else []
        fields = []
        if entries:
            if source[start:entries[0]['index']].strip():
                fields.append(field(start, entries[0]['index'], 'Style & scene' if shots else 'Notes'))
            for j, entry in enumerate(entries):
                part = field(entry['index'] + len(entry['text']), entries[j + 1]['index'] if j + 1 < len(entries) else end, entry['label'])
                part['entryStart'] = entry['index'] + entry['text'].index(entry['label'])
                part['entryEnd'] = part['end']
                fields.append(part)
        else:
            fields.append(field(start, end, TITLES[key]))
        result.append({'key': key, 'title': TITLES[key], 'fields': fields, 'headerStart': header['index'], 'bodyStart': start, 'end': end})
    return result


def _span(source, start, end):
    return {'start': start, 'end': end, 'before': source[start:end]}


def _entry(source, part, kind, value, shot=None):
    start = part['entryStart'] if part.get('entryStart') is not None else part['start']
    end = part['entryEnd'] if part.get('entryEnd') is not None else part['end']
    return {'kind': kind, 'shot': shot, 'range': _span(source, start, end), 'value': value}


def _target(target, tags):
    if target.startswith('<Subject ') or target.startswith('@'):
        return target
    named = [tag for tag in tags if tag.get('tag') == target]
    return '@' + named[0]['name'] if len(named) == 1 else None


def _unindent(text):
    return ''.join(part if part.startswith('<d>') else re.sub(r'\r?\n {2}', '\n', part)
                   for part in re.split(r'(<d>[\s\S]*?(?:</d>|\Z))', text))


def _speech(text):
    lead = SPEECH.match(text)
    if not lead:
        return None
    close = text.find('</d>', lead.end())
    if close < 0:
        return None
    words, end = text[lead.end():close], close + 4
    from_previous, to_next, cutoff = words.startswith('<scenetrans>'), words.endswith('<scenetrans>'), words.endswith('<cutoff>')
    if from_previous:
        words = words[12:]
    if to_next:
        words = words[:-12]
    elif cutoff:
        words = words[:-8]
    voiceover = 'voiceover' in lead.group(4)
    if voiceover:
        tail = VOICEOVER.match(text, end)
        if not tail:
            return None
        end = tail.end()
    for tail in AUDIO_TAILS:
        if text.startswith(tail, end):
            end += len(tail)
            break
    return end, {'speakers': lead.group(2).split(','), 'identity': lead.group(1).strip(), 'language': lead.group(5), 'text': words,
                 'delivery': lead.group(3) or '', 'voiceover': voiceover, 'singing': lead.group(4) == 'sings',
                 'fromPrevious': from_previous, 'toNext': to_next, 'cutoff': cutoff, 'key': 'dialogue', 'index': None}


def _split_speech(source, entry):
    if entry['kind'] != 'narrative':
        return [entry]
    raw, entries, cursor = entry['range']['before'], [], 0
    base = entry['range']['start']
    for candidate in SPEAKER.finditer(without_dialogue(raw)):
        if candidate.start() < cursor:
            continue
        speech = _speech(raw[candidate.start():])
        if not speech:
            continue
        end = _strip_end(raw[:candidate.start()])
        if end > cursor:
            text = raw[cursor:end]
            entries.append({'kind': 'existing' if cursor else 'narrative', 'shot': entry['shot'], 'range': _span(source, base + cursor, base + end),
                            'value': {'text': text if cursor else CLOCK.sub('', re.sub(r'^\[Shot [0-9]+\]\s*', '', text, count=1), count=1)}})
        entries.append({'kind': 'dialogue', 'shot': entry['shot'],
                        'range': _span(source, base + candidate.start(), base + candidate.start() + speech[0]), 'value': speech[1]})
        cursor = candidate.start() + speech[0]
    if not cursor:
        return [entry]
    if raw[cursor:].strip():
        entries.append({'kind': 'existing', 'shot': entry['shot'], 'range': _span(source, base + cursor, entry['range']['end']),
                        'value': {'text': raw[cursor:]}})
    return entries


def _shot_fields(source, part, shot):
    masked, found = without_dialogue(source), []
    for field, pattern in CUES:
        for match in pattern.finditer(masked[part['start']:part['end']]):
            index = match.group(1) if pattern.groups else None
            found.append({'start': part['start'] + match.start(), 'body': part['start'] + match.end(), 'field': field,
                          'index': int(index) if index else None})
    found.sort(key=lambda item: item['start'])
    if not found:
        return _split_speech(source, _entry(source, part, 'narrative', {'text': CLOCK.sub('', part['value'], count=1)}, shot))
    start = part['entryStart'] if part.get('entryStart') is not None else part['start']
    end = _strip_end(source[:found[0]['start']])
    entries = [{'kind': 'narrative', 'shot': shot, 'range': _span(source, start, end),
                'value': {'text': CLOCK.sub('', source[part['start']:end], count=1)}}]
    for i, match in enumerate(found):
        end = _strip_end(source[:found[i + 1]['start'] if i + 1 < len(found) else part['end']])
        key = match['field']['key']
        duplicate = sum(other['field']['key'] == key and other['index'] == match['index'] for other in found) > 1
        body = _unindent(source[match['body']:end])
        speech = _speech(body) if key == 'dialogue' else None
        if duplicate or key == 'dialogue' and (not speech or speech[0] != len(body)):
            entries.append({'kind': 'existing', 'shot': shot, 'range': _span(source, match['start'], end), 'value': {'text': source[match['start']:end]}})
        elif speech:
            entries.append({'kind': 'dialogue', 'shot': shot, 'range': _span(source, match['start'], end), 'value': {**speech[1], 'index': match['index']}})
        else:
            entries.append({'kind': 'cue', 'shot': shot, 'range': _span(source, match['start'], end),
                            'value': {'key': key, 'index': match['index'], 'text': body}})
    return [item for entry in entries for item in _split_speech(source, entry)]


def read(source, tags=()):
    """The browser's readPromptFields: every part of the prompt as a typed entry with its source range."""
    tags = list(tags)
    parsed = sections(source)
    if not parsed:
        markers = list(re.finditer(r'^[ \t]*(\[Shot ([1-9][0-9]*)\])(?=\s|$)', without_dialogue(source), re.M))
        if not markers:
            whole = [{'kind': 'existing', 'shot': None, 'range': _span(source, 0, len(source)), 'value': {'text': source}}]
            return {'sections': [{'key': 'integrated_multimodal_description', 'entries': whole}] if source.strip() else []}
        fields = []
        if source[:markers[0].start()].strip():
            fields.append({'start': 0, 'end': markers[0].start(), 'value': source[:markers[0].start()], 'label': 'Existing text'})
        for i, marker in enumerate(markers):
            start = marker.end()
            body = start + len(re.match(r'\s*', source[start:]).group(0))
            end = _strip_end(source[:markers[i + 1].start() if i + 1 < len(markers) else len(source)])
            fields.append({'entryStart': marker.start(), 'entryEnd': end, 'start': body, 'end': end, 'label': marker.group(1), 'value': source[body:end]})
        parsed = [{'key': 'integrated_multimodal_description', 'fields': fields}]
    result = []
    for section in parsed:
        entries = []
        for part in section['fields']:
            start = part['entryStart'] if part.get('entryStart') is not None else part['start']
            raw = source[start:part['entryEnd'] if part.get('entryEnd') is not None else part['end']]
            definition = DEFINITION.match(raw)
            if section['key'] == 'subject_definitions' and definition:
                target = _target(definition.group(1), tags)
                if target:
                    description, sources = definition.group(2), []
                    while match := SOURCE.search(description):
                        sources.insert(0, {'slot': match.group(2), 'role': match.group(1) or ''})
                        description = description[:match.start()]
                    entries.append(_entry(source, part, 'definition', {'target': target, 'description': description, 'sources': sources}))
                    continue
            retention = RETENTION.match(raw)
            if section['key'] == 'retention_analysis' and retention:
                target = _target(retention.group(1), tags)
                scope = retention.group(2) or ''
                if target:
                    entries.append(_entry(source, part, 'retention', {
                        'target': target, 'shots': [int(n) for n in re.findall(r'\[Shot ([0-9]+)\]', scope)],
                        'scope': re.sub(r'\[Shot [0-9]+\](?:,\s*)?', '', re.sub(r'appears in\s*', '', scope, count=1)).strip(),
                        'relationship': retention.group(3), 'detail': retention.group(4) or ''}))
                    continue
            if section['key'] == 'summary':
                prefix = re.match(r'\[([^\]]*)\]\s*', part['value'])
                entries.append(_entry(source, part, 'summary', {'taskTypes': re.split(r'\s*\+\s*', prefix.group(1)) if prefix else [],
                                                                'text': part['value'][prefix.end():] if prefix else part['value']}))
                continue
            shot = re.match(r'\[Shot ([0-9]+)\]\Z', part['label'])
            entries.extend(_shot_fields(source, part, int(shot.group(1))) if shot else [_entry(source, part, 'existing', {'text': part['value']})])
        result.append({'key': section['key'], 'entries': entries})
    return {'sections': result}


def inspect(source, tags=()):
    """Fields without the duplicated source text, plus counts an agent can check before saving."""
    parsed = read(source, tags)
    entries = [entry for section in parsed['sections'] for entry in section['entries']]
    cues = [entry for entry in entries if entry['kind'] == 'cue']
    # Plain section bodies (alignment, scene style, soundscape) are ordinary fields; these are not.
    unstructured = [entry for section in parsed['sections'] for entry in section['entries']
                    if entry['kind'] == 'existing' and entry['value']['text'].strip()
                    and (entry['shot'] is not None or section['key'] in ('existing', 'subject_definitions', 'retention_analysis'))]
    return {
        'structured': sections(source) is not None,
        'sections': [{'key': section['key'], 'entries': [{'kind': entry['kind'], 'shot': entry['shot'], 'start': entry['range']['start'],
                                                          'end': entry['range']['end'], 'value': entry['value']} for entry in section['entries']]}
                     for section in parsed['sections']],
        'summary': {
            'shots': len({entry['shot'] for entry in entries if entry['shot'] is not None}),
            'cues': len(cues), 'advanced_cues': sum(entry['value']['key'] in ADVANCED for entry in cues),
            'dialogue': sum(entry['kind'] == 'dialogue' for entry in entries),
            'unstructured_text': len(unstructured),
        },
    }


def request(body):
    """{prompt, tags?} or a saved {timeline, box, layer?, tags?}; tags map <Picture N> labels to slots as the Studio does."""
    prompt = body.get('prompt')
    if prompt is None:
        try:
            line = json.loads(body['timeline'])
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise ValueError('Give a prompt, or a box of a saved Timeline.') from error
        clip = next((box for box in line.get('boxes') or [] if isinstance(box, dict) and box.get('id') == body.get('box')), None)
        if clip is not None and body.get('layer') is not None:
            clip = next((layer for layer in clip.get('layers') or [] if isinstance(layer, dict) and layer.get('id') == body['layer']), None)
        if clip is None:
            raise ValueError('Choose a box, and optionally one of its layers, from this Timeline.')
        prompt = clip.get('prompt') or ''
    tags = body.get('tags') or []
    if not isinstance(prompt, str) or not isinstance(tags, list) or any(not isinstance(tag, dict) for tag in tags):
        raise ValueError('The prompt must be text and tags a list of {tag, name} objects.')
    return inspect(prompt, tags)
