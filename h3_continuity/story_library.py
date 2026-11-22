"""Generated Story workflows shared by every browser of this ComfyUI server."""

import copy
import json
import os
import re
import shutil
import time
from pathlib import Path

import folder_paths
from PIL import Image

from . import nodes, saved_state, stills, store


class WorkflowWiringConflict(ValueError):
    """A stale workflow must be opened or forked, never overwrite its saved copy."""

    code = 'h3c_story_wiring_conflict'

    def __init__(self, library_revision):
        super().__init__('Workflow wiring changed in another browser. Open the saved story before editing it here.')
        self.library_revision = library_revision


def _read_file(path):
    with open(path, encoding='utf-8-sig') as stream:
        return json.load(stream)


def save_checkpoint(graph, story, workflow, sequence, name):
    from .story_checkpoints import save
    return save(graph, story, workflow, sequence, name)


def duplicate(graph, story, workflow, sequence, title=None, timeline_text=None):
    from .story_checkpoints import duplicate
    return duplicate(graph, story, workflow, sequence, title, timeline_text)


def restore_checkpoint(identity):
    from .story_checkpoints import restore
    return restore(identity)


def _entry_path(identity):
    if not isinstance(identity, str) or not re.fullmatch('[a-f0-9]{64}', identity):
        raise ValueError('Choose a saved story.')
    return os.path.join(folder_paths.get_system_user_directory('h3c_state'), identity + '.json')


def _widgets(workflow):
    for node in workflow['nodes']:
        if node.get('type') not in ('H3C_Story', 'H3C_Timeline'):
            continue
        ports = [port for port in node.get('inputs', []) if port.get('widget')]
        values = node.get('widgets_values', [])
        for index, port in enumerate(ports):
            if index < len(values):
                yield node, index, port['widget']['name']


def _overlay(workflow, fields):
    value = copy.deepcopy(workflow)
    for node, index, name in _widgets(value):
        key = f"{node['id']}/{node['type']}/{name}"
        if key in fields:
            node['widgets_values'][index] = fields[key]
            if 'widgets_values_named' in node:
                node['widgets_values_named'][name] = fields[key]
    return value


def _fields(workflow):
    result = {}
    for node, index, name in _widgets(workflow):
        value = node['widgets_values'][index]
        if name in ('state', 'timeline'):
            value = json.loads(value or '{}')
        result[(str(node['id']), name)] = value
    return result


def _wiring(workflow):
    value = copy.deepcopy(workflow)
    value.pop('id', None)
    value.get('extra', {}).pop('h3c_story_id', None)
    graphs = [value]
    while graphs:
        graph = graphs.pop()
        graphs.extend(graph.get('definitions', {}).get('subgraphs', []))
        graph.get('extra', {}).pop('ds', None)
        if not graph.get('extra'):
            graph.pop('extra', None)
        for node in graph.get('nodes', []):
            for key in ('pos', 'size', 'showAdvanced'):
                node.pop(key, None)
            if graph is value and node.get('type') in ('H3C_Story', 'H3C_Timeline'):
                node.pop('widgets_values', None)
                node.pop('widgets_values_named', None)
            node.get('properties', {}).pop('h3c_library_revision', None)
            if not node.get('properties'):
                node.pop('properties', None)
        for port in graph.get('inputs', []) + graph.get('outputs', []):
            port.pop('pos', None)
        for group in graph.get('groups', []):
            group.pop('bounding', None)
        for key in ('inputNode', 'outputNode'):
            graph.get(key, {}).pop('bounding', None)
    return value


def save(graph, story, workflow, sequence, revision=None, library_revision=None, execution=None):
    if (not isinstance(workflow, dict) or (workflow.get('extra', {}).get('h3c_story_id') or workflow.get('id')) != graph
            or not isinstance(workflow.get('nodes'), list) or not isinstance(workflow.get('links'), list)
            or not any(node.get('type') == 'H3C_Story' and str(node.get('id')) == str(story) for node in workflow['nodes'])
            or not any(node.get('type') == 'H3C_Timeline' for node in workflow['nodes'])):
        raise ValueError('The story needs its original Story and Timeline workflow.')
    store.validate_name(sequence)
    with saved_state.LOCK:
        if revision is not None and saved_state.read('workflow', graph, 'workflow')['revision'] != revision:
            raise ValueError('This story changed in another browser. Refresh saved edits before switching.')
        current = saved_state.read('library', graph, 'library')['value'] or {}
        if current.get('checkpoint_name'):
            raise ValueError('A saved checkpoint cannot be overwritten. Open an editable copy first.')
        previous = current.get('workflow_revision', 0)
        if current and library_revision != previous and _wiring(current['workflow']) != _wiring(workflow):
            raise WorkflowWiringConflict(previous)
        value = {**current, 'format': 'h3-library', 'graph': graph, 'story': str(story),
                 'workflow': copy.deepcopy(workflow), 'sequence': sequence, 'updated': time.time(), 'workflow_revision': previous + 1}
        value['workflow'].setdefault('extra', {})['h3c_story_id'] = graph
        for node in value['workflow']['nodes']:
            if node.get('type') == 'H3C_Story' and str(node['id']) == value['story']:
                node.setdefault('properties', {})['h3c_library_revision'] = value['workflow_revision']
        saved_state.write('library', graph, 'library', value)
        if execution is not None:
            from .agent_api import projects
            projects.capture(graph, story, value['workflow'], execution)
        return {'id': Path(saved_state.path('library', graph, 'library')).stem, 'revision': value['workflow_revision']}


def checkpoint(graph, story, timeline, job, view):
    with saved_state.LOCK:
        if saved_state.deleted(graph):
            return
        value = saved_state.read('library', graph, 'library')['value']
        if value is None or value.get('checkpoint_name') or value['story'] != str(story):
            return
        value.update(job={'job': job, 'timeline': timeline, 'view': copy.deepcopy(view)}, updated=time.time())
        saved_state.write('library', graph, 'library', value)


def load(identity, deleting=False):
    with saved_state.LOCK:
        value = _read_file(_entry_path(identity)).get('value')
        if not isinstance(value, dict) or value.get('format') != 'h3-library' or saved_state.deleted(value['graph']) and not deleting:
            raise ValueError('This saved story is no longer available.')
        if not value.get('checkpoint_name'):
            saved = saved_state.read('workflow', value['graph'], 'workflow')
            value['workflow'] = _overlay(value['workflow'], saved.get('value') or {})
        for node in value['workflow']['nodes']:
            if node.get('type') == 'H3C_Story' and str(node['id']) == value['story']:
                node.setdefault('properties', {})['h3c_library_revision'] = value.get('workflow_revision', 0)
        value['id'] = identity
        return value


def _legacy():
    # Old hashed autosaves have no graph identity. Match them to native saved workflows without changing those files.
    user = Path(folder_paths.get_user_directory())
    for path in user.glob('*/workflows/**/*.json'):
        try:
            workflow = _read_file(path)
            graph = workflow.get('extra', {}).get('h3c_story_id') or workflow.get('id')
            if not graph or saved_state.deleted(graph) or saved_state.read('library', graph, 'library')['value']:
                continue
            saved = saved_state.read('workflow', graph, 'workflow')['value']
            if not saved:
                continue
            workflow = _overlay(workflow, saved)
            fields = _fields(workflow)
            jobs = {str(node['id']): saved_state.read('job', graph, str(node['id']))['value']
                    for node in workflow['nodes'] if node.get('type') == 'H3C_Story'}
            story = next((node for node in workflow['nodes'] if node.get('type') == 'H3C_Story'
                          and (fields.get((str(node['id']), 'state'), {}).get('title')
                               or (jobs[str(node['id'])] or {}).get('view', {}).get('result', {}).get('title'))), None)
            if story is None:
                continue
            state = fields.get((str(story['id']), 'state'), {})
            timeline = state.get('timeline') or next((str(node['id']) for node in workflow['nodes'] if node.get('type') == 'H3C_Timeline'), None)
            sequence = fields.get((timeline, 'name'))
            if not sequence:
                continue
            save(graph, str(story['id']), workflow, sequence)
            job = jobs[str(story['id'])]
            if job:
                checkpoint(graph, str(story['id']), job['timeline'], job['job'], job['view'])
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue


def _rendered(sequence, counts):
    """How many saved segments with a video sequence folder `sequence` holds (cached per listing); None when unknown."""
    if sequence not in counts:
        try:
            manifest = store.load_manifest(store.sequence_dir(nodes.sequences_root(), sequence))
            counts[sequence] = sum(1 for entry in manifest.get('segments', []) if entry.get('video'))
        except (OSError, ValueError, TypeError, AttributeError):
            counts[sequence] = None
    return counts[sequence]


def listing():
    with saved_state.LOCK:
        _legacy()
        rows, counts = [], {}
        for path in Path(folder_paths.get_system_user_directory('h3c_state')).glob('*.json'):
            try:
                raw = _read_file(path).get('value')
                if not isinstance(raw, dict) or raw.get('format') != 'h3-library':
                    continue
                value = load(path.stem, deleting=True)
                fields = _fields(value['workflow'])
                state = fields.get((value['story'], 'state'), {})
                view = value.get('job', {}).get('view', {})
                result = view.get('result') or {}
                line = fields.get((state.get('timeline'), 'timeline'), {})
                rows.append({'id': path.stem, 'graph': value['graph'], 'title': state.get('title') or result.get('title') or 'Untitled story',
                             'updated': value['updated'], 'boxes': len(line.get('boxes') or result.get('boxes') or result.get('outline') or []),
                             'status': 'Deletion incomplete — retry' if saved_state.deleted(value['graph']) else view.get('state', 'saved'), 'sequence': value['sequence'], 'revision': value.get('workflow_revision', 0),
                             'rendered': _rendered(value['sequence'], counts),
                             **({'checkpoint_name': value['checkpoint_name']} if value.get('checkpoint_name') else {})})
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                continue
        return sorted(rows, key=lambda row: row['updated'], reverse=True)


def _previews(value):
    if isinstance(value, str):
        match = re.fullmatch(r'h3_previews/(import_[a-f0-9]{64}|still_[a-f0-9-]+_\d+_)\.png \[output\]', value)
        if match:
            yield match.group(1) + '.png'
        try:
            value = json.loads(value)
        except ValueError:
            return
    if isinstance(value, dict):
        if value.get('type') == 'output' and value.get('subfolder') == 'h3_previews':
            filename = value.get('filename', '')
            if re.fullmatch(r'(?:[a-f0-9]{64}|import_[a-f0-9]{64}|still_[a-f0-9-]+_\d+_)\.png', filename):
                yield filename
        for child in value.values():
            yield from _previews(child)
    elif isinstance(value, list):
        for child in value:
            yield from _previews(child)


def _owned_previews(value):
    if isinstance(value, str):
        try: value = json.loads(value)
        except ValueError: return
    if isinstance(value, dict):
        if value.get('prompt_id') and value.get('request_id'):
            yield from _previews(value.get('images', []))
            if value.get('file'):
                yield from _previews(value['file'])
        for child in value.values():
            yield from _owned_previews(child)
    elif isinstance(value, list):
        for child in value:
            yield from _owned_previews(child)


def _receipt_ids(value):
    if isinstance(value, str):
        try: value = json.loads(value)
        except ValueError: return
    if isinstance(value, dict):
        if isinstance(value.get('prompt_id'), str) and isinstance(value.get('request_id'), str):
            yield value['prompt_id'], value['request_id']
        for child in value.values():
            yield from _receipt_ids(child)
    elif isinstance(value, list):
        for child in value:
            yield from _receipt_ids(child)


def _raw_previews(value):
    receipts = set(_receipt_ids(value))
    if not receipts:
        return
    root = Path(folder_paths.get_output_directory()) / 'h3_previews'
    for path in root.glob('still_*.png'):
        try:
            with Image.open(path) as image:
                receipt = json.loads(image.info.get('h3c_still', '{}'))
            if (receipt.get('prompt_id'), receipt.get('request_id')) in receipts:
                yield path.name
        except (OSError, ValueError, AttributeError):
            continue


def _native_usage(excluded_graph):
    sequences, previews = set(), set()
    for path in Path(folder_paths.get_user_directory()).glob('*/workflows/**/*.json'):
        try:
            workflow = _read_file(path)
        except (OSError, ValueError):
            raise ValueError(f'Could not verify shared media in {path.name}; restore that workflow before permanent deletion.') from None
        if not isinstance(workflow, dict) or (workflow.get('extra', {}).get('h3c_story_id') or workflow.get('id')) == excluded_graph or not isinstance(workflow.get('nodes'), list):
            continue
        graph = workflow.get('extra', {}).get('h3c_story_id') or workflow.get('id')
        if graph:
            workflow = _overlay(workflow, saved_state.read('workflow', graph, 'workflow').get('value') or {})
        previews.update(_previews(workflow))
        for (node, name), value in _fields(workflow).items():
            if name == 'name' and isinstance(value, str):
                sequences.add(value)
    return sequences, previews


def delete(identity):
    with nodes.SEQUENCE_LOCK, saved_state.LOCK:
        value = load(identity, deleting=True)
        from .timeline_api.service import authorize_sequence, sequence_identity
        authorize_sequence(value['sequence'], None, 'take_delete')
        others = [load(row['id'], deleting=True) for row in listing() if row['id'] != identity]
        native_sequences, native_previews = _native_usage(value['graph'])
        # Only generation-owned directories and immutable preview PNGs are eligible. Other output files, inputs and models stay.
        output = os.path.realpath(folder_paths.get_output_directory())
        root = os.path.join(output, 'h3_sequences')
        sequence = stills._contained(root, store.validate_name(value['sequence']))
        raw_sequence = os.path.join(root, store.validate_name(value['sequence']))
        if not folder_paths.is_within_directory(output, sequence) or os.path.normcase(os.path.abspath(raw_sequence)) != os.path.normcase(sequence):
            raise ValueError('Story media must stay inside the ComfyUI output directory.')
        if any(os.path.normcase(os.path.abspath(path)) != os.path.normcase(os.path.realpath(path)) for path in Path(sequence).rglob('*')):
            raise ValueError('This story has linked media; remove the filesystem link before permanent deletion.')
        protected = native_previews | set().union(*(set(_previews(other)) | set(_raw_previews(other)) for other in others))
        for node in value['workflow']['nodes']:
            protected.update(_previews(node.get('properties', {}).get('h3c_uploaded_assets', [])))
            protected.update(_previews(node.get('properties', {}).get('h3c_manual_guides', [])))
        previews = (set(_owned_previews(value)) | set(_raw_previews(value))) - protected
        paths = [stills._contained(os.path.join(output, 'h3_previews'), name) for name in previews]
        if any(not folder_paths.is_within_directory(output, path) for path in paths):
            raise ValueError('Story images must stay inside the ComfyUI output directory.')
        if not saved_state.deleted(value['graph']):
            # Retain the final autosave/media associations if an OS file lock makes deletion need a retry.
            saved_state.write('library', value['graph'], 'library', value)
            saved_state.write('deleted', value['graph'], 'library', {'deleted': time.time()})
        shared_sequences = native_sequences | {other['sequence'] for other in others}
        if not any(sequence_identity(name) == sequence_identity(value['sequence']) for name in shared_sequences) and os.path.isdir(sequence):
            shutil.rmtree(sequence)
        for path in paths:
            if os.path.isfile(path):
                os.unlink(path)
        for kind, node in (('library', 'library'), ('workflow', 'workflow'), ('job', value['story'])):
            path = saved_state.path(kind, value['graph'], node)
            if os.path.isfile(path):
                os.unlink(path)
        return {'ok': True}
