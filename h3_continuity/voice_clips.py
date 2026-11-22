"""Voice clips: sound files the user uploaded into the Timeline for a character's voice, sent whole to H3 by the boxes
that mention them."""
import os

from . import timeline as rules


def used(timeline, index):
    """The voice clips box `index` sends to H3, in slot order. `box_slots` already leaves switched-off audios out."""
    audios = set(rules.box_slots(timeline, index).audios)
    return sorted((clip for clip in timeline.voice_clips if clip["slot"] in audios
                   and clip['slot'] not in timeline.reference_replacements),
                  key=lambda clip: rules.slot_number(clip["slot"]))


def title(timeline, slot):
    """The clip's title: "Mara's voice" for the bible character whose voice clip is in `slot`, or its file's name."""
    for entity in (timeline.bible or {}).get("entities") or ():
        if isinstance(entity, dict) and entity.get("voice_clip") == slot and isinstance(entity.get("name"), str):
            return f"{entity['name']}'s voice"
    return next(clip["file"]["filename"] for clip in timeline.voice_clips if clip["slot"] == slot)


def path(file):
    """The file's path inside its ComfyUI folder, or None when the file is missing."""
    import folder_paths
    rules.audio_file(file)
    root = os.path.realpath(folder_paths.get_directory_by_type(file["type"]))
    found = os.path.realpath(os.path.join(root, file.get("subfolder", ""), file["filename"]))
    if not folder_paths.is_within_directory(root, found):
        raise ValueError("H3 Timeline: a voice clip must stay inside its ComfyUI folder")
    return found if os.path.isfile(found) else None


def load(timeline, index, loaded):
    """{slot: AUDIO} of the voice clips box `index` sends, each whole; `loaded` keeps each file read once per run."""
    from . import audio_tracks
    clips = used(timeline, index)
    for clip in clips:
        slot, file = clip["slot"], clip["file"]
        if slot in loaded:
            continue
        if path(file) is None:
            raise ValueError(f"H3 Timeline: box {index + 1} sends @{slot} ({file['filename']}), but the file is missing "
                             f"from ComfyUI's {file['type']} folder")
        loaded[slot] = audio_tracks.read(file)
    return {clip["slot"]: loaded[clip["slot"]] for clip in clips}


def fingerprint(timeline):
    """(slot, path, mtime, size) of each voice clip that isn't switched off, for ComfyUI's cache key; a missing file
    has None."""
    stamps = []
    for clip in timeline.voice_clips:
        if clip["slot"] in timeline.disabled_refs or clip['slot'] in timeline.reference_replacements:
            continue
        found = path(clip["file"])
        stat = os.stat(found) if found else None
        stamps.append((clip["slot"], found, stat.st_mtime_ns if stat else None, stat.st_size if stat else None))
    return stamps
