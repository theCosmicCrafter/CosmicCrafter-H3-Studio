# Superseded audio-reactive drafts

These were the first attempts at the SAM + audio-reactive graph.  They are kept
for reference only — **do not load them expecting them to work**.  Two defects
make them unreliable:

1. **Dangling link ids.** Both files reference link ids that do not exist in the
   `links` table. ComfyUI drops those connections silently on load, so the graph
   looks wired on the canvas but parts of it are not.

2. **`SetLatentNoiseMask` cannot address an H3 AV latent.** It stores a bare
   `[N,1,H,W]` tensor. H3's latent is a *nested* pair — video
   `[B,24,T,H/16,W/16]` and audio `[B,32,2,T40]` — so the sampler substitutes an
   all-ones mask for the audio stream and **trilinearly interpolates** the video
   mask down to `T`.

   That interpolation is the reason the background barely reacted. H3 packs
   ~3.4 source frames into one latent frame, so a one-frame beat hit lands
   between samples and averages to nothing. Measured on a 124-frame clip with 11
   single-frame beats, trilinear interpolation preserved **1 of 11** at full
   amplitude and erased 8 of them entirely.

Both problems are fixed in `../CosmicCrafter_AudioReactive_SubjectLock.json`,
which uses `MiniMaxH3LatentNoiseMask` — it builds the mask directly at the
latent's exact shape and *aggregates* the source frames belonging to each latent
frame instead of point-sampling them, preserving **11 of 11** beats.

Regenerate the current workflow with:

    python tools/build_audio_reactive_workflow.py

---

## `CosmicCrafter_AudioReactive_Masking_original.json`

The very first graph, recovered from
`<ComfyUI>/user/default/workflows/` on 2026-08-21. It was the *only*
CosmicCrafter workflow ComfyUI could see, so it kept getting loaded while the
regenerated files changed in the repo unnoticed.

It carries every defect described above plus the external-pack chain
(`SAMLoader` → `SAMDetectorCombined` → `InvertMask`, `AudioFeatureExtractor` →
`FeatureToMask` → `MaskComposite` → `SetLatentNoiseMask`), and it masks an
**empty** latent, so its "locked" subject decodes to flat grey.

Moved here so it can no longer be loaded by accident. The current graphs are
installed into `<ComfyUI>/user/default/workflows/CosmicCrafter/`.
