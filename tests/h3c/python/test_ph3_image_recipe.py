import json
import unittest
from unittest import mock

from tests.h3c.continuity_support import enable_comfy_cpu

enable_comfy_cpu()

import nodes  # noqa: E402

from h3_continuity import image_recipe, ph3_image_nodes as ph3, story_context, stills, timeline  # noqa: E402

FILES = {"diffusion_models": ["p-h3-image_int8_convrot.safetensors"],
         "text_encoders": ["p-h3-image_text_encoder_bf16.safetensors"], "vae": ["p-h3-image_vae_int8_convrot.safetensors"]}
NODE = "5"


def at(input):
    return {"node": NODE, "input": input}


def recipe():
    """What web/h3c_stills.mjs captureRecipe returns for the node."""
    return {"version": 2, "adapter": "pixels", "label": "P-H3-Image", "reference_limit": 8, "reference_label": "<Picture {index}>",
            "output": [NODE, 0],
            "bindings": {"prompt": at("prompt"), "instruction": at("instruction"), "seed": at("seed"),
                         "size": {"width": [at("width")], "height": [at("height")]},
                         "references": [at(f"images.image_{i}") for i in range(1, 9)]}}


def workflow():
    return {"api": {NODE: {"class_type": "H3C_PH3ImageStill", "inputs": {
        "diffusion_model": "p-h3-image_int8_convrot.safetensors", "text_encoder": "p-h3-image_text_encoder_bf16.safetensors",
        "vae": "p-h3-image_vae_int8_convrot.safetensors", "prompt": "", "instruction": "", "seed": 1, "width": 1024,
        "height": 576, "prompt_upsampler": "off"}}}}


def reference(slot, roles, digest):
    return {"slot": slot, "roles": roles, "sha256": digest, "file": {"type": "input", "filename": slot + ".png"}}


def prepare(references=(), **request):
    body = {"request_id": "r1", "box": "b1", "target": {"kind": "first"}, "prompt": "She pours coffee.", "seed": 42,
            "size": {"width": 1280, "height": 704}, "frame": 0, **request}
    with mock.patch("folder_paths.get_filename_list", lambda folder: list(FILES.get(folder, []))), \
         mock.patch.dict(nodes.NODE_CLASS_MAPPINGS, {"H3C_PH3ImageStill": ph3.H3C_PH3ImageStill}):
        return image_recipe.prepare(recipe(), workflow(), body, list(references))


class PrepareTest(unittest.TestCase):
    def test_still_graph_keeps_only_two_of_ten_connected_recipe_pictures(self):
        saved = workflow()
        made = recipe()
        made['reference_limit'] = 10
        made['bindings']['references'] = [at(f'images.image_{n}') for n in range(1, 11)]
        for n in range(1, 11):
            saved['api'][f'picture{n}'] = {'class_type': 'IndependentImage', 'inputs': {}}
            saved['api'][NODE]['inputs'][f'images.image_{n}'] = [f'picture{n}', 0]
        document = {'boxes': [{'id': 'b1', 'frames': 96, 'prompt':
                     '[Shot 1] Use @still2 and @still7.\n[Shot 2] At 0:02.000, use @still9.'}]}
        body = dict(name='shot-reference-test', box='b1', target={'kind': 'first'},
                    timeline=json.dumps(document), workflow=saved, recipe=made)
        with mock.patch.object(image_recipe, '_image_port', return_value=False):
            result = stills.prepare(body)
        self.assertTrue(result.get('ok'), result)
        self.assertEqual([ref['slot'] for ref in result['provenance']['references']], ['still2', 'still7'])
        self.assertEqual({node for node in result['prompt'] if node.startswith('picture')}, {'picture2', 'picture7'})
        self.assertEqual(len([port for port in result['prompt'][NODE]['inputs'] if port.startswith('images.')]), 2)
        self.assertEqual(len([port for port in saved['api'][NODE]['inputs'] if port.startswith('images.')]), 10)

    def test_timeline_pictures_follow_the_selected_shot_or_frame_prompt(self):
        saved = workflow()
        saved['timeline_node'] = 'timeline'
        inputs = {f'images.image{n}': [f'picture{n}', 0] for n in range(1, 11)}
        for n in range(1, 11):
            saved['api'][f'picture{n}'] = {'class_type': 'IndependentImage', 'inputs': {}}
        clip = ('[Shot 1] @image2 beside @image7.\n'
                '[Shot 2] At 0:02.000, @image9 in close-up.')
        document = {'boxes': [{'id': 'b1', 'frames': 96, 'prompt': clip}]}
        body = dict(name='timeline-shot-test', box='b1', timeline=json.dumps(document),
                    workflow=saved, recipe=recipe())
        inputs.update(name=body['name'], timeline=body['timeline'])
        saved['api']['timeline'] = {'class_type': 'H3C_Timeline', 'inputs': inputs}
        with mock.patch.object(image_recipe, '_image_port', return_value=False):
            for target, prompt, wanted in [('first', '', {2, 7}), ('last', '', {9}),
                                           ('first', '@image4 alone.', {4}), ('first', 'Empty field.', set())]:
                with self.subTest(target=target, prompt=prompt):
                    result = stills.prepare(dict(body, target={'kind': target}, prompt=prompt))
                    self.assertTrue(result.get('ok'), result)
                    self.assertEqual({ref['slot'] for ref in result['provenance']['references']},
                                     {f'image{n}' for n in wanted})
                    self.assertEqual({node for node in result['prompt'] if node.startswith('picture')},
                                     {f'picture{n}' for n in wanted})

    def test_still_preparation_includes_cast_and_mentioned_images_without_anchors(self):
        document = {'boxes': [{'id': 'b1', 'frames': 22, 'prompt': ''}]}
        body = {'timeline': json.dumps(document), 'prompt': '@image17 close-up',
                'workflow': {'api': {}}, 'recipe': {}}
        parsed = timeline.parse(body['timeline'])
        wanted = reference('image17', ['image17'], 'a' * 64)
        cast = reference('image18', ['location: Hall'], 'b' * 64)
        with mock.patch('h3_continuity.reference_assets.references', return_value=[cast]), \
             mock.patch('h3_continuity.reference_assets.identity_slots', return_value=[]), \
             mock.patch.object(stills, '_pixel_references', return_value=[wanted]) as pixels, \
             mock.patch.object(stills, '_recipe_references', return_value=[]), \
             mock.patch.object(image_recipe, 'prepare', return_value={}) as prepared:
            stills._prepare_pixels(body, parsed, 0, 0, 'test')
        self.assertEqual(pixels.call_args.args[0]['prompt'].strip(), '@image17 close-up')
        self.assertEqual(prepared.call_args.args[3], [cast, wanted])

    def test_studio_candidates_keep_the_connected_lora_stack_and_its_ancestors(self):
        saved = workflow()
        saved['api'][NODE]['inputs']['lora_stack'] = ['stack', 0]
        saved['api']['stack'] = {'class_type': 'easy loraStack', 'inputs': {'optional_lora_stack': ['base', 0]}}
        saved['api']['base'] = {'class_type': 'easy loraStack', 'inputs': {'lora_1_name': 'style.safetensors'}}
        with mock.patch('folder_paths.get_filename_list', lambda folder: list(FILES.get(folder, []))), \
             mock.patch.dict(nodes.NODE_CLASS_MAPPINGS, {'H3C_PH3ImageStill': ph3.H3C_PH3ImageStill}):
            result = image_recipe.prepare(recipe(), saved, {'prompt': 'A still.'}, [])
        self.assertEqual(result['prompt'][NODE]['inputs']['lora_stack'], ['stack', 0])
        self.assertEqual(result['prompt']['stack'], saved['api']['stack'])
        self.assertEqual(result['prompt']['base'], saved['api']['base'])

    def test_automatic_size_resolves_linked_video_dimensions_at_runtime(self):
        saved = workflow()
        saved['api'][NODE]['inputs'].update(width=['video_size', 0], height=['video_size', 1])
        saved['api']['video_size'] = {'class_type': 'ResolutionSelector', 'inputs': {'megapixels': 0.7}}
        with mock.patch('folder_paths.get_filename_list', lambda folder: list(FILES.get(folder, []))), \
             mock.patch.dict(nodes.NODE_CLASS_MAPPINGS, {'H3C_PH3ImageStill': ph3.H3C_PH3ImageStill}):
            result = image_recipe.prepare(recipe(), saved, {'prompt': 'A still.', 'target': {'kind': 'first'}}, [])
        size = result['prompt']['h3c_ph3_size']
        self.assertEqual(size, {'class_type': 'H3C_PH3StillSize', 'inputs': {'width': ['video_size', 0], 'height': ['video_size', 1]}})
        self.assertEqual(result['prompt'][NODE]['inputs']['width'], ['h3c_ph3_size', 0])
        self.assertEqual(result['prompt'][NODE]['inputs']['height'], ['h3c_ph3_size', 1])
        self.assertIn('video_size', result['prompt'])

    def test_explicit_still_size_bypasses_automatic_size(self):
        result = prepare(size={'width': 1760, 'height': 2368})
        self.assertEqual((result['prompt'][NODE]['inputs']['width'], result['prompt'][NODE]['inputs']['height']), (1760, 2368))
        self.assertNotIn('h3c_ph3_size', result['prompt'])

    def test_character_reference_is_not_resized_or_padded_to_the_canvas(self):
        result = prepare([reference('image20', ['identity: Courier'], 'a' * 64)])
        source = result['prompt']['h3c_still_source_0']['inputs']
        self.assertEqual(set(source), {'source'})
        self.assertNotIn('size', json.loads(source['source']))

    def test_studio_resolution_setting_reaches_the_runtime_size_node(self):
        saved = workflow()
        saved['api'][NODE]['inputs']['studio_resolution'] = '4 MP'
        with mock.patch('folder_paths.get_filename_list', lambda folder: list(FILES.get(folder, []))), \
             mock.patch.dict(nodes.NODE_CLASS_MAPPINGS, {'H3C_PH3ImageStill': ph3.H3C_PH3ImageStill}):
            result = image_recipe.prepare(recipe(), saved, {'prompt': 'A still.'}, [])
        self.assertEqual(result['prompt']['h3c_ph3_size']['inputs']['resolution'], '4 MP')

    def test_timeline_reference_context_keeps_cast_roles_picture_titles_and_descriptions(self):
        entity = lambda id, kind, name, slot: dict(id=id, kind=kind, name=name, pictures=[slot], description=name, looks=[])
        document = {'boxes': [{'id': 'b1', 'frames': 22, 'prompt': '@image20 in @image23.'}],
                    'bible': {'entities': [entity('e1', 'character', 'Courier', 'image20'), entity('e2', 'place', 'Hall', 'image23')]},
                    'pictures': [dict(slot=slot, title=title, file={'type':'input', 'filename':slot+'.png'})
                                 for slot, title in [('image20','courier-sheet'), ('image23','hall-design')]],
                    'reference_descriptions': {'image20': {'text':'One white eyebrow.', 'source':'sha256:'+'image20.png'.ljust(64,'a')}}}
        parsed = timeline.parse(json.dumps(document))
        body = {'prompt':'@image20 in @image23.'}
        with mock.patch.object(stills, '_timeline_inputs', return_value={}), \
             mock.patch('h3_continuity.image_descriptions.lookup', return_value=None), \
             mock.patch.object(stills, 'pin_image', side_effect=lambda file: dict(file=file,sha256=file['filename'].ljust(64,'a'))):
            refs = stills._pixel_references(body, parsed, 0, 0, {})
        result = prepare(refs)
        prompt = result['provenance']['effective_prompt']
        self.assertEqual(prompt, 'She pours coffee.')
        identity = next(ref for ref in result['provenance']['references'] if ref['slot']=='image20')
        self.assertIn('identity: Courier', identity['roles'])
        self.assertEqual(identity['title'], 'courier-sheet')
        self.assertEqual(identity['description'], 'One white eyebrow.')

        for cached in (None, {'text':''}):
            with self.subTest(cached=cached):
                parsed.reference_descriptions['image20']['source']='sha256:stale'
                with mock.patch.object(stills, '_timeline_inputs', return_value={}), \
                     mock.patch('h3_continuity.image_descriptions.lookup', return_value=cached), \
                     mock.patch.object(stills, 'pin_image', side_effect=lambda file: dict(file=file,sha256=file['filename'].ljust(64,'a'))):
                    refs = stills._pixel_references(body, parsed, 0, 0, {})
                self.assertTrue(all(ref.get('description')!='One white eyebrow.' for ref in refs))

    def test_reference_context_survives_deduplication_and_uses_native_picture_labels(self):
        approved = reference('image20', ['appearance: Courier'], 'a'*64)
        contextual = {**reference('image20', ['identity: Courier'], 'a'*64),
                      'title':'courier-sheet', 'description':'Match @image20 and keep the light from @image23.'}
        result = prepare([approved, contextual, reference('image23', ['location: Hall'], 'b'*64)])
        prompt = result['provenance']['effective_prompt']
        self.assertEqual(prompt, 'She pours coffee.')
        identity = next(ref for ref in result['provenance']['references'] if ref['slot']=='image20')
        self.assertEqual(identity['title'], 'courier-sheet')
        self.assertEqual(identity['description'], 'Match @image20 and keep the light from @image23.')
        self.assertEqual(identity['label'], '<Picture 2>')

    def test_computed_reference_pixels_bypass_the_file_loader(self):
        saved = workflow()
        saved['api']['pixels'] = {'class_type':'IndependentImage', 'inputs':{}}
        ref = {'slot':'image20','roles':['identity: Courier'],'output':['pixels',0]}
        with mock.patch('folder_paths.get_filename_list', lambda folder: list(FILES.get(folder, []))), \
             mock.patch.dict(nodes.NODE_CLASS_MAPPINGS, {'H3C_PH3ImageStill': ph3.H3C_PH3ImageStill}):
            result = image_recipe.prepare(recipe(), saved, {'prompt':'A courier.'}, [ref])
        self.assertEqual(result['prompt'][NODE]['inputs']['images.image_1'], ['pixels',0])
        self.assertFalse(any(node['class_type']=='H3C_StillImageSource' for node in result['prompt'].values()))

    def test_text_to_image_binds_prompt_seed_and_size_on_the_node_and_saves_its_image(self):
        result = prepare()
        node = result["prompt"][NODE]["inputs"]
        self.assertEqual((node["prompt"], node["seed"], node["width"], node["height"]), ("She pours coffee.", 42, 1280, 704))
        self.assertEqual(result["prompt"]["h3c_still_output"]["inputs"]["images"], [NODE, 0])
        self.assertEqual(result["provenance"]["generator"], "P-H3-Image")
        self.assertEqual(result["provenance"]["effective_prompt"], "She pours coffee.")
        self.assertEqual(result['provenance']['prompt_policy'], 'clip-verbatim-v1')
        self.assertFalse([key for key in node if key.startswith("images.")])

    def test_the_location_goes_first_as_picture_1_and_every_reference_guides_a_new_image(self):
        result = prepare([reference("image2", ["identity: Mei"], "b" * 64), reference("image1", ["location: Kitchen"], "a" * 64)])
        node = result["prompt"][NODE]["inputs"]
        self.assertEqual([key for key in node if key.startswith("images.")], ["images.image_1", "images.image_2"])
        prompt = result["provenance"]["effective_prompt"]
        self.assertEqual(prompt, 'She pours coffee.')
        self.assertEqual(result['provenance']['references'][0]['roles'], ['location: Kitchen'])
        self.assertEqual(result['provenance']['references'][1]['roles'], ['identity: Mei'])
        self.assertEqual(result['provenance']['prompt_policy'], 'clip-verbatim-v1')
        self.assertEqual(node["images.image_1"], ["h3c_still_source_0", 0])

    def test_logical_references_in_the_prompt_become_picture_labels(self):
        result = prepare([reference("image1", ["location: Kitchen"], "a" * 64), reference("image2", ["identity: Mei"], "b" * 64)],
                         prompt="@image2 stands in @image1.")
        self.assertIn("<Picture 2> stands in <Picture 1>.", result["provenance"]["effective_prompt"])

    def test_more_than_eight_references_name_what_does_not_fit(self):
        refs = [reference(f"image{i}", [f"prop: Thing {i}"], f"{i:064x}") for i in range(1, 10)]
        with self.assertRaisesRegex(ValueError, "capacity 8 cannot fit 9"):
            prepare(refs)


class RendererTest(unittest.TestCase):
    def prompt(self, link, **extra):
        return {"1": {"class_type": "H3C_Timeline", "inputs": {"still_recipe": link}},
                "5": {"class_type": "H3C_PH3ImageStill", "inputs": {}}, **extra}

    def test_a_pixel_story_that_uses_the_p_h3_image_recipe_output_writes_image_prompts(self):
        self.assertEqual(story_context.renderer_for(self.prompt(["5", 1]), "1"), "image")

    def test_the_image_output_is_not_a_recipe(self):
        self.assertEqual(story_context.renderer_for(self.prompt(["5", 0]), "1"), "video")

    def test_a_video_output_downstream_keeps_video_writing(self):
        save = {"9": {"class_type": "SaveVideo", "inputs": {"video": ["1", 0]}}}
        self.assertEqual(story_context.renderer_for(self.prompt(["5", 1], **save), "1"), "video")

    def test_a_recipe_through_a_lazy_switch_is_found(self):
        prompt = self.prompt(["7", 0], **{"7": {"class_type": "LazySwitchKJ", "inputs": {"switch": True, "on_true": ["5", 1], "on_false": ["5", 0]}}})
        self.assertEqual(story_context.renderer_for(prompt, "1"), "image")
        prompt["7"]["inputs"]["switch"] = False
        self.assertEqual(story_context.renderer_for(prompt, "1"), "video")

    def test_existing_still_recipes_are_unchanged(self):
        pixels = '{"adapter": "pixels"}'
        prompt = {"1": {"class_type": "H3C_Timeline", "inputs": {"still_recipe": ["6", 0]}},
                  "6": {"class_type": "H3C_StillRecipe", "inputs": {"bindings": pixels}}}
        self.assertEqual(story_context.renderer_for(prompt, "1"), "image")
        prompt["6"]["inputs"]["bindings"] = '{"adapter": "h3"}'
        self.assertEqual(story_context.renderer_for(prompt, "1"), "video")


if __name__ == "__main__":
    unittest.main()
