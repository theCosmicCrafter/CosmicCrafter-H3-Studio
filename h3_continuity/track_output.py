"""Compose independent tracks on their shared clock. Native generation and legacy sequence output stay separate."""
import copy
import os
import threading
from fractions import Fraction

import av
import numpy as np
from PIL import Image, ImageDraw

from . import tracks, timeline as rules, media, store, stacks, audio_tracks
from .timing import FPS

_LOCK = threading.RLock()
_JOBS = {}


def edit_list(parsed, manifest, available=None):
    data = tracks.document(parsed)
    placements = tracks.placements(data)
    priority = {t['id']: i for i, t in enumerate(parsed.tracks)}
    result = []

    def append(start, end, output, sources, sound=None, bridge=None):
        row = dict(start=start, end=end, outputStart=output, outputEnd=output+end-start,
                   sources=sources, sound=sound, bridgeId=bridge)
        if result:
            last = result[-1]
            n = last['outputEnd']-last['outputStart']
            same = (last['outputEnd'] == output and last['sound'] == sound and last['bridgeId'] == bridge
                    and len(last['sources']) == len(sources)
                    and all(a['id'] == b['id'] and a['weight'] == b['weight'] and a['first']+n == b['first']
                            for a, b in zip(last['sources'], sources)))
            if same:
                last['end'] = end; last['outputEnd'] = row['outputEnd']
                return
        result.append(row)

    for span in tracks.output_spans(data):
        if span['bridgeId']:
            count = span['outputEnd']-span['outputStart']
            append(span['start'], span['start']+count, span['outputStart'],
                   [dict(id='bridge:'+span['bridgeId'], first=0, weight=1)], 'bridge:'+span['bridgeId'], span['bridgeId'])
            continue
        for frame in range(span['start'], span['end']):
            active = sorted((p for p in placements if p['start'] <= frame < p['end']), key=lambda p: priority[p['track']])
            sources, sound = [], None
            if active:
                top = active[-1]
                sources = [dict(id=top['id'], first=frame-top['start'], weight=1)]
                sound = top['id']
                for switch in parsed.overlap_switches:
                    a = next((p for p in active if p['id'] == switch['from']), None)
                    b = next((p for p in active if p['id'] == switch['to']), None)
                    if not a or not b or top['id'] not in (a['id'], b['id']):
                        continue
                    weight = rules.layers.weight(switch, dict(at=switch['at']), frame)
                    sources = [dict(id=a['id'], first=frame-a['start'], weight=1-weight),
                               dict(id=b['id'], first=frame-b['start'], weight=weight)]
                    sources = [s for s in sources if s['weight'] > 0]
                    sound = switch['sound'] if switch['sound'] != 'screen' else (b['id'] if frame >= switch['at'] else a['id'])
                    break
            append(frame, frame+1, span['outputStart']+frame-span['start'], sources, sound)
    return result


def _entries(manifest):
    found = {store.box_of(e): e for e in manifest['segments']}
    found.update({'bridge:'+e['box']: e for e in manifest.get('bridges', [])})
    return found


def fingerprint(folder, parsed, manifest, mode, crf=16):
    stamps = []
    for entry in [*manifest['segments'], *manifest.get('layers', []), *manifest.get('bridges', [])]:
        video = entry.get('video') or {}
        files = [video.get('file')]
        if entry.get('audio_sample_rate'): files.append(entry['stem']+'.safetensors')
        for file in files:
            if not file: continue
            try:
                stat = os.stat(os.path.join(folder, file))
                stamps.append([file, stat.st_size, stat.st_mtime_ns])
            except OSError:
                stamps.append([file, None])
    source=manifest.get('source') or {}
    for file in [source.get('file'),source.get('audio')]:
        if not file: continue
        try:
            stat=os.stat(os.path.join(folder,file));stamps.append([file,stat.st_size,stat.st_mtime_ns])
        except OSError: stamps.append([file,None])
    soundtrack = audio_tracks.marked(parsed, manifest.get('reference_audio'))
    return rules._digest(dict(layout=tracks.document(parsed), layers=parsed.layers, switches=parsed.switches,
                              stamps=stamps, soundtrack=audio_tracks.soundtrack_sources(soundtrack), mode=mode, crf=crf))


def _missing(folder, parsed, row, entries):
    needs = [(s['id'], s['first']) for s in row['sources']]
    if row['sound'] and row['sound'] not in [n for n, _ in needs]:
        p = parsed.placements.get(row['sound'])
        needs.append((row['sound'], row['start']-p['start'] if p else 0))
    count = row['outputEnd']-row['outputStart']
    for identity, first in needs:
        entry = entries.get(identity)
        if not entry or not entry.get('video') or not os.path.isfile(os.path.join(folder, entry['video']['file'])):
            return identity
        if first+count > store.played_frames(entry): return identity
    return None


def build(folder, name, parsed, manifest, crf, mode='full'):
    """Write a CPU-composed movie, return its record and a user-facing note. Does not mutate the manifest."""
    key = fingerprint(folder, parsed, manifest, mode, crf)
    view = manifest
    if parsed.layers:
        view, waiting = stacks.substitute(folder, parsed, manifest, len(parsed.boxes), crf, partial=mode!='full')
        if waiting and mode == 'full': return None, ' '.join(waiting)
    entries = _entries(view)
    source=manifest.get('source')
    if mode=='partial' and source:
        entries['source']=dict(stem=name+'_source',frames=source['frames'],context_frames=0,
                               video=dict(file=source['file'],fps=24),audio_sample_rate=None)
    spans, rows = edit_list(parsed, view), []
    note = ''
    for row in spans:
        missing = _missing(folder, parsed, row, entries)
        if missing:
            note = f'Missing footage for clip {missing} at {row["start"]/FPS:.2f} s.'
            if mode == 'full': return None, note
            if mode == 'so_far': break
            if source and row['end']<=source['frames'] and os.path.isfile(os.path.join(folder,source['file'])):
                row={**row,'sources':[dict(id='source',first=row['start'],weight=1)],'sound':'source'}
            else:
                row = {**row, 'sources': [], 'sound': None, 'missing': missing}
        rows.append(row)
    if not rows: return None, note or 'No visible footage is ready.'
    used = {s['id'] for row in rows for s in row['sources']}
    paths = [os.path.join(folder, entries[i]['video']['file']) for i in used]
    signatures = [media._signature(path) for path in paths]
    width = min((s[2] for s in signatures), default=256)
    height = min((s[3] for s in signatures), default=144)
    # Consistent SDR conversion is performed by PyAV when decoding each source, including mixed source encodings.
    picks = {identity: [] for identity in used}
    for row in rows:
        for source in row['sources']:
            fps = entries[source['id']]['video'].get('fps') or FPS
            picks[source['id']].extend(int((source['first']+f)*fps/FPS) for f in range(row['outputEnd']-row['outputStart']))
    streams = {identity: stacks._frames(os.path.join(folder, entries[identity]['video']['file']), frames,
                                       (width, height), 'rgb24') for identity, frames in picks.items()}
    source_sound=None
    if source and source.get('audio'):
        from safetensors import safe_open
        with safe_open(os.path.join(folder,source['audio']),framework='pt') as stream:
            source_sound=(stream.get_tensor('waveform'),int(stream.metadata()['sample_rate']))
    sound_parts = []
    for row in rows:
        count = row['outputEnd']-row['outputStart']
        entry = entries.get(row['sound'])
        wave = store.load_waveform(folder, entry) if entry and entry.get('audio_sample_rate') else None
        p = parsed.placements.get(row['sound'])
        first = row['start']-p['start'] if p else 0
        carried = entry.get('context_frames', 0) if entry else 0
        rate=entry.get('audio_sample_rate') if wave is not None else None
        if row['sound']=='source' and source_sound:
            wave,rate=source_sound;first=row['start']
        sound_parts.append((first+carried+count, first+carried, wave, rate))
    sound = media.assemble_audio(sound_parts)
    soundtrack = audio_tracks.marked(parsed, manifest.get('reference_audio'))
    if soundtrack:
        coverage = [dict(frames=row['outputEnd']-row['outputStart'], coverage=[] if row['bridgeId'] else
                         [dict(box=s['id'], first=s['first'], frames=row['outputEnd']-row['outputStart']) for s in row['sources'][:1]]) for row in rows]
        sound = audio_tracks.soundtrack_audio(soundtrack, coverage)
    filename = f'tracks@{key}.mp4'
    path = os.path.join(folder, filename)
    temporary = path+f'.{threading.get_ident()}.tmp.mp4'
    try:
        with av.open(temporary, mode='w') as container:
            video = media._add_video_stream(container, Fraction(FPS), width, height, crf, 'sRGB', 'H.264')
            audio = media._add_audio_stream(container, *sound) if sound is not None else None
            for row in rows:
                slate = None
                if row.get('missing'):
                    slate = Image.new('RGB', (width,height), '#252933')
                    ImageDraw.Draw(slate).text((12,12), f'Missing clip {row["missing"]}', fill='white')
                for _ in range(row['outputEnd']-row['outputStart']):
                    picture = np.asarray(slate) if slate is not None else np.zeros((height,width,3), dtype=np.uint8)
                    if row['sources']:
                        picture = sum(next(streams[s['id']]).astype(np.float32)*s['weight'] for s in row['sources'])
                    frame = av.VideoFrame.from_ndarray(np.clip(np.rint(picture),0,255).astype(np.uint8),format='rgb24')
                    container.mux(video.encode(frame))
            container.mux(video.encode(None))
            if audio is not None: media._mux_audio(container,audio,*sound)
        os.replace(temporary,path)
    finally:
        for stream in streams.values(): stream.close()
        if os.path.exists(temporary): os.remove(temporary)
    frames = rows[-1]['outputEnd']
    clock = [[s['outputStart'], min(s['outputEnd'],frames)-s['outputStart'],s['start'],0 if s['bridgeId'] else 1]
             for s in tracks.output_spans(tracks.document(parsed)) if s['outputStart']<frames]
    return dict(file=filename,sources=key,frames=frames,fps=FPS,clock=clock,mode=mode,note=note), note


def ensure(folder, name, parsed, manifest, crf, mode='full', make=True):
    """Nonblocking status/save integration, with immutable content-addressed movie files."""
    key = fingerprint(folder, parsed, manifest, mode, crf)
    record_key = 'track_'+mode
    saved = manifest.get(record_key)
    if saved and saved.get('sources') == key and os.path.isfile(os.path.join(folder,saved['file'])):
        return saved,False,saved.get('note','')
    job_key = (os.path.normcase(folder),mode)
    with _LOCK:
        job = _JOBS.get(job_key) or {}
        if job.get('thread') and job['thread'].is_alive(): return None,True,''
        if job.get('key') == key and job.get('error'): return None,False,job['error']
        if not make: return None,False,''
        snapshot = copy.deepcopy(manifest)

        def run():
            error = ''
            try:
                record,error = build(folder,name,parsed,snapshot,crf,mode)
                if record:
                    from .nodes import SEQUENCE_LOCK
                    with SEQUENCE_LOCK:
                        latest = store.load_manifest(folder)
                        if fingerprint(folder,parsed,latest,mode,crf)==key:
                            latest[record_key]=record;store.write_manifest(folder,latest)
                            discard_superseded(folder,latest)
            except Exception as failure:
                error = f'Track output could not be built: {failure}'
            with _LOCK: _JOBS[job_key] = dict(key=key,error=error)
            from .nodes import _notify
            _notify(name)

        thread = threading.Thread(target=run,name='h3c-tracks-output',daemon=True)
        _JOBS[job_key] = dict(key=key,thread=thread)
        thread.start()
        return None,True,''


def discard_superseded(folder, manifest):
    """Outputs are named by content, so every edit writes a new file; only the recorded ones are kept. A file a
    player still holds (Windows) stays until a later edit."""
    kept = {record['file'] for key,record in manifest.items()
            if key.startswith('track_') and isinstance(record,dict) and record.get('file')}
    for file in os.listdir(folder):
        if file.startswith('tracks@') and file.endswith('.mp4') and file not in kept:
            try: os.remove(os.path.join(folder,file))
            except OSError: pass


def restacker(parsed):
    # Existing save hooks pass this view into rebuild_full_video, which delegates to ensure.
    return lambda folder,manifest,crf,make=True: {**manifest,'_track_timeline':parsed}
