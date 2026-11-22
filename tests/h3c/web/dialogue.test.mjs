import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import * as dialogue from '../../../js/h3c_dialogue.mjs';
import * as model from '../../../js/h3c_timeline_model.mjs';

const wav = {type: 'input', filename: 'line.wav', subfolder: ''};
const clip = (extra = {}) => ({slot: 'audio1', file: wav, start: 0, source_start: 0, duration: 30, ...extra});
const cue = (extra = {}) => ({id: 'c1', recording: {slot: 'audio1', file: wav}, start: 1.5, end: 2.25,
  text: 'Hello there.', speaker: 'Mara', portrayal: 'on_screen', ...extra});

test('alignment keys match h3_continuity.dialogue.alignment_key', async () => {
  assert.equal(await dialogue.alignmentKey(cue()), '3c847fc62192e64e1dda27989d3425916e79f3e5');
  const other = cue({recording: {slot: 'audio2', file: {type: 'input', filename: 'voz.wav', subfolder: 'h3'}},
    start: 12, end: 13.5, text: '¿Qué tal? — ok 😀 "quoted" \\ tab\t'});
  assert.equal(await dialogue.alignmentKey(other), '04624ecb00d6b4af2102e8d5246f477fbdf9cf46');
});

test('the plain SHA-1 matches the platform digest at every padding boundary', () => {
  for (const length of [0, 1, 55, 56, 57, 63, 64, 65, 119, 120, 128, 1000]) {
    const bytes = Uint8Array.from({length}, (_, i) => (i * 31 + 7) & 255);
    assert.equal(dialogue.sha1Plain(bytes), createHash('sha1').update(bytes).digest('hex'), `${length} bytes`);
  }
});

test('alignment keys are the same where crypto.subtle is missing (plain http)', async () => {
  const saved = Object.getOwnPropertyDescriptor(globalThis, 'crypto');
  Object.defineProperty(globalThis, 'crypto', {value: {}, configurable: true});
  try {
    assert.equal(await dialogue.alignmentKey(cue()), '3c847fc62192e64e1dda27989d3425916e79f3e5');
    const item = cue();
    await dialogue.setChecked(item, true);
    assert.equal(await dialogue.isChecked(item), true);
  } finally {
    if (saved) Object.defineProperty(globalThis, 'crypto', saved); else delete globalThis.crypto;
  }
});

test('checking a cue writes its alignment key; unchecking removes it', async () => {
  const item = cue();
  await dialogue.setChecked(item, true);
  assert.equal(item.aligned, '3c847fc62192e64e1dda27989d3425916e79f3e5');
  assert.equal(await dialogue.isChecked(item), true);
  item.text = 'Hello.';
  assert.equal(await dialogue.isChecked(item), false);
  await dialogue.setChecked(item, false);
  assert.equal('aligned' in item, false);
});

test('a recording file resolves as reference_replacements.file_for does', () => {
  const fresh = {type: 'input', filename: 'take2.wav', subfolder: ''};
  const other = {type: 'input', filename: 'other.wav', subfolder: 'h3_audio'};
  assert.deepEqual(dialogue.recordingFile({audio_clips: [clip({file: fresh})]}, 'audio1'), fresh);
  assert.deepEqual(dialogue.recordingFile({audio_clips: [clip()], reference_replacements: {audio1: {file: other}}}, 'audio1'),
    other);
  assert.deepEqual(dialogue.recordingFile({audio_clips: [clip(), clip({slot: 'audio2', file: fresh})],
    reference_replacements: {audio1: {source: 'audio2'}}}, 'audio1'), fresh);
  assert.equal(dialogue.recordingFile({audio_clips: [clip()],
    reference_replacements: {audio1: {source: 'audio2'}, audio2: {source: 'audio1'}}}, 'audio1'), null);
  assert.equal(dialogue.recordingFile({audio_clips: []}, 'audio1'), null);
});

test('checking a cue binds it to the file its slot plays now', async () => {
  const fresh = {type: 'input', filename: 'take2.wav', subfolder: ''};
  const item = cue({aligned: 'an older key'});
  await dialogue.setChecked(item, true, {audio_clips: [clip({file: fresh})]});
  assert.deepEqual(item.recording, {slot: 'audio1', file: fresh});
  assert.equal(item.aligned, await dialogue.alignmentKey(cue({recording: {slot: 'audio1', file: fresh}})));
  const gone = cue();
  await dialogue.setChecked(gone, true, {audio_clips: []});
  assert.deepEqual(gone.recording, {slot: 'audio1', file: wav});
});

test('a transcript becomes unchecked cues of unknown portrayal that keep their speakers', () => {
  const data = {segments: [{start: 1.25, end: 2.5, text: ' Hello there. ', speaker: 'SPEAKER_00'},
    {start: 3, end: 3, text: 'empty interval'}, {start: 4, end: 5, text: '   '}, {start: 6, end: 7.5, text: 'Bye.'}]};
  const found = dialogue.cuesFromTranscript(data, clip(), []);
  assert.deepEqual(found.cues, [
    {id: 'c1', recording: {slot: 'audio1', file: wav}, start: 1.25, end: 2.5, text: 'Hello there.',
      speaker: 'SPEAKER_00', portrayal: 'unknown', origin: 'transcript'},
    {id: 'c2', recording: {slot: 'audio1', file: wav}, start: 6, end: 7.5, text: 'Bye.', speaker: '',
      portrayal: 'unknown', origin: 'transcript'}]);
  assert.equal(found.skipped, 2);
  assert.deepEqual(dialogue.cuesFromTranscript([{timestamp: [0, 1], text: 'Hi.'}], clip(), [cue({id: 'c1'})]).cues
    .map((item) => item.id), ['c2']);
});

test('transcript text with H3 control tokens is refused, naming the segment', () => {
  assert.throws(() => dialogue.cuesFromTranscript({segments: [{start: 0, end: 1, text: '<d>Hi</d>'}]}, clip(), []),
    /segment 1 .*<d>/);
  assert.throws(() => dialogue.cuesFromTranscript({words: [{start: 0, end: 1, word: 'Hi'}]}, clip(), []),
    /segments/);
});

test('Story dialogue maps from each box generation clock onto the recording', () => {
  const state = {boxes: [
    {id: 'a', frames: 107, cut: false, source: {frame: {carried: 0}, reply: {shots: [{dialogue: [
      {start_ms: 500, end_ms: 1500, speaker: 'Mara', subject: 'e1', text: 'Hello there.', voiceover: false}]}]}}},
    {id: 'b', frames: 68, cut: false, source: {frame: {carried: 39}, reply: {shots: [{dialogue: [
      {start_ms: 2000, end_ms: 2500, speaker: '', subject: 'e2', text: 'Who is it?', voiceover: true}]}]}}},
    {id: 'c', frames: 107, cut: true}]};
  const found = dialogue.cuesFromStory(state, clip({start: 0.25, source_start: 10, duration: 20}), [], 39);
  const [first, second] = found.cues;
  assert.equal(found.cues.length, 2);
  assert.deepEqual(first, {id: 'c1', recording: {slot: 'audio1', file: wav}, start: 10.25, end: 11.25,
    text: 'Hello there.', speaker: 'Mara', portrayal: 'on_screen', origin: 'story'});
  assert.deepEqual([second.id, second.text, second.speaker, second.portrayal], ['c2', 'Who is it?', 'e2', 'voiceover']);
  assert.ok(Math.abs(second.start - (10 + 107 / 24 - 39 / 24 + 2 - 0.25)) < 1e-9);
  assert.ok(Math.abs(second.end - second.start - 0.5) < 1e-9);
  assert.equal(found.skipped, 0);
});

test('Story lines outside the recording window are skipped and counted', () => {
  const state = {boxes: [{id: 'a', frames: 107, cut: false, source: {frame: {carried: 0}, reply: {shots: [{dialogue: [
    {start_ms: 0, end_ms: 400, speaker: 'Mara', text: 'Early.', voiceover: false},
    {start_ms: 1000, end_ms: 1500, speaker: 'Mara', text: 'Inside.', voiceover: false}]}]}}}]};
  const found = dialogue.cuesFromStory(state, clip({start: 0.5, duration: 10}), [], 39);
  assert.deepEqual(found.cues.map((item) => item.text), ['Inside.']);
  assert.equal(found.skipped, 1);
});

test('cue problems mirror the server validation', () => {
  assert.equal(dialogue.cueProblem(cue()), '');
  assert.match(dialogue.cueProblem(cue({end: 1.5})), /end after/);
  assert.match(dialogue.cueProblem(cue({text: ' '})), /words/);
  assert.match(dialogue.cueProblem(cue({text: 'Hi <d>there</d>'})), /<d>/);
  assert.match(dialogue.cueProblem(cue({portrayal: 'maybe'})), /portrayal/);
});

test('a new cue starts at the recording window and takes a free id', () => {
  const made = dialogue.newCue([cue({id: 'c1'}), cue({id: 'c3'})], clip({source_start: 4}));
  assert.deepEqual(made, {id: 'c2', recording: {slot: 'audio1', file: wav}, start: 4, end: 5, text: '', speaker: '',
    portrayal: 'unknown', origin: 'manual'});
});

test('cue status lines read the server summary', () => {
  assert.equal(dialogue.cueStatusLine(undefined), "Waiting for the Timeline's status.");
  assert.equal(dialogue.cueStatusLine({state: 'bound', placed: true, cut: false, aligned: true, sequence: [4, 4.5]}),
    'Checked · plays 4.00–4.50 s in the video.');
  assert.equal(dialogue.cueStatusLine({state: 'bound', placed: true, cut: true, aligned: false, sequence: [4, 4.5]}),
    'Not checked · plays 4.00–4.50 s in the video · cut by the clip window: extend the clip or edit the words.');
  assert.equal(dialogue.cueStatusLine({state: 'bound', placed: false, aligned: false}),
    'Not checked · outside the clip window, so no box speaks it.');
  assert.match(dialogue.cueStatusLine({state: 'changed', placed: false, aligned: false, slot: 'audio1'}),
    /@audio1 has a different file/);
  assert.match(dialogue.cueStatusLine({state: 'missing', placed: false, aligned: false, slot: 'audio2'}), /@audio2/);
});

const cutState = (cues, second = {}) => ({prompt: '', audio_clips: [clip()], dialogue: {version: 1, cues}, boxes: [
  {id: 'a', frames: 107, prompt: 'One.', cut: false, memory: 'scene'},
  {id: 'b', frames: 107, prompt: 'Two.', cut: true, memory: 'scene', ...second}]});
const whole = [{box: 'a', frame: 0, label: 'the previous shot before this cut', whole: true}];
const before = {box: 'a', frame: 102, label: 'the moment before this cut'};
const views = [{box: 'a', frame: 0, label: 'scene establishing view'}, before];

test('a cut with speech on either side remembers views instead of the whole video, as timeline.memory_sources', () => {
  assert.deepEqual(model.memorySources(cutState([]), 1), whole);
  const after = cutState([cue({start: 5.6, end: 7.9})]);
  assert.deepEqual([model.speaks(after, 0), model.speaks(after, 1)], [false, true]);
  assert.deepEqual(model.memorySources(after, 1), views);
  const earlier = cutState([cue({start: 0.5, end: 2.48})]);
  assert.deepEqual([model.speaks(earlier, 0), model.speaks(earlier, 1)], [true, false]);
  assert.deepEqual(model.memorySources(earlier, 1), views);
  assert.deepEqual(model.memorySources(cutState([], {prompt: 'Mara says: <d>Hello.</d>'}), 1), views);
});

test('voiceover, manual boxes and unbound cues keep the whole video', () => {
  assert.deepEqual(model.memorySources(cutState([cue({start: 5.6, end: 7.9, portrayal: 'voiceover'})]), 1), whole);
  assert.deepEqual(model.memorySources(cutState([cue({start: 5.6, end: 7.9})], {dialogue: 'manual'}), 1), whole);
  const changed = cutState([cue({start: 5.6, end: 7.9})]);
  changed.audio_clips = [clip({file: {type: 'input', filename: 'take2.wav', subfolder: ''}})];
  assert.deepEqual(model.memorySources(changed, 1), whole);
});

test('selected moments at a speaking cut add the moment before it', () => {
  const chosen = {box: 'a', frame: 30, label: 'the envelope'};
  assert.deepEqual(model.memorySources(cutState([cue({start: 5.6, end: 7.9})], {memory: 'selected', memories: [chosen]}), 1),
    [chosen, before]);
  assert.deepEqual(model.memorySources(cutState([cue({start: 5.6, end: 7.9})], {memory: 'selected'}), 1), [before]);
});
