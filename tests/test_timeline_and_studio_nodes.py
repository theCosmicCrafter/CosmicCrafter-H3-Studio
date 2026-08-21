import json
import importlib.util
import sys
import types
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[1]

# Set up package context for relative imports
pkg_name = "cosmiccrafter_pkg"
if pkg_name not in sys.modules:
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [str(ROOT)]
    sys.modules[pkg_name] = pkg

compat = types.ModuleType(f"{pkg_name}.h3_compat")
compat.ensure_motion_context_compat = lambda *args, **kwargs: True
compat.ensure_existing_video_compat = lambda *args, **kwargs: True
sys.modules[f"{pkg_name}.h3_compat"] = compat

# Mock folder_paths, comfy, and node_helpers if missing
if "folder_paths" not in sys.modules:
    fp = types.ModuleType("folder_paths")
    fp.get_output_directory = lambda: "."
    fp.get_annotated_filepath = lambda p: p
    fp.get_input_directory = lambda: "."
    sys.modules["folder_paths"] = fp

if "node_helpers" not in sys.modules:
    nh = types.ModuleType("node_helpers")
    def _cond_set(c, v, append=False):
        res = []
        for tensor, d in c:
            new_d = dict(d)
            for k, val in v.items():
                if append and k in new_d and isinstance(new_d[k], list) and isinstance(val, list):
                    new_d[k] = new_d[k] + val
                else:
                    new_d[k] = val
            res.append([tensor, new_d])
        return res
    nh.conditioning_set_values = _cond_set
    sys.modules["node_helpers"] = nh

if "comfy" not in sys.modules:
    cm = types.ModuleType("comfy")
    cm.utils = types.ModuleType("comfy.utils")
    class PB:
        def __init__(self, t): pass
        def update_absolute(self, n): pass
    cm.utils.ProgressBar = PB
    cm.nested_tensor = types.ModuleType("comfy.nested_tensor")
    sys.modules["comfy"] = cm
    sys.modules["comfy.utils"] = cm.utils
    sys.modules["comfy.nested_tensor"] = cm.nested_tensor


def _load_nodes():
    spec = importlib.util.spec_from_file_location(f"{pkg_name}.nodes", ROOT / "nodes.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"{pkg_name}.nodes"] = mod
    spec.loader.exec_module(mod)
    return mod


nodes_mod = _load_nodes()

from h3_audio_reactive import (
    MiniMaxH3AudioAnalyze,
    MiniMaxH3AudioReactiveDenoise,
    MiniMaxH3AudioCurveRemap,
)


class MockVideoVAE:
    def encode(self, x):
        b = x.shape[0]
        steps = max(1, (b - 1) // 4 + 1 if b > 1 else 1)
        return torch.ones((1, 24, steps, 8, 8), dtype=torch.float32)


class MockAudioVAE:
    def encode(self, chunk):
        samples = chunk.shape[-1]
        steps = max(1, samples // 800)
        return torch.ones((1, 32, 2, steps), dtype=torch.float32)


def test_audio_reactive_full_pipeline():
    """Verify AudioAnalyze -> Denoise -> CurveRemap execution chain."""
    sr = 32000
    duration = 4.0  # 4 seconds
    t = torch.linspace(0, duration, int(sr * duration))
    waveform = (torch.sin(2 * 3.14159 * 220 * t) + 0.5 * torch.sin(2 * 3.14159 * 880 * t)).unsqueeze(0).unsqueeze(0)
    audio_dict = {"waveform": waveform, "sample_rate": sr}

    analyzer = MiniMaxH3AudioAnalyze()
    energy, beats, brightness, onsets, bass, mids, highs = analyzer.analyze(
        audio=audio_dict,
        clip_start_seconds=0.0,
        clip_frames=96,
        beat_decay=0.15,
        sensitivity=1.0,
    )

    assert len(energy) == 96
    assert len(beats) == 96
    assert len(brightness) == 96
    assert len(onsets) == 96
    assert len(bass) == 96
    assert len(mids) == 96
    assert len(highs) == 96

    # Verify Denoise modulation
    denoiser = MiniMaxH3AudioReactiveDenoise()
    denoise_val, = denoiser.map_strength(
        curve=energy,
        mode="peak",
        min_strength=0.7,
        max_strength=1.0,
        invert=False,
    )
    assert 0.7 <= denoise_val <= 1.0

    # Verify Remap
    remapper = MiniMaxH3AudioCurveRemap()
    remapped, = remapper.remap(
        curve=energy,
        smooth_frames=3,
        gamma=1.5,
        threshold=0.05,
        min_out=0.0,
        max_out=1.0,
    )
    assert len(remapped) == 96
    assert min(remapped) >= 0.0
    assert max(remapped) <= 1.0


def test_timeline_editor_image_clip_execution():
    timeline_node = nodes_mod.MiniMaxH3Timeline()
    v_vae = MockVideoVAE()
    a_vae = MockAudioVAE()

    cond = [[torch.zeros(1, 10, 768), {}]]
    latent = {"samples": torch.zeros((1, 24, 23, 60, 108))}  # 124 frames (23 steps)

    timeline_state = json.dumps({
        "clips": [
            {"id": 1, "kind": "image", "start": 1, "len": 1}
        ]
    })

    img = torch.ones((1, 480, 864, 3), dtype=torch.float32)
    out_cond, = timeline_node.apply(
        conditioning=cond,
        latent=latent,
        timeline_state=timeline_state,
        crop="disabled",
        image_1=img,
        **{"video vae": v_vae, "audio vae": a_vae, "fps": 24}
    )

    kfs = out_cond[0][1].get("minimax_keyframes", [])
    assert len(kfs) >= 1
    assert kfs[0]["resolved_frame_index"] == 0
    assert "latent" in kfs[0]


def test_timeline_editor_multi_track_execution():
    timeline_node = nodes_mod.MiniMaxH3Timeline()
    v_vae = MockVideoVAE()
    a_vae = MockAudioVAE()

    cond = [[torch.zeros(1, 10, 768), {}]]
    latent = {"samples": torch.zeros((1, 24, 23, 60, 108))}

    timeline_state = json.dumps({
        "clips": [
            {"id": 1, "kind": "image", "start": 1, "len": 1},
            {"id": 2, "kind": "video", "start": 18, "len": 5},
            {"id": 3, "kind": "audio", "start": 40, "len": 24}
        ]
    })

    img = torch.ones((1, 480, 864, 3), dtype=torch.float32)
    vid = torch.ones((5, 480, 864, 3), dtype=torch.float32)
    aud = {"waveform": torch.ones((1, 2, 32000)), "sample_rate": 32000}

    out_cond, = timeline_node.apply(
        conditioning=cond,
        latent=latent,
        timeline_state=timeline_state,
        crop="disabled",
        image_1=img,
        video_2=vid,
        audio_3=aud,
        **{"video vae": v_vae, "audio vae": a_vae, "fps": 24}
    )

    kfs = out_cond[0][1].get("minimax_keyframes", [])
    refs = out_cond[0][1].get("minimax_refs", [])

    assert len(kfs) >= 2  # image + video steps
    assert len(refs) >= 1  # audio ref
    assert refs[0]["kind"] == "audio"
    assert refs[0]["resolved_frame_index"] == 63  # 39 (start zero) + 24 len = 63


def test_custom_audio_node_execution():
    node = nodes_mod.MiniMaxH3CustomAudio()
    a_vae = MockAudioVAE()

    cond = [[torch.zeros(1, 10, 768), {}]]
    latent = {"samples": torch.zeros((1, 24, 23, 60, 108))}

    audio_state = json.dumps({"count": 2, "positions": [10, 50], "strengths": [1.0, 0.8]})
    aud1 = {"waveform": torch.ones((1, 2, 32000)), "sample_rate": 32000}
    aud2 = {"waveform": torch.ones((1, 2, 32000)), "sample_rate": 32000}

    out_cond, = node.apply(
        conditioning=cond,
        audio_vae=a_vae,
        latent=latent,
        audio_state=audio_state,
        indexing="1-based",
        align="end",
        audio_1=aud1,
        audio_2=aud2
    )

    refs = out_cond[0][1].get("minimax_refs", [])
    assert len(refs) == 2
    assert refs[0]["kind"] == "audio"
    assert refs[0]["resolved_frame_index"] == 10
    assert refs[1]["resolved_frame_index"] == 50


def test_custom_video_node_execution():
    node = nodes_mod.MiniMaxH3CustomVideo()
    v_vae = MockVideoVAE()
    a_vae = MockAudioVAE()

    cond = [[torch.zeros(1, 10, 768), {}]]
    latent = {"samples": torch.zeros((1, 24, 23, 60, 108))}

    video_state = json.dumps({"count": 1, "positions": [15], "strengths": [0.9]})
    vid = torch.ones((5, 480, 864, 3), dtype=torch.float32)
    aud = {"waveform": torch.ones((1, 2, 32000)), "sample_rate": 32000}

    out_cond, = node.apply(
        conditioning=cond,
        vae=v_vae,
        latent=latent,
        video_state=video_state,
        indexing="1-based",
        crop="disabled",
        audio_vae=a_vae,
        video_1=vid,
        video_audio_1=aud
    )

    kfs = out_cond[0][1].get("minimax_keyframes", [])
    refs = out_cond[0][1].get("minimax_refs", [])

    assert len(kfs) >= 2
    assert len(refs) == 1
    assert refs[0]["kind"] == "audio"
    assert refs[0]["resolved_frame_index"] == 19  # 14 (zero_based) + 5
