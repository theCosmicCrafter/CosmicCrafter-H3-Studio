# P-H3-Image still node: design

Issue: [#21](https://github.com/KadoBOT/ComfyUI-H3-Continuity-Studio/issues/21). Status: **D1/D2 answered by the user 2026-11-04; spikes next.**

## Goal

One node, **P-H3-Image Still**, that a user drops next to the Timeline, points at the installed P-H3-Image files and wires to `still_recipe`. The Studio then generates First, Last and Shot stills with it, as ordinary candidates. No sampler, encoder, decoder or bindings JSON is built by hand.

## What upstream says (investigated 2026-11-04)

Sources: [PrunaAI/P-H3-Image-Comfy](https://huggingface.co/PrunaAI/P-H3-Image-Comfy) README (sha `44a0fb7`) and its `p-h3-image_text_to_image.json` and `p-h3-image_edit.json`; ComfyUI `comfy_extras/nodes_minimax_h3.py` at the local checkout (0.44.0, `56f179f6c`).

| Item | Finding |
|---|---|
| ComfyUI | Native, no custom nodes. Support is `PH3ImageConditioning` + `MiniMaxH3SigmaShift` in ComfyUI core (PR #17506). The local checkout's `v0.44.0` tag contains it; **confirm the first release tag upstream before documenting it**. |
| Files (one per component, mixable) | `diffusion_models/p-h3-image_{bf16,int8_convrot,w4a8}.safetensors`; `text_encoders/p-h3-image_text_encoder_{bf16,int8_convrot,w4a8}.safetensors`; `vae/p-h3-image_vae_{bf16,int8_convrot}.safetensors` (no w4a8 VAE); optional `text_encoders/p-h3-image_prompt_upsampler_{bf16,int8_convrot,w4a8}.safetensors`; `loras/p-h3-image_lora_bf16.safetensors` only for the "own MiniMax-H3" variant. |
| Not interchangeable | The video H3 weights, text encoders and VAEs are different files. Do not offer them. Select by the `p-h3-image` filename prefix. |
| Graph | `UNETLoader` (default) → `MiniMaxH3SigmaShift(1.0, 1.0)` → `BasicGuider`. `CLIPLoader` (type `minimax`) → `PH3ImageConditioning(clip, vae?, prompt, width, height, images…)` → positive + latent. `ManualSigmas` `1.0, 0.984753, 0.967905, 0.951688, 0.925372, 0.881923, 0.810083, 0.528718, 0.0` (8 steps), `KSamplerSelect euler`, `RandomNoise`, `SamplerCustomAdvanced`, `VAELoader` → `VAEDecode`. No CFG, no negative prompt. |
| Latent | `PH3ImageConditioning` builds the latent itself (a 1-frame AV latent, 16 px per latent cell, width/height multiples of 32). 0 means 2912 without images, or `image_1`'s scaled size with images. |
| Prompt upsampler | Optional. `CLIPLoader` (type `minimax`) on the upsampler file → `TextGenerate` (greedy, thinking on, max 2048; edit variant 3072, thinking off) fed by `StringFormat`: `Aspect ratio: W:H\nRequest: {a}` for text-to-image; for edits a `<|im_start|>user …<Picture N>: <|vision_start|><|image_pad|><|vision_end|>… Edit <Picture 1>. {a}<|im_end|>…<think>` block and `image` = Batch Images of `image_1` at 1 MP plus the references padded to its size. Upstream: short prompts are weak without it; long specific prompts are rendered much better. |
| References | Edit mode: `image_1` is the image being edited; up to 8 images (`image_1`..`image_9` exist on the node, upstream documents 8). The prompt names them `<Picture N>`. `PH3ImageConditioning` prefixes `Edit <Picture 1>. ` unless the prompt already starts with `Edit <Picture N>` or `subject_definitions:`. Images are encoded by the VAE at the output area; the text encoder sees them at ≤1 MP. |
| Sizes | Best at 8 MP for text-to-image, 4 or 8 MP for edits. Smaller sizes are not documented; **spike S2 measures 1024×576 and 1280×720**. |
| Memory | bf16 set peaks about 56 GB; int8 about 31 GB; w4a8 + int8 VAE about 21 GB; upsampler 9–21 GB more (offloaded when the model needs the memory). Local machine: RTX 5090 Laptop, 24 GB, so int8 or w4a8; the local folders already hold the int8 model, bf16 text encoder, int8 VAE and int8 upsampler. |
| License | MiniMax H3 Community License: excludes the EU, UK, South Korea and the US unless separately licensed; products must show "Powered by MiniMax H3". The setup guide must say so. |

## Existing contracts we reuse (read from code)

- `H3C_StillRecipe(image raw_link lazy, bindings)` returns the recipe; `Timeline.still_recipe` is `raw_link, lazy`. The video render never evaluates the image branch. Only `isolateVideoPrompt` strips it for Studio submissions.
- `web/h3c_stills.mjs: captureRecipe` turns the API prompt + UI workflow into a recipe with absolute locators. It accepts only a node of class `H3C_StillRecipe`, whose bindings JSON gives locators relative to the connected generator.
- `h3_continuity/image_recipe.py: prepare` binds prompt, seed, size and reference IMAGE ports in the captured graph, loads reference pixels through `H3C_StillImageSource`, writes provenance, and appends a `SaveImage`. Reference ports must be `IMAGE` or an autogrow of `IMAGE` (`_image_port`). Prompt text policy is chosen by generator (`qwen` branch for `TextEncodeQwenImage21`).
- `h3_continuity/story_context.py: renderer_for` decides image vs video Story writing from the recipe node class and `adapter == "pixels"`.
- `web/h3c_stills.mjs: recipeControls` reads seed, size, label, adapter and `reference_label` for the Studio.

## Design

### One node, native graph inside

`H3C_PH3ImageStill` (display name **P-H3-Image Still**, category `H3 Continuity`), a V3 node that **expands** into native nodes at execution (`io.NodeOutput(..., expand=GraphBuilder…)`). Expansion keeps ComfyUI's own loading, caching, offloading and progress, and is the same graph as the official workflow, so results match upstream. The node does not load or run models itself.

Inputs:

| Input | Notes |
|---|---|
| `diffusion_model`, `text_encoder`, `vae` | Combos from ComfyUI's standard lists (`folder_paths`, so `extra_model_paths.yaml` is honored), filtered to names starting `p-h3-image`; w4a8/int8/bf16 mixed freely. Empty list gives a message naming the folder and the Hugging Face file. |
| `prompt` (multiline), `seed`, `width`, `height` | The Studio's bindings. Width/height are multiples of 32 and checked. |
| `images` | `Autogrow` of `IMAGE` (`image_1`..`image_8`) so `_image_port` accepts it and reference labels are `<Picture {index}>`. |
| `prompt_upsampler` | Combo: `off` or an upsampler file. Default off for Studio use (see Decision D2). |
| `instruction` | Reusable text added after the prompt, as the other recipes. |

Outputs: `IMAGE` (slot 0) and `H3C_STILL_RECIPE` (slot 1, a self-describing recipe, see below). Use the IMAGE output for a preview/Save node, the recipe output for the Timeline.

### Self-describing recipe

The recipe output is a literal dict (`{"version": 2, "adapter": "pixels", "generator": "ph3image", "label": "P-H3-Image", "reference_limit": 8, "reference_label": "<Picture {index}>"}`), no bindings JSON. `captureRecipe` gains one branch: when `still_recipe` links to slot 1 of an `H3C_PH3ImageStill`, the node itself is the generator and the locators are its own inputs (`prompt`, `instruction`, `seed`, `width`, `height`, `images.image_1`..). Locator resolution reuses the same `resolve()` checks (live, not muted, class type matches). `H3C_StillRecipe` keeps working unchanged, so arbitrary generators and the Qwen examples are untouched. `renderer_for` treats the new class as `pixels`.

Open item (spike S1): verify a literal recipe at slot 1 coexists with the expanded IMAGE at slot 0. If not, fall back to a thin `H3C_PH3ImageStillRecipe` wrapper and keep everything else.

### Validation, with messages that name the problem

`validate_inputs` and `execute` check, before any model loads:

1. ComfyUI has `PH3ImageConditioning`/`MiniMaxH3SigmaShift`/`TextGenerate`; else "Update ComfyUI to the release that includes P-H3-Image (PR #17506) …".
2. Each selected file exists in its standard folder and has the `p-h3-image` prefix; a video H3 file picked by hand through a combo is refused with what to use instead.
3. Width/height multiples of 32 and ≥ 256; at most 8 images; images present ⇒ VAE selected (always is).
4. Selected upsampler is a `p-h3-image_prompt_upsampler` file.

Missing files appear while Timeline-only video rendering too, because ComfyUI validates linked nodes: the combos accept an explicit `(not installed) …` sentinel only for the unconnected case, so a video render without P-H3 files still validates. Spike S3 checks that exact behavior.

### Stills prompt policy (`p-h3-image-scene-v1`)

Mirrors the Qwen policy in `image_recipe.prepare`, with `<Picture N>` labels: the canvas reference (scene layout, location, anchor, action state) goes first so it is `image_1`, because P-H3 treats `image_1` as the edited image and takes its size when width/height are 0; identity, appearance and props follow with their role text; `Edit <Picture 1>. …` is added by the model node. When there are no references, plain text-to-image. Provenance records `prompt_policy`.

### Lazy / on-demand

`H3C_StillRecipe` and the new slot-1 output are never evaluated by the Timeline. Regression test: build an API prompt with the node connected to the Timeline and a video output; execute through ComfyUI's scheduler on the CPU with `UNETLoader` etc. replaced by sentinels that raise, and assert none ran (the same shape as the existing lazy tests).

## Decisions (user answers 2026-11-04 marked)

- **D1 variants (confirmed 2026-11-04):** standalone files only; the node lets the user pick any installed `p-h3-image` file per component, and verification uses the user's local files (int8_convrot model, bf16 text encoder, int8_convrot VAE, int8_convrot upsampler). The w4a8 files are untested here and documented as such. Details: bf16, int8_convrot and w4a8 sets from this repo's node; **not** the "LoRA on your own MiniMax-H3" variant in v1 (it needs a different graph and a second weights family, and the issue asks for the simple path).
- **D2 upsampler default (confirmed 2026-11-04):** off. The Studio's *Prepare still prompts* already writes long, specific prompts; the upsampler adds a 9–19 GB model and rewrites away the reference-role text. Keep it as an option and measure on spike S4; flip the default only if the evidence says so.
- **D3 reference behavior:** compose by listing the canvas first; verify with real images in S5 and write down what holds and what does not (do not promise geometry).
- **D4 location:** `h3_continuity/ph3_image_nodes.py`, registered in `extension.py`; example `examples/ph3_image_still.json` (node + Timeline wired to existing flows) and a guide page.

## Out of scope

Video H3 changes, LoRA variant, training, batching multiple images per request, in-Studio model download.

## Verification (acceptance criteria mapped)

Unit/CPU: recipe capture (JS), prepare/provenance (Python), schema/validation messages, lazy execution. Real: one P-H3-Image generation through the Studio on the shared GPU (ticket protocol), candidate applied to a Timeline target, then a video render of the same Timeline proving the still branch did not run; existing Qwen and Fizgig examples still capture and prepare (existing tests plus a fresh capture of each example).
