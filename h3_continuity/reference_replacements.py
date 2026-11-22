"""Timeline reference substitutions, keeping the names authored in prompts and frame assignments."""

import os
import re

from . import timeline as rules, studio_pictures


def kind(name):
    match = re.fullmatch(r'(image|audio|video_audio|video)[1-9]\d*', name) if isinstance(name, str) else None
    return match.group(1) if match else None


def validate(value):
    if not isinstance(value, dict):
        raise ValueError('H3 Timeline: reference_replacements must be an object')
    for target, replacement in value.items():
        if not kind(target) or not isinstance(replacement, dict) or set(replacement) not in ({'source'}, {'file'}):
            raise ValueError('H3 Timeline: a reference replacement needs a canonical slot and exactly one source or file')
        if 'source' in replacement:
            if kind(replacement['source']) != kind(target):
                raise ValueError(f'H3 Timeline: replacement for {target} needs a source of the same type')
        else:
            rules.audio_file(replacement['file'])
    for target in value:
        origin(target, value)
    return value


def effective(timeline):
    replacements = dict(timeline.reference_replacements)
    for target, replacement in timeline.reference_replacements.items():
        if kind(target) == 'video':
            soundtrack = target.replace('video', 'video_audio')
            replacements.setdefault(soundtrack, {'file': replacement['file']} if 'file' in replacement else
                                    {'source': replacement['source'].replace('video', 'video_audio')})
    return replacements


def origin(name, replacements):
    visited = set()
    while name in replacements:
        if name in visited:
            raise ValueError(f'H3 Timeline: reference replacement cycle at {name}')
        visited.add(name)
        replacement = replacements[name]
        if 'file' in replacement:
            return replacement
        name = replacement['source']
    return {'source': name}


def pairing(timeline):
    replacements = effective(timeline)
    for target in timeline.reference_replacements:
        if kind(target) != 'video_audio':
            continue
        video = origin(target.replace('video_audio', 'video'), replacements)
        soundtrack = origin(target, replacements)
        if 'file' in soundtrack:
            continue
        paired = ({'source': video['source'].replace('video', 'video_audio')} if 'source' in video else video)
        if paired != soundtrack:
            raise ValueError(f'H3 Timeline: replacement soundtrack {target} must stay paired with its video')
    return replacements


def file_kind(timeline, target):
    replacements = effective(timeline)
    while target in replacements and 'source' in replacements[target]:
        target = replacements[target]['source']
    return 'audio' if kind(target) == 'video_audio' and target in timeline.reference_replacements else kind(target)


def resolve(timeline, values, file_value):
    """Resolve values or metadata using the same source graph at every consumer boundary."""
    replacements = pairing(timeline)
    result = dict(values)
    for target in replacements:
        if rules.reference_disabled(target, timeline.disabled_refs):
            result.pop(target, None)
            continue
        source = origin(target, replacements)
        if 'file' in source:
            result[target] = file_value(target, source['file'])
        elif source['source'] in values:
            result[target] = values[source['source']]
        elif kind(target) == 'video_audio' and target not in timeline.reference_replacements:
            # A silent source video is valid until a box asks for its soundtrack.
            result.pop(target, None)
        else:
            raise ValueError(f"H3 Timeline: replacement for {target} needs {source['source']}, but that source is missing or not connected")
    return result


def refmods(timeline):
    original = {ref['slot']: ref for ref in timeline.refmods}
    replacements = effective(timeline)
    mapped = [ref for ref in timeline.refmods if ref['slot'] not in replacements]
    for target in replacements:
        if rules.reference_disabled(target, timeline.disabled_refs):
            continue
        source = origin(target, replacements).get('source')
        target_kind = original[target]['kind'] if target in original else kind(target)
        source_kind = original[source]['kind'] if source in original else kind(source) if source else kind(target)
        if target_kind != source_kind or (target_kind == 'video' and kind(target) == 'image' and source not in original):
            raise ValueError(f'H3 Timeline: replacement for {target} needs a matching {target_kind} RefMod' if target_kind == 'video' and kind(target) == 'image' else
                             f'H3 Timeline: replacement for {target} cannot use a {source_kind} RefMod')
        if source not in original:
            continue
        ref = original[source]
        mapped.append(dict(ref, slot=target))
    bound = {clip['slot'] for clip in timeline.audio_clips if 'box_windows' in clip}
    if any(ref['slot'] in bound and ref.get('strength',1)>0 for ref in mapped):
        raise ValueError('H3 Timeline: box-bound audio cannot use an aliased audio RefMod; unlock it first')
    timeline.refmods = mapped


def validate_box_audio(timeline):
    """A raw alias has no placement; it cannot silently escape a bound lane's windows."""
    lanes = {clip['slot'] for clip in timeline.audio_clips}
    replacements = effective(timeline)
    def descriptor(slot):
        file = file_for(timeline,slot)
        return {'file':file} if file else origin(slot,replacements)
    bound = [clip for clip in timeline.audio_clips if 'box_windows' in clip and clip['slot'] not in timeline.disabled_refs]
    if not bound: return
    for clip in bound:
        source = origin(clip['slot'],replacements).get('source')
        if any(ref['slot']==source and ref.get('strength',1)>0 for ref in timeline.refmods):
            raise ValueError('H3 Timeline: box-bound audio cannot use an aliased audio RefMod; unlock it first')
    used = {slot for prose in [timeline.prompt,*[box.prompt for box in timeline.boxes]]
            for kind,slot in rules.mentions(prose) if kind=='audio' and slot not in lanes and slot not in timeline.disabled_refs}
    for slot in used:
        if any(descriptor(slot)==descriptor(clip['slot']) for clip in bound):
            raise ValueError(f'H3 Timeline: @{slot} is a raw alias of box-bound audio; add an independent audio lane or use its bound slot')


def file_path(file, target):
    found = studio_pictures.path(file)
    if found is None:
        raise ValueError(f'H3 Timeline: replacement for {target} is missing: {file["filename"]}')
    return found


def media(timeline, images, audios, loaded):
    from comfy_extras.nodes_video import LoadVideo, GetVideoComponents
    import nodes
    from . import audio_tracks
    values = {**images, **audios}
    replacements = effective(timeline)
    required = {origin(target, replacements).get('source') for target in replacements
                if not rules.reference_disabled(target, timeline.disabled_refs)}
    values.update({ref['slot']: ref for ref in timeline.refmods})

    def load(target, file, cache):
        path = file_path(file, target)
        media_kind = file_kind(timeline, target)
        key = (path, 'video' if media_kind.startswith('video') else media_kind)
        if key not in cache:
            name = '/'.join(part for part in (file.get('subfolder', ''), file['filename']) if part) + f" [{file['type']}]"
            if media_kind == 'image':
                cache[key] = nodes.LoadImage().load_image(name)[0]
            elif media_kind == 'audio':
                cache[key] = audio_tracks.read(file)
            else:
                video = LoadVideo.execute(name).args[0]
                frames, audio, fps = GetVideoComponents.execute(video).args[:3]
                if float(fps) != 24:
                    import torch
                    # H3's native reference input assumes 24 fps; keep the decoded soundtrack on the same clock.
                    count = max(1, round(len(frames) * 24 / float(fps)))
                    indices = (torch.arange(count, device=frames.device) * float(fps) / 24).long().clamp_max(len(frames) - 1)
                    frames = frames[indices]
                cache[key] = (frames, audio)
        value = cache[key]
        return value[media_kind == 'video_audio'] if media_kind.startswith('video') else value

    # Saved source slots can be used even when the prompt mentions only their target.
    for entry in [*timeline.pictures, *timeline.voice_clips, *timeline.audio_clips]:
        if entry['slot'] in required and 'file' in entry and entry['slot'] not in values:
            values[entry['slot']] = load(entry['slot'], entry['file'], loaded)
    result = resolve(timeline, values, lambda target, file: load(target, file, loaded))
    return ({name: value for name, value in result.items() if kind(name) in ('image', 'video')
             and not isinstance(value, dict) and not rules.reference_disabled(name, timeline.disabled_refs)},
            {name: value for name, value in result.items() if kind(name) in ('audio', 'video_audio')
             and value is not None and not ('slot' in value if isinstance(value, dict) else False)
             and not rules.reference_disabled(name, timeline.disabled_refs)})


def fingerprint(timeline):
    result = []
    saved = {entry['slot']: entry for entry in [*timeline.pictures, *timeline.voice_clips, *timeline.audio_clips]}
    replacements = effective(timeline)
    for target in replacements:
        replacement = origin(target, replacements)
        file = replacement.get('file') or saved.get(replacement.get('source'), {}).get('file')
        if file and not rules.reference_disabled(target, timeline.disabled_refs):
            found = file_path(file, target)
            stat = os.stat(found)
            result.append((target, found, stat.st_mtime_ns, stat.st_size))
    return result


def file_for(timeline, slot):
    source = origin(slot, effective(timeline))
    if 'file' in source:
        return source['file']
    return next((entry.get('file') for entry in [*timeline.pictures, *timeline.voice_clips, *timeline.audio_clips]
                 if entry['slot'] == source['source']), None)
