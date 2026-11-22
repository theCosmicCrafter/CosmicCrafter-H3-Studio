// Timeline-wide settings for long continuing chains: the Timeline keys context_noise, continuation_guide,
// audio_feather and video_slices, as h3_continuity/timeline.py reads them. A default is never written.
const MAX_FEATHER = 16;
const slotNumber = (slot) => Number(slot.slice('video'.length));

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function field(label, title, ...controls) {
  const node = el('label', 'h3ct-field');
  node.title = title;
  node.append(el('span', 'h3ct-label', label), ...controls);
  return node;
}

function checkbox(onChange) {
  const input = el('input');
  input.type = 'checkbox';
  input.addEventListener('change', () => onChange(input.checked));
  return input;
}

export class ChainSettings {
  // editor: the Timeline editor; commit() saves its state, host.connected() lists the reference videos.
  constructor(editor) {
    this.editor = editor;
    this.root = el('details', 'h3ct-advanced');
    this.noiseInput = checkbox((on) => this.set('context_noise', on || undefined));
    this.guideInput = checkbox((on) => this.set('continuation_guide', on ? undefined : false));
    this.featherInput = el('input', 'h3ct-number');
    Object.assign(this.featherInput, {type: 'number', min: '0', max: String(MAX_FEATHER), step: '1'});
    // On change, not input: a redraw while typing would put 0 back into a field just cleared.
    this.featherInput.addEventListener('change', () => {
      const ticks = Math.min(MAX_FEATHER, Math.max(0, Math.round(Number(this.featherInput.value)) || 0));
      this.featherInput.value = String(ticks);
      this.set('audio_feather', ticks || undefined);
    });
    this.slicesEl = el('div');
    this.root.append(el('summary', null, 'Long continuing chains'),
      el('p', 'h3ct-hint', 'These apply to every continuing clip; a split video, to every clip that mentions it. '
        + 'Changing noise, guide or feather marks those clips as changed until they render again. A split changes only '
        + 'the video they receive, which the Studio cannot see: rendered clips still show as rendered, and Run in the '
        + 'graph renders them again.'),
      field('Context noise', 'Adds fading noise to the frames each continuing clip carries, so fine texture builds up '
        + 'less ("burn") over a long chain. About 10% slower per continuing clip.', this.noiseInput),
      field('Guide from the last frame', "Guides each continuing clip's first new frame with the previous clip's last "
        + 'frame, so the pose does not reset. In moving shots it holds about 3 frames at the join: untick it there.',
      this.guideInput),
      field('Audio feather', 'The last carried audio regenerates over this many ticks of 25 ms, rising from frozen to '
        + 'free. 0 keeps all carried audio frozen.', this.featherInput, el('span', 'h3ct-hint', 'ticks of 25 ms, 0–16')),
      this.slicesEl);
  }

  set(key, value) {
    if (value === undefined) delete this.editor.state[key];
    else this.editor.state[key] = value;
    this.editor.commit();
  }

  toggleSlice(slot, on) {
    const slots = new Set(this.editor.state.video_slices ?? []);
    if (on) slots.add(slot);
    else slots.delete(slot);
    this.set('video_slices', slots.size ? [...slots].sort((a, b) => slotNumber(a) - slotNumber(b)) : undefined);
  }

  render() {
    const state = this.editor.state;
    this.noiseInput.checked = state.context_noise === true;
    this.guideInput.checked = state.continuation_guide !== false;
    if (document.activeElement !== this.featherInput) this.featherInput.value = String(state.audio_feather ?? 0);
    const listed = state.video_slices ?? [];
    const connected = (this.editor.host.connected().videos ?? []).filter((ref) => !ref.problem).map((ref) => ref.name);
    const slots = [...new Set([...connected, ...listed])].sort((a, b) => slotNumber(a) - slotNumber(b));
    // Rebuilt only when the slots change, so a ticked box keeps keyboard focus through the redraw after its edit.
    if (slots.join() !== this.slots?.join()) {
      this.slots = slots;
      this.sliceInputs = new Map(slots.map((slot) => [slot, checkbox((on) => this.toggleSlice(slot, on))]));
      this.slicesEl.replaceChildren(...(slots.length ? slots.map((slot) => field(`Split @${slot} across clips`,
        `Each clip receives only its own part of @${slot} and of @video_audio${slotNumber(slot)}: from its start in the `
        + `Timeline, minus the frames it carries, through its last frame. Mention @${slot} in each clip's prompt.`,
        this.sliceInputs.get(slot))) : [el('span', 'h3ct-hint', 'Connect a video to split it across clips.')]));
    }
    for (const [slot, input] of this.sliceInputs) input.checked = listed.includes(slot);
  }
}
