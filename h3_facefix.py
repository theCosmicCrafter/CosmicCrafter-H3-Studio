# ABSORBED NODE: PixelAIH3FaceSizeFade, ported from
# ComfyUI-H3-FaceFix-PixelAILabs by PixelAI Labs
# (https://github.com/Pixelailabs/ComfyUI-H3-FaceFix-PixelAILabs), MIT License.
# The node id and behaviour are kept identical so the upstream example
# workflow (examples/PixelAI_H3_FaceFix.json) resolves unchanged. Stdlib only.

"""Scale each tracked face's paste opacity by its size in the source video.

Sits between H3 Face Track Crop (ComfyUI-H3-FaceRefine) and H3 Face Stitch:
full fix on small (distant) faces, fading to none on big (close) faces, so
close-ups stay exactly as H3 generated them.
"""
import copy


def _smoothstep(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3.0 - 2.0 * x)


class PixelAIH3FaceSizeFade:
    CATEGORY = "PixelAI Labs/H3"
    RETURN_TYPES = ("H3FACEXFORM", "STRING")
    RETURN_NAMES = ("transform", "report")
    FUNCTION = "run"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "transform": ("H3FACEXFORM",),
            "full_fix_below_px": ("INT", {"default": 110, "min": 8, "max": 2048, "step": 2,
                "tooltip": "Face height (source pixels) at or under which the fix is pasted at full strength."}),
            "no_fix_above_px": ("INT", {"default": 180, "min": 8, "max": 4096, "step": 2,
                "tooltip": "Face height (source pixels) at or over which the original face is kept untouched."}),
            "crop_factor": ("FLOAT", {"default": 2.5, "min": 1.2, "max": 8.0, "step": 0.1,
                "tooltip": "Same value as crop_factor on H3 Face Track Crop (crop side = this x face height)."}),
            "reference_height": ("INT", {"default": 1080, "min": 0, "max": 8192, "step": 8,
                "tooltip": "Pixel sizes above are for a video of this height and scale with the real one. 0 = use source pixels as-is."}),
        }}

    def run(self, transform, full_fix_below_px, no_fix_above_px, crop_factor, reference_height):
        t = copy.copy(transform)
        boxes = t["boxes"]
        src_h = float(t.get("src_size", (0, reference_height or 1080))[1]) or 1.0
        scale = (src_h / reference_height) if reference_height else 1.0
        lo = full_fix_below_px * scale
        hi = max(lo + 1.0, no_fix_above_px * scale)
        old = list(t.get("weights") or [1.0] * len(boxes))
        faces, fades, new = [], [], []
        for i, b in enumerate(boxes):
            face = float(b[3]) / float(crop_factor)
            f = 1.0 - _smoothstep((face - lo) / (hi - lo))
            faces.append(face); fades.append(f)
            new.append((old[i] if i < len(old) else 1.0) * f)
        t["weights"] = new
        n = len(fades)
        full = sum(1 for f in fades if f >= 0.999)
        none = sum(1 for f in fades if f <= 0.001)
        rep = (f"[PixelAI FaceSizeFade] {n} frames, face height {min(faces):.0f}-{max(faces):.0f}px "
               f"(src {src_h:.0f}p, ramp {lo:.0f}->{hi:.0f}px): full fix {full}, fading {n-full-none}, untouched {none}")
        steps = max(1, n // 12)
        rep += "\n" + " ".join(f"f{i}:{faces[i]:.0f}px={fades[i]:.2f}" for i in range(0, n, steps))
        print(rep)
        return (t, rep)
