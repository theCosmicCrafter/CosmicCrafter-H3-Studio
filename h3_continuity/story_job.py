"""H3 Story Writes as server jobs: one at a time, followed by the panel, surviving page disconnects, and taking
turns on the GPU with a model server on this PC."""

import asyncio
import copy
import dataclasses
import json
import logging
import secrets
import time
import traceback

from . import llm, story_context, story_inputs, story_keys, story_lengths, story_vram
from . import timeline as rules
from . import story_prompts as prompts, story_stages, story_guide
from . import h3_prompt_ir as prompt_ir, h3_prompt_schema as prompt_schema
from . import saved_state, story_library, still_prompt_preparation, story_bible, story_bible_write, story_check, story_fast, story_vision, timed_text

HEARTBEAT_SECONDS = 30
STALL_SECONDS = 10
KEEP_SECONDS = 600
BUSY = "A story is already being written. Cancel it or wait."
BUSY_ELSEWHERE = "A story is already being written in another workflow. Cancel it there or wait."
CHECKING = "A continuity check is running. Cancel it or wait."
CHECKING_ELSEWHERE = "A continuity check is running in another workflow. Cancel it there or wait."
UNREADABLE = "Write couldn't read the picture for {label}, so the model didn't see it."
LENGTH_KEPT = "total_seconds only applies to an empty Timeline, so Write kept your boxes' lengths."


def story_progress(ctx):
    """The progress while the story request runs."""
    return "Planning the story and its boxes..." if ctx.planning else "Writing the story..."


class Unusable(ValueError):
    """A box whose replies stayed unusable; the Write goes on with the other boxes."""


class Job:
    """One Write. `client` is the id of the page that started it and `graph` the id of its workflow's graph, both ""
    from a panel that doesn't send them; `taken` is whether a panel
    has shown how the Write ended."""

    def __init__(self, ctx, key, client="", graph=""):
        self.id = secrets.token_urlsafe(12)
        self.kind = 'write'
        self.ctx, self.key = ctx, key
        self.client, self.graph = client, graph
        self.state, self.progress = "running", story_progress(ctx)
        self.result = self.error = None
        self.drafts = {}
        self.original_text = timed_text.snapshot(ctx.timeline.timed_text, ctx.timeline.audio_clips, rules.resolved_audio(ctx.timeline))
        self.notes = list(ctx.notes)
        self.polled = time.monotonic()
        self.updated = lambda job: None
        self.ended = None
        self.task = None
        self.reached = self.releasing = self.taken = False
        self.writer_models = set()
        self.vram = self.turn = self.stopped = None

    def report(self, progress):
        self.progress = progress

    def key_for(self, base_url):
        return self.key if base_url == self.ctx.base_url else story_keys.key_for(base_url)

    def view(self):
        view = {"state": self.state, "progress": self.progress, "notes": list(self.notes),
                "original_text": copy.deepcopy(self.original_text)}
        if getattr(self, 'agent_request_id', None):
            view['request_id'] = self.agent_request_id
        if self.drafts:
            view["drafts"] = copy.deepcopy(self.drafts)
        if self.kind != 'write':
            view['kind'] = self.kind
        if self.kind == 'still_prompts':
            view['source'] = copy.deepcopy(self.still_plan['source'])
        if self.ctx.base_url:
            view["base_url"] = self.ctx.base_url
        if self.ctx.initial_base_url:
            view["story_base_url"] = self.ctx.initial_base_url
        if self.ctx.vision_model:
            view["vision_base_url"] = self.ctx.vision_base_url or self.ctx.base_url
            view["vision_model"] = self.ctx.vision_model
        if self.result is not None:
            view["result"] = self.result
        if self.error is not None:
            view["error"] = self.error
        if self.vram is not None:
            view["vram"] = self.vram
        return view


class Chat:
    """One Write's provider settings. Each request is sent once."""

    def __init__(self, job):
        self.job = job
        self.pictures = job.ctx.pictures
        self.thinking = job.ctx.thinking
        self.urls = {}
        self.box_reply = ""

    async def ask(self, messages, reply_format=None, *, thinking=None, model=None, base_url=None):
        """The provider's reply to `messages`, sent once with no output token cap."""
        ctx = self.job.ctx
        model = model or ctx.model
        base_url = base_url or ctx.base_url
        key = self.job.key_for(base_url)
        provider = (base_url, model)
        sent = await self.with_pictures(messages) if self.pictures else messages
        before = self.job.reached
        used = provider in self.job.writer_models
        box_reply = (reply_format or {}).get("json_schema", {}).get("name") == "h3_fast_box"
        # a request on its way counts: the server may be loading the model for it
        self.job.reached = True
        self.job.writer_models.add(provider)
        try:
            reply = await llm.complete(base_url, model, sent, key=key, pictures=self.pictures,
                                       reply_format=reply_format, thinking=thinking or self.thinking, stream=True)
            reply = llm.scrub(reply, key)
        except llm.ChatError as error:
            error.partial = llm.scrub(error.partial, key)
            if box_reply and error.partial.strip():
                self.box_reply = error.partial
            self.job.reached = before or error.reached
            if not used and not error.reached:
                self.job.writer_models.discard(provider)
            raise
        if box_reply and reply.strip():
            self.box_reply = reply
        return reply

    async def with_pictures(self, messages):
        out = []
        for message in messages:
            items = []
            for item in message.get("pictures") or []:
                path = item["path"]
                if path not in self.urls:
                    try:
                        self.urls[path] = await asyncio.to_thread(llm.picture_url, path)
                    except (OSError, ValueError):
                        self.urls[path] = None
                        self.job.notes.append(UNREADABLE.format(label=item["label"]))
                if self.urls[path]:
                    items.append({"label": item["label"], "url": self.urls[path]})
            out.append(dict(message, pictures=items))
        return out

    async def checked(self, messages, parse, reply_format=None):
        """Parse the single Fast planning reply; leave an unusable result for manual recovery."""
        try:
            reply = await self.ask(messages, reply_format, thinking=self.job.ctx.initial_thinking,
                                   model=self.job.ctx.initial_model, base_url=self.job.ctx.initial_base_url)
        except llm.ChatError as error:
            if error.partial:
                self.job.drafts["plan"] = {"reply": llm.scrub(error.partial, self.job.key), "error": str(error)}
            raise ValueError(str(error)) from None
        try:
            if reply_format is not None:
                story_fast.validate.shape(prompt_ir.parse_json(reply), reply_format["json_schema"]["schema"])
            parsed = parse(reply)
            plan = parsed[0] if isinstance(parsed, tuple) else parsed
            if self.job.ctx.renderer != "image":
                for beat in plan.beats:
                    if (self.job.ctx.planning or self.job.ctx.boxes[beat.box - 1].status == "write") and not beat.stages:
                        raise ValueError(f"Box {beat.box} needs planned stages and exact dialogue")
            return parsed
        except ValueError as error:
            self.job.drafts["plan"] = {"reply": llm.scrub(reply, self.job.key), "error": str(error)}
            raise ValueError(f"The model's story plan wasn't usable: {error}. It replied: {prompts.excerpt(reply)}") from None


async def write_box(chat, ctx, plan, index, final, neighbors=None, work=None):
    """One structured completion, compiled locally without an automatic correction request. With `work`, the box is
    written with the bible."""
    neighbors = neighbors if neighbors is not None else {}
    if ctx.renderer != "image":
        conflict = prompts.rules.carry_conflict(ctx.timeline, index, ctx.context_frames)
        if conflict:
            raise Unusable(conflict)
    if work is not None:
        try:
            return await story_bible_write.write_box(chat, ctx, plan, index, final, neighbors, work)
        except (llm.ChatError, ValueError) as error:
            raise Unusable(f"Box {index + 1}: {error}") from None
    kept = story_fast.edited_definitions(ctx, plan, index)
    plan = story_fast.follow_pictures(plan, index, kept)
    context = prompt_ir.resolve(ctx, index, plan.beats[index].references)
    subjects = story_fast.bindings(ctx, plan, index, context, kept)
    box = ctx.boxes[index]
    stages = (story_stages.freeze(plan.beats[index].stages, box.frames, box.carried, subjects, plan.beats[index].ends)
              if ctx.renderer != "image" else None)
    messages = story_fast.messages(ctx, plan, index, final, context, subjects, neighbors, stages=stages)
    reply_schema = story_fast.response_schema(context, subjects, image=ctx.renderer == "image", stages=stages)
    reply_format = prompt_schema.reply_format("h3_fast_box", reply_schema)
    try:
        reply = await chat.ask(messages, reply_format)
        data = prompt_ir.parse_json(reply)
        story_fast.validate.shape(data if stages is not None else story_fast.validate.shot_cuts(data), reply_schema)
        if stages is not None:
            data = story_stages.expand(data, stages)
        text, ending = story_fast.compile_prompt(data, ctx, plan, index, context, subjects, chat.job.notes, kept)
        neighbors[ctx.boxes[index].id] = ending
        beat = plan.beats[index]
        beat.terminal_state, beat.looks, beat.definitions = ending["ending"], ending["looks"], ending["definitions"]
        return text
    except (llm.ChatError, ValueError) as error:
        raise Unusable(f"Box {index + 1}: {error}") from None


async def write(job):
    """The story and the prompts of the boxes in scope, as the result the panel applies. On an empty Timeline the
    story request also plans the boxes. Invalid replies stay in draft recovery, outside renderable prompts."""
    if getattr(job, "edit", None):
        from . import story_edits
        result = await story_edits.write(job, job.edit)
    else:
        result = await write_standard(job, job.ctx)
    await story_guide.enforce(Chat(job), getattr(job, 'generated_context', job.ctx), result)
    return result


async def write_standard(job, ctx):
    chat = Chat(job)
    planning = ctx.planning
    if ctx.saved_plan and not ctx.regenerate and ctx.saved_plan.get("source_key") != story_context.identity(ctx):
        ctx = dataclasses.replace(ctx, saved_plan=None)
    if ctx.renderer != "image" and ctx.saved_plan:
        saved_plan = copy.deepcopy(ctx.saved_plan)
        for box, entry in zip(ctx.boxes, saved_plan["boxes"]):
            if box.status == "write" and not entry.get("stages"):
                entry["stages"] = story_stages.from_saved(entry["beat"],
                    ctx.box_fields.get(box.id, {}).get("source"), box.prompt)
        ctx = dataclasses.replace(ctx, saved_plan=saved_plan)
    if ctx.total_seconds and not planning:
        job.notes.append(LENGTH_KEPT)
    work = None
    if story_bible_write.uses_bible(ctx):
        if ctx.saved_plan:
            plan, planned = story_bible_write.parse_plan(json.dumps(ctx.saved_plan), ctx, saved=True)
        else:
            plan, planned = await chat.checked(story_bible_write.plan_messages(ctx),
                                               lambda reply: story_bible_write.parse_plan(reply, ctx),
                                               story_bible_write.plan_format(ctx))
        job.notes.extend(plan.notes + planned.notes)
        work = story_bible_write.Work(copy.deepcopy(planned.bible), planned.schedules, planned.joins)
    elif ctx.saved_plan:
        plan = prompts.parse_story(json.dumps(ctx.saved_plan), ctx, lenient=True)
        job.notes.extend(plan.notes)
    else:
        plan = await chat.checked(prompts.story_messages(ctx),
                                  lambda reply: prompts.parse_story(reply, ctx, lenient=True), prompts.story_format(ctx))
        job.notes.extend(plan.notes)
    if planning:
        ctx = prompts.planned_context(ctx, story_lengths.planned_timeline(ctx.shared, plan.frames, plan.cuts, plan.scenes))
        note = story_lengths.slow_note(plan.frames, [item.fresh for item in ctx.boxes], ctx.context_frames)
        if note:
            job.notes.append(note)
    job.generated_context = ctx
    final = {item.id: item.prompt for item in ctx.boxes}
    neighbors = {box.id: {"ending": beat.terminal_state, "said": prompts.said_in(box.prompt)}
                 for box, beat in zip(ctx.boxes, plan.beats) if beat.terminal_state} if ctx.renderer == "image" else {}
    ids = [item.id for item in ctx.boxes]
    if work is not None and ctx.renderer != "image":
        for index, box in enumerate(ctx.boxes):
            made = story_bible_write.compiled(ctx.box_fields.get(box.id, {}), work.bible, ids, index)
            if made is not None and made[0] == box.prompt:
                neighbors[box.id] = made[1]
    # Keep the complete plan, including endings and shot/cast bindings, for independent retries.
    saved = {"title": plan.title, "sheet": plan.sheet, "suggestions": plan.suggestions,
             "source_key": story_context.identity(ctx),
             "cast": [{"name": name, "references": refs} for name, refs in plan.cast.values()],
             "boxes": [{**dataclasses.asdict(beat), "id": item.id} for item, beat in zip(ctx.boxes, plan.beats)]}
    if ctx.saved_plan:
        saved = copy.deepcopy(ctx.saved_plan)
    if ctx.idea_references:
        saved["idea_references"] = dict(ctx.idea_references)
    if work is not None:
        saved["bible_boxes"] = {item.id: {"schedule": copy.deepcopy(work.schedules.get(index)),
                                          **({"join": dict(work.joins[index])} if index in work.joins else {})}
                                for index, item in enumerate(ctx.boxes)}
    result = {"job": job.id, "title": plan.title, "sheet": plan.sheet, "plan": saved,
              "outline": [{"box": item.id, "beat": beat.beat} for item, beat in zip(ctx.boxes, plan.beats)],
              "suggestions": [dict(item, boxes=[ids[number - 1] for number in item["boxes"]])
                              for item in plan.suggestions],
              "prompts": {}, "failed": [], "drafts": job.drafts, "notes": list(job.notes)}
    # Guided output stays provisional until the final compiled prompts pass their Guide check.
    if not ctx.guide.strip():
        job.result = result
    result["original_text"] = copy.deepcopy(job.original_text)
    result["reference_descriptions"] = {"before": ctx.timeline.reference_descriptions,
                                        "value": ctx.reference_descriptions}
    if ctx.idea_images:
        result["idea_descriptions"] = ctx.idea_descriptions
    if planning:
        result["boxes"] = [{"id": item.id, "frames": item.frames, "cut": item.cut, "new_scene": item.new_scene,
                            "seed": item.seed} for item in ctx.timeline.boxes]
        for index, item in enumerate(result["boxes"] if work is not None else []):
            item["schedule"] = copy.deepcopy(work.schedules[index])
            join = work.joins.get(index)
            join = story_bible.saved_join(join["kind"], join["note"]) if join else None
            if join is not None:
                item["join"] = join

    def show_bible():
        if work is not None and work.bible != ctx.bible:
            result["bible"] = {"before": copy.deepcopy(ctx.bible), "value": copy.deepcopy(work.bible)}

    show_bible()
    job.updated(job)
    targets = ctx.targets
    blocked = None
    for count, target in enumerate(targets, 1):
        job.progress = f"Writing box {target.number} ({count} of {len(targets)})..."
        chat.box_reply = ""
        problem = None
        try:
            if blocked is not None and not any(box.fresh for box in ctx.boxes[blocked + 1:target.number]):
                raise ValueError("Continuation waits for the previous box's valid ending; rewrite the failed box first")
            blocked = None
            if ctx.regenerate and ctx.renderer != "image" and target.prompt.strip():
                expected = prompts.said_in(target.prompt)
                if story_stages.required_dialogue(plan.beats[target.number - 1].stages) != expected:
                    raise ValueError("Rewrite changed the existing box's exact dialogue or its order")
            final[target.id] = await write_box(chat, ctx, plan, target.number - 1, final, neighbors, work)
            beat = plan.beats[target.number - 1]
            saved["boxes"][target.number - 1].update(terminal_state=beat.terminal_state, looks=beat.looks,
                                                     definitions=beat.definitions)
            result["prompts"][target.id] = {"before": target.prompt, "text": final[target.id]}
            if work is not None:
                result["prompts"][target.id].update(copy.deepcopy(work.fields.get(target.id, {})))
        except ValueError as error:
            problem = llm.scrub(str(error), job.key)
        except Exception:
            logging.error("H3 Story: box %s failed.\n%s", target.number, llm.scrub(traceback.format_exc(), job.key))
            problem = "Unexpected processing error; the ComfyUI console has the details."
        if problem is not None:
            blocked = target.number - 1
            result["failed"].append(target.id)
            draft = chat.box_reply or json.dumps({"stages": plan.beats[target.number - 1].stages}, ensure_ascii=False, indent=2)
            job.drafts[target.id] = {"reply": llm.scrub(draft, job.key), "error": problem}
            job.notes.append(f"Box {target.number}: {problem}. Saved as a draft; the Timeline prompt was kept.")
        show_bible()
        if ctx.idea_references:
            from .story_idea_refs import used_pictures
            result["pictures"] = used_pictures(ctx, [item["text"] for item in result["prompts"].values()])
            result["pictures_before"] = {item["slot"]: ctx.idea_picture_before.get(item["slot"])
                                         for item in result["pictures"]}
        result["notes"] = list(job.notes)
        job.updated(job)
    if result["failed"] and not result["prompts"]:
        raise ValueError(job.drafts[result["failed"][0]]["error"])
    return result


class Jobs:
    """The Write jobs of this ComfyUI server."""

    def __init__(self, heartbeat=HEARTBEAT_SECONDS, keep=KEEP_SECONDS, comfy=None, stall=STALL_SECONDS):
        self.heartbeat, self.keep, self.stall = heartbeat, keep, stall
        self.comfy = comfy or story_vram.Comfy()
        self.jobs = {}
        self.updated = lambda job: None

    def checkpoint(self, job, notify=True):
        if job.graph:
            record = saved_state.write("job", job.graph, job.ctx.story_id,
                                       {"job": job.id, "timeline": job.ctx.timeline_id, "view": job.view()})
            if job.kind == 'write':
                story_library.checkpoint(job.graph, job.ctx.story_id, job.ctx.timeline_id, job.id, job.view())
            if record.get("set_aside"):
                job.notes.append(f"The Story recovery file could not be read. It was kept as {record['set_aside']}, "
                                 "and a new one was started.")
        if notify:
            self.updated(job)

    def recovered(self, graph, story):
        if not graph or not story:
            return None
        record = saved_state.read("job", graph, story)["value"]
        if record and record["view"]["state"] == "running":
            view = record["view"]
            view["state"] = "interrupted"
            view["progress"] = "ComfyUI restarted. Saved boxes were recovered; press Write to fill unfinished boxes."
        return record

    def busy(self, graph):
        """The answer that turns a new job from graph `graph` down while a Write or a check runs, else None."""
        running = next((job for job in self.jobs.values() if job.state == "running"), None)
        if running is None:
            return None
        elsewhere = running.graph and graph and running.graph != graph
        if getattr(running, "kind", "") == "check":
            return {"ok": False, "error": CHECKING_ELSEWHERE if elsewhere else CHECKING}
        return {"ok": False, "error": BUSY_ELSEWHERE if elsewhere else BUSY}

    def take_over(self, job):
        """Starts `job`, and notes that no panel needs to show the jobs before it from its story node."""
        for previous in self.jobs.values():
            if (previous.graph, previous.ctx.story_id) == (job.graph, job.ctx.story_id) and (
                    job.graph or previous.client == job.client):
                previous.taken = True
        self.jobs[job.id] = job

    def start(self, body):
        """Reads the snapshot in `body` ({"prompt", "story", "client", "graph"}) and starts a Write; returns the
        route's answer."""
        self.forget()
        fields = body if isinstance(body, dict) else {}
        client, graph = (str(fields.get(name) or "") for name in ("client", "graph"))
        refused = self.busy(graph)
        if refused is not None:
            return refused
        try:
            if not isinstance(body, dict):
                raise ValueError("The Write request must be a JSON object.")
            if body.get("check_only"):
                raise ValueError("Guide Recheck was retired. Reload the page to use the current Story panel.")
            edit = body.get("edit")
            ctx = story_context.read(body.get("prompt"), body.get("story"), body.get("box"),
                                     rewrite_all=True if edit is not None else body.get("rewrite_all", False))
            if edit is not None:
                from . import story_edits
                edit = story_edits.validate(ctx, edit)
            key = None if "base_url" in ctx.links else story_keys.key_for(ctx.base_url)
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        job = Job(ctx, key, client, graph)
        job.agent_request_id = body.get('request_id')
        job.edit = edit
        story_inputs_snapshot = body["prompt"][ctx.story_id].get("inputs") or {}
        job.previous_story = story_context._saved(story_inputs_snapshot.get("state"))
        job.updated = self.checkpoint
        library = None
        try:
            if body.get('workflow') is not None:
                sequence = story_context.resolve_text(body['prompt'], body['prompt'][ctx.timeline_id]['inputs']['name'], 'Timeline name')
                library = story_library.save(graph, ctx.story_id, body['workflow'], sequence, body.get('revision'), body.get('library_revision'))
            self.checkpoint(job, notify=False)
        except (OSError, ValueError) as error:
            return {"ok": False, "error": f"Story was not started because its recovery file could not be saved: {error}"}
        self.take_over(job)
        job.task = asyncio.get_running_loop().create_task(self.run(job))
        return {"ok": True, "job": job.id, "timeline": ctx.timeline_id, **({'library': library} if library else {})}

    def start_check(self, body):
        """Reads the snapshot in `body` ({"prompt", "story", "client", "graph", "boxes"}) and starts a continuity
        check of the boxes, or of every rendered box without a current result; returns the route's answer. A check
        writes no recovery record, and doesn't start while ComfyUI renders or has prompts waiting."""
        self.forget()
        fields = body if isinstance(body, dict) else {}
        client, graph = (str(fields.get(name) or "") for name in ("client", "graph"))
        refused = self.busy(graph)
        if refused is not None:
            return refused
        if self.comfy.busy():
            return {"ok": False, "error": story_check.RENDERING}
        try:
            if not isinstance(body, dict):
                raise ValueError("The check request must be a JSON object.")
            ctx = story_check.read(body.get("prompt"), body.get("story"), body.get("boxes"))
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        job = story_check.CheckJob(ctx, client, graph)
        job.agent_request_id = body.get('request_id')
        job.updated = lambda job: self.updated(job)
        self.take_over(job)
        job.task = asyncio.get_running_loop().create_task(story_check.run(self, job))
        return {"ok": True, "job": job.id, "timeline": ctx.timeline_id}

    def start_still_prompts(self, body):
        """One explicit conversion of the current Timeline; uses the writer's provider/queue lifecycle."""
        self.forget()
        fields = body if isinstance(body, dict) else {}
        client, graph = (str(fields.get(name) or '') for name in ('client', 'graph'))
        refused = self.busy(graph)
        if refused is not None:
            return refused
        try:
            if not isinstance(body, dict):
                raise ValueError('The still prompt request must be a JSON object.')
            ctx, prepared = still_prompt_preparation.read(body)
            key = None if 'base_url' in ctx.links else story_keys.key_for(ctx.base_url)
        except ValueError as error:
            return {'ok': False, 'error': str(error)}
        job = Job(ctx, key, client, graph)
        job.agent_request_id = body.get('request_id')
        job.kind, job.still_plan = 'still_prompts', prepared
        job.report('Preparing still prompts...')
        job.updated = self.updated
        self.take_over(job)
        job.task = asyncio.get_running_loop().create_task(self.run(job))
        return {'ok': True, 'job': job.id, 'timeline': ctx.timeline_id, 'kind': job.kind}

    def poll(self, job_id, graph="", story=""):
        self.forget()
        job = self.jobs.get(job_id)
        if job is None:
            saved = self.recovered(graph, story)
            if saved and saved["job"] == job_id:
                return saved["view"]
            return {"state": "unknown"}
        now = time.monotonic()
        ran = job.ended is None or job.ended > job.polled
        if job.client and job.state != "cancelled" and ran and now - job.polled >= self.heartbeat:
            logging.info("H3 Story: the page didn't check on the Write for %.0f s; the server kept writing.",
                         now - job.polled)
        job.polled = now
        return job.view()

    def cancel(self, job_id):
        job = self.jobs.get(job_id)
        if job is None or job.state != "running" or job.releasing:
            return {"ok": False}
        job.task.cancel()
        return {"ok": True}

    def current(self, client, graph, story, recover=False):
        """The Write or check that page `client` started from story node `story` of graph `graph` and no panel has
        taken yet, as the route's answer; a check's says its kind."""
        self.forget()
        for job in reversed(list(self.jobs.values())):
            if not job.taken and (job.graph, job.ctx.story_id) == (graph, story) and (
                    graph or job.client == client):
                job.client = client
                found = {"job": job.id, "timeline": job.ctx.timeline_id}
                if getattr(job, 'agent_request_id', None):
                    found['request_id'] = job.agent_request_id
                if getattr(job, "kind", "write") != "write":
                    found["kind"] = job.kind
                return found
        if recover:
            saved = self.recovered(graph, story)
            if saved:
                return {"job": saved["job"], "timeline": saved["timeline"], 'request_id': saved['view'].get('request_id')}
        return {"job": None}

    def take(self, job_id):
        """Notes that a panel has shown how Write `job_id` ended."""
        job = self.jobs.get(job_id)
        if job is None or job.state == "running":
            return {"ok": False}
        job.taken = True
        return {"ok": True}

    def forget(self):
        """Drops old completed Writes, retaining unseen results until their workflow resumes or supersedes them."""
        now = time.monotonic()
        self.jobs = {job_id: job for job_id, job in self.jobs.items()
                     if job.ended is None or now - job.ended < self.keep or (job.client and not job.taken)}

    async def run(self, job):
        watchdog = asyncio.get_running_loop().create_task(self.watch(job))
        shares_gpu = False
        try:
            if job.ctx.links:
                texts = await story_inputs.run(self.comfy, job)
                linked_url = "base_url" in job.ctx.links
                job.ctx, notes = story_context.settle(job.ctx, texts)
                job.notes.extend(notes)
                if linked_url:
                    job.key = story_keys.key_for(job.ctx.base_url)
            ctx = job.ctx
            job.report(story_progress(ctx))
            shares_gpu = (ctx.free_vram
                          and (await asyncio.to_thread(story_vram.on_this_pc, ctx.base_url)
                               or job.kind != 'still_prompts' and bool(ctx.story_base_url) and await asyncio.to_thread(
                                   story_vram.on_this_pc, ctx.initial_base_url)
                               or job.kind != 'still_prompts' and not ctx.pictures and bool(ctx.vision_model) and await asyncio.to_thread(
                                   story_vram.on_this_pc, ctx.vision_base_url or ctx.base_url)))
            if shares_gpu:
                job.turn = await story_vram.take_turn(self.comfy, job.id, job.report)
                job.report(story_progress(ctx))
            if job.kind == 'still_prompts':
                result = await still_prompt_preparation.convert(job, Chat(job))
            else:
                await story_vision.prepare(job)
                if job.progress != story_progress(job.ctx):
                    job.report(story_progress(job.ctx))
                    self.checkpoint(job)
                result = await write(job)
            partial = bool(result.get("failed"))
            outcome = {"result": result, "state": "partial" if partial else "done",
                       "progress": (f"Incomplete: wrote {len(result['prompts'])} of "
                                    f"{len(result['prompts']) + len(result['failed'])} box prompts.") if partial
                       else "Done."}
        except asyncio.CancelledError:
            # the Write is over, but the model must still be unloaded
            asyncio.current_task().uncancel()
            outcome = ({"state": "failed", "error": job.stopped} if job.stopped else
                       {"state": "cancelled", "progress": "Cancelled."})
        except ValueError as error:
            outcome = {"state": "failed", "error": llm.scrub(str(error), job.key)}
            logging.warning("H3 Story: %s", outcome["error"])
        except Exception:
            logging.error("H3 Story: Write failed.\n%s", llm.scrub(traceback.format_exc(), job.key))
            outcome = {"state": "failed", "error": "Write failed unexpectedly; the ComfyUI console has the details."}
        finally:
            watchdog.cancel()
        try:
            if shares_gpu and job.reached:
                outcomes = []
                for base_url, model in sorted(job.writer_models):
                    if story_vram.on_this_pc(base_url):
                        job.releasing = True
                        job.report("Unloading the model...")
                        outcomes.append(await story_vram.unload(base_url, model, job.key_for(base_url)))
                if outcomes:
                    job.vram = " ".join(dict.fromkeys(outcomes))
        finally:
            story_vram.end_turn(self.comfy, job.id)
            for name, value in outcome.items():
                setattr(job, name, value)
            job.ended = time.monotonic()
            try:
                job.updated(job)
            except (OSError, ValueError) as error:
                job.error = f"Could not save Story recovery: {error}. Keep this browser open and save the workflow."
                job.state = "failed"
                self.updated(job)

    async def watch(self, job):
        """Stops `job` when its turn leaves ComfyUI's queue. Browser timers and sockets do not own its lifetime.
        Logs when the event
        loop wakes it `stall` seconds late or more."""
        step = min(1.0, self.heartbeat / 4)
        while True:
            before = time.monotonic()
            await asyncio.sleep(step)
            now = time.monotonic()
            if now - before - step >= self.stall:
                logging.warning("H3 Story: ComfyUI's event loop was blocked for %.0f s during a Write.", now - before)
            if not job.releasing and job.turn is not None and self.comfy.ahead(job.turn.prompt_id) is None:
                job.stopped = story_vram.ENDED
                job.task.cancel()
                return


JOBS = Jobs()
