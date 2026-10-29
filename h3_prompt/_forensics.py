"""Video forensics for reverse prompting: what the frames and the track actually did.

A vision model shown a handful of frames will happily invent a story. This helper
measures the things a model cannot see from stills -- where the picture cut, where
it froze, where it flashed or dropped to black, where the sound peaked and what kind
of sound it was -- and writes them down as timestamped lines. The Vision Analyzer then reasons over
that evidence instead of guessing, and the cut times drop straight into an H3
prompt's "At mm:ss.mmm, the camera cuts to" clauses.

Everything here is plain numpy/torch over a ComfyUI IMAGE batch (B,H,W,C in 0..1)
and an optional ComfyUI AUDIO dict ({"waveform": (B,C,N), "sample_rate": int}).
No model, no network, no GPU needed. Every threshold is a named constant with the
reason it has that value, because the heuristics are simple and a user who hits a
false alarm on stylised or very dark footage should be able to see why.
"""
from __future__ import annotations

import math

import numpy as np
import torch

# ---- picture thresholds ------------------------------------------------------
# Adaptive thresholds are median + K * MAD over the whole clip, clamped between a
# floor (below which nothing counts, whatever the clip's noise) and a "sure" value
# (above which it always counts, so a slideshow with more cuts than holds still
# reports its cuts).
CUT_MAD_K = 4.0          # a cut is far outside frame-to-frame noise; 4 MADs keeps pans and fades below it
CUT_DIFF_FLOOR = 0.06    # mean abs luminance change of 6% or more: below this is motion, not a new picture
CUT_DIFF_SURE = 0.25     # a quarter of full range changed at once is a cut in any footage
CUT_HIST_FLOOR = 0.10    # tonal distribution must shift by 10% as well, so a fast pan over one scene is not a cut
CUT_HIST_SURE = 0.50     # half the histogram mass moved: a new scene, whatever the adaptive threshold says
CUT_MIN_GAP_S = 0.25     # two cuts inside a quarter second are one transition (a dissolve, a flash) reported once
HIST_BINS = 16           # coarse luminance histogram: fine enough to see a scene change, coarse enough to ignore noise

FREEZE_DIFF = 0.004      # one 8-bit level (1/255): frames closer than this are the same picture
FREEZE_MIN_S = 0.5       # shorter holds are the subject pausing, not a freeze frame

FLASH_MAD_K = 4.0        # same outlier logic as cuts, applied to the brightness spike series
FLASH_JUMP_FLOOR = 0.15  # a frame 15% brighter than both neighbours is a visible flash
FLASH_JUMP_SURE = 0.40   # 40% brighter than both neighbours is a flash whatever the clip's noise
# The same three numbers, applied to the drop below both neighbours, find black frames
# (a dropout, a blink cut, a strobe's dark phase). Bright and dark spikes are one class:
# a one-frame event whose two transitions must not be counted as cuts.

LUMA_CHUNK_FRAMES = 16   # frames turned to luminance at once: 16 frames of 1080p is about 0.5 GB transient, never the whole clip

# ---- sound thresholds --------------------------------------------------------
RMS_WINDOW_S = 0.5       # half-second windows: long enough to be stable, short enough to place a hit on a cut
PEAK_MAD_K = 2.0         # a loudness peak is a window 2 MADs above the median window level
PEAK_MIN_DB = 6.0        # and at least 6 dB above it (double the amplitude), so a flat track has no peaks
PEAK_MAX_LISTED = 8      # the loudest eight are enough for a model to account for
SILENCE_DB = -80.0       # dB floor so digital silence does not become minus infinity
BAND_LOW_HZ = 250.0      # under 250 Hz: rumble, bass, engines, footsteps through the floor
BAND_HIGH_HZ = 4000.0    # over 4 kHz: hiss, cymbals, sibilance, glass; between is voice and most instruments
TONAL_FLATNESS_MAX = 0.2  # spectral flatness (geometric/arithmetic mean of power): tones sit near 0, noise near 1
BAND_CV_MAX = 0.35       # band shares that wander by more than 35% of their mean are a changing field, not a mix
SPECTRUM_LO_HZ = 60.0    # ignore sub-bass DC and rumble when judging tonality
SPECTRUM_HI_HZ = 8000.0  # ignore the top octave, which cheap encodes low-pass anyway

# ---- contact sheet -----------------------------------------------------------
SHEET_MAX_FRAMES = 16    # a 4x4 grid is the most a vision model reads reliably in one image
SHEET_TILE_W = 320       # tile width in pixels: legible, and 16 of them stay under 1300 px wide


# =============================================================================
# picture
# =============================================================================

def timestamp(seconds: float) -> str:
    """0.0417 -> '00:00.042', the mm:ss.mmm form H3 prompts use for cut times.

    Rounds to whole milliseconds first and carries from there, so 59.9996 is
    01:00.000 and never 00:60.000."""
    ms = max(0, int(round(float(seconds) * 1000.0)))
    m, rem = divmod(ms, 60000)
    return f"{m:02d}:{rem // 1000:02d}.{rem % 1000:03d}"


def _luma(images: torch.Tensor) -> torch.Tensor:
    """(B,H,W,C) -> (B,H,W) luminance in 0..1."""
    x = images.detach().float().cpu().clamp(0, 1)
    if x.dim() == 3:
        x = x.unsqueeze(-1)
    c = x.shape[-1]
    if c >= 3:
        return 0.299 * x[..., 0] + 0.587 * x[..., 1] + 0.114 * x[..., 2]
    return x[..., :c].mean(-1)


def _median_mad(v: torch.Tensor):
    """Lower median and median absolute deviation. The lower median matters on tiny
    batches: with two transitions [0, 0.5] it returns 0 and MAD 0, so the floor
    decides, rather than averaging the cut into the noise estimate."""
    if v.numel() == 0:
        return 0.0, 0.0
    med = v.median().item()
    mad = (v - med).abs().median().item()
    return med, mad


def _adaptive(v: torch.Tensor, k: float, floor: float, sure: float) -> float:
    med, mad = _median_mad(v)
    return max(floor, min(med + k * mad, sure))


def _hist_counts(luma: torch.Tensor) -> torch.Tensor:
    """(n,H,W) luminance -> (n, HIST_BINS) normalised histograms in one bincount.

    Same binning as torch.histc(min=0, max=1): a value of exactly 1.0 lands in the
    last bin. One call for the chunk instead of one histc per frame."""
    n = luma.shape[0]
    idx = (luma.reshape(n, -1) * HIST_BINS).long().clamp_(0, HIST_BINS - 1)
    idx += torch.arange(n).unsqueeze(1) * HIST_BINS
    counts = torch.bincount(idx.reshape(-1), minlength=n * HIST_BINS).reshape(n, HIST_BINS).float()
    return counts / counts.sum(1, keepdim=True).clamp_min(1.0)


def _frame_series(images: torch.Tensor):
    """Per-transition diff (B-1,), per-transition histogram distance (B-1,) and
    per-frame mean brightness (B,), built LUMA_CHUNK_FRAMES frames at a time.

    Only one chunk of the batch is ever converted to float luminance; the batch
    itself is read in place. What survives is three small vectors, so a 20 s 1080p
    clip costs a few hundred MB transient instead of several times its own size."""
    b = int(images.shape[0])
    diffs, hists, means = [], [], []
    prev = None                                                            # last luma plane of the previous chunk
    for start in range(0, b, LUMA_CHUNK_FRAMES):
        luma = _luma(images[start:start + LUMA_CHUNK_FRAMES])              # (n,H,W), the only big transient
        n = luma.shape[0]
        means.append(luma.reshape(n, -1).mean(1))
        hists.append(_hist_counts(luma))
        if prev is not None:
            diffs.append((luma[0] - prev).abs().mean().reshape(1))         # the seam between chunks
        if n > 1:
            diffs.append((luma[1:] - luma[:-1]).abs().reshape(n - 1, -1).mean(1))
        prev = luma[-1].clone()
        del luma
    mean = torch.cat(means) if means else torch.zeros(0)
    hist = torch.cat(hists) if hists else torch.zeros(0, HIST_BINS)
    diff = torch.cat(diffs) if diffs else torch.zeros(0)
    hist_dist = 0.5 * (hist[1:] - hist[:-1]).abs().sum(1) if b >= 2 else torch.zeros(0)
    return diff, hist_dist, mean


def analyze_frames(images: torch.Tensor, fps: float) -> dict:
    """Cuts, freezes, flashes and black frames over an IMAGE batch.

    Returns a dict with frame counts and lists of (frame, time, ...) tuples; the
    string writer below turns it into evidence lines."""
    fps = float(fps) if fps and fps > 0 else 24.0
    b = int(images.shape[0])
    out = {"frames": b, "fps": fps, "seconds": b / fps,
           "width": int(images.shape[2]) if images.dim() == 4 else 0,
           "height": int(images.shape[1]) if images.dim() == 4 else 0,
           "cuts": [], "freezes": [], "flashes": [], "blacks": []}
    if b < 2:
        return out

    diff, hist, mean = _frame_series(images)                               # transition i = frame i -> i+1

    # one-frame spikes first, bright (flash) and dark (black frame), so their in/out
    # transitions are not double-counted as cuts. The first and last frame have one
    # neighbour each; they borrow the frame beyond it, so a lone outlier at either
    # end is still a spike and is not reported as a cut on frame 1 or the last frame.
    spike_frames = set()
    if b >= 3:
        left = torch.cat([mean[1:2], mean[:-2], mean[-3:-2]])              # neighbour before frame i (frame 0 borrows frame 1)
        right = torch.cat([mean[2:3], mean[2:], mean[-2:-1]])              # neighbour after frame i (last frame borrows the one before)
        above = mean - torch.maximum(left, right)                          # frame i over its brighter neighbour
        below = torch.minimum(left, right) - mean                          # frame i under its darker neighbour
        for series, key in ((above, "flashes"), (below, "blacks")):
            thr = _adaptive(series, FLASH_MAD_K, FLASH_JUMP_FLOOR, FLASH_JUMP_SURE)
            for f in range(series.numel()):
                if series[f].item() >= thr:
                    spike_frames.add(f)
                    out[key].append((f, f / fps, series[f].item()))

    # hard cuts: both the pixel change and the tonal shift must be outliers
    thr_d = _adaptive(diff, CUT_MAD_K, CUT_DIFF_FLOOR, CUT_DIFF_SURE)
    thr_h = _adaptive(hist, CUT_MAD_K, CUT_HIST_FLOOR, CUT_HIST_SURE)
    candidates = []
    for i in range(b - 1):
        if (i in spike_frames) or (i + 1 in spike_frames):
            continue
        if diff[i].item() >= thr_d and hist[i].item() >= thr_h:
            candidates.append((i + 1, diff[i].item(), hist[i].item()))       # cut lands ON frame i+1
    min_gap = max(1, int(round(CUT_MIN_GAP_S * fps)))
    for f, d, h in candidates:
        if out["cuts"] and f - out["cuts"][-1][0] < min_gap:
            if d > out["cuts"][-1][2]:                                      # keep the stronger of the pair
                out["cuts"][-1] = (f, f / fps, d, h)
            continue
        out["cuts"].append((f, f / fps, d, h))

    # freezes: runs of transitions under one 8-bit level
    still = diff <= FREEZE_DIFF
    min_frames = max(2, int(math.ceil(FREEZE_MIN_S * fps)))
    i = 0
    while i < b - 1:
        if not still[i]:
            i += 1
            continue
        j = i
        while j < b - 1 and still[j]:
            j += 1
        first, last = i, j                                                  # frames first..last are identical
        n = last - first + 1
        if n >= min_frames:
            out["freezes"].append((first, last, first / fps, (last + 1) / fps, n))
        i = j + 1
    return out


def contact_sheet(images: torch.Tensor, fps: float, max_frames: int = SHEET_MAX_FRAMES,
                  tile_w: int = SHEET_TILE_W) -> torch.Tensor:
    """Evenly sampled, timestamped grid of up to max_frames frames as one IMAGE (1,H,W,3)."""
    from PIL import Image, ImageDraw
    fps = float(fps) if fps and fps > 0 else 24.0
    b = int(images.shape[0])
    n = max(1, min(int(max_frames), b))
    idx = sorted({int(round(v)) for v in torch.linspace(0, b - 1, n).tolist()})
    cols = int(math.ceil(math.sqrt(len(idx))))
    rows = int(math.ceil(len(idx) / cols))
    h, w = int(images.shape[1]), int(images.shape[2])
    tw = max(16, int(tile_w))
    th = max(16, int(round(h * tw / max(1, w))))
    sheet = Image.new("RGB", (cols * tw, rows * th), (0, 0, 0))
    draw = ImageDraw.Draw(sheet)
    for k, i in enumerate(idx):
        arr = (images[i].detach().float().cpu().clamp(0, 1) * 255).to(torch.uint8).numpy()
        if arr.ndim == 2:
            arr = arr[..., None]
        if arr.shape[-1] == 1:
            arr = arr.repeat(3, axis=-1)
        tile = Image.fromarray(arr[..., :3], "RGB").resize((tw, th))
        x, y = (k % cols) * tw, (k // cols) * th
        sheet.paste(tile, (x, y))
        label = f"{timestamp(i / fps)}  f{i}"
        draw.rectangle([x, y, x + 6 * len(label) + 8, y + 14], fill=(0, 0, 0))
        draw.text((x + 4, y + 2), label, fill=(255, 255, 255))
    t = torch.from_numpy(np.asarray(sheet).copy()).float() / 255.0
    return t.unsqueeze(0)


# =============================================================================
# sound
# =============================================================================

def _mono(audio: dict):
    """ComfyUI AUDIO -> (mono waveform (N,), sample_rate) or (None, 0)."""
    if not isinstance(audio, dict) or audio.get("waveform") is None:
        return None, 0
    wav = audio["waveform"]
    sr = int(audio.get("sample_rate", 0) or 0)
    if not torch.is_tensor(wav) or sr <= 0:
        return None, 0
    w = wav.detach().float().cpu()
    while w.dim() > 2:
        w = w[0]                       # batch -> first item
    if w.dim() == 2:
        w = w.mean(0)                  # channels -> mono
    if w.numel() == 0:
        return None, 0
    return w, sr


def _db(x: float) -> float:
    return max(SILENCE_DB, 20.0 * math.log10(x)) if x > 0 else SILENCE_DB


def analyze_audio(audio: dict) -> dict:
    """RMS windows with peaks, three-band energy and a music-vs-field verdict."""
    w, sr = _mono(audio)
    if w is None:
        return {"present": False}
    n = w.numel()
    win = max(1, int(round(RMS_WINDOW_S * sr)))
    n_win = int(math.ceil(n / win))
    pad = n_win * win - n
    if pad:
        w = torch.cat([w, torch.zeros(pad)])
    frames = w.reshape(n_win, win)

    rms = frames.pow(2).mean(1).sqrt()
    rms_db = torch.tensor([_db(v) for v in rms.tolist()])
    med, mad = _median_mad(rms_db)
    peaks = []
    for i in range(n_win):
        v = rms_db[i].item()
        if v >= med + PEAK_MAD_K * mad and v >= med + PEAK_MIN_DB:
            loudest = int(frames[i].abs().argmax().item())                 # the peak sample, not the window start
            peaks.append(((i * win + loudest) / sr, v))
    peaks.sort(key=lambda p: -p[1])
    peaks = sorted(peaks[:PEAK_MAX_LISTED])

    # spectrum per window (Hann), averaged: Welch estimate of the track's power
    hann = torch.hann_window(win)
    spec = torch.fft.rfft(frames * hann, dim=1).abs().pow(2)              # (n_win, bins)
    freqs = torch.fft.rfftfreq(win, d=1.0 / sr)
    low = freqs < BAND_LOW_HZ
    high = freqs >= BAND_HIGH_HZ
    mid = ~(low | high)
    band = torch.stack([spec[:, low].sum(1), spec[:, mid].sum(1), spec[:, high].sum(1)], 1)
    total = band.sum(1, keepdim=True)
    active = (total.squeeze(1) > 0) & (rms_db > SILENCE_DB + 20)          # windows with actual signal
    share = band[active] / total[active].clamp_min(1e-12) if active.any() else torch.zeros(0, 3)
    mean_share = share.mean(0) if share.numel() else torch.tensor([0.0, 0.0, 0.0])
    if share.shape[0] >= 2:
        cv = (share.std(0) / share.mean(0).clamp_min(1e-6)).mean().item()
    else:
        cv = 0.0

    keep = (freqs >= SPECTRUM_LO_HZ) & (freqs <= SPECTRUM_HI_HZ)
    mean_spec = spec[active][:, keep].mean(0) if active.any() else torch.zeros(int(keep.sum()))
    mean_spec = mean_spec.clamp_min(1e-20)
    flatness = (torch.exp(torch.log(mean_spec).mean()) / mean_spec.mean()).item() if mean_spec.numel() else 1.0

    tonal = flatness < TONAL_FLATNESS_MAX
    stable = cv < BAND_CV_MAX
    if not active.any():
        verdict = "silence (no window above the noise floor)"
    elif tonal and stable:
        verdict = "music (sustained tonal peaks, steady band balance)"
    elif tonal:
        verdict = "mixed: tonal content over a shifting bed (voice or music with field sound)"
    else:
        verdict = "field sound (broadband, no sustained tonal peaks)"

    return {
        "present": True, "sample_rate": sr, "seconds": n / sr,
        "mean_db": rms_db[active].mean().item() if active.any() else SILENCE_DB,
        "max_db": rms_db.max().item(),
        "peaks": peaks, "bands": [float(v) for v in mean_share.tolist()],
        "flatness": flatness, "band_cv": cv, "verdict": verdict,
    }


# =============================================================================
# the evidence string
# =============================================================================

def evidence_lines(frames: dict, audio: dict | None) -> str:
    fps = frames["fps"]
    lines = [f"VIDEO FORENSICS: {frames['frames']} frames at {fps:.2f} fps = "
             f"{frames['seconds']:.3f} s, {frames['width']}x{frames['height']}",
             "LIVE ACTION"]
    if frames["cuts"]:
        for f, t, d, h in frames["cuts"]:
            lines.append(f"  {timestamp(t)}  hard cut (frame {f}; diff {d:.2f}, hist {h:.2f})")
    else:
        lines.append("  no hard cuts found")
    for first, last, t0, t1, n in frames["freezes"]:
        lines.append(f"  {timestamp(t0)}-{timestamp(t1)}  freeze, {n} frames (frames {first}-{last})")
    for f, t, jump in frames["flashes"]:
        lines.append(f"  {timestamp(t)}  flash (frame {f}; +{jump:.2f} luminance over both neighbours)")
    for f, t, drop in frames.get("blacks", []):
        lines.append(f"  {timestamp(t)}  black frame (frame {f}; -{drop:.2f} luminance under both neighbours)")
    if not frames["freezes"]:
        lines.append("  no freezes found")
    if not frames["flashes"]:
        lines.append("  no flashes found")
    if not frames.get("blacks"):
        lines.append("  no black frames found")

    lines.append("SOUND")
    if not audio or not audio.get("present"):
        lines.append("  no audio connected")
        return "\n".join(lines)
    lines.append(f"  track {audio['seconds']:.3f} s at {audio['sample_rate']} Hz, "
                 f"mean {audio['mean_db']:.1f} dB, max {audio['max_db']:.1f} dB "
                 f"(dBFS, {RMS_WINDOW_S:.1f} s windows)")
    if audio["peaks"]:
        lines.append("  peaks: " + ", ".join(f"{timestamp(t)} ({v:.1f} dB)" for t, v in audio["peaks"]))
    else:
        lines.append("  peaks: none (level stays within the median window)")
    lo, mi, hi = audio["bands"]
    lines.append(f"  bands: low {lo * 100:.0f}% / mid {mi * 100:.0f}% / high {hi * 100:.0f}%  "
                 f"(under {BAND_LOW_HZ:.0f} Hz / {BAND_LOW_HZ:.0f}-{BAND_HIGH_HZ:.0f} Hz / "
                 f"over {BAND_HIGH_HZ:.0f} Hz)")
    lines.append(f"  verdict: {audio['verdict']}  "
                 f"(flatness {audio['flatness']:.2f}, band drift {audio['band_cv']:.2f})")
    return "\n".join(lines)


def run(images: torch.Tensor, fps: float, audio: dict | None = None):
    """The node's whole job: (evidence string, contact sheet IMAGE)."""
    frames = analyze_frames(images, fps)
    sound = analyze_audio(audio) if audio is not None else None
    return evidence_lines(frames, sound), contact_sheet(images, fps)
