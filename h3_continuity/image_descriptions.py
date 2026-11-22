"""Shared descriptions keyed by file content and purpose, using atomic saved-state writes."""
import asyncio
import hashlib
import secrets
from contextlib import asynccontextmanager

import aiohttp

from . import llm, saved_state, story_keys

IDENTITY = 'identity-traits-v1'
SCENE = 'idea-scene-v1'


def checksum(path):
    with open(path, 'rb') as handle:
        return 'sha256:' + hashlib.file_digest(handle, 'sha256').hexdigest()


def snapshot():
    return saved_state.read('workflow', 'image-descriptions', 'cache')


def lookup(source, purpose=IDENTITY):
    return (snapshot()['value'] or {}).get(source + ':' + purpose)


def save(source, text, purpose=IDENTITY, *, format=None, revision=None):
    if not isinstance(text, str) or len(text) > 12000:
        raise ValueError('A description must be text of at most 12,000 characters.')
    if purpose not in (IDENTITY, SCENE):
        raise ValueError('Unknown image description purpose.')
    with saved_state.LOCK:
        current = snapshot()
        if revision is not None and revision != current['revision']:
            return lookup(source, purpose)
        record = {'source': source, 'text': text.strip(), 'format': format or purpose}
        items = dict(current['value'] or {})
        items[source + ':' + purpose] = record
        saved_state.write('workflow', 'image-descriptions', 'cache', items, current['revision'])
        return record


def clear_all(sources=()):
    # Keep tombstones: an older workflow must not restore a cleared description.
    with saved_state.LOCK:
        current = snapshot()
        items = {key: dict(value, text='', format='manual') for key, value in (current['value'] or {}).items()}
        for source in sources:
            items[source + ':' + IDENTITY] = {'source': source, 'text': '', 'format': 'manual'}
        saved_state.write('workflow', 'image-descriptions', 'cache', items, current['revision'])


def vision_metadata(item):
    """Only positive provider metadata establishes that an unselected writer can see images."""
    for key in ('is_vision', 'supports_vision', 'vision'):
        if isinstance(item.get(key), bool):
            return item[key]
    capabilities = item.get('capabilities', {})
    if isinstance(capabilities, dict):
        for key in ('vision', 'supports_vision'):
            if isinstance(capabilities.get(key), bool):
                return capabilities[key]
    for metadata in (item, item.get('architecture')):
        if not isinstance(metadata, dict):
            continue
        modalities = metadata.get('input_modalities', metadata.get('modalities', []))
        if isinstance(modalities, dict):
            modalities = modalities.get('input', [])
        if isinstance(modalities, list) and 'image' in modalities:
            return True
    return False


async def has_vision(url, model, key=None):
    if not url or not model:
        return False
    story_keys.host_of(url)
    headers = {'Authorization': f'Bearer {key}'} if key else {}
    root = url.rstrip('/')
    endpoints = [root + '/models']
    if root.endswith('/v1'):
        endpoints.append(root[:-3] + '/api/v1/models')
    try:
        async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as session:
            for endpoint in endpoints:
                async with session.get(endpoint) as response:
                    if response.status != 200:
                        continue
                    data = await response.json(content_type=None)
                    entries = data.get('data', data.get('models', [])) if isinstance(data, dict) else []
                    for item in entries:
                        if isinstance(item, dict) and model in (item.get('id'), item.get('key'), item.get('model'), item.get('name')):
                            if vision_metadata(item):
                                return True
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError):
        pass
    return False


async def providers(body):
    """Resolve provider settings, including connected selectors, without requiring a story idea."""
    from . import story_context, story_inputs, story_job, story_vram
    prompt = body.get('prompt') or {}
    node = prompt.get(str(body.get('story')), {})
    if node.get('class_type') != 'H3C_Story':
        return {}, []
    settings, links = {}, {}
    settings['free_vram'] = (node.get('inputs') or {}).get('free_vram', True) is not False
    for name in ('base_url', 'model', 'vision_base_url', 'vision_model', 'thinking', 'story_thinking'):
        way, text = story_context.read_text(prompt, (node.get('inputs') or {}).get(name, ''))
        if way == 'run':
            links[name] = node['inputs'][name]
        settings[name] = text.strip() if way == 'text' else ''
    if links:
        busy = story_job.JOBS.busy('')
        if busy:
            raise ValueError(busy['error'])
        comfy = story_vram.Comfy()
        if comfy.busy():
            raise ValueError('Wait for the ComfyUI queue to finish before describing an image.')
        settings.update(await story_inputs.resolve(comfy, prompt, links))
    return settings, []


def source_file(body):
    from . import studio_pictures, refmods
    if body.get('file'):
        path = studio_pictures.path(body['file'])
        if not path:
            raise ValueError('The image file is missing; replace or reconnect it.')
        return path, checksum(path), ''
    if body.get('refmod'):
        ref = body['refmod']
        pack, _ = refmods.backend()
        path, meta = refmods.metadata(ref, pack)
        source = 'refmod:' + checksum(path) + ':' + str(ref.get('member', -1))
        # A bundle preview is not proof of the selected member's appearance.
        preview = refmods.thumbnail(path) if ref.get('member', -1) == -1 and meta['kind'] == 'image' else None
        return preview, source, str(ref.get('description') or meta.get('description') or '')
    raise ValueError('This reference has no readable image file.')


GENERATING = asyncio.Lock()


@asynccontextmanager
async def gpu_turn(candidates, free_vram):
    from . import story_vram
    local = free_vram and any(story_vram.on_this_pc(url) for url, _, _, _ in candidates)
    comfy, identity = story_vram.Comfy(), 'description-' + secrets.token_urlsafe(12)
    try:
        if local:
            await story_vram.take_turn(comfy, identity, lambda message: None)
        yield local
    finally:
        if local:
            story_vram.end_turn(comfy, identity)


async def handle(body):
    from . import story_job, story_vision, story_vram, story_prompts
    action = body.get('action', 'resolve')
    if action not in ('read', 'resolve', 'edit', 'clear', 'regenerate', 'clear_all'):
        raise ValueError('Unknown image description action.')
    if action == 'clear_all':
        descriptions, notes = {}, []
        images = body.get('images', [])
        if not isinstance(images, list) or len(images) > 1000:
            raise ValueError('Clear all needs a list of at most 1,000 current images.')
        for image in images:
            try:
                _, source, _ = await asyncio.to_thread(source_file, image)
                descriptions[image['slot']] = {'source': source, 'text': '', 'format': 'manual'}
            except (ValueError, OSError, TypeError, KeyError) as error:
                notes.append(str(error))
        await asyncio.to_thread(clear_all, [item['source'] for item in descriptions.values()])
        return {'ok': True, 'descriptions': descriptions, 'notes': notes}
    revision = snapshot()['revision']
    path, source, supplied = await asyncio.to_thread(source_file, body)
    purpose = body.get('purpose', IDENTITY)
    if purpose not in (IDENTITY, SCENE):
        raise ValueError('Unknown image description purpose.')
    if action in ('edit', 'clear'):
        record = await asyncio.to_thread(save, source, body.get('text', '') if action == 'edit' else '',
                                         purpose, format='manual')
        return {'ok': True, 'description': record, 'notes': []}
    record = await asyncio.to_thread(lookup, source, purpose)
    if action != 'regenerate' and record is not None:
        return {'ok': True, 'description': record, 'notes': []}
    if action != 'regenerate' and supplied:
        record = await asyncio.to_thread(save, source, supplied, purpose, format='manual', revision=revision)
    if action == 'read' or record is not None and action != 'regenerate':
        return {'ok': True, 'description': record or {'source': source, 'text': '', 'format': purpose}, 'notes': []}
    settings, notes = await providers(body)
    candidates = []
    own_url, own_model = settings.get('base_url', ''), settings.get('model', '')
    own_key = story_keys.key_for(own_url) if own_url else None
    if path and await has_vision(own_url, own_model, own_key):
        candidates.append((own_url, own_model, own_key, settings.get('story_thinking') or settings.get('thinking')))
    vision_model = settings.get('vision_model')
    vision_url = settings.get('vision_base_url') or own_url
    if path and vision_model and vision_url and not any((url, model) == (vision_url, vision_model) for url, model, _, _ in candidates):
        candidates.append((vision_url, vision_model, story_keys.key_for(vision_url), settings.get('thinking')))
    result = {'source': source, 'text': '', 'format': 'binding'}
    if not candidates:
        notes.append('No available vision model; the subject keeps only its image binding.')
        return {'ok': True, 'description': result, 'notes': notes}
    async with GENERATING:
        busy = story_job.JOBS.busy('')
        if busy:
            raise ValueError(busy['error'])
        try:
            if story_vram.Comfy().busy():
                raise ValueError('Wait for the ComfyUI queue to finish before describing an image.')
        except (ImportError, AttributeError):
            pass
        picture = await asyncio.to_thread(llm.picture_url, path)
        async with gpu_turn(candidates, settings.get('free_vram', True)) as local:
            for url, model, key, thinking in candidates:
                text, reached = '', True
                try:
                    reply = await llm.complete(url, model, [
                        {'role': 'system', 'content': story_vision.IDEA_INSTRUCTION if purpose == SCENE else story_vision.DESCRIPTION_INSTRUCTION},
                        {'role': 'user', 'content': 'Describe the visible image.', 'pictures': [{'label': 'Image', 'url': picture}]}],
                        key=key, thinking=thinking)
                    text = story_prompts.strip_reasoning(reply).strip()
                    if not text:
                        raise ValueError('The image description came back empty.')
                    _, current_source, _ = await asyncio.to_thread(source_file, body)
                    if current_source != source:
                        text = ''
                        raise ValueError('The image changed while it was being described; try again.')
                except (llm.ChatError, ValueError, OSError) as error:
                    if isinstance(error, llm.ChatError) and (error.refuses_pictures or not error.reached):
                        reached = False
                    notes.append(llm.scrub(f'{model} could not describe the image: {error}', key))
                finally:
                    if local and reached and story_vram.on_this_pc(url):
                        outcome = await story_vram.unload(url, model, key)
                        successful = tuple(f'{provider} {verb}unloaded the model' for provider in
                            ('Strata', 'Unsloth Studio', 'LM Studio', 'Ollama') for verb in ('', 'had already '))
                        if not outcome.startswith(successful):
                            raise ValueError(llm.scrub(f'Vision model unload failed: {outcome}', key))
                if text:
                    result = await asyncio.to_thread(save, source, text, purpose, revision=revision)
                    if result is None:
                        result = {'source': source, 'text': '', 'format': 'binding'}
                    break
    return {'ok': True, 'description': result, 'notes': notes}
