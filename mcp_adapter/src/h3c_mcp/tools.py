"""Typed domain operations. Routing never comes from a caller-supplied URL."""
from typing import Any, Literal
from urllib.parse import quote, urlencode

from pydantic import BaseModel, StrictInt, model_validator

from .transport import StudioError, encoded, parse

PREFIX = '/h3c/api/v1'


class Target(BaseModel):
    kind: Literal['managed', 'native']
    id: str | None = None
    graph: str | None = None
    timeline_node: str | None = None
    story_node: str | None = None

    @model_validator(mode='after')
    def identity(self):
        if self.kind == 'managed' and not self.id:
            raise ValueError('Managed target needs its project id')
        if self.kind == 'native' and (not self.graph or not self.timeline_node):
            raise ValueError('Native target needs graph and timeline_node')
        return self

    def wire(self):
        return self.model_dump(exclude_none=True)


class JobHandle(BaseModel):
    kind: Literal['managed', 'video', 'story', 'still', 'reference']
    id: str
    target: Target | None = None
    request_key: str | None = None


def _object(text):
    try:
        value = parse(text)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, UnicodeError) as error:
        raise StudioError('Supply a finite JSON object string.', code='invalid_document') from error


def _project_path(target, suffix=''):
    if target.kind != 'managed':
        raise StudioError('Use the native saved-workflow operation for this target.', code='unsupported_target_operation')
    return PREFIX + '/projects/' + quote(target.id, safe='') + suffix


def _managed_revision(revision):
    if set(revision) != {'project'} or type(revision['project']) is not int:
        raise StudioError('Use the current managed project revision.', code='revision_conflict')
    return revision['project']


def managed_view(project):
    fields = {key: project[key] for key in ('name', 'timeline', 'settings', 'assets', 'consumer', 'semantic_boxes') if key in project}
    return dict(target={'kind': 'managed', 'id': project['id']}, revision={'project': project['revision']},
                document_json=encoded(fields).decode(), inspection_json=encoded(project.get('inspection', {})).decode(),
                status_json=encoded(project.get('status', {})).decode(),
                execution_ready=True, profile=project.get('profile'), profile_sha256=project.get('profile_sha256'),
                sequence=project.get('sequence'), active_job=project.get('active_job'))


class StudioTools:
    def __init__(self, client, guidance, state_dir=None):
        self.client, self.guidance, self.state_dir = client, guidance, state_dir
        self.jobs = None

    def _post(self, path, body, key=None):
        return self.client.json(path, method='POST', body=body, key=key)

    def _context(self, target, revision, operation):
        if target.kind != 'native':
            raise StudioError('This operation is native-only; deliberately export/fork first if needed.', code='unsupported_target_operation')
        return self._post('/h3c/agent/projects/context', dict(target=target.wire(), expected_revision=revision, operation=operation))

    def h3_capabilities(self) -> dict[str, Any]:
        """Inspect this host's readiness/profiles, skill resources and capability coverage before authoring."""
        return {**self.client.json(PREFIX + '/capabilities'), 'agent_api_version': 1, 'coverage': self.guidance.catalog().get('coverage', {})}

    def h3_read_guidance(self, uri: str = 'skill://h3-continuity-video/SKILL.md') -> dict[str, Any]:
        """Read current host guidance as ordinary context. This does not activate a client skill."""
        raw, mime = self.guidance.read(uri)
        return dict(uri=uri, mime_type=mime, text=raw.decode('utf-8'))

    def h3_list_projects(self, kind: Literal['managed', 'native'] = 'managed', cursor: str | None = None, limit: int = 50) -> dict[str, Any]:
        """List one saved-project kind at a time; keep its pagination cursor with that kind."""
        query = urlencode({'limit': limit, **({'cursor': cursor} if cursor is not None else {})})
        return self.client.json((PREFIX + '/projects' if kind == 'managed' else '/h3c/agent/projects') + '?' + query)

    def h3_get_project(self, target: Target) -> dict[str, Any]:
        """Read saved authored data and revisions. Edit document_json to preserve uint64 seeds and opaque fields."""
        if target.kind == 'managed':
            return managed_view(self.client.json(_project_path(target)))
        return self._post('/h3c/agent/projects/read', {'target': target.wire()})

    def h3_create_project(self, document_json: str, request_key: str) -> dict[str, Any]:
        """Create a managed project with a ready profile and a saved idempotency key; never guess a profile."""
        return managed_view(self._post(PREFIX + '/projects', _object(document_json), request_key))

    def h3_save_project(self, target: Target, expected_revision: dict[str, StrictInt], document_json: str) -> dict[str, Any]:
        """Replace saved authored data under its current revision. Conflicts require rereading; no automatic merge."""
        document = _object(document_json)
        if target.kind == 'managed':
            project = self.client.json(_project_path(target), method='PUT', body={**document, 'expected_revision': _managed_revision(expected_revision)})
            return managed_view(project)
        return self._post('/h3c/agent/projects/save', dict(target=target.wire(), expected_revision=expected_revision, document=document))

    def h3_register_workflow(self, target: Target, workflow_json: str, expected_revision: dict[str, StrictInt] | None = None) -> dict[str, Any]:
        """Register an explicit native {ui,api} snapshot; existing saved targets require their current revision."""
        if target.kind != 'native':
            raise StudioError('Managed profiles cannot be replaced with native snapshots.', code='unsupported_target_operation')
        workflow = _object(workflow_json)
        return self._post('/h3c/agent/projects/register', dict(target=target.wire(), workflow_ui=workflow.get('ui'),
                          workflow_api=workflow.get('api'), expected_revision=expected_revision))

    def h3_export_workflow(self, target: Target, mode: Literal['fork', 'attached'] = 'fork') -> dict[str, Any]:
        """Export an editable managed workflow. Fork is deliberate and does not run or change the source project."""
        workflow = self.client.json(_project_path(target, '/workflow?' + urlencode({'mode': mode})))
        return dict(workflow_json=encoded(workflow).decode())

    def h3_upload_asset(self, path: str, kind: Literal['picture', 'guide', 'audio', 'video', 'whisper']) -> dict[str, Any]:
        """Upload original bytes from an allowed adapter-local path, returning host asset identity and hash."""
        return self.client.upload(path, kind)

    def h3_download_artifact(self, artifact_id: str, destination: str) -> dict[str, Any]:
        """Download immutable managed media into an allowed local path only after hash/size verification."""
        self.client.local_path(destination)
        descriptor = self.client.json(PREFIX + '/artifacts/' + quote(artifact_id, safe=''))
        return self.client.download(descriptor, destination)

    def h3_plan_video(self, target: Target, expected_revision: dict[str, StrictInt], selection_json: str = '{"kind":"all"}') -> dict[str, Any]:
        """Inspect render dependencies/reuse before submission. Planning itself never queues a render."""
        if target.kind == 'native':
            return self._native_jobs().prepare(target, expected_revision, _object(selection_json))
        plan = self._post(_project_path(target, '/plan'), dict(expected_revision=_managed_revision(expected_revision), selection=_object(selection_json)))
        return dict(plan_sha256=plan['plan_sha256'], plan_json=encoded(plan).decode(), target=target.wire(), revision=expected_revision)

    def h3_render_video(self, target: Target, expected_revision: dict[str, StrictInt], request_key: str,
                        plan_sha256: str, selection_json: str = '{"kind":"all"}') -> dict[str, Any]:
        """Explicitly submit approved video work. Keep this request/key; uncertain replies must not cause duplicate work."""
        if target.kind == 'native':
            return self._native_jobs().submit_video(target, expected_revision, _object(selection_json), plan_sha256, request_key)
        data = self._post(_project_path(target, '/jobs'), dict(expected_revision=_managed_revision(expected_revision),
                          selection=_object(selection_json), plan_sha256=plan_sha256), request_key)
        return dict(job=dict(kind='managed', id=data['id'], target=target.wire(), request_key=request_key), data_json=encoded(data).decode(), state=data['state'])

    def _native_jobs(self):
        if self.jobs is None:
            from .jobs import NativeJobs
            self.jobs = NativeJobs(self.client, self.state_dir)
        return self.jobs

    def _domain(self, target, revision, arguments, execution=False):
        reserved = {'name', 'timeline', 'settings', 'workflow', 'graph', 'story', 'client', 'timeline_node', 'prompt_id'}
        if reserved & arguments.keys():
            raise StudioError('Project identity and saved context cannot be overridden.', code='invalid_arguments')
        if revision is None:
            raise StudioError('Read the current project revision first.', code='revision_conflict')
        context = self._context(target, revision, 'domain' if execution else 'saved')
        body = dict(name=context['name'], timeline=encoded(context['timeline']).decode(), settings=context['settings'],
                    graph=target.graph, story=target.story_node, timeline_node=target.timeline_node,
                    workflow=context['workflow'])
        return context, {**body, **arguments}

    @staticmethod
    def _answer(data):
        return {'data_json': encoded(data).decode()}

    def h3_story(self, action: Literal['write', 'rewrite', 'feedback', 'check', 'still_prompts', 'templates', 'hosts', 'bible', 'taken'],
                 target: Target, arguments_json: str = '{}', expected_revision: dict[str, StrictInt] | None = None,
                 request_key: str | None = None) -> dict[str, Any]:
        """Story proposals: write/rewrite {box?,rewrite_all?}, feedback {edit}, check {boxes?}, still_prompts {instructions?,source?};
        execution needs revision/key. Templates/hosts read configuration; bible {action:build|link|apply|status|recompile|assign,...}
        returns transformed data only. See h3c://docs/MCP.md for action contracts. Poll returned job; save proposals explicitly.
        """
        args = _object(arguments_json)
        if action == 'taken':
            handle = JobHandle.model_validate(args.get('job'))
            if handle.target != target or handle.kind != 'story':
                raise StudioError('Story acknowledgement must match its target receipt.', code='receipt_conflict')
            return self._native_jobs().acknowledge_story(handle)
        if action == 'templates':
            return self._answer(self.client.json('/h3c/story/templates'))
        if action == 'hosts':
            return self._answer(self.client.json('/h3c/story/keys'))
        if action == 'bible':
            _, body = self._domain(target, expected_revision, args)
            body['timeline'] = parse(body['timeline'])
            return self._answer(self._post('/h3c/timeline/bible', body))
        if action not in ('write', 'rewrite', 'feedback', 'check', 'still_prompts') or args.get('check_only') or 'writing_mode' in args:
            raise StudioError('Unsupported or retired Story action.', code='unsupported_action')
        return self._native_jobs().start_story(target, expected_revision, action, args, request_key)

    def h3_stills(self, action: Literal['sources', 'import', 'pin', 'prepare', 'generate', 'reference_catalog', 'reference_prepare', 'reference_generate', 'reference_approve', 'prompt_instructions'],
                  target: Target, arguments_json: str = '{}', expected_revision: dict[str, StrictInt] | None = None,
                  request_key: str | None = None) -> dict[str, Any]:
        """Still/reference actions return proposals. Sources {box,target?}; pin {file}; import {path} uploads original bytes.
        Prepare/generate {box,target,prompt,seed,recipe,...}; reference variants {asset_key,input_fingerprint,prompt,seed,recipe,...}.
        Generate needs revision/key and actually submits one candidate. reference_approve {asset_key,candidate_id,approval_revision}
        returns proposed timeline; explicitly save with the project revision. Results never silently apply to a project.
        """
        args = _object(arguments_json)
        if target.kind != 'native':
            raise StudioError('Still operations require a deliberate native workflow export/fork.', code='unsupported_target_operation')
        if action in ('generate', 'reference_generate'):
            return self._native_jobs().start_still(target, expected_revision, args, request_key, reference=action.startswith('reference'))
        routes = {'sources': '/h3c/stills/sources', 'pin': '/h3c/stills/pin', 'prepare': '/h3c/stills/prepare',
                  'reference_catalog': '/h3c/reference-assets/catalog', 'reference_prepare': '/h3c/reference-assets/prepare',
                  'reference_approve': '/h3c/reference-assets/approve', 'prompt_instructions': '/h3c/still-prompts/instructions'}
        if action == 'import':
            return self._answer(self.client.import_still(args['path']))
        if action not in routes:
            raise StudioError('Unsupported still action; replacements are disabled.', code='unsupported_action')
        _, body = self._domain(target, expected_revision, args, execution=action in ('prepare', 'reference_prepare', 'reference_catalog', 'reference_approve'))
        if action == 'reference_approve':
            body['expected_revision'] = body.pop('approval_revision')
        return self._answer(self._post(routes[action], body))

    def h3_takes(self, action: Literal['list', 'use', 'rate', 'delete_preview', 'delete_apply'], target: Target,
                 arguments_json: str = '{}', expected_revision: dict[str, StrictInt] | None = None) -> dict[str, Any]:
        """List/use takes; native rate {created,rating,tag?}; deletion {scope:take|other|unusable,take?,box?,bridge?}.
        delete_preview only counts; delete_apply explicitly removes those takes. Managed supports list {box?} and
        use {take_id,box,kind} under its project revision; native cleanup never bypasses managed ownership.
        """
        args = _object(arguments_json)
        if target.kind == 'managed':
            if action == 'list':
                return self._answer(self.client.json(_project_path(target, '/takes?' + urlencode(args))))
            if action == 'use':
                return self._answer(self._post(_project_path(target, '/takes/use'), {**args, 'expected_revision': _managed_revision(expected_revision or {})}))
            raise StudioError('Managed take cleanup/ratings are unavailable; explicitly export/fork for native work.', code='unsupported_target_operation')
        routes = {'list': '', 'use': '/use', 'rate': '/rate', 'delete_preview': '/delete', 'delete_apply': '/delete'}
        if action not in routes:
            raise StudioError('Unsupported take action.', code='unsupported_action')
        if action == 'rate' and (not isinstance(args.get('created'), str) or type(args.get('rating')) is not int
                                 or not 0 <= args['rating'] <= 5 or not isinstance(args.get('tag', ''), str)):
            raise StudioError('Rate a listed render using created, integer rating 0..5 and optional tag text.', code='invalid_arguments')
        _, body = self._domain(target, expected_revision, args)
        if action.startswith('delete_'):
            body['apply'] = action == 'delete_apply'
        return self._answer(self._post('/h3c/timeline/takes' + routes[action], body))

    def h3_library(self, action: Literal['list', 'load', 'rename', 'delete', 'checkpoint', 'restore', 'duplicate', 'generation_start', 'generation_history', 'generation_export', 'generation_preflight', 'generation_import'],
                   target: Target, arguments_json: str = '{}', expected_revision: dict[str, StrictInt] | None = None) -> dict[str, Any]:
        """Native library: list; load/delete/restore {id}; rename {key,name}; checkpoint {name} uses saved UI.
        Duplicate {title?,timeline_json?} copies the saved story and its renders into an editable story, optionally from a
        corrected Timeline (e.g. dropping requires this host cannot read), and returns the copy's target; the source is unchanged.
        Generation start/history/export use saved context; export {references?}; preflight/import {archive,request_id?}.
        Start/import/restore return a new identity; explicitly register/save it before editing. Archives verify host-local media.
        """
        if target.kind != 'native':
            raise StudioError('Library actions require a deliberate native workflow export/fork.', code='unsupported_target_operation')
        args = _object(arguments_json)
        if action in ('list', 'load'):
            return self._answer(self.client.json('/h3c/stories' + ('?' + urlencode({'id': args['id']}) if action == 'load' else '')))
        if action == 'duplicate':
            if not set(args) <= {'title', 'timeline_json'} or not target.story_node:
                raise StudioError('Duplicate a target with its story_node, using only title and timeline_json arguments.', code='invalid_arguments')
            if isinstance(args.get('timeline_json'), dict):
                args['timeline_json'] = encoded(args['timeline_json']).decode()
            context, _ = self._domain(target, expected_revision, {})
            data = self._post('/h3c/stories/duplicate', dict(graph=target.graph, story=target.story_node,
                              workflow=context['workflow']['ui'], sequence=context['name'], **args))
            copy = Target(kind='native', graph=data['graph'], timeline_node=data['timeline_node'], story_node=data['story'])
            return {'target': copy.wire(), **self._answer(data)}
        routes = {'rename': '/h3c/stories/rename', 'delete': '/h3c/stories/delete', 'checkpoint': '/h3c/stories/checkpoint',
                  'restore': '/h3c/stories/restore', **{f'generation_{a}': f'/h3c/generations/{a}' for a in ('start', 'history', 'export', 'preflight', 'import')}}
        if action not in routes:
            raise StudioError('Unsupported library action.', code='unsupported_action')
        if action in ('rename', 'delete', 'restore', 'generation_preflight', 'generation_import'):
            body = args
        else:
            # Display naming is independent of the saved render identity.
            display_name = args.pop('name', None) if action == 'checkpoint' else None
            context, body = self._domain(target, expected_revision, args)
            if action == 'checkpoint':
                body.update(workflow=context['workflow']['ui'], sequence=context['name'], name=display_name)
            elif action == 'generation_export':
                body['story'] = {key.removeprefix(str(target.story_node) + '/'): value for key, value in context['fields'].items() if key.startswith(str(target.story_node) + '/')}
        return self._answer(self._post(routes[action], body))

    def h3_inspect(self, action: Literal['status', 'regeneration', 'audio', 'image_description', 'refmods', 'nodes', 'prompt_fields'], target: Target,
                   arguments_json: str = '{}', expected_revision: dict[str, StrictInt] | None = None) -> dict[str, Any]:
        """Status may materialize native previews; regeneration {box} only preflights. Audio {file}; image_description
        {action:read|resolve|edit|clear|regenerate|clear_all,...} uses existing provider/cache. Nodes {node?} gives schema;
        refmods lists installed references. prompt_fields {prompt,tags?} or saved {box,layer?,tags?} reads a prompt as the
        Studio's Sections form does: typed entries with ranges, plus counts of shots, cues, advanced cues, dialogue and
        unstructured text. Browser playback, beat analysis, layout and Undo remain browser features.
        """
        args = _object(arguments_json)
        if action == 'prompt_fields':
            if not set(args) <= {'prompt', 'tags', 'box', 'layer'} or ('prompt' in args) == ('box' in args):
                raise StudioError('Give either a prompt or a saved box (with optional layer), plus optional tags.', code='invalid_arguments')
            if 'box' in args:
                _, body = self._domain(target, expected_revision, args)
                args = {key: body[key] for key in ('timeline', *args)}
            return self._answer(self._post('/h3c/prompts/fields', args))
        if action == 'nodes':
            return self._answer(self.client.json('/object_info' + ('/' + quote(args['node'], safe='') if 'node' in args else '')))
        if action == 'refmods':
            return self._answer(self.client.json('/h3c/refmods'))
        if action in ('audio', 'image_description'):
            return self._answer(self._post('/h3c/audio/info' if action == 'audio' else '/h3c/images/description', args))
        if target.kind == 'managed':
            if action == 'status':
                return self.h3_get_project(target)
            raise StudioError('Use managed h3_plan_video for regeneration preflight.', code='unsupported_target_operation')
        if action not in ('status', 'regeneration'):
            raise StudioError('Unsupported inspection action.', code='unsupported_action')
        context, body = self._domain(target, expected_revision, args, execution=action == 'regeneration')
        if action == 'regeneration':
            body['workflow'] = context['workflow']['api']
        else:
            body['follow'] = False
        return self._answer(self._post('/h3c/timeline/' + action, body))

    def h3_job_status(self, job: JobHandle) -> dict[str, Any]:
        """Poll once; status never submits the next native unit. Retain failed/held evidence and completed proposals."""
        if job.kind != 'managed':
            return self._native_jobs().status(job)
        data = self.client.json(PREFIX + '/jobs/' + quote(job.id, safe=''))
        return dict(job=job.model_dump(exclude_none=True), state=data['state'], data_json=encoded(data).decode(),
                    blocked_by=data.get('blocked_by'), artifacts=data.get('artifacts', []))

    def h3_cancel_job(self, job: JobHandle) -> dict[str, Any]:
        """Request scoped cancellation. Never clears the global ComfyUI queue or interrupts unrelated work."""
        if job.kind != 'managed':
            return self._native_jobs().cancel(job)
        return self._post(PREFIX + '/jobs/' + quote(job.id, safe='') + '/cancel', {})

    def h3_resume_job(self, job: JobHandle) -> dict[str, Any]:
        """Reconcile retained evidence, not rerun failed/uncertain work."""
        if job.kind != 'managed':
            return self._native_jobs().status(job)
        return self._post(PREFIX + '/jobs/' + quote(job.id, safe='') + '/resume', {})

    def h3_abandon_job(self, job: JobHandle, reason: str, confirm_prompt_id: str | None = None) -> dict[str, Any]:
        """Human-attested close of a held managed job. Requires the person's reason and matching held prompt id."""
        if job.kind != 'managed':
            raise StudioError('Native uncertain submissions require retained evidence; do not automatically abandon them.', code='unsupported_target_operation')
        return self._post(PREFIX + '/jobs/' + quote(job.id, safe='') + '/abandon', dict(reason=reason, confirm_prompt_id=confirm_prompt_id))
