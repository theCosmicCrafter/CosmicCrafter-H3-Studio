"""Read-only CPU measurements; none is a perceptual quality verdict."""

import numpy as np
import torch


def video_join(before, after):
    before, after = np.asarray(before[-6:], dtype=np.float64), np.asarray(after[:6], dtype=np.float64)
    if not len(before) or not len(after):
        return {"status": "unavailable", "reason": "Both sides need a delivered frame.",
                "boundary_frame_mae": None, "nearby_frame_mae": [], "boundary_index": None}
    if before.shape[1:] != after.shape[1:]:
        return {"status": "unavailable", "reason": "Delivered frame geometry differs across this cut.",
                "boundary_frame_mae": None, "nearby_frame_mae": [], "boundary_index": None}
    joined = np.concatenate((before, after))
    if not np.isfinite(joined).all():
        return {"status": "unavailable", "reason": "Video contains non-finite values.",
                "boundary_frame_mae": None, "nearby_frame_mae": [], "boundary_index": None}
    steps = np.abs(np.diff(joined, axis=0)).mean(axis=(1, 2, 3))
    boundary = len(before) - 1
    return {"status": "ok", "boundary_frame_mae": float(steps[boundary]),
            "nearby_frame_mae": steps.tolist(), "boundary_index": boundary}


def audio_join(before, after, sample_rate):
    result = {"status": "unavailable", "before_rms": None, "after_rms": None, "rms_step_db": None,
              "sample_jump": None, "before_samples": 0, "after_samples": 0}
    if before is None or after is None or sample_rate is None or sample_rate <= 0:
        return {**result, "reason": "Both saved waveforms and a common sample rate are required."}
    count = max(1, round(sample_rate * 0.5))
    before, after = np.asarray(before[:, -count:], dtype=np.float64), np.asarray(after[:, :count], dtype=np.float64)
    result.update(before_samples=before.shape[-1], after_samples=after.shape[-1])
    if not before.size or not after.size:
        return {**result, "reason": "An audio side is empty."}
    if not np.isfinite(before).all() or not np.isfinite(after).all():
        return {**result, "reason": "Audio contains non-finite values."}
    a, b = float(np.sqrt(np.mean(before ** 2))), float(np.sqrt(np.mean(after ** 2)))
    result.update(before_rms=a, after_rms=b, sample_jump=float(np.abs(after[:, 0] - before[:, -1]).mean()))
    if a == 0 or b == 0:
        return {**result, "status": "partial", "reason": "Zero-energy audio has no finite level ratio."}
    result["rms_step_db"] = float(20 * np.log10(b / a))
    if min(before.shape[-1], after.shape[-1]) < count:
        return {**result, "status": "partial", "reason": "Less than 500 ms is available on a side."}
    return {**result, "status": "ok"}


def overlap_lag(reference, replay, sample_rate):
    """Positive delay means replay is delayed; only compare the same known source interval."""
    result = {"status": "unavailable", "delay_samples": None, "delay_ms": None,
              "correlation": None, "windows": 0}
    if sample_rate <= 0:
        return {**result, "reason": "A positive sample rate is required."}
    reference, replay = np.asarray(reference, dtype=np.float64), np.asarray(replay, dtype=np.float64)
    channels = max(reference.shape[0], replay.shape[0])
    reference, replay = np.broadcast_to(reference, (channels, reference.shape[-1])), np.broadcast_to(replay, (channels, replay.shape[-1]))
    window, hop = max(1, round(sample_rate * 0.05)), max(1, round(sample_rate * 0.025))
    limit = round(sample_rate * 0.04)
    stop = min(reference.shape[-1], replay.shape[-1]) - window - limit
    if stop < limit:
        return {**result, "reason": "Not enough known overlap for the window and lag search."}
    if not np.isfinite(reference).all() or not np.isfinite(replay).all():
        return {**result, "reason": "Known overlap contains non-finite values."}
    profiles = []
    for start in range(limit, stop + 1, hop):
        anchor = reference[:, start:start + window]
        anchor = anchor - anchor.mean(axis=-1, keepdims=True)
        anchor_energy = float(np.square(anchor).sum())
        if anchor_energy <= 1e-20:
            continue
        search = replay[:, start - limit:start + window + limit]
        sums = np.pad(np.cumsum(search, axis=-1), ((0, 0), (1, 0)))
        squares = np.pad(np.cumsum(np.square(search), axis=-1), ((0, 0), (1, 0)))
        means = sums[:, window:] - sums[:, :-window]
        energy = (squares[:, window:] - squares[:, :-window] - means ** 2 / window).sum(axis=0)
        norm = np.sqrt(anchor_energy * np.maximum(energy, 0))
        numerator = sum(np.correlate(row, template, mode="valid") for row, template in zip(search, anchor))
        correlation = np.divide(numerator, norm, out=np.zeros_like(numerator), where=norm > 1e-20)
        profiles.append(np.clip(correlation, -1, 1))
    result["windows"] = len(profiles)
    if not profiles:
        return {**result, "reason": "Known overlap has no usable energy."}
    scores = np.mean(profiles, axis=0)
    best = int(np.argmax(scores))
    score = float(scores[best])
    result["correlation"] = score
    if score < 0.8:
        return {**result, "reason": "Correlation is too weak to establish a lag."}
    separate = np.abs(np.arange(len(scores)) - best) >= max(1, round(sample_rate * 0.005))
    if np.any(scores[separate] >= score - 0.02):
        return {**result, "status": "ambiguous", "reason": "Competing lag peaks; periodic content cannot establish alignment."}
    delay = best - limit
    return {**result, "status": "ok", "delay_samples": delay, "delay_ms": 1000 * delay / sample_rate}


def phase_drift(previous, current, carried_tokens, *, ending_tokens=0):
    previous, current = previous.detach().cpu().float(), current.detach().cpu().float()
    pairs = []
    for phase in range(5):
        source = list(range(phase, previous.shape[2], 5))
        target = [i for i in range(carried_tokens, current.shape[2] - ending_tokens) if i % 5 == phase]
        if not source or not target:
            continue
        a = previous[0, :, source[-1]].flatten(1)
        b = current[0, :, target[0]].flatten(1)
        if not torch.isfinite(a).all() or not torch.isfinite(b).all():
            return {"status": "unavailable", "pairs": [], "reason": "Compared latent rows contain non-finite values."}
        pairs.append({"phase": phase, "source_token": source[-1], "target_token": target[0],
                      "mean_delta": float((b.mean(dim=1) - a.mean(dim=1)).abs().mean()),
                      "spread_delta": float((b.std(dim=1, unbiased=False) - a.std(dim=1, unbiased=False)).abs().mean())})
    return {"status": "ok" if pairs else "unavailable", "pairs": pairs,
            **({} if pairs else {"reason": "No free matching-phase token pair is available."})}
