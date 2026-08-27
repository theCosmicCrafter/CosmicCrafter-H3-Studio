"""Work out how long an H3 clip has to be.

H3 does not accept an arbitrary frame count.  Video length must sit on the
model's ``17k + 5`` grid at 24 fps (5, 22, 39, 56, ... 124, 141, ...), because
the causal VAE encodes 17 source frames into 5 latent frames and a length off
that grid leaves a partial group the model cannot represent.

Getting this wrong is quiet rather than loud: the frame count silently snaps
somewhere else, and any node you told the *unsnapped* number to - the audio
analysis window in particular - is then measuring a different span than the
video actually covers, so the curve and the picture drift apart.

This module turns a duration (or an audio clip) into the legal frame count and
everything derived from it, so one node can feed the whole graph.
"""

import logging
import math

_LOG = logging.getLogger("h3_motion_context.frame_calc")

FPS = 24.0

#: H3's frame grid: ``frames % FRAME_GROUP == FRAME_REMAINDER``.
FRAME_GROUP = 17
FRAME_REMAINDER = 5

#: Latent frames produced per :data:`FRAME_GROUP` source frames.
LATENT_GROUP = 5

AUDIO_LATENT_FPS = 40.0

#: The window H3 was trained on, in frames at 24 fps (~5.2s to ~15.1s).
TRAINED_MIN_FRAMES = 124
TRAINED_MAX_FRAMES = 362


def is_on_grid(frames):
    """True when ``frames`` is a length H3 can actually generate."""
    frames = int(frames)
    return frames >= FRAME_REMAINDER and frames % FRAME_GROUP == FRAME_REMAINDER


def align_up(frames):
    """Smallest legal frame count >= ``frames``."""
    frames = max(FRAME_REMAINDER, int(frames))
    while frames % FRAME_GROUP != FRAME_REMAINDER:
        frames += 1
    return frames


def align_down(frames):
    """Largest legal frame count <= ``frames`` (never below the 5-frame floor)."""
    frames = int(frames)
    if frames <= FRAME_REMAINDER:
        return FRAME_REMAINDER
    while frames % FRAME_GROUP != FRAME_REMAINDER:
        frames -= 1
    return frames


def align_nearest(frames):
    """Legal frame count closest to ``frames``; ties round up (longer)."""
    up, down = align_up(frames), align_down(frames)
    return down if (frames - down) < (up - frames) else up


ROUNDING = {"nearest": align_nearest, "up": align_up, "down": align_down}


def align(frames, rounding="nearest"):
    try:
        return ROUNDING[rounding](frames)
    except KeyError:
        raise ValueError(
            f"h3_frame_calc: unknown rounding {rounding!r}; "
            f"expected one of {sorted(ROUNDING)}"
        ) from None


def video_latent_t(frames):
    """Latent frames H3's video VAE produces for ``frames`` source frames."""
    frames = int(frames)
    if frames <= FRAME_REMAINDER:
        return 2
    return ((frames - FRAME_REMAINDER) // FRAME_GROUP) * LATENT_GROUP + 2


def audio_latent_t(frames, fps=FPS):
    """Audio latent length (40 Hz) matching ``frames`` video frames."""
    return int(round(int(frames) / float(fps) * AUDIO_LATENT_FPS))


def frames_for_seconds(seconds, fps=FPS, rounding="nearest"):
    """Legal frame count covering ``seconds``."""
    fps = max(1e-6, float(fps))
    return align(max(0.0, float(seconds)) * fps, rounding)


def audio_duration(audio):
    """Seconds of an AUDIO dict, or ``None`` when it is not readable."""
    if not isinstance(audio, dict):
        return None
    waveform, rate = audio.get("waveform"), audio.get("sample_rate")
    if waveform is None or not rate:
        return None
    try:
        samples = int(waveform.shape[-1])
    except (AttributeError, IndexError, TypeError):
        return None
    rate = float(rate)
    if rate <= 0 or samples <= 0:
        return None
    return samples / rate


def plan(seconds, fps=FPS, rounding="nearest", clip_start_seconds=0.0,
         max_frames=0):
    """Everything derived from a target duration.

    ``max_frames`` caps the clip (0 = uncapped) and is itself snapped down to the
    grid, so a cap can never produce an illegal length.
    """

    fps = max(1e-6, float(fps))
    start = max(0.0, float(clip_start_seconds))
    available = max(0.0, float(seconds) - start)

    frames = frames_for_seconds(available, fps, rounding)

    cap = int(max_frames or 0)
    if cap > 0:
        frames = min(frames, align_down(cap))

    duration = frames / fps
    covered = min(duration, available) if available > 0 else duration
    remainder = max(0.0, available - duration)

    return {
        "frames": frames,
        "latent_t": video_latent_t(frames),
        "audio_latent_t": audio_latent_t(frames, fps),
        "duration_seconds": duration,
        "remainder_seconds": remainder,
        # How many clips of this length it takes to cover the rest of the audio.
        "clips_to_cover": max(1, math.ceil(available / duration)) if duration > 0 else 1,
        "available_seconds": available,
        "on_grid": is_on_grid(frames),
        "in_trained_range": TRAINED_MIN_FRAMES <= frames <= TRAINED_MAX_FRAMES,
    }


def format_report(info, fps=FPS, source="seconds"):
    """Human-readable summary for the node's STRING output."""
    lines = [
        f"source          : {source}",
        f"audio available : {info['available_seconds']:.3f}s",
        f"frames          : {info['frames']}  (17k+5 grid, {fps:g} fps)",
        f"clip duration   : {info['duration_seconds']:.3f}s",
        f"video latent T  : {info['latent_t']}",
        f"audio latent T  : {info['audio_latent_t']}",
    ]
    if info["remainder_seconds"] > 1e-6:
        lines.append(
            f"uncovered audio : {info['remainder_seconds']:.3f}s "
            f"({info['clips_to_cover']} clips of this length would cover it)"
        )
    if not info["in_trained_range"]:
        lines.append(
            f"NOTE            : outside H3's trained range "
            f"({TRAINED_MIN_FRAMES}-{TRAINED_MAX_FRAMES} frames); quality is untested"
        )
    return "\n".join(lines)


class MiniMaxH3FrameCalculator:
    """Audio (or a duration) -> the H3-legal frame count and everything from it."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "seconds": ("FLOAT", {
                    "default": 5.0, "min": 0.0, "max": 99999.0, "step": 0.01,
                    "tooltip": "Target duration. Ignored when an audio input is connected.",
                }),
                "fps": ("INT", {
                    "default": 24, "min": 1, "max": 120,
                    "tooltip": "H3 is native at 24 fps. Changing this changes how a duration maps to frames.",
                }),
                "rounding": (list(ROUNDING), {
                    "default": "nearest",
                    "tooltip": "How to snap onto H3's 17k+5 grid. up never truncates the audio; down never overruns it.",
                }),
                "clip_start_seconds": ("FLOAT", {
                    "default": 0.0, "min": 0.0, "max": 99999.0, "step": 0.01,
                    "tooltip": "Offset into the song. Only the audio after this point is measured.",
                }),
                "max_frames": ("INT", {
                    "default": 0, "min": 0, "max": 99999,
                    "tooltip": "Cap the clip length (0 = uncapped). Snapped down to the grid, so a cap stays legal.",
                }),
            },
            "optional": {
                "audio": ("AUDIO", {
                    "tooltip": "Measure this clip's duration instead of using the seconds widget.",
                }),
            },
        }

    RETURN_TYPES = ("INT", "INT", "INT", "FLOAT", "FLOAT", "INT", "STRING")
    RETURN_NAMES = ("frames", "latent_t", "audio_latent_t", "duration_seconds",
                    "remainder_seconds", "clips_to_cover", "report")
    FUNCTION = "calculate"
    CATEGORY = "conditioning/minimax"
    DESCRIPTION = (
        "Turn an audio clip (or a duration) into the frame count H3 can actually "
        "generate - its length must sit on the 17k+5 grid at 24 fps. Wire "
        "'frames' into both MiniMaxH3ImageToVideo.length and "
        "MiniMaxH3AudioAnalyze.clip_frames so the picture and the analysis "
        "window cannot drift apart."
    )

    def calculate(self, seconds=5.0, fps=24, rounding="nearest",
                  clip_start_seconds=0.0, max_frames=0, audio=None):
        source = "seconds widget"
        target = float(seconds)

        if audio is not None:
            measured = audio_duration(audio)
            if measured is None:
                _LOG.warning(
                    "h3_frame_calc: audio input is not readable; "
                    "falling back to the seconds widget"
                )
            else:
                target = measured
                source = f"audio ({measured:.3f}s)"

        info = plan(target, fps=fps, rounding=rounding,
                    clip_start_seconds=clip_start_seconds, max_frames=max_frames)

        return (
            info["frames"],
            info["latent_t"],
            info["audio_latent_t"],
            info["duration_seconds"],
            info["remainder_seconds"],
            info["clips_to_cover"],
            format_report(info, fps=fps, source=source),
        )


NODE_CLASS_MAPPINGS = {
    "MiniMaxH3FrameCalculator": MiniMaxH3FrameCalculator,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MiniMaxH3FrameCalculator": "H3 Frame Calculator",
}
