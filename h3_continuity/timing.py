"""Frame, token and audio-clock arithmetic for MiniMax H3 (24 fps, 17k+5 frame grid)."""

FPS = 24
AUDIO_TICKS_PER_SECOND = 40
FRAME_PER_TOKEN = (1, 4, 4, 4, 4)
CONTEXT_OPTIONS = ("22", "39", "90", "141")
GRID_STEP = 17


def frames_for_tokens(tokens):
    return sum(FRAME_PER_TOKEN[k % 5] for k in range(tokens))


def tokens_for_frames(frames):
    if frames < 5 or frames % 17 != 5:
        raise ValueError(f"{frames} frames is not on the H3 17k+5 frame grid")
    return (frames - 5) // 17 * 5 + 2


def ticks_for_frames(frames):
    return round(frames * AUDIO_TICKS_PER_SECOND / FPS)


def audio_tail_start(source_frames, source_ticks, context_frames):
    """First audio tick of the source's last `context_frames` frames, kept inside the source audio."""
    start = round((source_frames - context_frames) * AUDIO_TICKS_PER_SECOND / FPS)
    return max(0, min(start, source_ticks - ticks_for_frames(context_frames)))


def effective_audio_context(context_frames, carry_audio, audio_context_frames=0):
    if type(audio_context_frames) is not int or audio_context_frames < 0:
        raise ValueError('audio_context_frames must be a nonnegative integer; 0 follows video context')
    return min(context_frames, audio_context_frames or context_frames) if carry_audio else 0


def audio_context_window(source_frames, source_ticks, context_frames, audio_context_frames=0):
    """(source start, target start, copied ticks), a suffix of our existing aligned audio block."""
    full = ticks_for_frames(context_frames)
    ticks = ticks_for_frames(effective_audio_context(context_frames, True, audio_context_frames))
    if source_ticks < full:
        raise ValueError(f'the previous segment has only {source_ticks} audio ticks, fewer than the aligned {full}')
    target_start = full - ticks
    source_start = audio_tail_start(source_frames, source_ticks, context_frames) + target_start
    return source_start, target_start, ticks


def sample_at_frame(frame, sample_rate):
    return round(frame * sample_rate / FPS)


def frames_at_fps(frames, fps):
    return round(frames * fps / FPS)


def seconds(frames):
    return frames / FPS


def window_frames(frames, minimum=22):
    """Nearest context-window length on the 17k+5 grid, at least `minimum`."""
    return max(minimum, GRID_STEP * round((frames - 5) / GRID_STEP) + 5)


def window_settings(length, overlap):
    """(length, overlap) in frames, both on the 17k+5 grid with the overlap shorter than the window, so every
    static window after the first starts on a chunk boundary."""
    length = window_frames(length)
    overlap = min(window_frames(overlap, minimum=5), length - GRID_STEP)
    return length, overlap


def window_count(total_frames, length, overlap):
    """Static context windows that cover `total_frames` (one when the box fits a single window)."""
    length, overlap = window_settings(length, overlap)
    total = tokens_for_frames(window_frames(total_frames))
    span = tokens_for_frames(length)
    stride = span - tokens_for_frames(overlap)
    return 1 if total <= span else 1 + -(-(total - span) // stride)
