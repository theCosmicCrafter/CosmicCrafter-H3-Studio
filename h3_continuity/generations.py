"""Same-installation generation interchange. State transfers; generator graphs do not."""
import copy,hashlib,json,os,re,shutil,uuid
import datetime
from pathlib import Path
from . import nodes,store,stills,studio_pictures,timeline,refmods

FORMAT='h3-generation'


def _request_name(body):
    name = body.get('name')
    if name is None and body.get('workflow'):
        from . import timeline_prepare
        graph = body['workflow']
        inputs = graph.get(str(body.get('timeline_node')), {}).get('inputs', {})
        name, _ = timeline_prepare.scalar(inputs.get('name'), graph, 'name')
    return store.validate_name(name or '')


def start(body):
    """Start an empty render sequence, retaining previous sequence files and authored snapshots."""
    from . import takes
    name = _request_name(body)
    timeline.parse(body['timeline'])
    folder = _folder(name)
    with nodes.SEQUENCE_LOCK:
        if takes.busy(folder):
            raise ValueError('Finish or cancel rendering before starting a new generation.')
        manifest = store.load_manifest(folder)
        previous = dict(name=name, created=datetime.datetime.now().isoformat(timespec='seconds'),
                        timeline=body['timeline'], settings=copy.deepcopy(body.get('settings') or {}))
        fresh = name[:40].rstrip(' .') + '_g' + uuid.uuid4().hex[:8]
        destination = _folder(fresh)
        os.makedirs(destination, exist_ok=False)
        empty = store.empty_manifest(fresh)
        empty['generation_history'] = [*copy.deepcopy(manifest.get('generation_history', [])), previous]
        store.write_manifest(destination, empty)
        return dict(ok=True, name=fresh)


def history(body):
    """Playable outputs of earlier generations, including partially rendered ones."""
    folder = _folder(_request_name(body))
    with nodes.SEQUENCE_LOCK:
        manifest = store.load_manifest(folder)
        found = []
        for saved in reversed(manifest.get('generation_history', [])):
            name = saved['name']
            directory = _folder(name)
            old = store.load_manifest(directory)

            def view(filename):
                if not filename or filename != os.path.basename(filename) or not os.path.isfile(os.path.join(directory, filename)):
                    return None
                return dict(filename=filename, subfolder='h3_sequences/' + name, type='output')

            video = next((file for key in ('full_video', 'preview_video', 'partial_video')
                          if (file := view((old.get(key) or {}).get('file')))), None)
            parsed = timeline.parse(saved['timeline'])
            store.align(old, [box.id for box in parsed.boxes])
            clips = [dict(id=store.box_of(entry), number=entry['index'], file=file)
                     for entry in store.placed(old, len(parsed.boxes))
                     if (file := view((entry.get('video') or {}).get('file')))]
            found.append(dict(name=name, created=saved['created'], video=video, clips=clips))
        return dict(ok=True, generations=found)
def _hash(path):
    digest=hashlib.sha256()
    with open(path,'rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()

def _descriptors(value):
    if isinstance(value,dict):
        if {'filename','subfolder','type'}<=value.keys():yield value
        else:
            for child in value.values():yield from _descriptors(child)
    elif isinstance(value,list):
        for child in value:yield from _descriptors(child)

def _values(line,story,references):
    values=[line,story,references]
    if isinstance(story.get('idea_images'),str):
        try:values.append(json.loads(story['idea_images']))
        except ValueError:raise ValueError('Story idea images are not valid JSON')
    return values

def _refmod_assets(line):
    identities=line.get('refmods',[])
    if not identities:return []
    pack,_=refmods.backend();result=[]
    for ref in identities:
        prefix,meta=refmods.metadata(ref,pack);files=[]
        for suffix in ('.safetensors','.json'):
            path=prefix+suffix
            if os.path.isfile(path):files.append({'suffix':suffix,'sha256':_hash(path),'size':os.path.getsize(path)})
        if not any(item['suffix']=='.safetensors' for item in files):raise ValueError('Generation RefMod weights are missing: '+ref['name'])
        result.append({'identity':copy.deepcopy(ref),'metadata':copy.deepcopy(meta),'files':files})
    return result

def _key(file):return tuple(file.get(key,'') for key in ('filename','subfolder','type'))

def _asset(file):
    timeline.audio_file(file)
    path=studio_pictures.path(file)
    if not path:raise ValueError('Generation media is missing: '+file['filename'])
    return {'file':copy.deepcopy(file),'sha256':_hash(path),'size':os.path.getsize(path)}

def _root():return os.path.realpath(nodes.sequences_root())
def _folder(name):return stills._contained(_root(),store.validate_name(name))
def _relative(folder,relative):
    if not isinstance(relative,str) or not relative or '\\' in relative or relative.startswith('/') or any(p in ('..','.') for p in relative.split('/')):
        raise ValueError('Generation take path must stay inside its sequence')
    return stills._contained(folder,*relative.split('/'))

def _settled(line):
    value=copy.deepcopy(json.loads(line))
    value['still_requests']=[receipt for receipt in value.get('still_requests',[]) if receipt.get('state')=='complete']
    for receipt in value['still_requests']:
        receipt['historical']=True
        receipt.pop('pending',None);receipt.pop('job',None)
    preparation=value.get('reference_preparation')
    if preparation is not None:
        preparation.pop('batch',None)
        preparation['requests']=[dict(receipt,historical=True) for receipt in preparation.get('requests',[])
                                 if receipt.get('state')=='complete']
        for receipt in preparation['requests']:
            receipt.pop('pending',None);receipt.pop('job',None)
    for box in value.get('boxes',[]):
        for preview in box.get('previews',[]):preview.pop('pending',None);preview.pop('job',None)
    parsed = timeline.parse(json.dumps(value))
    for box, checked in zip(value.get('boxes', []), parsed.boxes):
        if 'previews' in box:
            box['previews'] = checked.previews
    return value

def export_generation(body):
    if body.get('writing'):raise ValueError('Wait for Story writing before exporting a generation')
    name=store.validate_name(body['name']);folder=_folder(name);line=_settled(body['timeline'])
    story=copy.deepcopy(body.get('story') or {});references=copy.deepcopy(body.get('references') or {})
    for slot,ref in references.items():
        if not isinstance(ref,dict) or not ref.get('file'):
            raise ValueError(f'Generation has computed reference {slot}; render and import its pixels or media before export')
        line.setdefault('reference_replacements',{})[slot]={'file':copy.deepcopy(ref['file'])}
    assets={}
    values=_values(line,story,references)
    mods=_refmod_assets(line)
    for value in values:
        for file in _descriptors(value):assets[_key(file)]=_asset(file)
    files=[]
    # The native sequence lock protects manifests and take moves while a settled snapshot is pinned.
    with nodes.SEQUENCE_LOCK:
        manifest=store.load_manifest(folder)
        if os.path.isdir(folder):
            for path in sorted(Path(folder).rglob('*')):
                if not path.is_file() or path.name.endswith('.tmp') or path.name=='.generation_import.json':continue
                relative=path.relative_to(folder).as_posix();contained=_relative(folder,relative)
                files.append({'relative':relative,'sha256':_hash(contained),'size':path.stat().st_size})
    return {'format':FORMAT,'version':1,'story':story,'timeline':json.dumps(line,ensure_ascii=False),
            'references':references,'assets':list(assets.values()),'refmods':mods,'takes':{'sequence':name,'manifest':manifest,'files':files},
            'origin':copy.deepcopy(body.get('origin') or {}),'exported_at':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()}

def _schema(archive):
    if not isinstance(archive,dict) or archive.get('format')!=FORMAT or archive.get('version')!=1:
        raise ValueError('Choose a generation export version 1')
    if not isinstance(archive.get('story'),dict) or not isinstance(archive.get('assets'),list) or not isinstance(archive.get('takes'),dict):
        raise ValueError('Generation state or assets are invalid')
    timeline.parse(archive.get('timeline','{}'))
    store.validate_name(archive['takes']['sequence'])
    if not isinstance(archive['takes'].get('files'),list) or not isinstance(archive['takes'].get('manifest'),dict):
        raise ValueError('Generation takes are invalid')

def preflight_generation(archive):
    _schema(archive);assets={};relative=set();folder=_folder(archive['takes']['sequence'])
    for item in archive['assets']:
        current=_asset(item['file'])
        if current['sha256']!=item.get('sha256') or current['size']!=item.get('size'):
            raise ValueError('Generation media checksum changed: '+item['file']['filename'])
        if _key(item['file']) in assets:raise ValueError('Generation has duplicate assets')
        assets[_key(item['file'])]=item
    line=json.loads(archive['timeline'])
    if _refmod_assets(line)!=archive.get('refmods',[]):raise ValueError('Generation RefMod identity, metadata or bytes changed')
    for value in _values(line,archive['story'],archive.get('references',{})):
        for file in _descriptors(value):
            if _key(file) not in assets:raise ValueError('Generation media has no verified asset: '+file['filename'])
    for item in archive['takes']['files']:
        path=_relative(folder,item['relative'])
        if item['relative'] in relative:raise ValueError('Generation has duplicate take files')
        relative.add(item['relative'])
        if not os.path.isfile(path) or _hash(path)!=item.get('sha256') or os.path.getsize(path)!=item.get('size'):
            raise ValueError('Generation take checksum changed or file is missing: '+item['relative'])
    declared=archive['takes']['manifest']
    if store.load_manifest(folder)!=declared:raise ValueError('Generation manifest declaration differs from verified native manifest')
    for entry in [*declared.get('segments',[]),*declared.get('layers',[])]:
        for filename in [entry.get('stem','')+'.safetensors',(entry.get('video') or {}).get('file')]:
            if filename and filename not in relative:raise ValueError('Generation take is missing required sidecar: '+filename)
    return {'ok':True,'assets':len(assets),'take_files':len(relative)}

def _remap(value,old,new):
    if isinstance(value,list):return [_remap(child,old,new) for child in value]
    if not isinstance(value,dict):return value
    result={key:_remap(child,old,new) for key,child in value.items()}
    prefix='h3_sequences/'+old
    if result.get('type')=='output' and isinstance(result.get('subfolder'),str) and (result['subfolder']==prefix or result['subfolder'].startswith(prefix+'/')):
        result['subfolder']='h3_sequences/'+new+result['subfolder'][len(prefix):]
    return result

def _write_receipt(receipt,record):
    temporary=receipt.with_suffix('.json.tmp');temporary.write_text(json.dumps(record),encoding='utf-8');os.replace(temporary,receipt)

def _retarget(line, story, renderer):
    if renderer is None:
        return
    from . import story_bible_write
    bible=line.get('bible')
    if not isinstance(bible,dict):
        return
    ids=[box['id'] for box in line.get('boxes',[])]
    try:state=json.loads(story.get('state','{}'))
    except (ValueError,TypeError):state={}
    for index,box in enumerate(line.get('boxes',[])):
        source=box.get('source')
        if not isinstance(source,dict):continue
        old=story_bible_write.compiled(box,bible,ids,index)
        if old is None or old[0]!=box.get('prompt'):continue # Keep user-edited prose.
        source['frame']['renderer']=renderer
        text,details=story_bible_write.compile_source(source,bible,ids,index)
        box['prompt']=text;box['cast']=details.get('cast',{})
        if isinstance(state,dict) and isinstance(state.get('written'),dict) and state['written'].get(box['id'])==old[0]:
            state['written'][box['id']]=text
    if isinstance(state,dict) and 'state' in story:story['state']=json.dumps(state,ensure_ascii=False)


def import_generation(archive,request_id,renderer=None):
    _schema(archive)
    if renderer not in (None,'image','video'):raise ValueError('Generation renderer must be image or video')
    try:key=uuid.UUID(request_id).hex
    except (ValueError,TypeError,AttributeError):raise ValueError('Generation import needs a UUID request_id')
    name='generation_'+key;folder=_folder(name);receipt=Path(folder,'.generation_import.json')
    digest=hashlib.sha256(json.dumps({'archive':archive,'renderer':renderer} if renderer else archive,sort_keys=True).encode()).hexdigest()
    with nodes.SEQUENCE_LOCK:
        if receipt.exists():
            record=json.loads(receipt.read_text(encoding='utf-8'))
            if record['archive_sha256']!=digest:raise ValueError('Generation request_id already belongs to another archive')
            if not record.get('committed',False):
                preflight_generation(archive)
                for item in archive['takes']['files']:
                    if item['relative']==store.MANIFEST:continue
                    if _hash(_relative(folder,item['relative']))!=item['sha256']:raise ValueError('Generation recovery snapshot changed')
                store.write_manifest(folder,record['manifest'])
                record['committed']=True;_write_receipt(receipt,record)
            return copy.deepcopy(record['result'])
        preflight_generation(archive)
        if Path(folder,store.MANIFEST).exists():raise ValueError('Generation destination already exists without an import receipt')
        source=_folder(archive['takes']['sequence'])
        os.makedirs(folder,exist_ok=True)
        for item in archive['takes']['files']:
            if item['relative']==store.MANIFEST:continue
            before=_relative(source,item['relative']);after=_relative(folder,item['relative']);os.makedirs(os.path.dirname(after),exist_ok=True)
            shutil.copy2(before,after) # No hardlinks: takes and sidecars are mutable native storage.
            if _hash(before)!=item['sha256'] or _hash(after)!=item['sha256']:raise ValueError('Generation source changed while copying')
        # Recheck every source immediately before committing the destination snapshot.
        preflight_generation(archive)
        line=_remap(_settled(archive['timeline']),archive['takes']['sequence'],name)
        for box in line.get('boxes',[]):
            for preview in box.get('previews',[]):
                pin=preview.get('still_source')
                if isinstance(pin,dict) and pin.get('sequence')==archive['takes']['sequence']:pin['sequence']=name
        story=_remap(archive['story'],archive['takes']['sequence'],name)
        _retarget(line,story,renderer)
        result={'ok':True,'sequence':name,'story':story,
                'timeline':json.dumps(line,ensure_ascii=False),'origin':copy.deepcopy(archive.get('origin') or {}),'descriptor_remapping':[]}
        manifest=copy.deepcopy(archive['takes']['manifest']);manifest['name']=name
        record={'archive_sha256':digest,'result':result,'manifest':manifest,'committed':False}
        _write_receipt(receipt,record)
        store.write_manifest(folder,manifest)
        record['committed']=True;_write_receipt(receipt,record)
        return result
