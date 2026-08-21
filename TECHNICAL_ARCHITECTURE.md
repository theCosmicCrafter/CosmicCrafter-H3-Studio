# Technical Architecture

This document explains the implementation behind the workflows in this repository. It is intentionally more technical than the main README.

If you only want to choose and run a workflow, start with [README.md](README.md) and [example_workflows/README.md](example_workflows/README.md).

> **Update 6 current-state note:** the AV Extension and Music Video examples are checkpoint-free direct-latent workflows. Their public final outputs stream frames directly into VideoHelperSuite instead of materializing one complete ComfyUI `IMAGE` movie tensor. Small H3 decoded-audio duration undershoots are time-conformed to the exact frame-derived sample timeline before seam cutting. Sections 14–19 below document the historical Update-5 checkpoint architecture for context; those checkpoint/resume nodes are no longer registered by the current node pack.

---

## 1. Architecture overview

The repository contains two different continuation families.

### Legacy Motion Context

The previous clip is represented as **native H3 guide conditioning**. The target H3 latent remains a fresh generation target; previous motion/audio is supplied as conditioning that tells H3 what is already happening.

Main node:

- `H3 Motion Context`

Typical workflow label:

- `OLD - Motion Context - ...`

### Current latent masking

Known video/audio content is written directly into the H3 target latent. A per-token noise mask marks the known region as protected and the unknown region as generative.

Main nodes:

- `H3 Existing Video Masked Context`
- `H3 Generated AV Masked Context`
- `H3 Masked AV Bridge`
- `H3 Song Audio + Masked Video Context`

Current workflow examples:

- `NEW - AV Extension.json`
- `NEW - Music Video.json`

The two families can coexist in the same repository because they solve continuation in different ways.

---

## 2. MiniMax H3 joint AV latent

MiniMax H3 works with a joint audiovisual latent. In this repository it is treated as two streams inside the ComfyUI `LATENT` object:

- video latent: approximately `[B, C, T, H, W]`;
- audio latent: approximately `[B, C, 2, T_audio]`.

Current ComfyUI H3 represents these together using a nested tensor-like structure.

The custom nodes therefore avoid assuming that `latent["samples"]` is one ordinary tensor. Helper functions explicitly unpack the video and audio streams.

This matters for:

- target-latent masking;
- historical checkpoint serialization;
- direct generated-latent continuation;
- master-song audio replacement.

---

### Discretization and clock alignment constraints

MiniMax H3 establishes distinct operational frequencies across domains:

$$\text{Video Frame Rate } (f_v) = 24 \text{ Hz}$$
$$\text{Audio Latent Rate } (f_a) = 40 \text{ Hz}$$

The fundamental conversion ratio between temporal domains is:

$$\frac{f_a}{f_v} = \frac{40}{24} = \frac{5}{3} \approx 1.6667 \text{ audio latent steps per video frame}$$

Because individual video frames do not correspond to integer audio latent tokens, naive temporal slicing results in fractional token truncation and phase artifacts. Furthermore, the H3 video Variational Autoencoder (VAE) employs a non-uniform temporal token grouping pattern defined by the sequence $(1, 4, 4, 4, 4)$, yielding valid native video frame sequences governed by an arithmetic progression:

$$N_f = 17k + 5 \quad \text{for } k \in \mathbb{N}_0 \quad (N_f \in \{5, 22, 39, 56, 73, 90, 107, 124, 141, 158, 175, 192, \dots\})$$

### Harmonic AV context boundaries

To prevent fractional phase drift and temporal aliasing across multi-clip continuations, context boundaries must simultaneously satisfy the video VAE sequence ($N_f = 17k + 5$) and evaluate to an exact integer on the $40\text{ Hz}$ audio grid ($\frac{5 N_f}{3} \in \mathbb{Z}$).

Setting $5(17k + 5) \equiv 0 \pmod 3$ simplifies to:

$$85k + 25 \equiv 0 \pmod 3 \implies k + 1 \equiv 0 \pmod 3 \implies k \equiv 2 \pmod 3$$

Substituting $k = 3m + 2$ for $m \in \mathbb{N}_0$ into the frame progression establishes the exact harmonic synchronization series:

$$N_f = 17(3m + 2) + 5 = 51m + 39 \quad \text{for } m \in \mathbb{N}_0$$

| Context Index ($m$) | Frame Count ($N_f$) | Video Duration ($s$) | Audio Latent Steps ($T_a$) | PCM Samples ($44.1\text{ kHz}$) | PCM Samples ($48.0\text{ kHz}$) |
|---|---|---|---|---|---|
| **0 (Default Seam)** | **39** | **1.6250 s** | **65** | **71,662.5** | **78,000** |
| 1 | 90 | 3.7500 s | 150 | 165,375.0 | 180,000 |
| 2 | 141 | 5.8750 s | 235 | 259,087.5 | 282,000 |
| 3 | 192 | 8.0000 s | 320 | 352,800.0 | 384,000 |
| 4 | 243 | 10.1250 s | 405 | 446,512.5 | 486,000 |
| 5 | 294 | 12.2500 s | 490 | 540,225.0 | 588,000 |
| 6 | 345 | 14.3750 s | 575 | 633,937.5 | 690,000 |

At non-integer PCM sample boundaries (such as $44.1\text{ kHz}$ across a 39-frame window yielding 71,662.5 samples), exact timeline tracking requires alternating absolute sample counts (toggling between 71,662 and 71,663 samples) to avoid cumulative phase drift over extended multi-clip assemblies.

## 4. Why some target clips have a rounded audio tail

A full H3 target does not always end on an exact 40 Hz audio boundary.

Example:

```text
124 video frames / 24 fps = 5.166666... s
5.166666... s * 40 Hz = 206.666666... audio steps
```

The target AV latent may therefore contain:

```text
207 audio latent steps
```

The target latent length is authoritative.

This distinction is important for the master-song workflow because an audio VAE given only the exact picture-duration waveform can, on some encode paths, return 206 steps while the H3 target contains 207.

`H3 Song Audio + Masked Video Context` handles this by:

1. keeping its public `clip_audio` output at the exact picture duration;
2. calculating how much waveform is required to cover the complete target audio grid;
3. encoding that slightly longer real master-song interval when necessary;
4. retrying with a small amount of additional real-audio lookahead if an encoder boundary still floors the output;
5. cropping the encoded latent to the exact target-audio length.

The implementation does not solve the mismatch by inventing/repeating a latent token.

### Decoded-audio timebase conformance

The inverse problem also appears after H3 audio-VAE decode. A video-valid clip such as 362 frames does not represent an integer number of 40 Hz audio ticks, so the decoded waveform can be a few hundred samples shorter than the exact picture timeline.

For small grid-sized mismatches, `existing_video_extension.py` uses `_conform_waveform_length()` to resample the decoded waveform by the tiny rational ratio required to reach the exact frame-derived sample span. This happens **before** the protected-context samples are removed. The seam cut itself then uses absolute frame-to-sample boundaries.

The conformance path is deliberately bounded (`max_fractional_change=0.005` by default). A larger mismatch is treated as a real error rather than being silently stretched. The implementation does not append a zero/silence tail for these normal H3 grid undershoots.

---

## 5. Noise-mask semantics

The latent-masking workflows use per-stream H3 noise masks.

Conceptually:

```text
0 = preserve / do not denoise this known token
1 = denoise / generate this token
```

For a normal continuation:

```text
VIDEO: [ protected previous context ][ generate future ... ]
MASK:  [ 0 0 0 0 ...               ][ 1 1 1 1 ...      ]
```

For an AV continuation:

```text
VIDEO: [ protected AV prefix ][ future ]
AUDIO: [ protected AV prefix ][ future ]
```

both streams can have a protected prefix.

For the master-song music-video workflow:

```text
VIDEO MASK: protected previous visual prefix = 0, future = 1
AUDIO MASK: entire master-song audio latent = 0
```

The song is therefore treated as authoritative target content rather than something H3 must reconstruct through denoising.

---

## 6. `H3 Existing Video Masked Context`

Class:

```text
MiniMaxH3ExistingVideoMaskedContext
```

Purpose: start a latent-masked H3 continuation from a normal decoded video/audio source for which no original H3 sampler latent exists.

The node:

1. normalizes source timing to the H3 24 fps timeline;
2. selects the final requested context window;
3. snaps a masked prefix to a valid H3 video run where required;
4. resizes/crops source frames to the target H3 geometry;
5. VAE-encodes the source video tail;
6. takes the matching physical audio interval and audio-VAE encodes it;
7. writes both encoded streams into the beginning of the fresh target AV latent;
8. creates video/audio masks protecting that prefix;
9. leaves the rest of the target denoisable.

This node is normally used only for the **first** generated extension after an arbitrary uploaded video.

---

## 7. `H3 Generated AV Masked Context`

Class:

```text
MiniMaxH3GeneratedAVMaskedContext
```

Purpose: continue from a previous **generated H3 clip** without decoding and re-encoding its continuation context.

The previous sampler already contains the H3 video/audio latent representation. The node therefore copies the previous clip's final valid AV latent run directly into the next target's prefix.

For a 39-frame continuation window, it derives the corresponding H3 video-latent and audio-latent lengths, copies the tail, and protects the copied prefix with mask `0`.

Advantages:

- no previous-clip video decode → VAE encode round trip for continuation conditioning;
- no previous-clip audio decode → audio VAE encode round trip;
- smaller continuation path;
- exact use of the generated H3 representation.

Source and target latent geometry must match, so chained clips should keep the same H3 resolution/model configuration.

---

## 8. `H3 Masked AV Bridge`

Class:

```text
MiniMaxH3MaskedAVBridge
```

Purpose: generate a missing middle section between two known audiovisual endpoints.

The node places:

- the end of source A into the beginning of the target latent;
- the beginning of source B into the end of the target latent;
- mask `0` on the known endpoint regions;
- mask `1` over the unknown middle.

H3 then generates only the middle region.

The delivered workflow still uses visual overlap treatment at the final source/generated joins because decoded source pixels and VAE-reconstructed generated endpoint pixels can differ slightly even when they represent the same content.

---

## 9. Master-song latent masking

Class:

```text
MiniMaxH3SongMaskedAVContext
```

Display name:

```text
H3 Song Audio + Masked Video Context
```

Purpose: make one original song the authoritative audio timeline for a multi-clip H3 music video.

For each clip the node:

1. inspects the target H3 AV latent;
2. determines the target video duration and target audio-grid length;
3. selects the appropriate interval of the complete master song from `clip_start_seconds`;
4. resamples to the H3 audio-VAE input rate when required;
5. audio-VAE encodes enough waveform to fill the target H3 audio grid;
6. writes that audio latent into the target audio stream;
7. sets the complete audio denoise mask to `0`;
8. optionally inserts/protects previous visual context at the beginning of the target video stream;
9. leaves the new visual region denoisable.

The final delivered music video uses the original master song, not a chain of decoded H3-generated audio clips.

### Clip start timing

For equal-sized raw H3 clips with a protected visual overlap:

```text
raw clip duration = raw_frame_count / 24
context duration  = context_frames / 24
new timeline advance = (raw_frame_count - context_frames) / 24
```

Therefore:

```text
Clip N start = (N - 1) * new timeline advance
```

The song slices overlap by the same physical time interval as the visual continuation context.

---

## 10. Reference images and Ref2VA

Reference images and latent continuation have different jobs.

A reference image primarily defines stable identity/appearance.

The protected continuation context defines the current physical state at the clip boundary:

- pose;
- current expression;
- camera framing;
- camera trajectory;
- motion;
- lighting state;
- environment/object state.

The current workflows therefore allow native `MiniMaxH3ReferenceToVideo` conditioning to coexist with latent-masked continuation.

`H3 Optional Reference Image` is a lazy helper node used by the multi-clip extension workflow. Disabled slots return no image; enabled slots request the connected image and pass it into the normal H3 reference input.

---

## 11. Legacy `H3 Motion Context`

Class:

```text
MiniMaxH3MotionContext
```

The legacy workflows do **not** insert previous content into the target latent. Instead they create native H3 guide/keyframe conditioning.

Current classic Motion Context uses ComfyUI's native H3 guide architecture.

Important concepts:

- previous visual frames become native H3 video guide data;
- timeline audio can become native H3 audio-guide data;
- ordinary Ref2VA references remain in their normal reference-conditioning path;
- ComfyUI combines native guide and reference payloads.

### Native video run vs per-frame fallback

For an exact H3 video run such as 39 frames, Motion Context can VAE-encode the whole temporal guide in one call.

For an arbitrary off-grid context length, the implementation can fall back to per-frame/still-guide representation so the requested endpoint is preserved rather than silently changing the context length.

This is different from target-latent masking, where the protected prefix itself must map cleanly into H3's target temporal latent.

---

## 12. Motion Context trimming and legacy assembly

A classic guide-based continuation repeats the guided visual prefix at the beginning of the generated output.

`H3 Motion Context Trim` removes that repeated region for delivery and can keep a smaller visual overlap specifically for a final blend.

The legacy workflows historically used KJNodes `ImageBatchExtendWithOverlap` to accumulate and blend clips.

That visual blend is valid; the long-form memory problem came from the **cumulative tensor topology**:

```text
clip 1 + clip 2 -> large IMAGE batch
large batch + clip 3 -> larger IMAGE batch
larger batch + clip 4 -> ...
```

The historical Update-5 checkpoint assemblers preserved the blend operation while avoiding the ever-growing ComfyUI image batch.

---

## 13. Current Update-6 direct VHS final streaming

The current long-form workflows use direct single-pass streaming backed by VideoHelperSuite:

- `H3 Stream Final AV Extension to VHS` (`MiniMaxH3StreamLiveExtensionAVToVHS`) is the AV Extension output node.
- `H3 Stream Final Music Video to VHS` (`MiniMaxH3StreamLiveMusicVideoToVHS`) performs the Music Video encode and returns `VHS_FILENAMES`; `H3 Final Stream Output Sink` (`MiniMaxH3FinalizeVHSOutput`) is the terminal output node for that workflow.

The Music Video streamer is intentionally an intermediate-output node. Keeping the tiny filename sink one graph step after it prevents the streamer's all-clips dependency chain from competing with each clip-local `VAEDecode -> VHS Video Combine` preview as an equally direct output dependency.

A normal ComfyUI `IMAGE` output is a materialized tensor. For long H3 timelines, a complete RGB float32 movie can therefore consume tens of GiB before the encoder even starts. The Update-6 streaming nodes avoid exposing the final movie as an `IMAGE` output.

The internal frame source is a one-shot sequence tailored to the access pattern used by `VHS_VideoCombine`: VHS asks for `len(images)`, probes `images[0]` for dimensions, and then iterates the source. The sequence primes the generator once so Clip 1 is not decoded twice.

Final filename allocation is intentionally left to VHS. The H3 streaming layer passes through `filename_prefix` but does not construct, overwrite, rename, or delete final output paths. VHS therefore owns its normal numbered-output counter across repeated runs. This is a release invariant: final H3 output code must not return to a fixed filename that replaces the previous run.

For generated clips, the streamer:

1. decodes one H3 video latent to CPU float32;
2. computes the same effective overlap rule as the old assembler (`min(requested_overlap, effective_context, written_timeline)`);
3. keeps only the tail needed for the next seam;
4. linearly blends that retained tail against the matching decoded context of the next clip;
5. yields completed frames to VHS;
6. releases the decoded clip before continuing.

For an uploaded Existing Video source, source frames are CFR-indexed to 24 fps and resized in small chunks; only the source seam tail is retained before generated Extension 1.

The AV streamer builds the final audio waveform separately using exact absolute sample boundaries and the decoded-audio timebase conformance described above. The Music Video streamer passes the original master waveform through unchanged.

### Inline VHS preview refresh

The current controllers own real ComfyUI bypass mode for preview groups. VideoHelperSuite can return the same temp filename/type/format after overwriting a completed preview. Its normal `updateParameters()` path may treat those parameters as unchanged and skip the visible inline refresh.

For controller-managed preview groups only, the H3 frontend detects that exact same-result condition. After VHS's normal execution handler has run, it invalidates only the stored filename and calls VHS's own `updateParameters(params, true)` once. It does **not** directly call the video widget's `updateSource()` method, avoiding the partial/truncated reload behavior seen with forced source refreshes.

### ComfyUI result caching

The streaming nodes bound the RAM used by final RGB assembly, but they do not control ComfyUI's node-result cache. ComfyUI's default RAM-pressure cache can retain sampler/latent results between nodes and runs until its own pressure thresholds decide to evict them. This can make total process RAM rise across a long chain even when final streaming itself remains bounded.

The workflow JSON does not select a cache policy. `--cache-none` is useful as a diagnostic because it disables result reuse and lowers RAM/VRAM use, but it also recomputes every node on each manual run; it is not required for the Update-6 workflows. Bounded or RAM-pressure cache choices remain a ComfyUI runtime decision.

---

## 14. Historical Update-5 checkpoint format

Update 5 long-form workflows saved each completed H3 joint AV sampler output using:

```text
H3 Checkpoint Save
```

The checkpoint is a safetensors file containing at least:

```text
video
audio
```

for the H3 video/audio latent streams.

Fixed clip slots use names like:

```text
clip_00001.safetensors
clip_00002.safetensors
...
```

The save is designed to be atomic so a failed/interrupted write does not silently replace a valid completed checkpoint with a partial file.

### Why save latents rather than intermediate MP4s?

Latents:

- avoid lossy intermediate video encoding;
- are much smaller than decoded full-resolution frame batches;
- preserve the expensive sampler result;
- can be decoded again for final assembly;
- can provide continuation context after restarting ComfyUI.

---

## 15. Historical Update-5 lazy resume

The Update-5 architecture supported resume at **completed clip boundaries**.

The repository does not attempt to resume a sampler halfway through its diffusion steps.

### Music-video resume

`H3 Resume / Live Tail Frames` has a lazy live input.

Normal run:

```text
use live previous clip
```

Resume run:

```text
load previous completed checkpoint
-> decode only the visual information required for the next continuation
-> do not request the earlier live generation branch
```

Because the live input is lazy, ComfyUI can skip the earlier upstream clip tree when the checkpoint path is selected.

### AV-extension resume

`H3 Resume / Live AV Latent` performs the equivalent job for workflows that want the previous **joint H3 AV latent** rather than decoded tail frames.

This allows the multi-clip masked AV extension to continue directly from a saved previous latent.

---

## 16. Historical Update-5 final checkpoint trigger

`H3 Checkpoint Final Trigger` is a lazy dependency helper.

Its job is to make final assembly depend on only the configured last active checkpoint rather than eagerly requesting every optional clip group.

This is especially important in workflows with many available slots but only some active clips.

---

## 17. Historical Update-5 music-video checkpoint assembly

`H3 Assemble Checkpoints` assembled the Update-5 master-song music video from saved H3 checkpoints.

It deliberately does not create one final ComfyUI `IMAGE` output containing the complete movie.

The process is approximately:

```text
load checkpoint 1
-> decode clip 1
-> write completed frames
-> retain only overlap tail
-> release clip 1

load checkpoint 2
-> decode clip 2
-> blend previous tail with current overlap
-> write completed frames
-> retain only next overlap tail
-> release clip 2

...
```

### Linear blend

The implementation matches the source-side KJNodes `linear_blend` convention used by the previous workflow.

For an overlap of `N` frames, alpha values are the interior values of:

```python
linspace(0, 1, N + 2)[1:-1]
```

and each overlap frame is:

```text
(1 - alpha) * previous_tail + alpha * current_overlap
```

The endpoints therefore do not use exact alpha 0 or 1 inside the blended overlap.

Every adjacent clip pair is still blended. For 20 clips there can be 19 seams.

### Output streaming

Decoded images remain floating-point while the seam is calculated. Completed frames are then quantized to RGB24 at the final ffmpeg streaming boundary.

The final H.264 encode happens once.

For the master-song workflow, ffmpeg muxes the original master audio.

---

## 18. Historical Update-5 existing-video checkpoint assembly

`H3 Assemble Extension Checkpoints` performs the corresponding job for normal audiovisual extension.

Update 5 additionally introduced `H3 Start Masked Context`, `H3 Start Canvas Selector`, and `H3 Assemble Starter + Extension Checkpoints` so the same multi-clip masked-AV workflow could either begin from an uploaded source video or from a generated starter clip (pure T2V or I2V). The starter path was also checkpointed and assembled sequentially, so it kept the same low-memory / low-OOM behavior as the source-video path.

Unlike the music-video workflow, generated H3 audio is part of the delivered continuation.

The assembler therefore:

- starts with the original source video/audio;
- loads generated checkpoints sequentially;
- decodes video one clip at a time;
- blends every visual seam;
- decodes generated audio;
- removes the duplicated protected AV prefix from the delivered continuation audio;
- fits audio segments to the exact frame-derived sample timeline so small latent-grid rounding differences do not accumulate;
- streams the final result to ffmpeg.

---

## 19. Historical checkpoint-memory rationale

A decoded ComfyUI `IMAGE` batch is normally a floating-point tensor.

A long sequence at high resolution can therefore consume many gigabytes even before additional intermediate tensors are considered.

With cumulative overlap nodes, multiple increasingly large intermediate batches can coexist because they are graph outputs/cacheable values.

Sequential checkpoint assembly changes the memory shape from approximately:

```text
all clips + all cumulative intermediate movies
```

to:

```text
one decoded clip + one small overlap tail + encoder/runtime overhead
```

Disk becomes the durable intermediate store, while RAM remains bounded by the current clip rather than total movie length.

---

## 20. Runtime compatibility layers

The repository has historically supported ComfyUI versions at different stages of H3 feature development.

The guiding rule now is:

> Use native ComfyUI behavior when the required capability exists. Install compatibility behavior only for the specific missing capability needed by the executed node.

### Native guide compatibility

`h3_compat.py` covers the classic Motion Context/native-guide requirements.

The current capability check verifies live behavior rather than depending on one exact source-code spelling.

It also checks only capabilities relevant to the current conditioning:

- simple Motion Context without refs does not require Ref2VA merge behavior;
- video/image refs require the video merge behavior;
- audio refs require the audio merge behavior.

This avoids false negatives such as the environment reported in repository Issue #7.

### AV-mask compatibility

`h3_mask_compat.py` and `h3_mask_payload_compat.py` cover the target-latent video/audio denoise-mask path.

The mask layer is kept separate from normal Motion Context so using a legacy guide workflow does not unnecessarily install masked-target compatibility behavior.

Detection is capability-oriented so newer native ComfyUI support can make the fallback path retire itself.

PR #15375 changed its internal integration on 2026-08-15 (commit `989e7a9`): the earlier `MiniMaxH3.process_denoise_mask` preprocessing hook was removed, and token-grid mask/blend alignment moved into `MiniMaxH3.scale_latent_inpaint(..., x=..., denoise_mask=...)`. The compatibility layer recognizes both layouts. On a ComfyUI build with the newer native architecture it does **not** reinstall the older preprocessing hook; native mask alignment and payload handling remain authoritative.

The workflow-facing mask contract is unchanged: `0 = preserve`, `1 = generate`, with fractional audio values allowed for the AV feather. The current PR quantizes fractional mask strengths to a bounded set of levels before deriving per-row timesteps, so the Update-6 half-cosine audio feather remains compatible with the newer native implementation.

---

## 21. Main node reference

### Guide/legacy nodes

| Display name | Purpose |
|---|---|
| H3 Motion Context | Native H3 previous-motion/audio guide conditioning |
| H3 Motion Context Trim | Remove repeated guide prefix and produce delivery overlap |
| H3 Motion Context Save Latent | Older Motion Context latent persistence helper |
| H3 Motion Context Load Latent | Older Motion Context latent load helper |
| H3 Custom Keyframes | Native H3 still-image anchors at chosen timeline positions |

### Latent-masking nodes

| Display name | Purpose |
|---|---|
| H3 Existing Video Masked Context | Start masked continuation from ordinary decoded source AV |
| H3 Generated AV Masked Context | Continue from a previous generated H3 AV latent directly |
| H3 Masked AV Bridge | Protect source A/B endpoints and generate the middle |
| H3 Song Audio + Masked Video Context | Put the master-song interval into target audio latent and optionally protect previous visual context |
| H3 Optional Reference Image | Lazy optional global reference-image slot |
| H3 Crop Source To /32 | Prepare source image geometry for H3 workflows |

### Direct-latent long-form nodes

| Display name | Purpose |
|---|---|
| H3 Start Masked Context | First-extension selector: source-video prefix or generated-starter latent tail |
| H3 Start Canvas Selector | Shared source/generated resolution selector |
| H3 Stream Final AV Extension to VHS | Decode source/starter + 1–6 live extensions sequentially and stream completed frames directly into VHS without a full final IMAGE movie tensor |
| H3 Song Audio + Masked Video Context | Insert the exact master-song slice and optionally copy the previous generated video latent tail |
| H3 Stream Final Music Video to VHS | Decode up to 20 live clip latents sequentially and stream directly into VHS while passing the untouched master song |
| H3 Final Stream Output Sink | Terminal `VHS_FILENAMES` sink used by Music Video to keep clip-preview scheduling ahead of the all-clips final-stream dependency chain |
| H3 AV Extension Controller | Start mode, active extension count, audio feather, and preview policy |
| H3 Music Video Controller | Active clip count and preview policy |

The Update-5 checkpoint/resume nodes are no longer registered in Update 6. The historical sections above remain only to document the previous implementation and migration context.

---

## 22. Workflow categories

Only the two current Update-6 workflows use the `NEW -` prefix:

### `NEW - AV Extension.json`

General long-form extension from an existing video or generated T2V/I2V starter, with optional global image/audio references.

### `NEW - Music Video.json`

Long-form song-driven generation with exact master-song slices and direct previous-latent continuation.

Secondary examples are clearly separated:

- `UTILITY - AV Bridge.json`
- `UTILITY - Custom Keyframes.json`
- `OLD - Motion Context - Simple.json`
- `OLD - Motion Context - Advanced.json`
- `OLD - Hybrid Extension.json`

Direct latent continuation is an implementation detail of the two current workflows, not a separate workflow category.

---

## 23. Testing

The repository contains CPU/static/mock regression tests because full H3 inference requires the user's ComfyUI model/runtime installation.

The tests cover, among other things:

- native Motion Context structure;
- Simple and Advanced legacy workflow wiring;
- native guide/reference compatibility detection;
- per-token AV mask capabilities;
- existing-video extension behavior;
- direct generated-AV latent continuation;
- master-song audio masking;
- the one-token audio-grid boundary regression;
- direct-stream final workflow wiring and absence of a separate full-movie VHS input chain;
- absence of the superseded materialized full-movie Update-6 assembler nodes;
- Music Video intermediate-stream/terminal-sink scheduling topology;
- same-result VHS inline-preview refresh behavior;
- exact decoded-audio timebase conformance and no-silence-tail regression;
- streamed-frame equivalence against the former full-buffer seam math;
- one-shot VHS frame-sequence behavior;
- workflow JSON consistency.

Run the standalone repository regressions with:

```bash
pytest -q
```

The pytest entry point delegates to the isolated mock runner because several test modules intentionally install different lightweight ComfyUI mocks. The same underlying checks can also be run directly with `python tests/run_tests.py`.

---

## 24. Additional focused references

- [MODIFICATIONS.md](MODIFICATIONS.md) — release history.
- [example_workflows/README.md](example_workflows/README.md) — practical usage notes for the included workflows.

---

## 25. Audio-reactive analysis and feature tracking

### Relationship to master-song audio masking

`H3 Song Audio + Masked Video Context` (section 9) guarantees that the delivered audio is the original master song by injecting pre-encoded audio latents and enforcing $M_{\text{audio}} = 0$. The audio-reactive nodes solve the complementary problem: making the **visual generation** respond dynamically to what is happening in the music (beats, energy envelopes, spectral brightness, transients, and isolated frequency bands).

MiniMax H3 generates an entire clip at once in 3D spatio-temporal latent space (not frame-by-frame autoregressively). The reactive signals are therefore applied across two distinct operational tiers:

1. **Clip-level modulation**: aggregate a per-frame curve into one scalar per clip (peak energy, mean brightness, beat density) via `MiniMaxH3AudioReactiveDenoise` to drive sampler denoise strength (e.g., subtle 0.70 during verses, energetic 1.00 at drops), CFG scale, or prompt weights for that clip's generation.
2. **Timeline and multi-clip sequencing**: use beat frame indices to establish exact harmonic cut points ($N_f = 51m + 39$), or route energy/spectral curves to `MiniMaxH3CustomKeyframes` and reference image selectors to switch visual styles on predetermined musical cues.

### Core node suite

| Display name | Class | Purpose |
|---|---|---|
| H3 Audio Analyze | `MiniMaxH3AudioAnalyze` | Extract per-frame RMS energy, beat pulse, spectral brightness, onset strength, and bass/mids/highs frequency bands from a master song interval |
| H3 Audio-Reactive Denoise | `MiniMaxH3AudioReactiveDenoise` | Reduce any per-frame audio curve to a single denoise strength scalar (`peak`, `mean`, `median`, with optional inversion) |
| H3 Audio Curve Remap | `MiniMaxH3AudioCurveRemap` | Smooth, power-law shape (`gamma`), noise gate (`threshold`), and range-remap any per-frame audio curve |

### Analysis signals (24 fps grid)

All features operate on the 24 fps H3 video grid and produce one normalized float per frame ($[0.0, 1.0]$):

| Feature | Signal | Internal Mechanism | Typical Use |
|---|---|---|---|
| RMS energy (`energy`) | Per-frame loudness envelope | Moving RMS over sample window | Denoise modulation: calm = subtle, loud = dramatic |
| Beat pulse (`beats`) | Beat impulse + exponential decay | Adaptive peak / librosa beat track | Cut-on-beat editing, rhythmic visual pulse |
| Spectral centroid (`brightness`) | Physical spectral brightness | First spectral moment / Nyquist ($f_{\text{Nyq}} = \frac{\text{sr}}{2}$) | Color/mood shifting: dark tones vs bright tones |
| Onset strength (`onsets`) | Transient detection | Spectral flux (half-wave rectified diff) | Cymbal hits, drum transients, vocal entrances |
| Bass (`bass`) | Low frequency energy (20–250 Hz) | Bandpass FFT bin power | Kick drum, bassline visual scale |
| Mids (`mids`) | Mid frequency energy (250–4000 Hz) | Bandpass FFT bin power | Vocal presence, melody-driven motion |
| Highs (`highs`) | High frequency energy (4000 Hz+) | Bandpass FFT bin power | Hi-hats, shimmer, particle effects |

### Cross-ecosystem node compatibility

The signals emitted by `H3 Audio Analyze` output standard ComfyUI `FLOAT` lists, making them directly interoperable with external audio nodes:

- **`ComfyUI-AudioScheduler`** (`BatchAmplitudeSchedule`, `NormalizedAmplitudeDrivenString`): Drive dynamic prompt switching on energy thresholds.
- **`ComfyUI-AudioReactive`** (`OpPercussive`, `OpHarmonic`, `SignalToCurve`): Separate harmonic and percussive layers for dual-stream conditioning.
- **`ComfyUI_AudioTools`** (`Stem Separator AI`): Isolate dry vocals using Demucs before routing to `MiniMaxH3SongMaskedAVContext`, optimizing cross-modal lip-sync attention.
- **`ComfyUI_Fill-Nodes`** (`FL_Audio_BPM_Analyzer`): Global tempo detection and grid alignment.

---

## 26. Conditioning paradigms and cross-modal binding

### Cross-modal prompt directives (Qwen3-VL-32B)

The underlying text encoder possesses joint acoustic-visual semantic alignments. Synchronization markers such as `"as"`, `"when"`, and `"then"` bind sharp acoustic transients directly to visual actions within the diffusion attention layers:
- Declarative environmental clauses establish ambient acoustic beds.
- Explicit temporal sequencing instructs the model to align visual state transitions with sonic impacts.

### Multimodal conditioning modes

1. **Reference-to-Video (Ref2VA)**: Accepts up to 9 reference images, 3 reference videos, and 3 reference audio clips. Reference audio guides vocal timbre, acoustic ambiance, and musical style without locking temporal positions.
2. **First/Last Frame to Video (FL2VA)**: Dictates structural trajectories between explicit image keyframes, allowing visual events to match broad musical transitions.
3. **Custom Keyframes**: Injects static image anchors at arbitrary internal timeline indices ($t_k \in [0, N_f]$), forcing the visual diffusion trajectory to intersect specific compositions on predetermined musical beats.

### Per-token latent masking & acoustic feathering

For exact lip synchronization and beat-locked choreography:
- **Audio Stream**: Locked completely ($M_{\text{audio}} = 0$) with master audio encoded directly into target latents.
- **Video Stream**: Context tail from previous clip is preserved ($M_{\text{video}} = 0$ for $t \le T_{\text{context}}$), while the remainder is generated ($M_{\text{video}} = 1$).
- **Acoustic Boundary Smoothing**: To prevent seam clicks across continuation segments, an 8-tick ($0.2\text{ s}$) half-cosine feather is applied to the audio transition boundary:

$$\alpha(t) = \frac{1}{2} \left(1 - \cos\left(\frac{\pi t}{T_{\text{feather}}}\right)\right) \quad \text{for } t \in [0, T_{\text{feather}}]$$

---

## 27. Comparative analysis of diffusion video architectures

| Architectural Vector | MiniMax H3 (Masked AV Pipeline) | LTX-Video 2.3 (Audio-Reactive LoRA) | CogVideoX / AnimateDiff (Signal Travel) |
|---|---|---|---|
| **Model Type** | Native Omni-Modal DiT (Joint Video/Audio) | Decoupled Video DiT + Audio Cross-Attention LoRA | Video Diffusion + Injected Temporal Attention Layers |
| **Native Frame Rate** | 24 fps (Quantized to $17k+5$) | 24 / 25 fps | 8 / 16 / 24 fps |
| **Audio Clock** | 40 Hz Latent Space | External Feature Map / FFT Conditioning | External Curve (Per-Frame Float Schedules) |
| **Lip-Sync Precision** | Exact Sub-Frame (via Audio Latent Masking $M_a=0$) | Approximate / Stylistic Rhythmic Sync | Post-Process Dubbing / Latent Warp Required |
| **Multi-Clip Chaining** | Direct AV Latent Tail Copying ($N_f = 51m + 39$) | Iterative Image-to-Video Seed Chaining | Context Sliding Window / Latent Blending |
| **Acoustic Fidelity** | Master Track Passthrough with Zero Distortion | Video-only; audio multiplexed externally | Video-only; audio multiplexed externally |
| **Peak Memory Profile** | Streamed Frame Pipe (Bounded to 1 Clip in RAM) | Bounded Frame Batches | Cumulative Latent Accumulation |

---

## 28. Diagnostic procedures and troubleshooting

### 1. Audio-grid boundary shortfall ($T_a - 1$ token floor)
- **Symptom**: Sampler dimension mismatch crash when encoding master audio into a target latent (e.g. 206 tokens produced instead of 207 for a 124-frame target).
- **Cause**: Downward sample flooring inside the audio VAE.
- **Resolution**: The feeder node reads the authoritative target latent dimension ($T_{a,\text{target}}$), computes the required PCM sample window with lookahead padding:
  $$N_{\text{samples}} = \left\lceil T_{a,\text{target}} \times \frac{\text{SampleRate}}{40} \right\rceil + \text{Padding}$$
  encodes the waveform, and slices the tensor to the exact target length rather than padding with zero tokens.

### 2. Visual seam ghosting in multi-clip assembly
- **Symptom**: Double-exposure artifacts across the 39-frame continuation window.
- **Cause**: Applying fractional noise masks directly to video latents.
- **Resolution**: Video latent masking must remain strictly binary ($M_v = 0$ for protected context, $M_v = 1$ for generative synthesis). Fractional blending is reserved exclusively for CPU-level linear pixel interpolation inside the final streaming node (`MiniMaxH3StreamLiveMusicVideoToVHS`).

### 3. CUDA out-of-memory during Ref2VA execution
- **Symptom**: VRAM exhaustion when combining multiple high-resolution reference images with video context.
- **Resolution**: Pass all image inputs through `H3 Crop Source To /32` to conform dimensions to modulo-32 boundaries, and enable SageAttention via `Patch Sage Attention KJ` to reduce cross-attention memory overhead.

### 4. Controller-owned preview invalidation
- **Symptom**: VideoHelperSuite inline preview players display stale or black frames during iterative multi-clip generation.
- **Resolution**: `H3 Music Video Controller` and `H3 AV Extension Controller` enforce real ComfyUI group bypass and trigger targeted frontend parameter invalidation (`updateParameters(params, true)`), refreshing the user interface reliably without causing browser-side video player crashes.

