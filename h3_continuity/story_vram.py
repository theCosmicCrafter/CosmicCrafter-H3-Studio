"""H3 Story sharing the GPU with a model server on this PC: Write takes a turn in ComfyUI's queue, which moves
ComfyUI's models out of VRAM and keeps later prompts waiting, and the server unloads the model before the turn
ends."""

import asyncio
import ipaddress
import json
import socket
import threading
import time
import uuid
from urllib.parse import urlsplit

import aiohttp

from . import llm, story_keys

TURN_POLL_SECONDS = 0.1
UNLOAD_SECONDS = 10
TURN = "H3C_StoryTurn"
TURNS = {}
DROPPED = "ComfyUI's queue dropped Write's turn."
ENDED = "ComfyUI's queue ended Write's turn, so Write stopped."
REFUSED = "{host} refused the key, so the model may still be loaded."
SILENT = "{host} didn't answer, so the model may still be loaded."
UNKNOWN = "H3 Story can't unload models on {host}; free its VRAM before rendering."


def _own_addresses():
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None)
    except OSError:
        return set()
    found = set()
    for info in infos:
        try:
            found.add(ipaddress.ip_address(info[4][0].split("%")[0]))
        except ValueError:
            continue
    return found


def on_this_pc(base_url):
    """Whether the host of `base_url` is this PC: localhost, a loopback address, this PC's name or fully qualified
    name, or one of its own addresses. Only this PC's own name is ever looked up."""
    try:
        host = (urlsplit(str(base_url).strip()).hostname or "").lower()
    except ValueError:
        return False
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host == socket.gethostname().lower() or host == socket.getfqdn().lower()
    return address.is_loopback or address in _own_addresses()


def _ended_turn(prompt):
    """Whether API prompt `prompt` is the prompt of a turn that has ended."""
    node = prompt.get("h3c_turn") if isinstance(prompt, dict) else None
    return (isinstance(node, dict) and node.get("class_type") == TURN
            and (node.get("inputs") or {}).get("write") not in TURNS)


def _refusal(error, node_errors):
    """ComfyUI's reason for refusing a prompt: the first error of a node, else the prompt's own."""
    reasons = [reason for entry in node_errors.values() for reason in entry.get("errors") or []]
    reason = reasons[0] if reasons else error or {}
    message, details = str(reason.get("message") or "").strip(), str(reason.get("details") or "").strip()
    return f"{message}: {details}" if message and details else message or details


class Comfy:
    """ComfyUI's prompt queue, its history, the loaded models and the open pages."""

    @staticmethod
    def _queue():
        from server import PromptServer
        return PromptServer.instance.prompt_queue

    def connected(self, client_id):
        """Whether the page with client id `client_id` has its websocket to ComfyUI open."""
        from server import PromptServer
        return client_id in PromptServer.instance.sockets

    async def queue(self, prompt, outputs=None, front=False):
        """Checks the API prompt `prompt` as POST /prompt does, then queues it without a client, at the back or the
        `front`, so ComfyUI keeps its errors from the page. `outputs` lists the output nodes to run, as a partial run
        from the page does; None runs them all. Returns its prompt id; raises ValueError with ComfyUI's reason when
        the check fails."""
        import execution
        from server import PromptServer
        server = PromptServer.instance
        prompt_id = str(uuid.uuid4())
        valid = await execution.validate_prompt(prompt_id, prompt, outputs)
        if not valid[0]:
            raise ValueError(_refusal(valid[1], valid[3]))
        number = -server.number if front else server.number
        server.number += 1
        server.prompt_queue.put((number, prompt_id, prompt, {"create_time": int(time.time() * 1000)}, valid[2], {}))
        return prompt_id

    def busy(self):
        """Whether ComfyUI has a prompt running or waiting. A turn that has ended doesn't count: its prompt stays
        until it notices, up to TURN_POLL_SECONDS later."""
        running, waiting = self._queue().get_current_queue_volatile()
        return any(not _ended_turn(item[2]) for item in [*running, *waiting])

    def ahead(self, prompt_id):
        """How many prompts run before prompt `prompt_id`: 0 while it runs, None once it has left the queue."""
        running, waiting = self._queue().get_current_queue_volatile()
        if any(item[1] == prompt_id for item in running):
            return 0
        number = next((item[0] for item in waiting if item[1] == prompt_id), None)
        if number is None:
            return None
        return len(running) + sum(1 for item in waiting if item[0] < number)

    def where(self, prompt_id):
        """Where prompt `prompt_id` is: "waiting", "running", "done" (in the history) or "gone"."""
        queue = self._queue()
        running, waiting = queue.get_current_queue_volatile()
        if any(item[1] == prompt_id for item in running):
            return "running"
        if any(item[1] == prompt_id for item in waiting):
            return "waiting"
        return "done" if queue.get_history(prompt_id=prompt_id) else "gone"

    def history(self, prompt_id):
        """The history entry of prompt `prompt_id`, with its "outputs" and "status"."""
        return self._queue().get_history(prompt_id=prompt_id).get(prompt_id) or {}

    def forget(self, prompt_id):
        self._queue().delete_history_item(prompt_id)

    def cancel(self, prompt_id):
        """Takes prompt `prompt_id` off the queue, or interrupts it while it runs."""
        queue = self._queue()
        if not queue.delete_queue_item(lambda item: item[1] == prompt_id):
            queue.interrupt_if_running(prompt_id)


class Turn:
    """A Write's turn in ComfyUI's queue: its prompt, and whether it has made room on the GPU and when it's over.
    The prompt runs on ComfyUI's worker thread."""

    def __init__(self):
        self.prompt_id = None
        self.ready, self.over = threading.Event(), threading.Event()


async def hold(write_id):
    """Runs as ComfyUI's current prompt for Write `write_id`: moves ComfyUI's models out of VRAM, then keeps later
    prompts waiting until the Write's turn is over. Cancelling the prompt interrupts it."""
    from comfy import model_management
    turn = TURNS.get(write_id)
    if turn is None:
        return
    model_management.unload_all_models()
    model_management.soft_empty_cache()
    turn.ready.set()
    while not turn.over.is_set():
        model_management.throw_exception_if_processing_interrupted()
        await asyncio.sleep(TURN_POLL_SECONDS)


async def take_turn(comfy, write_id, report):
    """Queues a turn for Write `write_id` behind ComfyUI's queued prompts and waits until it runs with ComfyUI's
    models out of VRAM, telling report(text) what it waits for. Returns the Turn; raises ValueError when the queue
    drops it."""
    turn = TURNS[write_id] = Turn()
    try:
        turn.prompt_id = await comfy.queue({"h3c_turn": {"class_type": TURN, "inputs": {"write": write_id}}})
        while not turn.ready.is_set():
            ahead = comfy.ahead(turn.prompt_id)
            if ahead is None:
                raise ValueError(DROPPED)
            report(f"Waiting for ComfyUI's queue ({ahead} ahead)..." if ahead else "Moving ComfyUI's models out of VRAM...")
            await asyncio.sleep(TURN_POLL_SECONDS)
    except BaseException:
        end_turn(comfy, write_id)
        raise
    return turn


def end_turn(comfy, write_id):
    """Ends Write `write_id`'s turn, letting later prompts run; a turn still waiting leaves the queue."""
    turn = TURNS.pop(write_id, None)
    if turn is None:
        return
    turn.over.set()
    if turn.prompt_id and not turn.ready.is_set():
        comfy.cancel(turn.prompt_id)


def _reason(text, status):
    return llm.provider_text(text).strip().rstrip(".") or f"it answered {status}"


def _instances(models, model):
    """The loaded LM Studio instances of `model`: every instance of the model whose key it is, or the one instance
    whose id it is."""
    found = []
    for entry in models:
        if not isinstance(entry, dict):
            continue
        loaded = entry.get("loaded_instances")
        if not isinstance(loaded, list):
            loaded = []
        ids = [item["id"] for item in loaded if isinstance(item, dict) and isinstance(item.get("id"), str)]
        if entry.get("key") == model:
            found += ids
        elif model in ids:
            found.append(model)
    return list(dict.fromkeys(found))


async def _call(session, method, url, body=None):
    async with session.request(method, url, json=body) as response:
        text = await response.text(errors="replace")
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    return response.status, data, text


async def _lm_studio(session, root, models, model):
    instances = _instances(models, model)
    if not instances:
        return "LM Studio had already unloaded the model."
    for instance in instances:
        status, _, text = await _call(session, "POST", root + "/api/v1/models/unload", {"instance_id": instance})
        if status != 200:
            return f"LM Studio kept the model loaded: {_reason(text, status)}."
    return "LM Studio unloaded the model."


async def _ollama(session, root, model):
    status, _, text = await _call(session, "POST", root + "/api/chat",
                                  {"model": model, "messages": [], "keep_alive": 0})
    if status == 200:
        return "Ollama unloaded the model."
    return f"Ollama kept the model loaded: {_reason(text, status)}."


def _unsloth_model(data):
    """The name Unsloth Studio's status gives its loaded chat model for loading and unloading it: the loadable
    identifier, else the display name. None when nothing is loaded."""
    if not isinstance(data, dict) or not data.get("active_model"):
        return None
    return data.get("model_identifier") or data["active_model"]


async def _unsloth(session, root, host):
    """Unloads Unsloth Studio's one loaded chat model, the one that answered Write. The unload has to name it the
    way the status does: the node's model may be an alias such as "default", and an alias leaves it loaded."""
    status, data, text = await _call(session, "GET", root + "/v1/status")
    if status in (401, 403):
        return REFUSED.format(host=host)
    if status != 200:
        return f"Unsloth Studio kept the model loaded: {_reason(text, status)}."
    loaded = _unsloth_model(data)
    if loaded is None:
        return "Unsloth Studio had already unloaded the model."
    status, _, text = await _call(session, "POST", root + "/v1/unload", {"model_path": loaded})
    if status != 200:
        return f"Unsloth Studio kept the model loaded: {_reason(text, status)}."
    status, data, _ = await _call(session, "GET", root + "/v1/status")
    if status == 200 and _unsloth_model(data) == loaded:
        return "Unsloth Studio answered the unload but still has the model loaded."
    status, data, _ = await _call(session, "GET", root + "/api/settings/openai-auto-switch")
    if status == 200 and isinstance(data, dict) and data.get("enabled") is False:
        return ("Unsloth Studio unloaded the model. Its Model auto-switch is off, so load the model again in Unsloth "
                "Studio before the next Write, or turn auto-switch on in Settings > API.")
    return "Unsloth Studio unloaded the model."


async def _unload(session, root, host, model):
    status, data, _ = await _call(session, "GET", root + "/api/health")
    if status in (401, 403):
        return REFUSED.format(host=host)
    if status == 200 and isinstance(data, dict) and data.get("service") == "Unsloth UI Backend":
        return await _unsloth(session, root, host)
    if status == 200 and isinstance(data, dict) and data.get("service") == "strata":
        status, data, text = await _call(session, "GET", root + "/v1/status")
        if status != 200 or not isinstance(data, dict):
            return f"Strata kept the model loaded: {_reason(text, status)}."
        if data.get("loaded") is False:
            return "Strata had already unloaded the model."
        status, _, text = await _call(session, "POST", root + "/v1/unload", {"model": data.get("model")})
        if status != 200:
            return f"Strata kept the model loaded: {_reason(text, status)}."
        status, data, _ = await _call(session, "GET", root + "/v1/status")
        if status == 200 and isinstance(data, dict) and data.get("loaded") is False:
            return "Strata unloaded the model; the next request loads it again."
        return "Strata answered the unload but did not confirm the model was unloaded."
    status, data, _ = await _call(session, "GET", root + "/api/v1/models")
    if status in (401, 403):
        return REFUSED.format(host=host)
    if status == 200 and isinstance(data, dict) and isinstance(data.get("models"), list):
        return await _lm_studio(session, root, data["models"], model)
    status, data, _ = await _call(session, "GET", root + "/api/version")
    if status in (401, 403):
        return REFUSED.format(host=host)
    if status == 200 and isinstance(data, dict) and isinstance(data.get("version"), str):
        return await _ollama(session, root, model)
    return UNKNOWN.format(host=host)


async def unload(base_url, model, key=None, timeout=UNLOAD_SECONDS):
    """Asks Strata, Unsloth Studio, LM Studio or Ollama at the root of `base_url` to unload the model Write used: `model`,
    or on Unsloth Studio the chat model it has loaded. Returns one sentence saying what happened, without the key.
    Failures are sentences too; each request may take `timeout` seconds."""
    host = story_keys.host_of(base_url)
    root = f"{urlsplit(base_url.strip()).scheme.lower()}://{host}"
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout), headers=headers) as session:
            sentence = await _unload(session, root, host, model)
    except (TimeoutError, ValueError, aiohttp.ClientError):
        sentence = SILENT.format(host=host)
    return llm.scrub(sentence, key)
