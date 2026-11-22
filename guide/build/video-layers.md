# Videos in one clip

A clip can hold up to four videos that share its time: a wide shot and a close-up of the same moment, for example,
cut together on a beat. Each video is its own H3 generation of the whole clip, with its own prompt, seed, First and
Last frames, memory and dialogue setting. The clip's **switch** says which one is on screen when, and the full video
plays them as one **stack**.

!!! info "The complete reference"
    This page is an overview. The repository's [Videos in one clip](https://github.com/KadoBOT/ComfyUI-H3-Continuity-Studio/blob/main/docs/TIMELINE-VIDEO-LAYERS.md)
    note covers every message, the Timeline text and the API.

## Add a video

1. Select a clip in the Studio and press **+ Video**, under the clip's video rows or in **Settings → Videos in this
   clip**. The new video copies the clip's prompt and seed.
2. Pick it with its button above the clip's tabs (**2 · main**, **2b**…) or by clicking its row on the Timeline, and
   write what it shows. Prompt, Seed, First and Last frames, Visual memory and Dialogue now edit that video.
3. Press **Generate video 2b**, or **Render remaining**, which renders a clip's other videos right after the clip.

The Timeline marks the clip with a **▤** badge and a stripe per video showing when it is on screen. The head shows
both lengths, for example "3 clips · on screen 7.8 s · renders 11.5 s", because every video renders the clip's whole
time.

## Swap, fade and sound

| Setting | Where | What it does |
| --- | --- | --- |
| **Swap** | Drag its handle on the Timeline (snaps to beats), or type the frame in **Settings → Switch**. | The frame where the next video comes on screen. |
| **Fade** | **Settings → Switch** | 0 to 12 frames, centred on the swap. 0 is a hard cut. |
| **Sound** | **Settings → Switch** | **The video on screen** swaps the sound with the picture; one video's sound plays it for the whole clip. |

A recorded dialogue line across a swap, while the sound follows the screen, shows a warning: choose one video's sound
so the voice doesn't switch mid-line. If the swaps no longer fit the clip's length and fade, the clip is marked as a
problem until you move them apart or shorten the fade.

## Good to know

- **The clip after a stack starts with a Cut.** Adding a video, or moving a continuing clip after a stack, asks first.
- **The full video waits** until every video has a take. The video so far plays the main video until the others
  render.
- **The Viewer** plays the clip's stack, or the picked video's own take.
- **Not yet:** Shot images and a takes list for the other videos, managed jobs (the
  [Timeline HTTP API](../automation/api.md) refuses these Timelines for jobs), continuing from a stack, and the Story
  writer writing several videos.
