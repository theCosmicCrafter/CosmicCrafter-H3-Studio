"""Regression checks for the H3 node family, ported from cosmic_nodes_v2.

These checks used to live in the cosmic repo's tests/test_fixes_D.py,
tests/test_area_vfx_post_video_regressions.py and
tests/test_area_video_legacy_regressions.py; they were deleted there
(c69e2912) when the H3 code moved to this repo as its single home. Each
check fails on the code as it was before the fix and passes after; the
one-line comment on each says what the old behaviour was.

Module mapping (old cosmic path -> this repo):
    vfx/video/cosmic_h3_context.py        -> cosmic_h3_context.py
    vfx/video/cosmic_h3_vram.py           -> cosmic_h3_vram.py
    vfx/video/cosmic_h3_advanced.py       -> cosmic_h3_advanced.py
    nodes/video/h3_prompt/cosmic_h3_prompt.py -> h3_prompt/cosmic_h3_prompt.py
    nodes/video/h3_prompt/_providers.py   -> h3_prompt/_providers.py

Adaptations for this repo's API drift:
  * CosmicH3OptimalBucketSelector gained frame_grid_mode; the default H3
    grid is 17k+5, so an 81-frame request snaps to 73. The old cosmic node
    snapped on 4k+1 where 81 was a bucket. The checks now verify the aspect
    mode leaves frame snapping alone (all modes agree) and use on-grid
    counts where an exact value matters.
  * The R&D prototypes were removed entirely here, not just unregistered:
    the check asserts the ids stay out of cosmic_h3_advanced's
    NODE_CLASS_MAPPINGS and out of nodes.py, which registers by direct
    class import and cannot be imported without a ComfyUI tree.

Runnable as a script (pytest is not required):
    python tests/test_h3_ported_regressions.py

Needs torch (the node files import it) but not a ComfyUI tree: every node
here is loaded straight from its file, the way the source tests did.
"""
import importlib.util
import inspect
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PACK = HERE.parent

try:
    import torch
except ImportError:  # pragma: no cover - environment dependent
    torch = None

FAILS = []


def check(label, cond):
    print(("  PASS  " if cond else "  FAIL  ") + label)
    if not cond:
        FAILS.append(label)


def _load(rel, name):
    path = PACK / rel
    if name in sys.modules:
        return sys.modules[name]
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    sys.modules[name] = m
    s.loader.exec_module(m)
    return m


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------
class _FakePatcher:
    def __init__(self):
        self.model_options = {}

    def clone(self):
        c = _FakePatcher()
        c.model_options = dict(self.model_options)
        return c


class _FakeVAE:
    def encode(self, images):
        b, h, w, c = images.shape
        t_lat = (b - 1) // 4 + 1 if b > 1 else 1
        return torch.zeros((1, 4, t_lat, max(1, h // 8), max(1, w // 8)))


class _FakeSampling:
    # an EPS-style range, the case that broke the cosine schedule
    sigma_min = 0.0292
    sigma_max = 14.6146


class _FakeInner:
    model_sampling = _FakeSampling()


class _FakeHookModel:
    def __init__(self, inner=None):
        self.model = inner
        self.post_cfg = []

    def clone(self):
        c = _FakeHookModel(self.model)
        return c

    def set_model_sampler_post_cfg_function(self, fn):
        self.post_cfg.append(fn)


class _FakeVideoVAE:
    """ComfyUI 0.35 shapes: decode((B,C,T,h,w)) -> (B, 4T-3, 8h, 8w, 3) channel-last in [0,1]."""

    def decode(self, lat):
        b, c, t, h, w = lat.shape
        out = torch.zeros(b, max(1, 4 * t - 3), h * 8, w * 8, 3)
        out[..., 0], out[..., 1], out[..., 2] = 0.25, 0.5, 0.75
        return out


# ---------------------------------------------------------------------------
# CosmicH3SlidingContextWindow / CosmicH3AutoregressiveFrameExtender
# ---------------------------------------------------------------------------
def test_sliding_window_dead_widgets_are_gone():
    print("\n=== sliding context window: blend_mode removed, fuse_method collapsed ===")
    if torch is None:
        print("  (torch not importable; skipping)")
        return
    mod = _load("cosmic_h3_context.py", "ported_h3_context")
    cls = mod.CosmicH3SlidingContextWindow
    it = cls.INPUT_TYPES()
    widgets = set(it["required"]) | set(it.get("optional", {}))
    # old: blend_mode was a widget stored in model_options and read by nothing
    check("blend_mode is no longer a widget", "blend_mode" not in widgets)
    check("patch() no longer takes blend_mode",
          "blend_mode" not in inspect.signature(cls.patch).parameters)
    opts, meta = it["required"]["fuse_method"]
    # old: weighted_mean and pyramid both mapped to the native PYRAMID fuse
    check("weighted_mean alias dropped from fuse_method", "weighted_mean" not in opts)
    check("pyramid is the fuse_method default", meta.get("default") == "pyramid")
    (patched,) = cls().patch(_FakePatcher(), 16, 4)
    cfg = patched.model_options["h3_context"]
    check("model_options no longer carries blend_mode", "blend_mode" not in cfg)
    check("default fuse recorded as pyramid", cfg["fuse_method"] == "pyramid")


def test_frame_extender_prev_latent_is_gone():
    print("\n=== autoregressive frame extender: prev_latent removed ===")
    if torch is None:
        print("  (torch not importable; skipping)")
        return
    mod = _load("cosmic_h3_context.py", "ported_h3_context")
    cls = mod.CosmicH3AutoregressiveFrameExtender
    it = cls.INPUT_TYPES()
    widgets = set(it["required"]) | set(it.get("optional", {}))
    # old: prev_latent was accepted and never read; the prefix always came from images
    check("prev_latent is no longer an input", "prev_latent" not in widgets)
    check("extend() no longer takes prev_latent",
          "prev_latent" not in inspect.signature(cls.extend).parameters)
    images = torch.rand((8, 32, 32, 3))
    lat, ref = cls().extend(_FakeVAE(), images, overlap_frames=4, latent_length=9)
    check("extender still builds the prefix from images",
          lat["samples"].shape == (1, 4, 9, 4, 4) and ref.shape[0] == 4)


def test_frame_extender_total_frames_zero_uses_latent_length():
    """total_frames is an always-present widget; 0 must let latent_length take effect."""
    print("\n=== autoregressive frame extender: total_frames=0 defers to latent_length ===")
    if torch is None:
        print("  (torch not importable; skipping)")
        return
    mod = _load("cosmic_h3_context.py", "ported_h3_context")
    opts = mod.CosmicH3AutoregressiveFrameExtender.INPUT_TYPES()["optional"]["total_frames"][1]
    check("total_frames defaults to 0 and allows 0", opts["default"] == 0 and opts["min"] == 0)

    class VAE:
        def encode(self, px):
            return torch.randn(1, 16, (px.shape[0] - 1) // 4 + 1, px.shape[1] // 8, px.shape[2] // 8)

    node = mod.CosmicH3AutoregressiveFrameExtender()
    lat, ref = node.extend(VAE(), torch.rand(8, 64, 96, 3), 4, 0.0, 33, total_frames=0)
    check("total_frames=0 honours latent_length=33",
          lat["samples"].shape[2] == 33)
    check("noise_mask covers the whole latent",
          lat["noise_mask"].shape == (1, 1, 33, 8, 12))
    lat, _ = node.extend(VAE(), torch.rand(8, 64, 96, 3), 4, 0.0, 33, total_frames=81)
    check("total_frames=81 wins over latent_length (81 -> 21 latent frames)",
          lat["samples"].shape[2] == 21)


def test_tiling_decoder_single_frame_is_bhwc():
    """A T=1 decode (B,1,H,W,3) used to be mistaken for (B,C,T,H,W) and permuted into (H,W,3,3)."""
    print("\n=== dynamic tiling decoder: single-frame output stays BHWC ===")
    if torch is None:
        print("  (torch not importable; skipping)")
        return
    mod = _load("cosmic_h3_vram.py", "ported_h3_vram")
    node = mod.CosmicH3DynamicTilingDecoder()
    for samples in (torch.randn(1, 4, 8, 12), torch.randn(1, 16, 1, 8, 12), torch.randn(1, 16, 2, 8, 12)):
        (out,) = node.decode(_FakeVideoVAE(), {"samples": samples}, 256, 256, 32, 16, 4)
        t = samples.shape[2] if samples.ndim == 5 else 1
        check(f"{tuple(samples.shape)} decodes to {(max(1, 4 * t - 3), 64, 96, 3)}",
              tuple(out.shape) == (max(1, 4 * t - 3), 64, 96, 3))
        check("...and keeps the decoded pixels (channel 1 == 0.5)",
              bool(torch.allclose(out[..., 1], torch.full_like(out[..., 1], 0.5))))


# ---------------------------------------------------------------------------
# CosmicH3AdaptiveNoiseRecoupling
# ---------------------------------------------------------------------------
def _hook(mod, schedule_mode, inner=_FakeInner()):
    node = mod.CosmicH3AdaptiveNoiseRecoupling()
    (m,) = node.patch(_FakeHookModel(inner), noise_strength=0.1, recouple_ratio=1.0,
                      decay_power=2.0, highpass_cutoff=0.1, lowpass_cutoff=0.8,
                      schedule_mode=schedule_mode)
    return m.post_cfg[0]


def _run(hook, sigma, seed=0):
    torch.manual_seed(seed)
    latent = torch.zeros((1, 4, 3, 16, 16))
    return hook({"denoised": torch.zeros_like(latent), "input": latent,
                 "sigma": torch.tensor([float(sigma)])})


def test_cosine_schedule_is_normalised_to_the_model_sigma_range():
    print("\n=== adaptive noise recoupling: cosine uses normalised sigma ===")
    if torch is None:
        print("  (torch not importable; skipping)")
        return
    mod = _load("cosmic_h3_advanced.py", "ported_h3_advanced")
    cos_hook = _hook(mod, "cosine")
    lin_hook = _hook(mod, "linear")

    # old: cos(14.6 * pi/2) = -0.62, so the first step got a large NEGATIVE dose of noise
    out = _run(cos_hook, _FakeSampling.sigma_max)
    check("at sigma_max the cosine schedule adds nothing (alpha = cos(pi/2) = 0)",
          torch.allclose(out, torch.zeros_like(out), atol=1e-6))

    # old: cos(2.0 * pi/2) = -1, the hook SUBTRACTED the noise the linear schedule adds
    out_cos = _run(cos_hook, 2.0)
    out_lin = _run(lin_hook, 2.0)
    check("linear schedule adds a non-zero noise (sanity)", float(out_lin.abs().max()) > 0)
    check("at sigma 2.0 the cosine schedule adds noise with the SAME sign as linear",
          float((out_cos * out_lin).sum()) > 0)
    expected = math.cos((2.0 - _FakeSampling.sigma_min)
                        / (_FakeSampling.sigma_max - _FakeSampling.sigma_min) * math.pi / 2)
    check("...scaled by cos of the normalised sigma",
          torch.allclose(out_cos, out_lin * expected, atol=1e-6))

    # old: alpha could go negative; it must now stay in [0, 1] across the whole range
    ok = True
    for s in (0.0292, 0.5, 1.0, 3.0, 7.0, 14.6146):
        oc, ol = _run(cos_hook, s), _run(lin_hook, s)
        ratio = float((oc * ol).sum() / (ol * ol).sum())
        ok = ok and -1e-6 <= ratio <= 1.0 + 1e-6
    check("alpha stays within [0, 1] over the model's sigma range", ok)


def test_cosine_schedule_without_a_sigma_range_assumes_unit_range():
    print("\n=== adaptive noise recoupling: no model_sampling -> [0, 1] ===")
    if torch is None:
        print("  (torch not importable; skipping)")
        return
    mod = _load("cosmic_h3_advanced.py", "ported_h3_advanced")
    hook = _hook(mod, "cosine", inner=None)
    out_hi = _run(hook, 1.0)
    out_lo = _run(hook, 0.0)
    check("sigma 1.0 adds nothing", torch.allclose(out_hi, torch.zeros_like(out_hi), atol=1e-6))
    check("sigma 0.0 adds the full dose", float(out_lo.abs().max()) > 0)
    # old: any sigma > 1 went negative: cos(2.0 * pi/2) = -1 and cos(1.5 * pi/2) = -0.707,
    # so the hook SUBTRACTED the full (or 0.707 of the) dose instead of adding nothing
    for s in (1.5, 2.0):
        out_over = _run(hook, s)
        check("sigma %.1f above the range clamps to alpha 0 rather than going negative" % s,
              torch.allclose(out_over, torch.zeros_like(out_over), atol=1e-6))


def test_optical_flow_hook_keeps_block_dtype():
    """float32 projection added to bf16 hidden states must not promote the block output."""
    print("\n=== optical flow motion bucket: block output keeps its dtype ===")
    if torch is None:
        print("  (torch not importable; skipping)")
        return
    mod = _load("cosmic_h3_advanced.py", "ported_h3_advanced")

    class Model:
        def __init__(self):
            self.patches = {}

        def clone(self):
            return self

        def set_model_patch_replace(self, patch, name, block, number):
            self.patches[(block, number)] = patch

    m = mod.CosmicH3OpticalFlowMotionBucket().patch(Model(), torch.rand(2, 64, 96, 3), 1.5, 127, "bilinear", "6")[0]
    hook = m.patches[("double_block", 6)]
    for dt in (torch.float32, torch.bfloat16):
        img = torch.randn(1, 2 * 8 * 12, 64, dtype=dt)
        res = hook({"img": img, "txt": None}, {"original_block": lambda a: a})
        check(f"block output keeps {dt}", res["img"].dtype == dt)


# ---------------------------------------------------------------------------
# CosmicH3Promptor seed / provider loudness
# ---------------------------------------------------------------------------
def _providers_module():
    """Load h3_prompt/_providers.py under the same module name the promptor's
    _sibling() loader uses, so every test here shares one module object."""
    return _load("h3_prompt/_providers.py", "h3_studio.h3_prompt._providers")


def _promptor():
    node_mod = _load("h3_prompt/cosmic_h3_prompt.py", "ported_h3_prompt")
    return node_mod, node_mod.providers


def _capture(prov, reply):
    seen = {}

    def fake_post(url, payload, headers):
        seen["url"], seen["payload"], seen["headers"] = url, payload, headers
        return reply
    prov._post = fake_post
    return seen


def test_provider_failure_is_loud_and_names_the_endpoint():
    """A dead provider must raise a clear ProviderError, not a TypeError and not "".

    The old fork's bug was a signature mismatch that surfaced as TypeError deep in
    an orchestrator. The rewrite takes `model` explicitly, so the equivalent risk
    is a silent empty prompt -- which would waste a whole render."""
    print("\n=== providers.generate: dead endpoints and empty models fail loudly ===")
    prov = _providers_module()
    sig = inspect.signature(prov.generate)
    for required in ("provider", "model", "system", "user"):
        check(f"generate() takes {required!r}", required in sig.parameters)

    # nothing listens on port 9
    try:
        prov.generate("lmstudio", "any-model", "sys", "hi",
                      endpoint="http://127.0.0.1:9")
        check("a dead endpoint raises ProviderError naming it", False)
    except prov.ProviderError as e:
        check("a dead endpoint raises ProviderError naming it", "127.0.0.1:9" in str(e))

    # an empty model name is caught before any socket is opened
    try:
        prov.generate("ollama", "   ", "sys", "hi")
        check("an empty model raises ProviderError 'no model selected'", False)
    except prov.ProviderError as e:
        check("an empty model raises ProviderError 'no model selected'",
              "no model selected" in str(e))

    # discovery degrades to [] rather than raising, so the node can still load
    check("list_models on a dead endpoint returns []",
          prov.list_models("lmstudio", endpoint="http://127.0.0.1:9") == [])


def test_seed_reaches_the_providers_that_take_one():
    print("\n=== providers.generate: seed is sent ===")
    if torch is None:
        print("  (torch not importable; skipping)")
        return
    node_mod, prov = _promptor()
    original_post = prov._post
    try:
        chat = {"choices": [{"message": {"content": "ok"}}]}
        for name in ("ollama", "lmstudio", "openai"):
            seen = _capture(prov, chat)
            # old: generate() had no seed parameter at all (TypeError)
            prov.generate(name, "m", "sys", "hi", api_key="k", seed=123)
            check(f"{name}: payload carries seed 123", seen["payload"].get("seed") == 123)
            seen = _capture(prov, chat)
            prov.generate(name, "m", "sys", "hi", api_key="k")
            check(f"{name}: no seed given -> no seed key", "seed" not in seen["payload"])

        seen = _capture(prov, {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})
        prov.generate("gemini", "m", "sys", "hi", api_key="k", seed=123)
        check("gemini: generationConfig.seed == 123",
              seen["payload"]["generationConfig"].get("seed") == 123)
        seen = _capture(prov, {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})
        prov.generate("gemini", "m", "sys", "hi", api_key="k", seed=2 ** 63 + 5)
        check("gemini: a 64-bit ComfyUI seed is folded into int32",
              0 <= seen["payload"]["generationConfig"]["seed"] < 2 ** 31)

        seen = _capture(prov, {"content": [{"type": "text", "text": "ok"}]})
        prov.generate("anthropic", "m", "sys", "hi", api_key="k", seed=123)
        check("anthropic: takes no seed, none sent", "seed" not in seen["payload"])
    finally:
        prov._post = original_post


def test_promptor_passes_its_seed_widget_through():
    print("\n=== CosmicH3Promptor.build: seed widget reaches generate ===")
    if torch is None:
        print("  (torch not importable; skipping)")
        return
    node_mod, prov = _promptor()
    original = prov.generate
    seen = {}

    def fake_generate(provider, model, system, user, **kw):
        seen.update(kw)
        return ("integrated_multimodal_description: [Shot 1] A cat sits.\n\n"
                "overall_soundscape: Room tone.\n\nnon_diegetic_music: None.")
    prov.generate = fake_generate
    try:
        node_mod.CosmicH3Promptor().build("a cat", "T2VA", 5.0, 1, "ollama", "m", seed=42)
        # old: build() used seed only as a cache-bust and never passed it on
        check("build() forwards seed=42 to providers.generate", seen.get("seed") == 42)
    finally:
        prov.generate = original


# ---------------------------------------------------------------------------
# CosmicH3OptimalBucketSelector.aspect_ratio_mode
# ---------------------------------------------------------------------------
def test_bucket_selector_aspect_ratio_mode_is_wired():
    print("\n=== optimal bucket selector: aspect_ratio_mode is read ===")
    if torch is None:
        print("  (torch not importable; skipping)")
        return
    mod = _load("cosmic_h3_vram.py", "ported_h3_vram")
    inst = mod.CosmicH3OptimalBucketSelector()
    # A 4:3 request sits exactly between the 1:1 and 16:9 buckets in aspect
    # cost, so only the mode decides which side it lands on.
    near = inst.select_bucket(1024, 768, 81, "nearest_bucket")
    crop = inst.select_bucket(1024, 768, 81, "crop_to_fit")
    pad = inst.select_bucket(1024, 768, 81, "pad_to_fit")
    # old: all three modes returned the identical nearest bucket and name
    check("crop_to_fit picks a bucket at least as wide as 4:3 (1280x720)", crop[:2] == (1280, 720))
    check("pad_to_fit picks a bucket no wider than 4:3 (1024x1024)", pad[:2] == (1024, 1024))
    check("nearest_bucket keeps its old answer", near[:2] == (1280, 720))
    check("nearest bucket_name carries no fit note", near[4] == "1280x720_16:9_landscape")
    check("crop keeps the bucket id as the prefix", crop[4].startswith("1280x720_16:9_landscape"))
    # 1024x768 scaled to width 1280 is 1280x960; 240 px of height go to reach 720
    check("crop reports the trim", "crop: scale to 1280x960, trim 240px height" in crop[4])
    # 1024x768 scaled to width 1024 is 1024x768; 256 px of height are added to reach 1024
    check("pad reports the add", "pad: scale to 1024x768, add 256px height" in pad[4])
    # This repo's default frame grid is 17k+5 (H3 native), where 81 snaps to 73;
    # the old cosmic node snapped on the 4k+1 grid where 81 was itself a bucket.
    # The check's intent stands: the aspect mode must not touch frame snapping.
    check("frame snapping is untouched by the mode",
          crop[2] == pad[2] == near[2] == 73)
    on_grid = inst.select_bucket(1024, 768, 90, "crop_to_fit")
    check("an on-grid frame count (90) stays exact", on_grid[2] == 90)


def test_bucket_selector_fit_modes_edge_cases():
    print("\n=== optimal bucket selector: exact fit and no-candidate fallback ===")
    if torch is None:
        print("  (torch not importable; skipping)")
        return
    mod = _load("cosmic_h3_vram.py", "ported_h3_vram")
    inst = mod.CosmicH3OptimalBucketSelector()
    for mode in ("crop_to_fit", "pad_to_fit"):
        w, h, f, aspect, name = inst.select_bucket(1920, 1080, 90, mode)
        check(f"{mode}: an exact 16:9 request stays 1920x1080", (w, h, f) == (1920, 1080, 90))
        check(f"{mode}: exact fit is reported, nothing to trim or add", "exact fit" in name)
    # 15:1 is wider than every bucket, so crop_to_fit has no candidate
    w, h, f, aspect, name = inst.select_bucket(3000, 200, 90, "crop_to_fit")
    check("crop_to_fit with no wider bucket falls back to a valid bucket", w > 0 and h > 0 and w >= h)
    check("...and says so in bucket_name", "no qualifying bucket" in name)
    # 1:100 is narrower than every bucket, so pad_to_fit has no candidate
    w, h, f, aspect, name = inst.select_bucket(100, 10000, 90, "pad_to_fit")
    check("pad_to_fit with no narrower bucket falls back to a valid bucket", w > 0 and h > 0 and h >= w)
    check("...and says so in bucket_name", "no qualifying bucket" in name)


# ---------------------------------------------------------------------------
# Registration guard
# ---------------------------------------------------------------------------
def test_h3_prototypes_stay_unregistered():
    print("\n=== h3 advanced: R&D prototypes stay unregistered ===")
    if torch is None:
        print("  (torch not importable; skipping)")
        return
    mod = _load("cosmic_h3_advanced.py", "ported_h3_advanced_reg")
    # old cosmic check read this module's NODE_CLASS_MAPPINGS; the prototypes
    # were compiled-in but commented out of the map. In this repo they were
    # deleted outright, so the ids must also stay out of nodes.py, which
    # registers classes by direct import and cannot be imported here.
    ncm = getattr(mod, "NODE_CLASS_MAPPINGS", {})
    check("CosmicH3TemporalAttentionSharpening not in cosmic_h3_advanced mappings",
          "CosmicH3TemporalAttentionSharpening" not in ncm)
    check("CosmicH3MultiPromptCameraSteering not in cosmic_h3_advanced mappings",
          "CosmicH3MultiPromptCameraSteering" not in ncm)
    nodes_src = (PACK / "nodes.py").read_text(encoding="utf-8")
    check("nodes.py does not register the prototypes either",
          "CosmicH3TemporalAttentionSharpening" not in nodes_src
          and "CosmicH3MultiPromptCameraSteering" not in nodes_src)


TESTS = [
    test_sliding_window_dead_widgets_are_gone,
    test_frame_extender_prev_latent_is_gone,
    test_frame_extender_total_frames_zero_uses_latent_length,
    test_tiling_decoder_single_frame_is_bhwc,
    test_cosine_schedule_is_normalised_to_the_model_sigma_range,
    test_cosine_schedule_without_a_sigma_range_assumes_unit_range,
    test_optical_flow_hook_keeps_block_dtype,
    test_provider_failure_is_loud_and_names_the_endpoint,
    test_seed_reaches_the_providers_that_take_one,
    test_promptor_passes_its_seed_widget_through,
    test_bucket_selector_aspect_ratio_mode_is_wired,
    test_bucket_selector_fit_modes_edge_cases,
    test_h3_prototypes_stay_unregistered,
]

if __name__ == "__main__":
    import traceback

    for fn in TESTS:
        before = len(FAILS)
        try:
            fn()
        except Exception:  # one crash must not hide the tests after it
            tb = traceback.format_exc().strip().splitlines()
            print(f"  FAIL  {fn.__name__} crashed: {tb[-1]}")
            for line in tb[-6:-1]:
                print("        " + line)
            FAILS.append(f"{fn.__name__} (crashed)")
        print(("PASS " if len(FAILS) == before else "FAIL ") + fn.__name__)
    print()
    if FAILS:
        print(f"{len(FAILS)} check(s) failed:")
        for f in FAILS:
            print("  - " + f)
        sys.exit(1)
    print("all ported H3 regression checks passed")
