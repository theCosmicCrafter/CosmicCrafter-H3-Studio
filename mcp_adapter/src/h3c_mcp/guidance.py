"""Host-authoritative manifests; never substitute the adapter checkout's skills."""
from urllib.parse import urlencode

from .transport import StudioError


class Guidance:
    def __init__(self, client):
        self.client, self.current = client, None

    def catalog(self):
        try:
            catalog = self.client.json('/h3c/agent/catalog')
        except StudioError as error:
            if error.status == 404:
                raise StudioError('Update the Studio host: the agent catalog API is missing.', code='host_upgrade_required') from error
            raise
        if catalog.get('agent_api_version') != 1:
            raise StudioError('Update the Studio host/adapter to compatible agent API v1 versions.', code='host_upgrade_required')
        try:
            from .skills import Skill, SkillFile
            inventory = {entry['uri']: SkillFile.model_validate(entry) for entry in catalog['resources']}
            if len(inventory) != len(catalog['resources']):
                raise ValueError('Duplicate resource')
            names = set()
            for item in catalog['skills']:
                skill = Skill.model_validate(item)
                if skill.uri in names:
                    raise ValueError('Duplicate skill')
                names.add(skill.uri)
                for entry in skill.resources:
                    if inventory.get(entry.uri) != entry:
                        raise ValueError('Skill file missing from resource inventory')
        except (ValueError, KeyError, TypeError) as error:
            raise StudioError('Host agent catalog is incomplete or invalid.', code='invalid_catalog') from error
        self.current = catalog
        return catalog

    def get_skill(self, uri):
        for entry in self.catalog()['skills']:
            if entry['uri'] == uri:
                return entry
        raise StudioError('Unknown host skill URI.', code='unknown_skill')

    def read(self, uri):
        catalog = self.current or self.catalog()
        entry = next((entry for entry in catalog['resources'] if entry['uri'] == uri), None)
        if entry is None:
            raise StudioError('Unknown host guidance URI.', code='unknown_resource')
        try:
            raw = self.client.bytes('/h3c/agent/resource?' + urlencode({'uri': uri, 'digest': entry['digest']}),
                                    expected_digest=entry['digest'], expected_size=entry['size'])
        except StudioError as error:
            if error.code == 'resource_changed':
                self.current = None
            raise
        return raw, entry.get('mime_type', 'application/octet-stream')
