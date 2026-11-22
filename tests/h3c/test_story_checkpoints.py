import copy
import json
import os
import tempfile
import unittest
from unittest import mock

from tests.h3c.continuity_support import enable_comfy_cpu

enable_comfy_cpu()

from h3_continuity import nodes, saved_state, store, story_library, timeline, takes


def workflow():
    def node(identity, kind, fields):
        return {'id': identity, 'type': kind,
                'inputs': [{'name': key, 'widget': {'name': key}} for key in fields],
                'widgets_values': list(fields.values())}
    return {'id': 'working', 'nodes': [
        node(1, 'H3C_Story', {'state': json.dumps({'title': 'Heavy things fall up', 'timeline': '2'})}),
        node(2, 'H3C_Timeline', {'name': 'Project-original', 'timeline': json.dumps({
            'version': 1, 'boxes': [{'id': 'a', 'frames': 22, 'seed': 1, 'prompt': 'Falls up'}]})})], 'links': []}


class StoryCheckpointTest(unittest.TestCase):
    def test_checkpoint_still_accepts_an_empty_timeline_without_a_boxes_field(self):
        self.workflow['nodes'][1]['widgets_values'][1] = '{"version":1}'
        checkpoint = story_library.load(self.save()['id'])
        restored = story_library.restore_checkpoint(checkpoint['id'])
        for value in (checkpoint, restored):
            self.assertEqual(story_library._fields(value['workflow'])[('2', 'timeline')].get('boxes', []), [])

    def test_checkpoint_repairs_identical_preview_targets_without_changing_source(self):
        raw = json.loads(self.workflow['nodes'][1]['widgets_values'][1])
        preview = {'target': {'kind': 'first'}, 'frame': 0, 'still_source': None}
        raw['boxes'][0]['previews'] = [preview, copy.deepcopy(preview)]
        self.workflow['nodes'][1]['widgets_values'][1] = json.dumps(raw)
        before = copy.deepcopy(self.workflow)
        saved = story_library.load(self.save()['id'])
        restored = story_library.restore_checkpoint(saved['id'])
        for value in (saved, restored):
            line = story_library._fields(value['workflow'])[('2', 'timeline')]
            self.assertEqual(line['boxes'][0], {**raw['boxes'][0], 'previews': [preview]})
        self.assertEqual(self.workflow, before)
        with open(os.path.join(self.root, saved['sequence'], 'video.mp4'), 'rb') as stream:
            self.assertEqual(stream.read(), b'original video')

    def test_checkpoint_preserves_box_audio_bindings_and_hidden_tails(self):
        from h3_continuity import audio_windows
        raw=json.loads(self.workflow['nodes'][1]['widgets_values'][1])
        clip=dict(slot='audio1',start=0,source_start=30,duration=4)
        clip['box_windows']=audio_windows.capture(clip,[dict(id='a',start=0,duration=4)],{'source':'audio1'})
        raw.update(audio_clips=[clip],requires=[audio_windows.FEATURE])
        self.workflow['nodes'][1]['widgets_values'][1]=json.dumps(raw)
        value=story_library.load(self.save()['id'])
        restored=story_library._fields(value['workflow'])[('2','timeline')]
        self.assertEqual(restored['audio_clips'][0]['box_windows'],clip['box_windows'])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = os.path.join(self.temp.name, 'state')
        self.root = os.path.join(self.temp.name, 'h3_sequences')
        os.makedirs(self.state)
        self.folder = os.path.join(self.root, 'Project-original')
        os.makedirs(self.folder)
        self.addCleanup(mock.patch.stopall)
        mock.patch('folder_paths.get_system_user_directory', return_value=self.state).start()
        mock.patch('folder_paths.get_user_directory', return_value=os.path.join(self.temp.name, 'users')).start()
        mock.patch.object(nodes, 'sequences_root', return_value=self.root).start()
        mock.patch('folder_paths.get_output_directory', return_value=self.temp.name).start()
        self.workflow = workflow()
        manifest = store.empty_manifest('Project-original')
        manifest['segments'] = [{'index': 1, 'stem': 'seg_0001', 'timeline': {'box': 'a'},
                                 'video': {'file': 'video.mp4'}}]
        store.write_manifest(self.folder, manifest)
        with open(os.path.join(self.folder, 'seg_0001.safetensors'), 'wb') as stream:
            stream.write(b'original latents')
        with open(os.path.join(self.folder, 'video.mp4'), 'wb') as stream:
            stream.write(b'original video')

    def save(self, name='Fully rendered'):
        return story_library.save_checkpoint('working', '1', self.workflow, 'Project-original', name)

    def test_checkpoint_captures_local_state_not_later_autosaves_and_copies_video_bytes(self):
        before = copy.deepcopy(self.workflow)
        result = self.save()
        self.assertEqual(self.workflow, before)
        value = story_library.load(result['id'])
        self.assertEqual(value['checkpoint_name'], 'Fully rendered')
        self.assertNotEqual(value['sequence'], 'Project-original')
        changed = {'2/H3C_Timeline/timeline': '{"boxes": []}'}
        saved_state.write('workflow', value['graph'], 'workflow', changed)
        self.assertEqual(story_library._fields(story_library.load(result['id'])['workflow'])[('2', 'timeline')]['boxes'][0]['frames'], 22)
        with open(os.path.join(self.folder, 'video.mp4'), 'wb') as stream:
            stream.write(b'regenerated')
        with open(os.path.join(self.root, value['sequence'], 'video.mp4'), 'rb') as stream:
            self.assertEqual(stream.read(), b'original video')
        row = next(row for row in story_library.listing() if row['id'] == result['id'])
        self.assertEqual(row['checkpoint_name'], 'Fully rendered')
        self.assertEqual(row['rendered'], 1)
        self.assertEqual(row['boxes'], 1)

    def test_checkpoint_cannot_be_overwritten_or_changed_by_job_updates(self):
        value = story_library.load(self.save()['id'])
        with self.assertRaisesRegex(ValueError, 'checkpoint'):
            story_library.save(value['graph'], '1', value['workflow'], value['sequence'], library_revision=1)
        story_library.checkpoint(value['graph'], '1', '2', 'job', {'result': {'title': 'Changed'}})
        self.assertNotIn('job', story_library.load(value['id']))

    def test_duplicate_makes_a_titled_editable_copy_with_a_replacement_timeline(self):
        before = copy.deepcopy(self.workflow)
        line = json.loads(self.workflow['nodes'][1]['widgets_values'][1])
        line['boxes'][0]['prompt'] = 'Falls up, corrected'
        result = story_library.duplicate('working', '1', self.workflow, 'Project-original',
                                         title=' Heavy things, copy ', timeline_text=json.dumps(line))
        self.assertEqual(self.workflow, before)
        value = story_library.load(result['id'])
        self.assertNotIn('checkpoint_name', value)
        self.assertEqual(result, {'id': result['id'], 'graph': value['graph'], 'story': '1', 'timeline_node': '2',
                                  'sequence': value['sequence'], 'title': 'Heavy things, copy'})
        self.assertNotEqual(value['graph'], 'working')
        fields = story_library._fields(value['workflow'])
        self.assertEqual(fields[('1', 'state')]['title'], 'Heavy things, copy')
        self.assertEqual(fields[('2', 'timeline')]['boxes'][0]['prompt'], 'Falls up, corrected')
        with open(os.path.join(self.root, value['sequence'], 'video.mp4'), 'rb') as stream:
            self.assertEqual(stream.read(), b'original video')
        story_library.save(value['graph'], '1', value['workflow'], value['sequence'], library_revision=value['workflow_revision'])

    def test_duplicate_can_drop_features_this_host_cannot_read(self):
        line = json.loads(self.workflow['nodes'][1]['widgets_values'][1])
        line['requires'] = ['future-feature-9']
        with self.assertRaisesRegex(ValueError, 'newer'):
            story_library.duplicate('working', '1', self.workflow, 'Project-original', timeline_text=json.dumps(line))
        self.workflow['nodes'][1]['widgets_values'][1] = json.dumps(line)
        with self.assertRaisesRegex(ValueError, 'newer'):
            story_library.duplicate('working', '1', self.workflow, 'Project-original')
        self.assertEqual(os.listdir(self.root), ['Project-original'])
        with self.assertRaisesRegex(ValueError, 'title'):
            story_library.duplicate('working', '1', self.workflow, 'Project-original', title=' ')
        result = story_library.duplicate('working', '1', self.workflow, 'Project-original', timeline_text=json.dumps({**line, 'requires': []}))
        value = story_library.load(result['id'])
        self.assertEqual(result['title'], 'Heavy things fall up')
        self.assertEqual(story_library._fields(value['workflow'])[('2', 'timeline')]['requires'], [])

    def test_restoring_makes_an_independent_workflow_and_media_copy(self):
        checkpoint = story_library.load(self.save()['id'])
        restored = story_library.restore_checkpoint(checkpoint['id'])
        self.assertNotEqual(restored['graph'], checkpoint['graph'])
        self.assertNotEqual(restored['sequence'], checkpoint['sequence'])
        self.assertNotIn('checkpoint_name', restored)
        self.assertEqual(story_library.load(checkpoint['id'])['sequence'], checkpoint['sequence'])
        timeline_node = restored['workflow']['nodes'][1]
        self.assertEqual(timeline_node['properties']['h3c_fork_sequence'], restored['sequence'])
        with open(os.path.join(self.root, restored['sequence'], 'video.mp4'), 'wb') as stream:
            stream.write(b'edited restore')
        with open(os.path.join(self.root, checkpoint['sequence'], 'video.mp4'), 'rb') as stream:
            self.assertEqual(stream.read(), b'original video')

    def test_linked_text_controls_are_copied_and_retargeted_without_changing_source(self):
        source = self.workflow['nodes'][1]
        source['widgets_values_named'] = {'name': 'Project-original', 'timeline': source['widgets_values'][1]}
        source['inputs'][0]['link'] = 1
        self.workflow['nodes'].append({'id': 3, 'type': 'PrimitiveString',
            'inputs': [{'name': 'value', 'widget': {'name': 'value'}}], 'widgets_values': ['Project-original'],
            'widgets_values_named': {'value': 'Project-original'}})
        self.workflow['links'] = [[1, 3, 0, 2, 0, 'STRING']]
        value = story_library.load(self.save()['id'])
        self.assertEqual(value['workflow']['nodes'][2]['widgets_values'][0], value['sequence'])
        self.assertEqual(self.workflow['nodes'][2]['widgets_values'][0], 'Project-original')
        self.assertEqual(value['workflow']['nodes'][2]['widgets_values_named']['value'], value['sequence'])
        self.assertEqual(value['workflow']['nodes'][1]['widgets_values_named']['name'], value['sequence'])

    def test_missing_take_files_fail_before_creating_a_checkpoint_entry(self):
        os.unlink(os.path.join(self.folder, 'seg_0001.safetensors'))
        with self.assertRaisesRegex(ValueError, 'missing required sidecar'):
            self.save()
        self.assertEqual(story_library.listing(), [])

    def test_current_connection_wins_over_last_write_timeline(self):
        stale = copy.deepcopy(self.workflow['nodes'][1])
        stale['id'] = 4
        stale['widgets_values'][0] = 'Project-stale'
        self.workflow['nodes'].append(stale)
        self.workflow['nodes'][0]['widgets_values'][0] = json.dumps({'title': 'Heavy', 'timeline': '4'})
        self.workflow['links'] = [[1, 1, 0, 2, 0, 'H3C_STORY']]
        value = story_library.load(self.save()['id'])
        self.assertEqual(story_library._fields(value['workflow'])[('1', 'state')]['timeline'], '2')

    def test_own_folder_references_keep_current_and_outdated_render_associations(self):
        import torch
        from PIL import Image
        Image.new('RGB', (4, 4)).save(os.path.join(self.folder, 'picture.png'))
        line = json.loads(self.workflow['nodes'][1]['widgets_values'][1])
        line['reference_replacements'] = {'image1': {'file': {'filename': 'picture.png',
            'subfolder': 'h3_sequences/Project-original', 'type': 'output'}}}
        self.workflow['nodes'][1]['widgets_values'][1] = json.dumps(line)
        manifest = store.load_manifest(self.folder)
        entry = manifest['segments'][0]
        entry['timeline'].update(layout=timeline.layout_key(timeline.parse(json.dumps(line)), 0, 39),
                                 settings={'context_frames': 39})
        store.save_segment(self.folder, entry, torch.zeros(1, 1, 1, 1, 1), torch.zeros(1, 1, 1, 1), None)
        memory = {'index': 2, 'stem': 'seg_0002', 'timeline': {'box': 'b', 'memories': [
            {'box': 'a', 'layout': entry['timeline']['layout'], 'file_stamp': store.latent_stamp(self.folder, entry)}]}}
        store.save_segment(self.folder, memory, torch.zeros(1, 1, 1, 1, 1), torch.zeros(1, 1, 1, 1), None)
        manifest['segments'].append(memory)
        store.write_manifest(self.folder, manifest)
        value = story_library.restore_checkpoint(self.save()['id'])
        fields = story_library._fields(value['workflow'])
        expected = timeline.layout_key(timeline.parse(json.dumps(fields[('2', 'timeline')])), 0, 39)
        folder = os.path.join(self.root, value['sequence'])
        self.assertEqual(store.load_manifest(folder)['segments'][0]['timeline']['layout'], expected)
        path = os.path.join(folder, 'seg_0001.safetensors')
        self.assertEqual(takes.read_entry(path)['timeline']['layout'], expected)
        remembered = takes.read_entry(os.path.join(folder, 'seg_0002.safetensors'))['timeline']['memories'][0]
        self.assertEqual(remembered['layout'], expected)
        self.assertEqual(remembered['file_stamp'], store.latent_stamp(folder, entry))
        self.assertEqual(store.load_segment_latents(folder, entry)[0].sum().item(), 0)
        # A render that was already outdated must not become current merely because it was copied.
        manifest['segments'][0]['timeline']['layout'] = 'outdated layout'
        store.write_manifest(self.folder, manifest)
        stale = story_library.load(self.save('Outdated')['id'])
        self.assertEqual(store.load_manifest(os.path.join(self.root, stale['sequence']))['segments'][0]['timeline']['layout'], 'outdated layout')

    def test_repeated_names_create_distinct_checkpoints_and_bad_names_create_nothing(self):
        self.assertNotEqual(self.save()['id'], self.save()['id'])
        count = len(os.listdir(self.state))
        for name in ('', '   ', None, 3, 'x' * 121):
            with self.assertRaises(ValueError):
                self.save(name)
        self.assertEqual(len(os.listdir(self.state)), count)
