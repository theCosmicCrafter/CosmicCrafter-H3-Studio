# Cosmic Video | H3 Optimal Bucket Selector

**Category:** `Cosmic/Video/H3`

## Description

Snaps any width, height and frame request onto a resolution bucket and a 4k+1 frame count that MiniMax-H3 was trained on, so the sampler never sees an off-grid shape.

Buckets: 1280x720, 720x1280, 1920x1080, 1080x1920, 960x544, 544x960, 832x480, 480x832, 720x720, 1024x1024, 1280x544. Frame counts: 17, 33, 49, 81, 121, 161, 201, 241, 321, 401, 513.

## Inputs

- **target_width**: Width you want. Aspect ratio is weighted twice as heavily as size when choosing a bucket.
- **target_height**: Height you want. Only the ratio and rough area matter, not the exact number.
- **target_frames**: Frames you want; snapped to the nearest 4k+1 bucket.
- **aspect_ratio_mode**: How the request's aspect ratio may be changed to reach a bucket.
  - `nearest_bucket`: the bucket with the closest aspect and size, whichever side of the request it falls on.
  - `crop_to_fit`: only buckets at least as wide as the request. The request is scaled to the bucket's width and the surplus height is trimmed.
  - `pad_to_fit`: only buckets no wider than the request. The request is scaled to the bucket's width and the missing height is added.

If no bucket qualifies (a request wider than 21:9 in crop mode, or narrower than 9:16 in pad mode) the nearest bucket is used and `bucket_name` says so.

## Outputs

- **width**: `INT`
- **height**: `INT`
- **frame_count**: `INT`
- **aspect_ratio**: `FLOAT` of the chosen bucket
- **bucket_name**: `STRING`. In `nearest_bucket` mode this is the bare bucket id, for example `1280x720_16:9_landscape`. In crop and pad modes a fit note is appended after ` | `, for example `1280x720_16:9_landscape | crop: scale to 1280x960, trim 240px height`, so a Show Text node tells you what to do to the source.

## Example

A 1024x768 (4:3) request: `nearest_bucket` and `crop_to_fit` both give 1280x720 (crop reports scaling to 1280x960 and trimming 240 px of height); `pad_to_fit` gives 1024x1024 (scale to 1024x768, add 256 px of height).
