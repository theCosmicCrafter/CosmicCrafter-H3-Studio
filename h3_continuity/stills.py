"""Immutable local PNG imports for accepted frame guides."""

import copy
import hashlib
import json
import re
import uuid
import io
import os
from pathlib import Path
from collections import OrderedDict
from threading import Lock

import folder_paths
import torch
from PIL import Image, ImageOps, UnidentifiedImageError

from . import timeline as rules
from . import image_recipe, still_scene
from .image_recipe import _link, _scalar, _ancestry
from . import nodes as continuity, store, takes, visual_memory, media, reference_replacements, refmods, timeline_prepare, story_bible, image_descriptions

REFERENCE_PORT = re.compile(r"ref_(images|videos|video_audios|audios)\.ref_(image|video|video_audio|audio)_(\d+)")


def _root():
    output = os.path.realpath(folder_paths.get_output_directory())
    root = os.path.realpath(os.path.join(output, "h3_previews"))
    if not folder_paths.is_within_directory(output, root):
        raise ValueError("H3 Timeline: saved images must stay inside output/h3_previews")
    return root


def file_path(file):
    relative = rules.preview_file(file)
    root = _root()
    path = os.path.realpath(os.path.join(root, file["filename"]))
    if not folder_paths.is_within_directory(root, path):
        raise ValueError("H3 Timeline: saved images must stay inside output/h3_previews")
    if not os.path.isfile(path):
        raise ValueError(f"H3 Timeline: the saved image {relative} is missing; restore the file or remove it in the "
                         "Timeline editor")
    return path


# Keep only descriptors, never uploaded bytes or decoded images.
_imports = OrderedDict()
_imports_lock = Lock()


def import_image(data: bytes) -> dict:
    root = _root()
    key = (root, hashlib.sha256(data).hexdigest())
    with _imports_lock:
        file = _imports.get(key)
        if file is not None:
            try:
                path = file_path(file)
            except ValueError:
                if os.path.lexists(os.path.join(root, file['filename'])):
                    raise
                del _imports[key]
            else:
                digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
                if file['filename'] != 'import_' + digest + '.png':
                    raise ValueError('H3 Timeline: the imported PNG has changed; restore its immutable file')
                _imports.move_to_end(key)
                return dict(file)
        file = _import_image(data)
        _imports[key] = dict(file)
        if len(_imports) > 32:
            _imports.popitem(last=False)
        return file


def _import_image(data: bytes) -> dict:
    try:
        with Image.open(io.BytesIO(data)) as source:
            image = ImageOps.exif_transpose(source)
            image = image.convert("RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB")
            image.info.clear()
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        raise ValueError(f"H3 Timeline: could not read the imported image: {error}") from None
    png = buffer.getvalue()
    file = {"filename": "import_" + hashlib.sha256(png).hexdigest() + ".png", "subfolder": "h3_previews",
            "type": "output"}
    root = _root()
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, file["filename"])
    try:
        with open(path, "xb") as output:
            output.write(png)
    except FileExistsError:
        if Path(file_path(file)).read_bytes() != png:
            raise ValueError("H3 Timeline: the imported PNG has changed; restore its immutable file")
    return file


def _contained(root, *parts):
    root = os.path.realpath(root)
    path = os.path.realpath(os.path.join(root, *parts))
    if not folder_paths.is_within_directory(root, path):
        raise ValueError('H3 still source must stay inside its sequence folder')
    return path


def _sequence(body):
    if not isinstance(body, dict):
        raise ValueError('H3 still request must be a JSON object')
    parsed = rules.parse(body.get('timeline') or '{}')
    root = os.path.realpath(continuity.sequences_root())
    name = store.validate_name(body.get('name') or '')
    folder = _contained(root, name)
    return parsed, folder, name


def _file(folder, entry, pixels=False):
    name = (entry.get('video') or {}).get('file') if pixels else str(entry.get('stem', '')) + '.safetensors'
    if not isinstance(name, str) or not name or os.path.basename(name) != name or '/' in name or '\\' in name:
        raise ValueError('H3 still source has an invalid saved filename')
    path = _contained(folder, name)
    if not os.path.isfile(path):
        raise ValueError('H3 still source file is missing')
    return path


def _stamp(folder, entry, pixels=False):
    path = _file(folder, entry, pixels)
    if not pixels:
        return store.latent_stamp(folder, entry)
    stat = os.stat(path)
    return [stat.st_mtime_ns, stat.st_size]


def _entries(folder):
    _contained(folder, store.MANIFEST)
    for entry in store.load_manifest(folder).get('segments', []):
        yield folder, entry
    take_root = _contained(folder, 'takes')
    if os.path.isdir(take_root):
        for name in os.listdir(take_root):
            directory = _contained(folder, 'takes', name)
            if os.path.isdir(directory):
                for filename in os.listdir(directory):
                    _contained(directory, filename)
    for saved in takes.saved_takes(folder):
        directory = _contained(folder, saved['folder'])
        if saved['entry']:
            yield directory, saved['entry']


def _take(entry):
    logical = [entry.get('created'), (entry.get('timeline') or {}).get('box'),
               (entry.get('timeline') or {}).get('layout')]
    return hashlib.sha256(json.dumps(logical, sort_keys=True).encode()).hexdigest()


def sources(body):
    """Catalog current and archived logical take identities without decoding or loading tensors."""
    try:
        parsed, folder, name = _sequence(body)
        index = next((i for i, box in enumerate(parsed.boxes) if box.id == body.get('box')), None)
        if index is None:
            raise ValueError('H3 still target box is missing')
        target = body.get('target') or {'kind': 'first'}
        frame = _target_frame(parsed, index, target, int((body.get('settings') or {}).get('context_frames') or 39))
        preferred = [body['box']]
        if index and not rules.is_fresh(parsed, index):
            preferred.insert(0 if target.get('kind') == 'first' else 1, parsed.boxes[rules.previous_index(parsed,index)].id)
        choices = []
        for directory, entry in _entries(folder):
            box = (entry.get('timeline') or {}).get('box')
            if box not in {item.id for item in parsed.boxes}:
                continue
            moment = frame - int(bool(entry.get('context_frames'))) if box == body['box'] else store.played_frames(entry) - 1
            moment = min(max(0, moment), store.played_frames(entry) - 1)
            try:
                stamp, pixel_stamp = _stamp(directory, entry), None
            except ValueError:
                try:
                    stamp, pixel_stamp = None, _stamp(directory, entry, True)
                except ValueError:
                    continue
            pin = dict(sequence=name, box=box, take=_take(entry), created=entry.get('created'),
                       layout=(entry.get('timeline') or {}).get('layout'), latent_stamp=stamp, moment=moment)
            if pixel_stamp is not None:
                pin['pixel_stamp'] = pixel_stamp
            choices.append(pin)
        suggested = next((pin for box in preferred for pin in choices if pin['box'] == box), None)
        from . import story_bible_write
        document=json.loads(body['timeline'])
        compiled=story_bible_write.compiled(document['boxes'][index],document.get('bible'),
                                             [box['id'] for box in document['boxes']],index)
        return {'ok': True, 'choices': choices, 'suggested': suggested,
                'source_prompt': compiled[0] if compiled else None,
                'guide_source': _previous_guide(parsed, index, frame,
                    int((body.get('settings') or {}).get('context_frames') or 39))}
    except (ValueError, OSError, TypeError, KeyError) as error:
        return {'ok': False, 'error': str(error), 'choices': []}


def resolve_pin(body, pin):
    """Follow immutable identity across archival; never follow whichever take is current now."""
    parsed, folder, name = _sequence(body)
    if not isinstance(pin, dict):
        raise ValueError('H3 still source Pin must be a JSON object')
    label = f"H3 still source {pin.get('box')!r}"
    if pin.get('sequence') != name or not any(box.id == pin.get('box') for box in parsed.boxes):
        raise ValueError(label + ' belongs to another sequence or missing box')
    matched = [(directory, entry) for directory, entry in _entries(folder)
               if (entry.get('timeline') or {}).get('box') == pin.get('box')
               and entry.get('created') == pin.get('created')
               and (entry.get('timeline') or {}).get('layout') == pin.get('layout') and _take(entry) == pin.get('take')]
    if len(matched) != 1:
        raise ValueError(label + (' is ambiguous' if matched else ' is missing or changed'))
    directory, entry = matched[0]
    pixels = pin.get('latent_stamp') is None
    expected = pin.get('pixel_stamp') if pixels else pin.get('latent_stamp')
    try:
        if expected is None or _stamp(directory, entry, pixels) != expected:
            raise ValueError(label + ' changed after selection')
    except ValueError as error:
        raise ValueError(label + ': ' + str(error)) from None
    moment = pin.get('moment')
    if type(moment) is not int or not 0 <= moment < store.played_frames(entry):
        raise ValueError(label + ' has an invalid delivered moment')
    return {'folder': directory, 'entry': entry, 'frame': visual_memory.window_frame(entry, moment),
            'conditioning': 'pixels' if pixels else 'original_latent'}


def _target_frame(parsed, index, target, context):
    probe = copy.deepcopy(parsed)
    probe.boxes[index].previews = [{'target': target, 'frame': 0}]
    resolved = rules.resolved_previews(probe, index, context)
    if not resolved:
        raise ValueError('H3 still target no longer resolves')
    return resolved[0]['frame']


def _previous_guide(parsed, index, frame, context):
    """Nearest earlier accepted guide; candidate order and current/future targets are irrelevant."""
    from . import still_scene
    first = next(i for i, box in enumerate(parsed.boxes) if box.id == still_scene.start(parsed,index))
    for at in range(index, first - 1, -1):
        if not any(item.get('guide') for item in parsed.boxes[at].previews):
            continue
        frames, carried = rules.box_length(parsed, at, context)
        last = frames - (0 if carried else 1)
        earlier = [item for item in rules.resolved_previews(parsed, at, context)
                   if item.get('guide') and 0 <= item['frame'] <= last
                   and (at < index or item['frame'] < frame)]
        if earlier:
            item = max(earlier, key=lambda item: item['frame'])
            return {'box': parsed.boxes[at].id, 'frame': item['frame'],
                    'target': copy.deepcopy(item.get('target') or {'kind': 'shot', 'shot': item['shot']}),
                    'file': copy.deepcopy(item['guide'])}
    return None


def load_guide_source(body, guide):
    parsed, _, _ = _sequence(body)
    index = next(i for i, box in enumerate(parsed.boxes) if box.id == body['box'])
    context = int((body.get('settings') or {}).get('context_frames') or 39)
    frame = _target_frame(parsed, index, body['target'], context)
    selected = {key: value for key, value in guide.items() if key != 'sha256'}
    if _previous_guide(parsed, index, frame, context) != selected:
        raise ValueError('H3 still previous accepted guide changed after preparation')
    path = Path(file_path(guide['file']))
    if hashlib.sha256(path.read_bytes()).hexdigest() != guide.get('sha256'):
        raise ValueError('H3 still previous accepted guide image changed after preparation')
    from . import shot_preview
    pixels = shot_preview.load_image(guide['file'])
    if hashlib.sha256(path.read_bytes()).hexdigest() != guide['sha256']:
        raise ValueError('H3 still previous accepted guide image changed while loading')
    return pixels


def load_source(body, pin):
    resolved = resolve_pin(body, pin)
    directory, entry = resolved['folder'], resolved['entry']
    # Recheck containment and stamps immediately before the actual loading boundary.
    pixels = resolved['conditioning'] == 'pixels'
    path = _file(directory, entry, pixels)
    if _stamp(directory, entry, pixels) != pin.get('pixel_stamp' if pixels else 'latent_stamp'):
        raise ValueError(f"H3 still source {pin['box']!r} changed before loading")
    if pixels:
        arrays = media.read_frames(path, [pin['moment']])
        return resolved, torch.from_numpy(arrays[pin['moment']].copy()).float().unsqueeze(0) / 255
    window = store.load_video_window(directory, entry, resolved['frame'] // 17 * 5, 2)
    if window.ndim != 5 or window.shape[1] != 24 or window.shape[2] != 2:
        raise ValueError(f"H3 still source {pin['box']!r} has an invalid original H3 window")
    return resolved, window


def _port(locator, conditioner):
    port = locator.get('input')
    match = REFERENCE_PORT.fullmatch(port) if isinstance(port, str) else None
    if (locator.get('node') != conditioner or not match or match[1] != match[2] + 's'
            or int(match[3]) >= (9 if match[2] == 'image' else 3)):
        raise ValueError(f'H3 still recipe reference port {port!r} is invalid')
    return port


def prepare(body):
    """Copy the current compiled recipe into one owned IMAGE output; do not submit or evaluate."""
    try:
        parsed, folder, name = _sequence(body)
        index = next((i for i, box in enumerate(parsed.boxes) if box.id == body.get('box')), None)
        if index is None:
            raise ValueError('H3 still target box is missing')
        prompt = body.get('prompt', '')
        if not isinstance(prompt, str):
            raise ValueError('H3 still prompt must be text')
        prompt = prompt if prompt.strip() else parsed.boxes[index].prompt
        if not prompt.strip():
            raise ValueError('Enter a frame image prompt or a clip video prompt before generating candidates.')
        body = dict(body, prompt=prompt)
        context = int((body.get('settings') or {}).get('context_frames') or 39)
        frame = _target_frame(parsed, index, body.get('target') or {'kind': 'first'}, context)
        reference_text, entities = _frame_reference_scope(body, parsed, index, frame, context)
        from . import reference_assets
        reference_assets.require_ready(json.loads(body['timeline']), parsed.boxes[index].id, body)
        recipe = body['recipe']
        if recipe.get('version') == 2 and recipe.get('adapter') == 'pixels':
            return _prepare_pixels(body, parsed, index, frame, name, reference_text, entities)
        graph = copy.deepcopy(body['workflow']['api'])
        bindings = recipe['bindings']
        output, condition = recipe['output'], bindings['conditioning']['node']
        if recipe.get('version') not in (1, 2) or not _link(output) or condition not in graph:
            raise ValueError('H3 still recipe output or conditioner is missing')
        if graph[condition]['class_type'] != 'MiniMaxH3ReferenceToVideo' or bindings['conditioning'].get('output') != 0:
            raise ValueError('H3 still recipe must bind native Ref2VA conditioning output 0')
        if bindings['prompt'] != {'node': condition, 'input': 'prompt'}:
            raise ValueError('H3 still recipe final prompt must bind the native conditioner prompt')
        native = graph[condition]['inputs']
        native['prompt'] = body['prompt']
        if body.get('seed') is not None:
            locator = bindings['seed']
            if type(body['seed']) is not int or locator['node'] not in graph or locator['input'] not in graph[locator['node']]['inputs']:
                raise ValueError('H3 still seed binding is invalid')
            graph[locator['node']]['inputs'][locator['input']] = body['seed']
        size = body.get('size')
        if size is not None and (not isinstance(size, dict) or set(size) != {'width', 'height'}):
            raise ValueError('H3 still size needs width and height')
        for dimension in ('width', 'height'):
            if size is not None:
                value = timeline_prepare.setting(dimension, size[dimension])
                for locator in bindings['size'][dimension]:
                    if locator['node'] not in graph or locator['input'] not in graph[locator['node']]['inputs']:
                        raise ValueError(f'H3 still {dimension} binding is missing')
                    graph[locator['node']]['inputs'][locator['input']] = value
        ports = [_port(locator, condition) for locator in bindings['references']]
        if len(set(ports)) != len(ports):
            raise ValueError('H3 still recipe has duplicate reference ports')
        request_context = dict(name=name, timeline=body['timeline'], settings=body.get('settings') or {},
                               box=body['box'], target=body.get('target') or {'kind': 'first'})
        source = None
        mode = None
        guide_source = None
        owners, tags = _references(body, parsed, index, frame, graph, native, ports, reference_text)
        native['prompt'] = rules.rewrite(native['prompt'], tags) if tags else native['prompt']
        native['source_pin'] = json.dumps({'body': request_context, 'pin': source, 'references': owners,
                                         'guide_source': guide_source})
        graph[condition]['class_type'] = 'H3C_StillConditioning'
        graph = _ancestry(graph, output)
        if any(value == [condition, 1] for node in graph.values() for value in node.get('inputs', {}).values()):
            raise ValueError('H3 still target must use its independent Fizgig latent')
        if _scalar(graph, native.get('length')) != 5:
            raise ValueError('H3 still conditioning must use native Ref2VA length 5')
        digest = hashlib.sha256(json.dumps(graph, sort_keys=True).encode()).hexdigest()
        if 'h3c_still_output' in graph:
            raise ValueError('H3 still recipe collides with the owned output')
        graph['h3c_still_output'] = {'class_type': 'SaveImage', 'inputs': {'images': list(output),
            'filename_prefix': 'h3_previews/still_' + str(uuid.uuid4())}}
        provenance = {key: copy.deepcopy(body.get(key)) for key in ('request_id', 'box', 'target', 'prompt', 'seed', 'source', 'size')}
        provenance.update(recipe_sha256=digest, conditioning=mode, frame=frame, guide_source=guide_source,
                          effective_prompt=native['prompt'],
                          seed=_scalar(graph, graph[bindings['seed']['node']]['inputs'][bindings['seed']['input']]),
                          width=_scalar(graph, graph[bindings['size']['width'][-1]['node']]['inputs'][bindings['size']['width'][-1]['input']]),
                          height=_scalar(graph, graph[bindings['size']['height'][-1]['node']]['inputs'][bindings['size']['height'][-1]['input']]),
                          references=owners)
        return {'ok': True, 'prompt_id': str(uuid.uuid4()), 'prompt': graph,
                'outputs': ['h3c_still_output'], 'provenance': provenance}
    except (ValueError, OSError, TypeError, KeyError, IndexError) as error:
        return {'ok': False, 'error': str(error)}


def _timeline_inputs(body, graph, required):
    workflow = body['workflow']
    selector = workflow.get('timeline_node')
    candidates = [node for node, value in graph.items() if value.get('class_type') == 'H3C_Timeline']
    if selector is None:
        candidates = [node for node in candidates if _scalar(graph, graph[node]['inputs'].get('name')) == body.get('name')]
        if len(candidates) != 1:
            if not required and not candidates:
                return {}
            raise ValueError('H3 still reference Timeline instance is missing or ambiguous')
        selector = candidates[0]
    if selector not in candidates:
        raise ValueError('H3 still reference Timeline instance is missing')
    inputs = graph[selector]['inputs']
    if (_scalar(graph, inputs.get('name')) != body.get('name')
            or _scalar(graph, inputs.get('timeline')) != body.get('timeline')):
        raise ValueError('H3 still reference Timeline identity changed')
    return {key.rsplit('.', 1)[-1]: value for key, value in inputs.items()
            if re.fullmatch(r'(images|videos|audios|video_audios)\.(image|video|audio|video_audio)[1-9]\d*', key)}


def _references(body, parsed, index, frame, graph, native, ports, reference_text=None):
    mentioned = [name for _, name in rules.mentions(native['prompt'] if reference_text is None else reference_text)
                 if not rules.reference_disabled(name, parsed.disabled_refs)]
    if len(mentioned) != len(set(mentioned)):
        mentioned = list(dict.fromkeys(mentioned))
    for port in list(native):
        if REFERENCE_PORT.fullmatch(port):
            del native[port]
    if not mentioned:
        return [], {}
    for slot in list(mentioned):
        if reference_replacements.kind(slot) == 'video_audio':
            video = slot.replace('video_audio', 'video')
            if video not in mentioned:
                mentioned.append(video)
    inputs = _timeline_inputs(body, graph, True)
    reference_replacements.refmods(parsed)
    refmods.resolve(parsed)
    mods = {ref['slot']: ref for ref in parsed.refmods if ref.get('strength', 1) > 0}
    plates = rules.effective_plates(parsed, index, frame)
    owners = []
    replacements = reference_replacements.effective(parsed)
    available = {kind: [port for port in ports if port.startswith('ref_' + kind + 's.')]
                 for kind in ('image', 'video', 'audio', 'video_audio')}
    paired = {}
    for soundtrack in sorted(mentioned, key=rules.slot_number):
        if reference_replacements.kind(soundtrack) != 'video_audio':
            continue
        video = soundtrack.replace('video_audio', 'video')
        for port in available['video']:
            audio_port = 'ref_video_audios.ref_video_audio_' + port.rsplit('_', 1)[-1]
            if audio_port in available['video_audio']:
                paired[video], paired[soundtrack] = port, audio_port
                available['video'].remove(port)
                available['video_audio'].remove(audio_port)
                break
        else:
            raise ValueError(f'H3 still recipe needs paired native video/audio ports for @{video} and @{soundtrack}')
    for slot in sorted(mentioned, key=lambda name: (reference_replacements.kind(name) != 'image', rules.slot_number(name))):
        origin = reference_replacements.origin(slot, replacements)
        ref = mods.get(slot)
        kind = ref['kind'] if ref else reference_replacements.kind(slot)
        owner = {'slot': slot, 'kind': kind}
        if slot in plates and slot not in parsed.reference_replacements:
            kind = owner['kind'] = 'image'
            owner['file'] = plates[slot]['image']
        elif ref:
            owner['refmod'] = copy.deepcopy(ref)
        else:
            file = reference_replacements.file_for(parsed, slot)
            if file is not None:
                reference_replacements.file_path(file, slot)
                owner['file'] = copy.deepcopy(file)
            else:
                link = inputs.get(origin.get('source'))
                if not _link(link):
                    raise ValueError(f'H3 still reference @{slot} is not connected')
                owner['link'] = list(link)
        if slot in paired:
            port = paired[slot]
        else:
            if not available.get(kind):
                raise ValueError(f'H3 still recipe needs a declared native {kind} port for @{slot}')
            port = available[kind].pop(0)
        owner['port'] = port
        if 'link' in owner:
            native[port] = owner['link']
        owners.append(owner)
    tags = {}
    ordered_ports = {}
    for kind, label in (('image', 'Picture'), ('video', 'Video'), ('audio', 'Audio')):
        filled = {port for port in native if port.startswith('ref_' + kind + 's.')}
        filled.update(owner['port'] for owner in owners if owner['kind'] == kind)
        ordered = ordered_ports[kind] = sorted(filled, key=lambda port: int(port.rsplit('_', 1)[-1]))
        if kind != 'audio':
            for owner in owners:
                if owner['kind'] == kind:
                    tags[owner['slot']] = f'<{label} {ordered.index(owner["port"]) + 1}>'
    soundtracks = {port for port in native if port.startswith('ref_video_audios.')}
    soundtracks.update(owner['port'] for owner in owners if owner['kind'] == 'video_audio')
    audio_number = 0
    for video in ordered_ports['video']:
        audio = 'ref_video_audios.ref_video_audio_' + video.rsplit('_', 1)[-1]
        if audio in soundtracks:
            audio_number += 1
            for owner in owners:
                if owner['port'] == audio:
                    tags[owner['slot']] = f'<Audio {audio_number}>'
    for number, port in enumerate(ordered_ports['audio'], audio_number + 1):
        for owner in owners:
            if owner['port'] == port:
                tags[owner['slot']] = f'<Audio {number}>'
    return owners, tags


def result(body):
    """Recover only the receipt's native queue item and its own SaveImage collector."""
    from server import PromptServer
    try:
        if not isinstance(body, dict):
            raise ValueError('H3 still receipt must be an object')
        prompt_id = body['prompt_id']
        if str(uuid.UUID(prompt_id)) != prompt_id:
            raise ValueError('H3 still receipt has an invalid prompt UUID')
        expected = {key: body[key] for key in ('request_id', 'prompt_id', 'provenance')}
        expected['collector'] = 'h3c_still_output'
        queue = PromptServer.instance.prompt_queue
        running, pending = queue.get_current_queue()
        history = queue.get_history(prompt_id=prompt_id)
        rows = [('running', row, None) for row in running if row[1] == prompt_id]
        rows += [('queued', row, None) for row in pending if row[1] == prompt_id]
        if prompt_id in history:
            entry = history[prompt_id]
            rows.append(('history', entry.get('prompt'), entry))
        if not rows:
            return {'ok': True, 'state': 'unknown', 'images': [], 'provenance': body['provenance']}
        if len(rows) != 1:
            raise ValueError('H3 still UUID has conflicting queue evidence')
        state, row, entry = rows[0]
        if (not isinstance(row, (list, tuple)) or len(row) < 5 or row[1] != prompt_id
                or row[3].get('h3c_still') != expected or row[4] != ['h3c_still_output']):
            raise ValueError('H3 still history does not belong to this receipt')
        collector = row[2].get('h3c_still_output', {})
        prefix = collector.get('inputs', {}).get('filename_prefix', '')
        if collector.get('class_type') != 'SaveImage' or not re.fullmatch(r'h3_previews/still_[A-Za-z0-9_-]+', prefix):
            raise ValueError('H3 still history has an invalid collector')
        images = []
        if entry is not None:
            status = entry.get('status') or {}
            events = [message[0] for message in status.get('messages', []) if isinstance(message, (list, tuple)) and message]
            if 'execution_interrupted' in events:
                state = 'cancelled'
            elif 'execution_error' in events or status.get('status_str') == 'error':
                state = 'failed'
            elif status.get('status_str') == 'success' and status.get('completed') is True:
                state = 'complete'
                collected = entry.get('outputs', {}).get('h3c_still_output', {}).get('images')
                if not isinstance(collected, list) or not collected:
                    raise ValueError('H3 still history is missing its collector images')
                for index, file in enumerate(collected):
                    if not re.fullmatch(re.escape(prefix.split('/')[1]) + r'_\d+_\.png', str(file.get('filename', ''))):
                        raise ValueError('H3 still output is outside its owned collector prefix')
                    images.append({'file': import_image(Path(file_path(file)).read_bytes()), 'batch_index': index})
            else:
                state = 'unknown'
        return {'ok': True, 'state': state, 'images': images, 'provenance': copy.deepcopy(body['provenance'])}
    except (ValueError, OSError, TypeError, KeyError, AttributeError) as error:
        return {'ok': False, 'error': str(error)}


def pin_image(file):
    """Freeze a local image's bytes, using the existing contained file descriptor resolver."""
    path = reference_replacements.file_path(file, 'image')
    with Image.open(path) as picture:
        picture.verify()
    return {'file': copy.deepcopy(file), 'sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest()}


def load_pixel_source(source):
    """Invocation-only pixels. Never read a video latent or change original image bytes."""
    if 'pin' in source:
        resolved = resolve_pin(source['body'], source['pin'])
        path = _file(resolved['folder'], resolved['entry'], True)
    else:
        path = reference_replacements.file_path(source['file'], 'image')
    def check():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != source['sha256']:
            raise ValueError('Still reference bytes changed after preparation')
    check()
    if 'pin' in source:
        moment = source['pin']['moment']
        pixels = torch.from_numpy(media.read_frames(path, [moment])[moment].copy()).float().unsqueeze(0) / 255
    else:
        import numpy as np
        with Image.open(path) as image:
            pixels = torch.from_numpy(np.array(ImageOps.exif_transpose(image).convert('RGB')).copy()).float().unsqueeze(0) / 255
    check()
    size = source.get('size')
    if size and tuple(pixels.shape[1:3]) != (size['height'], size['width']):
        # Keep world geometry intact: fit inside the canvas and pad the margins, never stretch.
        import torch.nn.functional as F
        height,width=pixels.shape[1:3]; scale=min(size['width']/width,size['height']/height)
        h,w=max(1,round(height*scale)),max(1,round(width*scale))
        values=F.interpolate(pixels.movedim(-1,1),size=(h,w),mode='bicubic',align_corners=False).clamp(0,1)
        dw,dh=size['width']-w,size['height']-h
        pixels=F.pad(values,(dw//2,dw-dw//2,dh//2,dh-dh//2),mode='replicate').movedim(1,-1)
    return pixels


def _pixel_references(body, parsed, index, frame, graph):
    refs=[]
    mentioned=list(dict.fromkeys(name for _,name in rules.mentions(body['prompt'])
                                if not rules.reference_disabled(name,parsed.disabled_refs)))
    plates=rules.effective_plates(parsed,index,frame)
    replacements=reference_replacements.effective(parsed)
    reference_replacements.refmods(parsed); refmods.resolve(parsed)
    mods={ref['slot']:ref for ref in parsed.refmods if ref.get('strength',1)>0}
    inputs=_timeline_inputs(body,graph,False)
    for slot in sorted(mentioned,key=rules.slot_number):
        if reference_replacements.kind(slot)!='image':
            continue  # Audio and motion cues do not belong to a single-frame image request.
        owner={'slot':slot,'kind':'image','roles':[slot]}
        ids = [box.id for box in parsed.boxes]
        for entity in (parsed.bible or {}).get('entities', []):
            if slot in story_bible.pictures_at(entity, ids, index):
                role = {'character': 'identity', 'place': 'location', 'prop': 'prop'}[entity['kind']]
                owner['roles'].append(role + ': ' + entity['name'])
        original = reference_replacements.origin(slot, replacements).get('source', slot)
        picture = next((picture for picture in parsed.pictures if picture['slot'] == original), {})
        if picture.get('title'):
            owner['title'] = picture['title']
        file=plates.get(slot,{}).get('image') if slot not in parsed.reference_replacements else None
        file=file or reference_replacements.file_for(parsed,slot)
        if file:
            owner.update(pin_image(file))
        elif slot in mods:
            pack,_=refmods.backend(); path,meta=refmods.metadata(mods[slot],pack)
            if meta.get('kind')!='image' or meta.get('kind')=='bundle' or mods[slot].get('member',-1)!=-1:
                raise ValueError(f'Still reference {slot} needs an explicit pixel image for this RefMod member')
            preview=refmods.thumbnail(path)
            if not preview:
                raise ValueError(f'Still reference {slot} needs its saved pixel preview')
            file=import_image(Path(preview).read_bytes()); owner.update(pin_image(file))
            owner['refmod']=copy.deepcopy(mods[slot])
        else:
            origin=reference_replacements.origin(slot,replacements).get('source')
            link=inputs.get(origin)
            if not _link(link):
                raise ValueError(f'Still reference @{slot} is not connected')
            _pixel_link(owner, link, graph)
        if owner.get('sha256'):
            stamp = 'sha256:' + owner['sha256']
            shared = image_descriptions.lookup(stamp)
            if shared is not None:
                owner['description'] = shared['text']
            else:
                for name in dict.fromkeys([slot, original]):
                    saved = parsed.reference_descriptions.get(name, {})
                    source = saved.get('source', '')
                    if source.startswith('['):
                        try:
                            scene = json.loads(source)
                            source = scene[-1] if isinstance(scene, list) and len(scene) == 4 and scene[0] == 'idea-scene-v1' else source
                        except ValueError:
                            pass
                    if source == stamp:
                        owner['description'] = saved['text']
                        break
        refs.append(owner)
    return refs


def _pixel_link(owner, link, graph):
    if not _link(link) or link[0] not in graph:
        raise ValueError(f'Still reference @{owner["slot"]} needs a connected IMAGE output')
    producer=graph[link[0]]
    if producer['class_type']=='LoadImage' and link[1]==0:
        annotated=_scalar(graph,producer['inputs']['image'])
        path=folder_paths.get_annotated_filepath(annotated)
        file=import_image(Path(path).read_bytes()); owner.update(pin_image(file))
    else:
        ancestry = _ancestry(graph, link)
        owner.update(output=list(link), graph_sha256=hashlib.sha256(
            json.dumps(ancestry, sort_keys=True).encode()).hexdigest())


def _recipe_references(body, reference_text):
    graph=body['workflow']['api']
    ports=body['recipe']['bindings']['references']
    requested = dict.fromkeys(match.lower() for match in re.findall(r'@still[1-9]\d*\b', reference_text, flags=re.I))
    refs=[]
    for number,loc in enumerate(ports,1):
        slot=f'still{number}'
        if '@'+slot not in requested:
            continue
        if loc['node'] not in graph:
            raise ValueError('Still recipe reference IMAGE port is missing')
        link=graph[loc['node']]['inputs'].get(loc['input'])
        if link is None:
            continue
        ref={'slot':slot,'kind':'image','roles':['additional identity: '+slot],'source_port':copy.deepcopy(loc)}
        _pixel_link(ref,link,graph)
        refs.append(ref)
    connected={ref['slot'] for ref in refs}
    for slot in requested:
        if slot[1:] not in connected:
            raise ValueError(f'Still reference {slot} is not connected')
    return refs


def _frame_reference_scope(body, parsed, index, frame, context):
    from .still_prompt_preparation import _shots, _visual

    clip = parsed.boxes[index].prompt
    prompt = body['prompt']
    shots, style = _shots(prompt)
    target = body.get('target') or {'kind': 'first'}
    number = target.get('shot', 1)
    if len(shots) > 1 and target['kind'] == 'last':
        played, carried = rules.box_length(parsed, index, context)
        frames = rules._shot_frames(prompt, carried, played - (0 if carried else 1))
        number = max((n for n in frames if frames[n] <= frame), key=lambda n: (frames[n], n), default=1)
    shot = shots[0] if len(shots) == 1 else next((shot for shot in shots if shot['number'] == number), None)
    text = '\n'.join(filter(None, (_visual(style), _visual(shot['text']) if shot else '')))
    labels = set(re.findall(r'<Subject [1-9]\d*>', text))
    definitions = story_bible.subject_lines(clip) | story_bible.subject_lines(prompt)
    text += ''.join('\n' + definitions[label][2] for label in sorted(labels & definitions.keys()))
    text = re.sub(r'<image([1-9]\d*)>', lambda m:'@image'+m[1], text, flags=re.I)
    if len(shots) == 1 and prompt == clip:
        return text, None  # A single-shot clip's Cast and schedule already describe this shot.
    box = json.loads(body['timeline'])['boxes'][index]
    slots = {slot for kind, slot in rules.mentions(text) if kind == 'image'}
    cast = box.get('cast') or {}
    entities = {cast[label] for label in labels if label in cast}
    place = (box.get('schedule') or {}).get('place')
    if prompt == clip and place:
        entities.add(place)
    ids = [box.id for box in parsed.boxes]
    for entity in (parsed.bible or {}).get('entities', []):
        if slots.intersection(story_bible.pictures_at(entity, ids, index)) or re.search(
                r'(?<!\w)' + re.escape(entity['name']) + r'(?!\w)', text, re.I):
            entities.add(entity['id'])
    return text, entities


def _prepare_pixels(body, parsed, index, frame, name, reference_text=None, entities=None):
    selection = dict(body, prompt=body['prompt'] if reference_text is None else reference_text)
    from . import reference_assets
    document = json.loads(body['timeline'])
    prepared = reference_assets.references(document, parsed.boxes[index].id, dict(body, frame=frame), entities=entities)
    identity = reference_assets.identity_slots(document, parsed.boxes[index].id, entities=entities)
    selection['prompt'] += ' ' + ' '.join('@' + slot for slot in identity)
    refs = prepared + _pixel_references(selection, parsed, index, frame, body['workflow']['api'])
    for ref in refs:
        if ref.get('slot') in identity and 'identity' not in ref['roles']:
            ref['roles'].append('identity')
    refs += _recipe_references(body, selection['prompt'])
    return image_recipe.prepare(body['recipe'], body['workflow'], dict(body, frame=frame), refs)
