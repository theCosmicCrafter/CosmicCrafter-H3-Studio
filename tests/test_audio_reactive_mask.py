"""CPU-only tests for the native audio-reactive masking suite."""

import torch

from h3_audio_reactive_mask import (
    FRAME_PER_TOKEN,
    MASK_OPERATIONS,
    SPATIAL_MODES,
    MiniMaxH3AudioCurveToMask,
    MiniMaxH3LatentNoiseMask,
    MiniMaxH3MaskComposite,
    aggregate_frames,
    attach_noise_mask,
    audio_latent_t,
    audio_latent_windows,
    build_audio_noise_mask,
    build_video_noise_mask,
    curve_to_tensor,
    feather_mask,
    frames_from_video_latent,
    latent_frame_windows,
    match_frames,
    normalize_mask,
    pixel_frames,
    snap_to_token_grid,
    TOKEN_GRID,
    MiniMaxH3SourceToLatent,
    fit_frames,
    encode_video_frames,
    replace_video_stream,
    render_curve_mask,
    resize_mask,
    shape_curve,
    split_av_latent,
    video_latent_t,
)

FRAME_CASES = [5, 22, 39, 124, 192, 362]


def _av_latent(frames=124, height=48, width=84, batch=1):
    """Build an H3-shaped AV latent dict without needing ComfyUI."""
    latent_t = video_latent_t(frames)
    video = torch.zeros(batch, 24, latent_t, height, width)
    audio = torch.zeros(batch, 32, 2, audio_latent_t(frames))
    return {"samples": _Nested((video, audio))}, video, audio


class _Nested:
    """Minimal stand-in for comfy.nested_tensor.NestedTensor."""

    def __init__(self, tensors):
        self.tensors = list(tensors)
        self.is_nested = True

    def unbind(self):
        return self.tensors


# ---------------------------------------------------------------------------
# Temporal geometry
# ---------------------------------------------------------------------------

def test_latent_length_matches_h3_grid():
    # Mirrors comfy_extras/nodes_minimax_h3.video_latent_t exactly.
    for frames in FRAME_CASES:
        expected = 2 if frames <= 5 else ((frames - 5) // 17) * 5 + 2
        assert video_latent_t(frames) == expected


def test_pixel_frames_inverts_latent_length():
    for frames in FRAME_CASES:
        assert pixel_frames(video_latent_t(frames)) == frames


def test_frames_recovered_from_video_latent():
    for frames in FRAME_CASES:
        video = torch.zeros(1, 24, video_latent_t(frames), 4, 4)
        assert frames_from_video_latent(video) == frames


def test_latent_windows_tile_every_source_frame_exactly_once():
    for frames in FRAME_CASES:
        latent_t = video_latent_t(frames)
        windows = latent_frame_windows(frames, latent_t)
        assert len(windows) == latent_t

        covered = []
        for lo, hi in windows:
            covered.extend(range(lo, hi))
        # A partition: every frame covered, none twice.
        assert sorted(covered) == list(range(frames))


def test_latent_windows_follow_h3_token_spans():
    frames = 124
    windows = latent_frame_windows(frames, video_latent_t(frames))
    spans = [hi - lo for lo, hi in windows]
    for index, span in enumerate(spans):
        assert span == FRAME_PER_TOKEN[index % 5]


def test_audio_windows_cover_the_clip():
    frames = 124
    audio_t = audio_latent_t(frames)
    windows = audio_latent_windows(audio_t, frames)
    assert len(windows) == audio_t
    assert windows[0][0] == 0
    assert max(hi for _lo, hi in windows) <= frames
    assert all(hi > lo for lo, hi in windows)


# ---------------------------------------------------------------------------
# The core claim: aggregation preserves transients that interpolation loses
# ---------------------------------------------------------------------------

def _stock_reshape_mask(input_mask, output_shape):
    """Reimplementation of comfy.utils.reshape_mask (3-D path) for comparison."""
    if len(input_mask.shape) < 5:
        input_mask = input_mask.reshape(
            (1, 1, -1, input_mask.shape[-2], input_mask.shape[-1])
        )
    return torch.nn.functional.interpolate(
        input_mask, size=output_shape[2:], mode="trilinear"
    )


def test_single_frame_beats_survive_latent_compression():
    frames = 124
    latent_t = video_latent_t(frames)

    curve = torch.zeros(frames)
    curve[::12] = 1.0  # 11 one-frame transients
    mask = render_curve_mask(curve, 64, 64, "uniform")
    video = torch.zeros(1, 24, latent_t, 4, 4)

    ours = build_video_noise_mask(mask, video, temporal_aggregate="max")
    profile = ours[0, 0].amax(dim=(1, 2))

    # Every beat reaches the latent at full amplitude.
    assert int((profile >= 0.99).sum()) == int((curve >= 0.99).sum())

    # And that is strictly better than what trilinear interpolation manages.
    stock = _stock_reshape_mask(
        mask.reshape((-1, 1, 64, 64)), (1, 24, latent_t, 4, 4)
    )
    stock_profile = stock[0, 0].amax(dim=(1, 2))
    assert int((stock_profile >= 0.99).sum()) < int((profile >= 0.99).sum())


def test_aggregate_modes_bracket_each_other():
    values = torch.tensor([[0.0], [1.0], [0.0], [0.0]])
    windows = [(0, 4)]
    assert float(aggregate_frames(values, windows, "max")[0, 0]) == 1.0
    assert float(aggregate_frames(values, windows, "min")[0, 0]) == 0.0
    assert abs(float(aggregate_frames(values, windows, "mean")[0, 0]) - 0.25) < 1e-6


def test_mean_aggregate_smooths_where_max_preserves():
    frames = 124
    latent_t = video_latent_t(frames)
    curve = torch.zeros(frames)
    curve[::12] = 1.0
    mask = render_curve_mask(curve, 32, 32, "uniform")
    video = torch.zeros(1, 24, latent_t, 2, 2)

    peaked = build_video_noise_mask(mask, video, temporal_aggregate="max")
    smoothed = build_video_noise_mask(mask, video, temporal_aggregate="mean")

    # Compare how many latent frames keep full amplitude rather than the peak
    # itself: H3's first token of each group spans a single frame, so max and
    # mean necessarily agree there.
    peaked_hits = int((peaked[0, 0].amax(dim=(1, 2)) >= 0.99).sum())
    smoothed_hits = int((smoothed[0, 0].amax(dim=(1, 2)) >= 0.99).sum())
    assert peaked_hits > smoothed_hits


# ---------------------------------------------------------------------------
# Curve shaping
# ---------------------------------------------------------------------------

def test_curve_to_tensor_accepts_list_scalar_and_tensor():
    assert curve_to_tensor([0.0, 1.0], 2).tolist() == [0.0, 1.0]
    assert curve_to_tensor(0.5, 3).tolist() == [0.5, 0.5, 0.5]
    assert curve_to_tensor(torch.tensor([1.0, 0.0]), 2).tolist() == [1.0, 0.0]


def test_curve_to_tensor_resamples_mismatched_length():
    out = curve_to_tensor([0.0, 1.0], 5)
    assert out.numel() == 5
    assert out[0] == 0.0 and out[-1] == 1.0


def test_curve_to_tensor_rejects_non_numeric():
    try:
        curve_to_tensor(["loud"], 4)
    except ValueError:
        return
    raise AssertionError("expected ValueError for a non-numeric curve")


def test_threshold_gates_quiet_frames_but_keeps_peaks_full():
    values = torch.tensor([0.1, 0.5, 1.0])
    out = shape_curve(values, threshold=0.4)
    assert float(out[0]) == 0.0
    assert abs(float(out[2]) - 1.0) < 1e-6  # peak is not dimmed by gating


def test_floor_and_ceiling_bound_the_output():
    out = shape_curve(torch.tensor([0.0, 1.0]), floor=0.2, ceiling=0.8)
    assert abs(float(out[0]) - 0.2) < 1e-6
    assert abs(float(out[1]) - 0.8) < 1e-6


def test_invert_flips_the_curve():
    out = shape_curve(torch.tensor([0.0, 1.0]), invert=True)
    assert out.tolist() == [1.0, 0.0]


# ---------------------------------------------------------------------------
# Spatial rendering
# ---------------------------------------------------------------------------

def test_every_spatial_mode_renders_in_range():
    curve = torch.rand(11)
    for mode in SPATIAL_MODES:
        mask = render_curve_mask(curve, 40, 24, spatial_mode=mode)
        assert mask.shape == (11, 24, 40), mode
        assert float(mask.min()) >= 0.0 and float(mask.max()) <= 1.0, mode


def test_unknown_spatial_mode_is_rejected():
    try:
        render_curve_mask(torch.zeros(2), 8, 8, spatial_mode="disco")
    except ValueError:
        return
    raise AssertionError("expected ValueError for an unknown spatial mode")


def test_uniform_mode_tracks_the_curve_value():
    curve = torch.tensor([0.0, 0.5, 1.0])
    mask = render_curve_mask(curve, 8, 8, "uniform")
    assert abs(float(mask[1].mean()) - 0.5) < 1e-6


# ---------------------------------------------------------------------------
# Mask utilities
# ---------------------------------------------------------------------------

def test_normalize_mask_accepts_2d_3d_and_4d():
    assert normalize_mask(torch.zeros(8, 8)).shape == (1, 8, 8)
    assert normalize_mask(torch.zeros(3, 8, 8)).shape == (3, 8, 8)
    assert normalize_mask(torch.zeros(3, 1, 8, 8)).shape == (3, 8, 8)


def test_still_subject_mask_is_repeated_not_interpolated():
    subject = torch.zeros(1, 4, 4)
    subject[0, 1, 1] = 1.0
    out = match_frames(subject, 7)
    assert out.shape == (7, 4, 4)
    # Every frame identical: a still subject must not drift or fade.
    for frame in range(7):
        assert torch.equal(out[frame], subject[0])


def test_resize_mask_changes_resolution_only():
    out = resize_mask(torch.ones(3, 8, 8), 16, 16)
    assert out.shape == (3, 16, 16)


def test_feather_blurs_a_hard_edge():
    mask = torch.zeros(1, 9, 9)
    mask[0, 4, 4] = 1.0
    out = feather_mask(mask, 1)
    assert float(out[0, 4, 4]) < 1.0
    assert float(out[0, 3, 4]) > 0.0


def test_feather_zero_is_a_noop():
    mask = torch.rand(2, 6, 6)
    assert torch.equal(feather_mask(mask, 0), mask)


# ---------------------------------------------------------------------------
# Compositing
# ---------------------------------------------------------------------------

def test_composite_confines_pulse_to_background():
    node = MiniMaxH3MaskComposite()
    subject = torch.zeros(1, 4, 4)
    subject[0, :2, :] = 1.0          # subject occupies the top half
    pulse = torch.ones(6, 4, 4)      # full-frame pulse

    out, = node.composite(subject, operation="multiply", invert_a=True, mask_b=pulse)
    assert out.shape == (6, 4, 4)
    # Subject region locked off, background fully live.
    assert float(out[:, :2, :].max()) == 0.0
    assert float(out[:, 2:, :].min()) == 1.0


def test_every_composite_operation_stays_in_range():
    node = MiniMaxH3MaskComposite()
    a = torch.rand(2, 4, 4)
    b = torch.rand(2, 4, 4)
    for op in MASK_OPERATIONS:
        out, = node.composite(a, operation=op, mask_b=b)
        assert float(out.min()) >= 0.0 and float(out.max()) <= 1.0, op


def test_composite_without_second_mask_passes_through():
    node = MiniMaxH3MaskComposite()
    a = torch.rand(3, 4, 4)
    out, = node.composite(a, operation="multiply")
    assert torch.allclose(out, a, atol=1e-6)


def test_composite_aligns_mismatched_frames_and_resolution():
    node = MiniMaxH3MaskComposite()
    a = torch.ones(1, 4, 4)
    b = torch.ones(5, 8, 8)
    out, = node.composite(a, operation="multiply", mask_b=b)
    assert out.shape == (5, 8, 8)


def test_gain_and_offset_are_clamped():
    node = MiniMaxH3MaskComposite()
    out, = node.composite(torch.full((1, 2, 2), 0.5), gain=10.0)
    assert float(out.max()) == 1.0
    out, = node.composite(torch.full((1, 2, 2), 0.5), gain=0.0, offset=-1.0)
    assert float(out.min()) == 0.0


# ---------------------------------------------------------------------------
# Latent noise masking
# ---------------------------------------------------------------------------

def test_video_mask_matches_latent_shape_exactly():
    # Exact shape means the sampler's reshape_mask becomes a no-op, so the
    # aggregation done here is what actually reaches the denoiser.
    _latent, video, _audio = _av_latent(frames=124, height=48, width=84)
    mask = torch.ones(124, 768, 1344)
    out = build_video_noise_mask(mask, video)
    assert out.shape == (1, 1, video.shape[2], 48, 84)


def test_audio_mask_matches_latent_shape_exactly():
    _latent, _video, audio = _av_latent(frames=124)
    out = build_audio_noise_mask(audio, value=1.0)
    assert out.shape == (1, 1, 2, audio.shape[3])
    assert float(out.min()) == 1.0


def test_audio_mask_follows_a_curve():
    _latent, _video, audio = _av_latent(frames=124)
    curve = [0.0] * 62 + [1.0] * 62
    out = build_audio_noise_mask(audio, curve=curve, frame_count=124)
    assert float(out[0, 0, 0, 0]) == 0.0
    assert float(out[0, 0, 0, -1]) == 1.0


def test_strength_zero_disables_the_mask():
    _latent, video, _audio = _av_latent(frames=39)
    mask = torch.zeros(39, 64, 64)  # would freeze everything
    out = build_video_noise_mask(mask, video, strength=0.0)
    assert float(out.min()) == 1.0  # fully denoised, i.e. mask disabled


def test_strength_blends_toward_full_denoise():
    _latent, video, _audio = _av_latent(frames=39)
    mask = torch.zeros(39, 64, 64)
    out = build_video_noise_mask(mask, video, strength=0.5)
    assert abs(float(out.max()) - 0.5) < 1e-6


def test_batched_latent_gets_batched_mask():
    _latent, video, audio = _av_latent(frames=39, batch=3)
    assert build_video_noise_mask(torch.ones(39, 32, 32), video).shape[0] == 3
    assert build_audio_noise_mask(audio).shape[0] == 3


def test_split_av_latent_handles_video_only():
    video, audio = split_av_latent({"samples": torch.zeros(1, 24, 12, 4, 4)})
    assert audio is None
    assert video.shape[2] == 12


def test_split_av_latent_rejects_non_latent():
    for bad in ({}, {"samples": "nope"}, None):
        try:
            split_av_latent(bad)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {bad!r}")


def test_attach_noise_mask_without_audio_uses_plain_tensor():
    latent = {"samples": torch.zeros(1, 24, 12, 4, 4)}
    out = attach_noise_mask(latent, torch.ones(1, 1, 12, 4, 4))
    assert isinstance(out["noise_mask"], torch.Tensor)
    assert "noise_mask" not in latent  # original untouched


def test_node_apply_returns_latent_and_preview():
    node = MiniMaxH3LatentNoiseMask()
    latent, video, _audio = _av_latent(frames=39, height=8, width=8)
    mask = torch.ones(39, 64, 64)

    out, preview = node.apply(latent, mask, audio_mode="denoise")
    assert "noise_mask" in out
    assert preview.shape == (video.shape[2], 8, 8)


def test_follow_curve_without_curve_is_rejected():
    node = MiniMaxH3LatentNoiseMask()
    latent, _video, _audio = _av_latent(frames=39, height=8, width=8)
    try:
        node.apply(latent, torch.ones(39, 8, 8), audio_mode="follow_curve")
    except ValueError:
        return
    raise AssertionError("expected ValueError when follow_curve has no curve")


def test_preserve_mode_freezes_the_audio_stream():
    _latent, _video, audio = _av_latent(frames=39)
    out = build_audio_noise_mask(audio, value=0.0)
    assert float(out.max()) == 0.0


def test_curve_to_mask_node_end_to_end():
    node = MiniMaxH3AudioCurveToMask()
    curve = [0.0, 0.5, 1.0, 0.25]
    mask, shaped = node.render(curve, width=32, height=16, frames=4,
                               spatial_mode="uniform")
    assert mask.shape == (4, 16, 32)
    assert len(shaped) == 4
    assert abs(shaped[2] - 1.0) < 1e-6


def test_curve_to_mask_node_resamples_to_frame_count():
    node = MiniMaxH3AudioCurveToMask()
    mask, shaped = node.render([0.0, 1.0], width=8, height=8, frames=10)
    assert mask.shape[0] == 10
    assert len(shaped) == 10


def test_full_chain_subject_plus_beats_into_latent():
    """SAM subject -> invert -> multiply by beat pulse -> H3 latent mask."""
    frames = 124
    latent, video, audio = _av_latent(frames=frames, height=12, width=12)

    subject = torch.zeros(1, 96, 96)
    subject[0, 20:60, 20:60] = 1.0

    beats = torch.zeros(frames)
    beats[::12] = 1.0

    pulse, _ = MiniMaxH3AudioCurveToMask().render(
        beats.tolist(), width=96, height=96, frames=frames, spatial_mode="uniform",
    )
    combined, = MiniMaxH3MaskComposite().composite(
        subject, operation="multiply", invert_a=True, mask_b=pulse,
    )
    out, preview = MiniMaxH3LatentNoiseMask().apply(
        latent, combined, temporal_aggregate="max", audio_mode="preserve",
    )

    assert combined.shape == (frames, 96, 96)
    assert preview.shape == (video.shape[2], 12, 12)
    # The subject's interior stays locked at every latent frame.  Only whole
    # 2x2 token blocks are tested: with max snapping a block straddling the
    # subject edge resolves to "denoise", which is the conservative choice and
    # is covered by test_token_snapping_grows_the_subject_edge below.
    subject_interior = preview[:, 4:6, 4:6]
    assert float(subject_interior.max()) == 0.0
    # ...while the background still pulses to the beat.
    assert float(preview.max()) == 1.0
    assert "noise_mask" in out


def test_token_snapping_grows_the_subject_edge_with_max():
    """max snapping errs toward denoising, so a block straddling the subject
    edge is regenerated.  Use min (or feather the composite) when the subject
    boundary must be protected instead."""
    _latent, video, _audio = _av_latent(frames=39, height=8, width=8)

    background = torch.ones(39, 128, 128)
    background[:, :, :48] = 0.0        # locked region ends mid-token

    grown = build_video_noise_mask(background, video, temporal_aggregate="max")
    kept = build_video_noise_mask(background, video, temporal_aggregate="min")

    # max lets the live region claim the straddling block; min hands it to the
    # locked region, so the locked area is strictly larger.
    assert float((kept[0, 0] == 0).sum()) > float((grown[0, 0] == 0).sum())


# ---------------------------------------------------------------------------
# DiT token grid
# ---------------------------------------------------------------------------

def test_token_grid_matches_h3_patch_size():
    # comfy/ldm/minimax/model.py: patchify_video(latent, patch_size=(1, 2, 2))
    assert TOKEN_GRID == 2


def test_snapping_makes_every_token_block_uniform():
    mask = torch.zeros(1, 8, 8)
    mask[0, :, :3] = 1.0  # edge lands mid-token at latent column 3

    snapped = snap_to_token_grid(mask, 2, "max")
    blocks = snapped[0].reshape(4, 2, 4, 2).permute(0, 2, 1, 3).reshape(-1, 4)
    for block in blocks:
        assert len(set(block.tolist())) == 1, "a 2x2 token block is not uniform"


def test_snapping_max_grows_a_partial_block_to_the_whole_token():
    mask = torch.zeros(1, 4, 4)
    mask[0, 0, 0] = 1.0
    snapped = snap_to_token_grid(mask, 2, "max")
    assert snapped[0, :2, :2].min() == 1.0   # the whole token lights up
    assert snapped[0, 2:, 2:].max() == 0.0   # neighbours untouched


def test_snapping_min_drops_a_partial_block():
    mask = torch.zeros(1, 4, 4)
    mask[0, 0, 0] = 1.0
    snapped = snap_to_token_grid(mask, 2, "min")
    assert float(snapped.max()) == 0.0


def test_token_grid_of_one_is_a_noop():
    mask = torch.rand(2, 6, 6)
    assert torch.equal(snap_to_token_grid(mask, 1), mask)


def test_snapping_preserves_shape_on_odd_dimensions():
    # Replicate padding keeps the border block instead of fading it to zero.
    mask = torch.ones(3, 5, 7)
    snapped = snap_to_token_grid(mask, 2, "max")
    assert snapped.shape == (3, 5, 7)
    assert float(snapped.min()) == 1.0


def test_latent_mask_is_token_aligned_by_default():
    _latent, video, _audio = _av_latent(frames=39, height=8, width=8)
    mask = torch.zeros(39, 128, 128)
    mask[:, :, :48] = 1.0  # 48/128 * 8 = 3 latent columns -> odd, must snap

    out = build_video_noise_mask(mask, video)
    frame = out[0, 0, 0]
    blocks = frame.reshape(4, 2, 4, 2).permute(0, 2, 1, 3).reshape(-1, 4)
    for block in blocks:
        assert len(set(block.tolist())) == 1


def test_token_alignment_can_be_disabled():
    _latent, video, _audio = _av_latent(frames=39, height=8, width=8)
    mask = torch.zeros(39, 128, 128)
    mask[:, :, :48] = 1.0

    aligned = build_video_noise_mask(mask, video, token_grid=2)
    raw = build_video_noise_mask(mask, video, token_grid=1)
    assert not torch.equal(aligned, raw)


def test_snapping_does_not_cost_beat_transients():
    frames = 124
    latent_t = video_latent_t(frames)
    curve = torch.zeros(frames)
    curve[::12] = 1.0
    mask = render_curve_mask(curve, 64, 64, "uniform")
    video = torch.zeros(1, 24, latent_t, 4, 4)

    out = build_video_noise_mask(mask, video, temporal_aggregate="max")
    profile = out[0, 0].amax(dim=(1, 2))
    assert int((profile >= 0.99).sum()) == int((curve >= 0.99).sum())


# ---------------------------------------------------------------------------
# Source content: a mask can only preserve what the latent already holds
# ---------------------------------------------------------------------------

class _VideoVAE:
    """Encodes [B,H,W,C] pixels to an H3-shaped video latent."""

    def __init__(self, latent_t, lat_h, lat_w):
        self.latent_t, self.lat_h, self.lat_w = latent_t, lat_h, lat_w
        self.seen = None

    def encode(self, pixels):
        self.seen = tuple(pixels.shape)
        # Carry the mean pixel value through so tests can prove content landed.
        value = float(pixels.mean())
        return torch.full((1, 24, self.latent_t, self.lat_h, self.lat_w), value)


def test_fit_frames_repeats_a_still():
    still = torch.rand(1, 8, 8, 3)
    out = fit_frames(still, 5)
    assert out.shape == (5, 8, 8, 3)
    for i in range(5):
        assert torch.equal(out[i], still[0])


def test_fit_frames_resamples_a_clip():
    clip = torch.rand(10, 4, 4, 3)
    assert fit_frames(clip, 4).shape == (4, 4, 4, 3)
    assert fit_frames(clip, 20).shape == (20, 4, 4, 3)


def test_fit_frames_passes_through_exact_length():
    clip = torch.rand(7, 4, 4, 3)
    assert torch.equal(fit_frames(clip, 7), clip)


def test_fit_frames_rejects_non_image():
    try:
        fit_frames(torch.zeros(4, 4), 3)
    except ValueError:
        return
    raise AssertionError("expected ValueError for a non-IMAGE tensor")


def test_replace_video_stream_keeps_audio():
    latent, video, audio = _av_latent(frames=39, height=4, width=4)
    new_video = torch.ones_like(video)
    out = replace_video_stream(latent, new_video)

    out_video, out_audio = split_av_latent(out)
    assert torch.equal(out_video, new_video)
    assert out_audio is audio          # audio stream untouched
    assert latent["samples"].unbind()[0] is video  # original not mutated


def test_source_to_latent_fills_the_video_stream():
    """The bug this node exists for: an empty latent gives the mask nothing to
    preserve, so the 'locked' subject decodes to blank latent space."""
    latent, video, _audio = _av_latent(frames=39, height=4, width=4)
    assert float(video.abs().max()) == 0.0   # ImageToVideo hands back zeros

    vae = _VideoVAE(video.shape[2], 4, 4)
    still = torch.full((1, 128, 128, 3), 0.5)

    out, = MiniMaxH3SourceToLatent().apply(latent, vae, still)
    out_video, _ = split_av_latent(out)

    assert out_video.shape == video.shape
    assert float(out_video.abs().max()) > 0.0   # now it holds real content


def test_source_to_latent_encodes_the_full_clip_at_canvas_size():
    latent, video, _audio = _av_latent(frames=39, height=6, width=10)
    vae = _VideoVAE(video.shape[2], 6, 10)

    MiniMaxH3SourceToLatent().apply(latent, vae, torch.rand(1, 64, 64, 3))

    frames, height, width, channels = vae.seen
    assert frames == frames_from_video_latent(video)   # every frame encoded
    assert (height, width) == (6 * 16, 10 * 16)        # at the latent canvas
    assert channels == 3


def test_source_to_latent_rejects_a_latent_length_mismatch():
    latent, video, _audio = _av_latent(frames=39, height=4, width=4)
    wrong = _VideoVAE(video.shape[2] + 1, 4, 4)
    try:
        MiniMaxH3SourceToLatent().apply(latent, wrong, torch.rand(1, 32, 32, 3))
    except RuntimeError:
        return
    raise AssertionError("expected RuntimeError on a latent-length mismatch")


def test_source_to_latent_rejects_a_resolution_mismatch():
    latent, video, _audio = _av_latent(frames=39, height=4, width=4)
    wrong = _VideoVAE(video.shape[2], 8, 8)
    try:
        MiniMaxH3SourceToLatent().apply(latent, wrong, torch.rand(1, 32, 32, 3))
    except RuntimeError:
        return
    raise AssertionError("expected RuntimeError on a resolution mismatch")


def test_masked_region_holds_the_source_after_filling():
    """End to end: fill the latent, then lock the subject. The locked region
    must carry the encoded source rather than zeros."""
    latent, video, _audio = _av_latent(frames=39, height=4, width=4)
    vae = _VideoVAE(video.shape[2], 4, 4)

    filled, = MiniMaxH3SourceToLatent().apply(
        latent, vae, torch.full((1, 64, 64, 3), 0.7),
    )
    filled_video, _ = split_av_latent(filled)

    subject = torch.zeros(1, 64, 64)
    subject[0, 16:48, 16:48] = 1.0
    combined, = MiniMaxH3MaskComposite().composite(subject, invert_a=True)
    out, _preview = MiniMaxH3LatentNoiseMask().apply(filled, combined)

    # The latent the sampler restores toward is real content, not zeros.
    assert float(filled_video.abs().max()) > 0.0
    assert "noise_mask" in out


class _StockVAE:
    """A VAE mock with ComfyUI's real process_input / vae_dtype contract."""

    def __init__(self, dtype=torch.float16):
        self.vae_dtype = dtype
        self.process_input = lambda image: image * 2.0 - 1.0
        self.received = None

    def encode(self, pixels):
        # Mirror sd.py: normalize, then cast to the working dtype.
        self.received = self.process_input(pixels).to(self.vae_dtype).clone()
        return torch.zeros(1, 24, 2, 1, 1)


def test_encode_video_frames_matches_the_monolithic_normalization():
    """The chunked path must hand the model the same numbers sd.py would."""
    pixels = torch.rand(39, 8, 8, 3)

    reference = _StockVAE()
    reference.encode(pixels)

    chunked = _StockVAE()
    encode_video_frames(chunked, pixels, chunk=17)

    assert chunked.received.dtype == reference.received.dtype
    assert torch.equal(chunked.received, reference.received)


def test_encode_video_frames_does_not_write_to_its_source():
    """fit_frames hands us a zero-stride broadcast view for a still; writing
    through it would corrupt every frame at once."""
    still = torch.rand(1, 8, 8, 3)
    before = still.clone()
    view = fit_frames(still, 39)

    encode_video_frames(_StockVAE(), view, chunk=17)

    assert torch.equal(still, before)


def test_encode_video_frames_handles_a_ragged_final_chunk():
    pixels = torch.rand(20, 4, 4, 3)  # 17 + 3
    reference, chunked = _StockVAE(), _StockVAE()
    reference.encode(pixels)
    encode_video_frames(chunked, pixels, chunk=17)
    assert torch.equal(chunked.received, reference.received)


def test_encode_video_frames_restores_process_input_after_a_failure():
    vae = _StockVAE()
    original = vae.process_input

    def boom(pixels):
        raise RuntimeError("encode failed")

    vae.encode = boom
    try:
        encode_video_frames(vae, torch.rand(5, 4, 4, 3))
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected the encode failure to propagate")

    assert vae.process_input is original


def test_encode_video_frames_falls_back_for_a_nonstandard_process_input():
    """A VAE that does not use x*2-1 must not be handed pre-normalized data."""

    class _Odd(_StockVAE):
        def __init__(self):
            super().__init__()
            self.process_input = lambda image: image  # already [-1,1]

    vae = _Odd()
    pixels = torch.rand(5, 4, 4, 3)
    encode_video_frames(vae, pixels)
    assert torch.equal(vae.received, pixels.to(vae.vae_dtype))
