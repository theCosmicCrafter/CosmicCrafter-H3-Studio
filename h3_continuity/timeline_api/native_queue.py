"""The single seam for ComfyUI validation, tail submission and exact attribution."""

import copy
import contextvars
import json
import os
import socket
import time
import uuid

from .. import timeline_node
from .contracts import APIError, digest
from .service import authorize_sequence, sequence_identity

_internal_validation = contextvars.ContextVar("h3c_api_validation", default=False)


def admission(body):
    """Raw /prompt cannot acquire an API project, including through computed names."""
    if _internal_validation.get(): return body
    from . import service
    if service._records_provider is None: return body
    graph = body.get("prompt", {})
    native = [node for node in graph.values() if isinstance(node, dict)
              and node.get("class_type") in ("H3C_Timeline", "H3C_Sequence")]
    if not native: return body
    records = service._records_provider()
    for node in native:
        name = node.get("inputs", {}).get("name")
        if isinstance(name, list):
            # Only literal string nodes can prove a destination before execution.
            source = graph.get(str(name[0]), {}) if len(name) == 2 else {}
            values = source.get("inputs", {})
            if source.get("class_type") in ("PrimitiveString", "PrimitiveStringMultiline"):
                name = values.get("value")
            else:
                name = None
        name = sequence_identity(name)
        if ((name is not None and records.owner_for_sequence(name) is not None)
                or (name is None and records.list_projects(limit=1)["projects"])):
            rejected = copy.deepcopy(body)
            rejected["prompt"] = {}
            return rejected
    return body


def _process_identity():
    """Identity of this ComfyUI process. A per-boot UUID alone proves only "not me";
    host, PID and OS start time let a later process prove that the owner has exited."""
    started = None
    try:
        import psutil
        started = psutil.Process(os.getpid()).create_time()
    except Exception:
        pass
    return {"boot_id": str(uuid.uuid4()), "pid": os.getpid(), "host": socket.gethostname(), "started": started}


def _numeric(value):
    if type(value) is float and value.is_integer(): return int(value)
    if isinstance(value, list): return [_numeric(item) for item in value]
    if isinstance(value, dict): return {key: _numeric(item) for key, item in value.items()}
    return value


def _creative(graph):
    result = {}
    for node_id, node in graph.items():
        kind = node["class_type"]
        if kind == "H3C_Timeline":
            inputs = copy.deepcopy(node["inputs"])
            inputs["timeline"] = json.loads(inputs["timeline"])
            result[node_id] = {"class_type": kind, "inputs": _numeric(inputs)}
        elif kind == "H3C_SaveSegment":
            result[node_id] = {"class_type": kind, "inputs": _numeric({key: node["inputs"].get(key)
                              for key in ("segment", "latent", "images", "audio", "description", "fps", "write_full_video")})}
    return result


class NativeQueue:
    def cancel(self, prompt_id):
        queue = self.instance.prompt_queue
        removed = queue.delete_queue_item(lambda row: row[1] == prompt_id)
        if hasattr(queue, "interrupt_if_running"):
            queue.interrupt_if_running(prompt_id)
        return bool(removed)

    def __init__(self, instance):
        self.instance = instance
        # One identity per server instance, which is one per ComfyUI process in production.
        self.process = getattr(instance, "_h3c_api_process", None) or _process_identity()
        instance._h3c_api_process = self.process
        if hasattr(instance, "add_on_prompt_handler") and not getattr(instance, "_h3c_api_admission", False):
            instance.add_on_prompt_handler(admission)
            instance._h3c_api_admission = True

    async def validate(self, graph, prompt_id, metadata):
        import execution
        try:
            if str(uuid.UUID(prompt_id)) != prompt_id: raise ValueError()
            original = _creative(graph)
        except (ValueError, KeyError, TypeError):
            raise APIError("invalid_native_graph", "Native prompt identity or creative graph is invalid.") from None
        data = {"prompt": copy.deepcopy(graph), "prompt_id": prompt_id,
                "extra_data": {"h3c_api": copy.deepcopy(metadata), "extra_pnginfo": {"h3c_api": copy.deepcopy(metadata)}}}
        token = _internal_validation.set(True)
        try:
            data = self.instance.trigger_on_prompt(data)
        finally:
            _internal_validation.reset(token)
        effective = data.get("prompt")
        if not isinstance(effective, dict):
            raise APIError("invalid_native_graph", "Native prompt hooks removed the prepared graph.")
        self.instance.node_replace_manager.apply_replacements(effective)
        import nodes as comfy_nodes
        immutable = any(callable(getattr(comfy_nodes.NODE_CLASS_MAPPINGS.get(n["class_type"]), "STATIC_VALUES", None)) for n in graph.values())
        if (immutable or metadata.get("captured_api") == 2) and digest(effective) != digest(graph):
            raise APIError("native_inputs_changed", "Native hooks changed an immutable configuration graph.", status=409)
        import contextlib
        with contextlib.ExitStack() as captured_scopes:
            if metadata.get("captured_api") == 2:
                for kind in {n["class_type"] for n in graph.values()}:
                    scope = getattr(comfy_nodes.NODE_CLASS_MAPPINGS.get(kind), "CAPTURED_VALIDATION", None)
                    if callable(scope):
                        captured_scopes.enter_context(scope())
            targets = metadata.get("execution_outputs") if metadata.get("captured_api") == 2 else None
            execution_graph = effective
            if targets:
                execution_graph = {}
                def visit(node_id):
                    if node_id in execution_graph: return
                    execution_graph[node_id] = effective[node_id]
                    for value in effective[node_id].get("inputs", {}).values():
                        if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and type(value[1]) is int: visit(value[0])
                for output in targets: visit(output)
            valid = await execution.validate_prompt(prompt_id, execution_graph, targets)
        if not valid[0]:
            error = APIError("native_validation_failed", "Native render graph validation failed.", status=422)
            error.diagnostics = {"error": valid[1], "node_errors": valid[3]}
            raise error
        extra = copy.deepcopy(data.get("extra_data", {}))
        try:
            intact = _creative(effective) == original
        except (ValueError, KeyError, TypeError):
            intact = False
        if (not intact or data.get("prompt_id") != prompt_id or extra.get("h3c_api") != metadata
                or extra.get("extra_pnginfo", {}).get("h3c_api") != metadata):
            raise APIError("native_inputs_changed", "Native hooks changed authored inputs or API ownership.", status=409)
        sensitive = {key: extra.pop(key) for key in execution.SENSITIVE_EXTRA_DATA_KEYS if key in extra}
        return {"graph": execution_graph, "graph_sha256": digest(execution_graph), "prompt_id": prompt_id,
                "metadata": copy.deepcopy(metadata), "extra_data": extra, "sensitive": sensitive,
                "outputs_to_execute": valid[2], "node_errors": valid[3]}

    async def submit(self, validated):
        if digest(validated["graph"]) != validated["graph_sha256"]:
            raise APIError("native_inputs_changed", "Validated native graph changed before submission.", status=409)
        for node in validated["graph"].values():
            if node["class_type"] == "H3C_Timeline":
                authorize_sequence(node["inputs"]["name"], validated["metadata"], "conditioning")
        number = self.instance.number
        self.instance.number += 1
        extra = copy.deepcopy(validated["extra_data"])
        extra["create_time"] = int(time.time() * 1000)
        self.instance.prompt_queue.put((number, validated["prompt_id"], copy.deepcopy(validated["graph"]), extra,
                                        copy.deepcopy(validated["outputs_to_execute"]), copy.deepcopy(validated["sensitive"])))
        return {"prompt_id": validated["prompt_id"], "number": number, "node_errors": validated["node_errors"]}

    def evidence(self, prompt_id, attempt):
        queue = self.instance.prompt_queue
        with queue.mutex:
            running, pending = queue.get_current_queue()
            history = queue.get_history(prompt_id)
        rows = [("running", row, None) for row in running if row[1] == prompt_id]
        rows += [("queued", row, None) for row in pending if row[1] == prompt_id]
        if prompt_id in history:
            entry = history[prompt_id]
            rows.append(("terminal", entry.get("prompt"), entry))
        if not rows:
            return {"state": "unknown", "prompt_id": prompt_id}
        if len(rows) != 1:
            return {"state": "conflict", "prompt_id": prompt_id, "reason": "Multiple native attempts share this UUID."}
        state, row, entry = rows[0]
        if (not isinstance(row, (list, tuple)) or len(row) < 5 or row[1] != prompt_id
                or digest(row[2]) != attempt["graph_sha256"] or row[3].get("h3c_api") != attempt["metadata"]
                or row[3].get("extra_pnginfo", {}).get("h3c_api") != attempt["metadata"]):
            return {"state": "conflict", "prompt_id": prompt_id, "reason": "Native identity or final graph differs."}
        result = {"state": state, "prompt_id": prompt_id, "graph_sha256": digest(row[2]),
                  "metadata": row[3]["h3c_api"]}
        if entry is not None:
            status = entry.get("status") or {}
            failed = any(isinstance(message, (list, tuple)) and message
                         and message[0] in ("execution_error", "execution_interrupted") for message in status.get("messages", []))
            if failed or status.get("status_str") == "error":
                result["state"] = "failed"
            elif status.get("status_str") == "success" and status.get("completed") is True:
                result["state"] = "succeeded"
            else:
                result["state"] = "unknown"
            # Native history retains tuple queue rows; durable evidence is JSON.
            result["terminal"] = json.loads(json.dumps(entry))
        return result

    def active(self, prompt_id):
        """True while this process's native queue is running or holding the prompt."""
        queue = self.instance.prompt_queue
        with queue.mutex:
            running, pending = queue.get_current_queue()
        return any(isinstance(row, (list, tuple)) and len(row) > 1 and row[1] == prompt_id for row in [*running, *pending])

    def owner(self, attempt):
        """Liveness of the process that submitted an attempt: self, alive, gone or unknown.

        Only "self" and "gone" are proof. Another host, an attempt recorded before
        owner identities existed or an unreadable process table stays "unknown",
        which keeps the conservative admission barrier."""
        recorded = attempt.get("owner_process")
        if not isinstance(recorded, dict) or not recorded.get("boot_id"):
            return "unknown"
        if recorded["boot_id"] == self.process["boot_id"]:
            return "self"
        if (recorded.get("host") != self.process["host"] or type(recorded.get("pid")) is not int
                or not isinstance(recorded.get("started"), (int, float))):
            return "unknown"
        try:
            import psutil
        except ImportError:
            return "unknown"
        try:
            started = psutil.Process(recorded["pid"]).create_time()
        except psutil.NoSuchProcess:
            return "gone"
        except Exception:
            return "unknown"
        # A reused PID belongs to a process with a different OS start time.
        return "alive" if abs(started - recorded["started"]) < 1 else "gone"

    def status(self, project, *, materialize=False, managed_owner=None):
        prepared = project["prepared"]
        return timeline_node.request_status({"name": project["sequence"], "timeline": json.dumps(prepared["timeline"]),
                                             "settings": prepared["settings"]}, materialize=materialize, managed_owner=managed_owner)

# static-configuration-interop-v1

# captured-api-delivery-v2

# captured-api-validation-v1

# captured-api-active-outputs-v1

# captured-api-execution-closure-v1
