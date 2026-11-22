import copy
import unittest
from h3_continuity import story_bible


def cast_timeline():
    return {'version': 1, 'prompt': '<Subject 7> is a shared character.', 'bible': {'entities': [
        {'id': 'e1', 'name': 'Mara', 'kind': 'character', 'description': 'Mara in a blue coat', 'pictures': ['image17'],
         'looks': [{'from': 'b', 'description': 'Mara in a red coat'}]}]}, 'boxes': [
        {'id': 'a', 'frames': 48, 'exact': True, 'seed': 1, 'prompt': ''},
        {'id': 'b', 'frames': 96, 'exact': True, 'seed': 2, 'cut': True,
         'prompt': 'integrated_multimodal_description:\n[Shot 1] <Subject 2> waits.\n\noverall_soundscape: Rain.',
         'schedule': {'entities': ['e1'], 'place': None}}]}


class CastAssignmentTest(unittest.TestCase):
    def test_active_look_next_number_and_atomic_input(self):
        doc = cast_timeline()
        before = copy.deepcopy(doc)
        result = story_bible.handle({'action': 'assign', 'timeline': doc, 'box': 'b', 'entity': 'e1'})
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['subject'], '<Subject 8>')
        self.assertIn('red coat', result['prompts']['b'])
        self.assertIn('@image17', result['prompts']['b'])
        self.assertIn('[Shot 1] <Subject 2> waits.', result['prompts']['b'])
        self.assertTrue(result['prompts']['b'].endswith('overall_soundscape: Rain.'))
        self.assertEqual(result['casts']['b'], {'<Subject 8>': 'e1'})
        self.assertEqual(result['schedules']['b'], {'entities': ['e1'], 'place': None})
        self.assertEqual(doc, before)

    def test_duplicate_is_noop_and_preserves_manual_definition(self):
        doc = cast_timeline()
        doc['boxes'][1].update(cast={'<Subject 3>': 'e1'}, prompt='subject_definitions:\n<Subject 3> is my custom coat.')
        result = story_bible.handle({'action': 'assign', 'timeline': doc, 'box': 'b', 'entity': 'e1'})
        self.assertTrue(result['ok'], result)
        self.assertFalse(result['changed'])
        self.assertEqual(result['prompts'], {})
        self.assertEqual(result['subject'], '<Subject 3>')

    def test_picture_only_identity_and_empty_identity_error(self):
        for pictures, ok in [(['image17'], True), ([], False)]:
            doc = cast_timeline()
            doc['bible']['entities'][0].update(description='', looks=[], pictures=pictures)
            result = story_bible.handle({'action': 'assign', 'timeline': doc, 'box': 'a', 'entity': 'e1'})
            self.assertEqual(result['ok'], ok, result)
            if ok:
                self.assertIn('@image17', result['prompts']['a'])

    def test_plain_prose_with_a_colon_line_stays_the_visual_description(self):
        doc = cast_timeline()
        doc['boxes'][0]['prompt'] = 'A quiet room.\nnote: keep the lamp on'
        result = story_bible.handle({'action': 'assign', 'timeline': doc, 'box': 'a', 'entity': 'e1'})
        self.assertTrue(result['ok'], result)
        self.assertTrue(result['prompts']['a'].endswith('\n\ndetailed_description:\nA quiet room.\nnote: keep the lamp on'))

    def test_missing_entity_disabled_picture_and_ambiguous_headers_change_nothing(self):
        for patch in ({'entity': 'e99'}, {'disabled_refs': ['image17']}, {'prompt': 'subject_definitions: A\nsubject_definitions: B'}):
            doc = cast_timeline()
            if 'disabled_refs' in patch:
                doc.update(patch)
            if 'prompt' in patch:
                doc['boxes'][1]['prompt'] = patch['prompt']
            before = copy.deepcopy(doc)
            result = story_bible.handle({'action': 'assign', 'timeline': doc, 'box': 'b', 'entity': patch.get('entity', 'e1')})
            self.assertFalse(result['ok'], result)
            self.assertEqual(doc, before)


if __name__ == '__main__':
    unittest.main()
