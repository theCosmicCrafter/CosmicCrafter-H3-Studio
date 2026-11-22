import tempfile
import unittest

from tests.h3c.continuity_support import enable_comfy_cpu

enable_comfy_cpu()

import folder_paths  # noqa: E402
from h3_continuity import story_names  # noqa: E402


class StoryNamesTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.original = folder_paths.get_system_user_directory
        folder_paths.get_system_user_directory = lambda name='system': self.folder
        self.addCleanup(setattr, folder_paths, 'get_system_user_directory', self.original)

    def test_no_names_until_one_is_given(self):
        self.assertEqual(story_names.read(), {})

    def test_name_clear_and_keep_others(self):
        story_names.rename('heavy things fall up', '  Gravity   short ')
        story_names.rename('other', 'Second')
        self.assertEqual(story_names.read(), {'heavy things fall up': 'Gravity short', 'other': 'Second'})
        story_names.rename('heavy things fall up', '   ')
        self.assertEqual(story_names.read(), {'other': 'Second'})
        story_names.rename('never named', '')
        self.assertEqual(story_names.read(), {'other': 'Second'})

    def test_a_name_survives_a_new_read(self):
        story_names.rename('k', 'Kept')
        self.assertEqual(story_names.read(), {'k': 'Kept'})

    def test_invalid_names_fail_and_change_nothing(self):
        story_names.rename('k', 'Kept')
        for key, name in (('', 'x'), ('   ', 'x'), (None, 'x'), ('k' * 301, 'x'), ('k', 5), ('k', 'n' * 121)):
            with self.assertRaises(ValueError):
                story_names.rename(key, name)
        self.assertEqual(story_names.read(), {'k': 'Kept'})

    def test_the_names_file_is_not_mistaken_for_a_saved_story(self):
        story_names.rename('k', 'Kept')
        from h3_continuity import saved_state
        value = saved_state.read('names', 'library', 'names')['value']
        self.assertNotEqual(value.get('format'), 'h3-library')
