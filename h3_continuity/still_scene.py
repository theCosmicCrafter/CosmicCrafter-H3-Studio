"""Accepted scene anchors and preceding action-state pixels. Independent of the generator."""
import copy,re

def validate(value):
    if not isinstance(value,dict) or value.get('version')!=1 or not isinstance(value.get('anchors'),list):
        raise ValueError('Timeline scene anchor contract is invalid')
    scenes=set()
    from . import timeline
    for anchor in value['anchors']:
        if (not isinstance(anchor,dict) or not isinstance(anchor.get('box'),str) or not isinstance(anchor.get('scene'),str)
            or not re.fullmatch('[a-f0-9]{64}',str(anchor.get('sha256',''))) or type(anchor.get('revision')) is not int
            or anchor['revision']<1 or not isinstance(anchor.get('target'),dict) or anchor['target'].get('kind') not in ('first','last','shot')):
            raise ValueError('Timeline scene anchor identity or hash is invalid')
        timeline.preview_file(anchor.get('file'))
        if anchor['scene'] in scenes:raise ValueError('Timeline has duplicate scene anchors')
        scenes.add(anchor['scene'])
    return value

def start(parsed,index):
    while index>0 and not parsed.boxes[index].new_scene:index-=1
    return parsed.boxes[index].id

def references(body,parsed,index,frame):
    from . import stills,timeline as rules
    refs=[];scene=start(parsed,index)
    anchors=(parsed.continuity or {}).get('anchors',[])
    anchor=next((a for a in anchors if a['scene']==scene),None)
    if anchor:
        at=next((i for i,box in enumerate(parsed.boxes) if box.id==anchor['box']),None)
        context=int((body.get('settings') or {}).get('context_frames') or 39)
        accepted=at is not None and any(item.get('target')==anchor['target'] and item.get('guide')==anchor['file']
                                     for item in rules.resolved_previews(parsed,at,context))
        if not accepted:raise ValueError('Accepted scene anchor target changed or was removed')
        pinned=stills.pin_image(anchor['file'])
        if pinned['sha256']!=anchor['sha256']:raise ValueError('Accepted scene anchor image changed')
        refs.append(dict(copy.deepcopy(anchor),roles=['scene anchor']))
    if body.get('source') is not None:
        from pathlib import Path
        import hashlib
        context={key:body.get(key) for key in ('name','timeline','settings','box','target')}
        resolved=stills.resolve_pin(context,body['source']);path=stills._file(resolved['folder'],resolved['entry'],True)
        refs.append({'roles':['current action state'],'pin':copy.deepcopy(body['source']),'body':context,
                     'sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest()})
    else:
        previous=stills._previous_guide(parsed,index,frame,int((body.get('settings') or {}).get('context_frames') or 39))
        if previous:refs.append(dict(stills.pin_image(previous['file']),roles=['current action state'],box=previous['box'],target=previous['target']))
    return refs
