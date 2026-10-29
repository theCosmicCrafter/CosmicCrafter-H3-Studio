# Cosmic Video | MiniMax-H3 Video Forensics

**Category:** `Cosmic/Video/H3`

## Description

Measures what an existing clip actually did, so a prompt can be written from evidence instead of from a vision model's guess. Over the frame batch it finds hard cuts, freezes, single-frame flashes and single black frames; over the optional audio it finds level peaks in half-second windows, the low/mid/high energy split and whether the track behaves like music or like field sound. Everything is written as timestamped plain lines, in the `mm:ss.mmm` form H3 uses for cut times, and a labelled contact sheet of up to 16 frames is built for the Vision Analyzer to look at. No model, no network, no GPU: on the CPU, 300 frames take under half a second at 480p and about three seconds at 1080p. Frames are converted 16 at a time, so the working memory is under 1 GB at 1080p however long the clip is; the batch itself is read in place.

This is the reverse-prompting front end. Wire a video loader's frames (and audio, if it has one) in, wire `evidence` and `contact_sheet` into the Vision Analyzer with its focus set to `event chain (timestamped)`, and wire that into the Promptor's `vision_context`. The Promptor then writes cut clauses at the measured times, sound effects into `overall_soundscape` and the music verdict into `non_diegetic_music`, in the official field structure the grammar checker already knows.

## Inputs

- **images**: Every frame of the clip in order, a video loader's IMAGE output. The node works over the whole batch, so do not thin it first: a cut between skipped frames is a cut it cannot see.
- **fps**: The clip's frame rate, so frame numbers become timestamps. Take it from the loader. Default 24.
- **audio** (optional): The clip's track as ComfyUI AUDIO. Without it the SOUND block says `no audio connected`.

## Outputs

- **evidence**: `STRING`. The timestamped report, two blocks:

```
VIDEO FORENSICS: 96 frames at 24.00 fps = 4.000 s, 64x48
LIVE ACTION
  00:02.000  hard cut (frame 48; diff 0.40, hist 0.98)
  00:02.500-00:03.333  freeze, 20 frames (frames 60-79)
  00:03.750  flash (frame 90; +0.35 luminance over both neighbours)
  no black frames found
SOUND
  track 4.000 s at 48000 Hz, mean -17.4 dB, max -4.4 dB (dBFS, 0.5 s windows)
  peaks: 00:01.312 (-4.4 dB)
  bands: low 3% / mid 46% / high 51%  (under 250 Hz / 250-4000 Hz / over 4000 Hz)
  verdict: field sound (broadband, no sustained tonal peaks)  (flatness 0.71, band drift 0.07)
```

  When nothing is found a block says so (`no hard cuts found`, `peaks: none`), so the model downstream is told the absence rather than left to invent one.

- **contact_sheet**: `IMAGE`. Up to 16 evenly spaced frames in a square grid, each tile 320 px wide with its timestamp and frame number burned into the corner. One image, so the Vision Analyzer sees the whole clip in one round trip.

## How the events are found

Every threshold is a named constant at the top of `_forensics.py` with a one-line reason, so a false alarm on unusual footage can be traced to the number that caused it.

- **Hard cut**: the mean absolute luminance change between consecutive frames and the shift in a 16-bin luminance histogram must both be outliers. Outlier means above the clip's own median plus four median absolute deviations, clamped between a floor (6% change, 10% histogram mass) that motion and pans stay under, and a "sure" value (25%, 50%) that always counts, so a slideshow with more cuts than holds still reports its cuts. Cuts within a quarter second of each other are one transition. The transitions into and out of a flash or a black frame are never counted as cuts.
- **The first and last frame**: each has only one neighbour, so it borrows the frame beyond that one for the spike test. A lone bright or black frame at either end is therefore reported as a flash or a black frame, not as a hard cut at 00:00.042 or on the last frame.
- **Freeze**: a run of frames within one 8-bit level of each other (mean change under 1/255) lasting at least half a second. A static camera on a perfectly still subject in clean footage will register too; the line names the frame range so you can judge.
- **Flash**: a frame at least 15% brighter than both its neighbours (adaptive up to 40%). Strobe sequences show as a list of flashes.
- **Black frame**: the same test the other way, a frame at least 15% darker than both its neighbours (adaptive up to 40%): a dropout, a blink cut, a strobe's dark phase. It is reported as its own line, not as two cuts.
- **Peaks**: RMS level per 0.5 s window in dBFS; a window is a peak when it sits two MADs and at least 6 dB above the median window. The loudest eight are listed, each timed at its loudest sample inside the window rather than at the window start, so a click at 1.300 s prints `00:01.300` and the event chain can look for its cause at that moment.
- **Bands**: energy under 250 Hz (rumble, engines, bass), 250 Hz to 4 kHz (voice, most instruments) and over 4 kHz (hiss, cymbals, glass), averaged over the windows that carry signal.
- **Verdict**: `music` when the averaged spectrum has sustained tonal peaks (spectral flatness under 0.2) and the band balance is steady across windows; `field sound` when the spectrum is broadband; `mixed` when there is tonal content over a shifting bed, which is usually speech or music over location sound. Digital silence is reported as `silence`.

## Where it misfires

The heuristics are deliberately simple. Expect false cuts on hard strobing, very fast whip pans across differently lit areas and stylised footage with abrupt colour grading; expect missed cuts between two shots of the same scene with the same tonal balance; expect freezes on clean, static, denoised shots. Cuts closer together than a quarter second are merged into one line, and the frame that line keeps is the strongest of the run, so a burst of five cuts four frames apart can come back as a single line, or as two or three, because each merge can move the kept frame forward and the next cut is measured from there; the times can sit anywhere along the chain. A dissolve shorter than a quarter second is reported as a `hard cut` at one of its steps, since the node measures change, not its shape. A melody whose notes straddle the 250 Hz band edge shifts energy between the low and mid bands from note to note and gets the verdict `mixed` rather than `music`; a bass line or a cello part will do the same. A cut that lands on the frame right after a flash or a black frame is hidden by that spike's exclusion and goes unreported. The numbers in each line (diff, hist, luminance jump, dB) are there so you can see how far past the threshold an event landed. Reverse prompting someone else's clip is a content-rights question for you, not something this node decides.

## Example

A 5 s phone clip of a door slamming: the frames show a freeze of the last 12 frames (the app's end hold), no cuts, no flashes; the sound block lists one peak at 00:02.500 at -3 dB with the verdict `field sound`. Handed to the Vision Analyzer with the event chain focus, the model reports the hand reaching the door at 00:01.500, the slam at 00:02.500 explaining the peak, and the still hold from 00:04.500. The Promptor turns that into one shot with a slam in `overall_soundscape` and `N/A` for music.
