# Full video and projects

## The full video

When every clip has a saved take, H3 Continuity assembles one MP4 from the saved clip videos in Timeline order. It is built in the background: the Studio keeps showing every clip while it works, says *Building the full video in the background…*, and shows the links when it is ready. The Viewer's **Full video** plays it; **Open in new tab** opens the file and **Download** (or the top bar's **Download video**) saves it. It is stored under `output/h3_sequences/<name>/`.

While the video plays, a red **playhead** follows it along the ruler, the clips and the audio lanes; it holds still at a cut while an [inserted bridge](../continuity/joins-and-bridges.md#only-the-full-video-gets-longer) plays. Click or drag the ruler to move it: the selected clip's take seeks there while the moment is inside that clip, otherwise the video so far (or the full video) plays from there.

- Before that, the Viewer's switch reads **Video so far · 5/90**: the clips rendered from the first one on, up to the first clip without a take, joined into `<name>_sofar.mp4` with their bridges and the [ticked audio clips](../sound/audio.md#in-the-full-video) (or H3's audio). Play it after a few clips to check that picture and sound line up, instead of finding out after every clip has rendered. It is built in the background after each status check while clips render, grows as more clips render, keeps playing from the same moment when it grows, and gives way to the full video once every clip has a take. A clip rendered further on, after one that is still missing, waits until the gap is filled.
- In a Timeline that [splits a video across clips](../build/references.md#one-long-video-across-clips), a *partial video* (`<name>_partial.mp4`) stands in until every clip is rendered: current clips play their render, the others play the split video at the same moment.
- Otherwise the full-video links appear once **every clip has a saved take**. An [outdated](../build/timeline.md#outdated-clips) clip plays its saved take until you regenerate it. Re-rendering a clip or changing which take plays invalidates the previous export, and the next status check rebuilds it. Original segment videos and archived takes are preserved.
- Assembly copies the tracks when every clip has the same encoding. Otherwise it re-encodes on the CPU into one common format: the highest frame rate (a 24 fps clip repeats its frames beside 48 fps interpolated clips; every clip keeps its duration, so sound stays in sync), HDR when any clip is HDR (SDR clips are converted, with SDR white where BT.2408 puts it), and the dimensions of the smallest clip by pixel count. Larger clips resize to that width and height, including when aspect ratios differ; this can stretch the picture slightly. Re-rendering a smaller clip at higher resolution automatically rebuilds the preview at the new common size. Original clip files are preserved.
- An assembly progress bar and message appear above the viewer while **Video so far** or **Full video** is building, even when you are watching an individual clip. A failed build shows its reason there. An existing preview stays playable during rebuilding.
- Saved clip MP4s already exclude carried context. Audio comes from the saved decoded waveforms with the usual context trimming and overlap fade. Connect decoded images and audio to **H3 Save Segment** to include them; export generates no transitions or new soundtrack.
- Rendered [bridges](../continuity/joins-and-bridges.md) are played between their clips, and ticked [audio clips](../sound/audio.md#in-the-full-video) replace H3's audio.
- Once [replacement bridges](../continuity/joins-and-bridges.md#replacement-bridges) are available, a selected, current candidate plays in place of the footage it replaces, so the video keeps its length. When the clip after it then starts partway into its file, assembly re-encodes instead of copying.

## Projects

Open **Project settings** in the Studio's top bar.

[![Project settings](../assets/screens/project-settings.png)](../assets/screens/project-settings.png)

| Control | Does |
| --- | --- |
| **Shared prompt** | Text added before every clip's prompt. |
| **Export project JSON** / **Import project JSON** | Move a complete workflow graph, including wiring. Media and RefMods stay as file references. |
| **Export generation** / **Import generation into this workflow** | Move the *generation* (Story, Timeline, accepted guides, candidates, native saved takes and sidecars) into another generator workflow while keeping that workflow's models, nodes and sampler. |
| **Fork as a copy** | Downloads this generation as a file, then imports it into this workflow as a separate sequence with all its renders and takes. Change and re-render later clips in the copy to try another continuation; the original sequence is untouched, and importing the downloaded file returns to it. |
| **Back to graph** | Return to the Studio. |

Generation JSON references verified media in this installation; it contains no model weights and does not embed large videos or latents. Missing or changed media blocks an import. Import creates a *separate* sequence and never resumes a batch or replays source jobs. Use generation transfer to move work, for example, between a Qwen image workflow and the H3 video workflow, and project JSON to copy a whole graph.

API keys and provider settings live on the Story node, and the Timeline's name, width, height, context frames, carry audio and reference size stay on the Timeline node.

### New project

**New project** starts a fresh project in the current workflow.

[![The New project confirmation](../assets/screens/new-project.png){ width=420 }](../assets/screens/new-project.png)

Timeline clips, Cast, generated Story results and selected references are cleared. Uploaded pictures, connected images and audio, your idea, guide and other Story inputs stay available so you can write a new story immediately. Generated files on disk are kept. Unapplied form drafts for the old Timeline are cleared.

## Folder layout

```text
output/h3_sequences/<name>/
  seg_0001.mp4          # a clip's video, without carried context
  seg_0001.safetensors  # its original audio+video latents
  seg_0001_last.png     # its last frame
  bridge@<id>.mp4       # a bridge's new frames (plus .safetensors, _last.png)
  replace@<id>-<n>.mp4  # a replacement candidate (plus _preview.mp4, _original.mp4)
  <name>_full.mp4       # the full video
  manifest.json
  checks.json           # only if you ran the continuity check
  takes/                # earlier renders, one folder each
```
