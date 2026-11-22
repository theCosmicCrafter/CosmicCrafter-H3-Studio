"""Names the user gave to groups of saved stories. A group is the saved stories sharing one title; the browser works
out its key, so this module keeps the key opaque and only stores the name beside it."""

from . import saved_state

MAX_KEY = 300
MAX_NAME = 120
_GRAPH = 'library'
_NODE = 'names'


def read():
    value = saved_state.read('names', _GRAPH, _NODE)['value']
    names = value.get('names') if isinstance(value, dict) and value.get('format') == 'h3-names' else None
    return {key: name for key, name in (names or {}).items() if isinstance(key, str) and isinstance(name, str) and name}


def rename(key, name):
    """Give a group a name, or clear it with an empty name. Returns all names."""
    if not isinstance(key, str) or not key.strip() or len(key) > MAX_KEY:
        raise ValueError('Choose a saved story to rename.')
    if not isinstance(name, str):
        raise ValueError('A story name must be text.')
    name = ' '.join(name.split())
    if len(name) > MAX_NAME:
        raise ValueError(f'A story name can have at most {MAX_NAME} characters.')
    with saved_state.LOCK:
        names = read()
        if name:
            names[key] = name
        else:
            names.pop(key, None)
        saved_state.write('names', _GRAPH, _NODE, {'format': 'h3-names', 'names': names})
        return names
