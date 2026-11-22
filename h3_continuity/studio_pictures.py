"""Studio pictures: files the user uploaded into the Timeline, loaded with ComfyUI's own Load Image code."""
import os

from . import timeline as rules


def used(timeline, index):
    """The Studio pictures box `index` sends to H3, in slot order: its mentions and its first and last frames.
    `box_slots` already leaves disabled pictures out."""
    slots = rules.box_slots(timeline, index)
    names = {*slots.references, slots.first, slots.last}
    return sorted((picture for picture in timeline.pictures if picture["slot"] in names
                   and picture['slot'] not in timeline.reference_replacements),
                  key=lambda picture: rules.slot_number(picture["slot"]))


def path(file):
    """The file's path inside its ComfyUI folder, or None when the file is missing."""
    import folder_paths
    rules.picture_file(file)
    root = os.path.realpath(folder_paths.get_directory_by_type(file["type"]))
    found = os.path.realpath(os.path.join(root, file.get("subfolder", ""), file["filename"]))
    if not folder_paths.is_within_directory(root, found):
        raise ValueError("H3 Timeline: a Studio picture must stay inside its ComfyUI folder")
    return found if os.path.isfile(found) else None


def load(timeline, index, loaded):
    """{slot: IMAGE} of the Studio pictures box `index` uses; `loaded` keeps each file read once per run."""
    import nodes
    pictures = used(timeline, index)
    for picture in pictures:
        slot, file = picture["slot"], picture["file"]
        if slot in loaded:
            continue
        if path(file) is None:
            raise ValueError(f"H3 Timeline: box {index + 1} uses @{slot} ({file['filename']}), but the file is missing "
                             f"from ComfyUI's {file['type']} folder")
        name = "/".join(part for part in (file.get("subfolder", ""), file["filename"]) if part)
        loaded[slot] = nodes.LoadImage().load_image(f"{name} [{file['type']}]")[0]
    return {picture["slot"]: loaded[picture["slot"]] for picture in pictures}


def fingerprint(timeline):
    """(slot, path, mtime, size) of each enabled Studio picture for ComfyUI's cache key; a missing file has None."""
    stamps = []
    for picture in timeline.pictures:
        if picture["slot"] in timeline.disabled_refs or picture['slot'] in timeline.reference_replacements:
            continue
        found = path(picture["file"])
        stat = os.stat(found) if found else None
        stamps.append((picture["slot"], found, stat.st_mtime_ns if stat else None, stat.st_size if stat else None))
    return stamps
