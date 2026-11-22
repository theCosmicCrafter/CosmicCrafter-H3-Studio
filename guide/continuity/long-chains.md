# Long continuing chains

Each continuing clip copies the end of the clip before it and adds its own small errors on top. Over many clips this compounds: skin, fabric and backgrounds get crisper and more etched ("burn"), the way a photocopy of a photocopy gains contrast. The [continuity check](check.md) measures it as texture drift, for example *Drift: 104% grainier than box 1.*

These settings are experimental and off by default. They were compared on one six-clip chain (a woman talking to camera in a kitchen, FastH3 omniref 8-step int8 at 960 × 544); results on other models and scenes may differ, so compare a few clips before relying on them. On this chain, the model changed the burn more than any setting did: see [The model matters most](#the-model-matters-most).

## What was measured

Texture is the finest-detail energy of each clip against clip 1 (1.00 = no change). A "jump" is the largest frame-to-frame change at a join; the unchanged chain's joins measured 2.5 to 4.2.

| Setting | Clip 6 texture | Joins | Result |
| --- | --- | --- | --- |
| None (default) | 2.04 | 2.5–4.2 | Burn builds steadily. |
| `context_noise` | **1.75** | 2.6–3.2 | Much less burn; same framing; about 10% slower per continuing clip. |
| H3 Sigmas Tail, 3 steps, 0.5 | 1.93 | 2.4–3.2 | A little less burn. |
| `context_noise` and Sigmas Tail together | **1.67** | 2.7–3.3 | The least burn of all; same framing. |
| `continuation_guide: false` | 2.19 | 4.1–5.8 | See below: removes a hitch in moving shots. |
| Anti-burn LoRA 0.5 via H3 Continuation Model | (1.77) | **59 at clip 2** | Cut to a close-up at the first join; rejected. |
| Anti-burn LoRA 0.3 | 1.99 | 2.5–3.2 | No measurable effect on FastH3 int8. |

## The model matters most

The table above is `fasth3_omniref_8step_pruned_int8_convrot`. The same chain on MiniMax's REF2VA model (`minimax_h3_ref2va_pruned_int8_convrot` and `minimax_h3_ref2va_pruned_bf16`) with the ref2v turbo LoRA (`minimax_h3_ref2v_turbo_8step_v1.1`) burned far less in both files, so the difference comes from the model, not from int8.

FastH3 v2 (`fastvideo_fasth3_8step_v2_pruned_int8_convrot` with turbo LoRA `minimax_h3_ref2v_turbo_8step_v1.0` at 1), which the Story Studio examples render video with, did not burn (clip 6 texture 0.97), but in every render clip 2 cut to a closer framing one frame after the join. That held with the examples' own sampler (res_multistep) and with a second seed. Each time, clip 1 had come out wider than the "medium close-up" every prompt names, and clip 2 moved to the prompt's framing instead of keeping clip 1's; the later joins were smooth. The anti-burn LoRA did not change the cut. On this model, check the first join of a long chain. Whether a clip 1 that already matches the prompt's framing avoids the cut was not measured, and other models were not measured.

| Model and anti-burn LoRA | Clip 6 texture | Joins | Result |
| --- | --- | --- | --- |
| REF2VA int8 | 1.19 | 1.1–1.8 | Little burn with no setting. |
| REF2VA int8, anti-burn LoRA 0.3 | 1.16 | 1.0–1.7 | No clear effect. |
| REF2VA int8, anti-burn LoRA 0.5 | **1.04** | 1.1–1.3 | No cut. Clip 2 rises to 1.17, then later clips settle instead of climbing. |
| REF2VA bf16 | 1.25 | 1.0–1.8 | Like int8. |
| REF2VA bf16, anti-burn LoRA 0.3 | 1.16 | 1.0–1.7 | Slightly lower, within what the seed can move. |
| REF2VA bf16, anti-burn LoRA 0.5 | 1.23 | 1.1–1.5 | No cut; clip 2 rises to 1.36. |
| FastH3 v2 int8 | 0.97 | **36 at clip 2**, then 1.4–1.6 | No burn, but clip 2 cut to a closer framing. |
| FastH3 v2 int8, anti-burn LoRA 0.3 | 0.92 | **36 at clip 2**, then 1.3–1.5 | The same cut. |
| FastH3 v2 int8, anti-burn LoRA 0.5 | 0.86 | **37 at clip 2**, then 1.3–2.1 | The same cut. |
| FastH3 v2 int8, res_multistep | 0.95 | **39 at clip 2**, then 1.5–1.8 | The same cut with the examples' sampler. |
| FastH3 v2 int8, res_multistep, another seed | 0.90 | **45 at clip 2**, then 1.4–2.8 | The same cut; the 2.8 is a hand gesture. |

Each row is one render of this chain; differences of about 0.1 can come from the seed alone. The first three FastH3 v2 renders share clip 1 and the seed (the LoRA only reaches continuing clips), so their cuts count as one; the two res_multistep renders each made their own clip 1, so the cut was seen after three different clip 1s. Every row used euler at 8 steps except the two res_multistep rows, the sampler the Story Studio examples use for FastH3 v2 (same 8 steps and scheduler). On a 24 GB GPU a continuing clip took about 1 min 40 s on the int8 files and 2 min 40 s on the 40 GB bf16 file, which does not fit and streams from system memory.

## Context noise

Tick **Context noise** in the Studio ([below](#in-the-studio)), or add `"context_noise": true` to the Timeline JSON (or send it through the [API](../automation/api.md)). For each continuing clip, the carried frames are decoded, given seeded noise that fades from strong at the start of the overlap to none at its last frame, and encoded again; only the difference the noise makes is added to the original carried latent, so the VAE's own round-trip error is not carried forward. The carried frames stay frozen while H3 samples; audio is unchanged. It costs one decode and two encodes of the overlap per continuing clip.

## Guide at the first new frame

A continuing clip normally uses the previous clip's last frame as a guide at its first new frame, so the pose does not reset. In moving shots this produces a short hitch: about three nearly identical frames at the join, which the check reports as *Holds still: 3 frames at the join.* Unticking **Guide from the last frame** in the Studio (`"continuation_guide": false`) removes the guide and the hitch; in calm shots the join then moves a little more. It is a per-Timeline setting; the default keeps the guide.

## H3 Sigmas Tail

A node for your graph (`BasicScheduler → H3 Sigmas Tail → the sampler's sigmas`, with the Timeline's `segment` connected so clip 1 is unchanged). It raises the last noise levels before zero, so the final step of a distilled model settles less fine detail. See [Nodes](../reference/nodes.md#h3-sigmas-tail).

## H3 Continuation Model

Routes continuing clips (and bridges) to a different model, for a LoRA trained for continuations. The public H3 Anti-Burn LoRA did not help on FastH3 int8 and cut to a close-up at 0.5 ([first table](#what-was-measured)). On MiniMax's REF2VA model with the turbo LoRA, the base its authors tested it on, 0.5 caused no cut and kept later clips from climbing ([The model matters most](#the-model-matters-most)), though that model burns little without it. On FastH3 v2 it did not change that model's cut at the first join.

## In the Studio

**Project settings → Long continuing chains** holds these Timeline settings.

| Control | Timeline key | Default |
| --- | --- | --- |
| **Context noise** | `context_noise` | off |
| **Guide from the last frame** | `continuation_guide` | on |
| **Audio feather**, in ticks of 25 ms | `audio_feather` | 0 |
| **Split @video1 across clips**, one per reference video | `video_slices` | off; see [References](../build/references.md) |

They apply to every continuing clip; a split video applies to every clip that mentions it. Changing **Context noise**, **Guide from the last frame** or **Audio feather** marks those clips as changed until they render again. A split changes only the video frames and sound those clips receive, which the Studio cannot see before a run: clips already rendered still show as rendered, and **Run** in the graph renders them again, one clip per run.

**Audio feather** lets the end of the carried audio regenerate: over that many ticks (up to 16, which is 0.4 s), the carried sound fades from frozen to free, which can soften an audible seam at the join. At 0 the carried audio stays frozen.

H3 Sigmas Tail is a node in your graph, so it has no control here.
