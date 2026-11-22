"""A recipe describes an image branch without evaluating it."""
import json

from comfy_api.latest import io

from . import conditioning, frame_refmods, refmods, reference_replacements, stills, timeline as rules

StillRecipeType = io.Custom("H3C_STILL_RECIPE")


class H3C_StillRecipe(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="H3C_StillRecipe", display_name="Still Recipe", category="H3 Continuity",
            inputs=[io.Image.Input("image", raw_link=True, lazy=True),
                    io.String.Input("bindings", default="{}", multiline=True,
                                    tooltip="Explicit input locators relative to the connected native generator instance.")],
            outputs=[StillRecipeType.Output()],
        )

    @classmethod
    def check_lazy_status(cls, **kwargs):
        return []

    @classmethod
    def execute(cls, image, bindings) -> io.NodeOutput:
        if not isinstance(image, (list, tuple)) or len(image) != 2 or not isinstance(image[0], str) or type(image[1]) is not int or image[1] < 0:
            raise ValueError("Still recipe image must be a raw IMAGE link")
        bindings = json.loads(bindings)
        if not isinstance(bindings, dict):
            raise ValueError("Still recipe bindings must be a JSON object")
        return io.NodeOutput({"version": bindings.get("version", 1), "output": list(image), "bindings": bindings})


class _ReferenceOrder:
    """Insert RefMod presentation at declared native port positions."""
    def __init__(self, clip, images, videos, video_audios, audios, mods):
        self.clip = clip
        self.images, self.videos, self.video_audios, self.audios, self.mods = images, videos, video_audios, audios, mods

    def ordered(self, ordinary, blocks=False, vae=None, audio_vae=None):
        remaining = iter(ordinary)
        result = []
        for kind, refs in (('image', self.images), ('video', self.videos), ('audio', self.audios)):
            for name in sorted(refs, key=lambda key: int(key.rsplit('_', 1)[-1])):
                port = f'ref_{kind}s.{name}'
                if port in self.mods:
                    result.extend(self.mods[port][1 if blocks else 0])
                elif refs[name] is not None:
                    if not blocks:
                        if kind == 'video' and self.video_audios.get('ref_video_audio_' + name.rsplit('_', 1)[-1]) is not None:
                            result.append(next(remaining))
                        result.append(next(remaining))
                    elif (audio_vae if kind == 'audio' else vae) is not None:
                        result.append(next(remaining))
        result.extend(remaining)
        return result

    def tokenize(self, prompt, minimax_ref_items=None, images=None):
        return self.clip.tokenize(prompt, minimax_ref_items=self.ordered(list(minimax_ref_items or [])))

    def encode_from_tokens_scheduled(self, tokens):
        return self.clip.encode_from_tokens_scheduled(tokens)


class H3C_StillConditioning(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        native = conditioning._core().MiniMaxH3ReferenceToVideo.define_schema()
        return io.Schema(node_id='H3C_StillConditioning', display_name='H3 Still Conditioning', category='H3 Continuity',
                         inputs=[*native.inputs, io.String.Input('source_pin', multiline=True)],
                         outputs=[io.Conditioning.Output()])

    @classmethod
    def execute(cls, clip, prompt, width, height, length, source_pin, ref_image_size='match', vae=None,
                audio_vae=None, ref_images=None, ref_videos=None, ref_video_audios=None, ref_audios=None):
        envelope = json.loads(source_pin)
        body, pin = envelope['body'], envelope.get('pin')
        by_number = lambda refs: dict(sorted((refs or {}).items(), key=lambda item: int(item[0].rsplit('_', 1)[-1])))
        images, videos = by_number(ref_images), by_number(ref_videos)
        groups = {'image': images, 'video': videos, 'audio': dict(ref_audios or {}),
                  'video_audio': dict(ref_video_audios or {})}
        mods = {}
        parsed = rules.parse(body['timeline'])
        reference_replacements.refmods(parsed)
        refmods.resolve(parsed)
        current_mods = {ref['slot']: ref for ref in parsed.refmods}
        index = next(i for i, box in enumerate(parsed.boxes) if box.id == body['box'])
        frame = stills._target_frame(parsed, index, body['target'], int(body['settings'].get('context_frames') or 39))
        plates = rules.effective_plates(parsed, index, frame)
        for owner in envelope.get('references', []):
            kind, name = owner['kind'], owner['port'].split('.', 1)[1]
            if 'refmod' in owner:
                ref = current_mods.get(owner['slot'])
                if ref is None or ref != owner['refmod']:
                    raise ValueError(f"H3 still RefMod @{owner['slot']} changed before loading")
                _, backend = refmods.backend()
                items, blocks = refmods.prepare_references(backend, refmods.load([ref]), vae)
                mods[owner['port']] = (items, blocks)
                groups[kind][name] = None
            elif 'file' in owner:
                file = reference_replacements.file_for(parsed, owner['slot'])
                if owner['slot'] in plates and owner['slot'] not in parsed.reference_replacements:
                    file = plates[owner['slot']]['image']
                if file != owner['file']:
                    raise ValueError(f"H3 still reference @{owner['slot']} changed before loading")
                values = rules.parse(body['timeline'])
                values.reference_replacements = {owner['slot']: {'file': file}}
                pixels, audios = reference_replacements.media(values, {}, {}, {})
                groups[kind][name] = (pixels if kind in ('image', 'video') else audios)[owner['slot']]
        groups = {kind: by_number(refs) for kind, refs in groups.items()}
        images, videos = groups['image'], groups['video']
        ordered = _ReferenceOrder(clip, images, videos, groups['video_audio'], groups['audio'], mods)
        source_blocks = []
        wrapped = ordered
        guide_source = envelope.get('guide_source')
        source = None
        if pin is not None:
            resolved, source = stills.load_source(body, pin)
        elif guide_source is not None:
            source = stills.load_guide_source(body, guide_source)
            resolved = {'conditioning': 'pixels'}
        if source is not None:
            if vae is None:
                raise ValueError(f"H3 still source {(pin or guide_source)['box']!r} needs its video VAE")
            if resolved['conditioning'] == 'original_latent':
                wrapped, source_blocks = conditioning.memory_references(wrapped, vae, [source])
            else:
                number = max((int(name.rsplit('_', 1)[-1]) for name in images), default=-1) + 1
                images[f'ref_image_{number}'] = source
        if parsed.boxes[index].flf_refmods and any(image is not None for image in images.values()):
            if vae is None:
                raise ValueError('H3 still cached image RefMods need the video VAE')
            _, backend = refmods.backend()
            for name, pixels in images.items():
                if pixels is not None:
                    mods[f'ref_images.{name}'] = refmods.prepare_references(
                        backend, [frame_refmods.cached_image(pixels, vae)], vae)
                    images[name] = None
        positive, _ = conditioning._core().MiniMaxH3ReferenceToVideo.execute(
            wrapped, prompt, width, height, length, ref_image_size=ref_image_size, vae=vae, audio_vae=audio_vae,
            ref_images=images or None, ref_videos=videos or None, ref_video_audios=groups['video_audio'] or None,
            ref_audios=groups['audio'] or None).args
        positive = [[embedding, {**meta, 'minimax_refs': ordered.ordered(meta.get('minimax_refs', []), True, vae, audio_vae)
                                 + source_blocks}] for embedding, meta in positive]
        return io.NodeOutput(positive)


class H3C_StillImageSource(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(node_id='H3C_StillImageSource',display_name='Still Image Source',category='H3 Continuity',
                         inputs=[io.String.Input('source',multiline=True,default='{}'),
                                 io.Int.Input('width',optional=True,force_input=True,min=1),
                                 io.Int.Input('height',optional=True,force_input=True,min=1)],outputs=[io.Image.Output()])

    @classmethod
    def execute(cls,source,width=None,height=None):
        source=json.loads(source)
        if width is not None and height is not None: source['size']={'width':width,'height':height}
        return io.NodeOutput(stills.load_pixel_source(source))
