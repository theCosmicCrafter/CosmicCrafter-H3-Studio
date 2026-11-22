"""Saved image guides and appearance plates for H3 renders. The user supplies every picture; nothing here generates one."""

from . import conditioning, stills, timed_text, timeline as rules


def load_image(image):
    import nodes
    relative = rules.preview_file(image)
    stills.file_path(image)
    return nodes.LoadImage().load_image(relative + " [output]")[0]


def plate_images(timeline, index, images, frame=0, context=39):
    slots = rules.box_slots(timeline, index, context)
    replacements = rules.effective_plates(timeline, index, frame)
    result = dict(images)
    for slot, plate in replacements.items():
        if slot in slots.references and slot not in (slots.first, slots.last):
            timed_text.check_anchor(plate["image"], rules.frame_text(timeline, index, frame, context), f"plate {plate['id']}")
            result[slot] = load_image(plate["image"])
    return result


def add_guides(positive, latent, vae, guides):
    core = conditioning._core()
    for frame, image in guides:
        pixels = load_image(image)
        # An accepted preview takes precedence over a manual guide at this same frame.
        positive = [[embedding, {**meta, "minimax_keyframes": [
            kf for kf in meta.get("minimax_keyframes", []) if kf["resolved_frame_index"] != frame]}]
            for embedding, meta in positive]
        positive = core.MiniMaxH3AddGuide.execute(positive, latent, frame, vae=vae, image=pixels).args[0]
    return positive
