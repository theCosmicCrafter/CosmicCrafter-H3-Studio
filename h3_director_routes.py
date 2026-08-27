"""HTTP endpoints backing the CosmicCrafter Director timeline UI.

Registration is deferred behind :func:`register_routes` and guarded on the
ComfyUI server being importable, so the node pack still imports cleanly in a
bare Python process (tests, linting, CI) where ``server``/``aiohttp`` are absent.

All filesystem access is confined to ``<input>/cosmiccrafter`` via
:func:`resolve_media_path`; browser-supplied names are never joined to a
directory without first being checked for traversal.
"""

import logging
import os

_LOG = logging.getLogger("h3_motion_context.director_routes")

#: Sub-directory of ComfyUI's input dir that the Director owns.
MEDIA_SUBDIR = "cosmiccrafter"

AUDIO_EXTENSIONS = (".wav", ".mp3", ".ogg", ".flac", ".m4a")

#: Number of peak buckets returned to the timeline waveform renderer.
WAVEFORM_PEAKS = 200

_REGISTERED = False


def media_root(folder_paths):
    """Absolute path of the Director's media directory, created on demand."""
    root = os.path.join(folder_paths.get_input_directory(), MEDIA_SUBDIR)
    os.makedirs(root, exist_ok=True)
    return os.path.realpath(root)


def resolve_media_path(folder_paths, filename, extra_roots=()):
    """Resolve a browser-supplied ``filename`` to a path inside an allowed root.

    Returns ``None`` when the name is empty, absolute, or escapes every root via
    ``..``/symlinks.  ``extra_roots`` lets reads also reach the plain input
    directory while writes stay confined to the Director's own sub-directory.
    """

    if not filename:
        return None

    # Reject absolute paths and drive-relative names outright; only the
    # traversal-free remainder is ever joined to a root.
    if os.path.isabs(filename) or os.path.splitdrive(filename)[0]:
        return None

    roots = [media_root(folder_paths)]
    for root in extra_roots:
        roots.append(os.path.realpath(root))

    for root in roots:
        candidate = os.path.realpath(os.path.join(root, filename))
        # commonpath raises on differing drives, which is itself a rejection.
        try:
            inside = os.path.commonpath([candidate, root]) == root
        except ValueError:
            continue
        if inside and os.path.isfile(candidate):
            return candidate
    return None


def waveform_peaks(file_path, num_peaks=WAVEFORM_PEAKS):
    """Downsample ``file_path`` to ``num_peaks`` absolute-peak buckets.

    Returns ``None`` if the file cannot be decoded, so the caller can report a
    waveform-less clip instead of failing the whole timeline load.
    """

    try:
        import torch
        import torchaudio
    except ImportError:
        _LOG.debug("waveform peaks unavailable: torchaudio not installed")
        return None

    try:
        audio, _sr = torchaudio.load(file_path)
    except Exception as exc:  # unreadable/corrupt media is not fatal
        _LOG.warning("audio peak extraction failed for %s: %s", file_path, exc)
        return None

    mono = audio.mean(dim=0)
    total = int(mono.shape[-1])
    if total == 0:
        return []

    num_peaks = max(1, int(num_peaks))
    # Split into exactly num_peaks buckets so the UI always gets a fixed-width
    # waveform, rather than however many a fixed stride happens to produce.
    bounds = [round(i * total / num_peaks) for i in range(num_peaks + 1)]
    peaks = []
    for lo, hi in zip(bounds, bounds[1:]):
        if hi <= lo:
            peaks.append(peaks[-1] if peaks else 0.0)
            continue
        peaks.append(float(mono[lo:hi].abs().max().item()))
    return peaks


def register_routes():
    """Attach the Director's routes to the running ComfyUI PromptServer.

    Returns ``True`` when the routes were installed.  Missing server modules
    (standalone import) or an uninitialised PromptServer are treated as a no-op
    rather than an error, matching how the rest of the pack degrades.
    """

    global _REGISTERED
    if _REGISTERED:
        return True

    try:
        import folder_paths
        from aiohttp import web
        from server import PromptServer
    except ImportError as exc:  # standalone import - no ComfyUI server present
        _LOG.debug("director routes not registered (%s)", exc)
        return False

    if getattr(PromptServer, "instance", None) is None:
        _LOG.debug("director routes not registered (PromptServer not started)")
        return False

    routes = PromptServer.instance.routes

    @routes.get("/cosmic_crafter_director_check_file")
    async def cosmic_crafter_director_check_file(request):
        """Let the uploader skip re-sending media the server already holds."""
        filename = request.query.get("filename", "")
        expected_size = request.query.get("size", "")

        found = resolve_media_path(
            folder_paths, filename,
            extra_roots=[folder_paths.get_input_directory()],
        )
        if not found:
            return web.json_response({"exists": False})

        try:
            actual = os.path.getsize(found)
        except OSError as exc:
            return web.json_response({"exists": False, "error": str(exc)})

        if expected_size and str(actual) != str(expected_size):
            return web.json_response({
                "exists": True,
                "size_mismatch": True,
                "actual": actual,
                "expected": expected_size,
            })
        return web.json_response({"exists": True, "path": found})

    @routes.post("/cosmic_crafter_director_upload_chunk")
    async def cosmic_crafter_director_upload_chunk(request):
        """Chunked upload sink that sidesteps the server's 413 body limit."""
        post = await request.post()
        chunk = post.get("chunk")
        filename = post.get("filename")

        try:
            index = int(post.get("index", 0))
            total = int(post.get("total", 1))
        except (TypeError, ValueError):
            return web.json_response({"error": "index/total must be integers"}, status=400)

        if chunk is None or not filename:
            return web.json_response({"error": "Missing chunk or filename"}, status=400)
        if index < 0 or total < 1 or index >= total:
            return web.json_response({"error": "chunk index out of range"}, status=400)

        # Writes are confined to the Director's media dir: keep only the base
        # name so "../" segments cannot walk out of it.
        safe_name = os.path.basename(str(filename))
        if not safe_name or safe_name in (".", ".."):
            return web.json_response({"error": "Invalid filename"}, status=400)

        root = media_root(folder_paths)
        file_path = os.path.join(root, safe_name)

        try:
            with open(file_path, "wb" if index == 0 else "ab") as handle:
                handle.write(chunk.file.read())
        except OSError as exc:
            _LOG.error("chunk write failed for %s: %s", file_path, exc)
            return web.json_response({"error": str(exc)}, status=500)

        if index == total - 1:
            return web.json_response({
                "status": "complete",
                "filename": f"{MEDIA_SUBDIR}/{safe_name}",
            })
        return web.json_response({"status": "ok"})

    @routes.get("/cosmic_crafter_director_get_audio")
    async def cosmic_crafter_director_get_audio(request):
        """Return waveform peaks so the timeline can draw an audio clip."""
        filename = request.query.get("filename", "")

        file_path = resolve_media_path(
            folder_paths, filename,
            extra_roots=[folder_paths.get_input_directory()],
        )
        if not file_path:
            return web.json_response({"error": "File not found"}, status=404)

        if os.path.splitext(file_path)[1].lower() not in AUDIO_EXTENSIONS:
            return web.json_response({"error": "Unsupported file format"}, status=400)

        return web.json_response({"peaks": waveform_peaks(file_path)})

    @routes.get("/cosmic_crafter_director_open_folder")
    async def cosmic_crafter_director_open_folder(request):
        """Reveal the media directory in the host OS file browser."""
        root = media_root(folder_paths)
        opener = getattr(os, "startfile", None)
        if opener is None:
            # Non-Windows hosts have no equivalent we can rely on; report the
            # path so the UI can show it rather than claiming success.
            return web.json_response({"status": "unsupported", "path": root})
        try:
            opener(root)
        except OSError as exc:
            return web.json_response({"error": str(exc)}, status=500)
        return web.json_response({"status": "ok", "path": root})

    _REGISTERED = True
    return True
