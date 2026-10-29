"""Check a generated H3 prompt against the grammar, and repair what is safely repairable.

This is the half an LLM cannot be trusted to do for itself. A model asked for an
H3 prompt will reliably produce something that READS correctly and quietly breaks
one of the format rules -- a cut time that runs past the video, a speaker who
changes ID between shots, an unclosed <d>, a soundscape that repeats the dialogue.
Those do not look like errors on the page; they look like prose. They surface as a
bad render twenty minutes later.

Two passes, deliberately separated:

  check()  -- reports. Never edits. Every finding names the shot it is about.
  repair() -- fixes ONLY what has one correct answer: field order, blank-line
              separation, a stray markdown fence, an unbalanced tag at the very
              end. Anything needing a judgement call (a cut time past the end,
              a subject label that was never defined) is reported and left alone,
              because guessing at it would produce a prompt that passes the check
              and still means the wrong thing.
"""
from __future__ import annotations

import re

import importlib.util, sys
from pathlib import Path

_n="cosmic_nodes_v2.nodes.video.h3_prompt._spec"
if _n in sys.modules:
    spec = sys.modules[_n]
else:
    _s = importlib.util.spec_from_file_location(_n, Path(__file__).parent / "_spec.py")
    spec = importlib.util.module_from_spec(_s); sys.modules[_n] = spec; _s.loader.exec_module(spec)

_SHOT = re.compile(r"\[Shot\s+(\d+)\]", re.I)
# H3 writes cut times as MM:SS.mmm; accept a bare seconds form too since models emit it.
_AT_TIME = re.compile(r"\[Shot\s+\d+\]\s*At\s+(?:(\d{1,2}):)?(\d{1,2})(?:\.(\d{1,3}))?", re.I)
_SPEAKER = re.compile(r"\(S(\d+(?:,\s*S?\d+)*)\)")
_DTAG = re.compile(r"<d>(.*?)</d>", re.S)
_LANG = re.compile(r"^\s*\[[^\]]+\]")
_FENCE = re.compile(r"^\s*```[a-zA-Z]*\s*$|^\s*```\s*$", re.M)


def _seconds(m) -> float:
    mm = int(m.group(1) or 0)
    ss = int(m.group(2) or 0)
    ms = int((m.group(3) or "0").ljust(3, "0"))
    return mm * 60 + ss + ms / 1000.0


def _fields_for(text: str):
    return spec.REF_FIELDS if "subject_definitions:" in text else spec.CORE_FIELDS


def repair(text: str) -> tuple[str, list[str]]:
    """Return (fixed_text, notes). Only unambiguous fixes."""
    notes = []
    out = text.strip()

    if _FENCE.search(out):
        out = _FENCE.sub("", out).strip()
        notes.append("removed a markdown code fence the model wrapped the prompt in")

    # A model often prefixes "Here is the prompt:" -- drop anything before the first field.
    fields = _fields_for(out)
    first = min((out.find(f + ":") for f in fields if out.find(f + ":") >= 0), default=-1)
    if first > 0:
        head = out[:first]
        # keep a real alignment instruction, drop chatter
        if "referenced" in head or "aligns with" in head:
            pass
        else:
            out = out[first:]
            notes.append(f"dropped {len(head)} characters of preamble before the first field")

    # Each field label starts its own line, with a blank line before it.
    for f in fields:
        out = re.sub(r"(?<!\n)\n?(" + re.escape(f) + r":)", r"\n\n\1", out, count=1)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()

    # An unclosed <d> at the very end has one correct answer.
    if out.count("<d>") == out.count("</d>") + 1 and out.rfind("<d>") > out.rfind("</d>"):
        out += "</d>"
        notes.append("closed a trailing <d> tag the model left open")

    return out, notes


def check(text: str, seconds: float, task: str = "T2VA",
          expect_dialogue: bool | None = None) -> list[str]:
    """Every rule violation found, as plain sentences. Empty list means clean."""
    out: list[str] = []
    fields = _fields_for(text)

    # --- structure -------------------------------------------------------------
    missing = [f for f in fields if f + ":" not in text]
    if missing:
        out.append("missing required field(s): " + ", ".join(missing))
    seen = [(text.find(f + ":"), f) for f in fields if f + ":" in text]
    if seen != sorted(seen) and len(seen) > 1:
        out.append("fields are out of order; H3 expects " + " then ".join(fields))

    # --- alignment instruction -------------------------------------------------
    if task in ("I2VA", "FL2VA", "L2VA"):
        head = text[: text.find(fields[0] + ":") if fields[0] + ":" in text else 200]
        if "Picture 1" not in head:
            out.append(f"{task} needs its picture-alignment instruction as the FIRST line, "
                       "before the fields; none was found")

    # --- shots and cut times ---------------------------------------------------
    nums = [int(m.group(1)) for m in _SHOT.finditer(text)]
    if not nums:
        out.append("no [Shot N] markers at all -- H3 needs at least [Shot 1]")
    else:
        if nums[0] != 1:
            out.append(f"the first shot marker is [Shot {nums[0]}]; it must be [Shot 1]")
        expected = list(range(1, len(nums) + 1))
        if nums != expected:
            out.append(f"shot numbers run {nums} -- they must be consecutive from 1")

    times = [(int(m.group(0).split("]")[0].split()[-1]), _seconds(m))
             for m in _AT_TIME.finditer(text)]
    if times:
        if any(n == 1 for n, _ in times):
            out.append("[Shot 1] carries a timestamp; the opening shot must not have one")
        last = -1.0
        for n, t in times:
            if t <= last:
                out.append(f"shot {n} cuts at {t:.3f}s, which is not after the previous cut "
                           f"({last:.3f}s); cut times must strictly increase")
            if seconds and t >= float(seconds):
                out.append(f"shot {n} cuts at {t:.3f}s, at or past the {float(seconds):.2f}s "
                           "video end -- that shot can never be reached")
            last = t
    shot_count = len(nums)
    if shot_count > 1 and len(times) != shot_count - 1:
        out.append(f"{shot_count} shots but {len(times)} cut time(s); every shot after the "
                   "first needs one")

    # --- dialogue --------------------------------------------------------------
    opens, closes = text.count("<d>"), text.count("</d>")
    if opens != closes:
        out.append(f"unbalanced dialogue tags: {opens} <d> against {closes} </d>")
    for body in _DTAG.findall(text):
        if not _LANG.match(body):
            out.append('a <d> block does not start with a language tag like "[English]": '
                       + repr(body.strip()[:40]))
        if spec.VOICEOVER_PHRASE in text and "lips" not in text:
            break
    if spec.VOICEOVER_PHRASE in text and "lips remain" not in text:
        out.append('a voiceover is used but no sentence states the on-screen character\'s '
                   '"lips remain closed" -- H3 will animate the mouth')
    if expect_dialogue is False and opens:
        out.append("dialogue was switched off but the prompt contains <d> spoken lines")
    if expect_dialogue is True and not opens:
        out.append("dialogue was requested but the prompt contains no <d> spoken lines")

    # speaker IDs: every ID that speaks should be introduced once with an identity
    ids = set()
    for m in _SPEAKER.finditer(text):
        for part in m.group(1).split(","):
            ids.add("S" + part.strip().lstrip("S"))
    if opens and not ids:
        out.append("there is spoken dialogue but no (S1)-style speaker ID")

    # --- the two audio fields --------------------------------------------------
    def _section(name):
        i = text.find(name + ":")
        if i < 0:
            return ""
        j = min([text.find(f + ":", i + 1) for f in fields if text.find(f + ":", i + 1) > 0]
                or [len(text)])
        return text[i + len(name) + 1: j].strip()

    sound = _section("overall_soundscape")
    if sound and sound != "N/A":
        n_sent = len([s for s in re.split(r"[.!?]+", sound) if s.strip()])
        if n_sent > 4:
            out.append(f"overall_soundscape runs {n_sent} sentences; H3 wants 1-4")
        if "<d>" in sound:
            out.append("overall_soundscape contains a <d> dialogue tag; speech belongs in "
                       "the description, not the soundscape")
    music = _section("non_diegetic_music")
    if music and music != "N/A":
        n_sent = len([s for s in re.split(r"[.!?]+", music) if s.strip()])
        if n_sent > 3:
            out.append(f"non_diegetic_music runs {n_sent} sentences; H3 wants 1-3")

    # --- reference labels ------------------------------------------------------
    if "subject_definitions:" in text:
        defined = set(re.findall(r"<(Subject|Picture|Video|Audio)\s+(\d+)>",
                                 _section("subject_definitions")))
        used = set(re.findall(r"<(Subject|Picture|Video|Audio)\s+(\d+)>", text))
        undefined = used - defined
        if undefined:
            out.append("reference label(s) used but never defined in subject_definitions: "
                       + ", ".join(f"<{k} {v}>" for k, v in sorted(undefined)))

    return out
