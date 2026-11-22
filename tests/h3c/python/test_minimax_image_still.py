import asyncio
import json
import unittest
from unittest import mock

import torch

from tests.h3c.continuity_support import enable_comfy_cpu
enable_comfy_cpu()

from h3_continuity import minimax_image_nodes as image, image_recipe, story_context, stills
from tests.h3c.python.test_ph3_image_recipe import recipe, reference

FILES = {'diffusion_models': ['minimax_h3_image_pruned_w4a8.safetensors', 'p-h3-image_int8_convrot.safetensors'],
         'text_encoders': ['qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors', 'p-h3-image_text_encoder_bf16.safetensors'],
         'vae': ['minimax_h3_image_vae_fp16.safetensors', 'minimax_h3_video_vae_fp16.safetensors']}
ARGS = dict(diffusion_model=FILES['diffusion_models'][0], text_encoder=FILES['text_encoders'][0],
            vae=FILES['vae'][0], prompt='A kitchen at dawn.', instruction='', seed=42, width=2048, height=2048)


class MiniMaxImageTest(unittest.TestCase):
    def setUp(self):
        self.files = mock.patch('folder_paths.get_filename_list', lambda folder: FILES.get(folder, []))
        self.files.start()
        self.addCleanup(self.files.stop)

    def test_clip_candidate_model_text_is_only_the_clip_even_with_reference_metadata_and_node_instruction(self):
        clip = 'integrated_multimodal_description:\n[Shot 1] A quiet library. Nobody.\n\noverall_soundscape:\nWind.\n\nnon_diegetic_music:\nN/A'
        saved = {'api': {'5': {'class_type': 'H3C_MiniMaxH3ImageStill', 'inputs': {**ARGS, 'instruction': 'Add a person.'}}}}
        ref = {**reference('image20', ['location: Field'], 'a' * 64), 'description': 'Shared hidden style with MIRA holding a blue umbrella.'}
        with mock.patch.dict('nodes.NODE_CLASS_MAPPINGS', {'H3C_MiniMaxH3ImageStill': image.H3C_MiniMaxH3ImageStill}):
            result = image_recipe.prepare(recipe(), saved, {'box': 'b1', 'prompt': clip}, [ref])
        native = result['prompt']['5']['inputs']
        self.assertEqual(native['prompt'], clip)
        self.assertEqual(native['instruction'], '')
        self.assertEqual(native['images.image_1'], ['h3c_still_source_0', 0])
        self.assertEqual(result['provenance']['effective_prompt'], clip)
        self.assertEqual(result['provenance']['prompt_policy'], 'clip-verbatim-v1')
        self.assertEqual(result['provenance']['prompt_enhancer'], 'off')

    def test_reference_stills_run_the_official_edit_prompt_enhancer_before_conditioning(self):
        files = {**FILES, 'text_encoders': [*FILES['text_encoders'], 'qwen3.5_9b_int8_convrot.safetensors']}
        pixels = torch.zeros(1, 8, 8, 3)
        with mock.patch('folder_paths.get_filename_list', lambda folder: files.get(folder, [])), \
             mock.patch.dict('nodes.NODE_CLASS_MAPPINGS', {'MiniMaxH3ImageConditioning': object, 'TextGenerateV2': object}):
            result = image.H3C_MiniMaxH3ImageStill.execute(**{**ARGS, 'prompt': 'An empty "field".', 'width': 1152, 'height': 640},
                                                           megapixels=16, images={'image_1': pixels}, prompt_enhancer='auto')
        graph = result.expand
        by_class = {node['class_type']: (key, node['inputs']) for key, node in graph.items()}
        loader = next(key for key, node in graph.items()
                      if node['class_type'] == 'CLIPLoader' and node['inputs']['clip_name'].startswith('qwen3.5_'))
        _, generate = by_class['TextGenerateV2']
        caption_id, caption = by_class['H3C_MiniMaxPromptCaption']
        _, cond = by_class['MiniMaxH3ImageConditioning']
        task = image.enhancer_text('edit_task.txt').replace(
            '{input text}', 'User Editing Instruction: "An empty \\"field\\"."\nUser Aspect Ratio Selection: 56:31')
        self.assertEqual(generate['prompt'], task)
        self.assertEqual(generate['system_prompt'], image.enhancer_text('system.txt'))
        self.assertEqual(generate['clip'], [loader, 0])
        self.assertEqual(graph[loader]['inputs'], {'clip_name': 'qwen3.5_9b_int8_convrot.safetensors', 'type': 'minimax', 'device': 'default'})
        self.assertEqual(generate['images.image1'], cond['images.image_1'])
        self.assertEqual({key: generate[key] for key in ('max_length', 'sampling_mode', 'sampling_mode.temperature', 'sampling_mode.top_k',
                          'sampling_mode.top_p', 'sampling_mode.min_p', 'sampling_mode.repetition_penalty',
                          'sampling_mode.presence_penalty', 'sampling_mode.seed', 'thinking', 'use_default_template')},
                         {'max_length': 8196, 'sampling_mode': 'on', 'sampling_mode.temperature': 1.0, 'sampling_mode.top_k': 20,
                          'sampling_mode.top_p': 0.95, 'sampling_mode.min_p': 0.0, 'sampling_mode.repetition_penalty': 1.0,
                          'sampling_mode.presence_penalty': 0.0, 'sampling_mode.seed': 42, 'thinking': True,
                          'use_default_template': True})
        self.assertEqual(caption['text'], [by_class['TextGenerateV2'][0], 0])
        self.assertEqual(cond['prompt'], [caption_id, 0])
        self.assertEqual((cond['width'], cond['height']), (5376, 2976))

    def test_enhancer_is_off_by_default_and_auto_prefers_the_official_model(self):
        files = {**FILES, 'text_encoders': ['qwen3.5_9b_int8_convrot.safetensors', 'qwen3.5_9b_w4a8_gptq.safetensors', *FILES['text_encoders']]}
        pixels = torch.zeros(1, 8, 8, 3)
        with mock.patch('folder_paths.get_filename_list', lambda folder: files.get(folder, [])), \
             mock.patch.dict('nodes.NODE_CLASS_MAPPINGS', {'MiniMaxH3ImageConditioning': object, 'TextGenerateV2': object}):
            options = next(item for item in image.H3C_MiniMaxH3ImageStill.define_schema().inputs if item.id == 'prompt_enhancer')
            self.assertEqual(options.options, ['off', 'auto', 'qwen3.5_9b_w4a8_gptq.safetensors', 'qwen3.5_9b_int8_convrot.safetensors'])
            self.assertEqual(options.default, 'off')
            self.assertTrue(options.optional)
            def run(**kwargs):
                return {node['class_type']: node['inputs'] for node in image.H3C_MiniMaxH3ImageStill.execute(**ARGS, **kwargs).expand.values()}
            for setting in ({}, {'prompt_enhancer': None}, {'prompt_enhancer': 'off'}):
                with self.subTest(setting=setting):
                    plain = run(images={'image_1': pixels}, **setting)
                    self.assertNotIn('TextGenerateV2', plain)
                    self.assertEqual(plain['MiniMaxH3ImageConditioning']['prompt'], ARGS['prompt'])
            graph = image.H3C_MiniMaxH3ImageStill.execute(**ARGS, images={'image_1': pixels}, prompt_enhancer='auto').expand
            loaders = [n['inputs']['clip_name'] for n in graph.values() if n['class_type'] == 'CLIPLoader']
            self.assertEqual(loaders, [FILES['text_encoders'][0], 'qwen3.5_9b_w4a8_gptq.safetensors'])
            self.assertNotIn('TextGenerateV2', run(prompt_enhancer='auto'))
            text_only = run(prompt_enhancer='qwen3.5_9b_int8_convrot.safetensors')
            self.assertEqual(text_only['TextGenerateV2']['prompt'], image.enhancer_text('t2i_task.txt').replace('{input text}', ARGS['prompt']))
            self.assertNotIn('images.image1', text_only['TextGenerateV2'])
            with self.assertRaisesRegex(ValueError, 'prompt enhancer'):
                run(prompt_enhancer='qwen3.5_missing.safetensors')
        with mock.patch('folder_paths.get_filename_list', lambda folder: files.get(folder, [])), \
             mock.patch.dict('nodes.NODE_CLASS_MAPPINGS', {'MiniMaxH3ImageConditioning': object}, clear=True):
            with self.assertRaisesRegex(ValueError, 'TextGenerateV2'):
                image.H3C_MiniMaxH3ImageStill.execute(**ARGS, images={'image_1': pixels}, prompt_enhancer='auto')

    def test_enhancer_caption_is_required(self):
        caption = image.H3C_MiniMaxPromptCaption.execute
        self.assertEqual(caption('{"expanded_caption":"An empty field.","target_aspect_ratio":"16:9"}').result[0], 'An empty field.')
        self.assertEqual(caption('Done.\n```json\n{"expanded_caption": " A \\"quiet\\" field. "}\n```').result[0], 'A "quiet" field.')
        for text in ('', 'An empty field.', '{"expanded_caption": ""}', '{"aspect_ratio": "16:9"}', '{"expanded_caption": "unterminated'):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, 'expanded_caption'):
                caption(text)
        from h3_continuity.extension import H3ContinuityExtension
        self.assertIn(image.H3C_MiniMaxPromptCaption, asyncio.run(H3ContinuityExtension().get_node_list()))

    def test_a_location_sheet_reaches_clip_stills_as_separate_views_before_cast_pictures(self):
        import tempfile
        from pathlib import Path
        from PIL import Image
        from tests.h3c.python.test_reference_panels import picture
        saved = {'api': {'5': {'class_type': 'H3C_MiniMaxH3ImageStill', 'inputs': {**ARGS}}}}
        refs = [reference('image17', ['identity: MIRA'], 'b' * 64), reference('image20', ['location: Courtyard'], 'a' * 64)]
        with tempfile.TemporaryDirectory() as folder:
            sheet = Path(folder) / 'sheet.png'
            Image.fromarray(picture(3000, 1600, [(1490, 1512, 0, 1600)], [(790, 810, 0, 3000)])).save(sheet)
            paths = {'image20.png': sheet, 'image17.png': Path(folder) / 'missing.png'}
            def prepare(request, references, limit=8):
                with mock.patch('h3_continuity.reference_replacements.file_path', lambda file, target: paths[file['filename']]), \
                     mock.patch.dict('nodes.NODE_CLASS_MAPPINGS', {'H3C_MiniMaxH3ImageStill': image.H3C_MiniMaxH3ImageStill}):
                    return image_recipe.prepare({**recipe(), 'reference_limit': limit}, saved, request, references)
            result = prepare({'box': 'b1', 'prompt': '@image17 crosses @image20. Nobody else.'}, refs)
            native, graph = result['prompt']['5']['inputs'], result['prompt']
            views = [native[f'images.image_{i}'] for i in range(1, 5)]
            self.assertEqual([graph[view[0]]['class_type'] for view in views], ['ImageCrop'] * 4)
            self.assertTrue(all(graph[view[0]]['inputs']['image'] == ['h3c_still_source_0', 0] for view in views))
            self.assertEqual(native['images.image_5'], ['h3c_still_source_1', 0])
            location, cast = result['provenance']['references']
            self.assertEqual(location['label'], '<Picture 1>, <Picture 2>, <Picture 3>, <Picture 4>')
            self.assertEqual([view['label'] for view in location['views']], ['<Picture 1>', '<Picture 2>', '<Picture 3>', '<Picture 4>'])
            self.assertEqual(location['port'], {'node': '5', 'input': 'images.image_1'})
            self.assertEqual(cast['label'], '<Picture 5>')
            self.assertNotIn('views', cast)
            self.assertEqual(native['prompt'], '<Picture 5> crosses <Picture 1>, <Picture 2>, <Picture 3> and <Picture 4>. Nobody else.')
            crowded = prepare({'box': 'b1', 'prompt': 'A crossing.'}, refs, limit=3)['prompt']['5']['inputs']
            self.assertEqual([crowded[f'images.image_{i}'][0] for i in range(1, 4)], ['h3c_still_view_0_0', 'h3c_still_view_0_1', 'h3c_still_source_1'])
            whole = prepare({'box': 'b1', 'asset_key': 'entity:e5', 'prompt': 'A sheet.'}, refs[1:])['prompt']['5']['inputs']
            self.assertEqual(whole['images.image_1'], ['h3c_still_source_0', 0])

    def test_server_uses_submitted_frame_text_or_falls_back_to_clip(self):
        clip = 'A quiet library. Nobody.'
        saved = {'api': {'5': {'class_type': 'H3C_MiniMaxH3ImageStill', 'inputs': {**ARGS}}}}
        body = dict(name='clip-verbatim-test', box='b1', target={'kind':'first'},
                    timeline=json.dumps({'prompt':'MIRA carries a blue umbrella.', 'boxes':[{'id':'b1','frames':22,'prompt':clip}]}),
                    workflow=saved, recipe=recipe())
        with mock.patch.dict('nodes.NODE_CLASS_MAPPINGS', {'H3C_MiniMaxH3ImageStill': image.H3C_MiniMaxH3ImageStill}):
            for prompt, expected in [('A close-up of an open book.', 'A close-up of an open book.'), ('   ', clip), (None, clip)]:
                with self.subTest(prompt=prompt):
                    result = stills.prepare(body if prompt is None else dict(body, prompt=prompt))
                    self.assertTrue(result.get('ok'), result)
                    self.assertEqual(result['prompt']['5']['inputs']['prompt'], expected)

    def test_schema_filters_image_weights_and_keeps_shared_video_encoder(self):
        schema = {item.id: item.options for item in image.H3C_MiniMaxH3ImageStill.define_schema().inputs if hasattr(item, 'options')}
        for component, folder in [('diffusion_model', 'diffusion_models'), ('text_encoder', 'text_encoders'), ('vae', 'vae')]:
            self.assertEqual(schema[component], [FILES[folder][0]])
        from h3_continuity.extension import H3ContinuityExtension
        self.assertIn(image.H3C_MiniMaxH3ImageStill, asyncio.run(H3ContinuityExtension().get_node_list()))

    def test_native_six_step_graph_and_reference_order(self):
        a, b = torch.zeros(1, 8, 8, 3), torch.ones(1, 8, 8, 3)
        with mock.patch.dict('nodes.NODE_CLASS_MAPPINGS', {'MiniMaxH3ImageConditioning': object}):
            result = image.H3C_MiniMaxH3ImageStill.execute(**{**ARGS, 'instruction': 'Film still.'}, images={'image_2': b, 'image_1': a})
        graph = result.expand
        by_class = {node['class_type']: node['inputs'] for node in graph.values()}
        sampler = by_class['KSampler']
        self.assertEqual((sampler['steps'], sampler['cfg'], sampler['sampler_name'], sampler['scheduler']), (6, 1, 'euler', 'simple'))
        cond = by_class['MiniMaxH3ImageConditioning']
        self.assertEqual(cond['prompt'], 'A kitchen at dawn.\n\nFilm still.')
        self.assertEqual([key for key in cond if key.startswith('images.')], ['images.image_1', 'images.image_2'])
        reference_nodes = [n['inputs'] for n in graph.values() if n['class_type']=='ResizeImageMaskNode']
        self.assertEqual(len(reference_nodes),4)
        self.assertIs(reference_nodes[0]['input'], a)
        self.assertIn('vae', cond)
        self.assertEqual(result.result[1]['label'], 'MiniMax H3 Image')

    def test_reference_images_follow_official_four_mp_resize_while_output_stays_native_twenty_mp(self):
        pixels = torch.zeros(1,8,8,3)
        with mock.patch.dict('nodes.NODE_CLASS_MAPPINGS', {'MiniMaxH3ImageConditioning': object}):
            result = image.H3C_MiniMaxH3ImageStill.execute(**{**ARGS,'width':1152,'height':640},
                megapixels=20, images={'image_1':pixels})
        graph = result.expand
        cond = next(n['inputs'] for n in graph.values() if n['class_type']=='MiniMaxH3ImageConditioning')
        self.assertEqual((cond['width'],cond['height']),(6016,3328))
        scaled = [(key,n['inputs']) for key,n in graph.items() if n['class_type']=='ResizeImageMaskNode']
        self.assertEqual(len(scaled),2)
        self.assertIs(scaled[0][1]['input'],pixels)
        self.assertEqual((scaled[0][1]['resize_type'],scaled[0][1]['resize_type.megapixels'],scaled[0][1]['scale_method']),('scale total pixels',4.0,'area'))
        self.assertEqual(scaled[1][1]['input'],[scaled[0][0],0])
        self.assertEqual((scaled[1][1]['resize_type'],scaled[1][1]['resize_type.multiple']),('scale to multiple',32))
        self.assertEqual(cond['images.image_1'],[scaled[1][0],0])
        self.assertFalse(any(n['class_type']=='ImageScale' for n in graph.values()))

    def test_large_text_only_requests_keep_native_resolution(self):
        with mock.patch.dict('nodes.NODE_CLASS_MAPPINGS', {'MiniMaxH3ImageConditioning': object}):
            result = image.H3C_MiniMaxH3ImageStill.execute(**{**ARGS,'width':1152,'height':640},megapixels=20)
        cond = next(n['inputs'] for n in result.expand.values() if n['class_type']=='MiniMaxH3ImageConditioning')
        self.assertEqual((cond['width'],cond['height']),(6016,3328))
        self.assertFalse(any(n['class_type']=='ImageScale' for n in result.expand.values()))

    def test_megapixels_keep_the_width_height_ratio_and_set_the_area(self):
        pixels = torch.zeros(1, 8, 8, 3)
        cases = [(1152, 640, 20.0, (6016, 3328)), (1344, 768, 4.0, (2656, 1504)), (2048, 2048, 0.0, (2048, 2048)),
                 (1000, 563, 16.0, (5344, 3008))]
        for width, height, megapixels, expected in cases:
            with self.subTest(width=width, height=height, megapixels=megapixels), \
                 mock.patch.dict('nodes.NODE_CLASS_MAPPINGS', {'MiniMaxH3ImageConditioning': object}):
                graph = image.H3C_MiniMaxH3ImageStill.execute(**{**ARGS, 'width': width, 'height': height},
                                                              images={'image_1': pixels}, megapixels=megapixels).expand
            cond = next(node['inputs'] for node in graph.values() if node['class_type'] == 'MiniMaxH3ImageConditioning')
            self.assertEqual((cond['width'], cond['height']), expected)
        self.assertEqual(image.H3C_MiniMaxH3ImageStill.INPUT_TYPES()['optional']['megapixels'][0], 'FLOAT')
        with mock.patch.dict('nodes.NODE_CLASS_MAPPINGS', {'MiniMaxH3ImageConditioning': object}):
            with self.assertRaisesRegex(ValueError, 'side above 8192'):
                image.H3C_MiniMaxH3ImageStill.execute(**{**ARGS, 'width': 4096, 'height': 256}, megapixels=20.0)

    def test_lora_stack_is_an_optional_connection(self):
        schema = image.H3C_MiniMaxH3ImageStill.define_schema()
        socket = next((item for item in schema.inputs if item.id == 'lora_stack'), None)
        self.assertIsNotNone(socket)
        self.assertTrue(socket.optional)
        self.assertEqual(image.H3C_MiniMaxH3ImageStill.INPUT_TYPES()['optional']['lora_stack'][0], 'LORA_STACK')

    def test_loras_patch_model_and_clip_in_stack_order(self):
        with mock.patch.dict('nodes.NODE_CLASS_MAPPINGS', {'MiniMaxH3ImageConditioning': object}):
            graph = image.H3C_MiniMaxH3ImageStill.execute(**ARGS, lora_stack=[
                ('style.safetensors', 0.7, 0.2), ('detail.safetensors', -0.3, 0.0)]).expand
        loaders = [(key, node['inputs']) for key, node in graph.items() if node['class_type'] == 'LoraLoader']
        self.assertEqual(len(loaders), 2)
        (first_id, first), (second_id, second) = loaders
        by_type = {node['class_type']: key for key, node in graph.items()}
        self.assertEqual(first, {'model': [by_type['UNETLoader'], 0], 'clip': [by_type['CLIPLoader'], 0],
                                'lora_name': 'style.safetensors', 'strength_model': 0.7, 'strength_clip': 0.2})
        self.assertEqual(second, {'model': [first_id, 0], 'clip': [first_id, 1],
                                 'lora_name': 'detail.safetensors', 'strength_model': -0.3, 'strength_clip': 0.0})
        self.assertEqual(graph[by_type['KSampler']]['inputs']['model'], [second_id, 0])
        self.assertEqual(graph[by_type['MiniMaxH3ImageConditioning']]['inputs']['clip'], [second_id, 1])

    def test_empty_or_disabled_stack_keeps_unpatched_model_and_clip(self):
        for stack in (None, [], [('None', 1.0, 1.0), ('', 1.0, 1.0), ('unused.safetensors', 0.0, 0.0)]):
            with self.subTest(stack=stack), mock.patch.dict('nodes.NODE_CLASS_MAPPINGS', {'MiniMaxH3ImageConditioning': object}):
                graph = image.H3C_MiniMaxH3ImageStill.execute(**ARGS, lora_stack=stack).expand
                by_type = {node['class_type']: key for key, node in graph.items()}
                self.assertNotIn('LoraLoader', by_type)
                self.assertEqual(graph[by_type['KSampler']]['inputs']['model'], [by_type['UNETLoader'], 0])
                self.assertEqual(graph[by_type['MiniMaxH3ImageConditioning']]['inputs']['clip'], [by_type['CLIPLoader'], 0])

    def test_studio_candidates_keep_connected_stack_and_ancestors(self):
        workflow = {'api': {
            '5': {'class_type': 'H3C_MiniMaxH3ImageStill', 'inputs': {**ARGS, 'lora_stack': ['stack', 0]}},
            'stack': {'class_type': 'easy loraStack', 'inputs': {'optional_lora_stack': ['base', 0]}},
            'base': {'class_type': 'easy loraStack', 'inputs': {'lora_1_name': 'style.safetensors'}},
        }}
        with mock.patch.dict('nodes.NODE_CLASS_MAPPINGS', {'H3C_MiniMaxH3ImageStill': image.H3C_MiniMaxH3ImageStill}):
            result = image_recipe.prepare({**recipe(), 'label': 'MiniMax H3 Image'}, workflow, {'prompt': 'A room.'}, [])
        self.assertEqual(result['prompt']['5']['inputs']['lora_stack'], ['stack', 0])
        for node_id in ('stack', 'base'):
            self.assertEqual(result['prompt'][node_id], workflow['api'][node_id])

    def test_unavailable_core_and_wrong_vae_fail_before_loading(self):
        with mock.patch('nodes.NODE_CLASS_MAPPINGS', {}):
            with self.assertRaisesRegex(ValueError, 'Update ComfyUI.*MiniMaxH3ImageConditioning'):
                image.H3C_MiniMaxH3ImageStill.execute(**ARGS)
        with mock.patch.dict('nodes.NODE_CLASS_MAPPINGS', {'MiniMaxH3ImageConditioning': object}):
            for overrides, message in [({'vae': FILES['vae'][1]}, 'VAE'), ({'prompt': ' '}, 'prompt'),
                                       ({'width': 1000}, 'multiple of 32')]:
                with self.subTest(overrides=overrides), self.assertRaisesRegex(ValueError, message):
                    image.H3C_MiniMaxH3ImageStill.execute(**{**ARGS, **overrides})

    def test_scene_is_first_and_references_guide_a_new_image_at_the_requested_size(self):
        workflow = {'api': {'5': {'class_type': 'H3C_MiniMaxH3ImageStill', 'inputs': {**ARGS}}}}
        captured = {**recipe(), 'label': 'MiniMax H3 Image'}
        refs = [reference('image20', ['identity: Courier'], 'a' * 64), reference('image21', ['location: Hall'], 'b' * 64)]
        with mock.patch.dict('nodes.NODE_CLASS_MAPPINGS', {'H3C_MiniMaxH3ImageStill': image.H3C_MiniMaxH3ImageStill}):
            result = image_recipe.prepare(captured, workflow, {'prompt': '@image20 in @image21.'}, refs)
        self.assertEqual(result['provenance']['references'][0]['slot'], 'image21')
        self.assertEqual(set(result['prompt']['h3c_still_source_0']['inputs']), {'source'})
        self.assertEqual(result['prompt']['5']['inputs']['width'], 2048)
        self.assertNotIn('h3c_ph3_size', result['prompt'])
        prompt = result['prompt']['5']['inputs']['prompt']
        self.assertIn('<Picture 2>', prompt)
        self.assertTrue(prompt.startswith('The target image is a new still'))
        self.assertNotIn('Edit <Picture', prompt)
        self.assertNotIn('canvas', prompt)
        self.assertIn('grid', prompt)
        api = {**workflow['api'], '1': {'class_type': 'H3C_Timeline', 'inputs': {'still_recipe': ['5', 1]}}}
        self.assertEqual(story_context.still_model_for(api, '1'), 'MiniMax H3 Image')

    def test_real_scheduler_keeps_video_lazy_and_expands_a_still_on_demand(self):
        from tests.h3c.python.test_ph3_image_lazy import Timeline, Preview, stand_in, stand_ins, execute, RAN, SEEN
        pixels = torch.ones(1, 8, 8, 3)
        core = {**stand_ins(), 'H3C_MiniMaxH3ImageStill': image.H3C_MiniMaxH3ImageStill,
                'PH3TestTimeline': Timeline, 'PH3TestPreview': Preview,
                'MiniMaxH3ImageConditioning': stand_in('conditioning', ('cond', 'latent'), ('CONDITIONING', 'LATENT'),
                    ['clip', 'vae', 'prompt', 'width', 'height']),
                'ConditioningZeroOut': stand_in('zero', ('negative',), ('CONDITIONING',), ['conditioning']),
                'KSampler': stand_in('sampler', ('sampled',), ('LATENT',),
                    ['model', 'seed', 'steps', 'cfg', 'sampler_name', 'scheduler', 'positive', 'negative', 'latent_image', 'denoise']),
                'VAEDecode': stand_in('decode', (pixels,), ('IMAGE',), ['samples', 'vae'])}
        generator = {'class_type': 'H3C_MiniMaxH3ImageStill', 'inputs': {**ARGS}}
        with mock.patch.dict('nodes.NODE_CLASS_MAPPINGS', core):
            RAN.clear()
            self.assertTrue(execute({'1': generator, '2': {'class_type': 'PH3TestTimeline',
                                   'inputs': {'still_recipe': ['1', 1]}}}, ['2']))
            self.assertEqual(RAN, ['timeline'])
            self.assertTrue(execute({'1': generator, '2': {'class_type': 'PH3TestPreview',
                                   'inputs': {'image': ['1', 0]}}}, ['2']))
            self.assertIn('sampler', RAN)
            self.assertEqual(SEEN['sampler']['steps'], 6)
            self.assertEqual(tuple(SEEN['preview'].shape), (1, 8, 8, 3))


if __name__ == '__main__':
    unittest.main()
