"""Render a scene file's boxes on a ComfyUI server, one queued run per box, timing each run.

python tools/render_scene.py --server http://127.0.0.1:8189 --graph speed_graph.json --scene scene.json
    --project lamps_off [--copy-from lamps_shared] [--box 1] [--cap 120] [--set key=json]
    [--context 22] [--frames lamps=107]"""

import argparse
import copy
import json
import shutil
import time
import urllib.request
from pathlib import Path


def call(server, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(server + path, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def prompt_for(graph, scene, project, box, overrides, context=None, frames=None):
    graph = copy.deepcopy(graph)
    key = next(k for k, v in graph.items() if v["class_type"] == "H3C_Timeline")
    inputs = graph[key]["inputs"]
    settings = dict(scene["settings"])
    settings["context_frames"] = str(context or settings["context_frames"])
    inputs.update(settings, name=project)
    timeline = copy.deepcopy(scene["timeline"])
    timeline.update(overrides)
    for item in timeline["boxes"]:
        if item["id"] in (frames or {}):
            item["frames"] = frames[item["id"]]
    if box:
        timeline["render_box"] = box
    inputs["timeline"] = json.dumps(timeline)
    return graph


def run(server, graph, cap):
    queued = call(server, "/prompt", {"prompt": graph})["prompt_id"]
    start = None
    while True:
        record = call(server, f"/history/{queued}").get(queued)
        status = (record or {}).get("status", {})
        if status.get("completed") or status.get("status_str") == "error":
            return time.monotonic() - (start or time.monotonic()), record
        if start is None and any(item[1] == queued for item in call(server, "/queue")["queue_running"]):
            start = time.monotonic()
        if start is not None and time.monotonic() - start > cap:
            urllib.request.urlopen(urllib.request.Request(server + "/interrupt", data=b"{}", method="POST"))
            raise SystemExit(f"stopped: run exceeded {cap} s")
        time.sleep(1)


def render(server, graph, scene, project, cap, box=None, overrides=None, context=None, frames=None):
    """Queue the scene's boxes one run at a time; yield each run's seconds, status, info and Timeline outputs."""
    runs = 1 if box else len(scene["timeline"]["boxes"]) + 1
    for _ in range(runs):
        prompt = prompt_for(graph, scene, project, box, overrides or {}, context, frames)
        seconds, record = run(server, prompt, cap)
        outputs = record.get("outputs", {}).values()
        texts = [text for output in outputs for text in output.get("text", [])]
        timeline = [item for output in outputs for item in output.get("h3c_timeline", [])]
        texts += [f"{item.get('message')} Full video: {(item.get('full_video') or {}).get('filename')}" for item in timeline]
        status = record["status"].get("status_str")
        yield {"seconds": round(seconds, 1), "status": status, "info": texts, "timeline": timeline}
        if not texts or any(item.get("next") is None for item in timeline) or status == "error":
            break


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", default="http://127.0.0.1:8189")
    parser.add_argument("--graph", required=True)
    parser.add_argument("--scene", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--sequences", default="D:/development/rambrogi/work/.h3c-wave1-worker/output/h3_sequences")
    parser.add_argument("--copy-from")
    parser.add_argument("--box", type=int)
    parser.add_argument("--cap", type=float, default=120)
    parser.add_argument("--set", action="append", default=[], help="timeline key=json value")
    parser.add_argument("--context", type=int, help="override the Timeline's context_frames")
    parser.add_argument("--frames", action="append", default=[], help="box id=generated frames")
    args = parser.parse_args()
    graph = json.loads(Path(args.graph).read_text(encoding="utf-8"))
    scene = json.loads(Path(args.scene).read_text(encoding="utf-8"))
    overrides = {key: json.loads(value) for key, value in (item.split("=", 1) for item in args.set)}
    frames = {key: int(value) for key, value in (item.split("=", 1) for item in args.frames)}
    if args.copy_from:
        shutil.copytree(Path(args.sequences) / args.copy_from, Path(args.sequences) / args.project)
    for result in render(args.server, graph, scene, args.project, args.cap, args.box, overrides, args.context, frames):
        print(json.dumps({key: result[key] for key in ("seconds", "status", "info")}))


if __name__ == "__main__":
    main()
