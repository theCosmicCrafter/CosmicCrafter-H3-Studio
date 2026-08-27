"""The Director must honour the widgets it declares.

It previously declared 25 inputs and read 6 of them: guide strengths, the active
frame range, the encode canvas, the audio/motion toggles and the prompts were
all dead knobs that silently did nothing.  These tests pin each one to an
observable effect on the emitted conditioning.
"""

import importlib.util
import json
import sys
import types
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[1]

# Package context for nodes.py's relative imports, mirroring the pattern the
# rest of the suite uses.  Mocks are installed only when absent so sibling test
# modules sharing this process keep the environment they set up.
pkg_name = "cosmiccrafter_director_pkg"
if pkg_name not in sys.modules:
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [str(ROOT)]
    sys.modules[pkg_name] = pkg

compat = types.ModuleType(f"{pkg_name}.h3_compat")
compat.ensure_motion_context_compat = lambda *a, **k: True
compat.ensure_existing_video_compat = lambda *a, **k: True
sys.modules[f"{pkg_name}.h3_compat"] = compat

if "folder_paths" not in sys.modules:
    fp = types.ModuleType("folder_paths")
    fp.get_input_directory = lambda: "."
    fp.get_output_directory = lambda: "."
    fp.get_annotated_filepath = lambda p: p
    sys.modules["folder_paths"] = fp

if "node_helpers" not in sys.modules:
    nh = types.ModuleType("node_helpers")

    def _cond_set(cond, values, append=False):
        out = []
        for tensor, meta in cond:
            new_meta = dict(meta)
            for key, value in values.items():
                if (append and key in new_meta
                        and isinstance(new_meta[key], list)
                        and isinstance(value, list)):
                    new_meta[key] = new_meta[key] + value
                else:
                    new_meta[key] = value
            out.append([tensor, new_meta])
        return out

    nh.conditioning_set_values = _cond_set
    sys.modules["node_helpers"] = nh

if "comfy" not in sys.modules:
    cm = types.ModuleType("comfy")
    cm.utils = types.ModuleType("comfy.utils")

    class _PB:
        def __init__(self, total):
            pass

        def update_absolute(self, n):
            pass

    cm.utils.ProgressBar = _PB
    cm.nested_tensor = types.ModuleType("comfy.nested_tensor")
    sys.modules["comfy"] = cm
    sys.modules["comfy.utils"] = cm.utils
    sys.modules["comfy.nested_tensor"] = cm.nested_tensor


def _load_nodes():
    spec = importlib.util.spec_from_file_location(
        f"{pkg_name}.nodes", ROOT / "nodes.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"{pkg_name}.nodes"] = module
    spec.loader.exec_module(module)
    return module


nodes_mod = _load_nodes()

Director = nodes_mod.CosmicCrafterDirector


class _VAE:
    """Records the resolution it was asked to encode."""

    def __init__(self):
        self.encoded_sizes = []

    def encode(self, pixels):
        self.encoded_sizes.append((int(pixels.shape[2]), int(pixels.shape[1])))
        return torch.zeros(1, 24, 4, 8, 8)


def _latent(frames=124, latent_h=48, latent_w=84):
    latent_t = 2 if frames <= 5 else ((frames - 5) // 17) * 5 + 2
    return {"samples": torch.zeros(1, 24, latent_t, latent_h, latent_w)}


def _cond():
    return [[torch.zeros(1, 10, 768), {}]]


def _b64_pixel():
    """A 1x1 PNG as a data URI, so segments need no files on disk."""
    return (
        "data:image/png;base64,"
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )


def _run(timeline, **overrides):
    vae = _VAE()
    params = {
        "conditioning": _cond(),
        "latent": _latent(),
        "timeline_data": json.dumps(timeline),
        "local_prompts": "",
        "segment_lengths": "",
        "guide_strength": "",
        "audio_data": "",
        "use_custom_audio": False,
        "use_custom_motion": False,
        "inpaint_audio": False,
        "override_audio": False,
        "epsilon": 0.0,
        "frame_rate": 24,
        "display_mode": "frames",
        "custom_width": 0,
        "custom_height": 0,
        "resize_method": "stretch to fit",
        "divisible_by": 16,
        "img_compression": 0,
        "start_frame": 0,
        "end_frame": 124,
        "duration_frames": 124,
        "video vae": vae,
        "audio vae": None,
    }
    params.update(overrides)
    out, = Director().apply(**params)
    return out[0][1], vae


def _segment(start=0, length=1, **extra):
    seg = {"start": start, "length": length, "imageB64": _b64_pixel()}
    seg.update(extra)
    return seg


# ---------------------------------------------------------------------------
# guide_strength / epsilon
# ---------------------------------------------------------------------------

def test_guide_strength_from_timeline_json_reaches_the_keyframe():
    meta, _ = _run({"segments": [_segment(guideStrength=0.4)]})
    assert abs(meta["minimax_keyframes"][0]["strength"] - 0.4) < 1e-6


def test_guide_strength_falls_back_to_the_csv_widget():
    meta, _ = _run({"segments": [_segment(), _segment(start=20)]},
                   guide_strength="0.25,0.75")
    strengths = [kf["strength"] for kf in meta["minimax_keyframes"]]
    assert [round(s, 2) for s in strengths] == [0.25, 0.75]


def test_epsilon_floors_but_does_not_raise_a_strong_guide():
    weak, _ = _run({"segments": [_segment(guideStrength=0.0)]}, epsilon=0.3)
    assert abs(weak["minimax_keyframes"][0]["strength"] - 0.3) < 1e-6

    strong, _ = _run({"segments": [_segment(guideStrength=0.9)]}, epsilon=0.3)
    assert abs(strong["minimax_keyframes"][0]["strength"] - 0.9) < 1e-6


# ---------------------------------------------------------------------------
# Active frame range
# ---------------------------------------------------------------------------

def test_segments_outside_the_active_range_are_dropped():
    meta, _ = _run({"segments": [_segment(start=0), _segment(start=100)]},
                   start_frame=0, end_frame=50, duration_frames=50)
    assert len(meta["minimax_keyframes"]) == 1


def test_frame_indices_are_rebased_onto_the_active_range():
    meta, _ = _run({"segments": [_segment(start=60)]},
                   start_frame=50, end_frame=124, duration_frames=74)
    assert meta["minimax_keyframes"][0]["resolved_frame_index"] == 10


def test_duration_frames_defines_the_range_when_end_frame_is_unset():
    meta, _ = _run({"segments": [_segment(start=0), _segment(start=90)]},
                   start_frame=0, end_frame=0, duration_frames=30)
    assert len(meta["minimax_keyframes"]) == 1


def test_inverted_range_falls_back_to_the_whole_clip():
    # An unusable range must not silently discard the user's whole timeline.
    meta, _ = _run({"segments": [_segment(start=0), _segment(start=90)]},
                   start_frame=0, end_frame=0, duration_frames=0)
    assert len(meta["minimax_keyframes"]) == 2


# ---------------------------------------------------------------------------
# Encode canvas
# ---------------------------------------------------------------------------

def test_encode_canvas_defaults_to_the_latent_resolution():
    _meta, vae = _run({"segments": [_segment()]})
    # 48x84 latent at H3's /16 scale = 768x1344 pixels.
    assert vae.encoded_sizes == [(1344, 768)]


def test_custom_width_and_height_override_the_canvas():
    _meta, vae = _run({"segments": [_segment()]},
                      custom_width=512, custom_height=512)
    assert vae.encoded_sizes == [(512, 512)]


def test_maintain_aspect_ratio_fits_instead_of_stretching():
    _meta, vae = _run({"segments": [_segment()]},
                      custom_width=512, custom_height=512,
                      resize_method="maintain aspect ratio")
    width, height = vae.encoded_sizes[0]
    assert width == 512            # long edge fills the box
    assert height < 512            # short edge preserves 1344:768
    assert abs(width / height - 1344 / 768) < 0.05


def test_divisible_by_rounds_the_canvas_to_the_vae_grid():
    _meta, vae = _run({"segments": [_segment()]},
                      custom_width=500, custom_height=500, divisible_by=16)
    assert vae.encoded_sizes[0] == (496, 496)
    assert all(v % 16 == 0 for v in vae.encoded_sizes[0])


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

def test_local_prompts_csv_is_attached_when_no_clip_is_connected():
    meta, _ = _run({"segments": [_segment()]}, local_prompts="a burning city")
    assert meta["minimax_keyframes"][0]["prompt"] == "a burning city"


def test_global_prompt_is_attached_when_no_clip_is_connected():
    meta, _ = _run({"segments": []}, global_prompt="neon rain")
    assert meta["minimax_global_prompt"] == "neon rain"


def test_prompts_are_encoded_when_a_clip_is_connected():
    class _Clip:
        def tokenize(self, text):
            return {"text": text}

        def encode_from_tokens_scheduled(self, tokens):
            return [[torch.zeros(1, 1, 768), {"encoded": tokens["text"]}]]

    meta, _ = _run({"segments": [_segment(prompt="a wolf")]}, clip=_Clip())
    encoded = meta["minimax_keyframes"][0]["prompt_conditioning"]
    assert encoded[0][1]["encoded"] == "a wolf"


# ---------------------------------------------------------------------------
# Toggles
# ---------------------------------------------------------------------------

def test_text_segments_never_become_keyframes():
    meta, _ = _run({"segments": [_segment(type="text"), _segment(start=10)]})
    assert len(meta["minimax_keyframes"]) == 1


def test_motion_segments_are_ignored_unless_enabled():
    timeline = {"segments": [], "motionSegments": [{"start": 0, "length": 17}]}
    meta, _ = _run(timeline, use_custom_motion=False)
    assert "minimax_motion_guides" not in meta

    meta, _ = _run(timeline, use_custom_motion=True)
    assert len(meta["minimax_motion_guides"]) == 1


def test_audio_segments_are_ignored_unless_enabled():
    timeline = {"segments": [], "audioSegments": [{"start": 0, "audioFile": "nope.wav"}]}
    meta, _ = _run(timeline, use_custom_audio=False)
    assert "minimax_refs" not in meta


def test_malformed_timeline_json_does_not_raise():
    vae = _VAE()
    out, = Director().apply(
        conditioning=_cond(), latent=_latent(), timeline_data="{not json",
        local_prompts="", segment_lengths="", guide_strength="", audio_data="",
        use_custom_audio=False, use_custom_motion=False, inpaint_audio=False,
        override_audio=False, epsilon=0.0, frame_rate=24, display_mode="frames",
        custom_width=0, custom_height=0, resize_method="stretch to fit",
        divisible_by=16, img_compression=0, start_frame=0, end_frame=124,
        duration_frames=124, **{"video vae": vae, "audio vae": None},
    )
    # Conditioning passes through untouched: no keyframes, refs or guides.
    assert len(out) == 1
    assert out[0][1] == {}


def test_missing_image_file_is_skipped_not_fatal():
    timeline = {"segments": [{"start": 0, "length": 1, "imageFile": "absent.png"}]}
    meta, _ = _run(timeline)
    assert "minimax_keyframes" not in meta


# ---------------------------------------------------------------------------
# Declared-versus-used contract
# ---------------------------------------------------------------------------

def test_every_declared_input_is_read_or_documented_as_ui_only():
    """No silent dead knobs: each widget is used, or listed as UI-only."""
    import inspect

    source = inspect.getsource(Director.apply)
    schema = Director.INPUT_TYPES()
    declared = list(schema["required"]) + list(schema.get("optional", {}))

    unused = [
        name for name in declared
        if name not in Director.UI_ONLY_INPUTS
        and name.replace(" ", " ") not in source
        and f'"{name}"' not in source
    ]
    assert not unused, f"declared but never read: {unused}"
