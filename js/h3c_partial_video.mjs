// The video the Studio plays and downloads as the full video: the assembled full video; or, while a Timeline that
// splits a video across clips still has clips to render, the partial video (rendered clips, the source for the rest);
// or else the video so far (the clips rendered from the first one on, with the soundtrack), so timing can be checked
// before every clip renders.
export function exportedVideo(status) {
  if (status?.full_video) return {file: status.full_video, partial: null, preview: null, clock: status.full_video_clock ?? null};
  if (status?.partial_video?.file) return {file: status.partial_video.file, partial: status.partial_video, preview: null, clock: null};
  if (status?.preview_video?.file) return {file: status.preview_video.file, partial: null, preview: status.preview_video,
    clock: status.preview_video.clock ?? null};
  return null;
}

const summary = (partial) => `${partial.rendered} of ${partial.boxes} clips repainted, the rest from the source`;

export const partialBadge = (partial) => `Partial video · ${summary(partial)}`;

export const partialTitle = (partial) => `${summary(partial)}.${partial.note ? ` ${partial.note}` : ''}`;

const clips = (preview) => preview.boxes === 1 ? 'clip 1' : `clips 1–${preview.boxes}`;

export const previewLabel = (preview) => `Video so far · ${preview.boxes}/${preview.total}`;

export const previewBadge = (preview) => `Video so far · ${clips(preview)} of ${preview.total}`;

export const previewTitle = (preview) => `Play ${clips(preview)} of ${preview.total}, rendered so far, joined with the `
  + 'soundtrack: check timing before the rest render. It grows as more clips render.';

// The Timeline frame (24 fps) shown at `seconds` into a video whose `clock` is [[first video frame, frames, first
// Timeline frame, 1 when the Timeline advances with it or 0 while a bridge inserts time]], or the same frame without
// one. Past the last part the Timeline holds at its end.
export function timelineFrame(clock, seconds, fps = 24) {
  const frame = Math.max(0, seconds * fps);
  if (!clock?.length) return frame;
  for (const [video, frames, at, moves] of clock) {
    if (frame < video + frames) return at + (moves ? Math.max(0, frame - video) : 0);
  }
  const [, frames, at, moves] = clock[clock.length - 1];
  return at + (moves ? frames : 0);
}

// The seconds into the video where Timeline `frame` plays, or null when the video doesn't reach it.
export function videoSeconds(clock, frame, fps = 24) {
  if (!clock?.length) return Math.max(0, frame) / fps;
  for (const [video, frames, at, moves] of clock) {
    if (moves && frame >= at && frame < at + frames) return (video + frame - at) / fps;
  }
  return null;
}
