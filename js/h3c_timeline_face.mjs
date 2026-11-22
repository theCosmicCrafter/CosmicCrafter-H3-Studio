// The Timeline face and native advanced widgets share the Studio editor's saved state.
import {joinKind} from './h3c_timeline_model.mjs?v=1dfc1612e462';
import {setText} from './h3c_dom.mjs?v=584a9bf55653';
export const FACE_HEIGHT = 120;
const STYLE_ID = 'h3ct-face-style';
const CSS = `
.h3ct-face { display: flex; flex-direction: column; flex: none; gap: 4px; width: 100%; height: fit-content; min-height: ${FACE_HEIGHT}px; overflow-y: auto;
  box-sizing: border-box; padding: 4px 2px; color: var(--input-text, #ddd); font: 13px/1.45 system-ui, sans-serif; }
.h3ct-face * { box-sizing: border-box; }
.h3ct-face-summary, .h3ct-face-progress { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.h3ct-face-progress { min-height: 1.45em; color: #aab1bd; }
.h3ct-face-actions { display: flex; gap: 6px; flex-wrap: wrap; }
`;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function button(text, title, onClick, className = '') {
  const node = el('button', `h3ct-button ${className}`.trim(), text);
  node.type = 'button';
  node.title = title;
  node.addEventListener('click', (event) => {
    event.preventDefault();
    onClick();
  });
  return node;
}

export class TimelineFace {
  constructor({open, renderNext, renderAll, editor}) {
    if (!document.getElementById(STYLE_ID)) {
      const style = el('style');
      style.id = STYLE_ID;
      style.textContent = CSS;
      document.head.append(style);
    }
    this.root = el('div', 'h3ct-face');
    this.root.addEventListener('pointerdown', (event) => event.stopPropagation());
    this.root.addEventListener('keydown', (event) => {
      if (!event.ctrlKey && !event.metaKey && !event.altKey) event.stopPropagation();
    });
    this.summaryEl = el('div', 'h3ct-face-summary');
    this.progressEl = el('div', 'h3ct-face-progress');
    this.progressEl.setAttribute('aria-live', 'polite');
    this.nextButton = button('Render next', 'Queue one run, for the next box that is not rendered yet', renderNext);
    this.allButton = button('▶ Render', 'Queue one run per box that is not rendered yet', renderAll, 'h3ct-primary');
    this.generateButton = button('Generate clip', 'Generate the selected clip using its seed mode', () => editor.queueBox(1));
    const actions = el('div', 'h3ct-face-actions');
    actions.append(button('Open Studio', 'Edit this Timeline in a full-window Studio', open), this.nextButton, this.allButton, this.generateButton);
    this.root.append(this.summaryEl, this.progressEl, actions);
    this.editor = editor;
  }

  height() { return Math.max(FACE_HEIGHT, this.root.scrollHeight); }

  mountWidgets(node) {
    const editor = this.editor;
    this.controls = {};
    const add = (type, name, label, value, callback, options = {}) => {
      const widget = node.addWidget(type, name, value, callback, {...options, serialize:false, advanced:true});
      widget.label = label; widget.advanced = true; widget.serialize = false;
      this.controls[name] = widget;
      return widget;
    };
    const edit = (name, value) => {
      if (!editor.box()) return;
      const original = editor[name];
      if (original.type === 'checkbox') original.checked = value;
      else original.value = String(value);
      original.dispatchEvent(new Event('change'));
    };
    add('combo','h3c_clip','Selected clip','No clips', value => editor.select(this.controls.h3c_clip.options.values.indexOf(value)), {values:['No clips']});
    add('text','h3c_clip_seed','Clip seed','', value => edit('seedInput',value), {tooltip:'Unsigned 64-bit integer. Empty initializes a seed once.'});
    add('button','h3c_new_seed','New seed',null, () => editor.rollSeedButton.click());
    add('combo','h3c_clip_seed_mode','Clip seed mode','Fixed', value => edit('seedMode',value.toLowerCase()), {values:['Fixed','Randomize']});
    add('number','h3c_clip_frames','Clip frames',1, value => edit('framesInput',value), {min:1,max:362,step:10,precision:0});
    add('toggle','h3c_clip_exact','Exact clip length',false, value => edit('exactInput',value));
    this.joins = {continue:'Continue',transition:'Transition',cut:'Cut',new_scene:'New scene'};
    add('combo','h3c_clip_join','Clip join','Continue', value => edit('joinSelect',Object.keys(this.joins).find(key => this.joins[key] === value)), {values:Object.values(this.joins)});
    this.memories = {off:'Off',scene:'Same scene',selected:'Selected moments',cast:'Cast'};
    add('combo','h3c_clip_memory','Clip visual memory','Off', value => {
      editor.box().memory = Object.keys(this.memories).find(key => this.memories[key] === value); editor.commit();
    }, {values:Object.values(this.memories)});
    add('toggle','h3c_clip_refmods','FLF2VA + cached RefMods',false, value => edit('refmodFramesInput',value), {tooltip:editor.refmodFramesField.title});
    this.settings();
  }

  settings() {
    const editor = this.editor, box = editor.box(), widgets = this.controls;
    setText(this.generateButton, box ? `Generate clip ${editor.selected + 1}` : 'Generate clip');
    this.generateButton.disabled = !box || editor.boxRenderButton.disabled || !!editor.queueBatch;
    this.seedError = box ? editor.seedInput.validationMessage : '';
    if (!widgets) return;
    for (const widget of Object.values(widgets)) { widget.disabled = !box; widget.options.disabled = !box; }
    widgets.h3c_clip.options.values = editor.state.boxes.length ? editor.state.boxes.map((item,index) => `Clip ${index + 1}`) : ['No clips'];
    widgets.h3c_clip.value = box ? `Clip ${editor.selected + 1}` : 'No clips';
    if (!box) return;
    if (!this.seedError) widgets.h3c_clip_seed.value = String(box.seed ?? '');
    widgets.h3c_clip_seed_mode.value = box.seed_mode === 'randomize' ? 'Randomize' : 'Fixed';
    widgets.h3c_clip_frames.value = box.frames; widgets.h3c_clip_frames.options.max = Number(editor.framesInput.max);
    widgets.h3c_clip_exact.value = !!box.exact;
    widgets.h3c_clip_join.value = this.joins[joinKind(box)];
    widgets.h3c_clip_join.disabled = editor.selected === 0; widgets.h3c_clip_join.options.disabled = editor.selected === 0;
    widgets.h3c_clip_memory.options.values = Object.values(this.memories).filter(value => value !== 'Cast' || editor.state.bible || box.memory === 'cast');
    widgets.h3c_clip_memory.value = this.memories[box.memory ?? 'off'];
    widgets.h3c_clip_refmods.value = !!box.flf_refmods;
  }

  update({summary, progress, allLabel, canRender}) {
    this.settings();
    setText(this.summaryEl, summary);
    this.summaryEl.title = summary;
    setText(this.progressEl, this.seedError || progress);
    setText(this.allButton, allLabel);
    this.nextButton.disabled = !canRender;
    this.allButton.disabled = !canRender;
  }
}
