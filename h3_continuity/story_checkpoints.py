"""Explicit Story snapshots, with independent native videos and takes."""

import copy
import json
import os
import shutil
import struct
import uuid

from . import generations, nodes, saved_state, store, story_library, takes, timeline


def _retarget_renders(archive, result):
    """Keep matching renders matching after their own media references move to the snapshot folder."""
    old, new = archive['takes']['sequence'], result['sequence']
    before, after = timeline.parse(archive['timeline']), timeline.parse(result['timeline'])
    folder = generations._folder(new)
    manifest = store.load_manifest(folder)
    metadata = []
    for item in archive['takes']['files']:
        if item['relative'].endswith('.safetensors'):
            path = generations._relative(folder, item['relative'])
            entry = takes.read_entry(path)
            if entry is not None:
                with open(path, 'rb') as stream:
                    length = struct.unpack('<Q', stream.read(8))[0]
                    header = json.loads(stream.read(length))
                metadata.append({'path': path, 'entry': entry, 'header': header, 'length': length, 'stat': os.stat(path)})
    layouts = {}
    indices = {box.id: index for index, box in enumerate(before.boxes)}
    for entry in [*manifest['segments'], *(item['entry'] for item in metadata)]:
        record = entry.get('timeline') or {}
        index = indices.get(record.get('box'))
        context = (record.get('settings') or {}).get('context_frames', 39)
        if index is not None and isinstance(context, int) and record.get('layout') == timeline.layout_key(before, index, context):
            layouts[record['layout']] = timeline.layout_key(after, index, context)

    stamps = {}

    def remap(value):
        value = generations._remap(value, old, new)
        if isinstance(value, list):
            return [remap(child) for child in value]
        if not isinstance(value, dict):
            return value
        result = {key: layouts.get(child, child) if key == 'layout' and isinstance(child, str) else remap(child)
                  for key, child in value.items()}
        if isinstance(value.get('file_stamp'), list):
            result['file_stamp'] = stamps.get((value.get('box'), *value['file_stamp']), value['file_stamp'])
        return result

    # Plan header sizes before streaming: memory stamps include file size as well as modification time.
    for _ in range(8):
        planned = {}
        for item in metadata:
            updated = remap(item['entry'])
            item['encoded'] = None
            size = item['stat'].st_size
            if updated != item['entry']:
                header = copy.deepcopy(item['header'])
                header['__metadata__']['h3c'] = json.dumps(updated)
                encoded = json.dumps(header, separators=(',', ':')).encode('utf-8')
                encoded += b' ' * (-len(encoded) % 8)
                item['encoded'] = encoded
                size += len(encoded) - item['length']
            stamp = item['stat']
            planned[(store.box_of(item['entry']), stamp.st_mtime_ns, stamp.st_size)] = [stamp.st_mtime_ns, size]
        if planned == stamps:
            break
        stamps = planned
    else:
        raise ValueError('Could not preserve the checkpoint visual-memory file stamps.')

    # Latent metadata is also the source of archived takes. Stream tensor bytes unchanged, without loading them
    # into RAM, and preserve timestamps used by visual-memory stamps.
    for item in metadata:
        encoded = item['encoded']
        if encoded is None:
            continue
        path, stamp = item['path'], item['stat']
        temporary = path + '.tmp'
        try:
            with open(path, 'rb') as source, open(temporary, 'wb') as target:
                source.seek(8 + item['length'])
                target.write(struct.pack('<Q', len(encoded)))
                target.write(encoded)
                shutil.copyfileobj(source, target)
            os.replace(temporary, path)
            os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    store.write_manifest(folder, remap(manifest))


def _control(workflow, node, name):
    """Find a serialized widget through editable Text controls, just like the Studio."""
    seen = set()
    while True:
        ports = [port for port in node.get('inputs', []) if port.get('widget')]
        index = next((i for i, port in enumerate(ports) if port['widget']['name'] == name), None)
        if index is None or index >= len(node.get('widgets_values', [])):
            raise ValueError(f'The checkpoint needs an editable {name} control.')
        port = ports[index]
        if port.get('link') is None:
            return node['widgets_values'], index
        link_id = port['link']
        if link_id in seen:
            raise ValueError('The checkpoint has a cyclic Text connection.')
        seen.add(link_id)
        link = next((link for link in workflow['links'] if (link[0] if isinstance(link, list) else link['id']) == link_id), None)
        origin = link[1] if isinstance(link, list) else (link or {}).get('origin_id')
        node = next((item for item in workflow['nodes'] if str(item['id']) == str(origin)), None)
        if not node or node['type'] not in ('PrimitiveString', 'PrimitiveStringMultiline'):
            raise ValueError(f'The checkpoint needs a Text control for {name}; its connected value is computed.')
        name = 'value'


def _clone(graph, story, workflow, sequence, title=None, timeline_text=None):
    # Use a new library identity before saving anything: never flush/overlay a divergent tab's local content.
    workflow = copy.deepcopy(workflow)
    workflow.setdefault('extra', {})['h3c_story_id'] = graph
    source = next((node for node in workflow['nodes'] if node['type'] == 'H3C_Story' and str(node['id']) == str(story)), None)
    if source is None:
        raise ValueError('The checkpoint needs its Story node.')
    state_values, state_index = _control(workflow, source, 'state')
    state = json.loads(state_values[state_index] or '{}')
    connected = set()
    for link in workflow['links']:
        origin = link[1] if isinstance(link, list) else link.get('origin_id')
        target_id = link[3] if isinstance(link, list) else link.get('target_id')
        if str(origin) == str(story):
            connected.add(str(target_id))
    targets = [node for node in workflow['nodes'] if node['type'] == 'H3C_Timeline' and str(node['id']) in connected]
    if len(targets) > 1:
        raise ValueError('Connect this Story to one Timeline before saving a checkpoint.')
    target = targets[0] if targets else next((node for node in workflow['nodes'] if node['type'] == 'H3C_Timeline' and str(node['id']) == str(state.get('timeline'))), None)
    if target is None:
        timelines = [node for node in workflow['nodes'] if node['type'] == 'H3C_Timeline']
        if len(timelines) != 1:
            raise ValueError('Connect this Story to one Timeline before saving a checkpoint.')
        target = timelines[0]
    line_values, line_index = _control(workflow, target, 'timeline')
    name_values, name_index = _control(workflow, target, 'name')
    if name_values[name_index] != sequence:
        raise ValueError('The checkpoint Timeline folder changed. Try saving again.')
    fields = {}
    for name in ('state', 'idea', 'idea_images', 'template'):
        if any(port.get('widget', {}).get('name') == name for port in source.get('inputs', [])):
            values, index = _control(workflow, source, name)
            fields[name] = values[index]
    state['timeline'] = str(target['id'])
    if title is not None:
        state['title'] = title
    fields['state'] = json.dumps(state, ensure_ascii=False)
    # Existing interchange verifies/copies native files and remaps embedded media descriptors. No hardlinks:
    # regenerating or deleting a take must never change a checkpoint's bytes.
    with nodes.SEQUENCE_LOCK:
        line = line_values[line_index] if timeline_text is None else timeline_text
        archive = generations.export_generation({'name': sequence, 'timeline': line, 'story': fields})
        result = generations.import_generation(archive, str(uuid.uuid4()))
        _retarget_renders(archive, result)
    workflow = generations._remap(workflow, sequence, result['sequence'])
    source = next(node for node in workflow['nodes'] if str(node['id']) == str(story))
    target = next(node for node in workflow['nodes'] if str(node['id']) == str(target['id']))
    for node, values in ((source, result['story']), (target, {'name': result['sequence'], 'timeline': result['timeline']})):
        for name, value in values.items():
            controls, index = _control(workflow, node, name)
            controls[index] = value
            # Keep converted widgets consistent with their Text source for listing and older clients too.
            local = [port for port in node.get('inputs', []) if port.get('widget')]
            local_index = next(i for i, port in enumerate(local) if port['widget']['name'] == name)
            node['widgets_values'][local_index] = value
            for owner in workflow['nodes']:
                if owner is node or owner.get('widgets_values') is controls:
                    owner_index = local_index if owner is node else index
                    ports = [port for port in owner.get('inputs', []) if port.get('widget')]
                    if 'widgets_values_named' in owner:
                        owner['widgets_values_named'][ports[owner_index]['widget']['name']] = value
    identity = str(uuid.uuid4())
    workflow['id'] = identity
    workflow['extra']['h3c_story_id'] = identity
    for node in workflow['nodes']:
        node.get('properties', {}).pop('h3c_library_revision', None)
        if str(node['id']) == str(target['id']):
            # A project attachment or old fork pin must not redirect this independent copy to the source folder.
            for key in ('h3c_project', 'h3c_asset_bindings', 'h3c_fork_sequence'):
                node.get('properties', {}).pop(key, None)
            node.setdefault('properties', {})['h3c_fork_sequence'] = result['sequence']
    return identity, workflow, result['sequence']


def save(graph, story, workflow, sequence, name):
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
        raise ValueError('Give the checkpoint a name of 1–120 characters.')
    name = name.strip()
    # Validate the snapshot before copying media; save() supplies the existing workflow/identity checks.
    if not isinstance(workflow, dict) or (workflow.get('extra', {}).get('h3c_story_id') or workflow.get('id')) != graph:
        raise ValueError('The checkpoint needs its original workflow identity.')
    identity, snapshot, folder = _clone(graph, story, workflow, sequence)
    with saved_state.LOCK:
        result = story_library.save(identity, story, snapshot, folder)
        value = saved_state.read('library', identity, 'library')['value']
        value.update(checkpoint_name=name, source_graph=graph)
        saved_state.write('library', identity, 'library', value)
    return result


def duplicate(graph, story, workflow, sequence, title=None, timeline_text=None):
    """An editable library copy with its own renders; timeline_text replaces the Timeline the copy starts from."""
    if title is not None and (not isinstance(title, str) or not 1 <= len(title.strip()) <= 120):
        raise ValueError('Give the copy a title of 1–120 characters.')
    if timeline_text is not None:
        if not isinstance(timeline_text, str):
            raise ValueError('The replacement Timeline must be JSON text.')
        timeline.parse(timeline_text)
    if not isinstance(workflow, dict) or (workflow.get('extra', {}).get('h3c_story_id') or workflow.get('id')) != graph:
        raise ValueError('The copy needs its original workflow identity.')
    identity, copied, folder = _clone(graph, story, workflow, sequence, title and title.strip(), timeline_text)
    result = story_library.save(identity, story, copied, folder)
    fields = story_library._fields(copied)
    node = next(node for node in copied['nodes']
                if node['type'] == 'H3C_Timeline' and node.get('properties', {}).get('h3c_fork_sequence') == folder)
    return dict(id=result['id'], graph=identity, story=str(story), timeline_node=str(node['id']), sequence=folder,
                title=fields.get((str(story), 'state'), {}).get('title') or 'Untitled story')


def restore(identity):
    value = story_library.load(identity)
    if not value.get('checkpoint_name'):
        raise ValueError('Choose a named checkpoint to open an editable copy.')
    graph, workflow, sequence = _clone(value['graph'], value['story'], value['workflow'], value['sequence'])
    result = story_library.save(graph, value['story'], workflow, sequence)
    return story_library.load(result['id'])
