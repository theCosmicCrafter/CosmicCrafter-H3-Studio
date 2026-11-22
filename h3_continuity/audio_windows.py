"""Non-destructive source windows owned by stable box IDs. Times are half-open seconds."""

import copy
import math

FEATURE = 'box-audio-windows-1'
KEYS = ('start', 'source_start', 'duration')


def _number(value, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError('H3 Timeline: audio windows need finite nonnegative times and positive durations')


def validate(clip, boxes, origin):
    if 'box_windows' not in clip:
        return
    saved = clip['box_windows']
    if not isinstance(saved, dict) or type(saved.get('version')) is not int or saved['version'] != 1:
        raise ValueError('H3 Timeline: unsupported audio windows version')
    if saved.get('source') != origin or saved.get('placement') != {key: clip[key] for key in KEYS}:
        raise ValueError('H3 Timeline: unlock audio windows before changing the source or placement')
    for key in KEYS: _number(saved['placement'][key], key=='duration')
    bindings = saved.get('by_box')
    if not isinstance(bindings, dict):
        raise ValueError('H3 Timeline: audio windows need a box mapping')
    ids = {box['id'] for box in boxes}
    for box_id, window in bindings.items():
        if box_id not in ids or not isinstance(window, dict):
            raise ValueError('H3 Timeline: audio window refers to an unknown box')
        for key in ('offset', 'source_start', 'duration'):
            _number(window.get(key), key == 'duration')
        if window['source_start'] < clip['source_start'] - 1e-9 or window['source_start'] + window['duration'] > clip['source_start'] + clip['duration'] + 1e-9:
            raise ValueError('H3 Timeline: audio window is outside its captured source selection')


def capture(clip, boxes, origin):
    bindings = {}
    for box in boxes:
        first, last = max(box['start'], clip['start']), min(box['start'] + box['duration'], clip['start'] + clip['duration'])
        if last > first:
            bindings[box['id']] = dict(offset=first - box['start'], source_start=clip['source_start'] + first - clip['start'], duration=last-first)
    return dict(version=1, source=copy.deepcopy(origin), placement={key: clip[key] for key in KEYS}, by_box=bindings)


def resolve(clip, boxes):
    if 'box_windows' not in clip:
        return [dict(box=None, offset=0, **{key: clip[key] for key in KEYS})]
    result = []
    for box in boxes:
        window = clip['box_windows']['by_box'].get(box['id'])
        if window:
            duration = min(window['duration'], box['duration'] - window['offset'])
            if duration > 0:
                result.append({**window, 'box': box['id'], 'start': box['start'] + window['offset'], 'duration': duration})
    return result


def coalesce(windows):
    """Adjacent source-continuous windows are one clock for cues crossing a box edge."""
    result = []
    for window in sorted(windows, key=lambda w: w['start']):
        if result and result[-1].get('slot') == window.get('slot') and all(abs(result[-1][key] + result[-1]['duration'] - window[key]) < 1e-9 for key in ('start', 'source_start')):
            result[-1]['duration'] += window['duration']
        else:
            result.append(dict(window))
    return result


def on_output(clip, windows, parts):
    total = sum(part['frames'] for part in parts) / 24
    if 'box_windows' not in clip and 'windows' not in clip:
        movie, output, shift = 0, 0, 0
        for part in parts:
            if part['coverage']:
                if movie <= clip['start']: shift = output-movie
                movie += part['frames']/24
            output += part['frames']/24
        start = clip['start']+shift
        duration = min(clip['duration'],total-start)
        return [dict(box=None,offset=0,start=start,source_start=clip['source_start'],duration=duration)] if clip['start'] < movie and duration > 0 else []
    result, output = [], 0
    for part in parts:
        cursor = 0
        for cover in part['coverage']:
            first, last = cover['first']/24, (cover['first']+cover['frames'])/24
            for window in windows:
                if window['box'] != cover['box']: continue
                left, right = max(first,window['offset']),min(last,window['offset']+window['duration'])
                if right > left:
                    result.append(dict(box=window['box'],offset=left,start=output+cursor/24+left-first,
                                       source_start=window['source_start']+left-window['offset'],duration=right-left))
            cursor += cover['frames']
        output += part['frames']/24
    return result


def equivalent(left, right):
    left, right = coalesce(left), coalesce(right)
    return len(left)==len(right) and all(all(abs(a[key]-b[key]) < 1e-9 for key in KEYS) for a,b in zip(left,right))
