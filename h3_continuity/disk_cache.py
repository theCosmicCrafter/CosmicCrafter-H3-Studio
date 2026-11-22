"""H3 Disk Cache: keeps a sampler's result on disk, keyed by what it was made from.

The node sits after a sampler. Its `result` input is lazy: when a result made from the same inputs is on disk, the node
loads it and never asks for the sampler's output, so the sampler and everything only it needs do not run.

The key is built from two parts:

- **The keys:** the values that change from run to run (for H3 Timeline: positive, latent and seed). They are hashed
  by content, tensor bytes included, so the same box rendered into another sequence finds its result again.
- **The rest of the graph above `result`:** each node's class, its widget values and its fingerprint (`is_changed`).
  Node ids are not part of it, so rearranging a workflow keeps its results. A link from a node that already ran for
  one of the keys (a settings node that also feeds the Timeline, say) is hashed by the value it carries, so its
  other outputs (the second-pass size) do not change the first pass's key.

ComfyUI's own cache can't do this: it lives in RAM, keeps results only while their exact node signatures repeat, and
the Timeline's signature changes with every saved box. A link from a key source that is not itself a key makes the
result uncacheable rather than risk returning a result made from different inputs.
"""

import datetime
import hashlib
import json
import math
import os
import re
import struct
from dataclasses import fields, is_dataclass

import torch
from safetensors import safe_open
from safetensors.torch import save_file

import folder_paths
from comfy_api.latest import io, ui
from comfy_execution.graph_utils import ExecutionBlocker, is_link

CATEGORY = "H3 Continuity"
VERSION = "h3c-disk-cache-v1"
FOLDER = "h3c_cache"
MODES = ("use", "refresh", "off")
NAMESPACE = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
KEY_GROUP = "keys"
# Parts of each key recorded beside a result, to say which part changed when a later run finds no result.
PART_DEPTH = 6
MAX_PARTS = 256


class Uncacheable(ValueError):
    """The result can't be cached: something it depends on can't be identified."""


# --- content hashing -------------------------------------------------------------------------------------------------

def _tensor_digest(tensor):
    data = tensor.detach()
    if data.device.type != "cpu":
        data = data.cpu()
    data = data.contiguous().reshape(-1)
    h = hashlib.sha256(f"T{data.dtype}{tuple(tensor.shape)}".encode())
    if data.numel():
        h.update(memoryview(data.view(torch.uint8).numpy()))
    return h.digest()


def content_digest(value, parts=None, path="", depth=0):
    """A Merkle SHA-256 of `value`: tensors by dtype, shape and bytes, containers by their items. Records the hex
    digest of each part down to PART_DEPTH in `parts` (path -> digest). Raises Uncacheable for any other object."""

    def child(item, name):
        return content_digest(item, parts, f"{path}{name}", depth + 1)

    if value is None:
        result = hashlib.sha256(b"none").digest()
    elif isinstance(value, bool):
        result = hashlib.sha256(b"bool" + bytes([value])).digest()
    elif isinstance(value, int):
        result = hashlib.sha256(b"int" + str(value).encode()).digest()
    elif isinstance(value, float):
        result = hashlib.sha256(b"float" + (b"nan" if math.isnan(value) else struct.pack("<d", value))).digest()
    elif isinstance(value, str):
        result = hashlib.sha256(b"str" + value.encode("utf-8", "surrogatepass")).digest()
    elif isinstance(value, bytes):
        result = hashlib.sha256(b"bytes" + value).digest()
    elif isinstance(value, torch.Tensor):
        result = _tensor_digest(value)
    elif getattr(value, "is_nested", False) and isinstance(getattr(value, "tensors", None), (list, tuple)):
        h = hashlib.sha256(b"nested%d" % len(value.tensors))
        for index, item in enumerate(value.tensors):
            h.update(child(item, f".tensors[{index}]"))
        result = h.digest()
    elif isinstance(value, (list, tuple)):
        h = hashlib.sha256(b"%s%d" % (b"list" if isinstance(value, list) else b"tuple", len(value)))
        for index, item in enumerate(value):
            h.update(child(item, f"[{index}]"))
        result = h.digest()
    elif isinstance(value, dict):
        h = hashlib.sha256(b"dict%d" % len(value))
        for key in sorted(value, key=lambda item: (type(item).__name__, repr(item))):
            if not isinstance(key, (str, int, float, bool)) and key is not None:
                raise Uncacheable(f"{path or 'the value'} has a {type(key).__qualname__} key")
            h.update(content_digest(key))
            h.update(child(value[key], f"[{key!r}]" if not isinstance(key, str) else f".{key}"))
        result = h.digest()
    elif is_dataclass(value) and not isinstance(value, type):
        h = hashlib.sha256(f"dataclass {type(value).__module__}.{type(value).__qualname__}".encode())
        for field in fields(value):
            h.update(field.name.encode())
            h.update(child(getattr(value, field.name), f".{field.name}"))
        result = h.digest()
    else:
        raise Uncacheable(f"{path or 'the value'} is a {type(value).__qualname__}, which the cache can't compare")
    if parts is not None and path and depth <= PART_DEPTH and len(parts) < MAX_PARTS:
        parts[path] = result.hex()
    return result


# --- graph hashing ---------------------------------------------------------------------------------------------------

def node_class(class_type):
    import nodes
    return nodes.NODE_CLASS_MAPPINGS.get(class_type)


def _has_fingerprint(cls):
    if cls is None:
        return False
    try:
        from comfy_api.internal import _ComfyNodeInternal, first_real_override
        if issubclass(cls, _ComfyNodeInternal) and first_real_override(cls, "fingerprint_inputs") is not None:
            return True
    except (ImportError, TypeError, ValueError):
        pass
    return hasattr(cls, "IS_CHANGED")


def _is_nan(value):
    if isinstance(value, float):
        return math.isnan(value)
    if isinstance(value, (list, tuple)):
        return any(_is_nan(item) for item in value)
    return False


def _literal(value):
    return json.dumps(value, sort_keys=True, default=repr)


def _links(node):
    for name, value in node.get("inputs", {}).items():
        if is_link(value):
            yield name, str(value[0]), int(value[1])


def _ancestors(dynprompt, start):
    seen, stack = set(), list(start)
    while stack:
        node_id = stack.pop()
        if node_id in seen or not dynprompt.has_node(node_id):
            continue
        seen.add(node_id)
        stack.extend(source for _, source, _ in _links(dynprompt.get_node(node_id)))
    return seen


class GraphHasher:
    """Hashes the graph above a link. `keys` maps (source id, slot) to the key name it stands for; `outputs(id)`
    returns a node's outputs from this run, or None."""

    def __init__(self, dynprompt, keys, outputs):
        self.dynprompt, self.keys, self.outputs = dynprompt, keys, outputs
        self.key_sources = {source for source, _ in keys}
        self.ran = _ancestors(dynprompt, self.key_sources)
        self.memo = {}

    def label(self, node_id):
        node = self.dynprompt.get_node(node_id)
        return f"{node.get('class_type', '?')} (node {node_id})"

    def link(self, consumer, name, source, slot):
        if (source, slot) in self.keys:
            return f"key:{self.keys[(source, slot)]}"
        if source in self.key_sources:
            raise Uncacheable(f"{self.label(consumer)} input '{name}' reads output {slot} of {self.label(source)}, which "
                              "is not one of the cache keys; connect that output to a key as well")
        if source in self.ran:
            # Already computed for a key, so its value is known: hash what the link carries, not the node's inputs.
            outputs = self.outputs(source)
            if outputs is not None and slot < len(outputs):
                try:
                    return "value:" + content_digest(outputs[slot]).hex()
                except Uncacheable:
                    pass
        return f"node:{self.node(source)}:{slot}"

    def node(self, node_id):
        if node_id in self.memo:
            return self.memo[node_id]
        if not self.dynprompt.has_node(node_id):
            raise Uncacheable(f"node {node_id} is missing from the queued prompt")
        node = self.dynprompt.get_node(node_id)
        class_type = node.get("class_type", "")
        h = hashlib.sha256(b"class" + class_type.encode())
        if _has_fingerprint(node_class(class_type)):
            changed = node.get("is_changed")
            if changed is None or _is_nan(changed):
                raise Uncacheable(f"{self.label(node_id)} can change from run to run, so its result can't be "
                                  "identified; connect its output to a cache key instead")
            h.update(b"is_changed" + _literal(changed).encode())
        for name in sorted(node.get("inputs", {})):
            value = node["inputs"][name]
            part = (self.link(node_id, name, str(value[0]), int(value[1])) if is_link(value)
                    else "literal:" + _literal(value))
            h.update(f"\0{name}={part}".encode())
        self.memo[node_id] = h.hexdigest()
        return self.memo[node_id]


def _run_outputs(execution_list):
    def outputs(node_id):
        if execution_list is None:
            return None
        entry = None
        try:
            entry = execution_list.output_cache.get_local(node_id)
        except Exception:
            entry = None
        if entry is None:
            for sources in getattr(execution_list, "execution_cache", {}).values():
                entry = sources.get(node_id)
                if entry is not None:
                    break
        return getattr(entry, "outputs", None)
    return outputs


# --- storage ---------------------------------------------------------------------------------------------------------

def cache_root():
    return os.path.join(folder_paths.get_output_directory(), FOLDER)


def entry_paths(namespace, key):
    folder = os.path.join(cache_root(), namespace, key[:2])
    return os.path.join(folder, key + ".safetensors"), os.path.join(folder, key + ".json")


def _pack(value, tensors):
    if isinstance(value, torch.Tensor):
        name = f"t{len(tensors)}"
        tensors[name] = value.detach().cpu().contiguous().clone()
        return {"tensor": name}
    if getattr(value, "is_nested", False) and isinstance(getattr(value, "tensors", None), (list, tuple)):
        return {"nested": [_pack(item, tensors) for item in value.tensors]}
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise Uncacheable("the result has a dictionary with non-text keys")
        return {"dict": {key: _pack(item, tensors) for key, item in value.items()}}
    if isinstance(value, (list, tuple)):
        return {"list" if isinstance(value, list) else "tuple": [_pack(item, tensors) for item in value]}
    if value is None or isinstance(value, (bool, int, float, str)):
        return {"value": value}
    raise Uncacheable(f"the result holds a {type(value).__qualname__}, which the cache can't save")


def _unpack(spec, reader):
    if "tensor" in spec:
        return reader.get_tensor(spec["tensor"])
    if "nested" in spec:
        from comfy.nested_tensor import NestedTensor
        return NestedTensor([_unpack(item, reader) for item in spec["nested"]])
    if "dict" in spec:
        return {key: _unpack(item, reader) for key, item in spec["dict"].items()}
    if "list" in spec:
        return [_unpack(item, reader) for item in spec["list"]]
    if "tuple" in spec:
        return tuple(_unpack(item, reader) for item in spec["tuple"])
    return spec["value"]


def save(namespace, key, value, record):
    path, sidecar = entry_paths(namespace, key)
    tensors = {}
    spec = _pack(value, tensors)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    save_file(tensors, path + ".tmp", metadata={"h3c_disk_cache": json.dumps(spec)})
    os.replace(path + ".tmp", path)
    with open(sidecar + ".tmp", "w", encoding="utf-8") as f:
        json.dump(record, f, indent=1)
    os.replace(sidecar + ".tmp", sidecar)


def load(namespace, key):
    path, _ = entry_paths(namespace, key)
    with safe_open(path, framework="pt") as reader:
        spec = json.loads(reader.metadata()["h3c_disk_cache"])
        return _unpack(spec, reader)


def has(namespace, key):
    return os.path.isfile(entry_paths(namespace, key)[0])


def records(namespace):
    root = os.path.join(cache_root(), namespace)
    for folder, _, names in os.walk(root):
        for name in names:
            if name.endswith(".json"):
                try:
                    with open(os.path.join(folder, name), encoding="utf-8") as f:
                        yield json.load(f)
                except (OSError, ValueError):
                    continue


def closest_difference(namespace, record):
    """Why `record` found no saved result: the parts that differ from the saved result closest to it, or ""."""
    best, best_score = None, -1
    for other in records(namespace):
        if other.get("version") != VERSION:
            continue
        same = sum(other.get("keys", {}).get(name, {}).get("digest") == item["digest"]
                   for name, item in record["keys"].items())
        score = same * 2 + (other.get("graph") == record["graph"])
        if score > best_score:
            best, best_score = other, score
    if best is None or best_score <= 0:
        return ""
    changed = []
    if best.get("graph") != record["graph"]:
        changed.append("the settings above the sampler")
    for name, item in record["keys"].items():
        saved = best.get("keys", {}).get(name, {})
        if saved.get("digest") == item["digest"]:
            continue
        paths = [path for path, digest in item.get("parts", {}).items() if saved.get("parts", {}).get(path) != digest]
        # Report the deepest differing parts only; their containers differ by consequence.
        leaves = [path for path in paths
                  if not any(other.startswith((path + ".", path + "[")) for other in paths)]
        where = f" at {', '.join(leaves[:3])}" + (" and more" if len(leaves) > 3 else "") if leaves else ""
        changed.append(f"{name} ({item.get('source', '?')}){where}")
    return "The closest saved result differs in " + "; ".join(changed) + "." if changed else ""


# --- node ------------------------------------------------------------------------------------------------------------

def _key_links(dynprompt, unique_id):
    node = dynprompt.get_node(unique_id)
    links = {}
    for name, value in node.get("inputs", {}).items():
        if name.startswith(KEY_GROUP + ".") and is_link(value):
            links[(str(value[0]), int(value[1]))] = name.split(".", 1)[1]
    result = node.get("inputs", {}).get("result")
    return links, (str(result[0]), int(result[1])) if is_link(result) else None


def _source_label(dynprompt, source, slot):
    node = dynprompt.get_node(source)
    class_type = node.get("class_type", "?")
    name = None
    cls = node_class(class_type)
    try:
        names = getattr(cls, "RETURN_NAMES", None) or getattr(cls, "RETURN_TYPES", None)
        name = names[slot] if names and slot < len(names) else None
    except Exception:
        name = None
    return f"{class_type} {name}" if name else f"{class_type} output {slot}"


def describe_key(dynprompt, unique_id, namespace, values, execution_list=None):
    """(key, record) of this run. `values` maps key names to their values."""
    links, result = _key_links(dynprompt, unique_id)
    if result is None:
        raise Uncacheable("connect the sampler's output to result")
    if not links:
        raise Uncacheable("connect at least one key")
    hasher = GraphHasher(dynprompt, links, _run_outputs(execution_list))
    graph = hasher.link(unique_id, "result", *result)
    keys = {}
    for (source, slot), name in sorted(links.items(), key=lambda item: item[1]):
        parts = {}
        digest = content_digest(values.get(name), parts)
        keys[name] = {"digest": digest.hex(), "source": _source_label(dynprompt, source, slot), "parts": parts}
    material = {"version": VERSION, "namespace": namespace, "graph": graph,
                "keys": {name: item["digest"] for name, item in keys.items()}}
    key = hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
    return key, {"version": VERSION, "namespace": namespace, "key": key, "graph": graph, "keys": keys}


def _unwrap(group, lazy):
    """Key values by name. check_lazy_status receives each dynamic input as (value, path)."""
    if not isinstance(group, dict):
        return {}
    return {name: (value[0] if lazy and isinstance(value, tuple) and len(value) == 2 else value)
            for name, value in group.items()}


class H3C_DiskCache(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="H3C_DiskCache",
            display_name="H3 Disk Cache",
            category=CATEGORY,
            description="Keeps the sampler's result on disk. When a result made from the same keys and the same "
                        "settings is saved, loads it and the sampler does not run. Put it after the first-pass "
                        "sampler, connect everything that read the sampler to it, and connect the H3 Timeline's "
                        "positive, latent and seed as keys.",
            inputs=[
                io.Latent.Input("result", lazy=True,
                                tooltip="The sampler's output. Asked for only when no saved result matches."),
                io.Autogrow.Input(KEY_GROUP, template=io.Autogrow.TemplatePrefix(
                    io.AnyType.Input("key", tooltip="A value that changes from run to run, compared by content."),
                    prefix="key", min=1, max=16),
                    tooltip="Every output of a node that changes from run to run (H3 Timeline: positive, latent, "
                            "seed) that the sampler reads. The rest of the graph above the sampler is compared by "
                            "its settings."),
                io.Combo.Input("mode", options=list(MODES), default="use",
                               tooltip="use: load a matching saved result, else sample and save. refresh: sample and "
                                       "replace the saved result. off: sample, never load or save."),
                io.String.Input("namespace", default="first_pass",
                                tooltip=f"Folder under output/{FOLDER}/ for these results: letters, digits, _ and -."),
            ],
            outputs=[io.Latent.Output(display_name="result"), io.String.Output(display_name="info")],
            hidden=[io.Hidden.dynprompt, io.Hidden.unique_id, io.Hidden.execution_list],
        )

    @classmethod
    def _key(cls, namespace, values):
        if not NAMESPACE.match(namespace or ""):
            raise ValueError("H3 Disk Cache: namespace must be 1-64 letters, digits, _ or -")
        return describe_key(cls.hidden.dynprompt, cls.hidden.unique_id, namespace, values, cls.hidden.execution_list)

    @classmethod
    def check_lazy_status(cls, result=None, keys=None, mode="use", namespace="first_pass", **kwargs):
        if result is not None:
            return []
        values = _unwrap(keys, lazy=True)
        if any(isinstance(value, ExecutionBlocker) for value in values.values()):
            return []
        if mode != "use":
            return ["result"]
        try:
            key, _ = cls._key(namespace, values)
        except Uncacheable:
            return ["result"]
        return [] if has(namespace, key) else ["result"]

    @classmethod
    def execute(cls, result=None, keys=None, mode="use", namespace="first_pass") -> io.NodeOutput:
        values = _unwrap(keys, lazy=False)
        if mode == "off":
            return cls._done(result, "Disk cache off: passed the sampler's result through.")
        try:
            key, record = cls._key(namespace, values)
        except Uncacheable as reason:
            return cls._done(result, f"Not cached: {reason}.")
        short = key[:12]
        if result is None:
            if not has(namespace, key):
                raise ValueError(f"H3 Disk Cache: saved result {short} disappeared during this run; queue it again")
            return cls._done(load(namespace, key), f"Loaded saved result {short} from {namespace}; the sampler "
                                                   "did not run.")
        why = closest_difference(namespace, record) if mode == "use" else ""
        record["created"] = datetime.datetime.now().isoformat(timespec="seconds")
        try:
            save(namespace, key, result, record)
        except Uncacheable as reason:
            return cls._done(result, f"Sampled; not cached: {reason}.")
        info = (f"Sampled and saved result {short} to {namespace}" + (" (replaced the saved one)." if mode == "refresh"
                                                                       else ".") + (" " + why if why else ""))
        return cls._done(result, info)

    @classmethod
    def _done(cls, result, info):
        return io.NodeOutput(result, info, ui=ui.PreviewText(info))
