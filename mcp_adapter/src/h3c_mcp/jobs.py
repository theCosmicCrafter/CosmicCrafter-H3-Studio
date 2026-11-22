"""One explicit native unit per submission; uncertain delivery is never retried."""
import copy
import hashlib
import json
import uuid
from urllib.parse import quote, urlencode

from .receipts import ReceiptStore
from .transport import StudioError, encoded


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                                     separators=(',', ':')).encode()).hexdigest()


def settled(value):
    """`value` with whole-number floats as integers: ComfyUI rewrites an INT given for a FLOAT input as 24.0 (and the
    reverse) while validating, so a graph read back from its history differs from the one submitted only this way."""
    if isinstance(value, float) and value.is_integer() and abs(value) < 2 ** 53:
        return int(value)
    if isinstance(value, list):
        return [settled(item) for item in value]
    if isinstance(value, dict):
        return {key: settled(item) for key, item in value.items()}
    return value


def set_input(api, node, name, value):
    inputs = api[node]['inputs']
    previous = inputs.get(name)
    if isinstance(previous, list):
        source = api.get(str(previous[0]), {})
        if len(previous) != 2 or previous[1] != 0 or not source.get('class_type', '').startswith('Primitive'):
            raise StudioError(f'Recapture a snapshot with a literal or Primitive {name} input.', code='execution_snapshot_required')
        source['inputs']['value'] = value
    else:
        inputs[name] = value


def closure(api, outputs):
    result = {}
    def visit(identity):
        if identity in result:
            return
        if identity not in api:
            raise StudioError('Snapshot has a missing dependency.', code='execution_snapshot_required')
        result[identity] = api[identity]
        for value in api[identity].get('inputs', {}).values():
            if isinstance(value, list) and len(value) == 2:
                visit(str(value[0]))
    for identity in outputs:
        visit(identity)
    return result


class NativeJobs:
    def __init__(self, client, state_dir):
        self.client = client
        self.store = ReceiptStore(state_dir, client.base_url)

    def _post(self, path, body):
        return self.client.json(path, method='POST', body=body)

    def _prepare(self, target, revision, selection):
        context = self._post('/h3c/agent/projects/context', dict(target=target.wire(), expected_revision=revision, operation='video_plan'))
        api = copy.deepcopy(context['workflow']['api'])
        node = target.timeline_node
        # Preparation validates authored values without pretending an editor graph is executable.
        validation = copy.deepcopy(api)
        validation[node]['inputs'].update(name=context['name'], timeline=encoded(context['timeline']).decode())
        prepared = self._post('/h3c/timeline/prepare', dict(version=1, name=context['name'], timeline=context['timeline'],
            settings=context['settings'], workflow=dict(api=validation, timeline_node=node), assets=context.get('assets', [])))
        line = copy.deepcopy(prepared['timeline'])
        kind = selection.get('kind', 'all')
        ids = selection.get('ids', [])
        if kind not in ('all', 'boxes', 'bridges') or not isinstance(ids, list) or any(not isinstance(v, str) for v in ids):
            raise StudioError('Use all, boxes or bridges with box ids.', code='invalid_selection')
        boxes = line.get('boxes', [])
        known = {box['id'] for box in boxes}
        if kind != 'all' and (not ids or not set(ids) <= known):
            raise StudioError('Selection must identify existing boxes.', code='invalid_selection')
        status = context.get('native_status', {})
        if status.get('ok') is False:
            raise StudioError(str(status.get('error')), code='invalid_native_state')
        by_id = {row.get('id', row.get('box')): row for row in status.get('boxes', [])}
        unit = None
        for index, box in enumerate(boxes):
            if kind == 'bridges':
                break
            if (kind == 'boxes' and box['id'] in ids) or (kind == 'all' and by_id.get(box['id'], {}).get('status') not in ('done', 'outdated')):
                unit = dict(kind='box', id=box['id'], index=index + 1)
                break
        if unit is None:
            for row in status.get('bridges', []):
                identity = row.get('box', row.get('before'))
                if row.get('mode', 'insert') == 'replace':
                    continue
                if (kind == 'bridges' and identity in ids) or (kind == 'all' and row.get('status') != 'done'):
                    unit = dict(kind='bridge', id=identity)
                    break
        preflight = None
        if unit and unit['kind'] == 'box':
            preflight = self._post('/h3c/timeline/regeneration', dict(name=context['name'], timeline=encoded(line).decode(),
                settings=context['settings'], box=unit['id'], workflow=api, timeline_node=node))
        blocked = bool(preflight and preflight.get('needs_rebuild') and selection.get('rebuild_continuity') != preflight.get('receipt'))
        plan = dict(target=target.wire(), revision=revision, selection=selection, unit=unit,
                    preparation_sha256=digest(prepared), authored_sha256=digest(context['timeline']),
                    workflow_sha256=digest(api), preflight=preflight, blocked=blocked)
        line.pop('render_box', None)
        line.pop('render_bridge', None)
        line.pop('rebuild_continuity', None)
        if unit:
            line['render_box' if unit['kind'] == 'box' else 'render_bridge'] = unit.get('index', unit['id'])
            if preflight and preflight.get('needs_rebuild') and not blocked:
                line['rebuild_continuity'] = preflight['receipt']
        set_input(api, node, 'timeline', encoded(line).decode())
        return plan, closure(api, context['outputs']), context['workflow']['ui'], context['outputs']

    def prepare(self, target, revision, selection):
        plan, _, _, _ = self._prepare(target, revision, selection)
        return dict(target=target.wire(), revision=revision, plan_sha256=digest(plan), plan_json=encoded(plan).decode())

    def submit_video(self, target, revision, selection, plan_sha256, request_key):
        request_hash = digest(dict(target=target.wire(), revision=revision, selection=selection, plan_sha256=plan_sha256))
        with self.store.claim(request_key, request_hash) as record:
            if record is not None:
                return self._result(record)
            plan, graph, ui, outputs = self._prepare(target, revision, selection)
            if digest(plan) != plan_sha256:
                raise StudioError('Native plan changed; inspect a fresh plan.', code='plan_conflict')
            if plan['blocked']:
                raise StudioError('Review continuity rebuild effects and supply its receipt in selection_json.', code='continuity_consent_required', details=plan['preflight'])
            if plan['unit'] is None:
                raise StudioError('No eligible native unit remains.', code='nothing_to_render')
            return self._submit_locked(request_key, request_hash, target, 'video', graph, ui, outputs)

    def _submit_locked(self, key, request_hash, target, kind, graph, ui, outputs, metadata=None, identity=None, result_receipt=None):
        identity = identity or str(uuid.uuid4())
        provenance = dict(request_id=identity, graph_sha256=digest(graph), target=target.wire())
        body = dict(prompt_id=identity, prompt=graph, client_id='h3c-mcp', partial_execution_targets=outputs,
                    extra_data=dict(extra_pnginfo={'workflow': ui}, h3c_agent=provenance, **(metadata or {})))
        record = dict(request_sha256=request_hash, state='submitting', kind=kind, id=identity, target=target.wire(),
                      request_key=key, body=body, provenance=provenance)
        if result_receipt is not None:
            record['result_receipt'] = result_receipt
        self.store.write(key, record)
        try:
            reply = self._post('/prompt', body)
            if reply.get('prompt_id') != identity:
                raise StudioError('Host acknowledgement did not match the retained prompt id.')
            record['state'] = 'accepted'
        except StudioError as error:
            record.update(state='needs_reconciliation', delivery_error=error.result())
        self.store.write(key, record)
        return self._result(record)

    def _result(self, record):
        return dict(job={key: record[key] for key in ('kind', 'id', 'target', 'request_key')}, state=record['state'],
                    execution_completed=record.get('execution_completed', False),
                    result_available=bool(record.get('result')),
                    data_json=encoded({key: value for key, value in record.items() if key != 'body'}).decode())

    def _owned(self, row, record):
        return (isinstance(row, list) and len(row) >= 4 and row[1] == record['id']
                and digest(settled(row[2])) == digest(settled(record['body']['prompt']))
                and isinstance(row[3], dict) and row[3].get('h3c_agent') == record['provenance'])

    def status(self, handle):
        if not handle.request_key:
            raise StudioError('Native status requires its retained request key.', code='receipt_required')
        old = self.store.load(handle.request_key)
        if old is None or old['id'] != handle.id or old['kind'] != handle.kind or old['target'] != (handle.target.wire() if handle.target else None):
            raise StudioError('Job handle does not match its local receipt.', code='receipt_conflict')
        with self.store.claim(handle.request_key, old['request_sha256']) as record:
            if record['kind'] == 'story':
                return self._story_status(record)
            if record['kind'] in ('still', 'reference'):
                if record.get('result') is None or record['state'] not in ('complete', 'failed', 'cancelled'):
                    path = '/h3c/reference-assets/result' if record['kind'] == 'reference' else '/h3c/stills/result'
                    result = self._post(path, record['result_receipt'])
                    record.update(state=result['state'], result=result)
                    self.store.write(handle.request_key, record)
                return self._result(record)
            if record['state'] in ('succeeded', 'failed'):
                return self._result(record)
            history = self.client.json('/history/' + quote(handle.id, safe=''))
            entry = history.get(handle.id)
            if entry and self._owned(entry.get('prompt'), record):
                status = entry.get('status', {})
                if status.get('completed') and status.get('status_str') == 'success':
                    record.update(state='succeeded', execution_completed=True, history=entry)
                elif status.get('status_str') == 'error':
                    record.update(state='failed', history=entry)
                else:
                    record['state'] = 'needs_reconciliation'
            else:
                queue = self.client.json('/queue')
                record['state'] = 'needs_reconciliation'
                for name, state in (('queue_pending', 'queued'), ('queue_running', 'running')):
                    if any(self._owned(row, record) for row in queue.get(name, [])):
                        record['state'] = state
            self.store.write(handle.request_key, record)
            return self._result(record)

    def cancel(self, handle):
        if handle.kind == 'story':
            record = self.store.load(handle.request_key)
            if record and record['id'] == handle.id and record.get('remote_id'):
                return self._post('/h3c/story/cancel', {'job': record['remote_id']})
        raise StudioError('This host has no safely scoped native cancellation API; use Studio to stop the identified prompt.', code='scoped_cancellation_unavailable')

    def _context(self, target, revision, args):
        from .tools import StudioTools
        return StudioTools(self.client, None)._domain(target, revision, args, execution=True)

    def start_still(self, target, revision, args, key, reference=False):
        request_hash = digest(dict(kind='reference' if reference else 'still', target=target.wire(), revision=revision, args=args))
        with self.store.claim(key, request_hash) as record:
            if record is not None:
                return self._result(record)
            context, body = self._context(target, revision, args)
            body['request_id'] = str(uuid.uuid4())
            prepared = self._post('/h3c/reference-assets/prepare' if reference else '/h3c/stills/prepare', body)
            receipt = dict(request_id=body['request_id'], prompt_id=prepared['prompt_id'], provenance=prepared['provenance'])
            metadata = {**receipt, 'collector': 'h3c_still_output'}
            return self._submit_locked(key, request_hash, target, 'reference' if reference else 'still', prepared['prompt'],
                context['workflow']['ui'], prepared['outputs'], metadata={'h3c_still': metadata},
                identity=prepared['prompt_id'], result_receipt=receipt)

    def start_story(self, target, revision, action, args, key):
        if target.kind != 'native' or not target.story_node:
            raise StudioError('Story execution requires a native snapshot with an explicit Story node.', code='unsupported_target_operation')
        request_hash = digest(dict(kind='story', target=target.wire(), revision=revision, action=action, args=args))
        with self.store.claim(key, request_hash) as record:
            if record is not None:
                return self._result(record)
            context, body = self._context(target, revision, args)
            identity = str(uuid.uuid4())
            # Omitting workflow avoids the browser's save-on-start side effect. Only proposals are returned.
            body.pop('workflow', None)
            body.update(prompt=context['prompt'], story=target.story_node, client='h3c-mcp', request_id=identity)
            if action == 'rewrite':
                body['rewrite_all'] = True
            record = dict(request_sha256=request_hash, state='submitting', kind='story', id=identity,
                          target=target.wire(), request_key=key, body=body)
            self.store.write(key, record)
            path = {'check': '/h3c/story/check', 'still_prompts': '/h3c/still-prompts/prepare'}.get(action, '/h3c/story/write')
            try:
                reply = self._post(path, body)
                record.update(state='accepted', remote_id=reply['job'])
            except StudioError as error:
                record.update(state='needs_reconciliation', delivery_error=error.result())
            self.store.write(key, record)
            return self._result(record)

    def _story_status(self, record):
        target = record['target']
        if not record.get('remote_id'):
            current = self.client.json('/h3c/story/current?' + urlencode(dict(client='h3c-mcp', graph=target['graph'], story=target['story_node'], recover='true')))
            if current.get('request_id') == record['id'] and current.get('job'):
                record['remote_id'] = current['job']
        if record.get('remote_id') and record.get('result') is None:
            result = self.client.json('/h3c/story/job?' + urlencode(dict(id=record['remote_id'], graph=target['graph'], story=target['story_node'])))
            record['state'] = result['state']
            if result['state'] not in ('running', 'unknown'):
                record['result'] = result
        self.store.write(record['request_key'], record)
        return self._result(record)

    def acknowledge_story(self, handle):
        self.status(handle)
        record = self.store.load(handle.request_key)
        if not record.get('result') or not record.get('remote_id'):
            raise StudioError('Retain a finished Story proposal before acknowledging it.', code='result_not_available')
        return self._post('/h3c/story/taken', {'job': record['remote_id']})
