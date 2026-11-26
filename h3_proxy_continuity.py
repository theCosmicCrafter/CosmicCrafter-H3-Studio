"""3D Proxy Continuity & ResonanceStudio Beat-Sync module for CosmicCrafter H3 Studio.

Provides clean-room helpers and ComfyUI nodes that carry persistent 3D scene state
(from Blender / Three.js world_state.json files) and beat-aligned shot schedules
into MiniMax H3 / FastH3 conditioning pipelines.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

try:
    import torch
except ImportError:  # pragma: no cover
    torch = None

_LOG = logging.getLogger("h3_proxy_continuity")


def load_world_state(path: str | Path) -> dict[str, Any]:
    """Load and validate a persistent world_state.json scene manifest."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"world_state.json not found: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in world_state.json, got {type(data).__name__}")
    data.setdefault("entities", [])
    data.setdefault("shots", [])
    data.setdefault("fps", 24)
    return data


def save_world_state(path: str | Path, state: dict[str, Any]) -> Path:
    """Persist a world_state.json scene manifest atomically."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(p)
    return p


def _dedupe_color_name(color_name: str, raw_id: str) -> str:
    """Combine proxy color_name and entity id without repeating color tokens."""
    words = [w for w in raw_id.replace("_", " ").split() if w]
    color_words = [w for w in color_name.lower().split() if w]
    filtered = [w for w in words if w.lower() not in color_words]
    name_part = " ".join(filtered or words)
    return f"{color_name.strip()} {name_part}".strip() if color_name.strip() else name_part


def _spatial_phrase(loc: list[float] | tuple[float, ...] | None) -> str:
    """Convert 3D world coordinates into natural-English spatial placement."""
    if not loc or len(loc) < 3:
        return "in the scene"
    x = float(loc[0])
    if x > 2.2:
        return "on the far right pedestal"
    if x > 0.5:
        return "on the right"
    if x < -0.5:
        return "on the left"
    return "in the center"


def bind_proxy_prompt(
    base_prompt: str,
    entities: list[dict[str, Any]],
    shot_id: str,
    beat_anchor: dict[str, Any] | None = None,
    camera_x: float | None = None,
) -> str:
    """Ground a generation prompt in natural English using proxy entity colors and layout."""
    lines = [base_prompt.strip()] if base_prompt.strip() else []
    surface_bits: list[str] = []
    spatial_bits: list[str] = []
    motion_notes: list[str] = []

    for ent in entities:
        eid = str(ent.get("id", "entity"))
        gran = str(ent.get("granularity", "medium"))
        if gran == "video_model_only":
            clean_name = eid.replace("_", " ").strip()
            motion_notes.append(f"natural organic motion for {clean_name}")
            continue

        transforms = ent.get("transforms_by_shot", {})
        shot_tf = transforms.get(shot_id) if isinstance(transforms, dict) else None
        loc = shot_tf.get("location") if isinstance(shot_tf, dict) else None
        if camera_x is not None and isinstance(loc, (list, tuple)) and len(loc) >= 1:
            if abs(float(loc[0]) - float(camera_x)) > 2.5:
                continue

        role = str(ent.get("role", ""))
        color_name = str(ent.get("color_name", "")).strip()
        label = _dedupe_color_name(color_name, eid)

        if role == "static_env":
            if color_name:
                surface_bits.append(f"a {label}")
            continue
        if role == "secondary_env":
            if camera_x is not None and isinstance(loc, (list, tuple)) and len(loc) >= 1:
                spatial_bits.append(f"a {label} {_spatial_phrase(loc)}")
            continue

        where = _spatial_phrase(loc)
        spatial_bits.append(f"a {label} {where}")

    if surface_bits and spatial_bits:
        lines.append("Resting on " + " and ".join(surface_bits) + ": " + ", ".join(spatial_bits) + ".")
    elif surface_bits:
        lines.append("Resting on " + " and ".join(surface_bits) + ".")
    elif spatial_bits:
        lines.append("Scene layout: " + ", ".join(spatial_bits) + ".")
    if motion_notes:
        lines.append("Motion: " + ", ".join(motion_notes) + ".")
    if beat_anchor and beat_anchor.get("cue") and beat_anchor["cue"] != "uniform_fallback":
        # Keep musical energy cue descriptive without injecting frame numbers into CLIP/T5
        cue_text = str(beat_anchor["cue"]).split("@")[0].replace("_", " ").strip()
        if cue_text:
            lines.append(f"Pacing: {cue_text}.")

    return " ".join(lines)


def _extract_beat_times(payload: Any) -> tuple[list[float], list[dict[str, Any]], float | None]:
    """Normalize ResonanceStudio beat-grid payloads into sorted beat times + phrases."""
    if payload is None or payload == "":
        return [], [], None
    if isinstance(payload, str):
        stripped = payload.strip()
        if not stripped:
            return [], [], None
        payload = json.loads(stripped)

    beats: list[float] = []
    phrases: list[dict[str, Any]] = []
    duration: float | None = None

    if isinstance(payload, list):
        raw_beats = payload
    elif isinstance(payload, dict):
        raw_beats = payload.get("beats", [])
        raw_phrases = payload.get("phrases", [])
        if isinstance(raw_phrases, list):
            phrases = [p for p in raw_phrases if isinstance(p, dict)]
        if payload.get("duration") is not None:
            duration = float(payload["duration"])
    else:
        return [], [], None

    for item in raw_beats:
        if isinstance(item, (int, float)):
            beats.append(float(item))
        elif isinstance(item, dict) and "time" in item:
            beats.append(float(item["time"]))
        elif isinstance(item, dict) and "t" in item:
            beats.append(float(item["t"]))

    beats = sorted(t for t in beats if t >= 0.0)
    return beats, phrases, duration


def map_resonance_beats_to_shots(
    beat_grid_json: str | dict[str, Any] | list[Any] | None,
    num_shots: int,
    fps: int = 24,
    default_shot_frames: int = 48,
) -> list[dict[str, Any]]:
    """Map ResonanceStudio beats and phrases into ordered shot frame ranges and cut cues."""
    if num_shots < 1:
        raise ValueError("num_shots must be >= 1")
    fps = max(1, int(fps))
    default_shot_frames = max(2, int(default_shot_frames))

    beats, phrases, total_duration = _extract_beat_times(beat_grid_json)
    schedule: list[dict[str, Any]] = []

    if len(beats) >= num_shots + 1:
        # Partition beat indices evenly across shots so every cut lands on a real beat
        boundaries = [beats[0]]
        for idx in range(1, num_shots):
            b_idx = int(round(idx * (len(beats) - 1) / num_shots))
            b_idx = max(1, min(len(beats) - 1, b_idx))
            boundaries.append(beats[b_idx])
        end_time = total_duration if (total_duration and total_duration > beats[-1]) else (beats[-1] + (beats[-1] - beats[0]) / max(1, len(beats) - 1))
        boundaries.append(end_time)

        prev_frame = 0
        for s_idx in range(num_shots):
            start_sec = float(boundaries[s_idx])
            end_sec = max(start_sec + (1.0 / fps), float(boundaries[s_idx + 1]))
            start_frame = max(prev_frame, int(round(start_sec * fps)))
            end_frame = max(start_frame + 1, int(round(end_sec * fps)))
            prev_frame = end_frame
            shot_beats = [b for b in beats if start_sec - 1e-6 <= b < end_sec - 1e-6]
            phrase_label = ""
            for ph in phrases:
                ps = float(ph.get("start", -1.0))
                pe = float(ph.get("end", -1.0))
                if ps <= start_sec < pe:
                    phrase_label = str(ph.get("label", ""))
                    break
            cue = f"beat_cut@{start_sec:.2f}s" + (f" [{phrase_label}]" if phrase_label else "")
            schedule.append(
                {
                    "shot_id": f"shot_{s_idx + 1:02d}",
                    "start_sec": round(start_sec, 4),
                    "end_sec": round(end_sec, 4),
                    "start_frame": start_frame,
                    "end_frame": end_frame,
                    "beat_count": len(shot_beats),
                    "cue": cue,
                }
            )
        return schedule

    # Fallback uniform frame windows when no/insufficient beat grid is supplied
    for s_idx in range(num_shots):
        sf = s_idx * default_shot_frames
        ef = sf + default_shot_frames
        schedule.append(
            {
                "shot_id": f"shot_{s_idx + 1:02d}",
                "start_sec": round(sf / fps, 4),
                "end_sec": round(ef / fps, 4),
                "start_frame": sf,
                "end_frame": ef,
                "beat_count": 0,
                "cue": "uniform_fallback",
            }
        )
    return schedule


def _load_image_tensor(path: Path, align_to_32: bool = True):
    """Load an RGB image as ComfyUI float32 IMAGE tensor [1, H, W, 3] in [0, 1]."""
    if torch is None:
        raise RuntimeError("PyTorch is required to construct ComfyUI IMAGE tensors")
    img = Image.open(path).convert("RGB")
    arr = np.asarray(img, dtype=np.float32) / 255.0
    if align_to_32:
        h, w = arr.shape[:2]
        tw = (w // 32) * 32
        th = (h // 32) * 32
        if tw < 32 or th < 32:
            raise ValueError(f"Image {path} ({w}x{h}) is smaller than 32x32")
        left = (w - tw) // 2
        top = (h - th) // 2
        arr = arr[top : top + th, left : left + tw, :]
    return torch.from_numpy(np.ascontiguousarray(arr)).unsqueeze(0)


class CosmicH3ProxyWorldState:
    """Resolve persistent 3D world state + ResonanceStudio beat timing for a shot."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "world_state_path": ("STRING", {
                    "default": r"C:\Users\richk\CascadeProjects\_shots\code2video_poc\world_state.json",
                    "tooltip": "Path to persistent world_state.json generated by Blender or Three.js.",
                }),
                "shot_id": ("STRING", {
                    "default": "shot_01",
                    "tooltip": "Shot identifier in world_state.json (e.g., shot_01, shot_03).",
                }),
                "base_prompt": ("STRING", {
                    "default": "Photorealistic studio scene following the 3D proxy layout and lighting.",
                    "multiline": True,
                }),
            },
            "optional": {
                "resonance_beats_json": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "tooltip": "Optional ResonanceStudio beat/phrase JSON payload to anchor shot frame ranges.",
                }),
                "fps": ("INT", {"default": 24, "min": 1, "max": 120}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "INT", "INT")
    RETURN_NAMES = ("grounded_prompt", "entity_manifest_json", "camera_spec_json", "start_frame", "end_frame")
    FUNCTION = "build_proxy_context"
    CATEGORY = "H3 Studio/Proxy Continuity"
    DESCRIPTION = (
        "Load persistent 3D world_state.json, bind proxy entities and colors to the prompt, "
        "and optionally sync shot frame ranges to a ResonanceStudio beat grid."
    )

    def build_proxy_context(
        self,
        world_state_path: str,
        shot_id: str,
        base_prompt: str,
        resonance_beats_json: str = "",
        fps: int = 24,
    ):
        state = load_world_state(world_state_path)
        entities = state.get("entities", [])
        shots = state.get("shots", [])
        num_shots = max(1, len(shots))

        shot_index = 0
        matched_shot: dict[str, Any] = {}
        for idx, s in enumerate(shots):
            if s.get("shot_id") == shot_id:
                shot_index = idx
                matched_shot = s
                break

        schedule = map_resonance_beats_to_shots(
            resonance_beats_json,
            num_shots=num_shots,
            fps=fps,
        )
        beat_anchor = schedule[min(shot_index, len(schedule) - 1)]

        camera_spec = matched_shot.get("camera", {})
        cam_loc = camera_spec.get("location") if isinstance(camera_spec, dict) else None
        cam_x = float(cam_loc[0]) if isinstance(cam_loc, (list, tuple)) and len(cam_loc) >= 1 else None

        grounded = bind_proxy_prompt(
            base_prompt=base_prompt,
            entities=entities,
            shot_id=shot_id,
            beat_anchor=beat_anchor,
            camera_x=cam_x,
        )

        entity_manifest = [
            {
                "id": e.get("id"),
                "granularity": e.get("granularity"),
                "color_name": e.get("color_name"),
                "hex": e.get("hex"),
                "role": e.get("role"),
                "transform": (e.get("transforms_by_shot") or {}).get(shot_id),
            }
            for e in entities
        ]

        return (
            grounded,
            json.dumps(entity_manifest, indent=2),
            json.dumps(camera_spec, indent=2),
            int(beat_anchor["start_frame"]),
            int(beat_anchor["end_frame"]),
        )


class CosmicH3ProxyKeyframes:
    """Load 3D proxy RGB + depth keyframe tensors aligned to /32 for H3 & Flux-Depth."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "shot_dir": ("STRING", {
                    "default": r"C:\Users\richk\CascadeProjects\_shots\code2video_poc",
                    "tooltip": "Directory containing <shot_prefix>_proxy.png and <shot_prefix>_depth.png.",
                }),
                "shot_prefix": ("STRING", {"default": "shot_01"}),
                "align_to_32": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "last_shot_prefix": ("STRING", {
                    "default": "",
                    "tooltip": "Optional prefix for the ending keyframe (defaults to <shot_prefix>_end/anchor/proxy).",
                }),
            },
        }

    RETURN_TYPES = ("IMAGE", "IMAGE", "IMAGE", "INT", "INT")
    RETURN_NAMES = ("first_frame", "last_frame", "depth_image", "width", "height")
    FUNCTION = "load_proxy_keyframes"
    CATEGORY = "H3 Studio/Proxy Continuity"
    DESCRIPTION = (
        "Load proxy first/last keyframes and depth map from a Code2Video shot directory, "
        "optionally center-cropped to /32 dimensions for MiniMax H3 Masked AV Bridge."
    )

    def load_proxy_keyframes(
        self,
        shot_dir: str,
        shot_prefix: str,
        align_to_32: bool = True,
        last_shot_prefix: str = "",
    ):
        root = Path(shot_dir)
        first_candidates = [root / f"{shot_prefix}_anchor.png", root / f"{shot_prefix}_proxy.png"]
        first_path = next((p for p in first_candidates if p.exists()), None)
        if first_path is None:
            raise FileNotFoundError(f"No proxy or anchor PNG found for prefix '{shot_prefix}' in {root}")

        last_candidates = []
        if last_shot_prefix.strip():
            lp = last_shot_prefix.strip()
            last_candidates.extend([root / f"{lp}_anchor.png", root / f"{lp}_proxy.png"])
        last_candidates.extend([root / f"{shot_prefix}_end.png", first_path])
        last_path = next((p for p in last_candidates if p.exists()), first_path)

        depth_path = root / f"{shot_prefix}_depth.png"
        if not depth_path.exists():
            depth_path = first_path

        first_tensor = _load_image_tensor(first_path, align_to_32=align_to_32)
        last_tensor = _load_image_tensor(last_path, align_to_32=align_to_32)
        depth_tensor = _load_image_tensor(depth_path, align_to_32=align_to_32)

        height = int(first_tensor.shape[1])
        width = int(first_tensor.shape[2])
        return (first_tensor, last_tensor, depth_tensor, width, height)
