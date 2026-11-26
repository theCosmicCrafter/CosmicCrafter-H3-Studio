# -*- coding: utf-8 -*-
"""
tests/test_studio_futureproof.py — Comprehensive verification suite for all consolidated
H3 Studio nodes, joint AV NestedTensor compatibility, 17k+5 / 51m+39 frame grids,
security hardening, and ComfyUI Registry standards.
"""

from pathlib import Path
import sys
import torch

_TESTS_DIR = str(Path(__file__).resolve().parent)
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from cosmic_h3_vram import CosmicH3OptimalBucketSelector, CosmicH3DynamicTilingDecoder
from cosmic_h3_advanced import CosmicH3AdaptiveNoiseRecoupling, CosmicH3OpticalFlowMotionBucket
from cosmic_h3_context import CosmicH3SlidingContextWindow, CosmicH3AutoregressiveFrameExtender
from cosmic_h3_loop import (
    MiniMaxH3Loop,
    MiniMaxH3LoopDecode,
    MiniMaxH3LoopControlVideo,
    loop_sampler_wrapper,
    wrap_pad,
    joint_weight,
)
from h3_frame_calc import MiniMaxH3FrameCalculator
from h3_director_routes import sanitize_upload_filename, resolve_media_path
from h3_prompt._providers import _validate_http_url, ProviderError
from h3_prompt._validate import repair, check
from h3_prompt.cosmic_h3_prompt import CosmicH3VideoForensics
from test_pack_loads import _loaded_nodes_module


class _MockNestedTensor:
    """Simulates ComfyUI's comfy.nested_tensor.NestedTensor([video_latent, audio_latent])."""
    def __init__(self, tensors):
        self._tensors = list(tensors)

    def unbind(self):
        return list(self._tensors)


class _DummyModel:
    def __init__(self):
        self.model_options = {"transformer_options": {}}
        self.post_cfg_fn = None
        self.patches = {}

    def clone(self):
        m = _DummyModel()
        m.model_options = {"transformer_options": dict(self.model_options.get("transformer_options", {}))}
        m.post_cfg_fn = self.post_cfg_fn
        m.patches = dict(self.patches)
        return m

    def set_model_sampler_post_cfg_function(self, fn):
        self.post_cfg_fn = fn

    def set_model_patch_replace(self, fn, *keys):
        self.patches[keys] = fn


def test_optimal_bucket_selector_h3_grids():
    """Verify CosmicH3OptimalBucketSelector snaps to 17k+5, 51m+39 harmonic, and 4k+1 grids."""
    node = CosmicH3OptimalBucketSelector()

    # Default mode: 17k+5 (H3 Native)
    w, h, f, ar, name = node.select_bucket(1280, 720, 120, "nearest_bucket")
    assert (w, h) == (1280, 720)
    assert f == 124
    assert (f - 5) % 17 == 0
    assert name == "1280x720_16:9_landscape"

    # Harmonic AV mode: 51m+39
    _, _, f_harm, _, _ = node.select_bucket(1280, 720, 100, "nearest_bucket", "51m+39 (H3 Harmonic AV)")
    assert f_harm == 90
    assert (f_harm - 39) % 51 == 0

    # Legacy 4k+1 mode
    _, _, f_leg, _, _ = node.select_bucket(1280, 720, 80, "nearest_bucket", "4k+1 (Legacy)")
    assert f_leg == 81
    assert (f_leg - 1) % 4 == 0


def test_dynamic_tiling_decoder_nested_and_24ch():
    """Verify CosmicH3DynamicTilingDecoder unpacks joint AV NestedTensor and decodes 24-ch H3 latents."""
    decoder = CosmicH3DynamicTilingDecoder()
    # 7 latent frames in 24-channel H3 = 1 clip (5 lat -> 17 frames) + tail (2 lat -> 5 frames) = 22 pixel frames
    video_lat = torch.zeros((1, 24, 7, 8, 8), dtype=torch.float32)
    audio_lat = torch.zeros((1, 128, 1, 37), dtype=torch.float32)
    nested = _MockNestedTensor([video_lat, audio_lat])

    (images,) = decoder.decode(
        vae=None,
        samples={"samples": nested},
        tile_sample_min_height=64,
        tile_sample_min_width=64,
        tile_overlap=16,
        temporal_tile_size=4,
        temporal_overlap=1,
    )
    assert images.shape == (22, 128, 128, 3)


def test_adaptive_noise_recoupling_nested_tensor_and_cache():
    """Verify CosmicH3AdaptiveNoiseRecoupling works on both 5D Tensor and joint AV NestedTensor."""
    node = CosmicH3AdaptiveNoiseRecoupling()
    model = _DummyModel()
    (patched,) = node.patch(
        model=model,
        noise_strength=0.1,
        recouple_ratio=0.5,
        decay_power=2.0,
        highpass_cutoff=0.1,
        lowpass_cutoff=0.8,
        schedule_mode="cosine",
    )
    assert patched.post_cfg_fn is not None

    v_lat = torch.zeros((1, 24, 4, 16, 16))
    a_lat = torch.zeros((1, 128, 1, 20))
    nested_in = _MockNestedTensor([v_lat, a_lat])
    nested_den = _MockNestedTensor([v_lat.clone(), a_lat.clone()])

    out = patched.post_cfg_fn({
        "denoised": nested_den,
        "input": nested_in,
        "sigma": torch.tensor([0.5]),
    })
    unpacked = out.unbind()
    # Video latent must receive band-passed noise, while audio latent remains untouched
    assert not torch.allclose(unpacked[0], v_lat)
    assert torch.allclose(unpacked[1], a_lat)


def test_optical_flow_motion_bucket_deterministic_and_pixel_resample():
    """Verify CosmicH3OpticalFlowMotionBucket is deterministic, grad-free, and resamples 17k+5 pixel flow."""
    node = CosmicH3OpticalFlowMotionBucket()
    # 22 pixel frames (17k+5 with k=1 -> 7 H3 latent frames)
    flow_imgs = torch.ones((22, 32, 32, 3), dtype=torch.float32) * 0.25

    m1 = _DummyModel()
    m2 = _DummyModel()
    (p1,) = node.patch(m1, flow_imgs, 1.5, 127, "bilinear", "6-7")
    (p2,) = node.patch(m2, flow_imgs, 1.5, 127, "bilinear", "6-7")

    hook1 = p1.patches[("dit", "double_block", 6)]
    hook2 = p2.patches[("dit", "double_block", 6)]

    # 7 latent frames * 8x8 spatial tokens = 448 tokens
    hidden = torch.zeros((2, 7 * 8 * 8, 64), dtype=torch.float32)
    extra = {"original_block": lambda a: {"img": hidden.clone()}}

    res1 = hook1({}, extra)["img"]
    res2 = hook2({}, extra)["img"]
    assert res1.shape == hidden.shape
    assert not res1.requires_grad
    assert torch.allclose(res1, res2)


def test_context_window_and_autoregressive_extender_h3():
    """Verify CosmicH3SlidingContextWindow and CosmicH3AutoregressiveFrameExtender."""
    win = CosmicH3SlidingContextWindow()
    m = _DummyModel()
    (patched,) = win.patch(m, context_size=16, context_overlap=4, fuse_method="pyramid")
    assert patched.model_options["h3_context"]["h3_sliding_window_active"] is True

    ext = CosmicH3AutoregressiveFrameExtender()
    images = torch.rand((22, 64, 64, 3), dtype=torch.float32)
    # 124 frames on 17k+5 grid -> 37 H3 latent steps
    samples_dict, ref_imgs = ext.extend(
        vae=None,
        images=images,
        overlap_frames=5,
        noise_aug=0.0,
        latent_length=17,
        total_frames=124,
    )
    assert ref_imgs.shape[0] == 5
    assert samples_dict["samples"].shape[2] == 37
    assert samples_dict["noise_mask"].shape[2] == 37


def test_loop_seed_overflow_and_decode():
    """Verify cosmic_h3_loop handles unsigned 64-bit max seeds without overflow and decodes tuples."""
    called = {}
    def fake_executor(guider, sigmas, extra_args, callback, noise, *args, **kwargs):
        called["swap"] = extra_args["model_options"]["transformer_options"]["minimax_h3_loop_noise_swap"]
        return "ok"

    class _FakeGuider:
        class inner_model:
            latent_shapes = None

    noise = torch.ones((1, 24, 12, 4, 4))
    extra_args = {
        "seed": 0xFFFFFFFFFFFFFFFF,  # Max uint64 seed from ComfyUI
        "model_options": {"transformer_options": {"minimax_h3_loop_views": 1}},
    }
    res = loop_sampler_wrapper(fake_executor, _FakeGuider(), torch.tensor([1.0]), extra_args, None, noise)
    assert res == "ok"
    assert called["swap"].shape == noise.shape

    ctrl = MiniMaxH3LoopControlVideo()
    loop_in = torch.rand((24, 16, 16, 3))
    (built,) = ctrl.build(loop_in, fps=24.0, length=39, pad_clips=1, cycles=1)
    # length=39 -> loop=34, pad=17 -> range(-17, 34 + 17 + 5) = 73 frames
    assert built.shape == (73, 16, 16, 3)


def test_frame_calculator_and_forensics_and_validator():
    """Verify MiniMaxH3FrameCalculator, CosmicH3VideoForensics, and prompt grammar validator."""
    calc = MiniMaxH3FrameCalculator()
    frames, latent_t, audio_latent_t, duration_s, rem_s, clips_to_cover, summary = calc.calculate(
        seconds=5.0, fps=24, rounding="nearest"
    )
    assert frames == 124
    assert (frames - 5) % 17 == 0
    assert latent_t == 37
    assert audio_latent_t == 207
    assert "124" in summary

    forensics = CosmicH3VideoForensics()
    clip = torch.linspace(0.0, 1.0, 12 * 16 * 16 * 3).reshape(12, 16, 16, 3)
    evidence, sheet = forensics.measure(clip, fps=24.0)
    assert isinstance(evidence, str) and len(evidence) > 0
    assert isinstance(sheet, torch.Tensor) and sheet.ndim == 4

    raw_prompt = (
        "```text\nHere is the prompt:\n"
        "integrated_multimodal_description: [Shot 1] A samurai walks in rain. <d>[English] Hold the line.\n"
        "overall_soundscape: Heavy rain.\n"
        "non_diegetic_music: Slow strings.\n```"
    )
    fixed, notes = repair(raw_prompt)
    assert "```" not in fixed
    assert fixed.endswith("</d>")
    assert len(notes) >= 2
    issues = check(fixed, seconds=5.0, task="T2VA")
    # Missing (S1) speaker ID should be flagged by check()
    assert any("speaker ID" in msg for msg in issues)


def test_security_hardening_routes_and_providers():
    """Verify URL scheme validation in _providers and upload filename sanitization in h3_director_routes."""
    # SSRF / file:// scheme block
    assert _validate_http_url("http://127.0.0.1:11434/api/tags").startswith("http://")
    assert _validate_http_url("https://api.openai.com/v1/models").startswith("https://")
    for bad_url in ("file:///etc/passwd", "file:///C:/Windows/win.ini", "ftp://example.com/file", "javascript:alert(1)"):
        try:
            _validate_http_url(bad_url)
            assert False, f"Expected ProviderError for {bad_url}"
        except ProviderError:
            pass

    # Cross-platform upload filename sanitization & extension allowlist
    assert sanitize_upload_filename("song_track.wav") == "song_track.wav"
    assert sanitize_upload_filename(r"..\..\secret\clip.mp4") == "clip.mp4"
    assert sanitize_upload_filename("../../etc/audio.flac") == "audio.flac"
    assert sanitize_upload_filename("evil.py") is None
    assert sanitize_upload_filename("shell.bat") is None
    assert sanitize_upload_filename(".htaccess") is None
    assert sanitize_upload_filename("bad\x00.wav") is None


def test_all_registered_nodes_comfy_contract():
    """Verify all 37 registered nodes satisfy ComfyUI Registry and runtime schema contracts."""
    with _loaded_nodes_module() as studio_nodes:
        mappings = studio_nodes.NODE_CLASS_MAPPINGS
        display = studio_nodes.NODE_DISPLAY_NAME_MAPPINGS
        assert len(mappings) >= 37
        for key, cls in mappings.items():
            assert key in display, f"{key} missing from NODE_DISPLAY_NAME_MAPPINGS"
            assert hasattr(cls, "INPUT_TYPES") and callable(cls.INPUT_TYPES)
            schema = cls.INPUT_TYPES()
            assert isinstance(schema, dict) and "required" in schema
            assert hasattr(cls, "RETURN_TYPES") and isinstance(cls.RETURN_TYPES, tuple)
            assert hasattr(cls, "FUNCTION") and isinstance(cls.FUNCTION, str)
            assert hasattr(cls, cls.FUNCTION), f"{key} missing function {cls.FUNCTION}"
            assert hasattr(cls, "CATEGORY") and isinstance(cls.CATEGORY, str)

    # Verify JS dynamic models import path matches WEB_DIRECTORY = "./js"
    js_path = Path(__file__).resolve().parent.parent / "js" / "h3_dynamic_models.js"
    js_text = js_path.read_text(encoding="utf-8")
    assert '"../../scripts/app.js"' in js_text
    assert '"../../../scripts/app.js"' not in js_text
