import test from 'node:test';
import assert from 'node:assert/strict';
import {buildStillPrompt} from '../../../js/h3c_shot_preview.mjs';

const options = {adapter:'pixels',referenceLabel:'<Picture {index}>'};
const video = 'subject_definitions:\n<Subject 1> is a tall courier in a crimson coat, as in @image20, with the face of @image21.\n\nsummary: A courier walks.\n\nretention_analysis:\n<Subject 1>: fully_preserved\n\ndetailed_description:\nAn angular painted animation frame with warm directional sunlight.\n[Shot 1] The courier starts on the left and walks to the right, reaching the doorway by the end.\n\noverall_soundscape: Footsteps.\n\nnon_diegetic_music: A song.';

test('an imported P-H3 video sequence needs preparation or manual still text instead of silently becoming a still', () => {
  const state={boxes:[{id:'b1',prompt:video}]};
  assert.equal(buildStillPrompt(state,0,{kind:'first'},options),'');
  assert.equal(buildStillPrompt(state,0,{kind:'last'},options),'');
  state.still_prompt_preparation={prompts:[{members:[{box:'b1',target:{kind:'first'}}],prompt:'A painted frame: the courier stands at the left.'}]};
  assert.equal(buildStillPrompt(state,0,{kind:'first'},options),'A painted frame: the courier stands at the left.');
});

test('authored snapshots keep subject design, style and reference meaning while excluding the video action', () => {
  const withAudio=video.replace('\n\nsummary:', '\n@audio1 is a song excerpt.\n\nsummary:');
  const state={boxes:[{id:'b1',prompt:withAudio,source:{reply:{shots:[{number:1,opening_state:'The courier stands at the left.',ending_state:'The courier stands beside the doorway.'}]}}}]};
  for (const [kind,expected] of [['first','stands at the left'],['last','stands beside the doorway']]) {
    const text=buildStillPrompt(state,0,{kind},{...options,sourcePrompt:withAudio});
    assert.match(text,new RegExp(expected));
    assert.match(text,/tall courier in a crimson coat/);
    assert.match(text,/@image20/);
    assert.match(text,/angular painted animation/);
    assert.doesNotMatch(text,/walks to the right|reaching the doorway|Footsteps|song excerpt/);
  }
});

test('other pixel generators retain their existing fallback', () => {
  assert.match(buildStillPrompt({boxes:[{id:'b1',prompt:video}]},0,{kind:'first'},{adapter:'pixels'}),/walks to the right/);
});

test('a directly authored unstructured still keeps its text without a Story snapshot', () => {
  assert.match(buildStillPrompt({boxes:[{id:'b1',prompt:'An ink drawing of a cup in window light.'}]},0,{kind:'first'},options),/ink drawing of a cup/);
});
