"""Smoke test one scenario: render each arm through render_scene, then a side-by-side and a JSON summary.

python tools/smoke.py --spec examples/prefixstream_scenes/smoke/s2_baseline.json --graph speed_graph.json
    [--server http://127.0.0.1:8188] [--output $COMFY_ROOT/output]
    [--out .tmp/smoke/s2] [--cap 600] [--arm base]

A spec is {"scene": "<path relative to the repository>" or an inline scene, "arms": {name: patch}}. A patch may hold
"settings" (Timeline node inputs), "timeline" (Timeline keys), "boxes" ({box id: fields}) and "graph" ({node id: node
or null}). Projects are named ps-<scenario>-<arm>; run the batch inside one shared GPU-queue turn."""

import argparse
import copy
import json
import os
import shutil
import subprocess
import urllib.error
from pathlib import Path

import render_scene
import side_by_side

ROOT = Path(__file__).resolve().parents[1]


def merge(base, patch):
    """Recursive dict merge: None deletes a key, anything else replaces it."""
    out = dict(base)
    for key, value in patch.items():
        if value is None:
            out.pop(key, None)
        elif isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def arm_scene(scene, arm):
    scene = copy.deepcopy(scene)
    scene["settings"] = merge(scene.get("settings", {}), arm.get("settings", {}))
    scene["timeline"] = merge(scene["timeline"], arm.get("timeline", {}))
    patches = dict(arm.get("boxes", {}))
    scene["timeline"]["boxes"] = [merge(box, patches.pop(box["id"], {})) for box in scene["timeline"]["boxes"]]
    if patches:
        raise ValueError(f"arm patches unknown boxes {sorted(patches)}")
    return scene


def arm_graph(graph, arm):
    return merge(graph, arm.get("graph", {}))


def load_scene(spec, root=ROOT):
    scene = spec["scene"]
    return json.loads((Path(root) / scene).read_text(encoding="utf-8")) if isinstance(scene, str) else scene


def full_video(output_root, records):
    views = [item["full_video"] for record in records for item in record.get("timeline", []) if item.get("full_video")]
    if not views:
        return None
    path = Path(output_root) / views[-1].get("subfolder", "") / views[-1]["filename"]
    return path if path.is_file() else None


def probe(path):
    result = subprocess.run(["ffprobe", "-v", "error", "-count_packets", "-show_entries",
                             "stream=codec_type,nb_read_packets:format=duration", "-of", "json", str(path)],
                            capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    video = next((s for s in data["streams"] if s["codec_type"] == "video"), {})
    return {"duration": float(data["format"]["duration"]), "frames": int(video.get("nb_read_packets", 0)),
            "audio": any(s["codec_type"] == "audio" for s in data["streams"])}


def compose(clips, labels, output):
    subprocess.run(side_by_side.command([str(clip) for clip in clips], labels, str(output)), check=True)


def run(spec, graph, scenario, out, output_root, server, cap, arms=None,
        render=render_scene.render, probe=probe, compose=compose):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    scene = load_scene(spec)
    summary = {"scenario": scenario, "arms": {}}
    for name, arm in spec["arms"].items():
        if arms and name not in arms:
            continue
        records, info = [], []
        try:
            for record in render(server, arm_graph(graph, arm), arm_scene(scene, arm), f"ps-{scenario}-{name}", cap):
                records.append(record)
                info += record["info"]
        except SystemExit as stopped:  # render_scene stops a run that exceeds its cap
            info.append(str(stopped))
        except urllib.error.HTTPError as rejected:  # ComfyUI refused the prompt, e.g. a missing node
            info.append(f"HTTP {rejected.code}: {rejected.read().decode('utf-8', 'replace')[:500]}")
        video = full_video(output_root, records)
        copied = None
        if video is not None:
            copied = out / f"{name}.mp4"
            shutil.copyfile(video, copied)
        summary["arms"][name] = {"runs": [{"seconds": r["seconds"], "status": r["status"]} for r in records],
                                 "info": info, "video": str(copied) if copied else None,
                                 "probe": probe(copied) if copied else None}
    done = [(name, arm["video"]) for name, arm in summary["arms"].items() if arm["video"]]
    if len(done) >= 2 and len(done) == len(summary["arms"]):
        compose([video for _, video in done], [name for name, _ in done], out / "side_by_side.mp4")
        summary["side_by_side"] = str(out / "side_by_side.mp4")
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", required=True)
    parser.add_argument("--graph", required=True)
    parser.add_argument("--server", default="http://127.0.0.1:8188")
    comfy = os.environ.get("COMFY_ROOT")
    parser.add_argument("--output", default=comfy and str(Path(comfy) / "output"), required=not comfy,
                        help="ComfyUI's output folder; defaults to $COMFY_ROOT/output")
    parser.add_argument("--out")
    parser.add_argument("--cap", type=float, default=600)
    parser.add_argument("--arm", action="append", help="render only these arms")
    args = parser.parse_args()
    spec_path = Path(args.spec)
    scenario = spec_path.stem.split("_")[0]
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    graph = json.loads(Path(args.graph).read_text(encoding="utf-8"))
    out = args.out or ROOT / ".tmp" / "smoke" / spec_path.stem
    print(json.dumps(run(spec, graph, scenario, out, args.output, args.server, args.cap, args.arm), indent=2))


if __name__ == "__main__":
    main()
