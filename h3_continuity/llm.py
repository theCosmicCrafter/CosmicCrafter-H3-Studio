"""One chat completion on an OpenAI-compatible API, with pictures as data URLs and errors in plain words. The key
never appears in a message."""

import base64
import io
import json
import re

import aiohttp
from PIL import Image, ImageOps

from . import story_keys
from .repetition import RepetitionGuard

REQUEST_SECONDS = 600
PICTURE_SIDE = 768
PICTURE_QUALITY = 85
PICTURE_WORDS = re.compile(r"image|vision|multimodal", re.IGNORECASE)
THINKING_WORDS = re.compile(r"reasoning", re.IGNORECASE)
STREAM_WORDS = re.compile(r"\bstream(?:ing)?\b", re.IGNORECASE)
EFFORTS = {effort: effort for effort in ("minimal", "low", "medium", "high", "xhigh", "max")}
EFFORTS.update({"on": "medium", "off": "none"})
REPEATING = "Stopped the model because it kept repeating the same text."


class ChatError(ValueError):
    """A failed request, with a message for the user; `refuses_pictures` when the model can't take pictures,
    `refuses_format` when the server turned the reply format down, `refuses_thinking` when it turned
    reasoning_effort down, `refuses_stream` when streaming was rejected,
    `repetition` for an output loop, `truncated` for a reply cut off at the provider's length limit,
    `empty` for a completion with no text, `partial` for generated text available for manual recovery,
    `reason` the server's own message, and `reached` unless the connection itself failed."""

    def __init__(self, message, refuses_pictures=False, reached=True, refuses_format=False, reason="",
                 refuses_thinking=False, refuses_stream=False, repetition=False,
                 truncated=False, empty=False, partial=""):
        super().__init__(message)
        self.refuses_pictures = refuses_pictures
        self.reached = reached
        self.refuses_format = refuses_format
        self.refuses_thinking = refuses_thinking
        self.refuses_stream = refuses_stream
        self.repetition = repetition
        self.truncated = truncated
        self.empty = empty
        self.reason = reason
        self.partial = partial if isinstance(partial, str) else ""


def scrub(text, key):
    """`text` with `key` replaced by [key]."""
    return text.replace(key, "[key]") if key else text


def picture_url(path):
    """The picture at `path` as a JPEG data URL: upright, at most 768 px on its long side, transparency on black."""
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source)
        image.thumbnail((PICTURE_SIDE, PICTURE_SIDE))
        rgba = image.convert("RGBA")
    flat = Image.new("RGB", rgba.size, (0, 0, 0))
    flat.paste(rgba, mask=rgba.getchannel("A"))
    buffer = io.BytesIO()
    flat.save(buffer, "JPEG", quality=PICTURE_QUALITY)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _openai(messages, pictures):
    out = []
    for message in messages:
        items = (message.get("pictures") or []) if pictures else []
        if items:
            content = [{"type": "text", "text": message["content"]}]
            for item in items:
                content += [{"type": "text", "text": item["label"]},
                            {"type": "image_url", "image_url": {"url": item["url"]}}]
        else:
            content = message["content"]
        out.append({"role": message["role"], "content": content})
    return out


def _duration(seconds):
    return f"{seconds / 60:g} minutes" if seconds >= 60 else f"{seconds:g} seconds"


def provider_text(body):
    """The error message in a provider's error body, else the start of the body."""
    try:
        data = json.loads(body)
    except ValueError:
        data = None
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"]
        if isinstance(error, str):
            return error
    return body[:300]


def _reply_text(body, host):
    try:
        choice = json.loads(body)["choices"][0]
        content = (choice.get("message") or {}).get("content")
        finish = choice.get("finish_reason")
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        raise ChatError(f"{host} answered with something that isn't a chat completion.") from None
    if isinstance(content, list):
        content = "".join(str(part.get("text") or "") for part in content if isinstance(part, dict))
    if finish == "length":
        raise ChatError("The reply hit the model's length limit and was cut off.", truncated=True, partial=content)
    if finish == "content_filter":
        raise ChatError("The provider's content filter stopped the reply.", partial=content)
    if not isinstance(content, str) or not content.strip():
        raise ChatError("The model returned no text.", empty=True)
    return content


async def _stream_text(response, host):
    """Read OpenAI SSE deltas, closing the response as soon as a loop is detected.

    The caller's response context manager closes the connection on every error or
    cancellation. Providers decide how promptly a disconnect cancels generation.
    """
    parts, finish, event = [], None, []
    guards = {name: RepetitionGuard() for name in ("content", "reasoning_content", "reasoning")}

    def consume(lines):
        nonlocal finish
        payload = "\n".join(lines)
        if payload == "[DONE]":
            return True
        try:
            data = json.loads(payload)
            if data.get("error"):
                raise ChatError(f"{host} stopped the stream: {provider_text(payload)}")
            choices = data.get("choices") or []
            if not choices:  # usage-only and keepalive events
                return False
            choice = next((item for item in choices if item.get("index", 0) == 0), None)
            if choice is None:
                return False
            delta = choice.get("delta") or {}
            for field, guard in guards.items():
                value = delta.get(field)
                if value is None:
                    continue
                if not isinstance(value, str):
                    raise ValueError("non-text delta")
                if field == "content":
                    parts.append(value)
                if guard.feed(value):
                    raise ChatError(REPEATING, repetition=True)
            if choice.get("finish_reason") is not None:
                finish = choice["finish_reason"]
        except (ValueError, TypeError, AttributeError) as error:
            if isinstance(error, ChatError):
                raise
            raise ChatError(f"{host} sent an invalid chat-completion stream.") from None
        return False

    try:
        async for raw in response.content:
            try:
                line = raw.decode("utf-8").rstrip("\r\n")
            except UnicodeDecodeError:
                raise ChatError(f"{host} sent an invalid chat-completion stream.") from None
            if line.startswith("data:"):
                event.append(line[5:].lstrip(" "))
            elif not line and event:
                ended = consume(event)
                event = []
                if ended:
                    break
        if event:
            consume(event)
        if any(guard.feed("", final=True) for guard in guards.values()):
            raise ChatError(REPEATING, repetition=True)
        if finish is None:
            raise ChatError(f"{host}'s reply stream ended before completion.")
    except ChatError as error:
        error.partial = "".join(parts)
        raise
    except (aiohttp.ClientError, TimeoutError) as error:
        raise ChatError(f"{host}'s reply stream was interrupted: {error or type(error).__name__}.",
                        partial="".join(parts)) from None
    return _reply_text(json.dumps({"choices": [{"message": {"content": "".join(parts)},
                                               "finish_reason": finish}]}), host)


async def complete(base_url, model, messages, key=None, pictures=True, timeout=REQUEST_SECONDS, reply_format=None,
                   thinking=None, stream=False):
    """The reply text of one chat completion; raises ChatError. `messages` are {"role", "content", "pictures"}
    dicts whose pictures are {"label", "url"}; pictures are left out when `pictures` is false. `reply_format`, when
    given, is sent as the request's response_format. `thinking` sends an explicit reasoning_effort level;
    "off" sends "none" and legacy "on" sends "medium". No output token cap is sent; provider limits still apply.
    `stream` enables early repetition detection; buffered replies are checked only after receipt. The server may
    go `timeout` seconds without sending anything."""
    host = story_keys.host_of(base_url)
    url = base_url.strip().rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    body = {"model": model, "messages": _openai(messages, pictures)}
    if reply_format is not None:
        body["response_format"] = reply_format
    if thinking in EFFORTS:
        body["reasoning_effort"] = EFFORTS[thinking]
    if stream:
        body["stream"] = True
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(sock_connect=timeout, sock_read=timeout)) as session:
            async with session.post(url, json=body, headers=headers) as response:
                if response.status == 200 and response.content_type == "text/event-stream":
                    return await _stream_text(response, host)
                status, text = response.status, await response.text()
    except ChatError as error:
        error.args = (scrub(str(error), key),)
        error.reason = scrub(error.reason, key)
        raise
    except TimeoutError:
        raise ChatError(f"{host} sent nothing for {_duration(timeout)}.") from None
    except aiohttp.ClientError as error:
        raise ChatError(scrub(f"Can't reach {host}: {error or type(error).__name__}.", key),
                        reached=not isinstance(error, aiohttp.ClientConnectorError)) from None
    if status == 200:
        # Some compatible providers return ordinary JSON even when asked to
        # stream. Check finished output too, without claiming early abort.
        content = _reply_text(text, host)
        if RepetitionGuard().feed(content, final=True):
            raise ChatError(REPEATING, repetition=True, partial=content)
        return content
    if status in (401, 403):
        raise ChatError(f"{host} refused the key. Save a key for {host}." if key else f"No key is saved for {host}.")
    if status == 404:
        raise ChatError(f"Nothing at {url}. Check the base URL and the model name.")
    if status == 429:
        raise ChatError(f"{host} is limiting requests. Wait, then press Write again.")
    provider = scrub(provider_text(text), key).strip()
    sent_pictures = pictures and any(message.get("pictures") for message in messages)
    refuses_thinking = status in (400, 422) and "reasoning_effort" in body and bool(THINKING_WORDS.search(provider))
    refuses_stream = status in (400, 422) and stream and bool(STREAM_WORDS.search(provider))
    raise ChatError(f"{host} answered {status}: {provider}",
                    refuses_pictures=status == 400 and sent_pictures and bool(PICTURE_WORDS.search(provider)),
                    refuses_format=status in (400, 422) and reply_format is not None and not refuses_thinking
                    and not refuses_stream,
                    refuses_thinking=refuses_thinking, refuses_stream=refuses_stream,
                    reason=provider)
