"""Exact, allowlisted host guidance and skill files."""
import hashlib
import json
import mimetypes
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
ENTRY = 'h3-continuity-video'
GUIDES = ('TIMELINE-API.md', 'EXTERNAL-TIMELINE.md', 'TIMELINE-TEXT.md', 'TIMELINE-AUDIO.md',
          'TIMELINE-REFERENCES.md', 'H3-TRANSITIONS.md', 'STORY-TEMPLATES.md', 'MCP.md')


class ResourceChanged(ValueError):
    pass


def _digest(raw):
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def _descriptor(uri, raw, mime):
    return dict(uri=uri, digest=_digest(raw), size=len(raw), mime_type=mime)


def _inventory():
    files, skills = {}, []
    pack = (ROOT / 'skills').resolve()
    if not pack.is_relative_to(ROOT.resolve()):
        raise ValueError('Skill pack escapes the checkout')
    for entry in sorted(pack.glob('*/SKILL.md'), key=lambda p: (p.parent.name != ENTRY, p.parent.name)):
        directory = entry.parent
        if not directory.resolve().is_relative_to(pack):
            raise ValueError('Skill directory escapes the pack')
        raw = entry.read_bytes()
        front = re.match(r'\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)', raw.decode('utf-8'), re.S)
        metadata = yaml.safe_load(front.group(1)) if front else None
        if (not isinstance(metadata, dict) or metadata.get('name') != directory.name
                or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', directory.name)
                or len(directory.name) > 64 or not isinstance(metadata.get('description'), str)
                or not 1 <= len(metadata['description']) <= 1024):
            raise ValueError(f'Invalid skill name/frontmatter: {directory.name}')
        json.dumps(metadata, allow_nan=False)
        manifest = []
        for path in sorted(directory.rglob('*')):
            if not path.resolve().is_relative_to(directory.resolve()):
                raise ValueError('Skill resource escapes its directory')
            if path.is_dir() and (path.is_symlink() or getattr(path.lstat(), 'st_file_attributes', 0) & 0x400):
                raise ValueError('Linked skill directories are not supported')
            if not path.is_file():
                continue
            uri = f'skill://{directory.name}/{path.relative_to(directory).as_posix()}'
            content = path.read_bytes()
            mime = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
            files[uri] = (content, mime)
            manifest.append(_descriptor(uri, content, mime))
        if len(manifest) > 512 or sum(item['size'] for item in manifest) > 16 * 1024**2:
            raise ValueError('Skill exceeds the MCP manifest limits')
        skills.append(dict(uri=f'skill://{directory.name}/SKILL.md', frontmatter=metadata, resources=manifest))
    for folder, names in (('docs', GUIDES), ('examples', ('timeline_api.py', 'external_timeline.py'))):
        for name in names:
            path = ROOT / folder / name
            if path.is_file():
                if not path.resolve().is_relative_to(ROOT.resolve()):
                    raise ValueError('Guidance resource escapes the checkout')
                files[f'h3c://{folder}/{name}'] = (path.read_bytes(), mimetypes.guess_type(name)[0] or 'text/plain')
    if (ROOT / 'h3_continuity' / 'timeline_prepare.py').is_file():
        from ..timeline_prepare import instructions
        files['h3c://instructions'] = (json.dumps(instructions(), ensure_ascii=False, allow_nan=False).encode(), 'application/json')
    return files, skills


def catalog():
    files, skills = _inventory()
    coverage = json.loads(Path(__file__).with_name('coverage.json').read_text(encoding='utf-8'))
    result = dict(agent_api_version=1, skills=skills, resources=[_descriptor(uri, raw, mime)
                  for uri, (raw, mime) in sorted(files.items())], coverage=coverage)
    result['catalog_sha256'] = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    return result


def read(uri, digest=None):
    files, _ = _inventory()
    if uri not in files:
        raise ValueError('Unknown agent resource URI')
    raw, mime = files[uri]
    if digest is not None and digest != _digest(raw):
        raise ResourceChanged('Agent resource changed; refresh the catalog')
    return raw, mime
