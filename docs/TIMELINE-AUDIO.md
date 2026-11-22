# Timeline audio

For standalone audio references and the separate, synchronized soundtrack inputs of video references, see
[MiniMax H3 references](TIMELINE-REFERENCES.md). Video soundtracks have their own three slots and do not consume
the three standalone audio slots described here.

In the Studio (**Open Studio** on the Timeline node), press **+ Audio** or drop an audio file onto the audio lanes above the video boxes.
Long files keep their original duration; the initial selected window fits the video when boxes already exist.
Move the clip to align it, trim either edge, or use **Fit to video**. Playback speed stays unchanged.
Shift-drag selects a different source window without moving the clip. Audio settings also provide exact
video-start, source-in and length values, and an audition player.

Choose **Music**, **Overall soundscape**, or **Shot audio / voice**, then describe the sound in Audio settings.
In **H3 Story**, you can also connect Text to `descriptions.audio1`, `descriptions.audio2`, or
`descriptions.audio3`, just as for images. Story Text takes precedence over the lane description.
Write uses these descriptions in H3's corresponding audio sections and preserves the reference binding.

Connect an **audio VAE** to Timeline. Each covered box receives the matching audio window as a native H3
audio reference. Continuing generations include the matching replayed audio context so the reference follows
the generated clip clock. Uncovered parts of a box are silent in that reference; audio outside its placed
interval is excluded. A short source is padded rather than stretched or looped.

Up to three audio slots are available, shared with connected audio references and audio RefMods. Existing
connected references keep their previous behavior until added through **Add connected audio**. A Load Audio
file can be placed directly; for computed audio, upload its source file to create a draggable lane.

A character's voice clip, from the Cast page, isn't a lane: it has a slot of its own from `@audio4` up, so it
doesn't hold one of these three. The **Shot audio / voice** lane gives a box its sound, while a voice clip gives a
character's voice to every box where that character speaks, and counts among H3's three audios only there. It never
plays in the full video. See [Voice clips](STORY-BIBLE.md#voice-clips).

Clip placement, trim, waveform and descriptions persist with Timeline and shared saved state. Uploaded files
remain in ComfyUI's `input/h3_audio`; Story exports retain their file references. H3 generates from the reference
and prompt. To hear the uploaded file itself in the full video, see [In the full video](#in-the-full-video).

## In the full video

Tick **In the full video** in an uploaded clip's Audio settings, and the full video plays that clip instead of the
audio H3 generated. It's off by default, and a clip from a connected Load Audio node needs its file uploaded first.
It's independent of the reference switch: a clip can play in the full video while H3 never hears it. In the saved
Timeline, a ticked clip has `"in_full_video": true`.

With at least one clip ticked, the full video plays only the ticked clips:

- each plays the source window its lane shows, from its video start, at original speed;
- overlapping clips add up, held within full scale;
- the video is silent where no ticked clip plays, and a clip that runs past the last frame is cut there;
- the sample rate is the first ticked clip's, in slot order, and the audio is stereo if any ticked clip is;
- there are no fades.

A moment after a ticked clip changes, the full video is rebuilt on its own, with nothing rendered, and the Studio's
Full video view names the clips it plays. Ticking never puts a rendered box out of date; moving or trimming a clip
that H3 hears still does, as before. With bridges, a ticked clip starts with the box it starts in, after the bridges
before that box, then plays straight through (see
[Only the full video gets longer](TIMELINE-BRIDGES.md#only-the-full-video-gets-longer)).

If a ticked clip's file is missing, the full video isn't rebuilt, and the Studio names the file. Box and bridge takes
keep H3's audio, and unticking every clip brings H3's audio back to the full video.

## Imported audio metadata

An audio lane uses `start` (movie seconds), `source_start` (original recording
seconds) and `duration` (the placed window). `source_duration` is the positive,
finite duration of the entire recording, not the placed window. Include it when
known. The API schema and native parser validate it when supplied; older records
without it remain valid.

The Studio opens those older records without guessing their source bounds. It
reads metadata from the source file and saves the measured duration without
changing placement or the selected source window. Until that succeeds, moving
the clip and editing its description remain available; trimming, source-window
changes and Fit to video are disabled. An unavailable file leaves a clear
source-duration message instead of stopping the Studio from opening. Use **Read
source duration** to retry after a temporary file or server failure.
