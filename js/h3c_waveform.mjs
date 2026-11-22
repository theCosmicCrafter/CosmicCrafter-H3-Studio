// Waveforms and beats of Timeline audio. Each file is decoded in the browser once per session, at a low rate that is
// plenty for drawing and for finding beats; the analysis is kept and the samples are let go.
export const DECODE_RATE = 11025;
export const PEAKS_PER_SECOND = 100;
const ONSETS_PER_SECOND = 100;

const cache = new Map();

// {duration, peaks (Float32Array, PEAKS_PER_SECOND), onsets (Float32Array, ONSETS_PER_SECOND)} of the audio at `url`.
export function loadAudio(url, fetcher = (address) => fetch(address)) {
  let found = cache.get(url);
  if (!found) {
    found = decode(url, fetcher).catch((error) => {
      cache.delete(url);
      throw error;
    });
    cache.set(url, found);
  }
  return found;
}

// The analysis of `url` if it is decoded already, else null.
export function loaded(url) {
  return cache.get(url)?.ready ?? null;
}

async function decode(url, fetcher) {
  const response = await fetcher(url);
  if (!response.ok) throw new Error(`Could not read the audio (HTTP ${response.status}).`);
  const bytes = await response.arrayBuffer();
  const Context = globalThis.OfflineAudioContext ?? globalThis.webkitOfflineAudioContext;
  if (!Context) throw new Error('This browser cannot decode audio.');
  const buffer = await new Context(1, 1, DECODE_RATE).decodeAudioData(bytes);
  const channels = Array.from({length: buffer.numberOfChannels}, (_, i) => buffer.getChannelData(i));
  const mono = new Float32Array(buffer.length);
  for (const channel of channels) for (let i = 0; i < mono.length; i++) mono[i] += channel[i] / channels.length;
  const result = analyse(mono, buffer.sampleRate);
  cache.get(url).ready = result;
  return result;
}

// Peaks and an onset envelope of mono `samples` at `rate`. The onset envelope sums how much the energy rises in a low
// band (kick drums, bass) and a high band (snares, hats) and overall, on a log scale, less its local average.
export function analyse(samples, rate) {
  const duration = samples.length / rate;
  const peaks = new Float32Array(Math.max(1, Math.ceil(duration * PEAKS_PER_SECOND)));
  for (let i = 0; i < samples.length; i++) {
    const bin = Math.floor(i / rate * PEAKS_PER_SECOND), value = Math.abs(samples[i]);
    if (value > peaks[bin]) peaks[bin] = value;
  }
  const hop = rate / ONSETS_PER_SECOND, count = Math.max(1, Math.floor(samples.length / hop));
  const lowPass = Math.exp(-2 * Math.PI * 150 / rate), highPass = Math.exp(-2 * Math.PI * 2000 / rate);
  const energy = [new Float32Array(count), new Float32Array(count), new Float32Array(count)];
  let low = 0, smooth = 0;
  for (let i = 0; i < Math.min(samples.length, count * hop); i++) {
    const x = samples[i];
    low = low * lowPass + x * (1 - lowPass);
    smooth = smooth * highPass + x * (1 - highPass);
    const high = x - smooth, frame = Math.floor(i / hop);
    energy[0][frame] += low * low;
    energy[1][frame] += high * high;
    energy[2][frame] += x * x;
  }
  const raw = new Float32Array(count);
  for (const band of energy) {
    let previous = Math.log1p(1000 * band[0] / hop);
    for (let i = 1; i < count; i++) {
      const value = Math.log1p(1000 * band[i] / hop);
      raw[i] += Math.max(0, value - previous);
      previous = value;
    }
  }
  const onsets = new Float32Array(count), window = Math.round(ONSETS_PER_SECOND / 4), prefix = new Float64Array(count + 1);
  for (let i = 0; i < count; i++) prefix[i + 1] = prefix[i] + raw[i];
  for (let i = 0; i < count; i++) {
    const lo = Math.max(0, i - window), hi = Math.min(count, i + window + 1);
    onsets[i] = Math.max(0, raw[i] - (prefix[hi] - prefix[lo]) / (hi - lo));
  }
  return {duration, peaks, onsets};
}

// The beat period in onset frames: the lag, between 200 and 60 beats a minute, at which the onsets repeat best,
// leaning towards 120 beats a minute.
export function beatPeriod(onsets) {
  const shortest = Math.round(ONSETS_PER_SECOND * 60 / 200), longest = Math.round(ONSETS_PER_SECOND * 60 / 60);
  let best = Math.round(ONSETS_PER_SECOND / 2), bestScore = -Infinity;
  for (let lag = shortest; lag <= longest; lag++) {
    let sum = 0;
    for (let i = lag; i < onsets.length; i++) sum += onsets[i] * onsets[i - lag];
    const weight = Math.exp(-0.5 * (Math.log2(lag / (ONSETS_PER_SECOND / 2)) / 0.9) ** 2);
    const score = weight * sum / (onsets.length - lag || 1);
    if (score > bestScore) [best, bestScore] = [lag, score];
  }
  return best;
}

// Beat times in seconds of the audio, by dynamic programming over the onsets (Ellis, 2007): each beat is an onset
// that follows the beat before it by about one period. Kept with the analysis once found.
export function beatTimes(analysis) {
  if (analysis.beats) return analysis.beats;
  const onsets = analysis.onsets, count = onsets.length;
  let mean = 0, square = 0;
  for (const value of onsets) { mean += value / count; square += value * value / count; }
  const deviation = Math.sqrt(Math.max(1e-12, square - mean * mean));
  const period = beatPeriod(onsets), tightness = 100;
  const score = new Float32Array(count), back = new Int32Array(count).fill(-1);
  for (let t = 0; t < count; t++) {
    const strength = onsets[t] / deviation;
    let best = 0, from = -1;
    for (let p = t - 2 * period; p <= t - Math.round(period / 2); p++) {
      if (p < 0) continue;
      const value = score[p] - tightness * Math.log((t - p) / period) ** 2;
      if (from < 0 || value > best) [best, from] = [value, p];
    }
    score[t] = strength + Math.max(0, best);
    back[t] = best > 0 ? from : -1;
  }
  let end = Math.max(0, count - 2 * period);
  for (let t = end; t < count; t++) if (score[t] > score[end]) end = t;
  const beats = [];
  for (let t = end; t >= 0; t = back[t]) beats.push((t + 0.5) / ONSETS_PER_SECOND);
  analysis.beats = beats.reverse();
  analysis.tempo = 60 * ONSETS_PER_SECOND / period;
  return analysis.beats;
}

// Draws `peaks` from `from` to `to` seconds of the source across `canvas`, with `beats` (seconds) as ticks below.
export function drawWave(canvas, analysis, from, to, beats = []) {
  const context = canvas.getContext?.('2d');
  if (!context) return;
  const {width, height} = canvas, peaks = analysis.peaks;
  context.clearRect(0, 0, width, height);
  context.fillStyle = '#80d3c2';
  let loudest = 0.001;
  const first = Math.max(0, Math.floor(from * PEAKS_PER_SECOND)), last = Math.min(peaks.length, Math.ceil(to * PEAKS_PER_SECOND));
  for (let i = first; i < last; i++) loudest = Math.max(loudest, peaks[i]);
  const perPixel = (to - from) / width;
  for (let x = 0; x < width; x++) {
    const start = Math.floor((from + x * perPixel) * PEAKS_PER_SECOND);
    const end = Math.max(start + 1, Math.floor((from + (x + 1) * perPixel) * PEAKS_PER_SECOND));
    let peak = 0;
    for (let i = Math.max(0, start); i < Math.min(peaks.length, end); i++) peak = Math.max(peak, peaks[i]);
    const bar = Math.max(1, height * 0.9 * peak / loudest);
    context.fillRect(x, (height - bar) / 2, 1, bar);
  }
  if (!beats.length) return;
  context.fillStyle = '#f2c96d';
  const tick = Math.max(3, Math.round(height / 6));
  for (const beat of beats) {
    if (beat < from || beat > to) continue;
    context.fillRect(Math.round((beat - from) / perPixel), height - tick, Math.max(1, Math.round(width / 2000)), tick);
  }
}
