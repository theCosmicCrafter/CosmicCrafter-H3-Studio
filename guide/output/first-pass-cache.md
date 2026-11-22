# Keep the first pass, re-render the second

A common way to work: render the whole Timeline with the second pass off, review it, then turn the second pass on and render again. **H3 Disk Cache** makes the second render skip the first pass. Every clip whose first pass is unchanged loads it from disk and goes straight to the second pass.

!!! warning "Status"
    Implemented and tested on CPU against ComfyUI's real scheduler with stand-in models. Not yet checked on a full GPU render.

## Why ComfyUI's own cache does not do this

ComfyUI keeps results in RAM, and only for a node whose inputs are exactly the same as on the run before. Each Timeline run renders a different clip, so its outputs change from run to run and nothing above the sampler stays cached between clips. A restart clears the cache too.

## Wiring

1. Put **H3 Disk Cache** after the first-pass sampler, and connect the sampler's output to `result`.
2. Move every link that read the sampler's output (decode, H3 Save Segment `latent`, the second pass, metadata) to the cache's `result` output.
3. Connect the H3 Timeline's `positive`, `latent` and `seed` to the cache's `keys`.
4. Connect the first-pass decode (the sampler's latent decoded as is, 24 fps, before any second pass, upscale or grade) to H3 Save Segment's `guide_frames`.

Step 4 matters for continuing clips. A continuing clip is guided from the last frame of the clip before. Without `guide_frames` that frame is the finished one, so a new second pass changes the next clip's first pass, and every clip after the first samples again.

## What the cache compares

| Part | Compared by |
| --- | --- |
| The keys (`positive`, `latent`, `seed`) | Content, tensor bytes included. The same clip rendered in another project finds its result too. |
| The rest of the graph above the sampler | Each node's type and widget values. Node ids and layout do not count. |
| A settings node that also feeds the Timeline | The values it passes on. A config node's second-pass size does not change the first pass's key unless the first pass reads it. |

Changing the prompt, a reference, the seed, a LoRA, the step count or the first-pass size samples again. Changing only the second pass, upscale, interpolation or grade loads the saved first pass.

The cache refuses to save, and says why in its `info` output, when it cannot compare something:

- A node above the sampler that changes on every run (a random value, a file loader without a fingerprint). Connect its output to a key instead.
- A Timeline output read above the sampler that is not a key. Connect it to a key as well.

When a run finds no saved result, `info` names the closest saved one and what differs (for example `positive (H3C_Timeline positive) at [0][0]`).

## Modes and storage

| `mode` | Effect |
| --- | --- |
| `use` | Load a matching saved result, else sample and save. |
| `refresh` | Sample and replace the saved result. |
| `off` | Sample; never load or save. |

Results are saved under `output/h3c_cache/<namespace>/` as safetensors with a JSON record beside each. `namespace` defaults to `first_pass`; use a different one per workflow if you want to clear them separately. Nothing is deleted automatically; delete the folder to clear the cache.
