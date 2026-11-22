import json
import unittest
from unittest import mock

from h3_continuity import image_recipe, reference_assets, stills

STYLE = ("Soft graphite shading and diffuse light. Cobalt blue belongs only to MIRA's coat. "
         "Characters move as living animated figures.")


def entity(id, kind, name, description, looks=()):
    return dict(id=id, kind=kind, name=name, pictures=[], description=description, looks=list(looks))


def document():
    return {'boxes': [{'id': 'b1', 'frames': 22, 'prompt': '',
                       'schedule': {'entities': ['e1', 'e2'], 'place': 'e3'}},
                      {'id': 'b2', 'frames': 22, 'prompt': '',
                       'schedule': {'entities': ['e1'], 'place': 'e3'}}],
            'bible': {'style': {'look': STYLE}, 'entities': [
                entity('e1', 'character', 'MIRA', 'A museum curator in a cobalt-blue coat.',
                       [{'from': 'b2', 'description': 'Her coat is buttoned.', 'pictures': []}]),
                entity('e2', 'character', 'Garden lizard', 'A speckled lizard with a curled tail.'),
                entity('e3', 'place', 'Museum Courtyard', 'A paved courtyard with a stone fountain.')]}}


SIZED = {'version': 2, 'adapter': 'pixels', 'bindings': {'size': {'width': [{}], 'height': [{}]}}}


def planned(key, approved_identity=None, saved=None, recipe=None, size=None, api=None):
    saved = saved or document()
    recipe = recipe or {'version': 2, 'adapter': 'pixels'}
    body = {'timeline': json.dumps(saved), 'recipe': recipe, 'workflow': {'api': api or {}}}
    row = next(r for r in reference_assets.catalog(saved, body) if r['key'] == key)
    body.update(asset_key=key, input_fingerprint=row['input_fingerprint'], prompt=row['prompt'])
    if size:
        body['size'] = size
    with mock.patch.object(stills, '_pixel_references', return_value=[]), \
         mock.patch.object(reference_assets, '_approved_pixels', return_value=approved_identity or []), \
         mock.patch.object(image_recipe, 'prepare', return_value={'ok': True}) as prepared:
        answer = reference_assets.prepare(body)
    assert answer == {'ok': True}, answer
    return prepared.call_args.args[2]


def planned_prompt(key, approved_identity=None):
    return planned(key, approved_identity)['prompt']


class CastSheetTest(unittest.TestCase):
    def test_the_default_layout_is_two_head_studies_and_four_whole_figures(self):
        prompt = planned_prompt('entity:e2')
        self.assertTrue(prompt.startswith('A 16:9 landscape character reference sheet for the character described below'), prompt)
        self.assertIn('plain ivory background', prompt)
        self.assertIn('two large head studies stacked', prompt)
        self.assertIn('four whole-figure studies', prompt)
        for column in ('Column 3, FRONT', 'Column 4, LEFT SIDE', 'Column 5, BACK', 'Column 6, RIGHT SIDE'):
            self.assertIn(column, prompt)
        self.assertIn('There is no text anywhere.', prompt)

    def test_the_description_goes_where_the_layout_puts_it(self):
        prompt = planned_prompt('entity:e2')
        self.assertIn('THE CHARACTER\nA speckled lizard with a curled tail.\n\nLEFT THIRD, TOP HALF', prompt)
        self.assertEqual(prompt.count('A speckled lizard with a curled tail.'), 1)
        self.assertNotIn('{description}', prompt)
        self.assertNotIn('{look}', prompt)

    def test_a_look_is_a_character_sheet_of_the_same_identity(self):
        identity = [{'slot': 'image17', 'roles': ['identity: MIRA'], 'sha256': 'a' * 64}]
        prompt = planned_prompt('entity:e1:look:b2', identity)
        self.assertTrue(prompt.startswith('A 16:9 landscape character reference sheet of the same character'), prompt)
        self.assertIn('same character as the identity reference', prompt)
        self.assertIn('Her coat is buttoned.', prompt)

    def test_style_sentences_about_other_cast_are_left_out(self):
        prompt = planned_prompt('entity:e2')
        self.assertIn('Soft graphite shading and diffuse light.', prompt)
        self.assertNotIn('MIRA', prompt)
        self.assertIn('MIRA', planned_prompt('entity:e1'))


    def test_a_style_sentence_about_another_character_without_naming_them_is_left_out(self):
        saved = document()
        saved['bible']['style']['look'] = ('Soft graphite shading and diffuse light. '
                                           "Cobalt blue appears only on the curator's coat.")
        prompt = planned('entity:e2', saved=saved)['prompt']
        self.assertIn('Soft graphite shading', prompt)
        self.assertNotIn('Cobalt blue', prompt)
        self.assertNotIn('coat', prompt)

    def test_the_creature_layout_is_one_head_and_a_two_by_two_of_headless_body_views(self):
        saved = with_overrides('entity:e2', {'layout': {'choice': 'creature'}})
        prompt = planned('entity:e2', saved=saved)['prompt']
        self.assertTrue(prompt.startswith('A 16:9 landscape creature reference sheet'), prompt)
        self.assertIn('2 rows and 2 columns', prompt)
        for view in ('Row 1, column 1: left side', 'Row 1, column 2: right side', 'Row 2, column 1: back',
                     'Row 2, column 2: top-down'):
            self.assertIn(view, prompt)
        self.assertIn('THE CREATURE\nA speckled lizard with a curled tail.\n', prompt)
        for human in (' arms', 'collarbone', 'five fingers', 'outfit', 'clothing'):
            self.assertNotIn(human, prompt)

    def test_a_layout_of_your_own_replaces_the_template(self):
        saved = with_overrides('entity:e2', {'layout': {'choice': 'custom', 'text': 'A turnaround on ivory.'}})
        prompt = planned('entity:e2', saved=saved)['prompt']
        self.assertTrue(prompt.startswith('A turnaround on ivory.\nA speckled lizard with a curled tail.'), prompt)
        self.assertNotIn('reference sheet', prompt)
        placed = with_overrides('entity:e2', {'layout': {'choice': 'custom', 'text': 'Sheet of {description} on ivory.'}})
        self.assertTrue(planned('entity:e2', saved=placed)['prompt'].startswith('Sheet of A speckled lizard with a curled tail. on ivory.'))
        empty = with_overrides('entity:e2', {'layout': {'choice': 'custom'}})
        self.assertTrue(planned('entity:e2', saved=empty)['prompt'].startswith('A speckled lizard with a curled tail.'))

    def test_every_cast_layout_is_sixteen_by_nine(self):
        for choice in ('human', 'creature', 'custom'):
            saved = with_overrides('entity:e2', {'layout': {'choice': choice}})
            self.assertEqual(planned('entity:e2', saved=saved, recipe=SIZED).get('size'), {'width': 2048, 'height': 1152}, choice)


class CastSheetSizeTest(unittest.TestCase):
    def test_a_sheet_is_16_9_unless_the_reference_sets_a_size(self):
        self.assertEqual(planned('entity:e2', recipe=SIZED).get('size'), {'width': 2048, 'height': 1152})
        own = {'width': 1024, 'height': 1536}
        self.assertEqual(planned('entity:e2', recipe=SIZED, size=own).get('size'), own)

    def test_a_workflow_without_size_inputs_keeps_its_own_size(self):
        self.assertNotIn('size', planned('entity:e2'))

    def test_a_location_sheet_is_16_9_too_unless_it_sets_a_size(self):
        self.assertEqual(planned('entity:e3', recipe=SIZED).get('size'), {'width': 2048, 'height': 1152})
        own = {'width': 1024, 'height': 1536}
        self.assertEqual(planned('entity:e3', recipe=SIZED, size=own).get('size'), own)
        self.assertNotIn('size', planned('entity:e3'))

    def graph_sized(self, width, height):
        recipe = {'version': 2, 'adapter': 'pixels', 'bindings': {'size': {
            'width': [{'node': 'gen', 'input': 'width'}], 'height': [{'node': 'gen', 'input': 'height'}]}}}
        return recipe, {'gen': {'inputs': {'width': width, 'height': height}}}

    def assertSixteenByNine(self, size, area):
        self.assertEqual((size['width'] % 32, size['height'] % 32), (0, 0), size)
        self.assertEqual(size['width'] * 9, size['height'] * 16, size)
        # The size only follows the workflow loosely: the nearest exact 16:9 step on the 32 grid.
        self.assertTrue(0.7 < size['width'] * size['height'] / area < 1.45, size)

    def test_a_sheet_is_exactly_16_9_near_the_size_of_the_connected_workflow(self):
        for width, height in ((1088, 1920), (2160, 3840), (4000, 6000), (1920, 1088)):
            recipe, api = self.graph_sized(width, height)
            for key in ('entity:e2', 'entity:e3'):
                size = planned(key, recipe=recipe, api=api)['size']
                self.assertSixteenByNine(size, width * height)

    def test_the_area_is_read_through_a_native_primitive(self):
        recipe, api = self.graph_sized(['p1', 0], ['p2', 0])
        api.update(p1={'class_type': 'PrimitiveInt', 'inputs': {'value': 2160}},
                   p2={'class_type': 'PrimitiveInt', 'inputs': {'value': 3840}})
        self.assertSixteenByNine(planned('entity:e2', recipe=recipe, api=api)['size'], 2160 * 3840)

    def test_an_unreadable_workflow_size_falls_back_to_the_default_16_9(self):
        recipe, api = self.graph_sized(['math', 0], ['math', 1])
        api['math'] = {'class_type': 'ComfyMathExpression', 'inputs': {}}
        self.assertEqual(planned('entity:e2', recipe=recipe, api=api)['size'], {'width': 2048, 'height': 1152})
        recipe, api = self.graph_sized(16, 9)
        self.assertEqual(planned('entity:e2', recipe=recipe, api=api)['size'], {'width': 2048, 'height': 1152})

    def test_a_composed_scene_and_an_object_keep_the_workflow_size(self):
        saved = document()
        saved['bible']['entities'].append(entity('e4', 'prop', 'Brass key', 'A small brass key.'))
        saved['boxes'][0]['schedule']['props'] = ['e4']
        self.assertNotIn('size', planned('entity:e4', saved=saved, recipe=SIZED))


def with_overrides(key, overrides):
    saved = document()
    saved['reference_preparation'] = {'version': 1, 'generate': {}, 'requests': [],
                                      'assets': [{'key': key, 'category': 'cast', 'role': 'identity',
                                                  'part_overrides': overrides}]}
    return saved


def row_of(saved, key):
    return next(r for r in reference_assets.catalog(saved) if r['key'] == key)


class PromptPartsTest(unittest.TestCase):
    def test_a_row_lists_every_text_the_studio_adds_in_the_order_it_is_sent(self):
        parts = row_of(document(), 'entity:e2')['prompt_parts']
        self.assertEqual([p['id'] for p in parts], ['layout', 'style'])
        self.assertEqual([p['where'] for p in parts], ['before', 'after'])
        self.assertTrue(parts[0]['text'].startswith('A 16:9 landscape character reference sheet'))
        self.assertTrue(parts[1]['text'].startswith('Visual style: Soft graphite shading'))
        self.assertTrue(all(p['enabled'] and not p['edited'] for p in parts))
        self.assertEqual([p['id'] for p in row_of(document(), 'entity:e3')['prompt_parts']], ['layout', 'style', 'empty'])

    def test_the_prompt_is_what_the_parts_say(self):
        saved = document()
        parts = row_of(saved, 'entity:e2')['prompt_parts']
        prompt = planned('entity:e2')['prompt']
        layout = parts[0]['text'].replace('{description}', 'A speckled lizard with a curled tail.')
        self.assertEqual(prompt, '\n'.join([layout, parts[1]['text']]))

    def test_a_cast_layout_offers_the_human_creature_and_custom_choices(self):
        layout = row_of(document(), 'entity:e2')['prompt_parts'][0]
        self.assertEqual((layout['choice'], layout['choices']), ('human', ['human', 'creature', 'custom']))
        saved = document()
        saved['bible']['entities'].append(entity('e4', 'prop', 'Brass key', 'A small brass key.'))
        saved['boxes'][0]['schedule']['props'] = ['e4']
        self.assertNotIn('choices', row_of(saved, 'entity:e4')['prompt_parts'][0])
        saved = with_overrides('entity:e2', {'layout': {'choice': 'creature'}})
        self.assertEqual(row_of(saved, 'entity:e2')['prompt_parts'][0]['choice'], 'creature')
        self.assertFalse(row_of(saved, 'entity:e2')['prompt_parts'][0]['edited'])

    def test_a_part_can_be_switched_off_for_one_reference(self):
        saved = with_overrides('entity:e2', {'style': {'enabled': False}})
        self.assertNotIn('Visual style', planned('entity:e2', saved=saved)['prompt'])
        self.assertIn('Visual style', planned('entity:e1')['prompt'])
        self.assertFalse(row_of(saved, 'entity:e2')['prompt_parts'][1]['enabled'])

    def test_a_part_can_be_rewritten_for_one_reference(self):
        saved = with_overrides('entity:e2', {'layout': {'text': 'A creature turnaround on ivory.'}})
        prompt = planned('entity:e2', saved=saved)['prompt']
        self.assertTrue(prompt.startswith('A creature turnaround on ivory.\n'), prompt)
        self.assertNotIn('six equal-width', prompt)
        self.assertTrue(row_of(saved, 'entity:e2')['prompt_parts'][0]['edited'])
        self.assertEqual(saved['bible']['style']['look'], STYLE)

    def test_a_sheet_without_its_layout_is_not_forced_to_16_9(self):
        saved = with_overrides('entity:e2', {'layout': {'enabled': False}})
        self.assertNotIn('size', planned('entity:e2', saved=saved, recipe=SIZED))

    def test_edits_change_the_design_only_for_that_reference(self):
        plain = row_of(document(), 'entity:e2')['input_fingerprint']
        edited = row_of(with_overrides('entity:e2', {'style': {'enabled': False}}), 'entity:e2')['input_fingerprint']
        self.assertNotEqual(plain, edited)
        self.assertEqual(row_of(document(), 'entity:e1')['input_fingerprint'],
                         row_of(with_overrides('entity:e2', {'style': {'enabled': False}}), 'entity:e1')['input_fingerprint'])

    def test_bad_edits_are_refused(self):
        for bad in ({'nope': {'enabled': False}}, {'style': {'enabled': 'no'}}, {'style': {'text': 3}}, {'style': 'x'},
                    {'layout': {'choice': 'dragon'}}, {'style': {'choice': 'human'}}):
            with self.assertRaises(ValueError):
                reference_assets.catalog(with_overrides('entity:e2', bad))


class LocationLayoutTest(unittest.TestCase):
    def location(self, overrides):
        saved = document()
        saved['reference_preparation'] = {'version': 1, 'generate': {}, 'requests': [],
                                          'assets': [{'key': 'entity:e3', 'category': 'locations', 'role': 'location',
                                                      'part_overrides': overrides}]}
        return saved

    def test_a_location_offers_the_grid_of_angles_and_a_layout_of_your_own(self):
        layout = row_of(document(), 'entity:e3')['prompt_parts'][0]
        self.assertEqual((layout['choice'], layout['choices']), ('grid', ['grid', 'custom']))
        self.assertTrue(layout['text'].startswith('A location reference sheet'))
        self.assertTrue(layout['text'].endswith('Location: {description}'))

    def test_the_description_goes_where_the_grid_puts_it(self):
        prompt = planned_prompt('entity:e3')
        self.assertIn('Location: A paved courtyard with a stone fountain.', prompt)
        self.assertNotIn('{description}', prompt)

    def test_a_location_layout_of_your_own_replaces_the_grid(self):
        saved = self.location({'layout': {'choice': 'custom', 'text': 'One wide establishing view.'}})
        prompt = planned('entity:e3', saved=saved)['prompt']
        self.assertTrue(prompt.startswith('One wide establishing view.\nA paved courtyard with a stone fountain.'), prompt)
        self.assertNotIn('2 rows and 2 columns', prompt)
        self.assertIn('The place is empty in every panel.', prompt)

    def test_a_character_layout_is_refused_for_a_location(self):
        with self.assertRaises(ValueError):
            reference_assets.catalog(self.location({'layout': {'choice': 'human'}}))
        with self.assertRaises(ValueError):
            reference_assets.catalog(with_overrides('entity:e2', {'layout': {'choice': 'grid'}}))


class LocationGridTest(unittest.TestCase):
    def test_location_is_an_empty_two_by_two_grid_of_camera_angles(self):
        prompt = planned_prompt('entity:e3')
        self.assertTrue(prompt.startswith('A location reference sheet'), prompt)
        self.assertIn('2 rows and 2 columns', prompt)
        for cell in ('row 1, column 1', 'row 1, column 2', 'row 2, column 1', 'row 2, column 2'):
            self.assertIn(cell, prompt)
        self.assertIn('A paved courtyard with a stone fountain.', prompt)
        self.assertIn('no people, characters, animals or creatures', prompt)
        self.assertNotIn('MIRA', prompt)
        self.assertNotIn('Characters move', prompt)

    def test_a_place_with_an_interior_gets_one_interior_camera(self):
        prompt = planned_prompt('entity:e3')
        self.assertIn('If the place has an interior', prompt)
        self.assertIn('row 2, column 2, instead shows that interior from the inside', prompt)


class ObjectGridTest(unittest.TestCase):
    def test_object_is_a_two_by_two_ivory_grid_of_angles_of_only_the_object(self):
        saved = document()
        saved['bible']['entities'].append(entity('e4', 'prop', 'Brass key', 'A long steel pry bar, sharpened at one end.'))
        saved['boxes'][0]['schedule']['props'] = ['e4']
        body = {'timeline': json.dumps(saved), 'recipe': {'version': 2, 'adapter': 'pixels'}, 'workflow': {'api': {}}}
        row = next(r for r in reference_assets.catalog(saved, body) if r['key'] == 'entity:e4')
        body.update(asset_key=row['key'], input_fingerprint=row['input_fingerprint'], prompt=row['prompt'])
        with mock.patch.object(stills, '_pixel_references', return_value=[]),              mock.patch.object(image_recipe, 'prepare', return_value={'ok': True}) as prepared:
            reference_assets.prepare(body)
        prompt = prepared.call_args.args[2]['prompt']
        self.assertTrue(prompt.startswith('An object reference sheet'), prompt)
        self.assertIn('plain ivory background', prompt)
        self.assertIn('2 rows and 2 columns', prompt)
        for cell in ('row 1, column 1', 'row 1, column 2', 'row 2, column 1', 'row 2, column 2'):
            self.assertIn(cell, prompt)
        self.assertIn('Only the object appears', prompt)
        self.assertIn('A long steel pry bar, sharpened at one end.', prompt)


if __name__ == '__main__':
    unittest.main()
