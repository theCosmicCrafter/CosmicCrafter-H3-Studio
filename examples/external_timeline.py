"""Synchronous, receipt-first H3 Timeline consumer; Python standard library only.

Run with --help. Input is the successful /h3c/timeline/prepare response. See the
public EXTERNAL-TIMELINE guide for authoring, graph requirements and recovery.
"""
import argparse
import copy
from contextlib import contextmanager, nullcontext
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request


class ClientError(RuntimeError):
    pass


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def require(condition, message):
    if not condition:
        raise ClientError(message)


def base_url(value):
    url = urllib.parse.urlsplit(value)
    require(url.scheme in ("http", "https") and url.hostname and not url.username
            and not url.password and not url.query and not url.fragment, "invalid base URL")
    # Preserve explicit port, spelling/aliases and reverse-proxy base path.
    return urllib.parse.urlunsplit((url.scheme, url.netloc, url.path.rstrip("/"), "", ""))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ClientError("HTTP redirect refused; use the exact ComfyUI base URL")


class HTTP:
    def __init__(self, base, timeout, end):
        self.base, self.timeout, self.end = base, timeout, end
        self.opener = urllib.request.build_opener(NoRedirect)

    @contextmanager
    def response(self, path, body=None):
        remaining = self.end - time.monotonic()
        require(remaining > 0, "poll/HTTP deadline exceeded; resume with the same receipt")
        request = urllib.request.Request(self.base + path, data=None if body is None else encoded(body),
                                         headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(request, timeout=min(self.timeout, remaining)) as response:
                yield response
        except (OSError, ValueError, urllib.error.URLError) as error:
            raise ClientError(f"HTTP request failed: {error}") from error

    def request(self, path, body=None):
        with self.response(path, body) as response:
            return json.loads(response.read())

    def view(self, descriptor, destination=None, expected_sha=None):
        """Retrieve/hash media in bounded chunks, optionally committing a complete local copy."""
        require(isinstance(descriptor, dict) and descriptor.get("type") in ("input", "output", "temp"),
                "invalid /view descriptor")
        filename, folder = descriptor.get("filename"), descriptor.get("subfolder", "")
        require(isinstance(filename, str) and filename and not any(c in filename for c in "/\\:")
                and filename not in (".", "..") and isinstance(folder, str)
                and not folder.startswith(("/", "\\")) and "\\" not in folder and ":" not in folder
                and ".." not in folder.split("/"), "unsafe /view descriptor")
        query = {k: descriptor[k] for k in ("filename", "subfolder", "type", "v") if k in descriptor}
        sha, size = hashlib.sha256(), 0
        with self.response("/view?" + urllib.parse.urlencode(query)) as response:
            with atomic_file(destination) if destination is not None else nullcontext(None) as stream:
                while True:
                    require(time.monotonic() < self.end, "HTTP deadline exceeded")
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    sha.update(chunk)
                    if stream is not None:
                        stream.write(chunk)
                require(size > 0, "empty output artifact")
                require(expected_sha is None or sha.hexdigest() == expected_sha, "artifact identity/hash changed")
        return sha.hexdigest()


@contextmanager
def atomic_file(path):
    path = Path(path)
    handle, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            yield stream
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_write(path, payload):
    with atomic_file(path) as stream:
        stream.write(payload)


@contextmanager
def sequence_lock(directory, host, sequence):
    path = directory / (".h3-" + digest([host, sequence]) + ".lock")
    try:
        handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise ClientError(f"sequence lock exists: {path}; reconcile its owner before manual removal") from error
    try:
        with os.fdopen(handle, "w") as stream:
            stream.write(str(os.getpid()))
            stream.flush()
            os.fsync(stream.fileno())
        yield
    finally:
        path.unlink()


def stable_inputs(prepared):
    value = copy.deepcopy(prepared)
    value["timeline"].pop("render_box", None)
    target = value["workflow"]["timeline_node"]
    line = json.loads(value["workflow"]["api"][target]["inputs"]["timeline"])
    line.pop("render_box", None)
    value["workflow"]["api"][target]["inputs"]["timeline"] = line
    return {"name": value["name"], "timeline_node": target, "timeline": value["timeline"],
            "settings": value["settings"], "api": value["workflow"]["api"], "assets": value["assets"],
            "fingerprint": value["fingerprint"], "revisions": value["revisions"], "boxes": value["boxes"]}


def selected_graph(prepared, ordinal):
    graph = copy.deepcopy(prepared["workflow"]["api"])
    target = prepared["workflow"]["timeline_node"]
    line = copy.deepcopy(prepared["timeline"])
    line["render_box"] = ordinal
    graph[target]["inputs"]["timeline"] = encoded(line).decode("utf-8")
    return graph


def check_prepared(prepared):
    require(prepared.get("ok") is True and prepared.get("version") == 1, "need a successful version 1 preparation")
    require(re.fullmatch(r"[A-Za-z0-9_ .-]{1,64}", prepared["name"])
            and prepared["name"] == prepared["name"].strip()
            and not prepared["name"].startswith(".") and not prepared["name"].endswith("."), "invalid sequence name")
    boxes = prepared["boxes"]
    require(boxes and len({box["id"] for box in boxes}) == len(boxes), "need unique box IDs")
    require([box["index"] for box in boxes] == list(range(1, len(boxes) + 1)), "invalid box order")
    require([box["id"] for box in prepared["timeline"]["boxes"]] == [box["id"] for box in boxes],
            "prepared box identities disagree")
    graph = prepared["workflow"]["api"]
    target = prepared["workflow"]["timeline_node"]
    require(graph[target]["class_type"] == "H3C_Timeline" and graph[target]["inputs"]["name"] == prepared["name"],
            "prepared Timeline identity mismatch")
    line = json.loads(graph[target]["inputs"]["timeline"])
    line.pop("render_box", None)
    expected = copy.deepcopy(prepared["timeline"])
    expected.pop("render_box", None)
    require(line == expected, "prepared Timeline graph differs from normalized input")

    def connected(value, seen=None):
        seen = set() if seen is None else seen
        if not (isinstance(value, list) and len(value) == 2 and isinstance(value[0], str)
                and type(value[1]) is int and value[0] in graph):
            return False
        if value[0] == target:
            return True
        if value[0] in seen:
            return False
        seen.add(value[0])
        return any(connected(v, seen) for v in graph[value[0]].get("inputs", {}).values())

    saves = [node["inputs"] for node in graph.values() if node.get("class_type") == "H3C_SaveSegment"
             and node.get("inputs", {}).get("segment") == [target, 3]]
    require(len(saves) == 1 and connected(saves[0].get("latent")) and connected(saves[0].get("images"))
            and saves[0].get("fps", 24) == 24 and saves[0].get("write_full_video", True) is True,
            "need one connected native H3C_SaveSegment with sampled latent, decoded images, 24 fps and full video")


def graph_matches(evidence, submitted, graph_hash):
    """Compare native numeric coercions without changing durable intent hashes."""
    require(digest(submitted) == graph_hash, "submitted graph intent mismatch")
    if digest(evidence) == graph_hash:
        return True

    def numeric_json(value):
        # JSON encoding keeps booleans distinct from numbers and rejects nonfinites.
        if type(value) is float and math.isfinite(value) and value.is_integer():
            return int(value)
        if isinstance(value, list):
            return [numeric_json(item) for item in value]
        if isinstance(value, dict):
            return {key: numeric_json(item) for key, item in value.items()}
        return value

    return encoded(numeric_json(evidence)) == encoded(numeric_json(submitted))


def terminal(entry, graph_hash, submitted):
    row = entry.get("prompt")
    require(isinstance(row, list) and len(row) >= 3 and graph_matches(row[2], submitted, graph_hash),
            "history submitted graph mismatch")
    status = entry.get("status", {})
    messages = status.get("messages", [])
    failed = [m for m in messages if isinstance(m, (list, tuple)) and m
              and m[0] in ("execution_error", "execution_interrupted")]
    if failed or status.get("status_str") == "error":
        return "failed", {"status": status, "prompt_id": row[1], "graph_hash": graph_hash}
    require(status.get("status_str") == "success" and status.get("completed") is True,
            "ambiguous terminal history status")
    return "succeeded", {"status": status, "prompt_id": row[1], "graph_hash": graph_hash}


def poll(http, attempt, interval, submitted):
    pid = attempt["prompt_id"]
    path = "/history/" + urllib.parse.quote(pid, safe="")
    while True:
        history = http.request(path)
        if pid in history:
            require(history[pid].get("prompt", [None, None])[1] == pid, "history prompt identity mismatch")
            return terminal(history[pid], attempt["graph_hash"], submitted)
        queue = http.request("/queue")
        rows = queue["queue_running"] + queue["queue_pending"]
        matches = [row for row in rows if len(row) >= 3 and row[1] == pid]
        if matches:
            require(len(matches) == 1 and graph_matches(matches[0][2], submitted, attempt["graph_hash"]),
                    "queue submitted graph mismatch")
            require(time.monotonic() < http.end, "poll deadline exceeded")
            time.sleep(min(interval, max(0, http.end - time.monotonic())))
            continue
        history = http.request(path)
        if pid in history:
            require(history[pid].get("prompt", [None, None])[1] == pid, "history prompt identity mismatch")
            return terminal(history[pid], attempt["graph_hash"], submitted)
        raise ClientError(f"ambiguous delivery: acknowledged prompt {pid} absent from history/queue/history; never resubmit automatically")


def run(prepared, base, production, receipt, *, timeout=30, deadline=3600, poll_interval=1, output_directory=None):
    """Return a verified receipt, or stop with the durable attempt available for resume."""
    try:
        return _run(prepared, base, production, receipt, timeout, deadline, poll_interval, output_directory)
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as error:
        raise ClientError(f"invalid prepared input, receipt or server response: {error}") from error


def _run(prepared, base, production, receipt, timeout, deadline, interval, output_directory):
    require(all(type(v) in (int, float) and math.isfinite(v) and v > 0 for v in (timeout, deadline, interval)),
            "timeouts and poll interval must be positive finite numbers")
    require(isinstance(production, str) and production.strip(), "production identity is required")
    check_prepared(prepared)
    base, receipt = base_url(base), Path(receipt)
    receipt.parent.mkdir(parents=True, exist_ok=True)
    identity = dict(production=production, base_url=base, sequence=prepared["name"], inputs=stable_inputs(prepared))
    identity_hash = digest(identity)
    http = HTTP(base, timeout, time.monotonic() + deadline)
    output = Path(output_directory) if output_directory is not None else None

    def status():
        result = http.request("/h3c/timeline/status", dict(name=prepared["name"],
            timeline=encoded(prepared["timeline"]).decode("utf-8"), settings=prepared["settings"]))
        require(result.get("ok") is True and result.get("name") == prepared["name"]
                and [b["id"] for b in result["boxes"]] == [b["id"] for b in prepared["boxes"]],
                "status sequence/box identity mismatch")
        return result

    def artifact(descriptor, frames, previous=None):
        require(isinstance(descriptor, dict) and descriptor.get("type") == "output"
                and descriptor.get("subfolder") == "h3_sequences/" + prepared["name"]
                and descriptor.get("filename", "").lower().endswith(".mp4"), "invalid sequence MP4 descriptor")
        if output:
            output.mkdir(parents=True, exist_ok=True)
        if previous:
            require(previous.get("frames") == frames
                    and previous.get("fps") == 24 and {k: previous["file"].get(k) for k in ("type", "filename", "subfolder")}
                    == {k: descriptor.get(k) for k in ("type", "filename", "subfolder")}, "artifact identity/hash changed")
        sha = http.view(descriptor, output / descriptor["filename"] if output else None,
                        expected_sha=previous["sha256"] if previous else None)
        value = dict(file=descriptor, frames=frames, fps=24, sha256=sha)
        return value

    with sequence_lock(receipt.parent, base, prepared["name"]):
        if receipt.exists():
            try:
                record = json.loads(receipt.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise ClientError(f"corrupt receipt: {error}") from error
            require(record.get("version") == 1 and record.get("identity_hash") == identity_hash
                    and record.get("identity") == identity, "receipt identity changed; preserve it and reconcile")
            require(isinstance(record.get("boxes"), list) and len(record["boxes"]) <= len(prepared["boxes"]), "corrupt receipt boxes")
            for i, attempt in enumerate(record["boxes"]):
                require(attempt["id"] == prepared["boxes"][i]["id"] and attempt["index"] == i + 1
                        and attempt["graph_hash"] == digest(selected_graph(prepared, i + 1))
                        and attempt["state"] in ("submitting", "acknowledged", "succeeded", "failed", "verified"), "corrupt receipt attempt")
                require(i == len(record["boxes"]) - 1 or attempt["state"] == "verified", "corrupt receipt order")
                if attempt["state"] != "submitting":
                    require(isinstance(attempt.get("prompt_id"), str) and attempt["prompt_id"], "corrupt receipt prompt ID")
                if attempt["state"] in ("succeeded", "failed", "verified"):
                    proof = attempt["terminal"]
                    require(proof["prompt_id"] == attempt["prompt_id"] and proof["graph_hash"] == attempt["graph_hash"], "corrupt terminal receipt")
                    result, _ = terminal(dict(prompt=[0, proof["prompt_id"], selected_graph(prepared, i + 1)], status=proof["status"]), attempt["graph_hash"], selected_graph(prepared, i + 1))
                    require(result == ("failed" if attempt["state"] == "failed" else "succeeded"), "corrupt terminal receipt")
                if attempt["state"] == "verified":
                    require(isinstance(attempt.get("artifact"), dict), "corrupt artifact receipt")
            require("final" not in record or len(record["boxes"]) == len(prepared["boxes"])
                    and all(a["state"] == "verified" for a in record["boxes"]), "corrupt final receipt")
        else:
            current = status()
            require(current["segments"] == 0 and current["done"] == 0 and current["trailing"] == 0
                    and not current.get("full_video") and not any(b.get("video") or b["status"] == "done" for b in current["boxes"]),
                    "existing sequence cannot be adopted; use its matching receipt or a unique sequence name")
            record = dict(version=1, identity=identity, identity_hash=identity_hash, boxes=[])
            atomic_write(receipt, encoded(record))

        def save():
            atomic_write(receipt, encoded(record))

        for asset in prepared["assets"]:
            require(http.view(asset["file"]) == asset["sha256"].lower(), "staged asset hash changed")

        for i, box in enumerate(prepared["boxes"]):
            if i == len(record["boxes"]):
                current = status()
                require(current["segments"] == i and current["done"] == i and current["trailing"] == 0
                        and current["next"] == i + 1, "unexpected sequence segments before submission")
                graph = selected_graph(prepared, i + 1)
                attempt = dict(id=box["id"], index=i + 1, graph_hash=digest(graph), state="submitting")
                record["boxes"].append(attempt)
                save()
                try:
                    ack = http.request("/prompt", {"prompt": graph})
                    require(isinstance(ack.get("prompt_id"), str) and ack["prompt_id"], "missing prompt ID")
                except Exception as error:
                    raise ClientError(f"ambiguous submission acknowledgment; receipt retained, never retry POST: {error}") from error
                attempt.update(state="acknowledged", prompt_id=ack["prompt_id"], acknowledgment=ack)
                save()  # Must persist the server-minted ID before the first history request.
            attempt = record["boxes"][i]
            require(attempt["state"] != "submitting", "ambiguous submission in receipt; reconcile manually, never resubmit")
            if attempt["state"] == "acknowledged":
                attempt["state"], attempt["terminal"] = poll(http, attempt, interval, selected_graph(prepared, i + 1))
                save()
            require(attempt["state"] != "failed", "render failed: " + json.dumps(attempt.get("terminal", {})))
            current = status()
            item = current["boxes"][i]
            video = item.get("video", {})
            require(item["status"] == "done" and video.get("fps") == 24 and video.get("frames") == box["frames"],
                    "successful attempt lacks fresh segment with expected frames/fps")
            attempt["artifact"] = artifact(video.get("file"), box["frames"], attempt.get("artifact"))
            attempt["state"] = "verified"
            save()

        current = status()
        count = len(prepared["boxes"])
        # The full video also plays each bridge that is done, rendered and current; no box gets longer.
        bridged = sum(item["video"]["frames"] for item in current.get("bridges", []) if item["status"] == "done")
        total = sum(b["frames"] for b in prepared["boxes"]) + bridged
        require(current["done"] == count and current["segments"] == count and current["trailing"] == 0
                and current["next"] is None and all(b["status"] == "done" for b in current["boxes"])
                and abs(current["seconds"] - total / 24) <= .011, "sequence segments/duration are not complete")
        record["final"] = artifact(current.get("full_video"), total, record.get("final"))
        save()
        return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prepared", type=Path, help="saved successful prepare response JSON")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--production", required=True, help="stable caller production identity")
    parser.add_argument("--receipt", type=Path, required=True, help="same durable path on every resume")
    parser.add_argument("--output-directory", type=Path)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--deadline", type=float, default=3600)
    args = parser.parse_args()
    try:
        result = run(json.loads(args.prepared.read_text(encoding="utf-8")), args.base_url, args.production,
                     args.receipt, timeout=args.timeout, deadline=args.deadline, output_directory=args.output_directory)
        print(json.dumps(result["final"], indent=2))
    except (ClientError, OSError, ValueError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
