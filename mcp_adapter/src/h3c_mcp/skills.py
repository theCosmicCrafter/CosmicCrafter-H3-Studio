"""SEP-2640 bindings through the released SDK's public Extension interface."""
import re
from typing import Any

import anyio
from mcp.server.extension import Extension, MethodBinding
from mcp.shared.exceptions import MCPError
from mcp_types import CacheableResult, PaginatedRequestParams, RequestParams
from mcp_types.version import MODERN_PROTOCOL_VERSIONS
from pydantic import BaseModel, Field, StrictInt, ValidationError, model_validator

from .transport import StudioError


class SkillFile(BaseModel):
    uri: str
    digest: str = Field(pattern=r'^sha256:[a-f0-9]{64}$')
    size: StrictInt = Field(ge=0)


class Skill(BaseModel):
    uri: str
    frontmatter: dict[str, Any]
    resources: list[SkillFile]

    @model_validator(mode='after')
    def manifest(self):
        name, description = self.frontmatter.get('name'), self.frontmatter.get('description')
        if (not isinstance(name, str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', name) or len(name) > 64
                or not isinstance(description, str) or not 1 <= len(description) <= 1024
                or self.uri != f'skill://{name}/SKILL.md'):
            raise ValueError('Skill URI/frontmatter must match the host skill directory')
        uris = [entry.uri for entry in self.resources]
        prefix = self.uri.removesuffix('SKILL.md')
        if (self.uri not in uris or len(set(uris)) != len(uris) or len(uris) > 512
                or sum(item.size for item in self.resources) > 16 * 1024**2
                or any(not uri.startswith(prefix) or any(part in ('.', '..') for part in uri[len(prefix):].split('/')) for uri in uris)):
            raise ValueError('Skill file manifest is incomplete or invalid')
        return self


class GetSkillParams(RequestParams):
    uri: str


class ListSkillResult(CacheableResult):
    skills: list[Skill]


class GetSkillResult(CacheableResult):
    skill: Skill


class SkillsExtension(Extension):
    identifier = 'io.modelcontextprotocol/skills'

    def __init__(self, guidance):
        self.guidance = guidance

    def methods(self):
        return (MethodBinding('skills/list', PaginatedRequestParams, self.list_skills),
                MethodBinding('skills/get', GetSkillParams, self.get_skill))

    @staticmethod
    def result(result, context):
        if context.protocol_version in MODERN_PROTOCOL_VERSIONS:
            return result
        return result.model_dump(by_alias=True, exclude={'ttl_ms', 'cache_scope'})

    async def list_skills(self, context, params):
        if params.cursor is not None:
            raise MCPError(-32602, 'Unknown skill catalog cursor')
        try:
            catalog = await anyio.to_thread.run_sync(self.guidance.catalog)
            result = ListSkillResult(skills=[Skill.model_validate(entry) for entry in catalog['skills']])
            return self.result(result, context)
        except (StudioError, ValidationError, KeyError) as error:
            raise MCPError(-32603, 'Host skill catalog is unavailable or invalid') from error

    async def get_skill(self, context, params):
        try:
            entry = await anyio.to_thread.run_sync(self.guidance.get_skill, params.uri)
            return self.result(GetSkillResult(skill=Skill.model_validate(entry)), context)
        except StudioError as error:
            raise MCPError(-32602 if error.code == 'unknown_skill' else -32603, str(error)) from error
        except (ValidationError, KeyError) as error:
            raise MCPError(-32603, 'Host returned an invalid skill manifest') from error
