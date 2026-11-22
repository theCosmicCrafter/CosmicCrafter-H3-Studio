// Shared fixtures for Shot splitting and reading existing frame guides in the browser and renderer.
export const CONTEXT = 39;
export const guideFile = (name = 'guide_a') => ({ filename: `${name}.png`, subfolder: 'h3_previews', type: 'output' });

const box = (id, frames, prompt, extra = {}) => ({
  id, frames, prompt, seed: 7, cut: false, first: '', last: '', ...extra,
});

// A fresh clip; the accepted guide sits on Shot 2's start (frame 96).
export function shotGuideTimeline() {
  return {
    prompt: '',
    boxes: [box('a', 192, [
      '[Shot 1] A woman walks along the pier.',
      '[Shot 2] At 00:04.000, the camera cuts to a close-up of her face.',
      '[Shot 3] At 00:06.000, the camera cuts to the sea.',
    ].join('\n'), {
      previews: [
        { target: { kind: 'shot', shot: 2 }, frame: 96, guide: guideFile(), images: [{ file: guideFile('cand_b') }],
          still_prompt: 'Close-up of her face.' },
        { target: { kind: 'shot', shot: 3 }, frame: 144, guide: guideFile('guide_c') },
      ],
    })],
  };
}

// A project already saved by the removed guide-split feature: its paired endpoints and Continue join stay valid.
export function savedGuideSplitTimeline() {
  const prompt = '[Shot 1] The camera starts at her feet and tilts up.';
  return {
    prompt: '',
    boxes: [
      box('a', 107, prompt, {
        previews: [{ target: { kind: 'last' }, frame: 106, guide: guideFile() }],
      }),
      box('b', 102, prompt, {
        previews: [{ target: { kind: 'first' }, frame: 0, guide: guideFile() }],
      }),
    ],
  };
}

export function unstructuredGuideTimeline() {
  return { prompt: '', boxes: [box('a', 192, 'The camera starts at her feet and tilts up.', {
    previews: [{ shot: 9, frame: 80, guide: guideFile() }],
  })] };
}
