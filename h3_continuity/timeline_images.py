"""Read a selected Timeline Picture without preparing or rendering a video."""

import nodes
from comfy_api.latest import io
from comfy_execution.graph_utils import ExecutionBlocker

from . import timeline as rules, reference_replacements, refmods, timing
from .nodes import CATEGORY


def source(timeline, picture, box=1, frame=0, context_frames=39, images=None):
    parsed = rules.parse(timeline)
    reference_replacements.refmods(parsed)
    if not 1 <= box <= len(parsed.boxes):
        return None, None, None
    index, context = box - 1, int(context_frames)
    slots = rules.box_slots(parsed, index, context)
    ordered = [(name, None) for name in slots.image_inputs]
    if slots.mode != 'ref2va':
        frames, carried = rules.box_length(parsed, index, context)
        fresh = rules.is_fresh(parsed, index)
        endpoints = {}
        for at, file in rules.frame_guides(parsed, index, context):
            if at == 0 and fresh:
                endpoints['first'] = file
            elif at == frames + carried - 1:
                endpoints['last'] = file
        first = (slots.first, endpoints.get('first')) if slots.first or 'first' in endpoints else None
        last = (slots.last, endpoints.get('last')) if slots.last or 'last' in endpoints else None
        end = frames + carried - 1 if rules.dropped_frames(parsed, index) else -1
        cached = parsed.boxes[index].flf_refmods and (not fresh or first is not None)
        # Match conditioning.encode: a trimmed Last can be AddGuide-only, with no Picture token.
        if first is not None and end == 0 and not (slots.last and ('first' in endpoints or cached)):
            last = None
        native_last = last if end == -1 or (first is not None and 'first' in endpoints) or cached else None
        ordered = [item for item in (first, native_last) if item is not None]
        if cached:
            ordered += [item for item in (first, last) if item is not None]
            ordered += [(name, None) for name in slots.image_inputs]
    ordered += [(ref['slot'], None) for ref in slots.refmods if ref['kind'] == 'image']
    if not 1 <= picture <= len(ordered):
        return None, None, None
    slot, file = ordered[picture - 1]
    if file is not None:
        return None, None, file
    if rules.reference_disabled(slot, parsed.disabled_refs):
        return None, None, None
    origin = reference_replacements.origin(slot, reference_replacements.effective(parsed))
    name, file = origin.get('source'), origin.get('file')
    ref = next((ref for ref in parsed.refmods if ref['slot'] == name), None)
    if ref is not None and ref.get('strength', 1) <= 0:
        return None, None, None
    if ref is not None and name in (images or {}) and not rules.reference_disabled(name, parsed.disabled_refs):
        raise ValueError(f'H3 Timeline: {name} has both an input and a RefMod; disconnect the input or remove the RefMod')
    if file is None:
        file = next((picture['file'] for picture in parsed.pictures if picture['slot'] == name), None)
    plate = rules.effective_plates(parsed, index, frame).get(slot)
    if plate is not None and slot in slots.references and slot not in (slots.first, slots.last):
        return None, None, plate['image']
    return name, ref, file


class H3C_TimelineImage(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id='H3C_TimelineImage', display_name='H3 Timeline Image', category=CATEGORY,
            description='Resolved pixels for <Picture N> in the selected Timeline clip. Image RefMods decode their stored reference.',
            inputs=[
                io.Int.Input('picture', default=1, min=1),
                io.String.Input('timeline', default='{"version":1,"boxes":[]}', multiline=True),
                io.Int.Input('box', default=1, min=1),
                io.Int.Input('frame', default=0, min=0),
                io.Combo.Input('context_frames', options=list(timing.CONTEXT_OPTIONS), default='39'),
                io.Vae.Input('vae', optional=True, lazy=True),
                io.Autogrow.Input('images', optional=True, template=io.Autogrow.TemplateNames(
                    io.Image.Input('image', lazy=True), names=rules.IMAGE_SLOTS, min=0)),
            ],
            outputs=[io.Image.Output(display_name='image')],
        )

    @classmethod
    def check_lazy_status(cls, picture, timeline, box=1, frame=0, images=None, vae=False, context_frames=39):
        name, ref, file = source(timeline, picture, box, frame, context_frames, images)
        if file is not None or name is None:
            return []
        if ref is not None:
            return ['vae'] if vae is None else []
        value = images.get(name) if isinstance(images, dict) else None
        return [value[1]] if value is not None and value[0] is None else []

    @classmethod
    def fingerprint_inputs(cls, picture, timeline, box=1, frame=0, context_frames=39, **kwargs):
        if None in (picture, timeline, box, frame, context_frames):
            return float('nan')
        name, ref, file = source(timeline, picture, box, frame, context_frames)
        if file is not None:
            reference_replacements.file_path(file, f'<Picture {picture}>')
            path = '/'.join(part for part in (file.get('subfolder', ''), file['filename']) if part)
            return nodes.LoadImage.IS_CHANGED(f"{path} [{file['type']}]")
        if ref is not None:
            pack, _ = refmods.backend()
            path, _ = refmods.metadata(ref, pack)
            return pack._file_stamp(path)
        return name

    @classmethod
    def execute(cls, picture, timeline, box=1, frame=0, images=None, vae=None, context_frames=39):
        name, ref, file = source(timeline, picture, box, frame, context_frames, images)
        if file is not None:
            reference_replacements.file_path(file, f'<Picture {picture}>')
            path = '/'.join(part for part in (file.get('subfolder', ''), file['filename']) if part)
            pixels = nodes.LoadImage().load_image(f"{path} [{file['type']}]")[0]
        elif ref is not None:
            if vae is None:
                raise ValueError(f'H3 Timeline: connect the H3 VAE to decode <Picture {picture}> from its RefMod')
            pack, _ = refmods.backend()
            mod = refmods.load([ref])[0][0]
            pixels = pack.decode_visual(vae, mod.latent)
        else:
            pixels = (images or {}).get(name, ExecutionBlocker(None))
        return io.NodeOutput(pixels)
