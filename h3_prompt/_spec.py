"""The MiniMax-H3 prompt grammar, as data.

Everything here is the format H3 itself defines -- task types, the three core
fields, the camera-motion vocabulary, the cut phrasings, the speaker and dialogue
tags. It is transcribed from MiniMax's published prompt-writing guide so the rest
of this package has one place to agree with, instead of nine files each carrying
their own copy of the rules.

Kept as plain data on purpose: the builder reads it to write the instruction, and
the validator reads THE SAME data to check what came back. A rule can therefore
never be enforced in one direction and forgotten in the other.
"""
from __future__ import annotations

# --- task types ---------------------------------------------------------------
# What H3 accepts, and what each one needs wired to be legal. `images` is how many
# reference pictures the task requires; `anchor` is what those pictures mean.
TASKS = {
    "T2VA": {
        "label": "Text to Video+Audio",
        "images": 0,
        "anchor": "",
        "how": "Build the whole audiovisual timeline from the text alone.",
    },
    "I2VA": {
        "label": "Image to Video+Audio",
        "images": 1,
        "anchor": "first frame",
        "how": "Picture 1 IS the frame at 0.00s. Establish it, then develop forward: "
               "first-frame anchor -> action onset -> continuous development -> result.",
    },
    "FL2VA": {
        "label": "First+Last Frame to Video+Audio",
        "images": 2,
        "anchor": "first and last frame",
        "how": "Picture 1 opens, Picture 2 closes. Describe the path between them: "
               "first-frame state -> intermediate changes -> narrowing difference -> "
               "last-frame state. Prefer ONE shot so the model can interpolate.",
    },
    "L2VA": {
        "label": "Last Frame to Video+Audio",
        "images": 1,
        "anchor": "last frame",
        "how": "Picture 1 is the FINAL frame and belongs to the last shot, not Shot 1. "
               "Infer a plausible earlier state, then converge on it.",
    },
    "Ref2VA": {
        "label": "Reference to Video+Audio",
        "images": 1,
        "anchor": "subject reference",
        "how": "References say what a subject LOOKS like, not where a frame sits. "
               "Six-section rewrite: subject_definitions, summary, retention_analysis, "
               "detailed_description, overall_soundscape, non_diegetic_music.",
    },
}
TASK_ORDER = ["Auto", "T2VA", "I2VA", "FL2VA", "L2VA", "Ref2VA"]

# The three fields every non-reference prompt must carry, in this order.
CORE_FIELDS = ("integrated_multimodal_description", "overall_soundscape", "non_diegetic_music")
# Full-reference mode replaces them with six sections, in this order.
REF_FIELDS = ("subject_definitions", "summary", "retention_analysis",
              "detailed_description", "overall_soundscape", "non_diegetic_music")

# --- the alignment instruction that must precede the core fields ---------------
# `n` = index of the final shot, `s` = effective duration, two decimals.
ALIGNMENT = {
    "T2VA": "",
    "I2VA": "For the target video, at 0.00 seconds into the target video, "
            "<Picture 1> (from [Shot 1]) is fully referenced.",
    "FL2VA": "How the reference pictures align with the target video -- Picture 1 "
             "(from Shot 1) aligns with the 0.00-second mark of the target video; "
             "Picture 2 (from Shot {n}) aligns with the {s} -second mark of the target video.",
    "L2VA": "How the reference pictures align with the target video -- <Picture 1> "
            "(from [Shot {n}]) aligns with the {s} -second mark of the target video.",
    "Ref2VA": "",
}

# --- camera motion: type + amplitude + speed -----------------------------------
CAMERA_MOVES = (
    "Zoom In", "Zoom Out", "Push In", "Pull Out", "Pan Left", "Pan Right",
    "Truck Left", "Truck Right", "Tilt Up", "Tilt Down", "Pedestal Up",
    "Pedestal Down", "Arc Shot", "Tracking Shot", "Static Shot",
    "Shake Slightly", "Shake Strongly", "POV",
    "Roll Clockwise", "Roll Counterclockwise",
)
AMPLITUDES = ("with small amplitude", "with large amplitude")
SPEEDS = ("at slow speed", "at fast speed")

# --- named shots: film-school recipes over the vocabulary above ----------------
# Each entry composes the official moves, one amplitude and one speed into a shot
# a director would name. An empty amplitude or speed means "leave it out", which
# the guide says is the medium / normal default. `min_frames` is the shortest clip
# the recipe is known to land in at 24 fps (community renders: one subject, one
# scene, small stated sample sizes, so treat it as a floor and not a promise).
# `framing` says what the opening frame needs so the move has room. `phrase` is
# the camera sentence the writing model is steered toward.
#
# Three of these (rack focus, snorricam, split screen) have no motion primitive of
# their own in the guide; they are written as a static or tracking shot plus a
# description of the result, and that is what the renders responded to.
SHOTS = {
    "crash zoom": {
        "moves": ("Zoom In",), "amplitude": "with large amplitude", "speed": "at fast speed",
        "min_frames": 124,
        "framing": "Open wide so the snap has range; it ends on a tight close-up. The moment "
                   "of the snap cannot be placed in time, so tie the reaction and one sharp "
                   "sound to the landing rather than spreading them across the shot.",
        "phrase": "From a wide view the camera zooms in on the subject's face with "
                  "large amplitude at fast speed: one hard snap from wide to a tight "
                  "close-up, over in a single beat, with nobody and nothing in the "
                  "scene shifting. The jump is all magnification.",
    },
    "yo-yo zoom": {
        "moves": ("Zoom Out", "Zoom In"), "amplitude": "with large amplitude",
        "speed": "at fast speed", "min_frames": 192,
        "framing": "Open and close on the same tight close-up. Needs 192 frames; at 124 the "
                   "hold and the return do not both fit. The hold length is the model's "
                   "choice, not yours. The out leg is written as a build-up from slow, "
                   "with no amplitude or speed words; a zoom out at one steady fast speed "
                   "renders as an ordinary zoom with no snap-back shape. Only the return "
                   "leg carries the modifiers.",
        "phrase": "Opening on a tight close-up of the face, the camera zooms out, "
                  "beginning slowly and gathering speed the whole way until the picture "
                  "streaks with blur and the subject has shrunk to a distant speck, "
                  "holds on that far view for roughly a second, then zooms in again "
                  "with large amplitude at fast speed, covering the whole return in one "
                  "beat and whipping back to the close-up it opened on.",
    },
    "dolly zoom": {
        "moves": ("Push In", "Zoom Out"), "amplitude": "", "speed": "",
        "min_frames": 124,
        "framing": "Open at the medium framing it ends on: the subject stays the same size "
                   "throughout, so a wide opening has no purpose. Adding 'at slow speed' loosened "
                   "the lock in testing, so leave amplitude and speed out.",
        "phrase": "The camera pushes in on the subject and zooms out at the same time, "
                  "the two moves paced to cancel each other, so the subject keeps one "
                  "size and one spot in frame from first frame to last while the space "
                  "behind them stretches away, thinning and deepening as the "
                  "background drops back.",
    },
    "super dolly in": {
        "moves": ("Push In",), "amplitude": "with large amplitude", "speed": "at fast speed",
        "min_frames": 124,
        "framing": "Open extreme wide: the subject tiny in the distance, with one large "
                   "foreground object on each side of frame; a wide lens alone is not "
                   "enough, the opening must be written. The run finishes on a tight "
                   "close-up of the face.",
        "phrase": "From the far end of the space the camera pushes in toward the "
                  "distant subject with large amplitude at fast speed: the two near "
                  "objects at the edges of frame fly out past the lens first, then the "
                  "middle ground streams by on either side and the floor pours away "
                  "under the camera, until the run stops hard on a tight close-up of "
                  "the face.",
    },
    "eyes in": {
        "moves": ("Push In",), "amplitude": "with large amplitude", "speed": "at slow speed",
        "min_frames": 124,
        "framing": "Medium framing. The destination must be a named anatomical detail (one "
                   "eye, the iris), not a degree of closeness; an extreme enough destination "
                   "widens the opening by itself.",
        "phrase": "Starting at medium distance, the camera pushes in on the face with "
                  "large amplitude at slow speed and does not stop at a close-up: it "
                  "keeps travelling until a single eye takes up the entire frame and "
                  "only the iris remains.",
    },
    "aerial pullback": {
        "moves": ("Pull Out", "Pedestal Up"), "amplitude": "with large amplitude",
        "speed": "at fast speed", "min_frames": 124,
        "framing": "Open tight on the subject; the shot must end wide with the whole location "
                   "around them. The subject needs a visible response to the scale, or it "
                   "reads as stock footage. Use Pull Out rather than Zoom Out, so the "
                   "background shrinks along with the subject.",
        "phrase": "Beginning tight on the subject, the camera pulls out and pedestals "
                  "up at once, with large amplitude at fast speed, backing away and "
                  "rising in one continuous climb, so the subject dwindles to a single "
                  "small figure on the ground below while the full location spreads "
                  "out around them to the edges of the frame.",
    },
    "crane rise": {
        "moves": ("Tracking Shot", "Pedestal Up", "Tilt Down"),
        "amplitude": "with large amplitude", "speed": "at fast speed", "min_frames": 124,
        "framing": "Begin at ankle height next to a subject on the move and end high overhead "
                   "with them centred. Write the performance as an arc (one expression "
                   "easing into another), never as a held state, or one frame freezes.",
        "phrase": "Beginning at ankle height next to the moving subject, the camera "
                  "performs a tracking shot beside them with large amplitude at fast "
                  "speed while it pedestals up and tilts down as it travels, and ends "
                  "directly above them looking straight down, with the subject held "
                  "centred and sharp the whole way.",
    },
    "orbit 360": {
        "moves": ("Arc Shot",), "amplitude": "with large amplitude", "speed": "at fast speed",
        "min_frames": 124,
        "framing": "Medium framing on a subject who stays put and stays loose; a rigid pose "
                   "collapses the travel. Both modifiers are required: without them the arc "
                   "shot only bends part way round and never closes the loop.",
        "phrase": "With the subject standing loose and still at the centre, the camera "
                  "performs a full arc shot around them with large amplitude at fast "
                  "speed: a complete circle that begins on the face, passes behind "
                  "them to show the setting beyond their back, and comes round to the "
                  "face again where it started.",
    },
    "handheld": {
        "moves": ("Shake Strongly", "Tracking Shot"), "amplitude": "", "speed": "at fast speed",
        "min_frames": 124,
        "framing": "Medium framing on a subject moving fast enough to earn the shake (a run, "
                   "a chase); on a still subject it reads as a broken camera. Shake Slightly "
                   "gives a static frame with a faint tremor, which is not a handheld look.",
        "phrase": "Running with the subject, the camera performs a tracking shot at "
                  "fast speed and shakes strongly the whole way, the frame jolting off "
                  "line and swinging back with each footfall.",
    },
    "whip pan": {
        "moves": ("Pan Left", "Pan Right"), "amplitude": "", "speed": "",
        "min_frames": 124,
        "framing": "Medium framing. No amplitude or speed words: the pan is driven by its "
                   "landing point, so name both the subject it leaves and the subject and "
                   "place it lands on, and say the shot stays on the second one, or the "
                   "framing wanders back. The blur is a result of that speed, not something "
                   "to ask for. The phrase is written for Pan Right; Pan Left is in the guide "
                   "but was not rendered in the survey.",
        "phrase": "Framed first on one named subject, the camera pans right in one hard "
                  "sweep, leaving that subject behind to land on a second named subject "
                  "at a named spot; everything between the two streaks into horizontal blur for "
                  "the length of the move, and the picture comes back sharp only once "
                  "the second subject fills the frame. The shot ends and stays on the "
                  "second subject, never returning to the first.",
    },
    "dutch angle": {
        "moves": ("Roll Counterclockwise", "Roll Clockwise"), "amplitude": "", "speed": "",
        "min_frames": 124,
        "framing": "Medium framing with visible verticals (a horizon, doorframes, trees) so "
                   "the tilt reads as intended rather than crooked. The roll lands and holds; "
                   "it is not a continuous move. Counterclockwise is the tested direction.",
        "phrase": "The camera rolls counterclockwise a short way and stops, leaving "
                  "the horizon on a slant and the subject leaning off the vertical, "
                  "and it stays at that tilt for the whole shot rather than rolling "
                  "back.",
    },
    "rack focus": {
        "moves": ("Static Shot",), "amplitude": "", "speed": "", "min_frames": 124,
        "framing": "Medium-wide with two clear depth planes: one subject near the lens, "
                   "others far behind. Give the focus change a reason (a look, a sound). "
                   "There is no focus move in the vocabulary; describing the result is "
                   "what works.",
        "phrase": "A static shot, the camera never moving, on two depth planes: the "
                  "near subject starts sharp while the figures far behind are a soft "
                  "blur; then the focus travels back to the far figures, which come up "
                  "crisp at the same moment the near subject goes soft.",
    },
    "snorricam": {
        "moves": ("Tracking Shot",), "amplitude": "", "speed": "", "min_frames": 124,
        "framing": "Tight head-and-shoulders on a subject walking a plain straight line "
                   "through an open space. Extra action or a curved path loosens the lock; "
                   "the tight crop still keeps the background swinging.",
        "phrase": "The subject walks a straight line and the camera, mounted hard to "
                  "their body, performs a tracking shot in which the face never leaves "
                  "the exact centre of frame or changes size, while the whole world "
                  "behind them pitches and swings from side to side with every step.",
    },
    "split screen": {
        "moves": ("Static Shot",), "amplitude": "", "speed": "", "min_frames": 192,
        "framing": "Three equal vertical panels with thin black gutters; unopened panels are "
                   "solid black. Every panel is locked: no pan, no zoom, no movement. Needs "
                   "192 frames; only the reveal order can be set, the reveal times are "
                   "the model's own.",
        "phrase": "Three tall panels of equal width fill the frame, split by narrow "
                  "black bars, and each is a static shot of the same moment from its "
                  "own angle. They light up in turn, left, then middle, then right; a "
                  "panel not yet open is plain black, and once all three are open they "
                  "run together in sync.",
    },
}
SHOT_NONE = "none"
SHOT_ORDER = [SHOT_NONE] + list(SHOTS)

# Cuts. The first five are always available; the rest only on explicit request.
CUTS = ("the camera cuts to", "the shot cuts to", "the shot transitions to",
        "the shot changes to", "the shot switches to")
CUTS_ON_REQUEST = ("cross-dissolve", "fade", "wipe")

# Dialogue continuity markers.
TAG_DIALOGUE = "<d>"
TAG_SCENE_TRANS = "<scenetrans>"
TAG_CUTOFF = "<cutoff>"
VOICEOVER_PHRASE = "says in an off-screen voiceover"
CONTINUITY_PHRASES = ("continues seamlessly across the cut",
                      "continues uninterrupted into the next shot",
                      "carries over from the previous shot",
                      "remains audible across the transition")

STYLES = ("Cinematic", "live-action", "2D-animated", "3D CG", "claymation",
          "watercolor", "vintage film")

# H3 samples on a 17k+5 frame grid at 24fps; these are the reachable shot lengths
# in seconds for the durations a promptor is asked for. Informational -- the
# sampler rounds -- but it stops the LLM writing cut times the model cannot hit.
FPS = 24.0
GRID_FRAMES = (39, 56, 73, 90, 107, 124, 141, 158, 175, 192, 209, 226, 243, 260)


def grid_seconds():
    return tuple(round(f / FPS, 2) for f in GRID_FRAMES)


def grid_frames(seconds: float) -> int:
    """The frame count a stated duration actually renders as: rounded UP onto the
    17k+5 grid, because the sampler never hands back less than was asked for
    (5.00 s is 120 frames, which does not exist, so it becomes 124)."""
    n = max(5, int(round(float(seconds) * FPS)))
    lo = n - ((n - 5) % 17)
    return lo if lo == n else lo + 17


def shot_phrase(name: str) -> str:
    """The camera sentence for a named shot; "" for none or an unknown name."""
    entry = SHOTS.get((name or "").strip().lower())
    return entry["phrase"] if entry else ""


def shots_for(seconds: float) -> list:
    """Names of the shots whose minimum frame count fits the duration once it is
    snapped onto the grid, in table order."""
    frames = grid_frames(seconds)
    return [n for n, s in SHOTS.items() if s["min_frames"] <= frames]


def min_seconds_for_frames(min_frames: int, step: float = 0.5) -> float:
    """The shortest stated duration, on a widget stepping by `step`, that renders
    as at least `min_frames`. Because grid_frames rounds up, anything past the
    previous grid point already lands on min_frames: 124 needs 4.5 s (108 frames
    asked, 124 rendered), 192 needs 7.5 s. Computed here so the tooltip, the docs
    and shots_for() cannot disagree about it."""
    step = float(step) if step and step > 0 else 0.5
    k = 0
    while grid_frames(k * step) < int(min_frames):
        k += 1
    return round(k * step, 2)


def shot_seconds_summary(step: float = 0.5) -> str:
    """'most need 4.5 s, yo-yo zoom and split screen 7.5 s': the tooltip text,
    written from the table so it tracks any change to min_frames."""
    floors = {}
    for name, s in SHOTS.items():
        floors.setdefault(s["min_frames"], []).append(name)
    common = max(floors, key=lambda f: len(floors[f]))
    parts = [f"most need {min_seconds_for_frames(common, step):g} s"]
    for frames in sorted(f for f in floors if f != common):
        names = " and ".join(floors[frames])
        parts.append(f"{names} {min_seconds_for_frames(frames, step):g} s")
    return ", ".join(parts)


def shot_note(name: str, seconds: float) -> str:
    """One line for the report when the chosen shot needs more frames than the
    duration renders as; "" when it fits or no shot is chosen."""
    entry = SHOTS.get((name or "").strip().lower())
    if not entry:
        return ""
    have = grid_frames(seconds)
    need = entry["min_frames"]
    if need <= have:
        return ""
    return (f"SHOT: {name} is known to land in {need} frames ({need / FPS:.2f}s); "
            f"{_fmt_seconds(seconds)}s renders as {have}. Expect a truncated move.")


def detect_task(n_images: int, has_last_frame: bool, reference_mode: bool) -> str:
    """The task type implied by what is actually wired. Auto resolves through here."""
    if reference_mode:
        return "Ref2VA"
    if n_images >= 2:
        return "FL2VA"
    if n_images == 1:
        return "L2VA" if has_last_frame else "I2VA"
    return "T2VA"


def _fmt_seconds(seconds: float) -> str:
    return f"{float(seconds):.2f}"


def alignment_line(task: str, last_shot: int, seconds: float) -> str:
    tpl = ALIGNMENT.get(task, "")
    if not tpl:
        return ""
    return tpl.format(n=max(1, int(last_shot)), s=_fmt_seconds(seconds))


def system_prompt(task: str, seconds: float, shots: int, style: str = "",
                  dialogue: bool = True, reference_mode: bool = False,
                  shot: str = "") -> str:
    """The instruction handed to the LLM. Written from the grammar above, so the
    model is told exactly what the validator will check it against. `shot` names
    a SHOTS recipe whose sentence and framing note join the camera guidance."""
    t = TASKS.get(task, TASKS["T2VA"])
    fields = REF_FIELDS if reference_mode else CORE_FIELDS
    lines = [
        "You write prompts for the MiniMax-H3 video model. Output ONLY the prompt "
        "itself -- no preamble, no explanation, no markdown fences.",
        "",
        f"TASK: {task} ({t['label']}). {t['how']}",
        f"TARGET DURATION: {_fmt_seconds(seconds)} seconds, in {max(1, int(shots))} shot(s).",
        "",
        "STRUCTURE -- emit these fields, in this order, each on its own line, each "
        "followed by a blank line:",
    ]
    lines += [f"  {f}:" for f in fields]
    lines += [
        "",
        "RULES:",
        "- Shot 1 carries the style and opening composition and takes NO timestamp.",
        "- Every later shot starts with a strictly increasing cut time inside the "
        "duration, written as [Shot N] At MM:SS.mmm, followed by a cut phrase: "
        + ", ".join(f'"{c}"' for c in CUTS[:3]) + ".",
        "- Camera motion is written as natural English inside the sentence: a motion "
        "type, optionally an amplitude and a speed. Motion types: "
        + ", ".join(CAMERA_MOVES) + ".",
    ]
    recipe = SHOTS.get((shot or "").strip().lower())
    if recipe:
        lines += [
            f"- CAMERA SHOT: {shot.strip().lower()}. Write Shot 1's camera move as this "
            "sentence, adapted to the subject and place but keeping every motion word, "
            f"amplitude and speed as written: \"{recipe['phrase']}\"",
            f"  Framing for it: {recipe['framing']}",
        ]
    lines += [
        "- Speakers get stable IDs (S1), (S2); a joint line uses (S1,S2). The same "
        "person keeps the same ID across shots. People who never vocalise get no ID.",
        "- Spoken words go inside <d>[Language] ... </d> and NOTHING else goes in "
        "there. The speaker's identity, action and delivery stay outside the tag. "
        "Reproduce the user's words and punctuation exactly.",
        f'- Voiceover uses the exact phrase "{VOICEOVER_PHRASE}", and the sentence '
        "after it must say the on-screen character's lips remain closed.",
        "- Text visible on screen goes in double quotes, in its original language.",
        "- overall_soundscape: 1-4 sentences, one paragraph, ambient and physical "
        "and non-verbal human sound only. No dialogue, no singing, no diegetic "
        'music -- those live in the description. "N/A" only for deliberate silence.',
        "- non_diegetic_music: 1-3 sentences on instrumentation, tempo, rhythm and "
        'dynamics. No mood words, no explaining what it makes the viewer feel. "N/A" '
        "if there is none.",
    ]
    if style:
        lines.append(f"- STYLE: open Shot 1 with {style}.")
    if not dialogue:
        lines.append("- NO dialogue: nobody speaks or sings. Emit no <d> tags at all.")
    if reference_mode:
        lines.append("- Reference labels (<Subject N>, <Picture N>) must be defined in "
                     "subject_definitions before they are used anywhere else, and every "
                     "label used must be defined.")
    return "\n".join(lines)
