# Replacement candidates in real generation

Status: B1.11's joins failed on 2026-11-03 at the user's review; its dialogue sync passed once Visual memory stopped replaying a talking shot across the cut (098a1ea). This was item 4 of the [specification's feasibility gate](../superpowers/specs/2026-11-03-bridge-dialogue-timing-design.md#required-feasibility-gate): real generated endpoint continuity, motion and protected-speech behaviour at both joins. Every candidate of both constructions tried jumps at or near a join. Following the gate's failure rule, replacement bridges ship unavailable (`replacement.UNAVAILABLE`), existing cuts are kept, and this record holds the failing constructions and their evidence.

## Setup

Two boxes in an unmanaged sequence `h3c-b111-replacement-1`, rendered on the user's GPU ComfyUI with this branch loaded:

- 1024×576, context 39, `carry_audio` off. Boxes b1 and b2 have 107 fresh frames each, seeds 3110101 and 3110102. Box 2 cuts from box 1 and starts a memory scene.
- Models installed on the host, in the shape of the shipped `native-turbo4` profile: `minimax_h3_ref2va_pruned_int8_convrot` with `pika_h3_flex_ref2va_v1_bf16` at 1.0, shift 12/3, ManualSigmas `1.0, 0.972973, 0.923077, 0.8, 0.571429, 0.333333, 0.0`, lcm, `minimax_h3_video_vae_fp16` (the [B1.10](2026-11-03-replacement-vae-validation.md) VAE) and `qwen3vl_32b_h3_ultra_uncensored_heretic_int8_convrot`.
- The recording `input/h3c_b111/b111_dialogue.wav` (8.917 s of synthetic speech) on `audio1`, locked and in the full video. Two on-screen cues: line 1 at 0.50–2.48 s and line 2 at 5.60–7.90 s, with a pause of about 3 s around the cut at 4.46 s. Both cues lie outside every region tried, so no candidate regenerates protected speech.
- The full video before any replacement: 214 frames, 8.916667 s of video and audio.

## Measurement

The agent's numbers are the mean absolute RGB difference between consecutive frames at 512×288, on a 0–255 scale. Normal motion in these clips is 0.3–0.5 per frame; the original cut is 9.3. A *join* step is the step between the last surviving frame and the first new frame (carried join) or the last new frame and the first surviving frame (frozen join). The *inner* step is the largest step inside the region. These numbers locate a jump; the verdicts are the user's.

## Construction 1: 29 frames, push-in prompt

The bridge prompt asked for a push-in from box 1's medium shot to a close-up. Region 93–122 for 14/15 (both endpoints re-encoded) and 90–119 for 17/12 (the carried endpoint is an exact latent slice). Each candidate took about 95 s. After the frame-timing fix in ce68640 the same seeds reproduced the earlier candidates bit for bit.

| Candidate | Split | Seed | Carried join | Frozen join | Inner step (sequence frame) |
| --- | --- | --- | --- | --- | --- |
| `8c6f2681` | 14/15 | 3110201 | 2.12 | 1.88 | 8.97 (114) |
| `840afc6f` | 14/15 | 3110202 | 2.11 | 1.91 | 8.02 (118) |
| `dc6b414a` | 17/12 | 3110301 | 1.51 | 2.71 | 8.54 (118) |
| `8da5bcce` | 17/12 | 3110302 | 1.54 | 2.10 | 9.03 (117) |

Every candidate continues box 1's shot and then cuts hard to box 2 inside the region, with a step as large as the original cut. With `840afc6f` selected, the full video still had 214 frames at 24/1, its audio samples were identical to the baseline, and the footage outside the region matched the baseline at 47–49 dB.

User review, 12:19: *"There's a jump clearly on all videos. Less on the 3rd. In the second line, the lip sync is off."* All four fail; `dc6b414a` jumps least.

## Construction 2: 46 frames, matched prompt

Both boxes had come out at the same medium framing, looking down at an envelope held low, so the push-in described neither endpoint. The bridge prompt became a static medium shot, looking down, lips closed, camera still. The region grew to 46 frames: 84–130 for 23/23 (both endpoints re-encoded) and 73–119 for 34/12 (exact carried slice, re-encoded frozen side). No 46-frame split is exact on both sides. Each candidate took 80–110 s.

| Candidate | Split | Seed | Carried join | Frozen join | Inner step (sequence frame) |
| --- | --- | --- | --- | --- | --- |
| `2046a162` | 23/23 | 3110401 | 2.18 | 2.48 | 6.49 (124) |
| `e061c84e` | 23/23 | 3110402 | 2.19 | 1.88 | 6.88 (122) |
| `40b69dc0` | 34/12 | 3110501 | 1.55 | 6.16 | 0.79 |
| `5b8c8e50` | 34/12 | 3110502 | 1.56 | 6.61 | 0.73 |

The 23/23 candidates still switch inside the region, with a smaller step. The 34/12 candidates move smoothly through the region and then jump at the frozen join, where brightness falls from 83.8 to 80.1. Frames on either side of each step show the same framing: box 1's brighter, flatter light and face snap to box 2's darker, higher-contrast light and slightly different face.

User review, 13:25: *"Still the same issue at 3-4 there's a jump and the second part the lipsync is not right."* Seconds 3–4 of the previews are frames 72–96, which hold the measured step in every candidate.

## Findings

1. **The model holds one clip's look and then switches, instead of blending.** The jump is a change of light and face between two renders that differ in look, not in framing. Where it lands depends on the construction: inside the region for both 29-frame splits, and in the 46-frame candidates inside the region when both endpoints are re-encoded and at the frozen join when the carried endpoint is exact. A longer region and a prompt that matches both endpoints made it smaller (from 8.0–9.0 to 6.2–6.9) but never removed it.
2. **An exact carried slice joins better than a re-encoded one.** Carried joins are 1.45–1.56 on exact slices and 2.06–2.19 on re-encoded windows, against 0.3–0.5 for normal motion. Neither is the failure the user saw.
3. **The pipeline around the candidate holds.** The selected replacement left the full video's length, every later frame time and the recording unchanged. The one defect found, previews and replaced full videos collapsing onto time 0, was fixed in ce68640.
4. **The line-2 lip sync is not a replacement effect.** Line 2 lies outside every region, so every candidate plays it as box 2 rendered it. Box 2 rendered without its `<d>` lines: a box with Visual memory rebuilt its prompt without the compiled dialogue cues. That is fixed in f3d49d1, but box 2 rendered again with its line (same seed) was still out of sync. Its mouth moves with box 1's mouth (correlation 0.59 at zero lag), not with line 2 (−0.01). With Visual memory off, the same box follows line 2 (0.70), but loses the kitchen, the light and the face. The cause is the full preceding video that memory supplies at a cut: box 1 is a talking shot of the same length, and H3 replays its lip movement. Memory now leaves that video out when either side of a cut speaks. Rendered again on 098a1ea with the same seed, box 2's mouth follows line 2 (0.58) rather than box 1's mouth (0.11) and keeps the kitchen, light and face. User review, 18:38: the line-2 sync *"looks right"*. Measurements: `.tmp/b111/memory-compare.json`, `memory-replay.json` and `memory-fix.json` (local).
5. **The clip after the cut kept the previous shot's framing.** Box 2's prompt asks for a close-up, but every render with memory came out at box 1's medium framing, both with the full preceding video and with the establishing view plus the moment before the cut. Memory off changed the framing and lost the scene. So the cut at 4.46 s is a jump cut (step 6.26 against a median 0.52). It stays a cut: spec §4 keeps the original cut, and making box 2 a continuation or re-rolling it for a close-up would test neither replacements nor dialogue. This is one seed of one scene, so how strongly memory holds framing at a cut is not measured.

## Not tried

- Clips whose light already matches across the cut. That would hide the failure rather than fix it: the test pair, two separate renders of one scene, is the ordinary case a replacement exists for.
- Conditioning beyond the carried and frozen latents: a guide image at the frozen join, references or memory in the bridge run.
- Other models, LoRAs, schedules or more steps.

## Turning replacements back on

`replacement.UNAVAILABLE` is the single switch. While it is set, `replacement_candidates.states` marks every replacement `unavailable`, `active` plays none, `render_bridge` refuses, the status reports `replacement_unavailable`, and the Studio hides **Replace around the cut** and keeps a cut inside a locked recording a cut. The machinery tests patch it to `""`. Set it to `""` only after a construction passes the same review: the reviewer accepts both joins and the dialogue sync for at least the default split.
