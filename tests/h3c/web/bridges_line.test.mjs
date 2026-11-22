import test from 'node:test';
import assert from 'node:assert/strict';
import {allowedRanges, bridgeLine, candidateLine, protectionLine, regionText, replacementLine} from '../../../js/h3c_bridges.mjs';

const item = (extra = {}) => ({box: 'b', mode: 'replace', status: 'review', reviewed: false, selection: 'none',
  plays: false, candidates: [], protected: [], ...extra});

test('insertion lines keep their wording', () => {
  assert.deepEqual(bridgeLine({box: 'b', mode: 'insert', status: 'next'}), {text: 'Plays as a cut until it renders.', problem: false});
  assert.deepEqual(bridgeLine({box: 'b', mode: 'insert', status: 'done', video: {frames: 29}}),
    {text: 'Rendered, 29 frames.', problem: false});
  assert.deepEqual(bridgeLine(undefined, 'Box 1 drops 7 frames.'), {text: 'Box 1 drops 7 frames.', problem: true});
});

test('replacement lines say what the full video plays', () => {
  assert.deepEqual(replacementLine(undefined), {text: "Waiting for the Timeline's status.", problem: false});
  assert.deepEqual(replacementLine(item({status: 'problem', note: 'mara speaks on screen from 4.58 s to 5.00 s'})),
    {text: 'Mara speaks on screen from 4.58 s to 5.00 s. The full video plays the original cut.', problem: true});
  assert.deepEqual(replacementLine(item({status: 'waiting', note: 'render box 2 first'})),
    {text: 'Render box 2 first. The full video plays the original cut.', problem: false});
  assert.equal(replacementLine(item({note: 'confirm the region before rendering a candidate'})).text,
    'Confirm the region before rendering a candidate. The full video plays the original cut.');
  assert.equal(replacementLine(item({status: 'next', reviewed: true})).text,
    'Region confirmed: render a candidate. The full video plays the original cut.');
  assert.equal(replacementLine(item({status: 'done', reviewed: true})).text,
    'Review the candidates, then select one or keep the original cut.');
  assert.equal(replacementLine(item({status: 'done', reviewed: true, selection: 'current', plays: true})).text,
    'The selected candidate plays in the full video in place of the original cut.');
  assert.equal(replacementLine(item({status: 'pending', reviewed: true, selection: 'current', plays: true})).text,
    'The selected candidate plays in the full video; its prompt or seed changed since, so render a new candidate to compare.');
  assert.deepEqual(replacementLine(item({status: 'review', selection: 'stale', note: 'confirm the region again'})),
    {text: 'Confirm the region again. The selected candidate is stale, so the full video plays the original cut.', problem: true});
  assert.equal(replacementLine(item({status: 'done', reviewed: true, selection: 'missing'})).text,
    "The selected candidate's file is missing, so the full video plays the original cut.");
  assert.equal(replacementLine(item({status: 'next'}), 'The bridge has no prompt.').text, 'The bridge has no prompt.');
});

test('the region names the frames each box gives up and keeps the duration', () => {
  const region = {join: 107, start: 93, end: 122, left: 14, right: 15, frames: 29, before: ['a', 93, 107], after: ['b', 0, 15]};
  assert.equal(regionText(region, 1),
    'Replaces box 1 frames 93–106 and box 2 frames 0–14: 29 frames (1.21 s) from 3.88 s to 5.08 s. '
    + 'The video keeps its length and every recording stays in place.');
  assert.equal(regionText({...region, left: 0, start: 107, before: ['a', 107, 107]}, 1),
    'Replaces box 2 frames 0–14: 29 frames (1.21 s) from 4.46 s to 5.08 s. '
    + 'The video keeps its length and every recording stays in place.');
});

test('allowed coverage reads as ranges', () => {
  const options = [[12, [0, 1, 2, 5, 6, 12]], [29, []], [46, [3]]];
  assert.equal(allowedRanges(options, 12), '0–2, 5–6, 12');
  assert.equal(allowedRanges(options, 29), '');
  assert.equal(allowedRanges(options, 46), '3');
  assert.equal(allowedRanges(undefined, 12), '');
});

test('protections say what keeps footage', () => {
  const speech = {kind: 'on_screen', start: 110, end: 120, id: 'c1', speaker: 'Mara', text: 'Hello there.', checked: true};
  assert.equal(protectionLine(speech), 'Mara speaks on screen 4.58–5.00 s: “Hello there.”');
  assert.equal(protectionLine({...speech, checked: false}), 'Mara speaks on screen 4.58–5.00 s: “Hello there.” · not checked');
  assert.equal(protectionLine({...speech, kind: 'voiceover'}),
    'Mara speaks off screen 4.58–5.00 s: “Hello there.” · may continue over the replacement');
  assert.equal(protectionLine({...speech, kind: 'unknown'}), 'Mara speaks (portrayal unknown) 4.58–5.00 s: “Hello there.”');
  assert.equal(protectionLine({kind: 'changed', slot: 'audio1', id: 'c1', start: 0, end: 720}),
    '@audio1 has a different file than cue c1 was written for');
  assert.equal(protectionLine({kind: 'observed', start: 147, end: 157, label: 'door slam', box: 'b', current: false}, 2),
    'Protected footage: door slam 6.13–6.54 s · marked on an earlier take of box 2');
});

test('candidate rows', () => {
  const candidate = {candidate: 'abc', seed: 7, state: 'current', recipe: true, frames: 29, created: '2026-11-03T11:00:00'};
  assert.equal(candidateLine(candidate, 1, false), 'Candidate 1 · seed 7 · 29 frames');
  assert.equal(candidateLine(candidate, 1, true), 'Candidate 1 · seed 7 · 29 frames · selected');
  assert.equal(candidateLine({...candidate, recipe: false}, 2, false), 'Candidate 2 · seed 7 · 29 frames · earlier prompt or seed');
  assert.equal(candidateLine({...candidate, state: 'stale'}, 3, true), 'Candidate 3 · seed 7 · 29 frames · selected · stale: its region, takes or settings changed');
  assert.equal(candidateLine({...candidate, state: 'missing'}, 4, false), 'Candidate 4 · seed 7 · 29 frames · file missing');
});
