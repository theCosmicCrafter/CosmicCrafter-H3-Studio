import copy
import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from tests.h3c.continuity_support import enable_comfy_cpu
enable_comfy_cpu()
from h3_continuity import saved_state, story_library
try:
    from h3_continuity.agent_api import projects
except ImportError:
    projects = None


def fixture():
    line = {'version': 1, 'boxes': [{'id': 'a', 'frames': 22, 'prompt': 'Old', 'seed': 18446744073709551615}], 'opaque': {'keep': True}}
    fields = {'name': 'native-study', 'timeline': json.dumps(line), 'width': 768, 'height': 448, 'context_frames': 39,
              'carry_audio': True, 'ref_image_size': 'match', 'audio_context_frames': 0}
    def node(identity, kind, values):
        return dict(id=identity, type=kind, inputs=[dict(name=name, widget={'name': name}) for name in values], widgets_values=list(values.values()))
    ui = dict(id='graph-a', nodes=[node(1, 'H3C_Story', {'state': '{}', 'idea': 'A study'}), node(2, 'H3C_Timeline', fields)], links=[])
    api = {'1': {'class_type': 'H3C_Story', 'inputs': {'state': '{}', 'idea': 'A study'}},
           '2': {'class_type': 'H3C_Timeline', 'inputs': copy.deepcopy(fields)},
           '9': {'class_type': 'H3C_SaveSegment', 'inputs': {'segment': ['2', 3]}}}
    return ui, api


class NativeProjectsTest(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(projects, 'Saved native projects need an agent interface')
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.addCleanup(mock.patch.stopall)
        mock.patch('folder_paths.get_system_user_directory', side_effect=lambda name: str(root / name)).start()
        mock.patch('folder_paths.get_user_directory', return_value=str(root / 'user')).start()
        mock.patch('folder_paths.get_output_directory', return_value=str(root / 'output')).start()
        mock.patch('h3_continuity.nodes.sequences_root', return_value=str(root / 'output' / 'h3_sequences')).start()
        self.ui, self.api = fixture()
        self.target = dict(kind='native', graph='graph-a', timeline_node='2', story_node='1')

    def registered(self):
        return projects.register(self.target, self.ui, self.api)

    def test_old_story_is_editable_without_execution_snapshot(self):
        story_library.save('graph-a', '1', self.ui, 'native-study')
        before = projects.read(self.target)
        self.assertFalse(before['execution_ready'])
        document = json.loads(before['document_json'])
        self.assertEqual(document['timeline']['boxes'][0]['seed'], 18446744073709551615)
        document['timeline']['boxes'][0]['prompt'] = 'Changed'
        after = projects.save(self.target, before['revision'], document)
        self.assertEqual(json.loads(after['document_json'])['timeline']['boxes'][0]['prompt'], 'Changed')
        context = projects.context(self.target, after['revision'], 'saved')
        self.assertEqual(context['name'], 'native-study')
        self.assertEqual(context['workflow']['ui']['id'], 'graph-a')

    def test_read_reports_timeline_features_this_host_cannot_read(self):
        story_library.save('graph-a', '1', self.ui, 'native-study')
        self.assertEqual(projects.read(self.target)['unsupported_features'], [])
        line = json.loads(self.ui['nodes'][1]['widgets_values'][1])
        line['requires'] = ['future-feature-9', 'timeline-tracks-1']
        self.ui['nodes'][1]['widgets_values'][1] = json.dumps(line)
        story_library.save('graph-a', '1', self.ui, 'native-study', library_revision=1)
        self.assertEqual(projects.read(self.target)['unsupported_features'], ['future-feature-9'])

    def test_listed_library_projects_carry_their_title_and_sequence(self):
        self.ui['nodes'][0]['widgets_values'][0] = json.dumps({'title': 'A study in rain', 'timeline': '2'})
        story_library.save('graph-a', '1', self.ui, 'native-study')
        row = next(r for r in projects.list_projects()['projects'] if r['target']['graph'] == 'graph-a')
        self.assertEqual((row['title'], row['sequence']), ('A study in rain', 'native-study'))
        self.assertRegex(row['library_id'], '^[a-f0-9]{64}$')
        self.assertNotIn('checkpoint_name', row)

    def test_registration_and_edits_update_execution_inputs(self):
        before = self.registered()
        self.assertTrue(before['execution_ready'])
        document = json.loads(before['document_json'])
        document['timeline']['boxes'][0]['prompt'] = 'Changed'
        after = projects.save(self.target, before['revision'], document)
        context = projects.context(self.target, after['revision'], 'video')
        self.assertEqual(json.loads(context['workflow']['api']['2']['inputs']['timeline'])['boxes'][0]['prompt'], 'Changed')
        self.assertEqual(context['workflow']['ui']['id'], 'graph-a')
        self.assertEqual(context['outputs'], ['9'])

    def test_video_plan_status_never_materializes_media(self):
        before = self.registered()
        with mock.patch('h3_continuity.timeline_node.request_status', return_value={'boxes': []}) as status:
            context = projects.context(self.target, before['revision'], 'video_plan')
            self.assertEqual(context['native_status'], {'boxes': []})
            self.assertFalse(status.call_args.kwargs['materialize'])

    def test_stale_save_preserves_newer_seed_and_metadata(self):
        before = self.registered()
        document = json.loads(before['document_json'])
        document['timeline']['boxes'][0]['prompt'] = 'Accepted'
        accepted = projects.save(self.target, before['revision'], document)
        with self.assertRaisesRegex(ValueError, 'revision'):
            projects.save(self.target, before['revision'], document)
        self.assertEqual(projects.read(self.target)['document_json'], accepted['document_json'])
        self.assertEqual(json.loads(accepted['document_json'])['timeline']['opaque'], {'keep': True})

    def test_primitive_binding_is_updated_without_changing_link(self):
        self.linked()
        before = self.registered()
        document = json.loads(before['document_json'])
        document['settings']['width'] = 1024
        after = projects.save(self.target, before['revision'], document)
        api = projects.context(self.target, after['revision'], 'video')['workflow']['api']
        self.assertEqual(api['source']['inputs']['value'], 1024)
        self.assertEqual(api['2']['inputs']['width'], ['source', 0])

    def test_computed_binding_remains_editable_but_requires_recapture(self):
        self.linked(kind='SomeComputedWidth')
        before = self.registered()
        document = json.loads(before['document_json'])
        document['settings']['width'] = 1024
        after = projects.save(self.target, before['revision'], document)
        self.assertFalse(after['execution_ready'])
        with self.assertRaisesRegex(ValueError, 'snapshot'):
            projects.context(self.target, after['revision'], 'video')

    def test_browser_widget_overlay_updates_context(self):
        before = self.registered()
        saved_state.write('workflow', 'graph-a', 'workflow', {'2/H3C_Timeline/width': 1024})
        after = projects.read(self.target)
        self.assertNotEqual(after['revision'], before['revision'])
        self.assertEqual(projects.context(self.target, after['revision'], 'video')['settings']['width'], 1024)

    def test_snapshot_cannot_replace_registered_identity_without_revision(self):
        self.registered()
        with self.assertRaisesRegex(ValueError, 'revision'):
            projects.register(self.target, self.ui, self.api)

    def test_wiring_change_invalidates_execution(self):
        self.registered()
        library = story_library.save('graph-a', '1', self.ui, 'native-study')
        changed = copy.deepcopy(self.ui)
        changed['nodes'].append(dict(id=4, type='Other', inputs=[], widgets_values=[]))
        story_library.save('graph-a', '1', changed, 'native-study', library_revision=library['revision'])
        self.assertFalse(projects.read(self.target)['execution_ready'])

    def test_managed_sequence_is_rejected(self):
        self.ui['nodes'][1]['properties'] = {'h3c_project': {'mode': 'attached', 'id': 'managed'}}
        with self.assertRaisesRegex(ValueError, 'managed'):
            self.registered()

    def test_snapshot_save_hook_and_discovery(self):
        story_library.save('graph-a', '1', self.ui, 'native-study', execution=self.api)
        self.assertTrue(projects.read(self.target)['execution_ready'])
        self.assertEqual(projects.list_projects()['projects'][0]['target']['graph'], 'graph-a')

    def test_busy_native_sequence_cannot_be_saved(self):
        before = self.registered()
        with mock.patch('h3_continuity.takes.busy', return_value=True), self.assertRaisesRegex(ValueError, 'busy'):
            projects.save(self.target, before['revision'], json.loads(before['document_json']))

    def test_captured_api_must_match_authored_literal_widgets(self):
        self.api['2']['inputs']['timeline'] = '{"boxes":[]}'
        with self.assertRaisesRegex(ValueError, 'match'):
            self.registered()

    def test_busy_native_sequence_cannot_replace_snapshot(self):
        before = self.registered()
        with mock.patch('h3_continuity.takes.busy', return_value=True), self.assertRaisesRegex(ValueError, 'busy'):
            projects.register(self.target, self.ui, self.api, before['revision'])

    def test_failure_after_widget_save_never_executes_old_authored_inputs(self):
        before = self.registered()
        document = json.loads(before['document_json'])
        document['timeline']['boxes'][0]['prompt'] = 'Saved before interruption'
        with mock.patch.object(projects, '_write', side_effect=OSError('disk unavailable')), self.assertRaises(OSError):
            projects.save(self.target, before['revision'], document)
        after = projects.read(self.target)
        self.assertEqual(json.loads(after['document_json'])['timeline']['boxes'][0]['prompt'], 'Saved before interruption')
        context = projects.context(self.target, after['revision'], 'video')
        self.assertEqual(json.loads(context['workflow']['api']['2']['inputs']['timeline'])['boxes'][0]['prompt'], 'Saved before interruption')

    def test_checkpoint_is_readable_but_cannot_be_saved(self):
        self.registered()
        library = saved_state.read('library', 'graph-a', 'library')['value']
        library['checkpoint_name'] = 'Locked version'
        saved_state.write('library', 'graph-a', 'library', library)
        before = projects.read(self.target)
        self.assertTrue(before['checkpoint'])
        with self.assertRaisesRegex(ValueError, 'checkpoint'):
            projects.save(self.target, before['revision'], json.loads(before['document_json']))

    def test_timeline_only_registration_does_not_invent_a_story(self):
        self.ui['nodes'] = self.ui['nodes'][1:]
        del self.api['1']
        del self.target['story_node']
        before = self.registered()
        self.assertTrue(before['execution_ready'])
        self.assertNotIn('story', json.loads(before['document_json']))
        self.assertEqual(projects.list_projects()['projects'][0]['target'], self.target)

    def test_wrong_timeline_identity_is_rejected(self):
        self.target['timeline_node'] = 'unrelated'
        with self.assertRaisesRegex(ValueError, 'Timeline'):
            self.registered()

    def test_recapture_replaces_authoritative_library_and_old_overlay(self):
        before = self.registered()
        document = json.loads(before['document_json'])
        document['settings']['width'] = 1024
        before = projects.save(self.target, before['revision'], document)
        # An explicit recapture must replace both wiring and previously saved values.
        ui, api = fixture()
        ui['nodes'].append(dict(id=10, type='NewNode', inputs=[], widgets_values=[]))
        api['10'] = dict(class_type='NewNode', inputs={})
        after = projects.register(self.target, ui, api, before['revision'])
        self.assertTrue(after['execution_ready'])
        context = projects.context(self.target, after['revision'], 'video')
        self.assertEqual(context['settings']['width'], 768)
        self.assertIn('10', context['workflow']['api'])
        library = saved_state.read('library', 'graph-a', 'library')['value']
        self.assertTrue(any(str(n['id']) == '10' for n in library['workflow']['nodes']))
        self.assertGreater(after['revision']['workflow'], before['revision']['workflow'])

    def linked(self, widget='width', value=768, kind='PrimitiveInt'):
        node = self.ui['nodes'][1 if widget == 'width' else 0]
        index = next(i for i, port in enumerate(node['inputs']) if port['name'] == widget)
        node['inputs'][index]['link'] = 1
        self.ui['links'].append([1, 'source', 0, node['id'], index, 'INT' if kind == 'PrimitiveInt' else 'STRING'])
        self.ui['nodes'].append(dict(id='source', type=kind, inputs=[], outputs=[{'links': [1]}], widgets_values=[value], widgets_values_named={'value': value}))
        self.api['source'] = dict(class_type=kind, inputs={'value': value})
        self.api[str(node['id'])]['inputs'][widget] = ['source', 0]

    def test_linked_controls_survive_browser_reopen_and_recapture(self):
        for widget, old, new, kind in [('width', 768, 1024, 'PrimitiveInt'), ('idea', 'A study', 'New idea', 'PrimitiveString')]:
            with self.subTest(widget=widget):
                self.ui, self.api = fixture()
                self.target['graph'] = self.ui['id'] = 'linked-' + widget
                self.linked(widget, old, kind)
                for node in self.ui['nodes'][:2]:
                    node['widgets_values_named'] = {port['widget']['name']: value for port, value in zip(node['inputs'], node['widgets_values'])}
                before = self.registered()
                document = json.loads(before['document_json'])
                if widget == 'width':
                    document['settings']['width'] = new
                else:
                    document['extra_widgets']['1/H3C_Story/idea'] = new
                after = projects.save(self.target, before['revision'], document)
                context = projects.context(self.target, after['revision'], 'video')
                source = next(n for n in context['workflow']['ui']['nodes'] if n['id'] == 'source')
                self.assertEqual(source['widgets_values'][0], new)
                self.assertEqual(source['widgets_values_named']['value'], new)
                self.assertEqual(context['workflow']['api']['source']['inputs']['value'], new)
                owner = context['workflow']['ui']['nodes'][1 if widget == 'width' else 0]
                self.assertEqual(owner['widgets_values_named'][widget], new)
                recaptured = projects.register(self.target, context['workflow']['ui'], context['workflow']['api'], after['revision'])
                self.assertTrue(recaptured['execution_ready'])

    def test_capture_reads_effective_primitive_control_instead_of_stale_h3_widget(self):
        self.linked()
        self.ui['nodes'][-1]['widgets_values'][0] = 1024
        self.api['source']['inputs']['value'] = 1024
        before = self.registered()
        self.assertTrue(before['execution_ready'])
        self.assertEqual(json.loads(before['document_json'])['settings']['width'], 1024)

    def test_capture_rejects_ui_and_api_binding_disagreement(self):
        self.linked()
        self.api['2']['inputs']['width'] = 768
        with self.assertRaisesRegex(ValueError, 'connection'):
            self.registered()

    def test_shared_primitive_cannot_silently_change_an_unedited_consumer(self):
        self.linked()
        self.api['shared'] = dict(class_type='OtherNode', inputs={'setting': ['source', 0]})
        before = self.registered()
        document = json.loads(before['document_json'])
        document['settings']['width'] = 1024
        with self.assertRaisesRegex(ValueError, 'shared'):
            projects.save(self.target, before['revision'], document)
        self.assertEqual(projects.read(self.target)['revision'], before['revision'])

    def test_native_operations_never_hold_state_while_waiting_for_render_lock(self):
        before = self.registered()
        real_sequence = projects.nodes.SEQUENCE_LOCK
        attempted = threading.Event()
        class ObservedLock:
            def __enter__(self):
                attempted.set()
                real_sequence.acquire()
                return self
            def __exit__(self, *args):
                real_sequence.release()
        operations = [lambda: projects.save(self.target, projects.read(self.target)['revision'], json.loads(projects.read(self.target)['document_json'])),
                      lambda: projects.register(self.target, self.ui, self.api, projects.read(self.target)['revision']),
                      lambda: projects.context(self.target, projects.read(self.target)['revision'], 'video_plan')]
        for operation in operations:
            errors = []
            def run():
                try:
                    operation()
                except Exception as error:
                    errors.append(error)
            attempted.clear()
            real_sequence.acquire()
            with mock.patch.object(projects.nodes, 'SEQUENCE_LOCK', ObservedLock()):
                worker = threading.Thread(target=run, daemon=True)
                worker.start()
                try:
                    self.assertTrue(attempted.wait(2), 'operation must reach the render lock')
                    acquired = saved_state.LOCK.acquire(blocking=False)
                    if acquired:
                        saved_state.LOCK.release()
                    self.assertTrue(acquired, 'render completion must be able to take the state lock')
                finally:
                    real_sequence.release()
                    worker.join(5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(errors, [])

    def test_video_context_verifies_timed_text_audio_against_real_preparation(self):
        from h3_continuity import timed_text, timeline_prepare
        root = Path(self.directory.name) / 'input'
        root.mkdir()
        audio = root / 'recording.wav'
        audio.write_bytes(b'original recording bytes')
        checksum = hashlib.sha256(audio.read_bytes()).hexdigest()
        mock.patch('folder_paths.get_directory_by_type', return_value=str(root)).start()
        for file_backed in (False, True):
            with self.subTest(file_backed=file_backed):
                self.ui, self.api = fixture()
                self.target['graph'] = self.ui['id'] = 'audio-' + str(file_backed)
                line = json.loads(self.api['2']['inputs']['timeline'])
                text = timed_text.import_whisper([dict(start=0, end=.2, text=' exact words')], 'words.json', 'b'*64)
                text['audio_sha256'] = checksum
                line['timed_text'] = text
                if file_backed:
                    line['audio_clips'] = [dict(slot='audio1', start=0, source_start=0, duration=1,
                                               file=dict(filename=audio.name, subfolder='', type='input'))]
                else:
                    self.api['audio'] = dict(class_type='LoadAudio', inputs={'audio': audio.name})
                    self.api['2']['inputs']['audios.audio1'] = ['audio', 0]
                self.api['2']['inputs']['timeline'] = json.dumps(line)
                self.ui['nodes'][1]['widgets_values'][1] = json.dumps(line)
                view = self.registered()
                context = projects.context(self.target, view['revision'], 'video_plan')
                self.assertEqual(context['assets'][0]['sha256'], checksum)
                prepared = timeline_prepare.prepare(dict(version=1, name=context['name'], timeline=context['timeline'],
                    settings=context['settings'], workflow=dict(api=context['workflow']['api'], timeline_node='2'), assets=context['assets']))
                self.assertTrue(prepared['ok'], prepared)
                bad = copy.deepcopy(context['assets'])
                bad[0]['sha256'] = 'c'*64
                rejected = timeline_prepare.prepare(dict(version=1, name=context['name'], timeline=context['timeline'],
                    settings=context['settings'], workflow=dict(api=context['workflow']['api'], timeline_node='2'), assets=bad))
                self.assertFalse(rejected['ok'])


if __name__ == '__main__':
    unittest.main()
