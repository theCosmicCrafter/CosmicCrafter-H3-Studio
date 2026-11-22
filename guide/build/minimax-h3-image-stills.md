# Stills with MiniMax H3 Image

**MiniMax H3 Image Still** wraps the official native ComfyUI image workflow in
one node. Its **still_recipe** output connects directly to the Timeline's
**still_recipe** input. Its **image** output can also feed Preview or Save Image.
Load `examples/minimax_h3_image_story_studio.json` for an already connected example.

## Install

Update ComfyUI to a version that includes **MiniMaxH3ImageConditioning** (native
support added November 10, 2026), then restart ComfyUI. The node reports a missing
core node when an older installation attempts image generation. No additional
custom image nodes are needed.

Download the weights from [Comfy-Org/MiniMax-H3-Image](https://huggingface.co/Comfy-Org/MiniMax-H3-Image):

| Component | File | ComfyUI folder |
| --- | --- | --- |
| Diffusion model | `minimax_h3_image_pruned_int8_convrot.safetensors` (about 21 GB) | `models/diffusion_models` |
| Text encoder | `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` | `models/text_encoders` |
| Image VAE | `minimax_h3_image_vae_fp16.safetensors` (about 1.2 GB) | `models/vae` |

The bf16 and W4A8 diffusion variants also work. Reuse your existing official
Qwen3-VL MiniMax H3 text encoder if installed; bf16 and int8_convrot encoder
variants are also supported. The image VAE and diffusion model are different
from the H3 video and Pruna P-H3-Image files.

For example, downloading just the diffusion model and image VAE:

```bash
hf download Comfy-Org/MiniMax-H3-Image diffusion_models/minimax_h3_image_pruned_int8_convrot.safetensors vae/minimax_h3_image_vae_fp16.safetensors --local-dir ComfyUI/models
```

Read the [MiniMax H3 Image license](https://huggingface.co/MiniMaxAI/MiniMax-H3-Image/blob/main/LICENSE),
which differs from the video model's license.

## Generate a guide

Select your diffusion model, text encoder and image VAE on **MiniMax H3 Image
Still**, then connect its **still_recipe** output to Timeline **still_recipe**.
In the Studio, select a First, Last or Shot marker, choose **Generate candidates**,
and accept an image with **Use as guide**.

Optionally connect a **LORA_STACK** output, such as Easy Use's LoRA stack, to
**lora_stack**. Each entry is `(filename, model strength, CLIP strength)`. Entries
apply in order to the diffusion model and conditioning text encoder for both
direct images and Studio candidates. Use LoRAs compatible with MiniMax H3 Image.
An unconnected or empty stack leaves generation unchanged; entries named `None`
and entries with both strengths at zero are skipped.

The Studio uses the selected clip's prompt exactly, without adding shared text,
reference descriptions or the generator's instruction. It fills the seed and
reference images for each request, putting the location first when one is
available. Prompts use native `<Picture 1>`, `<Picture 2>` labels. Up to eight
references are exposed here.
Sampling follows the [official workflow](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/image_minimax_h3_image_t2i.json):
six Euler steps, simple schedule, CFG 1. Dimensions are explicit, default to
2048 × 2048 and must be multiples of 32. Studio generation uses these dimensions
unless the request supplies a still size. There is no implicit P-H3 8 MP resize.
The official template starts at a reduced size and recommends about 16 MP for
quality when memory permits (4096 × 4096 square or 5472 × 3072 widescreen).

Set **megapixels** above 0 to generate at that area instead. Width and height
then only set the aspect ratio, so you can connect the video size directly: 1152
× 640 at 20 MP generates 6016 × 3328. Each side is rounded to a multiple of 32
and must stay within 8192. At 0, width and height are used exactly.

Reference images are separately resized to 4 MP and aligned to a multiple of 32,
matching the [official edit workflow](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/image_minimax_h3_image_edit.json).
The requested output remains native resolution: a 20 MP output is sampled at
20 MP. Candidate metadata records the separate reference resize setting.

## Prompt enhancer

The prompt is sent as written by default. The official ComfyUI workflows can
first rewrite it with a Qwen3.5 model and **Generate Text** (`TextGenerateV2`)
into a detailed description that names each reference picture's role. This
optional step uses the instructions of the
[official edit](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/image_minimax_h3_image_edit.json)
and [text-to-image](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/image_minimax_h3_image_t2i.json)
templates, unchanged.

**prompt_enhancer** controls this step:

| Setting | Behavior |
| --- | --- |
| `off` (default) | Always uses the prompt as written. |
| `auto` | Rewrites prompts that have reference pictures, as the official edit template does. Text-only prompts are used as written, as in the text-to-image template. |
| A model file | Also rewrites text-only prompts with that model. |

Download `text_encoders/qwen3.5_9b_w4a8_gptq.safetensors` from
[Comfy-Org/MiniMax-H3-Image](https://huggingface.co/Comfy-Org/MiniMax-H3-Image)
into `models/text_encoders`; `auto` also accepts another installed Qwen3.5 text
model such as `qwen3.5_9b_int8_convrot.safetensors`. Without one, `auto` uses the
prompt as written. The rewrite runs once per candidate with the candidate's
seed and adds the enhancer's generation time. If the enhancer returns no
caption, the candidate fails with its reply instead of generating from an empty
prompt. Candidate metadata records the **prompt_enhancer** setting.

## Location sheets

With reference pictures MiniMax H3 Image is an editing model: a location sheet
sent whole as `<Picture 1>` is the canvas being edited, so the still keeps its
grid, with or without the enhancer. For a clip still,
the Studio therefore sends a location or scene-layout reference that is a sheet
of views as one picture per view, cut at the sheet's divider lines, so the
location takes `<Picture 1>` to `<Picture 4>` for a 2 × 2 sheet and Cast pictures
follow. A mention of the location in the clip prompt names all its views. Views
that do not fit the eight reference slots are dropped from the end. Single
pictures, Cast character sheets and pinned frames are sent whole, as is every
reference of a still generated for a Cast entry. Candidate metadata lists each
view's crop. Each view is resized to 4 MP like any other reference, so a 2 × 2
sheet takes roughly twice as long to generate as the same sheet sent whole.

Video rendering does not execute or load the connected still model.
