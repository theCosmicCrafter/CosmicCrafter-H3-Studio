# Third-party notices

## H3 Continuity Studio (vendored)

The `h3_continuity/` package, `mcp_adapter/`, `skills/`, `docs/continuity/`,
`guide/`, `examples/continuity/`, `tests/h3c/`, and `tools/h3c/` directories
are vendored from ComfyUI-H3-Continuity-Studio
(https://github.com/KadoBOT/ComfyUI-H3-Continuity-Studio), MIT License,
copyright (c) 2026 H3 Continuity contributors. See `VENDORED.md` for the
pinned commit and `h3_continuity/LICENSE` for the license text. The Apache
License 2.0 copy at `APACHE-2.0.txt` covers the adapted MiniMax H3
Singularity prompt-writing specification in `h3_continuity/story_prompts.py`.

Attribution carried over from upstream THIRD_PARTY_NOTICES.md:

- `h3_continuity/story_prompts.py` shot-writing guidance is adapted from the
  MiniMax H3 Singularity prompt-writing specification by WarmBloodAban
  (Apache-2.0; upstream model card at revision af671d9).
- `h3_continuity/check_frames.py` texture measure is a NumPy port of
  `texture_band_rms` from ComfyUI-MiniMaxH3-PrefixStream by knoic (MIT).
- Paired context noise, audio feather, take ratings/lineage, per-box video
  windows: ideas from the same PrefixStream project.
- H3 Sigmas Tail: independent implementation of an idea from
  ComfyUI-H3-Motion-Context by NikoDemon80 (GPL-3.0); contains none of that
  project's code.
- `h3_continuity/h3_guide/` prompt guides and MiniMax H3 model weights are
  NOT included; they carry their own terms (see `h3_guide/NOTICE`).

## This pack

CosmicCrafter-H3-Studio runtime code is GPL-3.0-only (see LICENSE).
