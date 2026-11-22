import * as tracks from './h3c_tracks.mjs';
import * as model from './h3c_timeline_model.mjs?v=1dfc1612e462';
import { importWhisper, validateTimedText, setTextSync, textClock, projectTimedText } from './h3c_timed_text.mjs?v=21a5be84eb83';
import { loadAudio, loaded, beatTimes, drawWave } from './h3c_waveform.mjs?v=162256e10b5b';
import {captureWindows,resolveWindows,unlockWindows,lockEligibility,sourceOrigin,outputWindows,equivalentWindows,timelineAudioParts} from './h3c_audio_windows.mjs?v=cdefbd77b246';
import {replaceChanged, setText} from './h3c_dom.mjs?v=584a9bf55653';

const node = (tag, cls, text) => {
  const item = document.createElement(tag);
  if (cls) item.className = cls;
  if (text != null) item.textContent = text;
  return item;
};
const button = (text, action) => {
  const item = node('button', 'h3ct-button', text);
  item.type = 'button'; item.addEventListener('click', action);
  return item;
};
// A lane clip takes one of the node's wired audio slots; the Timeline refuses any other, such as a voice clip's.
const LANE_SLOTS = Array.from({length: model.MAX_REF_AUDIOS}, (_, i) => `audio${i + 1}`);
const SNAP_KEY = 'h3c-snap-to-beats';
const MAX_CANVAS = 8192;

export class AudioLanes {
  constructor(editor) {
    this.editor = editor;
    this.root = node('div', 'h3ct-audio');
    this.header = node('div', 'h3ct-row h3ct-audio-lane');
    this.header.style.height = 'auto'; this.header.style.minHeight = '40px';
    this.header.setAttribute('aria-label', 'Audio lane');
    this.upload = node('input');
    this.upload.type = 'file'; this.upload.accept = 'audio/*,.wav,.mp3,.flac,.ogg,.m4a,.aac,.opus,.aiff'; this.upload.hidden = true;
    this.upload.addEventListener('change', () => {
      const file = this.upload.files?.[0]; this.upload.value = '';
      if (file) this.addFile(file);
    });
    this.addButton = button('+ Audio', () => this.upload.click());
    this.addButton.title = 'Upload an audio file, or choose a connected source beside this button';
    this.connectedSelect = node('select', 'h3ct-select');
    this.connectedSelect.setAttribute('aria-label', 'Add connected audio to a lane');
    this.connectedSelect.addEventListener('change', () => {
      const ref = editor.host.connected().audios.find(ref => ref.name === this.connectedSelect.value);
      if (ref) this.addConnected(ref);
    });
    this.message = node('span', 'h3ct-hint');
    this.message.setAttribute('role','status');
    // Beats are found on request, kept for the session by audio file, and drawn as ticks under each waveform.
    this.beats = new Map();
    this.beatMessages = new Map();
    this.drawings = [];
    this.beatButton = button('Detect beats', () => this.detectBeats());
    this.beatButton.title = 'Find beats only in the selected audio lane’s file, drawn as ticks under its waveform';
    this.beatMessage = node('span', 'h3ct-hint');
    this.beatMessage.setAttribute('role', 'status');
    this.snapField = node('label', 'h3ct-field', 'Snap to beats');
    this.snapField.title = 'Dragging a clip’s edge lands it on the nearest beat (hold Shift to drag freely). A clip '
      + 'without an exact length still keeps a length on the frame grid.';
    this.snapInput = node('input'); this.snapInput.type = 'checkbox';
    this.snapInput.setAttribute('aria-label', 'Snap clip edges to beats');
    try { this.snapInput.checked = localStorage.getItem(SNAP_KEY) === '1'; } catch { /* storage may be unavailable */ }
    this.snapInput.addEventListener('change', () => {
      try { localStorage.setItem(SNAP_KEY, this.snapInput.checked ? '1' : '0'); } catch { /* storage may be unavailable */ }
    });
    this.snapField.append(this.snapInput);
    this.textUpload = node('input'); this.textUpload.type = 'file'; this.textUpload.accept = '.json,application/json'; this.textUpload.hidden = true;
    this.textUpload.addEventListener('change', () => {
      const file = this.textUpload.files?.[0]; this.textUpload.value = '';
      if (file) this.importText(file);
    });
    this.textButton = button('+ Text', () => this.textUpload.click());
    this.textButton.title = 'Import timed text from Whisper JSON';
    this.textMessage = node('span', 'h3ct-hint'); this.textMessage.setAttribute('role', 'status');
    this.header.append(node('span', 'h3ct-label', 'Audio'), this.addButton, this.connectedSelect, this.upload,
      this.message);
    this.textHeader = node('div', 'h3ct-row');
    this.textSelect = button('Timed text', () => this.selectText());
    this.textSelect.setAttribute('aria-label', 'Edit timed text');
    this.textHeader.append(node('span', 'h3ct-label', 'Text'), this.textSelect, this.textButton, this.textUpload, this.textMessage);
    this.lanes = node('div', 'h3ct-audio-lanes');
    this.textLane = node('div', 'h3ct-audio-lane h3ct-text-lane');
    this.textLane.style.height = 'auto'; this.textLane.style.minHeight = '40px';
    this.textLane.setAttribute('aria-label', 'Text lane');
    this.textLane.append(this.textHeader);
    this.settings = node('details', 'h3ct-audio-settings');
    this.textSettings = node('details', 'h3ct-audio-settings');
    this.textSummary = node('pre', 'h3ct-hint'); this.textSummary.style.whiteSpace = 'pre-wrap';
    this.root.append(this.lanes, this.header, this.textLane, this.textSettings);
    this.root.addEventListener('dragover', event => {
      if (event.dataTransfer?.types.includes('Files')) { event.preventDefault(); event.stopPropagation(); }
    });
    this.root.addEventListener('drop', event => {
      const file = event.dataTransfer?.files?.[0];
      if (file) {
        event.preventDefault(); event.stopPropagation();
        if (this.textLane.contains(event.target) && /\.json$/i.test(file.name)) this.importText(file);
        else this.addFile(file);
      }
    });
  }

  get text() {
    const state=this.editor.state;
    if(!tracks.enabled(state))return state.timed_text;
    if(!state.tracks.some(t=>t.id===this.selectedTextTrack&&t.type==='text'))this.selectedTextTrack=state.tracks.find(t=>t.type==='text')?.id;
    return state.text_lanes?.find(l=>l.track===this.selectedTextTrack)?.attachment;
  }
  set text(value) {
    const state=this.editor.state;
    if(!tracks.enabled(state)){if(value)state.timed_text=value;else delete state.timed_text;return;}
    if(!state.tracks.some(t=>t.id===this.selectedTextTrack&&t.type==='text'))throw Error('The selected text lane no longer exists.');
    state.text_lanes??=[];state.text_lanes=state.text_lanes.filter(l=>l.track!==this.selectedTextTrack);
    if(value)state.text_lanes.push({track:this.selectedTextTrack,attachment:value});
  }
  syncText(value,enabled,slot) {
    const proxy={...this.editor.state,timed_text:value};setTextSync(proxy,enabled,slot);
  }

  get clips() { return this.editor.state.audio_clips ?? []; }

  // Whether clip edges snap: the box is ticked and some clip's beats are found.
  get snapping() { return this.snapInput.checked && this.beatFrames().length > 0; }

  // The file a clip plays from: its connected source, or its upload; null while a replacement has none.
  sourceFile(clip) {
    const reference = this.editor.host.connected().audios.find(ref => ref.name === clip?.slot);
    return reference?.problem || (reference?.replaced && !reference.mediaFile) ? null : reference?.mediaFile ?? clip?.file ?? null;
  }

  sourceUrl(clip) {
    const file = this.sourceFile(clip);
    return file ? this.editor.host.viewUrl(file) : null;
  }

  // Each enabled clip's found beats inside its window, as Timeline frames.
  beatFrames() {
    const frames = [];
    for (const clip of this.clips) {
      const beats = this.beats.get(this.sourceUrl(clip));
      if (!beats || !model.referenceEnabled(this.editor.state, clip.slot)) continue;
      for (const beat of beats) {
        for(const window of resolveWindows(clip,model.audioBoxSpans(this.editor.state)))
          if(beat>=window.source_start && beat<window.source_start+window.duration)frames.push((window.start+beat-window.source_start)*model.FPS);
      }
    }
    return frames;
  }

  async detectBeats() {
    if (this.findingBeats) return;
    const clip = this.clips.find(clip => clip.slot === this.selected) ?? this.clips[0];
    if (!clip) return;
    const url = this.sourceUrl(clip);
    const message = text => {
      this.beatMessages.set(clip.slot, {url, text});
      this.renderBeatControls();
    };
    if (!url) { message(`@${clip.slot} has no audio file to read.`); return; }
    this.findingBeats = true;
    message(`Finding beats for @${clip.slot}…`);
    try {
      const analysis = await loadAudio(url);
      this.beats.set(url, beatTimes(analysis));
      message(`@${clip.slot}: ${analysis.beats.length} beats at about ${Math.round(analysis.tempo)} BPM.`
        + (this.snapInput.checked ? '' : ' Tick Snap to beats to use them.'));
      this.redraw(url);
    } catch (error) { message(`Could not find beats for @${clip.slot}: ${error.message}`); }
    finally { this.findingBeats = false; this.renderBeatControls(); }
  }

  renderBeatControls() {
    const clip = this.clips.find(clip => clip.slot === this.selected) ?? this.clips[0];
    setText(this.beatButton, clip ? `Detect beats · @${clip.slot}` : 'Detect beats');
    this.beatButton.disabled = !!this.findingBeats;
    const found = this.beatMessages.get(clip?.slot);
    setText(this.beatMessage, found?.url === this.sourceUrl(clip) ? found?.text ?? '' : '');
  }

  // Draws the waveforms decoded since the lanes were drawn (those of `url`, or every one), with their beats.
  redraw(url = null) {
    for (const drawing of this.drawings) {
      if (url && drawing.url !== url) continue;
      const analysis = loaded(drawing.url);
      if (!analysis || !drawing.canvas.isConnected) continue;
      drawing.fallback?.remove();
      drawing.fallback = null;
      drawWave(drawing.canvas, analysis, drawing.clip.source_start, drawing.clip.source_start + drawing.clip.duration,
        this.beats.get(drawing.url) ?? []);
    }
  }

  async setBoxLock(enabled) {
    if(this.boxLockBusy)return false;
    const state=this.editor.state,clip=this.clips.find(c=>c.slot===(this.selected??this.clips[0]?.slot));
    if(!clip || !!clip.box_windows===enabled)return false;
    this.boxLockBusy=true;
    const before=structuredClone(clip), signature=()=>model.serialize(this.editor.state), original=signature();
    let applied=null;
    try {
      if(enabled) {
        const eligibility=lockEligibility(state,clip);
        if(!eligibility.ok){this.message.textContent=eligibility.conflicts.join(' ');return false;}
      } else {
        const boxes=model.audioBoxSpans(state),parts=timelineAudioParts(state),continuous={...clip};delete continuous.box_windows;
        const changed=!equivalentWindows(outputWindows(clip,resolveWindows(clip,boxes),parts),outputWindows(continuous,resolveWindows(continuous,boxes),parts));
        if(changed && !await this.editor.host.confirmAudioUnlock?.())return false;
        if(this.editor.state!==state || signature()!==original){this.message.textContent='The Timeline changed. Review its current audio before unlocking.';return false;}
      }
      if(enabled)clip.box_windows=captureWindows(clip,model.audioBoxSpans(state),sourceOrigin(state,clip));
      else unlockWindows(clip);
      applied=signature();
      await this.editor.commit();
      this.message.textContent=enabled?'Audio ranges now follow their boxes.':'Continuous audio placement restored.';
      return true;
    } catch(error) {
      if(applied && this.editor.state===state && signature()===applied) {
        for(const key of Object.keys(clip))delete clip[key];Object.assign(clip,before);
        this.editor.host.write?.(model.serialize(state));
      }
      this.message.textContent=error.message;return false;
    } finally {this.boxLockBusy=false;this.settingsKey=null;}
  }

  selectAudio(slot, boxId = null) {
    if (!this.clips.some(clip => clip.slot === slot)) return;
    this.selected = slot; this.auditionBox=boxId; this.settings.open = true;
    this.renderSettings();
    this.editor.inspect({kind: 'audio', slot});
  }

  selectText() {
    if (!this.text) return;
    this.textSettings.open = true;
    this.editor.inspect({kind:'text',track:this.selectedTextTrack});
  }

  async importText(file) {
    const originalState=this.editor.state,targetTrack=this.selectedTextTrack;
    this.textButton.disabled = true; this.textMessage.textContent = 'Reading text…';
    try {
      const bytes = await file.arrayBuffer();
      const digest = await crypto.subtle.digest('SHA-256', bytes);
      const hash = Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, '0')).join('');
      const value = importWhisper(JSON.parse(new TextDecoder('utf-8', {fatal:true}).decode(bytes)), file.name, hash);
      await this.editor.host.uploadWhisper?.(file, hash);
      if(originalState!==this.editor.state||targetTrack!==this.selectedTextTrack)throw Error('The project or text lane changed; import the file again.');
      this.text = value;
      this.textSettings.open = true; this.textMessage.textContent = '';
      this.editor.commit();
      this.selectText();
    } catch (error) { this.textMessage.textContent = error.message; if(this.editor.trackEditor)this.editor.trackEditor.message.textContent=error.message; }
    finally { this.textButton.disabled = false; }
  }

  renderText() {
    const state = this.editor.state, value = this.text;
    this.textSettings.hidden = !value;
    this.textSelect.hidden = !value;
    const signature = JSON.stringify([value, this.clips]);
    const sameState = this.textState === state && this.textValue === value;
    const typing = sameState && this.textSettings.contains(document.activeElement) && document.activeElement.tagName === 'TEXTAREA';
    if ((!sameState || this.textKey !== signature) && !typing) {
      this.textKey = signature; this.textState = state; this.textValue = value;
      this.textSettings.replaceChildren(node('summary', null, 'Timed text · Whisper JSON'), button('Remove text', () => {
        this.text = null; this.textMessage.textContent = ''; this.editor.commit(); this.editor.inspectClip();
      }));
      if (value) {
        this.textSettings.append(node('div', 'h3ct-hint', `${value.source_name ?? 'Text'} · SHA-256 ${value.source_sha256 ?? 'missing'}`));
        try {
          validateTimedText(value);
          const row = node('div', 'h3ct-row');
          for (const [key, label] of [['enabled', 'Enable timed text'], ['sync_audio', 'Sync text to audio']]) {
            const field = node('label', 'h3ct-field', label), input = node('input'); input.type = 'checkbox'; input.checked = value[key];
            input.setAttribute('aria-label', label);
            input.addEventListener('change', () => {
              try {
                if (key === 'sync_audio') this.syncText(value,input.checked); else value.enabled = input.checked;
                this.editor.commit();
              }catch(error){input.checked=value[key];this.textMessage.textContent=error.message;this.textSummary.textContent=error.message;}
            });
            field.append(input); row.append(field);
          }
          const lane = node('select', 'h3ct-select'); lane.setAttribute('aria-label', 'Text audio lane');
          for (const slot of ['audio1','audio2','audio3']) {
            const clip = this.clips.find(clip => clip.slot === slot);
            const option = node('option', null, `@${slot}${clip ? ` · ${clip.title ?? 'Audio'}` : ' (missing lane)'}`); option.value = slot; lane.append(option);
          }
          lane.value = value.audio_slot;
          lane.addEventListener('change', () => { this.syncText(value,value.sync_audio,lane.value); this.editor.commit(); });
          row.append(lane); this.textSettings.append(row);
          const timing = node('div', 'h3ct-row'), clock = textClock(value, this.clips);
          for (const [key, label] of [['start','Text video start (s)'],['source_start','Text source in (s)'],['duration','Text length (s)']]) {
            const field = node('label', 'h3ct-field', label), input = node('input', 'h3ct-number');
            input.type = 'number'; input.min = key === 'duration' ? .001 : 0; input.step = 'any'; input.required = true;
            input.value = clock[key]; input.disabled = value.sync_audio; input.setAttribute('aria-label', label);
            input.addEventListener('change', () => {
              const number = Number(input.value);
              if (!input.value || !Number.isFinite(number) || number < 0 || (key === 'duration' && number === 0)) { input.value = value[key]; return; }
              value[key] = number; this.editor.commit();
            });
            field.append(input); timing.append(field);
          }
          const direction = node('textarea', 'h3ct-text'); direction.rows = 2; direction.value = value.direction;
          direction.setAttribute('aria-label', 'Text direction'); direction.placeholder = 'Describe how these exact words appear: placement, typography, motion…';
          direction.addEventListener('input', () => { value.direction = direction.value; this.editor.typed(); });
          direction.addEventListener('change', () => { value.direction = direction.value; this.editor.commit(false); });
          const treatment = node('label', 'h3ct-field', 'Text visual direction'); treatment.append(direction);
          this.textSettings.append(timing, treatment);
        } catch { /* The removable attachment's precise error is displayed below. */ }
      }
      this.textSettings.append(this.textSummary);
    }
    if (!value) { setText(this.textSummary, ''); return; }
    try {
      validateTimedText(value);
      const clock = textClock(value, this.clips);
      if (!clock.resolved) { setText(this.textSummary, `@${value.audio_slot} lane is missing. Select a lane or turn sync off.`); return; }
      if (!value.enabled) { setText(this.textSummary, 'Timed text is disabled.'); return; }
      const index = this.editor.selected, box = state.boxes[index];
      const start = tracks.startFrame(state,state.boxes[index]?.id) / model.FPS;
      const window = projectTimedText(value, this.clips, start, box?.frames ?? model.totalFrames(state),
        box && !model.isFresh(state, index) ? this.editor.host.context() : 0, model.resolvedAudio(state));
      setText(this.textSummary, (clock.box_windows?'Audio follows boxes':`Movie ${clock.start} s · source ${clock.source_start}–${clock.source_start + clock.duration} s`)
        + `\nClip ${index + 1} source ${window.source_windows?.map(w=>`${w.source_start}–${w.source_end}`).join(', ') || `${window.source_start ?? '—'}–${window.source_end ?? '—'}`} s · replay ${window.replay_end_ms} ms`
        + `${window.direction ? `\nDirection: ${window.direction}` : ''}`
        + (window.cues.length ? window.cues.map(cue => `\n${cue.start_ms}–${cue.end_ms} ms${cue.continuing ? ' · continuing' : ''}${cue.replay_only ? ' · replay only' : ''}\n${cue.text}`).join('') : '\nNo active phrases in this clip.'));
    } catch (error) { setText(this.textSummary, error.message); }
  }

  async addFile(file) {
    if (this.busy) return;
    const occupied = new Set([...this.editor.referenceOptions().map(ref => ref.name), ...this.clips.map(clip => clip.slot)]);
    const slot = LANE_SLOTS.find(slot => !occupied.has(slot));
    if (!slot) { this.message.textContent = 'All three audio slots are in use. Remove a clip or disconnect a reference.'; if(this.editor.trackEditor)this.editor.trackEditor.message.textContent=this.message.textContent; return; }
    await this.add(slot, () => this.editor.host.uploadAudio(file), true);
  }

  async addConnected(ref) {
    if (this.busy) return;
    if (!ref.mediaFile) { this.message.textContent = 'For a draggable lane, use Load Audio or upload the source file here.'; return; }
    await this.add(ref.name, async () => ({title: ref.title || ref.file,
      ...await this.editor.host.audioInfo(ref.mediaFile)}), false);
  }

  async add(slot, read, uploaded) {
    const targetTrack=this.pendingTrack,originalState=this.editor.state;
    this.busy = true; this.addButton.disabled = true; this.message.textContent = 'Reading audio…';
    try {
      const source = await read();
      if(originalState!==this.editor.state)throw Error('The project changed while reading audio; add the file again.');
      if(tracks.enabled(this.editor.state)&&!this.editor.state.tracks.some(t=>t.id===targetTrack&&t.type==='audio'))throw Error('Select an audio lane before importing a source.');
      if (!Number.isFinite(source.duration) || source.duration <= 0) throw new Error('This file has no playable audio.');
      if (this.clips.some(clip => clip.slot === slot)) throw new Error(`${slot} is already in use.`);
      const video = model.totalFrames(this.editor.state) / model.FPS;
      this.editor.state.audio_clips ??= [];
      this.clips.push({slot, ...(tracks.enabled(this.editor.state)?{track:targetTrack}:{}), ...(uploaded ? {file: source.file} : {}), title: source.title,
        start: 0, source_start: 0, duration: video ? Math.min(video, source.duration) : source.duration,
        source_duration: source.duration, peaks: source.peaks, layer: 'music', description: ''});
      this.editor.state.disabled_refs = (this.editor.state.disabled_refs ?? []).filter(name => name !== slot);
      this.selected = slot; this.settings.open = true; this.message.textContent = '';
      this.editor.commit();
      this.selectAudio(slot);
    } catch (error) { this.message.textContent = error.message; if(this.editor.trackEditor)this.editor.trackEditor.message.textContent=error.message; }
    finally { this.busy = false; this.addButton.disabled = false; }
  }

  width() {
    return this.lanes.getBoundingClientRect().width;
  }

  render(span, laneWidth) {
    this.span = span;
    this.renderLanes(laneWidth);
    const connected = this.editor.host.connected().audios.filter(ref => !ref.refmod && LANE_SLOTS.includes(ref.name)
      && !this.clips.some(clip => clip.slot === ref.name));
    const prompt = node('option', null, 'Add connected audio…');
    prompt.value = '';
    replaceChanged(this.connectedSelect, [prompt, ...connected.map(ref => {
      const option = node('option', null, `@${ref.name} · ${ref.title || ref.name}`);
      option.value = ref.name;
      return option;
    })]);
    this.connectedSelect.value = '';
    this.connectedSelect.hidden = !connected.length;
    this.renderSettings();
  }

  renderLanes(laneWidth = this.width()) {
    this.renderText();
    // Drawn again only when what the lanes show changed: every redraw restyles the whole ComfyUI page.
    const refs = this.editor.host.connected().audios;
    const key = JSON.stringify([this.clips, this.clips.map(clip => {
      const reference = refs.find(ref => ref.name === clip.slot);
      return [reference?.replaced, reference?.title, this.sourceUrl(clip)];
    }), model.audioBoxSpans(this.editor.state), this.span, laneWidth, this.editor.state.disabled_refs,
    globalThis.devicePixelRatio]);
    if (this.lanesState === this.editor.state && this.lanesKey === key) return;
    this.lanesState = this.editor.state; this.lanesKey = key;
    if (this.header.parentNode === this.lanes) this.lanes.after(this.header);
    this.lanes.replaceChildren();
    this.drawings = [];
    if (!this.clips.length) {
      this.lanes.append(this.header);
    }
    for (const recording of this.clips) {
      const clip=recording;
      const reference = this.editor.host.connected().audios.find(ref => ref.name === clip.slot);
      const title = reference?.replaced ? reference.title || 'Replacement unavailable' : clip.title || 'Audio';
      const lane = node('div', 'h3ct-audio-lane');
      lane.setAttribute('aria-label', `Audio lane @${clip.slot}`);
      const video = node('div', 'h3ct-audio-video');
      video.style.width = `${100 * model.totalFrames(this.editor.state) / this.span}%`;
      lane.append(video);
      const spans=model.audioBoxSpans(this.editor.state),windows=resolveWindows(recording,spans);
      if(recording.box_windows)for(const [index,span] of spans.entries()) {
        const window=windows.find(w=>w.box===span.id);
        const gaps=window?[[span.start,window.start],[window.start+window.duration,span.start+span.duration]]:[[span.start,span.start+span.duration]];
        for(const [first,last] of gaps)if(last>first) {
          const gap=button(`Silence · Box ${index+1}`,()=>this.selectAudio(recording.slot,span.id));gap.className='h3ct-audio-gap';
          gap.style.left=`${100*first*model.FPS/this.span}%`;gap.style.width=`${100*(last-first)*model.FPS/this.span}%`;
          gap.title=`Box ${index+1} · no assigned audio in this region`;gap.setAttribute('aria-label',`@${recording.slot}, box ${index+1}: no assigned audio`);lane.append(gap);
        }
      }
      for(const clip of recording.box_windows?windows.map(window=>({...recording,...window})):[recording]) {
      const item = node('div', 'h3ct-audio-clip');
      item.classList.toggle('box-bound',!!recording.box_windows);
      if(clip.box)item.dataset.box=clip.box;
      item.style.left = `${100 * clip.start * model.FPS / this.span}%`;
      item.style.width = `${100 * clip.duration * model.FPS / this.span}%`;
      item.classList.toggle('disabled', !model.referenceEnabled(this.editor.state, clip.slot));
      item.tabIndex = 0; item.setAttribute('role', 'button');
      const inFullVideo = clip.in_full_video === true && !!clip.file;
      item.setAttribute('aria-label', `Edit @${clip.slot} audio clip${inFullVideo ? ', in the full video' : ''}`);
      item.title = `${title} · ${clip.duration.toFixed(3)} s · original speed\n`+(recording.box_windows?`Box ${this.editor.state.boxes.findIndex(b=>b.id===clip.box)+1} · source ${clip.source_start.toFixed(3)}–${(clip.source_start+clip.duration).toFixed(3)} s · follows box`:'Drag to move · edges trim · Shift-drag selects a different source window')
        + (inFullVideo ? '\nIn the full video' : '');
      const url = reference?.replaced ? null : this.sourceUrl(clip);
      let pending = null;
      if (url) {
        // The detailed waveform, decoded in the browser; the coarse saved peaks show until it is ready.
        const canvas = node('canvas');
        canvas.setAttribute('aria-hidden', 'true');
        const scale = globalThis.devicePixelRatio || 1;
        const pixels = (laneWidth || 800) * clip.duration * model.FPS / this.span * scale;
        canvas.width = Math.max(1, Math.min(MAX_CANVAS, Math.round(pixels)));
        canvas.height = Math.round(36 * scale);
        item.append(canvas);
        const drawing = {canvas, clip, url, fallback: null};
        this.drawings.push(drawing);
        if (!loaded(url)) {
          loadAudio(url).then(() => this.redraw(url)).catch(() => { /* the saved peaks stay */ });
          pending = drawing;
        }
      }
      if (!reference?.replaced && (!url || pending)) {
        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('viewBox', '0 0 256 36'); svg.setAttribute('preserveAspectRatio', 'none');
        svg.setAttribute('aria-hidden', 'true');
        const peaks = model.audioSourceDuration(clip) === null ? [] : clip.peaks ?? [];
        const max = Math.max(.001, ...peaks);
        for (let i = 0; i < 128; i++) {
          const source = clip.source_start + (i + .5) / 128 * clip.duration;
          const peak = peaks[Math.min(peaks.length - 1, Math.floor(source / clip.source_duration * peaks.length))] ?? 0;
          const rect = document.createElementNS(svg.namespaceURI, 'rect');
          const height = Math.max(1, 32 * peak / max);
          for (const [key, value] of Object.entries({x: i * 2, y: (36 - height) / 2, width: 1, height})) rect.setAttribute(key, value);
          svg.append(rect);
        }
        item.append(svg);
        if (pending) pending.fallback = svg;
      }
      item.append(node('span', 'h3ct-audio-label', `@${clip.slot} · ${title} · ${clip.duration.toFixed(2)} s${reference?.replaced ? ' · Replaced source' : ''}${clip.locked === true && clip.file ? ' · locked' : ''}`));
      for (const edge of recording.box_windows || model.audioSourceDuration(clip) === null ? [] : ['left', 'right']) {
        const handle = node('div', `h3ct-audio-handle ${edge}`);
        handle.title = `Drag to trim the ${edge} edge`;
        handle.addEventListener('pointerdown', event => this.drag(event, clip, edge));
        item.append(handle);
      }
      item.addEventListener('pointerdown', event => this.drag(event, clip, event.shiftKey ? 'source' : 'move'));
      item.addEventListener('click', () => this.selectAudio(clip.slot,clip.box??null));
      item.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); item.click(); }
        if (!recording.box_windows && ['ArrowLeft', 'ArrowRight'].includes(event.key)) {
          event.preventDefault(); Object.assign(clip, model.editAudioClip(clip, 'move', (event.key === 'ArrowLeft' ? -1 : 1) / model.FPS));
          this.editor.commit();
        }
      });
      lane.append(item);
      }
      this.lanes.append(lane);
    }
    this.redraw();
  }

  drag(event, clip, mode) {
    if(clip.box_windows || (mode !== 'move' && model.audioSourceDuration(clip) === null))return;
    if (event.button !== 0 || (event.pointerType === 'touch' && !['left', 'right'].includes(mode)
      && getComputedStyle(this.root).touchAction.includes('pan-x'))) return;
    event.preventDefault(); event.stopPropagation();
    const before = {...clip}, x = event.clientX, id = event.pointerId;
    const perPixel = this.span / model.FPS / (this.lanes.getBoundingClientRect().width || 1);
    this.selectAudio(clip.slot);
    try { this.root.setPointerCapture(id); } catch { /* synthetic test pointers */ }
    const move = e => {
      if (e.pointerId !== id) return;
      const delta = Math.round((e.clientX - x) * perPixel * model.FPS) / model.FPS;
      if (mode === 'source') clip.source_start = Math.max(0, Math.min(before.source_start + delta, clip.source_duration - clip.duration));
      else Object.assign(clip, model.editAudioClip(before, mode, delta));
      this.renderLanes();
    };
    const end = e => {
      if (e.pointerId !== id) return;
      this.root.removeEventListener('pointermove', move);
      this.root.removeEventListener('pointerup', end);
      this.root.removeEventListener('pointercancel', end);
      if (e.type === 'pointercancel') Object.assign(clip, before);
      this.editor.commit();
    };
    this.root.addEventListener('pointermove', move);
    this.root.addEventListener('pointerup', end);
    this.root.addEventListener('pointercancel', end);
  }

  recoverSourceDuration(clip, file) {
    if (!file || !this.editor.host.audioInfo || model.audioSourceDuration(clip) !== null) return;
    this.durationReads ??= new WeakMap();
    const key = JSON.stringify(file), state = this.editor.state;
    if (this.durationReads.get(clip) === key) return;
    this.durationReads.set(clip, key);
    void (async () => {
      try {
        const source = await this.editor.host.audioInfo(file);
        if (this.editor.state !== state || !this.clips.includes(clip)
          || JSON.stringify(this.sourceFile(clip)) !== key || model.audioSourceDuration(clip) !== null) return;
        if (!Number.isFinite(source.duration) || source.duration <= 0) return;
        clip.source_duration = source.duration;
        await this.editor.commit();
        if (this.editor.state === state) this.renderSettings();
      } catch { /* Keep the placed window editable without inventing source bounds. */ }
      finally { this.durationReads.delete(clip); }
    })();
  }

  renderSettings() {
    this.renderBeatControls();
    const clip = this.clips.find(clip => clip.slot === this.selected) ?? this.clips[0];
    const reference = this.editor.host.connected().audios.find(ref => ref.name === clip?.slot);
    const file = this.sourceFile(clip);
    const signature = JSON.stringify([this.clips, clip?.slot, this.editor.state.boxes.map(b=>[b.id,b.frames]),this.editor.state.bridges,this.auditionBox,file,reference?.replaced]);
    const typing = this.settingsClip === clip && this.settingsState === this.editor.state
      && this.settings.contains(document.activeElement) && document.activeElement.tagName === 'TEXTAREA';
    if (typing) { this.renderPlayer(file, clip); return; }
    if (this.settingsKey === signature && this.settingsClip === clip) return;
    this.settingsState = this.editor.state;
    this.settingsKey = signature; this.settingsClip = clip;
    this.settings.replaceChildren(node('summary', null, clip?.box_windows?'Audio settings · audio ranges follow boxes':'Audio settings · move clips and trim their edges above the clips'));
    this.settings.hidden = !this.clips.length;
    if (!clip) return;
    const sourceDuration = model.audioSourceDuration(clip);
    if (!reference?.replaced) this.recoverSourceDuration(clip, file);
    const row = node('div', 'h3ct-row');
    const choose = node('select', 'h3ct-select'); choose.setAttribute('aria-label', 'Selected audio clip');
    for (const c of this.clips) { const option = node('option', null, `@${c.slot} · ${c.title||c.file?.filename||'Audio'}`); option.value = c.slot; choose.append(option); }
    choose.value = clip.slot;
    choose.addEventListener('change', () => this.selectAudio(choose.value));
    const fit=button('Fit to video', () => {
      if(clip.box_windows || sourceDuration === null)return;
      const duration = model.totalFrames(this.editor.state) / model.FPS;
      if (!duration) { this.message.textContent = 'Add video clips first.'; return; }
      clip.start = 0; clip.duration = Math.min(duration, clip.source_duration - clip.source_start);
      this.editor.commit();
    });
    fit.disabled=!!clip.box_windows || sourceDuration === null;fit.title=clip.box_windows?'Unlock audio from boxes before fitting the recording.':'';
    if (sourceDuration === null && file && !reference?.replaced && this.editor.host.audioInfo)
      row.append(button('Read source duration', () => this.recoverSourceDuration(clip, file)));
    row.append(choose,fit, button('Remove audio', () => {
      this.editor.state.audio_clips = this.clips.filter(c => c !== clip);
      if (clip.file) this.editor.state.disabled_refs = [...new Set([...this.editor.state.disabled_refs ?? [], clip.slot])];
      this.selected = this.clips[0]?.slot;
      this.editor.commit();
      if (this.selected) this.selectAudio(this.selected); else this.editor.inspectClip();
    }));
    if (clip.file) {
      const field = node('label', 'h3ct-field', 'In the full video'), input = node('input');
      input.type = 'checkbox'; input.checked = clip.in_full_video === true;
      input.setAttribute('aria-label', 'In the full video');
      field.title = 'Play this clip in the full video instead of H3’s audio';
      input.addEventListener('change', () => {
        if (input.checked) clip.in_full_video = true; else delete clip.in_full_video;
        this.editor.commit();
      });
      field.append(input); row.append(field);
      const lock = node('label', 'h3ct-field', 'Locked to the sequence clock'), locked = node('input');
      locked.type = 'checkbox'; locked.checked = clip.locked === true;
      locked.setAttribute('aria-label', 'Locked to the sequence clock');
      lock.title = 'Keep this recording at its place in the full video: no bridge may add time across a cut inside '
        + 'it, so its dialogue stays in sync';
      locked.addEventListener('change', () => {
        if (locked.checked) clip.locked = true; else delete clip.locked;
        this.editor.commit();
      });
      lock.append(locked); row.append(lock);
    } else row.append(node('span', 'h3ct-hint', 'Upload this audio’s file to play it in the full video.'));
    this.settings.append(row);
    const bound=node('label','h3ct-field','Lock audio to boxes'),toggle=node('input');
    toggle.type='checkbox';toggle.checked=!!clip.box_windows;toggle.setAttribute('aria-label','Lock audio to boxes');
    const eligibility=clip.box_windows?{ok:true,conflicts:[]}:lockEligibility(this.editor.state,clip);
    toggle.disabled=this.boxLockBusy || !eligibility.ok;
    bound.title=eligibility.conflicts.join(' ') || 'Keep each box’s current source audio through length, order and insertion edits.';
    toggle.addEventListener('change',async()=>{await this.setBoxLock(toggle.checked);this.renderSettings();});
    bound.append(toggle);this.settings.append(bound);
    if(!eligibility.ok)this.settings.append(node('div','h3ct-hint',eligibility.conflicts.join(' ')));
    const beats = node('div', 'h3ct-row');
    beats.append(this.beatButton, this.snapField, this.beatMessage);
    this.settings.append(beats);
    const timing = node('div', 'h3ct-row');
    for (const [key, label] of [['start', 'Video start (s)'], ['source_start', 'Source in (s)'], ['duration', 'Length (s)']]) {
      const field = node('label', 'h3ct-field', label);
      const input = node('input', 'h3ct-number'); input.type = 'number'; input.min = key === 'duration' ? .001 : 0; input.step = '0.001';
      input.value = Number(clip[key].toFixed(6)); input.setAttribute('aria-label', label);
      input.disabled=!!clip.box_windows || (key !== 'start' && sourceDuration === null);
      input.addEventListener('change', () => {
        if(clip.box_windows || (key !== 'start' && sourceDuration === null))return;
        const value = Number(input.value);
        if (!Number.isFinite(value) || value < 0 || (key === 'duration' && value === 0)) { input.value = clip[key]; return; }
        if (key === 'source_start') { clip.source_start = Math.min(value, Math.max(0, clip.source_duration - clip.duration)); }
        else if (key === 'duration') clip.duration = Math.min(value, clip.source_duration - clip.source_start);
        else clip.start = value;
        this.editor.commit();
      });
      field.append(input); timing.append(field);
    }
    const layer = node('select', 'h3ct-select'); layer.setAttribute('aria-label', 'Audio description layer');
    for (const [value, label] of [['music', 'Music'], ['soundscape', 'Overall soundscape'], ['shot', 'Shot audio / voice']]) {
      const option = node('option', null, label); option.value = value; layer.append(option);
    }
    layer.value = clip.layer ?? 'music'; layer.addEventListener('change', () => { clip.layer = layer.value; this.editor.commit(); });
    timing.append(layer); this.settings.append(timing);
    const description = node('textarea', 'h3ct-text'); description.rows = 2;
    description.setAttribute('aria-label', `Audio description for @${clip.slot}`);
    description.placeholder = `Describe @${clip.slot} for H3 Story: instruments, mood, rhythm, ambience or voice. Story Text descriptions can override this.`;
    description.value = clip.description ?? '';
    description.addEventListener('input', () => { clip.description = description.value; this.editor.typed(); });
    this.settings.append(description);
    this.renderPlayer(file, clip);
    const video = model.totalFrames(this.editor.state) / model.FPS;
    this.settings.append(node('div', 'h3ct-hint', (reference?.replaced ? 'Replaced source · current clip timing preserved. ' : (sourceDuration === null ? 'Source duration unavailable; source trimming is disabled until the audio file can be read. ' : `${sourceDuration.toFixed(3)} s source · original playback speed. `))
      + (clip.box_windows?'Audio ranges follow their boxes. Unlock before moving, trimming or replacing this recording. ':'Shift-drag the clip to change its source window. ')
      + (clip.start > 0 || clip.start + clip.duration < video ? 'Uncovered time uses silence in this reference.' : '')));
  }

  renderPlayer(file, clip) {
    let player = this.settings.querySelector('audio');
    if (!file) { player?.pause(); player?.remove(); return; }
    if (!player) {
      player = node('audio'); player.controls = true; player.preload = 'none';
      player.addEventListener('play', () => {
        const window=player.audioWindow;
        if(!window){player.pause();return;}
        if (player.currentTime < window.source_start || player.currentTime >= window.source_start + window.duration) player.currentTime = window.source_start;
      });
      player.addEventListener('timeupdate', () => { const window=player.audioWindow;if(!window || player.currentTime >= window.source_start + window.duration)player.pause(); });
      this.settings.append(player);
    }
    const key = JSON.stringify(file);
    const windows=resolveWindows(clip,model.audioBoxSpans(this.editor.state)),id=this.auditionBox??this.editor.state.boxes[this.editor.selected]?.id;
    const window=clip.box_windows?(id?windows.find(w=>w.box===id):windows[0]):clip;
    if(JSON.stringify(player.audioWindow)!==JSON.stringify(window))player.pause();
    player.audioWindow=window;player.hidden=!window;
    if (player.dataset.source !== key) {
      player.pause(); player.src = this.editor.host.viewUrl(file); player.dataset.source = key;
    }
  }
}
