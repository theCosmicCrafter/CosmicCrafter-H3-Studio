"""A timeline box's H3 conditioning and empty latent, built with the core MiniMax H3 nodes."""

from . import frame_refmods, refmods, timing


def _core():
    from comfy_extras import nodes_minimax_h3
    return nodes_minimax_h3


def memory_references(clip, vae, memories, *, memory_frames=()):
    """Present source pixels to CLIP while retaining original H3 reference latent dimensions."""
    memory_blocks = []
    if memories:
        items = []
        for i, video in enumerate(memories):
            # Pixels present the reference to H3's text encoder; the DiT receives the original saved latent.
            frames = vae.decode(video)
            frames = frames.reshape(-1, *frames.shape[-3:])
            delivered = memory_frames[i] if i < len(memory_frames) else None
            if delivered is not None:
                frames = frames[:delivered]
            # Match native reference-video presentation at 2 fps, also showing the outgoing state at the end.
            full_video = delivered is not None or video.shape[2] > 2
            indices = list(range(0, len(frames), timing.FPS // 2)) if full_video else [0]
            if full_video and indices[-1] != len(frames) - 1:
                indices.append(len(frames) - 1)
            items.append({"type": "video", "data": frames[indices].clone(),
                          "timestamps": [frame / timing.FPS for frame in indices]})
            memory_blocks.append({"kind": "video", "latent_t": video.shape[2], "latent_h": video.shape[3],
                                  "latent_w": video.shape[4], "ref_audio_t": 0, "latent": video, "audio_latent": None})
        clip = refmods.ReferenceClip(clip, items)
    return clip, memory_blocks


def encode(plan, clip, vae, audio_vae, width, height, ref_image_size, images, audios, memories=(), *,
           endpoint_images=None, memory_frames=(), continuation_image=None):
    """(positive, latent) for `plan`, a timeline.BoxPlan; `images` / `audios` map slot names to inputs."""
    core = _core()
    slots = plan.slots
    endpoints = endpoint_images or {}
    first = endpoints.get("first") if plan.fresh else None
    if first is None and slots.first:
        first = images[slots.first]
    last = endpoints.get("last")
    if last is None and slots.last:
        last = images[slots.last]
    first = first[:1] if first is not None else None
    last = last[:1] if last is not None else None
    # A box that drops generated frames ends on its last played frame, not on the last generated one. A box that
    # plays one frame opens on its first frame, so it has no frame left for its last.
    end = plan.carried + plan.frames - 1 if plan.generated > plan.carried + plan.frames else -1
    if (first is not None and end == 0
            and not (slots.mode != "ref2va" and slots.last
                     and (endpoints.get("first") is not None or plan.box.flf_refmods))):
        last = None
    clip, memory_blocks = memory_references(clip, vae, memories, memory_frames=memory_frames)
    if slots.mode != "ref2va":
        blocks = []
        cached_refs = plan.box.flf_refmods and (not plan.fresh or first is not None)
        if cached_refs:
            references = [image for image in (first, last) if image is not None]
            references.extend(images[name] for name in slots.image_inputs)
            clip, blocks = frame_refmods.prepare(clip, vae, references, slots.refmods,
                                                 [audios[name] for name in slots.audio_inputs], audio_vae)
        native_last = last if (end == -1 or (first is not None and endpoints.get("first") is not None)
                              or cached_refs) else None
        positive, latent = core.MiniMaxH3ImageToVideo.execute(clip, vae, plan.prompt, width, height, plan.generated,
                                                            first_frame=first,
                                                            last_frame=native_last).args
        if native_last is not None and end != -1:
            # Keep native text-image order/crop, placing Last at the delivered end; one frame belongs to First.
            positive = [[embedding, {**meta, "minimax_keyframes": [
                {**kf, "resolved_frame_index": end} if kf["resolved_frame_index"] == plan.generated - 1 else kf
                for kf in meta["minimax_keyframes"] if end != 0 or kf["resolved_frame_index"] != plan.generated - 1]}]
                for embedding, meta in positive]
        if blocks or memory_blocks:
            positive = [[embedding, {**meta, "minimax_refs": blocks + memory_blocks}] for embedding, meta in positive]
        if last is not None and end != -1 and native_last is None:
            positive = core.MiniMaxH3AddGuide.execute(positive, latent, end, vae=vae, image=last).args[0]
        return continuation_guide(positive, latent, vae, plan.carried, continuation_image), latent
    blocks = []
    if slots.refmods:
        clip, blocks = refmods.prepare(clip, vae, slots.refmods)
    positive, latent = core.MiniMaxH3ReferenceToVideo.execute(
        clip, plan.prompt, width, height, plan.generated, ref_image_size=ref_image_size, vae=vae,
        audio_vae=audio_vae,
        ref_images={f"ref_image_{i}": images[name] for i, name in enumerate(slots.image_inputs, 1)} or None,
        ref_videos={f"ref_video_{i}": images[name] for i, name in enumerate(slots.video_inputs, 1)} or None,
        ref_video_audios={f"ref_video_audio_{i}": audios[name.replace("video", "video_audio")]
                          for i, name in enumerate(slots.video_inputs, 1)
                          if name.replace("video", "video_audio") in slots.video_audio_inputs} or None,
        ref_audios={f"ref_audio_{i}": audios[name] for i, name in enumerate(slots.audio_inputs, 1)} or None).args
    blocks += memory_blocks
    if blocks:
        positive = [[embedding, {**meta, "minimax_refs": list(meta.get("minimax_refs", [])) + blocks}]
                    for embedding, meta in positive]
    for frame_idx, image in ((0, first), (end, last)):
        if image is not None:
            positive = core.MiniMaxH3AddGuide.execute(positive, latent, frame_idx, vae=vae, image=image).args[0]
    return continuation_guide(positive, latent, vae, plan.carried, continuation_image), latent


def continuation_guide(positive, latent, vae, carried, image):
    """The frozen replay does not constrain the first free frame's visible pose."""
    if not carried or image is None or any(kf['resolved_frame_index'] == carried
            for _, meta in positive for kf in meta.get('minimax_keyframes', [])):
        return positive
    return _core().MiniMaxH3AddGuide.execute(positive, latent, carried, vae=vae, image=image[:1]).args[0]
