"""Official MiniMax H3 Image native workflow as one Timeline still generator.

minimax_pe/ holds the prompt-enhancer instructions of Comfy-Org/workflow_templates (MIT) commit c8e48bd,
image_minimax_h3_image_edit.json and image_minimax_h3_image_t2i.json, unchanged.
"""
import json
import math
import re
from functools import cache
from pathlib import Path

import folder_paths
from comfy_api.latest import io
from comfy_execution.graph_utils import GraphBuilder

StillRecipeType = io.Custom('H3C_STILL_RECIPE')
UPSTREAM = 'https://huggingface.co/Comfy-Org/MiniMax-H3-Image'
MISSING = '(none installed)'
MAX_REFERENCES = 8
MAX_MEGAPIXELS = 64.0
MAX_SIDE = 8192
REFERENCE_MEGAPIXELS = 4.0
COMPONENTS = {
    'diffusion_model': ('diffusion_models', 'minimax_h3_image_pruned_', 'diffusion model'),
    'text_encoder': ('text_encoders', 'qwen3vl_32b_minimax_h3_', 'text encoder'),
    'vae': ('vae', 'minimax_h3_image_vae_', 'VAE'),
}
ENHANCER_PREFIX = 'qwen3.5_'
OFFICIAL_ENHANCER = 'qwen3.5_9b_w4a8_gptq.safetensors'


def _base(name):
    return name.replace('\\', '/').rsplit('/', 1)[-1].lower()


def enhancers():
    """Installed prompt-enhancer models, the one the official templates name first."""
    names = [name for name in folder_paths.get_filename_list('text_encoders') if _base(name).startswith(ENHANCER_PREFIX)]
    return sorted(names, key=lambda name: _base(name) != OFFICIAL_ENHANCER)


@cache
def enhancer_text(name):
    return (Path(__file__).with_name('minimax_pe') / name).read_text(encoding='utf-8')


def installed(component):
    folder, prefix, _ = COMPONENTS[component]
    return [name for name in folder_paths.get_filename_list(folder)
            if name.replace('\\', '/').rsplit('/', 1)[-1].lower().startswith(prefix)]


def choose(component, name):
    if name not in installed(component):
        folder, _, label = COMPONENTS[component]
        raise ValueError(f'MiniMax H3 Image {label} {name!r} is not installed. Select an image-model file from '
                         f'{UPSTREAM} in ComfyUI/models/{folder}. The video and P-H3 image VAEs/models are different.')
    return name


def size_at(width, height, megapixels):
    """Keep width:height and scale the area to megapixels, rounding each side to a multiple of 32."""
    if not 0 < megapixels <= MAX_MEGAPIXELS:
        raise ValueError(f'MiniMax H3 Image megapixels must be between 0 and {MAX_MEGAPIXELS:g}; got {megapixels}.')
    if width <= 0 or height <= 0:
        raise ValueError(f'MiniMax H3 Image needs a positive width and height for its aspect ratio; got {width} x {height}.')
    sides = [max(256, round(math.sqrt(megapixels * 1e6 * ratio) / 32) * 32) for ratio in (width / height, height / width)]
    if max(sides) > MAX_SIDE:
        raise ValueError(f'MiniMax H3 Image at {megapixels:g} MP and {width}:{height} needs a side above {MAX_SIDE}; '
                         'lower megapixels or use a less extreme aspect ratio.')
    return tuple(sides)


def recipe():
    return {'version': 2, 'adapter': 'pixels', 'generator': 'H3C_MiniMaxH3ImageStill', 'label': 'MiniMax H3 Image',
            'reference_limit': MAX_REFERENCES, 'reference_label': '<Picture {index}>'}


class H3C_MiniMaxH3ImageStill(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id='H3C_MiniMaxH3ImageStill', display_name='MiniMax H3 Image Still', category='H3 Continuity',
            description='Official MiniMax H3 Image, six-step native generation and reference editing. '
                        'Connect still_recipe directly to the Timeline.', enable_expand=True,
            inputs=[
                *[io.Combo.Input(component, options=installed(component) or [MISSING]) for component in COMPONENTS],
                io.String.Input('prompt', multiline=True, default=''),
                io.String.Input('instruction', multiline=True, default='', tooltip='Text added after every still prompt.'),
                io.Int.Input('seed', default=0, min=0, max=0xffffffffffffffff),
                io.Int.Input('width', default=2048, min=256, max=8192, step=32),
                io.Int.Input('height', default=2048, min=256, max=8192, step=32),
                io.Autogrow.Input('images', optional=True, template=io.Autogrow.TemplateNames(
                    io.Image.Input('image'), names=[f'image_{i}' for i in range(1, MAX_REFERENCES + 1)], min=0),
                    tooltip='Reference pictures, named <Picture 1>, <Picture 2>, ... in the prompt. The Studio fills these slots.'),
                io.Custom('LORA_STACK').Input('lora_stack', optional=True,
                    tooltip='Optional LoRA stack (for example Easy Use): filename, model strength and CLIP strength. '
                            'Applied in order to direct images and Studio stills. Use LoRAs compatible with MiniMax H3 Image.'),
                io.Float.Input('megapixels', default=0.0, min=0.0, max=MAX_MEGAPIXELS, step=0.1, optional=True,
                    tooltip='0 uses width and height exactly. Above 0, width and height only set the aspect ratio and the image '
                            'is generated at this many megapixels (1 MP = 1,000,000 pixels), each side a multiple of 32. '
                            'Reference images are separately resized to 4 MP as in the official edit workflow.'),
                io.Combo.Input('prompt_enhancer', options=['off', 'auto', *enhancers()], default='off', optional=True,
                    tooltip='off (default) sends the prompt exactly as written. The official templates can instead rewrite it '
                            'with a Qwen3.5 model and Generate Text before MiniMax H3 Image sees it. auto does this for '
                            f'reference edits, like the official edit template, using {OFFICIAL_ENHANCER} or another installed '
                            'Qwen3.5 text model (none installed: prompt used as written). A model name also rewrites text-only '
                            'prompts.'),
            ], outputs=[io.Image.Output('image'), StillRecipeType.Output('still_recipe')])

    @classmethod
    def execute(cls, diffusion_model, text_encoder, vae, prompt, instruction, seed, width, height, images=None, lora_stack=None,
                megapixels=0.0, prompt_enhancer='off'):
        import nodes
        if 'MiniMaxH3ImageConditioning' not in nodes.NODE_CLASS_MAPPINGS:
            raise ValueError('Update ComfyUI to a version with MiniMaxH3ImageConditioning (native MiniMax H3 Image '
                             'support added 2026-11-10), then restart ComfyUI.')
        files = {component: choose(component, name) for component, name in
                 [('diffusion_model', diffusion_model), ('text_encoder', text_encoder), ('vae', vae)]}
        if megapixels:
            width, height = size_at(width, height, megapixels)
        for label, value in [('width', width), ('height', height)]:
            if not 256 <= value <= 8192 or value % 32:
                raise ValueError(f'MiniMax H3 Image {label} must be a multiple of 32 between 256 and 8192; got {value}.')
        if not prompt.strip():
            raise ValueError('MiniMax H3 Image needs a prompt.')
        references = {name: value for name, value in sorted((images or {}).items(),
                      key=lambda item: int(item[0].rsplit('_', 1)[-1])) if value is not None}
        if len(references) > MAX_REFERENCES:
            raise ValueError(f'MiniMax H3 Image Still supports at most {MAX_REFERENCES} references.')
        text = prompt.strip() + ('\n\n' + instruction.strip() if instruction.strip() else '')
        if prompt_enhancer in (None, 'off'):
            enhancer = None
        elif prompt_enhancer == 'auto':
            enhancer = next(iter(enhancers()), None) if references else None
        elif prompt_enhancer in enhancers():
            enhancer = prompt_enhancer
        else:
            raise ValueError(f'MiniMax H3 Image prompt enhancer {prompt_enhancer!r} is not installed. Put {OFFICIAL_ENHANCER} '
                             f'from {UPSTREAM} in ComfyUI/models/text_encoders, or choose auto or off.')
        if enhancer and 'TextGenerateV2' not in nodes.NODE_CLASS_MAPPINGS:
            raise ValueError('The MiniMax H3 Image prompt enhancer needs ComfyUI\'s Generate Text node (TextGenerateV2). '
                             'Update ComfyUI, or set prompt_enhancer to off.')
        g = GraphBuilder()
        model = g.node('UNETLoader', unet_name=files['diffusion_model'], weight_dtype='default')
        clip = g.node('CLIPLoader', clip_name=files['text_encoder'], type='minimax', device='default')
        model_link, clip_link = model.out(0), clip.out(0)
        for lora_name, strength_model, strength_clip in lora_stack or []:
            if not lora_name or lora_name == 'None' or (strength_model == 0 and strength_clip == 0):
                continue
            lora = g.node('LoraLoader', model=model_link, clip=clip_link, lora_name=lora_name,
                          strength_model=strength_model, strength_clip=strength_clip)
            model_link, clip_link = lora.out(0), lora.out(1)
        vae_node = g.node('VAELoader', vae_name=files['vae'])
        for key, value in references.items():
            # Match the official edit workflow before its native vision/VAE reference scaling.
            resized = g.node('ResizeImageMaskNode', input=value, resize_type='scale total pixels',
                             **{'resize_type.megapixels': REFERENCE_MEGAPIXELS}, scale_method='area')
            aligned = g.node('ResizeImageMaskNode', input=resized.out(0), resize_type='scale to multiple',
                             **{'resize_type.multiple': 32}, scale_method='area')
            references[key] = aligned.out(0)
        if enhancer:
            if references:
                ratio = math.gcd(width, height)
                request = (f'User Editing Instruction: {json.dumps(text, ensure_ascii=False)}\n'
                           f'User Aspect Ratio Selection: {width // ratio}:{height // ratio}')
            task = enhancer_text('edit_task.txt' if references else 't2i_task.txt').replace('{input text}', request if references else text)
            reader = g.node('CLIPLoader', clip_name=enhancer, type='minimax', device='default')
            sampling = {'temperature': 1.0, 'top_k': 20, 'top_p': 0.95, 'min_p': 0.0, 'repetition_penalty': 1.0,
                        'presence_penalty': 0.0, 'seed': seed}
            generated = g.node('TextGenerateV2', clip=reader.out(0), prompt=task, system_prompt=enhancer_text('system.txt'),
                               max_length=8196, sampling_mode='on', thinking=True, use_default_template=True, mtp='auto',
                               **{'sampling_mode.' + key: value for key, value in sampling.items()},
                               **{f'images.image{i}': value for i, value in enumerate(references.values(), 1)})
            text = g.node('H3C_MiniMaxPromptCaption', text=generated.out(0)).out(0)
        cond = g.node('MiniMaxH3ImageConditioning', clip=clip_link, vae=vae_node.out(0), prompt=text,
                      width=width, height=height, **{'images.' + key: value for key, value in references.items()})
        negative = g.node('ConditioningZeroOut', conditioning=cond.out(0))
        sampled = g.node('KSampler', model=model_link, seed=seed, steps=6, cfg=1.0, sampler_name='euler',
                         scheduler='simple', positive=cond.out(0), negative=negative.out(0), latent_image=cond.out(1), denoise=1.0)
        decoded = g.node('VAEDecode', samples=sampled.out(0), vae=vae_node.out(0))
        return io.NodeOutput(decoded.out(0), recipe(), expand=g.finalize())


class H3C_MiniMaxPromptCaption(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id='H3C_MiniMaxPromptCaption', display_name='MiniMax H3 Prompt Caption', category='H3 Continuity',
            description='The expanded_caption written by the MiniMax H3 Image prompt enhancer. Fails instead of '
                        'passing on an empty or unreadable caption.',
            inputs=[io.String.Input('text', multiline=True, force_input=True)], outputs=[io.String.Output('caption')])

    @classmethod
    def execute(cls, text):
        decoder = json.JSONDecoder()
        for start in re.finditer(r'\{', text):
            try:
                data, _ = decoder.raw_decode(text, start.start())
            except json.JSONDecodeError:
                continue
            caption = data.get('expanded_caption') if isinstance(data, dict) else None
            if isinstance(caption, str) and caption.strip():
                return io.NodeOutput(caption.strip())
        raise ValueError('The MiniMax H3 Image prompt enhancer returned no expanded_caption, so no image was generated. '
                         f'Its reply began: {text.strip()[:300]!r}. Run again, or set prompt_enhancer to off.')
