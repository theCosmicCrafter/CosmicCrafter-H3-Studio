# Stills from the user's own image workflow

Date: 2026-11-15. Branch `feat/subgraph-still-workflows` (worktree `h3c-subgraph-stills`).

## Goal

Generate stills and reference pictures through any ComfyUI image workflow the
user builds, with their settings, and without placing a node from this pack in it.

## What stood in the way

The pixel engine (`image_recipe.prepare`) already rewrites any native graph.
Three things kept it from being general:

1. `H3C_StillRecipe` needs hand-written JSON naming inner node ids.
2. `H3C_PH3ImageStill` and `H3C_MiniMaxH3ImageStill` hide steps, sampler, sigmas
   and LoRA handling behind fixed values.
3. `image_recipe.py` chose prompt wording and port order from the class of the
   node that receives the references, which only matched three node classes.

## Design

The inputs of a native subgraph are its contract.

- **Connection.** The Timeline has a `still_image` IMAGE input (raw link, lazy,
  never requested). The user connects the IMAGE output of a subgraph, or of one
  node that has its own `prompt` and `seed`.
- **Binding by name.** `captureWorkflow` (web/h3c_stills.mjs) follows each
  subgraph input to the inner inputs it reaches, through nested subgraphs, and
  returns the same version 2 pixel recipe the server already accepts, marked
  `auto: true`.
  - Required: `prompt`/`positive_prompt`, `seed`/`noise_seed`.
  - Optional: `width`, `height`, `negative`/`negative_prompt`.
  - Every IMAGE input is a reference slot, in subgraph order.
  - One input may reach several inner inputs (`more` on a locator).
  - `instruction` is deliberately not bound. The Studio bakes its instruction
    field into the prompt, and a workflow that joins its own instruction to
    `prompt` would otherwise apply it twice.
- **Picture wording.** Read from the node classes inside the workflow
  (`<image{index}>` for Qwen, `<Picture {index}>` for P-H3/MiniMax conditioning,
  `image {index}` otherwise), with the Timeline node property
  `h3c_still_reference_label` as an override.
- **Server.** For an `auto` recipe, `image_recipe.prepare` detects the model from
  the ancestry of the image output, skips the single-node port rules and the
  P-H3 size node, allows a missing size binding, and reports an empty required
  IMAGE input before ComfyUI refuses the prompt.
- **Compatibility.** `still_recipe` is unchanged and wins when both inputs are
  connected.

Rejected: tracing a flat graph heuristically (sampler, text encoder). It fails on
API nodes, custom samplers and several encoders, and the binding is invisible.

## Spike result

Posting a prompt with an unconnected required IMAGE input to the live ComfyUI
0.45.0 returned `prompt_outputs_failed_validation` / `required_input_missing`
and queued nothing. The Studio therefore checks unfilled reference slots itself.

## Slices

1. **Done here:** `still_image`, auto-binding, server changes, Story's
   generator detection, guide page, Qwen example without a recipe node.
2. Native templates for P-H3-Image and MiniMax H3 Image (editable subgraphs), then
   mark the two ready-made nodes and `H3C_StillRecipe` deprecated for one release.
   Open point: the MiniMax prompt enhancer depends on `H3C_MiniMaxPromptCaption`
   to extract `expanded_caption`; a native replacement is not confirmed.
3. Replace the injected `H3C_StillImageSource` with native `LoadImage` on a
   content-addressed copy. It never appears in the user's graph, so this is
   internal; the fit-and-pad sizing it does for the first Qwen reference needs a
   native equivalent first.
4. Derive the recipe on the server when `/h3c/stills/prepare` receives none, so
   MCP agents stop writing recipes.
5. Delete the deprecated nodes.

Out of scope: H3 video-model stills (`H3C_StillConditioning`, RefMods, latent
memory). They cannot be expressed with native nodes.

## Not verified

No browser run against a real graph and no generation. The binding is tested
against the shipped Qwen example's saved subgraph definition, not against a live
`graphToPrompt` result.
