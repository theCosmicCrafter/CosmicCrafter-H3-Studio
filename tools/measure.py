"""Texture drift, colour drift and still holds per saved segment of a sequence, as the continuity check measures them.

python tools/measure.py $COMFY_ROOT/output/h3_sequences/ps-s1-base [--every 8]

Texture and colour use every `--every`-th played frame against the first segment; holds use all played frames,
preceded by the previous segment's last frame when a segment continues. Read-only."""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from h3_continuity import check_frames, media  # noqa: E402


def measure(folder, every=8):
    with open(os.path.join(folder, "manifest.json"), encoding="utf-8") as handle:
        segments = json.load(handle)["segments"]
    rows, first, previous_last = [], None, None
    for entry in segments:
        count = entry.get("played", entry["video"]["frames"])
        found = media.read_frames(os.path.join(folder, entry["video"]["file"]), list(range(count)))
        frames = [found[i] for i in range(count)]
        sample = frames[::every]
        measured = check_frames.lab_mean(sample), check_frames.texture_mean(sample)
        first = first or measured
        joined = bool(entry.get("context_frames")) and previous_last is not None
        holds = check_frames.holds(([previous_last] if joined else []) + frames)
        rows.append({"segment": entry["index"], "texture": [round(float(v), 5) for v in measured[1]],
                     "texture_ratio": [round(float(v / b), 3) for v, b in zip(measured[1], first[1])],
                     "words": check_frames.drift_words(measured[0], first[0], measured[1], first[1]),
                     "holds": check_frames.hold_records(holds, joined)})
        previous_last = frames[-1]
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("folder")
    parser.add_argument("--every", type=int, default=8)
    args = parser.parse_args()
    for row in measure(args.folder, args.every):
        print(json.dumps(row))
