# Stills with your own image workflow

The Studio can generate stills and reference pictures through any ComfyUI image
workflow: your model, sampler, steps, LoRAs and custom nodes. Nothing from this
pack goes into that workflow. You wrap it in a native subgraph, name a few of its
inputs, and connect its image to the Timeline.

## Connect a workflow

1. Build or paste an image workflow in the same graph as the Timeline and check
   that it produces a picture.
2. Select its nodes and choose **Convert to Subgraph**.
3. Open the subgraph and expose the inputs listed below, with exactly these names.
4. Connect the subgraph's **IMAGE** output to the Timeline's **still_image** input.

Video renders never run this branch. The Studio queues it by itself when you
generate a still.

## Input names

| Input | Type | Needed | What the Studio does with it |
| --- | --- | --- | --- |
| `prompt` (or `positive_prompt`) | text | yes | Sets the still prompt. |
| `seed` (or `noise_seed`) | whole number | yes | Sets a seed for each candidate. Without it every candidate would be the same picture. |
| `width`, `height` | whole number | no | Sets the still size. Without them the workflow keeps its own size and the Studio cannot change it. |
| `negative` (or `negative_prompt`) | text | no | Sets a negative prompt when the request has one. |
| any **IMAGE** input | image | no | One reference picture each, filled in the order the subgraph lists them. Their number is the most references a still can use. |

Names are not case sensitive. Every other input and widget stays yours: the Studio
never changes steps, guidance, samplers, models or LoRAs.

One input may feed several nodes inside the subgraph; the Studio sets all of them.
Text your workflow adds to every prompt, such as a house style joined to `prompt`,
keeps working. The Studio's **Reusable still instruction** is already part of the
prompt it sends.

## Reference pictures

The Studio fills the image inputs from the first one and leaves the rest empty.
An image input that feeds a node which cannot run without a picture makes that
many references necessary, and the Studio says so before queueing:

> This image workflow needs 2 reference pictures, and this still has 1.

Use image inputs that are optional on the node that reads them (for example the
picture inputs of an edit model's text encoder) when stills should also work
without references.

Pictures wired directly to these inputs are available as `@still1`, `@still2`
and so on, by input position. Mention an alias in the frame image prompt or
the selected shot of the fallback video prompt to send that picture.

## How the prompt names pictures

Models refer to reference pictures differently. The Studio reads the wording from
the nodes inside your workflow:

| Inside the workflow | Wording |
| --- | --- |
| **TextEncodeQwenImage21** | `<image1>` |
| **PH3ImageConditioning**, **MiniMaxH3ImageConditioning** | `<Picture 1>` |
| anything else | `image 1` |

To use another wording, add the property `h3c_still_reference_label` to the
Timeline node (right-click, **Properties Panel**) with `{index}` where the number
goes, for example `Figure {index}`.

## Follow the video's shape at a fixed size

To make stills that match the video's aspect ratio at a chosen area, let `width`
and `height` only set the shape and compute the size inside the subgraph:

1. Connect the video's width and height to the subgraph's `width` and `height`.
2. Inside, add a **Float** primitive for megapixels and two **Math Expression**
   nodes, each with `a` from `width`, `b` from `height` and `c` from megapixels:
   - width: `round(sqrt(c * 1000000 * a / b) / 32) * 32`
   - height: `round(sqrt(c * 1000000 * b / a) / 32) * 32`
3. Connect their **INT** outputs to the width and height of the node that sets the
   canvas, and expose the primitive as an input named `megapixels`.

A still size chosen in the Studio is treated the same way: it sets the shape and
is scaled to the megapixels value.

## One node instead of a subgraph

A single node that has its own `prompt` and `seed` inputs and an IMAGE output,
such as an API image node, can connect to **still_image** without a subgraph.

## Example

`examples/qwen_image_21_still.json` is a Qwen Image 2.1 subgraph with `prompt`,
`width`, `height`, `seed` and ten image inputs. Paste it beside a Timeline and
connect its IMAGE output to **still_image**.

## Earlier connections

**Still Recipe**, **P-H3-Image Still** and **MiniMax H3 Image Still** connected
to **still_recipe** keep working. When both inputs are connected, **still_recipe**
is used.
