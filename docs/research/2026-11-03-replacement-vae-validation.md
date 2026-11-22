# Replacement endpoint windows against the real H3 video VAE

Status: B1.10 passed on 2026-11-03 (CPU, float32). This settles item 1 of the [specification's feasibility gate](../superpowers/specs/2026-11-03-bridge-dialogue-timing-design.md#required-feasibility-gate): where frame and token origins sit, and how to extract an internal endpoint on the real VAE path. It says nothing about generated continuity, motion or speech at the joins; that is B1.11.

## What was measured

A replacement run is conditioned on the surviving footage on each side of its region: the carried context taken from the end of box A before the region, and the frozen ending taken from the start of box B after it. `latents.window(video, audio, start, frames, vae)` builds each of these windows from a saved run:

- **Aligned start** (`start % 17 == 0`): a token slice of the saved latent, starting at token `start // 17 * 5`.
- **Unaligned start**: decode the covering chunks, crop the window from the decoded frames and encode it again with the VAE.

[`scripts/validate_replacement_vae.py`](../../scripts/validate_replacement_vae.py) encodes a synthetic 107-frame, 256×256 moving clip (drifting gradients, a disc moving on a curve, scrolling stripes). It runs `latents.window` for four 39-frame windows taken from the geometry of two 107-frame boxes with context 39:

| Window | Start | Path | Role |
| --- | --- | --- | --- |
| aligned carried, L=34 | 34 | slice | A's carried context when 34 frames of A are replaced |
| aligned carried, L=17 | 51 | slice | the same with L=17 |
| unaligned carried, L=14 | 54 | re-encode | A's carried context for L=14 |
| unaligned frozen, R=15 | 15 | re-encode | B's frozen ending for R=15 |

L=14 with R=15 is the 29-frame allocation that `tests/python/test_candidates.py` uses for its endpoint test.

Pass criteria were fixed in the plan before the run:

- An aligned slice must decode within 35 dB PSNR of the full run's decode.
- An unaligned re-encoded window must decode within 30 dB of the source pixels.
- Every window must have the expected token count (12 for 39 frames) and must decode to exactly 39 frames.

## Run

```text
C:/Users/ricar/ComfyUI/ComfyUI_windows_portable/python_embeded/python.exe scripts/validate_replacement_vae.py \
  --vae D:/Projects/ComfyUI_windows_portable/ComfyUI/models/vae/minimax_h3_video_vae_fp16.safetensors \
  --out .tmp/vae_256_cpu.json
```

The environment was torch 2.14.1+cu130 with 12 CPU threads. The report records device `cpu` and dtype `torch.float32`. The run took 617 s and exited 0. The user's ComfyUI (pid 63704) held the GPU throughout: the validation process was not among the GPU compute processes, and the VAE file was only read.

The script sets `CUDA_VISIBLE_DEVICES=-1` before importing torch and refuses to run if CUDA is still visible. The plan's `CUDA_VISIBLE_DEVICES=""` does not work on Windows, because assigning an empty value deletes the variable. An earlier attempt made that mistake and ran for about 11 s on `cuda:0` in fp16. That attempt also passed every window, and its numbers agree with this run to within 0.04 dB. It is not used as evidence.

## Results

Full run: 107 frames encoded to latent `[1, 24, 32, 16, 16]` and decoded back to 107 frames at 38.287 dB round-trip PSNR against the source.

| Window | Tokens | Decode vs full decode (dB) | Decode vs source (dB) | Full decode vs source (dB) | Worst frame vs full decode (dB, index) | Latent vs direct encode (max abs, relative RMS) | Pass |
| --- | --- | --- | --- | --- | --- | --- | --- |
| aligned carried, L=34 | 12 | 53.308 | 38.456 | 38.505 | 43.311 (0) | 0.0, 0.0 | yes |
| aligned carried, L=17 | 12 | 53.301 | 38.199 | 38.348 | 42.393 (0) | 0.0, 0.0 | yes |
| unaligned carried, L=14 | 12 | 37.926 | 34.891 | 38.382 | 34.854 (5) | 1.21, 0.173 | yes |
| unaligned frozen, R=15 | 12 | 37.691 | 34.781 | 38.551 | 35.593 (36) | 1.438, 0.171 | yes |

Every window produced 65 audio ticks and decoded to 39 frames.

## Findings

1. **The 17-frame temporal origin holds bit-for-bit.** An aligned slice of the full run's latent is identical (max abs difference 0.0) to encoding the same 39 source frames directly. The encoder restarts its temporal grid every 17 frames, so on-grid endpoints carry no approximation at all.
2. **The decoder carries state across chunks.** Decoding a slice on its own differs slightly from the same frames in the full decode. The first frame differs most (42–43 dB), and the window as a whole sits at 53 dB. This affects pixel previews only; conditioning uses the latent, which is exact.
3. **Re-encoding costs 3.5–3.8 dB.** Unaligned windows decode at 34.8–34.9 dB against the source, compared with 38.4–38.6 dB for the full run over the same frames. This is second-generation loss from decode, crop and encode, and it stays 4.8 dB above the 30 dB criterion. The frames next to each join decode better than the window average: the last frame of the carried window is 37.8 dB against the full decode, and the first frame of the frozen window is 41.0 dB.
4. **Re-encoded latents are not the latents of the source pixels.** The latent rebuilt for an unaligned window differs from a direct encode of the same source frames by about 17% relative RMS. Its decode is close to the source, but the conditioning a replacement run receives off the grid differs measurably from conditioning on the original pixels. Whether the model's joins tolerate this is a question for real generation (B1.11).
5. **A replacement re-encodes at least one endpoint, except beside an exact-length box.** `replacement.geometry` starts the frozen window at `R` in box B's saved run. It starts the carried window at `carried + played - L - context` in box A's saved run. When A is on the grid, carried + played is its whole 17k+5 run, and the context is 17k+5 too. So the carried window is on the grid only when L is a multiple of 17, and the frozen window only when R is. L + R is 12, 29 or 46, so at most one of them can be. The default 14/15 split re-encodes both endpoints, and 17/12 or 12/17 keeps one side exact. The re-encode path is therefore the normal case, and B1.11 has to judge it. When box A has an exact length, its dropped frames shift the carried window's phase.

## Not established

- Generated continuity, motion and protected-speech behaviour at both joins (gate item 4, B1.11).
- Real footage; this clip is synthetic and smooth.
- Resolutions above 256×256 and other VAE dtypes. The fp16 VAE weights were run in float32 on the CPU. The accidental GPU fp16 run agrees, but only for this clip.
- Audio-window content: the run checks only the tick count of the cut audio latent.
