"""Converting decoded RGB frames between the colour spaces H3 Save Segment writes: "sRGB" (BT.709 primaries, sRGB
curve), "HDR" (BT.2020, HLG) and "HDR PQ" (BT.2020, PQ). Values are the encoded signal in 0-1, as ComfyUI decodes them.
SDR white sits where BT.2408 puts it: 75% HLG signal, 203 cd/m2 in PQ."""

import math

import torch

HDR_SPACES = ("HDR", "HDR PQ")
_BT709_TO_BT2020 = torch.tensor([[0.6274040, 0.3292820, 0.0433136],
                                 [0.0690970, 0.9195400, 0.0113612],
                                 [0.0163916, 0.0880132, 0.8955950]])
_BT2020_LUMA = torch.tensor([0.2627, 0.6780, 0.0593])
_HLG_A, _HLG_B, _HLG_C = 0.17883277, 0.28466892, 0.55991073
_PQ_M1, _PQ_M2, _PQ_C1, _PQ_C2, _PQ_C3 = 0.1593017578125, 78.84375, 0.8359375, 18.8515625, 18.6875
HLG_PEAK = 1000.0  # cd/m2 of HLG's nominal display
SDR_WHITE_PQ = 203.0
# Scene light that HLG encodes at 75%, where SDR white goes.
SDR_WHITE_HLG = (math.exp((0.75 - _HLG_C) / _HLG_A) + _HLG_B) / 12


def target_space(spaces):
    """The colour space a join of clips in `spaces` uses: HDR when any clip is HDR (PQ only when more clips use PQ
    than HLG), otherwise sRGB."""
    hdr = [space for space in spaces if space in HDR_SPACES]
    if not hdr:
        return "sRGB"
    return "HDR PQ" if hdr.count("HDR PQ") > hdr.count("HDR") else "HDR"


def _srgb_to_linear(v):
    return torch.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


def _hlg_oetf(e):
    e = e.clamp(min=0)
    return torch.where(e <= 1 / 12, torch.sqrt(3 * e), _HLG_A * torch.log((12 * e - _HLG_B).clamp(min=1e-12)) + _HLG_C)


def _hlg_inverse_oetf(v):
    return torch.where(v <= 0.5, v * v / 3, (torch.exp((v - _HLG_C) / _HLG_A) + _HLG_B) / 12)


def _pq_encode(nits):
    y = (nits / 10000).clamp(0, 1) ** _PQ_M1
    return ((_PQ_C1 + _PQ_C2 * y) / (1 + _PQ_C3 * y)) ** _PQ_M2


def _pq_decode(v):
    p = v.clamp(0, 1) ** (1 / _PQ_M2)
    return 10000 * ((p - _PQ_C1).clamp(min=0) / (_PQ_C2 - _PQ_C3 * p)) ** (1 / _PQ_M1)


def _luma(rgb):
    return (rgb * _BT2020_LUMA).sum(-1, keepdim=True).clamp(min=1e-9)


def convert(rgb, source, target):
    """`rgb` ([..., 3] float, 0-1 signal) from colour space `source` to `target`. HDR goes to SDR by clipping above SDR
    white, which a join never asks for: it converts SDR clips up to HDR."""
    if source == target:
        return rgb
    rgb = rgb.float()
    if source == "sRGB":
        linear = _srgb_to_linear(rgb.clamp(0, 1)) @ _BT709_TO_BT2020.T  # SDR white = 1.0
    elif source == "HDR":
        scene = _hlg_inverse_oetf(rgb.clamp(0, 1))
        display = HLG_PEAK * _luma(scene) ** 0.2 * scene  # BT.2100 OOTF, system gamma 1.2
        linear = display / SDR_WHITE_PQ
    else:
        linear = _pq_decode(rgb) / SDR_WHITE_PQ
    if target == "HDR PQ":
        out = _pq_encode(linear * SDR_WHITE_PQ)
    elif target == "HDR":
        if source == "sRGB":
            out = _hlg_oetf(linear * SDR_WHITE_HLG)
        else:
            display = linear * SDR_WHITE_PQ / HLG_PEAK
            scene = display * _luma(display) ** (-0.2 / 1.2)  # inverse OOTF
            out = _hlg_oetf(scene)
    else:
        out = (linear.clamp(0, 1) @ torch.linalg.inv(_BT709_TO_BT2020).T).clamp(0, 1)
        out = torch.where(out <= 0.0031308, out * 12.92, 1.055 * out ** (1 / 2.4) - 0.055)
    return out.clamp(0, 1)
