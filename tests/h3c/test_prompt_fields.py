import json
import unittest
from pathlib import Path

from h3_continuity import prompt_fields

FIXTURE = json.loads((Path(__file__).parent / 'fixtures' / 'prompt_field_cases.json').read_text(encoding='utf-8'))


def browser_offsets(source, value):
    """The browser records UTF-16 offsets; Python ranges count code points."""
    if isinstance(value, list):
        return [browser_offsets(source, item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: browser_offsets(source, item) for key, item in value.items()}
    if 'before' in value:
        for key in ('start', 'end'):
            result[key] = len(source[:value[key]].encode('utf-16-le')) // 2
    return result


class PromptFieldsTest(unittest.TestCase):
    def test_fields_match_the_browser_form(self):
        self.assertEqual([{key: field[key] for key in ('key', 'prefix', 'advanced', 'repeatable')} for field in prompt_fields.SHOT_FIELDS],
                         FIXTURE['fields'])
        for case in FIXTURE['cases']:
            with self.subTest(case['name']):
                parsed = prompt_fields.read(case['prompt'], case.get('tags', []))
                self.assertEqual(browser_offsets(case['prompt'], parsed), case['expected'])

    def test_python_ranges_slice_the_prompt_they_describe(self):
        prompt = 'detailed_description:\n[Shot 1] Zoë 😀 waits.\nLighting: Dim.'
        view = prompt_fields.inspect(prompt)
        cue = view['sections'][0]['entries'][1]
        self.assertEqual(prompt[cue['start']:cue['end']], 'Lighting: Dim.')
        self.assertEqual(view['summary'], {'shots': 1, 'cues': 1, 'advanced_cues': 1, 'dialogue': 0, 'unstructured_text': 0})
        self.assertTrue(view['structured'])

    def test_requests_read_a_given_prompt_or_a_saved_box_or_layer_prompt(self):
        line = json.dumps({'version': 1, 'boxes': [{'id': 'a', 'prompt': 'detailed_description:\n[Shot 1] Base.',
                                                    'layers': [{'id': 'v2', 'prompt': '[Shot 1] Layer.\nLighting: Dim.'}]}]})
        self.assertEqual(prompt_fields.request({'timeline': line, 'box': 'a'})['summary']['shots'], 1)
        layer = prompt_fields.request({'timeline': line, 'box': 'a', 'layer': 'v2'})
        self.assertEqual((layer['structured'], layer['summary']['advanced_cues']), (False, 1))
        tagged = prompt_fields.request({'prompt': 'subject_definitions:\n<Picture 1> is a hall.', 'tags': [{'tag': '<Picture 1>', 'name': 'image4'}]})
        self.assertEqual(tagged['sections'][0]['entries'][0]['value']['target'], '@image4')
        for body in ({'timeline': line, 'box': 'missing'}, {'timeline': line, 'box': 'a', 'layer': 'missing'}, {'prompt': 3}, {'prompt': '', 'tags': 'x'}):
            with self.subTest(body=body), self.assertRaises(ValueError):
                prompt_fields.request(body)

    def test_summary_counts_text_the_form_cannot_read_as_fields(self):
        case = next(case for case in FIXTURE['cases'] if case['name'] == 'advanced')
        summary = prompt_fields.inspect(case['prompt'], case['tags'])['summary']
        # Unresolved <Picture 2>, the repeated Gaze pair, prose after Shot 2's dialogue and a malformed Dialogue 1;
        # alignment, scene style and soundscape are ordinary fields.
        self.assertEqual(summary, {'shots': 3, 'cues': 6, 'advanced_cues': 2, 'dialogue': 3, 'unstructured_text': 5})
        unknown = prompt_fields.inspect('summary: One.\nsummary: Two.\ndetailed_description:\n[Shot 1] A room.')['summary']
        self.assertEqual(unknown['unstructured_text'], 2)
