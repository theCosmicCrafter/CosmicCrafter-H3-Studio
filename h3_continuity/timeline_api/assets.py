"""Original-byte ingestion with contained native role files and logical bindings."""

import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path

import av
from PIL import Image

from .. import timed_text, reference_replacements
from .contracts import APIError, canonical

MAX_UPLOAD_BYTES = 2 * 1024**3
ROLES = {"picture": "picture", "guide": "guide", "candidate": "guide", "plate": "guide", "audio_clip": "audio", "voice_clip": "audio", "whisper": "whisper"}


def contained(root, path):
    root, path = Path(root).resolve(), Path(path).resolve()
    if not path.is_relative_to(root):
        raise APIError("invalid_asset", "Asset path must stay inside its configured directory.", status=422)
    return path


def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class Assets:
    def __init__(self, records, roots):
        self.records = records
        self.roots = {kind: Path(path).resolve() for kind, path in roots.items()}
        self.staging = contained(records.root, records.root / "uploads")
        self.staging.mkdir(parents=True, exist_ok=True)

    def _inspect(self, path, kind, checksum):
        if kind in ("picture", "guide"):
            try:
                with Image.open(path) as image:
                    fmt, width, height = image.format, image.width, image.height
                    image.verify()
                if fmt not in ("PNG", "JPEG", "WEBP", "GIF", "BMP") or (kind == "guide" and fmt != "PNG"):
                    raise ValueError()
            except (OSError, ValueError, Image.DecompressionBombError):
                raise APIError("invalid_asset", "Picture bytes are invalid; guides require an original PNG.", status=422) from None
            suffix = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp", "GIF": ".gif", "BMP": ".bmp"}[fmt]
            return suffix, {"format": fmt, "width": width, "height": height}
        if kind == 'video':
            try:
                with av.open(str(path)) as container:
                    stream = next(stream for stream in container.streams if stream.type == 'video')
                    frame = next(container.decode(stream))
                    duration = (stream.duration * float(stream.time_base) if stream.duration is not None else
                                container.duration / av.time_base if container.duration is not None else None)
                    fmt = container.format.name
                    suffix = '.mp4' if 'mp4' in fmt.split(',') else '.webm' if 'webm' in fmt.split(',') else '.video'
                    return suffix, dict(format=fmt, width=frame.width, height=frame.height, duration=duration,
                                        has_audio=any(item.type == 'audio' for item in container.streams))
            except (av.error.FFmpegError, OSError, StopIteration, ValueError):
                raise APIError('invalid_asset', 'Video bytes could not be decoded.', status=422) from None
        if kind == "audio":
            try:
                with av.open(str(path)) as container:
                    stream = next(stream for stream in container.streams if stream.type == "audio")
                    frame = next(container.decode(stream))
                    rate, channels = frame.sample_rate, len(frame.layout.channels)
                    duration = (stream.duration * float(stream.time_base) if stream.duration is not None else
                                container.duration / av.time_base if container.duration is not None else None)
                    fmt = container.format.name
                    suffix = ".wav" if "wav" in fmt.split(",") else ".flac" if "flac" in fmt.split(",") else ".audio"
                return suffix, {"format": fmt, "sample_rate": rate, "channels": channels, "duration": duration}
            except (av.error.FFmpegError, OSError, StopIteration, ValueError):
                raise APIError("invalid_asset", "Audio bytes could not be decoded.", status=422) from None
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            canonical(data)
            timed_text.import_whisper(data, "original.json", checksum)
        except (OSError, ValueError, TypeError):
            raise APIError("invalid_asset", "Whisper bytes must contain valid timed cues or words.", status=422) from None
        return ".json", {"format": "whisper"}

    def _install(self, original, root, relative, checksum):
        destination = contained(root, root / relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination = contained(root, root / relative)
        if destination.exists():
            if file_hash(destination) != checksum:
                raise APIError("asset_conflict", "A digest filename contains different bytes.", status=422)
            return destination
        temporary = contained(root, destination.with_suffix("." + uuid.uuid4().hex + ".tmp"))
        try:
            with original.open("rb") as source, temporary.open("xb") as output:
                shutil.copyfileobj(source, output, 1024 * 1024)
                output.flush(); os.fsync(output.fileno())
            try:
                os.link(temporary, destination)
            except FileExistsError:
                if file_hash(destination) != checksum:
                    raise APIError("asset_conflict", "A digest filename contains different bytes.", status=422) from None
            return destination
        finally:
            temporary.unlink(missing_ok=True)

    def ingest(self, stream, kind, expected_sha256=None):
        if kind not in ("picture", "guide", "audio", "video", "whisper"):
            raise APIError("invalid_request", "Asset kind must be picture, guide, audio, video or whisper.", path="/kind")
        if expected_sha256 is not None and (not isinstance(expected_sha256, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", expected_sha256)):
            raise APIError("invalid_request", "Expected SHA-256 is invalid.", path="/expected_sha256")
        temporary = self.staging / (uuid.uuid4().hex + ".tmp")
        try:
            hasher, size = hashlib.sha256(), 0
            with temporary.open("xb") as output:
                while chunk := stream.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_UPLOAD_BYTES:
                        raise APIError("invalid_asset", "Asset exceeds the upload limit.", status=422)
                    output.write(chunk); hasher.update(chunk)
                output.flush(); os.fsync(output.fileno())
            checksum = hasher.hexdigest()
            if expected_sha256 is not None and expected_sha256.lower() != checksum:
                raise APIError("hash_mismatch", "Uploaded bytes do not match the expected SHA-256.", status=422)
            suffix, media = self._inspect(temporary, kind, checksum)
            filename = checksum + suffix
            if kind == "guide":
                folder, root_kind = "h3_previews", "output"
            elif kind in ("picture", "audio", "video"):
                folder, root_kind = "h3_api/" + ("pictures" if kind == "picture" else kind), "input"
            else:
                folder, root_kind = "whisper", "user"
            role = self._install(temporary, self.roots[root_kind], Path(folder) / filename, checksum)
            original = self._install(temporary, self.records.root, Path("originals") / filename, checksum)
            asset_id = "asset_" + checksum
            with self.records.transaction() as db:
                row = db.execute("SELECT data FROM blobs WHERE kind='asset' AND id=?", (asset_id,)).fetchone()
                record = json.loads(row["data"]) if row else {
                    "version": 1, "id": asset_id, "sha256": checksum, "size": size, "kinds": [],
                    "media": media, "blob": original.relative_to(self.records.root).as_posix(), "files": {}}
                record["kinds"] = sorted(set(record["kinds"]) | {kind})
                record["files"][kind] = {"type": root_kind, "subfolder": folder, "filename": role.name}
                db.execute("INSERT INTO blobs VALUES ('asset',?,?) ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data",
                           (asset_id, canonical(record).decode("utf-8")))
            return self.get(asset_id)
        except OSError:
            raise APIError("invalid_asset", "Upload could not be stored completely.", status=422) from None
        finally:
            temporary.unlink(missing_ok=True)

    def get(self, asset_id):
        record = self.records.get_blob_record("asset", asset_id)
        return {"api_version": 1, **{key: record[key] for key in ("id", "sha256", "size", "kinds", "media", "files")},
                "permitted_uses": sorted([kind for kind, role in ROLES.items() if role in record["kinds"]]
                                         + (['reference_replacement'] if set(record['kinds']) & {'picture', 'audio', 'video'} else [])),
                "download_url": "/h3c/api/v1/assets/" + record["id"] + "?download=1"}

    def path(self, asset_id):
        record = self.records.get_blob_record("asset", asset_id)
        path = contained(self.records.root, self.records.root / record["blob"])
        try:
            if file_hash(path) != record["sha256"]:
                raise APIError("asset_changed", "Registered original bytes have changed.", status=422)
        except OSError:
            raise APIError("asset_missing", "Registered original bytes are unavailable.", status=422) from None
        return path

    def resolve(self, bindings, timeline, profile):
        grouped = {}
        for asset in bindings:
            record = self.records.get_blob_record("asset", asset["asset_id"])
            self.path(asset["asset_id"])
            for requested in asset["bindings"]:
                kind = requested["kind"]
                role = ROLES.get(kind)
                if kind == 'reference_replacement':
                    role = {'image': 'picture', 'audio': 'audio', 'video': 'video', 'video_audio': 'audio'}.get(
                        reference_replacements.kind(requested.get('slot')))
                if role not in record["kinds"]:
                    raise APIError("asset_role", "Asset is not registered for this use.", status=422)
                if kind == "whisper":
                    attachment = timeline.get("timed_text") or {}
                    if requested.get("source_sha256") != record["sha256"] or attachment.get("source_sha256") != record["sha256"]:
                        raise APIError("hash_mismatch", "Whisper binding must match the original timed-text source SHA-256.", status=422,
                                       path="/timeline/timed_text/source_sha256")
                    continue
                file = copy.deepcopy(record["files"][role])
                native_path = contained(self.roots[file["type"]], self.roots[file["type"]] / file["subfolder"] / file["filename"])
                try:
                    if file_hash(native_path) != record["sha256"]:
                        raise APIError("asset_changed", "Native role bytes have changed.", status=422)
                except OSError:
                    raise APIError("asset_missing", "Native role bytes are unavailable.", status=422) from None
                binding = copy.deepcopy(requested)
                if kind in ("plate", "guide"):
                    for key in ("visible_text", "text_contract"):
                        if key in binding: file[key] = binding[key]
                if kind == "picture" and int(binding["slot"][5:]) <= 16:
                    destination = profile.get("wired_assets", {}).get(binding["slot"])
                    if not destination:
                        raise APIError("invalid_asset", "Profile has no configured loader for this wired slot.", status=422)
                    binding = {"kind": "loader", "slot": binding["slot"], **destination}
                identity = canonical(file)
                item = grouped.setdefault(identity, {"file": file, "sha256": record["sha256"], "bindings": []})
                item["bindings"].append(binding)
        return list(grouped.values())
