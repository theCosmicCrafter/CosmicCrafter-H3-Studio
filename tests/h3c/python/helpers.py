import json

from h3_continuity import timeline as rules


def wav(name="line.wav"):
    return {"type": "input", "filename": name, "subfolder": ""}


def clip(slot="audio1", start=0.0, source_start=0.0, duration=30.0, file=None, **extra):
    return {"slot": slot, "start": start, "source_start": source_start, "duration": duration,
            "file": file or wav(), **extra}


def cue(cue_id="c1", start=1.0, end=2.0, text="Hello there.", slot="audio1", file=None, **extra):
    return {"id": cue_id, "recording": {"slot": slot, "file": file or wav()}, "start": start, "end": end,
            "text": text, "speaker": extra.pop("speaker", "Mara"), "portrayal": extra.pop("portrayal", "on_screen"),
            **extra}


def box(box_id, frames, prompt="A quiet street.", cut=False, **extra):
    return {"id": box_id, "frames": frames, "prompt": prompt, "seed": 1, "cut": cut, **extra}


def document(boxes, **extra):
    return {"version": 1, "prompt": "", "boxes": boxes, **extra}


def parse(boxes, **extra):
    return rules.parse(json.dumps(document(boxes, **extra)))
