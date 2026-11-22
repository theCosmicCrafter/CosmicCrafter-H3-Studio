# P-H3 still quality corrections

The user approved correcting the diagnosed still pipeline and releasing it. The b07 job inherited 736x992 video size, padded a character sheet to that canvas and submitted an entire video action.

## Approach

Keep the official sampler and installed model files. At Studio recipe preparation, resolve the saved dimension ancestry through a small CPU size node and use approximately 8 MP at the same aspect ratio (with 4 MP and custom options on the generator) unless the request explicitly supplies a still size. Direct P-H3 defaults use an 8 MP canvas. Preserve P-H3 reference pixels and let native PH3ImageConditioning handle their scale. Other generators retain existing behavior.

Carry Cast roles where known and preserve native subject descriptions and picture titles as reference context without guessing semantic roles from filenames. Do not pretend a video sequence is a still: use authored opening/ending snapshots or prepared prompts; otherwise show an empty still prompt with a clear preparation instruction. Manual and prepared prose remain editable and are preserved.

Alternatives: changing the video resolution also increases video cost; replacing the sampler has no evidence; heuristic rewriting of arbitrary video prose loses intent. These do not fit the diagnosed failure.

Release the smallest patch version after CPU regression checks and fresh review. Preserve all prior dirty files; fast-forward both main checkouts. No model downloads, workflow rewiring, service restart or GPU inference is needed.
