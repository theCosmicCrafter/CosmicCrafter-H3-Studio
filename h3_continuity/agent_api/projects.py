"""Saved native workflow access; execution uses captured graphs, never browser state."""
import copy
import hashlib
import json
import os
import posixpath
import tempfile
from pathlib import Path

import folder_paths

from .. import nodes, saved_state, story_library, store, takes, timeline
from ..timeline_api.contracts import APIError

SETTINGS = ('width', 'height', 'context_frames', 'carry_audio', 'ref_image_size', 'audio_context_frames')
PRIMITIVES = {'PrimitiveString', 'PrimitiveStringMultiline', 'PrimitiveInt', 'PrimitiveFloat', 'PrimitiveBoolean'}


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def _target(target):
    if (not isinstance(target, dict) or target.get('kind') != 'native'
            or not isinstance(target.get('graph'), str) or not 1 <= len(target['graph']) <= 256
            or not isinstance(target.get('timeline_node'), str) or not target['timeline_node']):
        raise APIError('invalid_target', 'Choose an explicit saved native graph and Timeline node.')
    return {key: target[key] for key in ('kind', 'graph', 'timeline_node', 'story_node') if key in target}


def _path(graph):
    return Path(folder_paths.get_system_user_directory('h3c_agent')) / 'projects' / (hashlib.sha256(graph.encode()).hexdigest() + '.json')


def _stored(graph):
    try:
        return json.loads(_path(graph).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {}


def _write(graph, value):
    path = _path(graph)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(_json(value)); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _widgets(ui):
    return {f"{node['id']}/{node['type']}/{name}": (node, index, name)
            for node, index, name in story_library._widgets(ui)}


def _effective_controls(ui):
    """Read supported connected UI scalars without executing or compiling a graph."""
    ui = copy.deepcopy(ui)
    for node, index, name in story_library._widgets(ui):
        ports = [port for port in node.get('inputs', []) if port.get('widget')]
        pointer = ports[index].get('link')
        if pointer is None:
            continue
        links = [row for row in ui['links'] if isinstance(row, list) and len(row) == 6 and row[0] == pointer]
        if len(links) != 1 or links[0][2] != 0:
            continue
        sources = [source for source in ui['nodes'] if str(source['id']) == str(links[0][1]) and source.get('type') in PRIMITIVES]
        if len(sources) != 1 or not sources[0].get('widgets_values'):
            continue
        source = sources[0]
        controls = [port for port in source.get('inputs', []) if port.get('widget')]
        selected = next((i for i, port in enumerate(controls) if port['widget']['name'] == 'value'), 0)
        node['widgets_values'][index] = source['widgets_values'][selected]
        if 'widgets_values_named' in node:
            node['widgets_values_named'][name] = node['widgets_values'][index]
    return ui


def _guard(target, ui):
    if (not isinstance(ui, dict) or not isinstance(ui.get('nodes'), list) or not isinstance(ui.get('links'), list)
            or (ui.get('extra', {}).get('h3c_story_id') or ui.get('id')) != target['graph']):
        raise APIError('invalid_workflow', 'Workflow and native graph identity must match.')
    matches = [n for n in ui['nodes'] if str(n.get('id')) == target['timeline_node'] and n.get('type') == 'H3C_Timeline']
    if len(matches) != 1:
        raise APIError('invalid_target', 'Timeline node is missing or ambiguous in this saved workflow.')
    if matches[0].get('properties', {}).get('h3c_project', {}).get('mode') == 'attached':
        raise APIError('managed_target', 'Use the managed project API for this attached workflow.', status=409)
    if 'story_node' in target and not any(str(n.get('id')) == target['story_node'] and n.get('type') == 'H3C_Story' for n in ui['nodes']):
        raise APIError('invalid_target', 'Story node is missing from this saved workflow.')
    fields = story_library._fields(ui)
    name = fields.get((target['timeline_node'], 'name'), '')
    if isinstance(name, str) and name.startswith('api_'):
        raise APIError('managed_target', 'Managed sequence names cannot use native project operations.', status=409)
    return store.validate_name(name) if name else None


def _current(target):
    target = _target(target)
    graph = target['graph']
    if saved_state.deleted(graph):
        raise APIError('project_deleted', 'This saved story was permanently deleted.', status=404)
    record = _stored(graph)
    library = saved_state.read('library', graph, 'library')['value'] or {}
    ui = library.get('workflow') or record.get('workflow_ui')
    if ui is None:
        raise APIError('project_not_found', 'Native project is not saved or registered.', status=404)
    state = saved_state.read('workflow', graph, 'workflow')
    ui = copy.deepcopy(ui) if library.get('checkpoint_name') else story_library._overlay(ui, state.get('value') or {})
    ui = _effective_controls(ui)
    _guard(target, ui)
    revision = dict(state=state['revision'], workflow=library.get('workflow_revision', record.get('workflow_revision', 0)),
                    execution=record.get('revision', 0))
    return target, record, library, ui, state, revision


def _check_revision(expected, actual):
    if (not isinstance(expected, dict) or expected != actual
            or any(type(number) is not int for number in expected.values())):
        raise APIError('revision_conflict', 'Saved native project revision changed; reread before retrying.',
                       status=409, details={'current_revision': actual})


def _binding(api, identity, name):
    seen = set()
    while True:
        if (identity, name) in seen:
            raise ValueError('Cyclic primitive binding')
        seen.add((identity, name))
        node = api.get(identity, {})
        if name not in node.get('inputs', {}):
            raise ValueError('Captured input is missing')
        value = node['inputs'][name]
        if not (isinstance(value, list) and len(value) == 2):
            return identity, name
        identity = str(value[0])
        if value[1] != 0 or api.get(identity, {}).get('class_type') not in PRIMITIVES:
            raise ValueError('Computed input needs a fresh execution snapshot')
        name = 'value'


def _execution(record, ui):
    if not record.get('workflow_api'):
        return None, 'This saved workflow needs an execution snapshot; save it in Studio or register an API export.'
    if record.get('execution_error'):
        return None, record['execution_error']
    if story_library._wiring(ui) != story_library._wiring(record['workflow_ui']):
        return None, 'Workflow wiring changed; capture a fresh execution snapshot.'
    if ui.get('definitions', {}).get('subgraphs'):
        return None, 'Subgraphs require an explicitly supported execution snapshot; use root-level H3 nodes.'
    api = copy.deepcopy(record['workflow_api'])
    before = _widgets(record['workflow_ui'])
    try:
        for key, (node, index, name) in _widgets(ui).items():
            if key not in before:
                raise ValueError('Widget bindings changed')
            old_node, old_index, _ = before[key]
            value = node['widgets_values'][index]
            if value == old_node['widgets_values'][old_index]:
                continue
            identity, port = _binding(api, str(node['id']), name)
            api[identity]['inputs'][port] = value
    except (ValueError, KeyError, TypeError) as error:
        return None, f'Execution snapshot needs recapture: {error}'
    return api, None


def _document(target, ui, record):
    fields = story_library._fields(ui)
    identity = target['timeline_node']
    line = fields.get((identity, 'timeline'), {})
    settings = {name: fields[(identity, name)] for name in SETTINGS if (identity, name) in fields}
    extras = {key: node['widgets_values'][index] for key, (node, index, name) in _widgets(ui).items()
              if not (str(node['id']) == identity and (name == 'timeline' or name in SETTINGS))
              and not (str(node['id']) == target.get('story_node') and name == 'state')}
    result = {**record.get('document_extra', {}), 'timeline': line, 'settings': settings, 'extra_widgets': extras}
    if target.get('story_node'):
        result['story'] = fields.get((target['story_node'], 'state'), {})
    return result


def unsupported_features(line):
    requires = line.get('requires') if isinstance(line, dict) else None
    return [item for item in requires if item not in timeline.REQUIRES] if isinstance(requires, list) else []


def read(target):
    with saved_state.LOCK:
        target, record, library, ui, _, revision = _current(target)
        api, reason = _execution(record, ui)
        document = _document(target, ui, record)
        return dict(target=target, revision=revision, document_json=_json(document),
                    execution_ready=api is not None, execution_error=reason, checkpoint=bool(library.get('checkpoint_name')),
                    unsupported_features=unsupported_features(document['timeline']),
                    capabilities={'saved_edit': not bool(library.get('checkpoint_name')), 'execution': api is not None})


def _capture(target, ui, api, record, *, persist=True):
    ui = _effective_controls(ui)
    _guard(target, ui)
    if api is not None:
        if (not isinstance(api, dict) or api.get(target['timeline_node'], {}).get('class_type') != 'H3C_Timeline'
                or any(not isinstance(n, dict) or not isinstance(n.get('inputs'), dict) or not isinstance(n.get('class_type'), str) for n in api.values())):
            raise APIError('invalid_snapshot', 'API snapshot does not match the selected native Timeline.')
        for _, (node, index, name) in _widgets(ui).items():
            if name not in api.get(str(node['id']), {}).get('inputs', {}):
                continue
            from ..timeline_prepare import ui_connections
            try:
                ui_connections(ui, node, api, [name])
            except ValueError as error:
                raise APIError('invalid_snapshot', f'Captured API/UI connection differs: {error}') from error
            try:
                identity, port = _binding(api, str(node['id']), name)
            except ValueError:
                continue  # Computed inputs are recaptured rather than rebound when edited.
            if _json(api[identity]['inputs'][port]) != _json(node['widgets_values'][index]):
                raise APIError('invalid_snapshot', f'Captured API input does not match saved widget {node["id"]}/{name}.')
    value = {**record, 'target': target, 'workflow_ui': copy.deepcopy(ui), 'workflow_api': copy.deepcopy(api),
             'revision': record.get('revision', 0) + 1}
    value.pop('execution_error', None)
    if persist:
        _write(target['graph'], value)
    return value


def capture(graph, story, ui, api):
    """Save-time capture: the accepted library write already owns the state lock."""
    candidates = [str(n['id']) for n in ui['nodes'] if n.get('type') == 'H3C_Timeline']
    if len(candidates) != 1:
        return
    target = dict(kind='native', graph=graph, timeline_node=candidates[0], story_node=str(story))
    try:
        _capture(target, ui, api, _stored(graph))
    except APIError:
        # Ordinary browser saves remain valid even when their graph cannot be captured.
        return


def register(target, workflow_ui, workflow_api, expected_revision=None):
    target = _target(target)
    with nodes.SEQUENCE_LOCK, saved_state.LOCK:
        name = _guard(target, workflow_ui)
        if name and takes.busy(os.path.join(nodes.sequences_root(), name)):
            raise APIError('project_busy', 'Native sequence is busy; finish rendering before replacing its snapshot.', status=409)
        existing = _stored(target['graph'])
        library = saved_state.read('library', target['graph'], 'library')['value']
        if existing or library:
            current = read(target)
            _check_revision(expected_revision, current['revision'])
            if current['checkpoint']:
                raise APIError('checkpoint_immutable', 'Open an editable checkpoint copy first.', status=409)
        value = _capture(target, workflow_ui, workflow_api, existing, persist=False)
        workflow_ui = value['workflow_ui']
        value['workflow_revision'] = existing.get('workflow_revision', 0) + 1
        # Explicit recapture replaces the authoritative library and its old widget overlay too.
        if target.get('story_node'):
            story_library.save(target['graph'], target['story_node'], workflow_ui, name,
                               library_revision=library.get('workflow_revision') if library else None)
        state = saved_state.read('workflow', target['graph'], 'workflow')
        fields = {key: node['widgets_values'][index] for key, (node, index, _) in _widgets(workflow_ui).items()}
        saved_state.write('workflow', target['graph'], 'workflow', fields, state['revision'])
        _write(target['graph'], value)
        return read(target)


def _sync_controls(record, ui, api):
    """Persist editable Primitive sources as well as their connected H3 widgets."""
    before = record.get('workflow_api') or {}
    widgets = _widgets(ui)
    changed = {}
    owned = {(str(node['id']), name): node['widgets_values'][index] for node, index, name in widgets.values()}
    for (identity, name), value in owned.items():
        try:
            source, port = _binding(api, identity, name)
        except ValueError:
            continue
        if source == identity or api[source]['inputs'][port] == before.get(source, {}).get('inputs', {}).get(port):
            continue
        changed[(source, port)] = api[source]['inputs'][port]
    for (source, port), value in changed.items():
        for identity, node in api.items():
            for name in node.get('inputs', {}):
                try:
                    binding = _binding(api, identity, name)
                except ValueError:
                    continue
                if binding != (source, port) or identity == source:
                    continue
                if (identity, name) not in owned or owned[(identity, name)] != value:
                    raise APIError('shared_control', 'A shared Primitive would change another consumer; edit all bound controls consistently or recapture separate controls.')
        matches = [node for node in ui['nodes'] if str(node['id']) == source and node.get('type') in PRIMITIVES]
        if len(matches) != 1 or not isinstance(matches[0].get('widgets_values'), list) or not matches[0]['widgets_values']:
            raise APIError('execution_snapshot_required', 'The linked Primitive needs its matching editable UI control.')
        node = matches[0]
        ports = [p for p in node.get('inputs', []) if p.get('widget')]
        index = next((i for i, p in enumerate(ports) if p['widget']['name'] == port), 0)
        node['widgets_values'][index] = value
        if 'widgets_values_named' in node:
            node['widgets_values_named'][port] = value


def save(target, expected_revision, document):
    with nodes.SEQUENCE_LOCK, saved_state.LOCK:
        target, record, library, ui, state, revision = _current(target)
        _check_revision(expected_revision, revision)
        if library.get('checkpoint_name'):
            raise APIError('checkpoint_immutable', 'Open an editable checkpoint copy first.', status=409)
        name = _guard(target, ui)
        if name and takes.busy(os.path.join(nodes.sequences_root(), name)):
            raise APIError('project_busy', 'Native sequence is busy; finish rendering before saving.', status=409)
        _json(document)
        if not isinstance(document, dict) or not isinstance(document.get('timeline'), dict):
            raise APIError('invalid_document', 'Provide the complete authored native document.')
        timeline.parse(_json(document['timeline']))
        changes = dict(document.get('extra_widgets') or {})
        widgets = _widgets(ui)
        for key, (_, _, field) in widgets.items():
            identity = key.split('/', 1)[0]
            if identity == target['timeline_node']:
                if field == 'timeline':
                    changes[key] = _json(document['timeline'])
                elif field in SETTINGS and field in document.get('settings', {}):
                    changes[key] = document['settings'][field]
            if identity == target.get('story_node') and field == 'state' and 'story' in document:
                changes[key] = _json(document['story'])
        if any(key not in widgets or not isinstance(value, (str, int, float, bool, type(None))) for key, value in changes.items()):
            raise APIError('invalid_document', 'Native document widget bindings must remain valid scalar values.')
        updated = story_library._overlay(ui, changes)
        _guard(target, updated)
        api, reason = _execution(record, updated)
        if api is not None:
            _sync_controls(record, updated, api)
        new_state = saved_state.write('workflow', target['graph'], 'workflow', {**(state['value'] or {}), **changes}, state['revision'])
        if library:
            reply = story_library.save(target['graph'], library['story'], updated,
                                       _guard(target, updated), new_state['revision'], revision['workflow'])
            workflow_revision = reply['revision']
        else:
            workflow_revision = revision['workflow'] + 1
        value = {**record, 'target': target, 'workflow_ui': updated, 'workflow_api': api,
                 'revision': revision['execution'] + 1, 'workflow_revision': workflow_revision,
                 'document_extra': {key: value for key, value in document.items() if key not in ('timeline', 'settings', 'story', 'extra_widgets')}}
        if reason:
            value['execution_error'] = reason
        _write(target['graph'], value)
        return read(target)


def context(target, expected_revision, operation):
    with nodes.SEQUENCE_LOCK, saved_state.LOCK:
        target, record, _, ui, _, revision = _current(target)
        _check_revision(expected_revision, revision)
        if operation == 'saved':
            document = _document(target, ui, record)
            return dict(target=target, revision=revision, name=_guard(target, ui), timeline=document['timeline'],
                        settings=document['settings'], graph=target['graph'], story=target.get('story_node'),
                        timeline_node=target['timeline_node'], workflow={'ui': ui},
                        fields={f'{node}/{key}': value for (node, key), value in story_library._fields(ui).items()})
        api, reason = _execution(record, ui)
        if api is None:
            raise APIError('execution_snapshot_required', reason, status=409)
        document = _document(target, ui, record)
        outputs = []
        def depends(identity, seen=None):
            seen = set() if seen is None else seen
            if identity == target['timeline_node']:
                return True
            if identity in seen:
                return False
            seen.add(identity)
            return any(depends(str(v[0]), seen) for v in api.get(identity, {}).get('inputs', {}).values()
                       if isinstance(v, list) and len(v) == 2)
        for identity, node in api.items():
            if node['class_type'] == 'H3C_SaveSegment' and depends(identity):
                outputs.append(identity)
        if operation in ('video', 'video_plan') and len(outputs) != 1:
            raise APIError('execution_snapshot_required', 'Video snapshot needs one unambiguous native Save Segment output.', status=409)
        fields = story_library._fields(ui)
        result = dict(target=target, revision=revision, name=_guard(target, ui), timeline=document['timeline'],
                    settings=document['settings'], graph=target['graph'], story=target.get('story_node'),
                    timeline_node=target['timeline_node'], workflow={'ui': ui, 'api': api, 'timeline_node': target['timeline_node']},
                    prompt=api, outputs=outputs, fields={f'{node}/{key}': value for (node, key), value in fields.items()})
        if operation == 'video_plan':
            from ..timeline_node import request_status
            result['assets'] = _text_audio_assets(document['timeline'], api, target['timeline_node'])
            result['native_status'] = request_status(dict(name=result['name'], timeline=json.dumps(document['timeline']),
                                                          settings=document['settings']), materialize=False)
        return result


def _text_audio_assets(line, api, timeline_node):
    """Pin the actual saved timed-text audio source using preparation's existing byte verifier."""
    from .. import timeline_prepare
    attachment = line.get('timed_text') or {}
    if 'audio_sha256' not in attachment:
        return []
    slot = attachment['audio_slot']
    clip = next((clip for clip in line.get('audio_clips', []) if clip['slot'] == slot), {})
    if clip.get('file'):
        file = copy.deepcopy(clip['file'])
        binding = dict(kind='audio_clip', slot=slot)
    else:
        link = api[timeline_node]['inputs'].get('audios.' + slot)
        source = api.get(str(link[0]), {}) if isinstance(link, list) and len(link) == 2 and link[1] == 0 else {}
        name = source.get('inputs', {}).get('audio')
        if source.get('class_type') != 'LoadAudio' or not isinstance(name, str):
            raise APIError('unverified_audio_source', 'Timed text needs a file-backed audio clip or direct literal LoadAudio source for byte verification.', status=422)
        kind = 'input'
        for candidate in ('input', 'output', 'temp'):
            if name.endswith('[' + candidate + ']'):
                kind, name = candidate, name[:-(len(candidate) + 2)].rstrip()
                break
        subfolder, filename = posixpath.split(name.replace('\\', '/'))
        file = dict(filename=filename, subfolder=subfolder, type=kind)
        binding = dict(kind='loader', node=str(link[0]), input='audio', slot=slot)
    try:
        path = timeline_prepare.descriptor(file, 'timeline.timed_text.audio_sha256')
        with open(path, 'rb') as stream:
            checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
    except (ValueError, OSError) as error:
        raise APIError('unverified_audio_source', str(error), status=422) from error
    return [dict(file=file, sha256=checksum, bindings=[binding])]


def list_projects(cursor=None, limit=50):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise APIError('invalid_request', 'Native page size must be 1..100.')
    offset = int(cursor or 0)
    if offset < 0:
        raise APIError('invalid_request', 'Invalid native project cursor.')
    targets, details = {}, {}
    root = _path('catalog').parent
    for path in root.glob('*.json'):
        record = json.loads(path.read_text(encoding='utf-8'))
        target = record['target']
        targets[(target['graph'], target['timeline_node'])] = target
    for row in story_library.listing():
        library = story_library.load(row['id'])
        details[library['graph']] = {'library_id': row['id'], 'title': row.get('title') or '', 'sequence': row.get('sequence') or '',
                                     **({'checkpoint_name': row['checkpoint_name']} if row.get('checkpoint_name') else {})}
        for node in library['workflow']['nodes']:
            if node.get('type') == 'H3C_Timeline':
                target = dict(kind='native', graph=library['graph'], timeline_node=str(node['id']), story_node=library['story'])
                targets[(target['graph'], str(node['id']))] = target
    rows = []
    for target in targets.values():
        if saved_state.deleted(target['graph']):
            continue
        try:
            view = read(target)
            rows.append(dict(target=target, revision=view['revision'], execution_ready=view['execution_ready'], checkpoint=view['checkpoint'],
                             **details.get(target['graph'], {})))
        except APIError as error:
            if error.code != 'managed_target':
                raise
    rows.sort(key=lambda item: (item['target']['graph'], item['target']['timeline_node']))
    return dict(projects=rows[offset:offset + limit], next_cursor=str(offset + limit) if len(rows) > offset + limit else None)
