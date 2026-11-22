# Nodes

All nodes appear under the **H3 Continuity** category.

## H3 Timeline

The heart of the pack. Draw clips in the Studio; each queued run renders the next clip that needs it.

| Input | Type | Notes |
| --- | --- | --- |
| `name` | string | Folder under `output/h3_sequences`. |
| `width`, `height` | int | Output size. |
| `context_frames` | 22, 39, 90, 141 | Frames each clip carries from the clip before (0.9 s, 1.6 s, 3.75 s, 5.9 s). |
| `carry_audio` | boolean | Also carry and freeze the matching audio. |
| `ref_image_size` | `match` or `max` | Reference image sizing, as in MiniMax H3 Reference to Video. |
| `audio_context_frames` | int | Incoming audio context in 24 fps frames; 0 follows video. |
| `timeline` | string | The clips as JSON, written by the editor. |
| `clip`, `vae`, `audio_vae` | optional | H3 CLIP, video VAE and audio VAE. Without the audio VAE, `@audio` references only label the prompt. |
| `images.imageN`, `videos.videoN`, `video_audios.…`, `audios.audioN` | optional | [Connected references](../build/references.md). |
| `negative` | optional | Negative conditioning. |
| `still_recipe` | optional | A [Still Recipe](../build/frame-guides.md); video rendering never evaluates it. |
| `still_image` | optional | The IMAGE output of [your own image workflow](../build/own-image-workflow-stills.md); video rendering never evaluates it. `still_recipe` is used when both are connected. |
| `story` | optional | From **H3 Story**. Renders never wait for it. |

| Output | Type |
| --- | --- |
| `positive`, `negative` | CONDITIONING |
| `latent` | LATENT (empty audio+video latent to sample) |
| `segment` | H3C_SEGMENT (to H3 Save Segment) |
| `seed` | INT |
| `prompt` | STRING |
| `info` | STRING |
| `image_1`, `image_2`… | IMAGE, the clip's final `<Picture N>` pixels |

## H3 Story

Plans and writes the Timeline's prompts through an OpenAI-compatible API. Output: `story`. Settings are on [the writer page](../story/writer.md). The `writing_mode` widget is retired (every Write uses Fast) and kept only so saved workflows load.

## H3 Save Segment

Saves the run as the next segment (the finished video without repeated frames, plus latents for the next run) and then rebuilds the full video.

| Input | Notes |
| --- | --- |
| `segment`, `latent` | From the Timeline and the sampler. |
| `images`, `audio` | Decoded frames and audio. Needed for the segment and full videos. |
| `fps` | 24 unless you interpolate. |
| `crf` | Video quality (H.264 or HEVC CRF); lower is better and larger. |
| `color_space` | HDR videos use 10-bit BT.2020. |
| `codec` | `H.264` (default) plays everywhere. `HEVC` is 10-bit Main10 for HDR and tagged `hvc1`, which phones decode in hardware and Apple players need to show HLG. A browser without HEVC support can't play these videos in the Studio. The full video keeps its segments' codec. |
| `description` | Text stored with the segment, such as the prompt. |
| `guide_frames` | Optional. The sampler's latent decoded as is, before any second pass. The next continuing clip is guided from its last played frame instead of the finished one, so a second-pass change does not change the next clip's first pass. See [Keep the first pass](../output/first-pass-cache.md). |
| `write_full_video` | Only affects the deprecated H3 Sequence chain; the Timeline always exports when every clip is done. |

## H3 Disk Cache

Saves the first-pass sampler's result on disk and loads it, without running the sampler, when a later run has the same keys and the same settings above the sampler. See [Keep the first pass](../output/first-pass-cache.md).

| Input | Notes |
| --- | --- |
| `result` | The sampler's output. Asked for only when no saved result matches. |
| `keys` | The Timeline's `positive`, `latent` and `seed`. |
| `mode` | `use`, `refresh` or `off`. |
| `namespace` | Folder under `output/h3c_cache/`. |

## H3 Continuation Model

Picks the model the sampler uses for this run: `continuation_model` when the Timeline's `segment` carries frames from the clip before (a continuing clip or a bridge), `model` otherwise. Put it between your model chain and the guider, for example with a LoRA meant only for continuations on `continuation_model`. See [Long continuing chains](../continuity/long-chains.md).

| Input | Notes |
| --- | --- |
| `model` | For clips that start fresh or cut. |
| `segment` | From H3 Timeline. |
| `continuation_model` | Optional. Unconnected, every clip uses `model`. |

## H3 Sigmas Tail

Experimental. Raises the last few noise levels before zero (`BasicScheduler → H3 Sigmas Tail → sampler sigmas`), so a distilled 8-step model settles less fine detail in its final step. Each moved level keeps its ratio to the level above the tail, raised to the power 1 / (1 + `strength`); the first level, the levels above the tail and the final zero stay. With `segment` connected, clips that start fresh or cut keep their schedule. Defaults: `tail_steps` 3, `strength` 0.5; 0 changes nothing.

## H3 Context Windows, H3 Join Chain

For [long clips](../build/long-clips.md). **Context Windows** wraps ComfyUI's MiniMax H3 Context Windows (model → model); **Join Chain** joins saved continuing segments into one latent for refinement.

## Still nodes

| Node | Purpose |
| --- | --- |
| **Still Recipe** | Wraps a native image generator's `IMAGE` output with `bindings` that say where its prompt, seed, size and references are. Connect it to the Timeline's `still_recipe`. |
| **MiniMax H3 Image Still** | Generates images with the official MiniMax H3 Image model in six steps. Connects directly to Timeline `still_recipe`; see [installation and connections](../build/minimax-h3-image-stills.md). |
| **H3 Still Conditioning** | Adapts a still generator invocation for pinned-source and reference presentation. Used inside the supplied H3 still examples. |
| **Still Image Source** | Supplies source pixels to a still request. |
| **H3 Timeline Image** | Resolved pixels for `<Picture N>` in the selected clip. |

## Deprecated

**H3 Sequence** and **H3 Continue** are the earlier chain-based way of continuing a sequence. Use **H3 Timeline** instead. They remain so old workflows load.
