import asyncio
import copy
import json
from types import SimpleNamespace
import unittest
from unittest import mock

from tests.h3c.continuity_support import enable_comfy_cpu

enable_comfy_cpu()

from h3_continuity import h3_prompt_ir, story_bible_write, story_fast  # noqa: E402
from h3_continuity import still_prompt_preparation as still, story_context, story_instructions  # noqa: E402


def workflow():
    return {
        '1': {'class_type': 'H3C_Timeline', 'inputs': {'still_recipe': ['5', 1]}},
        '5': {'class_type': 'H3C_PH3ImageStill', 'inputs': {}},
        '6': {'class_type': 'H3C_StillRecipe', 'inputs': {'bindings': '{"adapter":"pixels"}'}},
    }


class ModelSelectionTest(unittest.TestCase):
    def test_model_selection_is_independent_of_video_story_writing(self):
        prompt = workflow()
        prompt['9'] = {'class_type': 'SaveVideo', 'inputs': {'video': ['1', 0]}}
        self.assertEqual(story_context.renderer_for(prompt, '1'), 'video')
        self.assertEqual(story_context.still_model_for(prompt, '1'), 'P-H3-Image')

    def test_only_the_selected_switch_branch_supplies_model_instructions(self):
        prompt = workflow()
        prompt['1']['inputs']['still_recipe'] = ['7', 0]
        prompt['7'] = {'class_type': 'LazySwitchKJ', 'inputs': {
            'switch': ['8', 0], 'on_true': ['5', 1], 'on_false': ['6', 0]}}
        prompt['8'] = {'class_type': 'PrimitiveBoolean', 'inputs': {'value': True}}
        self.assertEqual(story_context.still_model_for(prompt, '1'), 'P-H3-Image')
        prompt['8']['inputs']['value'] = False
        self.assertEqual(story_context.still_model_for(prompt, '1'), '')
        prompt['8']['class_type'] = 'ComputedBoolean'
        self.assertEqual(story_context.still_model_for(prompt, '1'), '')

    def test_image_output_and_unconnected_model_do_not_select_ph3(self):
        for link in (['5', 0], ['6', 0], None):
            prompt = workflow()
            prompt['1']['inputs']['still_recipe'] = link
            self.assertEqual(story_context.still_model_for(prompt, '1'), '')


class InstructionsTest(unittest.TestCase):
    def test_workflow_context_reaches_planner_writer_and_plan_identity(self):
        prompt = workflow()
        prompt['2'] = {'class_type': 'H3C_Story', 'inputs': {
            'idea': 'A woman holds a cup.', 'model': 'writer', 'base_url': 'http://localhost:1234/v1'}}
        prompt['1']['inputs'].update(story=['2', 0], name='ph3-instructions-test', context_frames=39,
            timeline=json.dumps({'boxes': [{'id': 'b1', 'frames': 22, 'prompt': 'A woman holds a cup.'}]}))
        with mock.patch.object(story_context, 'request_status', return_value={'ok': True, 'boxes': []}):
            ctx = story_context.read(prompt, '2', rewrite_all=True)
        self.assertEqual((ctx.renderer, ctx.image_model), ('image', 'P-H3-Image'))
        self.assertIn(story_instructions.PH3_IMAGE, story_bible_write.plan_messages(ctx)[0]['content'])
        plan = SimpleNamespace(title='Cup', sheet='', beats=[SimpleNamespace(
            beat='A woman holds a cup.', on_screen=[], ends='She holds the cup.')])
        context = h3_prompt_ir.resolve(ctx, 0, [])
        messages = story_fast.messages(ctx, plan, 0, {}, context, {}, {})
        self.assertIn(story_instructions.PH3_IMAGE, messages[0]['content'])
        ph3_identity = story_context.identity(ctx)
        ctx.image_model = ''
        self.assertNotEqual(story_context.identity(ctx), ph3_identity)
        self.assertNotIn(story_instructions.PH3_IMAGE, story_bible_write.plan_messages(ctx)[0]['content'])
        self.assertNotIn(story_instructions.PH3_IMAGE, story_fast.messages(ctx, plan, 0, {}, context, {}, {})[0]['content'])

    def test_image_planner_and_snapshot_writer_receive_ph3_guidance_only_for_ph3(self):
        for build in (story_instructions.image_writer,
                      lambda **kwargs: story_instructions.image_planner(True, **kwargs)):
            self.assertIn(story_instructions.PH3_IMAGE, build(model='P-H3-Image'))
            self.assertNotIn(story_instructions.PH3_IMAGE, build())

    def test_final_conversion_receives_model_guidance_and_preserves_saved_instructions(self):
        document = {'boxes': [{'id': 'b1', 'frames': 22, 'prompt': 'A woman holds a red cup.'}]}
        prepared = still.plan(document, instructions='Use an ink drawing with blue shadows.')
        saved = copy.deepcopy(prepared)
        rows = [{**{key: copy.deepcopy(row[key]) for key in ('id', 'members')},
                 'prompt': 'An ink drawing of a woman holding a red cup in blue window light.',
                 'components': {key: 'Visible detail.' for key in still.COMPONENTS}, 'issues': []}
                for row in prepared['prompts']]
        for model in ('P-H3-Image', ''):
            with self.subTest(model=model):
                chat = SimpleNamespace(ask=mock.AsyncMock(return_value=json.dumps({'prompts': rows})))
                # Video Story writing still uses the selected image model for still conversion.
                job = SimpleNamespace(still_plan=prepared, report=mock.Mock(),
                                      ctx=SimpleNamespace(image_model=model, renderer='video', references=[]))
                with mock.patch.object(still, '_descriptions', return_value={}):
                    result = asyncio.run(still.convert(job, chat))
                messages = chat.ask.call_args.args[0]
                self.assertEqual(story_instructions.PH3_IMAGE in messages[0]['content'], bool(model))
                self.assertIn(still.DEFAULT_INSTRUCTIONS, messages[0]['content'])
                self.assertEqual(json.loads(messages[1]['content'])['instructions'], saved['source']['instructions'])
                self.assertEqual(result['instructions'], saved['source']['instructions'])
                self.assertEqual(prepared, saved)


if __name__ == '__main__':
    unittest.main()
