# Qwen Story Studio

The installed ComfyUI workflow list contains `qwen_image_21_story_studio`, `qwen_image_21_turbo_story_studio` and `h3_story_studio_generation_import`. After a backend update, restart idle ComfyUI and refresh the browser to load the matching frontend.

Load `examples/qwen_story_studio.json` for Qwen images, `examples/qwen_story_studio_turbo.json` for official Turbo images, or `examples/h3_story_studio.json` for H3 video. Each workflow has its own Story and Timeline. Open Studio and write the Story normally, then select First, Last or a timed Shot and generate candidates. Preview or regenerate, then choose **Use as guide** to accept an image.

The Story page keeps model choices, reasoning effort and Story/Box/Vision API settings inside **Advanced**, closed by default. **Initial story model** handles planning and writer image descriptions; empty uses **Box writing model**, preserving existing workflows. **Story API URL** can use a different provider; empty uses **Box API URL**. Save each provider's key in the node's closed **API keys** section; keys are stored by host on the server. Hover over a field for tips: a strong planning model suits the initial story, while a creative writing or roleplay model that follows structured output instructions can suit box prompts. Each stage has its own reasoning setting.

Still requests receive relevant Cast images, images mentioned in the prompt, and images connected to the Still Recipe. Scene anchors and previous guides are not added automatically. An empty image Seed field gives every candidate a new random seed. Enter an image Seed to repeat one exact seed for that target; each candidate records the seed it used.

The image prompt remains editable. Image-only Story writing asks for concrete opening and ending states and a fixed viewpoint, while retaining actions and timing as portable Story metadata for H3. Qwen First/Last/Shot prompts describe one visible state and use native `<imageN>` references. Last selects the ending state; edited clip text takes precedence over an older structured source. A legacy Story without a concrete final-state description requires reviewing the Last image prompt. Existing saved image drafts are preserved: use **Rebuild prompt** to replace an old animated draft. The actual executed prompt and reference roles are shown on each candidate. Choose your usual writer host/model in Story; its credentials and renderer settings remain local to the destination.

## Transfer between workflows

On the Story page use **Export generation**, open the other generator workflow, then **Import generation into this workflow**. Import keeps its generator nodes, links, model choices and sampler controls. It creates a separate sequence and copies native saved takes and sidecars. Completed image receipts remain historical; candidates stay candidates.

Generation JSON references verified media in this installation; it does not contain model weights or embed large videos and latents. Missing or changed media prevents import. Generated structured prompts are adapted to the destination image/video renderer, while manual clip edits and the underlying Story actions remain intact. Editable linked native text primitives can receive imported Story and Timeline values without disconnecting links. A computed project field produces a field-specific error because its value cannot be set by import.

The separate **Export project JSON / Import project JSON** actions transfer a complete workflow graph. Creating a new workflow with those actions is expected. To move a generation from Qwen to the existing H3 graph, use the two generation actions above.

## Generator presets

`examples/qwen_image_21_still.json` contains the reusable native base generator: Qwen Image 2.1 INT8, Qwen3-VL 8B BF16, Qwen 2.1 VAE, Euler/simple, CFG 1, 25 steps. The official Turbo example uses its Turbo checkpoint and ManualSigmas `1.0,0.978453,0.95418,0.926626,0.89508,0.845148,0.704534,0.414568,0.0` with Euler/CFG 1. The final zero is ComfyUI's terminal sigma. No additional schedule shift or LoRA is inserted.

In the image panel, click **Generator settings** to select and center the connected native generator group. Double-click the group to edit its nodes. In the base recipe, change **BasicScheduler → steps**, **CFGGuider → cfg**, **KSamplerSelect → sampler_name**, or **UNETLoader / CLIPLoader / VAELoader** model selections. The selected model, text encoder and VAE must be compatible. Insert a native **LoraLoaderModelOnly** between the model loader and its model consumers to add a model LoRA; use **LoraLoader** when the LoRA also needs CLIP. Turbo uses the explicit **ManualSigmas** schedule rather than a steps widget; edit that schedule or use the base generator for ordinary step-count control. Studio executes the current connected graph, including these changes.

Copy the native subgraph into another workflow to reuse it. Connect its IMAGE to the Timeline's `still_image` input (see `guide/build/own-image-workflow-stills.md`); the subgraph's own input names bind it, and `examples/qwen_image_21_still.json` no longer contains a Still Recipe node. Its references use native Qwen encoding and 64-channel latents. Output dimensions use a native 64-channel canvas with 16-pixel spatial compression (EmptyFlux2LatentImage); accepted source bytes remain unchanged.

## Connecting another image generator

For P-H3-Image (Pruna AI), use the ready-made **P-H3-Image Still** node instead of writing bindings; see `guide/build/p-h3-image-stills.md` and `examples/ph3_image_story_studio.json`.

Any image workflow can connect through `still_image` without bindings. For a workflow that keeps a **Still Recipe** node, use Still Recipe bindings version 2 with `adapter: "pixels"`, a descriptive `label`, `reference_limit`, and `reference_label` containing `{index}`. Declare local node/input locators for `prompt`, reusable `instruction`, `seed`, both dimension arrays in `size`, and ordered `references`. An optional `negative` locator preserves native negative text unless a request overrides it. The generator exposes IMAGE. The Studio supplies invocation-only pixel loaders; the native graph owns all model and sampling behavior.

A request exceeding the declared reference capacity fails before submission and names the required references. Computed IMAGE references, including X2 detail subgraphs, run through their captured graph connections during still generation; provenance records the source graph hash. Exporting their pixels still requires a rendered image file. Existing version-1 H3 recipes retain their native conditioning adapter.

## Validation status

Graph, storage and Studio checks are distinct from visual acceptance. The native base/Turbo comparison and media interchange are verified; arbitrary-view geometry remains experimental. See the dated verification record. Reference delivery does not by itself establish exact reconstructed geometry.

## Native verification and quality limits

Base and official Turbo rendered First, a timed action Shot, Last, a same-room camera cut and a new location at 1024×576. Base preserved the fixed-camera couch/window/table arrangement and the requested one-handed vase hold more closely in this sample; it remains the default. Turbo is the faster alternative: five warm jobs had median execution times of 4.694s versus 9.983s for base. This small warm comparison is not a general benchmark. Turbo also generated Shot/Last using its own accepted First and Shot.

Both presets only partly followed the requested 45° camera change, even with clearer camera instructions. Exact geometry across arbitrary viewpoints is **experimental**. Inspect each candidate before accepting; regenerate or supply an accepted reference for the desired view. Acceptance records continuity inputs but cannot guarantee that the model obeyed them. No automatic geometry or identity quality check is advertised.

The persistent scene-anchor ordering applies to pixel recipes, including Qwen. The retained H3/Fizgig still recipe keeps its existing native latent-memory behavior. To generate Qwen guides within an H3 workflow, connect the Qwen pixel recipe to its Timeline.

Actual Qwen → H3 → Qwen and H3 → Qwen → H3 generation imports retained destination renderer controls. H3 rendered a 90-frame 1024×576 video from the Qwen guides; Qwen then generated from its exact delivered frame 89. The returned H3 sequence recognizes its saved clip and preserves independent copies of native video/latent sidecars. Full evidence and remaining limits are in verification.


## Prepare richer still prompts

In Studio, click **Prepare all still prompts** above the Timeline. It is available independently of the selected clip or image panel and uses the connected Story writer's model in one explicit batch for all unique targets across every clip. **Still prompt conversion instructions** is separately editable in the same Timeline area. Select a First, Last or Shot marker to review or edit its result. Results describe subject and visible state, setting/layout, style/materials, lighting/atmosphere, color palette, and camera/composition; **Prepared visual details** in the selected image panel shows those fields and any review notes.

Each target uses only its selected shot. First describes the opening moment; Last describes the reached state at the actual clip end. A continuous Last/next First shares one stored prompt, and editing either updates both. Shot markers alone do not imply cuts. Saved prompts retain logical reference names; the connected image recipe assigns its native image labels when generating.

Earlier saved image prompts keep priority. Choose **Use prepared prompt** for one target, or **Use prepared prompts for all targets** to replace them in one Undo transaction. Earlier text and all images/guides remain preserved. A blank edit stays a local draft until valid text is entered.

Relevant timeline, reference or instruction changes show **Still prompts are out of date** and a **Regenerate all still prompts** action above the Timeline. Regeneration is manual; image generation does not call the converter. A lost polling connection can be resumed without submitting another batch, and **Cancel preparation** keeps existing saved prompts. Prepared metadata travels with generation export/import. The backend must be restarted and Studio refreshed after installing this feature.

Qwen 2.1 generation adds its scene-integration instructions when compiling the native image request. A mentioned location image is placed first when available. Identity, appearance and prop references retain their separate roles, and all logical image references are rebound to the final `<imageN>` input order. For a single input, the instruction says **the reference image**. The requested pose, expression, camera and lighting remain authoritative: Qwen is asked to reconstruct the subjects within the environment with matching perspective, scale, illumination, reflected light, shadows and occlusion. A different camera view reconstructs the same environment rather than freezing the reference framing. Without environment pixels, the instruction explicitly composes the requested setting from the available identity/object references.

These instructions apply to existing saved still prompts without rewriting them or calling the Story model again. New batch-instruction defaults also request physical integration while remaining generator-neutral; existing edited conversion instructions remain preserved. **Effective prompt** in the candidate records shows what the native generator actually received. Regenerate an image candidate to test the new behavior; earlier images and accepted guides remain in place. Reference ordering and prompt compilation are verified separately from actual visual blending quality.

## Optional reusable references

Open **Studio → Cast → Prepare references** before generating First, Last or Shots. Enable **Generate cast images**, **Generate location images**, and/or **Generate object / prop images**. These switches are independent and start off, including in existing Stories.

Each card is one independent Story asset: for example Mei, Dress and Bedroom. The panel does not automatically create character/outfit or character/scene combinations. Uploaded pictures linked to an asset appear as **Uploaded reference — ready** and require no new candidate. An extra can be anything reusable: clothing, a weapon, car, flowers, teddy bear, furniture or another prop. **Add object reference** adds an extra that the Story did not list; choose the current clip or **Use throughout this scene**.

Select the missing assets, edit their still-image prompt, optional seed or size, and choose **Generate missing references**. This runs the native image generator directly, with no Story LLM call per asset. Repeated source-image preparation is shared across requests and the batch. The generator uses its current native model, LoRAs and sampler controls; **Generator settings** opens those nodes. Completed images remain candidates until **Use as reference**. Ready assets offer optional **Regenerate reference**; you can also upload a candidate. **Stop after current image** retains completed work. Reloading recovers saved requests without submitting them again.

With preparation enabled, First/Last/Shot generation opens this panel if an included independent asset is missing. Original uploaded pictures satisfy that requirement. Disabling a preparation category skips its requirements and retains approved references. Use **Enabled references** to disable actual image inputs. Existing scheduled appearance/composition images, their approvals and clip scopes remain preserved in saved Stories and generation imports.

**Export generation / Import generation into this workflow** carries the preferences, candidates, approvals, object scopes and completed receipts. Imports preserve the destination generator and never resume a preparation batch or replay source jobs. Original H3 version-1 recipes can use imported approved images; generating new reference candidates requires a connected version-2 pixel recipe. Use `examples/h3_story_studio_qwen_references.json` for H3 video with Qwen images attached. Other version-2 pixel generators use the same interface.

Native prompts assign explicit roles: location controls room geometry, identity controls the person, props control their own design, and prior stills guide pose/action without overriding the approved location. Reference roles and approved image hashes/revisions are recorded on executed requests. These guide identity, wardrobe, props and layout; exact geometry under arbitrary camera changes remains experimental.
