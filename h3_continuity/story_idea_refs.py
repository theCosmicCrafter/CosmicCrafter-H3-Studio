"""Optional idea-image guidance uses the existing Studio picture transport."""
import copy
import dataclasses

from . import timeline as rules
from .story_prompts import Reference


GUIDANCE = """Ref2VA idea images are optional visual guides, not mandatory cast or target frames.
Select only the images relevant to this clip, within H3's total nine-image allowance. One guide may draw
from several images. Keep these images out of cast, on_screen, place and native first/last frames.
Use image_guidance to state exactly what each selected image contributes: palette, lighting, texture,
style, atmosphere, composition or another requested attribute. Do not reproduce the source image,
its layout, people, objects or visible text merely because they occur in it. Describe the original scene
from the idea and creative Guide. The compiler cites image sources inside reusable guidance Subject
definitions, uses reference generation and weak_reference, and creates no standalone Picture anchor.
Use [] when a selected image contributes nothing; its file will not be attached to the rendered clip."""

PLANNING = """Optional Idea-image references may guide Ref2VA style, palette, lighting, texture, atmosphere or
composition without their source image or depicted people/objects appearing in the video. Select relevant
image slots in a box's references even when they show no on-screen cast. State their intended contribution
in the beat. Do not assign them to cast, on_screen, place or first/last frames. Omit unused images.
They count toward the same nine-image allowance as identity and other image references."""


def protected_slots(ctx):
    protected = {slot for box in ctx.timeline.boxes for slot in (box.first, box.last) if slot}
    for entity in (ctx.bible or {}).get("entities", []):
        protected.update(entity["pictures"])
        for look in entity["looks"]:
            protected.update(look.get("pictures", []))
    return protected


def guide_slots(ctx):
    """Saved guide roles outlive the uploads and their current describing route."""
    known = {picture["slot"] for picture in ctx.timeline.pictures if picture.get("guidance") is True}
    known.update((ctx.saved_plan or {}).get("idea_references", {}).values())
    for fields in ctx.box_fields.values():
        known.update((fields.get("source") or {}).get("frame", {}).get("image_guidance", []))
    return known - protected_slots(ctx)


def prepare(ctx):
    """Offer described idea images under stable Studio slots, without changing the input Timeline."""
    pictures = list(ctx.timeline.pictures)
    references, descriptions = list(ctx.references), dict(ctx.descriptions)
    cached = dict(ctx.reference_descriptions)
    known = guide_slots(ctx)
    protected = protected_slots(ctx)
    assigned = {}
    occupied = {ref.name for ref in references} | set(ctx.timeline.disabled_refs)
    occupied.update(picture["slot"] for picture in pictures)
    occupied.update(protected)
    occupied.update(name for _, name in rules.mentions(ctx.shared))
    occupied.update(item["slot"] for item in ctx.timeline.refmods)
    for box in ctx.timeline.boxes:
        occupied.update(filter(None, (box.first, box.last)))
        occupied.update(name for _, name in rules.mentions(box.prompt))
    for ref in ctx.idea_images:
        if ref.name not in ctx.idea_descriptions or not ref.file:
            continue
        matches = [picture for picture in pictures if picture["file"] == ref.file]
        if matches and all(picture["slot"] in ctx.timeline.disabled_refs for picture in matches):
            continue
        enabled = next((picture for picture in matches if picture["slot"] not in ctx.timeline.disabled_refs
                        and picture["slot"] not in protected and
                        (picture["slot"] in known or picture["slot"] in assigned.values()
                         or picture.get("title") == ref.title)), None)
        if enabled is None:
            number = 17
            while f"image{number}" in occupied:
                number += 1
            enabled = {"slot": f"image{number}", "title": ref.title, "file": dict(ref.file), "guidance": True}
            pictures.append(enabled)
            occupied.add(enabled["slot"])
        slot = enabled["slot"]
        assigned[ref.name] = slot
        if not any(item.name == slot for item in references):
            references.append(Reference(slot, ref.title, ref.path))
        descriptions[slot] = ctx.idea_descriptions[ref.name]["text"]
        cached[slot] = dict(ctx.idea_descriptions[ref.name])
    for picture in pictures:
        slot = picture["slot"]
        if slot in known and slot not in assigned.values() and slot not in ctx.timeline.disabled_refs:
            assigned[f"saved:{slot}"] = slot
    saved = ctx.saved_plan
    if ctx.regenerate and saved and saved.get("idea_references"):
        saved = copy.deepcopy(saved)
        old = saved["idea_references"]
        changes = {slot: assigned.get(name) for name, slot in old.items() if not name.startswith("saved:")}
        targets = {box.id for box in ctx.targets}
        for beat in saved.get("boxes", []):
            if beat.get("id") in targets:
                beat["references"] = list(dict.fromkeys(changes.get(slot, slot) for slot in beat.get("references", [])
                                                         if changes.get(slot, slot)))
    return dataclasses.replace(ctx, timeline=dataclasses.replace(ctx.timeline, pictures=pictures),
                               references=references, descriptions=descriptions, reference_descriptions=cached,
                               idea_references=assigned, saved_plan=saved,
                               idea_picture_before={picture["slot"]: dict(picture["file"])
                                                    for picture in ctx.timeline.pictures})


def used_pictures(ctx, prompts):
    """Only the files actual compiled prompts mention become saved render inputs."""
    selected = {name for text in prompts for _, name in rules.mentions(text)} & set(ctx.idea_references.values())
    return [dict(picture) for picture in ctx.timeline.pictures if picture["slot"] in selected]
