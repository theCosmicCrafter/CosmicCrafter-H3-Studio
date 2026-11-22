"""Original H3 video latents used as visual references, separate from seam context."""

import re

from . import layers, store, timeline as rules, timing

DEFINITIONS = re.compile(r"(?m)^subject_definitions:.*$")
SECTION_BREAK = re.compile(r"\n\s*\n")
# The first shot of the description, not "(from [Shot 1])" in an I2VA or L2VA alignment line.
FIRST_SHOT = re.compile(r"(?m)(?:^|:)[ \t]*(\[Shot 1\])")


def window_frame(entry, moment):
    """Phase-aligned five-frame source window, after carried context and within saved generation."""
    context = entry.get("context_frames", 0)
    return min(max((moment + context) // 17 * 17, -(-context // 17) * 17), (entry["frames"] - 5) // 17 * 17)


def records(timeline, index, folder, entries, is_done, width=None, height=None, layer_entries=None):
    """The memory windows of box `index`. A moment of a clip with several videos reads the video on screen then, and
    the whole-video replay reads the closing one, from `layer_entries` (the up-to-date layer renders, by layer id)."""
    result = []
    for number, (source, frame, label) in enumerate(rules.memory_sources(timeline, index)):
        whole = number == 0 and rules.replays_previous(timeline, index)
        video = layers.closing(timeline, source) if whole else layers.on_screen(timeline, source, frame)
        if video != timeline.boxes[source].id:
            entry = (layer_entries or {}).get(video)
            if (entry is None or (entry.get("timeline") or {}).get("layer") != video
                    or not store.has_segment_latents(folder, entry)):
                raise ValueError(f"H3 Timeline: memory source box {source + 1}'s video "
                                 f"{layers.label(timeline, source, video)} needs rendering first, "
                                 f"or set box {index + 1}'s Visual memory to Off")
        else:
            entry = entries.get(source + 1)
            if (entry is None or (entry.get("timeline") or {}).get("box") != timeline.boxes[source].id
                    or not store.has_segment_latents(folder, entry) or not is_done(source, entry)):
                raise ValueError(f"H3 Timeline: memory source box {source + 1} needs rendering first, "
                                 f"or set box {index + 1}'s Visual memory to Off")
        if ((width is not None and entry.get("latent_width") != width)
                or (height is not None and entry.get("latent_height") != height)):
            raise ValueError(f"H3 Timeline: memory source box {source + 1} has a different resolution; render it again")
        # Two tokens are five frames. Starting on a full 17-frame cycle preserves H3's temporal phase; the first
        # cycle after the carried frames keeps the window on the source box's own frames.
        raw = window_frame(entry, frame)
        record = {"box": timeline.boxes[source].id, "index": source + 1, "frame": raw, "label": label,
                  "created": entry.get("created"), "layout": (entry.get("timeline") or {}).get("layout"),
                  "file_stamp": store.latent_stamp(folder, entry)}
        if video != timeline.boxes[source].id:
            record["layer"] = video
        if whole:
            # Retain replay to preserve the original phase and the group containing the played endpoint.
            # That last group can encode up to three padding frames; CLIP presentation stops at delivered.
            delivered = entry.get("context_frames", 0) + store.played_frames(entry)
            tokens = next(t for t in range(1, timing.tokens_for_frames(entry["frames"]) + 1)
                          if timing.frames_for_tokens(t) >= delivered)
            record.update(frame=0, tokens=tokens, frames=delivered, whole=True,
                          new_scene=timeline.boxes[index].new_scene)
        if not any(item["index"] == record["index"] and item["frame"] == record["frame"]
                   and item.get("whole", False) == record.get("whole", False)
                   and item.get("layer") == record.get("layer") for item in result):
            result.append(record)
    return result


def load(folder, entries, records, layer_entries=None):
    """Read just the selected slices; no full video/audio load or VAE re-encode."""
    windows = []
    for record in records:
        tokens = record.get("tokens", 2)
        entry = layer_entries[record["layer"]] if "layer" in record else entries[record["index"]]
        video = store.load_video_window(folder, entry, record["frame"] // 17 * 5, tokens)
        if video.ndim != 5 or video.shape[1] != 24 or video.shape[2] != tokens:
            raise ValueError(f"H3 Timeline: memory source box {record['index']} has an invalid H3 latent window")
        windows.append(video)
    return windows


def with_note(prompt, records, first_video, cast=False):
    """`prompt` with the windows defined where H3 reads reference roles: in subject_definitions, else before
    [Shot 1]. H3 knows nothing of Timeline boxes. On Cast memory, a label that says what the window is "showing"
    ends the sentence; every other label is in brackets."""
    note = "\n".join(f"<Video {first_video + i}> is an earlier moment of this film "
                     + (item["label"] if cast and item["label"].startswith("showing ") else f"({item['label']})") + "."
                     for i, item in enumerate(records))
    if any(item.get("whole") for item in records):
        note += "\nUse these videos for reference generation of this new shot."
        if any(item.get("new_scene") for item in records):
            note += ("\nThe preceding video provides visual history for details and movement carried forward; "
                     "this description defines the new setting, time, appearance, lighting, camera, composition and action.")
        else:
            note += ("\nKeep the scene's people, clothing, object appearance, layout, spatial relationships, lighting "
                     "and ongoing movement shown in these videos; the camera, composition and action follow this description.")
        note += (" Do not retain the reference camera, composition or shot progression. Begin the new shot "
                 "immediately: it starts already at the requested camera position and framing, without replaying, "
                 "moving or blending from the preceding shot.")
    else:
        note += ("\nThe target video keeps the people, clothing, setting, lighting and style these videos show; "
                 "its camera, composition and action follow this description.")
    definitions = DEFINITIONS.search(prompt)
    if definitions:
        end = SECTION_BREAK.search(prompt, definitions.end())
        at = end.start() if end else len(prompt)
        return prompt[:at] + "\n" + note + prompt[at:]
    shot = FIRST_SHOT.search(prompt)
    if shot:
        return prompt[:shot.start(1)] + note + "\n" + prompt[shot.start(1):]
    return prompt + "\n" + note


def box_prompt(timeline, index, context, plan, records):
    """What H3 receives for box `index` planned as `plan`, with `records` noted before its timed text and dialogue."""
    slots = plan.slots
    prose = rules.rewrite(rules.assemble_prompt(timeline, index), slots.tags)
    prose = with_note(prose, records, 1 + len(slots.video_inputs) + sum(ref["kind"] == "video" for ref in slots.refmods),
                      cast=timeline.boxes[index].memory == "cast")
    return rules.timed_prompt(timeline, index, context, prose, slots.mode, plan.text_window)
