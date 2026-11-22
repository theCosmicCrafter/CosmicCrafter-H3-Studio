"""Texts that the story node gets from nodes Write can't read, such as a switch or Generate Text: Write runs those
nodes in one job at the front of ComfyUI's queue, before the API requests, and reads what they gave."""

import asyncio
import copy

POLL_SECONDS = 0.5
PREVIEW = "PreviewAny"
PREVIEW_TITLE = "Preview as Text"
DESCRIPTION = "descriptions."
REFUSED = "ComfyUI can't run the nodes linked to the story node: {reason}"
FAILED = "The nodes linked to the story node failed at '{title}' ({kind}): {error}"
STOPPED = "ComfyUI stopped the nodes linked to the story node."
DROPPED = "ComfyUI's queue dropped the job that runs the nodes linked to the story node."


def _needed(snapshot, links):
    """The ids of the snapshot's nodes that `links` need: their own nodes and every node those take in."""
    found, waiting = set(), [str(node_id) for node_id, _ in links]
    while waiting:
        node_id = waiting.pop()
        if node_id in found or node_id not in snapshot:
            continue
        found.add(node_id)
        for value in (snapshot[node_id].get("inputs") or {}).values():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[1], int):
                waiting.append(str(value[0]))
    return found


def job_prompt(snapshot, links):
    """The API prompt that runs `links`, distinct (node id, output) pairs: copies of the snapshot's nodes they need,
    with their ids, and Preview as Text node h3c_text_n on the nth link."""
    needed = _needed(snapshot, links)
    prompt = {node_id: copy.deepcopy(node) for node_id, node in snapshot.items() if node_id in needed}
    for number, (node_id, output) in enumerate(links, 1):
        prompt[f"h3c_text_{number}"] = {"class_type": PREVIEW, "inputs": {"source": [node_id, output]}}
    return prompt


def read(entry, count, snapshot):
    """The texts of Preview as Text nodes h3c_text_1 to h3c_text_`count` in the job's history entry, trimmed, ""
    where there is none. Raises ValueError when the job failed or was stopped, naming a failed node by its title in
    `snapshot` and its type."""
    for event, data in (entry.get("status") or {}).get("messages") or []:
        if event == "execution_interrupted":
            raise ValueError(STOPPED)
        if event == "execution_error":
            node = snapshot.get(str(data.get("node_id"))) or {}
            kind = node.get("class_type") or str(data.get("node_type") or PREVIEW)
            title = (node.get("_meta") or {}).get("title") or (PREVIEW_TITLE if kind == PREVIEW else kind)
            error = str(data.get("exception_message") or "").strip()
            raise ValueError(FAILED.format(title=title, kind=kind, error=error))
    outputs = entry.get("outputs") or {}
    return [str(((outputs.get(f"h3c_text_{number}") or {}).get("text") or [""])[0]).strip()
            for number in range(1, count + 1)]


def purpose(names):
    """What the job runs the nodes for, from the story node's input names in its order: the inputs by name, then the
    number of descriptions, such as "model and 3 descriptions"."""
    parts = [name for name in names if not name.startswith(DESCRIPTION)]
    count = len(names) - len(parts)
    if count:
        parts.append("1 description" if count == 1 else f"{count} descriptions")
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


async def run(comfy, job):
    """What the nodes behind the links of the Write `job` give, by input name and trimmed: runs them in one job at the
    front of ComfyUI's queue. Cancelling the Write takes the job out of ComfyUI. Raises ValueError saying why the
    nodes didn't run."""
    return await resolve(comfy, job.ctx.snapshot, job.ctx.links, job.report)


async def resolve(comfy, snapshot, linked, report=None):
    """Run connected text inputs and return their values, using only their upstream nodes."""
    links = list(dict.fromkeys((str(link[0]), link[1]) for link in linked.values()))
    what = purpose(list(linked))
    outputs = [f"h3c_text_{number}" for number in range(1, len(links) + 1)]
    try:
        prompt_id = await comfy.queue(job_prompt(snapshot, links), outputs, front=True)
    except ValueError as error:
        raise ValueError(REFUSED.format(reason=error)) from None
    try:
        while (place := comfy.where(prompt_id)) in ("waiting", "running"):
            if report:
                report(f"Waiting for ComfyUI's queue to run the nodes for {what}..." if place == "waiting"
                       else f"Running the nodes for {what} in ComfyUI...")
            await asyncio.sleep(POLL_SECONDS)
    except asyncio.CancelledError:
        comfy.cancel(prompt_id)
        raise
    if place == "gone":
        raise ValueError(DROPPED)
    entry = comfy.history(prompt_id)
    comfy.forget(prompt_id)
    texts = dict(zip(links, read(entry, len(links), snapshot)))
    return {name: texts[(str(link[0]), link[1])] for name, link in linked.items()}
