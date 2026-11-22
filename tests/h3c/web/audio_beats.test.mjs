import test from 'node:test';
import assert from 'node:assert/strict';
import {installDom} from './fake_dom.mjs';
import {AudioLanes} from '../../../js/h3c_audio_lanes.mjs';

installDom();
const createElement = document.createElement;
document.createElement = tag => {
  const element = createElement(tag);
  if (tag === 'audio') element.pause = () => {};
  return element;
};

function audioLanes() {
  const clips = ['audio1', 'audio2'].map((slot, index) => ({slot, title: slot, file: {filename: `${slot}.wav`},
    start: index * 4, source_start: 0, duration: 4, source_duration: 4}));
  const editor = {state: {boxes: [], audio_clips: clips}, host: {connected: () => ({audios: []}),
    viewUrl: file => `/beats/${file.filename}`}};
  const lanes = new AudioLanes(editor);
  lanes.settings.querySelector = selector => lanes.settings.children.find(child => child.tagName === selector.toUpperCase());
  lanes.renderSettings();
  return lanes;
}

test('beat controls belong to the selected audio inspector and analyse only its file', async () => {
  const lanes = audioLanes(), requested = [];
  assert.equal(lanes.header.contains(lanes.beatButton), false);
  assert.equal(lanes.settings.contains(lanes.beatButton), true);
  lanes.selected = 'audio2';
  lanes.renderSettings();
  assert.match(lanes.beatButton.textContent, /@audio2/);
  const originalFetch = globalThis.fetch, originalContext = globalThis.OfflineAudioContext;
  globalThis.fetch = async url => { requested.push(url); return {ok: true, arrayBuffer: async () => new ArrayBuffer(0)}; };
  globalThis.OfflineAudioContext = class {
    async decodeAudioData() {
      const samples = new Float32Array(44100);
      for (let i = 0; i < samples.length; i += 5512) samples.fill(1, i, i + 60);
      return {numberOfChannels: 1, length: samples.length, sampleRate: 11025, getChannelData: () => samples};
    }
  };
  try {
    await lanes.detectBeats();
    assert.deepEqual(requested, ['/beats/audio2.wav']);
    assert.equal(lanes.beats.has('/beats/audio1.wav'), false);
    assert.ok(lanes.beats.get('/beats/audio2.wav').length > 0);
    assert.match(lanes.beatMessage.textContent, /@audio2.*beats/);
    lanes.selected = 'audio1';
    lanes.renderSettings();
    assert.doesNotMatch(lanes.beatMessage.textContent, /@audio2/);
  } finally {
    globalThis.fetch = originalFetch;
    globalThis.OfflineAudioContext = originalContext;
  }
});
