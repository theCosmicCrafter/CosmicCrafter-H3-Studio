import test from 'node:test';
import assert from 'node:assert/strict';
import {analyse, beatTimes, PEAKS_PER_SECOND} from '../../../js/h3c_waveform.mjs';

const RATE = 11025;

// `seconds` of quiet noise with a short decaying thump every 60/bpm seconds from `offset`.
function clicks(bpm, seconds, offset) {
  const samples = new Float32Array(RATE * seconds);
  let seed = 7;
  const noise = () => ((seed = (seed * 16807) % 2147483647) / 2147483647 - 0.5) * 0.02;
  for (let i = 0; i < samples.length; i++) samples[i] = noise();
  for (let beat = offset; beat < seconds; beat += 60 / bpm) {
    const start = Math.round(beat * RATE);
    for (let i = 0; i < RATE * 0.05 && start + i < samples.length; i++) {
      samples[start + i] += Math.sin(2 * Math.PI * 80 * i / RATE) * Math.exp(-i / (RATE * 0.01)) * 0.8;
    }
  }
  return samples;
}

test('peaks follow the loudness at PEAKS_PER_SECOND', () => {
  const samples = new Float32Array(RATE * 2);
  samples.fill(0.25, RATE, RATE * 2);
  const {duration, peaks} = analyse(samples, RATE);
  assert.equal(duration, 2);
  assert.equal(peaks.length, 2 * PEAKS_PER_SECOND);
  assert.equal(peaks[10], 0);
  assert.equal(peaks[150], 0.25);
});

for (const [bpm, offset] of [[120, 0.13], [90, 0.4]]) {
  test(`beats of a ${bpm} BPM click track land on the clicks`, () => {
    const analysis = analyse(clicks(bpm, 20, offset), RATE);
    const beats = beatTimes(analysis);
    assert.ok(Math.abs(analysis.tempo - bpm) < 3, `tempo ${analysis.tempo}`);
    const period = 60 / bpm;
    const inner = beats.filter((beat) => beat > 1 && beat < 19);
    assert.ok(inner.length >= Math.floor(17 / period), `${inner.length} beats`);
    for (const beat of inner) {
      const phase = ((beat - offset) / period) % 1;
      assert.ok(Math.min(phase, 1 - phase) * period < 0.03, `beat at ${beat}`);
    }
    assert.equal(beatTimes(analysis), beats, 'found once');
  });
}
