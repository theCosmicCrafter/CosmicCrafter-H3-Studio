---
name: h3-continuity-sound
description: Use when an H3 Timeline has music, ambience, voice or on-screen words. That covers audio lanes (audio_clips) that H3 hears as references, playing the original recording in the full video (in_full_video), character voice clips from audio4 up, and Whisper-style timed text with its audio-synced clock and lettering contracts. Part of the H3 Continuity pack; read h3-continuity-video first.
---

# Audio lanes, voice clips and timed text

Read the bundle's `timeline-audio` and `timeline-text` guides, and the complete
Whisper example in `external-timeline` (`examples/whisper-source30.json`).

## Audio lanes

An audio lane places a recording on the movie clock. Each box that the lane covers
hears the matching window as a native audio reference. This selects `ref2va` by
default, but a qualifying box with `flf_refmods: true` stays `flf2va` while using
that audio. Both raw audio references and existing audio RefMods work with this
opt-in path; audio presence alone does not force REF2VA. See
`h3-continuity-references` for First-frame, VAE and raw-video requirements.

```json
"audio_clips": [{"slot": "audio1", "start": 0, "source_start": 30, "duration": 12,
                 "description": "Rhythm reference", "layer": "music", "file": {…}}]
```

- `start` is in movie seconds and `source_start` in the recording's own seconds;
  keep the recording's real offset. Source-in 30 at movie start 0 maps source 30 s
  to movie 0 s. `duration` is the placed length, and `layer` is `music`,
  `soundscape` or `shot` (voice or shot audio). `description` tells H3 Story what
  the sound is, and a Story `descriptions.audioN` input takes precedence over it.
- There are **three audio slots** (`audio1` to `audio3`), shared with connected
  audio references and audio RefMods. A lane needs either an uploaded `file` or a
  connected `audios.audioN` input, never both. A short source is padded, never
  stretched or looped.
- A box hears the lane over its whole generated window, its carried replay included,
  so the reference follows the box's own clock. Parts of a box the lane doesn't
  cover are silent in that reference.
- Connect an **audio VAE** to the Timeline. Without it, audio only labels the prompt.
- Moving or trimming a lane makes every box it covers need a render again.
- H3 *generates* sound from the reference and the prompt; it doesn't copy the
  recording. A box that should open on silence needs silence in its window, not
  just a prompt that says so.

## The original recording in the full video

`"in_full_video": true` on an uploaded clip makes the full video play that recording
instead of H3's audio:

- With at least one clip marked, the full video plays **only** the marked clips,
  each from its own window at its original speed. Overlapping clips add up within
  full scale, the video is silent where no marked clip plays, and nothing fades.
- A marked clip starts with the box its `start` falls in, after the bridges before
  that box, and then plays straight through. Bridges add picture but no time to
  the recording, so a bridge before a later box shifts that box's picture against
  the recording (see `h3-continuity-joins`).
- Marking or unmarking never makes a rendered box stale. The full video rebuilds a
  moment later, and box and bridge takes keep H3's audio.
- Mixing H3's audio with the recording is left to whoever consumes the full video.

## Voice clips

A character can have a voice clip, a recording H3 hears in the boxes where that
character speaks, so the voice stays the same across boxes. Voice clips live in
`voice_clips` on slots from `audio4` up (API asset binding `voice_clip`), and are
attached to characters in the Story bible.

- A box written by H3 Story from the bible sends the clip when the character has a
  line, voiceover included. It takes what is left of the box's three audios after
  lanes and mentioned audios, and one that doesn't fit is left out with a note.
- A box that sends a voice is `ref2va` by default, so its first and last frames
  become guides. The qualifying `flf_refmods: true` path can retain `flf2va` with
  the voice reference, just as it can with other audio references.
- H3 hears the whole file each time, so keep samples short (there's a note above
  30 s). Voice clips never play in the full video. Rendering needs an audio VAE.

## Recording ownership and dialogue

`audio_clips[].box_windows` binds source windows to stable box IDs. Preserve the
captured source, placement and `by_box` mapping: moving a box moves its assigned
recording window; duplicated/new boxes receive none. Splits preserve ownership.
Unlock windows before changing the recording or placement. Keep original source
timestamps rather than rewriting them onto the movie clock.

Dialogue cues hold exact recorded words, source times, speaker, portrayal and
checked source identity. A clip chooses cue dialogue or typed `<d>` lines;
conflicting sources stop it rather than silently doubling speech. Source/word/time
edits invalidate the check. A cue crossing a cut remains one spoken line, with
carried time accounted for. Never claim a cue was checked without listening.

A recording locked to the sequence clock must remain `in_full_video`; insertion
bridges inside it shift picture against the recording. `timing_conflicts` warns
but does not prevent rendering, so remove the bridge deliberately if the audio
must stay locked. Replacement bridges are unavailable. Box-window ownership is
independent of this sequence-clock lock.

Use `h3_upload_asset`, `h3_get_project`/`h3_save_project` and `h3_inspect` audio/status
for MCP authoring and metadata. Keep uint64 seeds, exact transcript bytes, source
clocks and opaque audio ownership fields intact. Waveform/beat analysis, snap and
playback are browser features, not server tools. Read `h3c://docs/MCP.md` and the
host audio guide for full payloads.

## Timed text

Attach a Whisper-style transcript and H3 is asked to show those exact phrases as
on-screen lettering at their times. Spoken words go in `<d>…</d>` in the prompt
instead.

- `timed_text` holds `source_name`, `source_sha256` (of the original JSON bytes),
  `enabled`, `sync_audio`, `audio_slot`, its own `start`, `source_start` and
  `duration`, `direction` (typography, placement and motion), `cues`
  `{id, start, end, text}` and optional `words`. Keep the text verbatim, including
  leading spaces, punctuation and language. Times are seconds, and intervals are
  half-open.
- Whisper `segments` (with nested `words`), top-level `words`, `chunks` with
  `timestamp: [start, end]` and raw timing arrays import with
  `h3_continuity.timed_text.import_whisper`. Import never invents missing word
  times or speakers.
- With `sync_audio` on, the chosen lane's `start`, `source_start` and `duration`
  drive the clock (`movie = lane.start + source - lane.source_start`). Moving the
  lane moves the text, and transcript timestamps are never rewritten. When turning
  sync off, copy the resolved clock into the text's own fields first.
- A cue that crosses a box boundary continues into the next box (`continues_after`
  in the outgoing box, `continuing` in the next), and a phrase that ends within the
  replay is `replay_only`. Preparation reports each box's `text_window`.
- H3 control tokens (`<d>`, `<|…|>`, `<scenetrans>`, `<cutoff>`) can't appear in
  transcript text.
- A guide or plate can carry a **lettering contract** (`visible_text`,
  `text_contract`) for the text active where it applies. Editing the timed text never
  rewrites a contract, and rendering stops with "timed text changed; restore the
  text or remove this lettering image" when they no longer match.
- Cue intervals are requests to the model, not overlays. Check the actual spelling,
  onset, clearing and continuity in the render. No subtitle overlay is generated.
