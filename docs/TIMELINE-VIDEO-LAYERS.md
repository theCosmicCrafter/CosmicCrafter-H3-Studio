# Videos in one clip

A clip can hold up to four videos that share its time. Each video is a separate H3 generation of the whole clip, with
its own prompt, seed, First and Last frames, memory and dialogue setting. The clip's **switch** says which video is on
screen when, and the full video plays the clip as one **stack**: the videos swapped, or crossfaded, at the frames you
choose. Use it for coverage: a wide shot and a close-up of the same moment, cut together on a beat, without splitting
the moment into separate clips that would each start over.

## Adding a video

In the Studio, select a clip and press **+ Video** under the clip's video rows on the Timeline, or turn on
**Settings → Multiple videos**. Turning that switch off again keeps only the main video, after a confirmation. The new
video copies the clip's prompt and seed, and starts with no First or Last frame. It
takes over halfway through the time the last video is on screen. A clip holds at most four videos; **+ Video** is off
at four, and when the clip is too short for another swap with its fade.

Videos are labelled by clip number: clip 2's videos are **2 · main** (the clip itself), **2b**, **2c** and **2d**. The
Timeline marks a clip with several videos with a **▤** badge and a stripe per video that shows when it is on screen.
Selecting the clip opens a row per video under the track, inside the clip's own time. The main video's First and Last
stay in the marker row above; each other video's row has its own First and Last tiles, its render state ("2b ✓ seed
5101" or "2b not rendered") and a bar for its time on screen.

The clip panel has a button per video above its tabs. The picked video is the one the panel edits: its **Prompt**, its
**Seed**, its **First frame** and **Last frame** in Settings, its **Visual memory** and its **Dialogue** setting.
**Generate video 2b** renders only that video, and keeps the one before in the clip's takes folder. Clicking a video's
row on the Timeline picks it too.

## Swap, fade and sound

Each swap is a frame of the clip where the next video comes on screen. Drag its handle on the Timeline (it snaps to
beats like clip edges; Shift drags freely), or type the frame under **Switch** in **Settings → Multiple videos**. The chip on the handle reads
"27 · fade 6".

- **Fade**: 0 to 12 frames, 6 by default, centred on the swap. 0 is a hard cut. Swaps stay at least one fade apart,
  and inside the clip with room for half the fade on each side.
- **Sound**: **The video on screen** follows the picture, so the sound swaps with it. Choosing one video plays that
  video's sound for the whole clip, whatever is on screen.

When a recorded dialogue line crosses a swap while the sound follows the screen, the clip warns: "A line crosses the
swap at frame 27 while the sound follows the screen, so the voice switches mid-line. Choose one video's sound for this
clip." It's a warning; the clip still renders.

If the clip gets shorter, or its fade longer, the swaps move to fit. When they can't fit any more, the clip is marked
as a problem and doesn't render: "The swaps no longer fit this length; move them apart or shorten the fade."

## What follows a stack

The clip after a clip with several videos must start with a **Cut**: a continuing clip would need one ending to carry
on from, and a stack has several. Adding the first other video, or moving a clip so that a continuing clip lands after
a stack, asks first: "Clip 3 continues from clip 2. With several videos in clip 2, clip 3 must start with a Cut.
Change it?" **No** leaves everything as it was. Deleting a clip with several videos asks too: "Delete clip 2 and its 2
videos?"

## Rendering and time

Each video renders the clip's full time, so the Timeline's head shows both: "3 clips · on screen 7.8 s · renders
11.5 s". **Render remaining** counts every video without a take, and renders a clip's other videos right after the
clip, before the next clip.

The stack is built when the full video is assembled: `stack@<clip>.mp4` in the sequence folder, next to the clip's own
take. The videos are blended in the encoder's YUV format at the same quality as the takes, so the full video still
copies every clip without encoding it again. A stack is reused until one of its videos, the switch or the clip's
length changes.

- **The full video** waits until every video of every clip has a take. Until then its status names the videos still
  missing, for example "Clip 2's video 2b has no take yet."
- **The video so far** plays a clip's main video alone until its other videos render, then a stack of the videos that
  have takes, skipping swaps to the ones that don't.
- **The Viewer** plays the selected clip's stack ("Clip 2 · videos together"), or the picked video's own take ("Video
  2b · take").

## The Timeline text

A clip with several videos keeps its other videos in `layers` and its switch in `switch`, and the Timeline names the
feature it needs in `requires` (`video-layers-1`), so an older H3 Continuity opens it read-only instead of losing them:

```json
{"id": "b2", "frames": 90, "exact": true, "prompt": "Wide on the kitchen.", "seed": 1, "cut": true,
 "layers": [{"id": "b2v1", "seed": 5101, "prompt": "Close on her hands.", "first": "", "last": "", "previews": [],
             "memory": "off", "memories": [], "dialogue": "cues"}],
 "switch": {"cuts": [{"at": 27, "to": "b2v1"}], "fade": 6, "sound": "screen"}}
```

A run renders one video with `"render_layer": "b2v1"`, as it renders one box with `render_box`. The Timeline API's
schema declares `layers` (at most three) and `switch`, and refuses `render_layer` in a stored Timeline. Managed jobs
can't render a Timeline with several videos in a clip yet: planning answers `unsupported_timeline`, "H3 Timeline API:
this Timeline has clips with several videos, which managed jobs can't render yet. Render it from the Studio."

## Not in this version

- Shot images (guides) on another video: its Shots tab says so. Its First and Last frames are in Settings.
- A takes list per video, and the Viewer's Switch between takes of another video.
- Explicit visual memory sources per video, candidate stills and Prepare all still prompts for other videos.
- Managed-job units for other videos.
- Measured alignment between the videos and a nudge control (the `align` field is read, but nothing sets it).
- Continuing a clip from a stack.
- The H3 Story writer writing several videos for a clip.
