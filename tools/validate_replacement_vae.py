"""CPU validation of replacement endpoint windows against the real MiniMax H3 video VAE.

A replacement run reads `latents.window` of the surviving footage on each side of its region. On the 17-frame grid
the window is a token slice of the saved run; off it, the covering chunks are decoded, cropped and encoded again.
This encodes a synthetic moving clip and measures, for each window:

- aligned: the slice against a direct encode of the same frames, and its decode against the full run's decode;
- unaligned: the re-encoded window's decode against the source pixels and the full run's decode.

Pass criteria (fixed before the run): an aligned slice decodes within 35 dB PSNR of the full decode, and an
unaligned window decodes within 30 dB of the source pixels. CUDA is hidden before torch loads and the VAE runs in
float32 on the CPU, so a running ComfyUI keeps its GPU; the VAE file is only read. Prints JSON; --out also writes it.

Run with the ComfyUI portable interpreter, whose path already holds ComfyUI:
    python_embeded/python.exe scripts/validate_replacement_vae.py --vae <path>/minimax_h3_video_vae_fp16.safetensors
"""
import os

# "-1", not "": on Windows an empty value deletes the variable and torch sees every GPU.
os.environ["CUDA_VISIBLE_DEVICES"] = "-1"

import argparse
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import torch  # noqa: E402

if torch.cuda.is_available():
    sys.exit("validate_replacement_vae: CUDA is still visible; refusing to run beside a ComfyUI that owns the GPU")

from comfy.cli_args import args as comfy_args  # noqa: E402

comfy_args.cpu = True

import comfy.sd  # noqa: E402
import comfy.utils  # noqa: E402

from h3_continuity import latents  # noqa: E402
from h3_continuity.timing import GRID_STEP, ticks_for_frames, tokens_for_frames  # noqa: E402

ALIGNED_DB = 35.0
UNALIGNED_DB = 30.0
# (name, start, frames): starts from boxes [107, 107] with context 39. L=14, R=15 gives the carried window at 54 of
# box A and the frozen window at 15 of box B; L=34 and L=17 put the carried window on the grid at 34 and 51.
WINDOWS = [("aligned carried, L=34", 34, 39), ("aligned carried, L=17", 51, 39),
           ("unaligned carried, L=14", 54, 39), ("unaligned frozen, R=15", 15, 39)]


def synthetic_clip(frames, size):
    """[frames, size, size, 3] in [0, 1]: drifting colour gradients, a disc moving on a curve and scrolling stripes."""
    t = torch.arange(frames, dtype=torch.float32).view(-1, 1, 1)
    axis = torch.linspace(0, 1, size)
    y, x = axis.view(1, -1, 1), axis.view(1, 1, -1)
    r = 0.5 + 0.35 * torch.sin(2 * math.pi * (x + t / 60))
    g = 0.5 + 0.35 * torch.sin(2 * math.pi * (0.8 * y - t / 90))
    b = 0.5 + 0.25 * torch.cos(2 * math.pi * ((x + y) / 2 + t / 120))
    cx, cy = 0.2 + 0.6 * t / frames, 0.5 + 0.25 * torch.sin(2 * math.pi * t / 48)
    disc = torch.sigmoid((0.12 - torch.sqrt((x - cx) ** 2 + (y - cy) ** 2)) * size / 3)
    stripes = 0.06 * torch.sin(2 * math.pi * (x * size - t) / 16)
    shape = (frames, size, size)
    rgb = torch.stack([r.expand(shape), g.expand(shape), b.expand(shape)], dim=-1) + stripes.unsqueeze(-1)
    rgb = rgb * (1 - disc.unsqueeze(-1)) + disc.unsqueeze(-1) * torch.tensor([0.95, 0.9, 0.8])
    return rgb.clamp(0, 1)


def frames_of(pixels):
    return pixels.reshape(-1, *pixels.shape[-3:])[..., :3].float().cpu()


def psnr(a, b):
    mse = torch.mean((a - b) ** 2).item()
    return float("inf") if mse == 0 else 10 * math.log10(1 / mse)


def per_frame(a, b):
    return [psnr(a[i], b[i]) for i in range(a.shape[0])]


def rounded(value):
    return None if value is None else round(value, 3)


def latent_difference(a, b):
    a, b = a.float().cpu(), b.float().cpu()
    return {"max_abs": rounded((a - b).abs().max().item()),
            "relative_rms": rounded((torch.sqrt(torch.mean((a - b) ** 2)) / torch.sqrt(torch.mean(b ** 2))).item())}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--vae", required=True, help="minimax_h3_video_vae_fp16.safetensors")
    parser.add_argument("--frames", type=int, default=107)
    parser.add_argument("--size", type=int, default=256)
    parser.add_argument("--threads", type=int, default=12)
    parser.add_argument("--out", help="also write the JSON report here")
    args = parser.parse_args()
    torch.set_num_threads(args.threads)
    began = time.time()

    sd, metadata = comfy.utils.load_torch_file(args.vae, return_metadata=True)
    vae = comfy.sd.VAE(sd=sd, metadata=metadata, device=torch.device("cpu"), dtype=torch.float32)
    del sd
    if vae.device.type != "cpu":
        sys.exit(f"validate_replacement_vae: the VAE loaded on {vae.device}, not the CPU")
    source = synthetic_clip(args.frames, args.size)
    with torch.inference_mode():
        full = vae.encode(source)
        if full.ndim == 4:
            full = full.unsqueeze(0)
        decoded = frames_of(vae.decode(full))
        audio = torch.zeros(1, 8, ticks_for_frames(args.frames))
        report = {"vae": os.path.basename(args.vae), "device": str(vae.device), "dtype": str(vae.vae_dtype),
                  "torch": torch.__version__, "frames": args.frames, "size": args.size,
                  "latent_shape": list(full.shape), "decoded_frames": decoded.shape[0],
                  "round_trip_psnr": rounded(psnr(decoded, source)),
                  "criteria": {"aligned_vs_full_decode_db": ALIGNED_DB, "unaligned_vs_source_db": UNALIGNED_DB},
                  "windows": []}
        passed = decoded.shape[0] == args.frames
        for name, start, frames in WINDOWS:
            window, ticks = latents.window(full, audio, start, frames, vae if start % GRID_STEP else None)
            pixels = frames_of(vae.decode(window))
            direct = vae.encode(source[start:start + frames])
            if direct.ndim == 4:
                direct = direct.unsqueeze(0)
            versus_full = per_frame(pixels, decoded[start:start + frames])
            item = {"name": name, "start": start, "frames": frames, "aligned": start % GRID_STEP == 0,
                    "tokens": window.shape[2], "expected_tokens": tokens_for_frames(frames),
                    "audio_ticks": ticks.shape[-1], "decoded_frames": pixels.shape[0],
                    "vs_full_decode_db": rounded(psnr(pixels, decoded[start:start + frames])),
                    "vs_source_db": rounded(psnr(pixels, source[start:start + frames])),
                    "full_decode_vs_source_db": rounded(psnr(decoded[start:start + frames], source[start:start + frames])),
                    "first_frame_vs_full_db": rounded(versus_full[0]), "last_frame_vs_full_db": rounded(versus_full[-1]),
                    "worst_frame_vs_full_db": rounded(min(versus_full)),
                    "worst_frame_index": versus_full.index(min(versus_full)),
                    "latent_vs_direct_encode": latent_difference(window, direct)}
            if item["aligned"]:
                item["pass"] = item["vs_full_decode_db"] >= ALIGNED_DB
            else:
                item["pass"] = item["vs_source_db"] >= UNALIGNED_DB
            item["pass"] = bool(item["pass"] and item["tokens"] == item["expected_tokens"] and pixels.shape[0] == frames)
            passed = passed and item["pass"]
            report["windows"].append(item)
            print(f"{name}: {item['vs_full_decode_db']} dB vs full decode, {item['vs_source_db']} dB vs source",
                  file=sys.stderr, flush=True)
    report["pass"] = bool(passed)
    report["seconds"] = round(time.time() - began, 1)
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
