"""Decode verified native media into immutable, job-bound download records."""

import copy
import json
import os
import shutil
import uuid
from pathlib import Path

import av

from .. import nodes, store
from .assets import contained, file_hash
from .contracts import APIError, digest
from .planning import media_units, native_status


class Artifacts:
    def __init__(self, records, root):
        self.records, self.root = records, Path(root).resolve()
        self.blobs = contained(records.root, records.root / "artifacts")
        self.blobs.mkdir(parents=True, exist_ok=True)

    def _source(self, descriptor):
        if (descriptor.get("type") != "output" or not isinstance(descriptor.get("filename"), str)
                or Path(descriptor["filename"]).name != descriptor["filename"]
                or not descriptor["filename"].endswith(".mp4")):
            raise APIError("invalid_artifact", "Artifact must name a contained native output MP4.", status=422)
        return contained(self.root, self.root / descriptor.get("subfolder", "") / descriptor["filename"])

    def _inspect(self, path, project, descriptor, expected_frames):
        fps = project.get("profile_snapshot", {}).get("output_fps", 24)
        expected_frames = descriptor.get("output_frames", round(expected_frames * fps / 24))
        try:
            with av.open(str(path)) as container:
                videos = list(container.streams.video)
                if len(videos) != 1 or abs(float(videos[0].average_rate or 0) - fps) > .0001: raise ValueError()
                stream = videos[0]
                settings = (project["prepared"].get("production_size", {}).get("output_geometry")
                            or project.get("profile_snapshot", {}).get("output_geometry") or project["prepared"]["settings"])
                if (stream.width, stream.height) != (settings["width"], settings["height"]): raise ValueError()
                frames, stamps = 0, []
                for frame in container.decode(stream):
                    frames += 1
                    stamps.append(float(frame.pts * frame.time_base))
                if frames != expected_frames or any(abs((b-a)-1/fps) > .0001 for a,b in zip(stamps,stamps[1:])):
                    raise ValueError()
            audio = None
            with av.open(str(path)) as container:
                streams = list(container.streams.audio)
                expected_rate = descriptor.get("audio_sample_rate")
                if len(streams) > 1 or (expected_rate and not streams): raise ValueError()
                if streams:
                    stream = streams[0]
                    rate = stream.sample_rate
                    channels = len(stream.layout.channels)
                    samples = sum(frame.samples for frame in container.decode(stream))
                    if expected_rate and rate != expected_rate: raise ValueError()
                    if samples <= 0 or not 1 <= channels <= 2 or abs(samples/rate - frames/fps) > .1: raise ValueError()
                    audio = {"sample_rate": rate, "channels": channels, "samples": samples, "duration": samples/rate}
            return {"frames": frames, "fps": fps, "width": settings["width"], "height": settings["height"], "audio": audio}
        except (OSError, ValueError, av.error.FFmpegError):
            raise APIError("media_invalid", "Saved media has invalid frame, timing, geometry or audio metadata.", status=422) from None

    def snapshot(self, project, job, descriptor, *, expected_frames, kind):
        source = self._source(descriptor)
        temporary = contained(self.records.root, self.blobs / (uuid.uuid4().hex + ".tmp"))
        try:
            stat = source.stat(); checksum = file_hash(source)
            with source.open("rb") as incoming, temporary.open("xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing, 1024*1024)
                outgoing.flush(); os.fsync(outgoing.fileno())
            after = source.stat()
            if ((stat.st_size, stat.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
                    or file_hash(temporary) != checksum or file_hash(source) != checksum):
                raise APIError("artifact_changed", "Native media changed while it was being snapshotted.", status=409)
            metadata = self._inspect(temporary, project, descriptor, expected_frames)
            destination = contained(self.records.root, self.blobs / (checksum + ".mp4"))
            try: os.link(temporary, destination)
            except FileExistsError:
                if file_hash(destination) != checksum:
                    raise APIError("artifact_corrupt", "Immutable artifact bytes have changed.", status=500) from None
            identity = {"project_id": project["id"], "revision": project["revision"], "job_id": job["id"],
                        "unit_id": descriptor.get("unit_id"), "kind": kind, "sha256": checksum}
            identifier = "artifact_" + digest(identity)
            record = {**identity, **metadata, "api_version": 1, "id": identifier, "profile_sha256": project["profile_sha256"],
                      "created": job["created"], "size": stat.st_size, "blob": destination.relative_to(self.records.root).as_posix(),
                      "download_url": "/h3c/api/v1/artifacts/" + identifier + "/download"}
            self.records.put_immutable_blob_record("artifact", record)
            return self.get(identifier)
        except OSError:
            raise APIError("artifact_unavailable", "Native media could not be read or committed.", status=409) from None
        finally:
            temporary.unlink(missing_ok=True)

    def get(self, artifact_id):
        record = self.records.get_blob_record("artifact", artifact_id)
        return {key: copy.deepcopy(value) for key,value in record.items() if key != "blob"}

    def path(self, artifact_id):
        record = self.records.get_blob_record("artifact", artifact_id)
        path = contained(self.records.root, self.records.root / record["blob"])
        try:
            if file_hash(path) != record["sha256"]: raise OSError()
        except OSError:
            raise APIError("artifact_corrupt", "Immutable artifact bytes are unavailable or changed.", status=500) from None
        return path

    def _body(self, project):
        return {"name": project["sequence"], "timeline": json.dumps(project["prepared"]["timeline"]),
                "settings": project["prepared"]["settings"]}

    def _unit(self, project, unit, status):
        if unit["kind"] == "box":
            found = next((item for item in status["boxes"] if item["id"] == unit["box_id"]), None)
        else:
            found = next((item for item in status.get("bridges",[]) if item["box"] == unit["box_id"]), None)
        if found is None or found["status"] != "done" or not found.get("video"):
            raise APIError("native_media_stale", "Required native unit is missing, stale or lacks decoded media.", status=409)
        descriptor = copy.deepcopy(found["video"]["file"])
        descriptor["unit_id"] = unit["id"]
        folder = store.sequence_dir(nodes.sequences_root(), project["sequence"])
        manifest = store.load_manifest(folder)
        entry = next(item for item in (manifest["segments"] if unit["kind"] == "box" else manifest.get("bridges",[]))
                     if ((item.get("timeline") or {}).get("box") if unit["kind"] == "box" else item.get("box")) == unit["box_id"])
        descriptor["audio_sample_rate"] = entry.get("audio_sample_rate")
        fps = project.get("profile_snapshot", {}).get("output_fps", 24)
        if found["video"]["frames"] != round(unit["frames"] * fps / 24) or found["video"]["fps"] != fps:
            raise APIError("native_media_stale", "Native unit metadata does not match planned timing.", status=409)
        return descriptor

    def verify_unit(self, project, job, attempt):
        if attempt["state"] != "succeeded" or attempt.get("evidence",{}).get("state") != "succeeded":
            raise APIError("native_evidence_uncertain", "Unit needs attributed terminal execution evidence.", status=409)
        with nodes.SEQUENCE_LOCK:
            status = native_status(self._body(project))
            descriptor = self._unit(project, attempt["unit"], status)
            artifact = self.snapshot(project,job,descriptor,expected_frames=attempt["unit"]["frames"],kind=attempt["unit"]["kind"])
            self.records.put_blob_record("unit", {"id": project["id"]+":"+attempt["unit_id"], "verified": True,
                "input_sha256": attempt["unit"]["input_sha256"], "native_sha256": status["unit_evidence"][attempt["unit_id"]],
                "artifact_id": artifact["id"], "job_id": job["id"]})
            return artifact

    def finalize(self, project, job, native):
        with nodes.SEQUENCE_LOCK:
            status = native_status(self._body(project))
            artifacts = []
            for unit in media_units(job["plan"]["units"]):
                descriptor = self._unit(project, unit, status)
                provenance = self.records.get_blob_record("unit",project["id"]+":"+unit["id"])
                if (not provenance.get("verified") or provenance["input_sha256"] != unit["input_sha256"]
                        or provenance["native_sha256"] != status["unit_evidence"][unit["id"]]):
                    raise APIError("native_media_stale", "Native media no longer matches verified API input identity.", status=409)
                artifacts.append(self.snapshot(project,job,descriptor,expected_frames=unit["frames"],kind=unit["kind"]))
            if job["selection"].get("rebuild_continuity"):
                # This job intentionally delivered one new take; dependent clips now await Render remaining.
                return artifacts
            owner = {"project_id":project["id"],"job_id":job["id"],"revision":job["revision"],
                     "profile_sha256":job["profile_sha256"],"owner_token":job["owner_token"]}
            current = native.status(project,materialize=True,managed_owner=owner)
            descriptor = current.get("full_video")
            if not current.get("ok") or not descriptor:
                raise APIError("full_video_unavailable", "Full video could not be materialized with every planned bridge.", status=409)
            rate = next((item["audio"]["sample_rate"] for item in artifacts if item.get("audio")),None)
            soundtrack = sorted((clip for clip in project["prepared"]["timeline"].get("audio_clips",[])
                                 if clip.get("in_full_video") is True),key=lambda clip:clip["slot"])
            if soundtrack:
                # Native placement uses the first marked original's clock/rate,
                # which can differ from the generated H3 unit waveforms.
                slot = soundtrack[0]["slot"]
                asset = next(asset for asset in project["assets"] if any(
                    binding.get("kind") == "audio_clip" and binding.get("slot") == slot
                    for binding in asset["bindings"]))
                rate = self.records.get_blob_record("asset",asset["asset_id"])["media"]["sample_rate"]
            fps = project.get("profile_snapshot", {}).get("output_fps", 24)
            descriptor = {**descriptor,"audio_sample_rate": rate,
                          "output_frames": sum(round(unit["frames"] * fps / 24) for unit in media_units(job["plan"]["units"]))}
            artifacts.append(self.snapshot(project,job,descriptor,expected_frames=job["plan"]["total_frames"],kind="full_video"))
            return artifacts

# static-configuration-interop-v1

# captured-api-delivery-v2

# configured-production-size-v1
