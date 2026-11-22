import {test} from 'node:test';
import assert from 'node:assert/strict';
import {formHarness} from './prompt_form_fixture.mjs';
import {findAll,buttonNamed} from './fake_dom.mjs';
test('opening and redrawing an empty form does not invent prompt content or history',()=>{
  const h=formHarness({prompt:''});h.panel.render();
  assert.equal(h.stored().boxes[0].prompt,'');assert.equal(h.history.entries.length,1);
});
test('new definition rows expose a type selector and source picker',()=>{
  const h=formHarness({prompt:'subject_definitions:\n<Subject 1> is Mara.'});
  buttonNamed(h.panel.root,'Add definition').click();
  const types=findAll(h.panel.root,n=>n.getAttribute?.('aria-label')==='Definition type')[0];
  assert.ok(types);
  assert.deepEqual(types.options.map(o=>o.value).filter(Boolean),['subject','image','video','audio']);
});
test('a Basic description field replaces only the selected definition',()=>{
  const h=formHarness({prompt:'subject_definitions:\n<Subject 1> is Mara.\n\ncustom_section: Keep this.'});
  h.input('<Subject 1> description','Mara in a blue coat.');
  assert.equal(h.stored().boxes[0].prompt,'subject_definitions:\n<Subject 1> is Mara in a blue coat.\n\ncustom_section: Keep this.');
});
test('each duplicate Existing text region edits only its own text',()=>{
  const h=formHarness({prompt:'summary: One.\nsummary: Two.\ndetailed_description:\n[Shot 1] A room.'});
  h.panel.section='existing';h.panel.render();
  const areas=findAll(h.panel.root,n=>n.tagName==='TEXTAREA'&&n.getAttribute('aria-label')==='Existing text');
  assert.deepEqual(areas.map(a=>a.value),['summary: One.','summary: Two.']);
  areas[1].value='summary: Two, edited.';areas[1].fire('input');
  assert.equal(h.stored().boxes[0].prompt,'summary: One.\nsummary: Two, edited.\ndetailed_description:\n[Shot 1] A room.');
});
test('summary task types are a multiple selection that generates the expected prefix',()=>{
  const h=formHarness({prompt:'summary:\nA pause.'});
  const input=findAll(h.panel.root,n=>n.getAttribute?.('aria-label')==='Task types')[0];
  assert.equal(input.multiple,true);
  input.options[0].selected=true;input.options[1].selected=true;input.fire('change');
  assert.equal(h.stored().boxes[0].prompt,'summary:\n[keyframe completion + reference generation] A pause.');
});
test('invalid shot starts stay local and prevent navigation and generation until discarded',async()=>{
  const prompt='integrated_multimodal_description:\n[Shot 1] A room.\n[Shot 2] At 00:02.000, the camera cuts to a doorway.';
  const h=formHarness({prompt});h.editor.state.boxes.push({...h.editor.state.boxes[0],id:'b'});
  h.input('Shot 2 start (seconds)','-1');
  assert.equal(h.stored().boxes[0].prompt,prompt);assert.equal(h.panel.canLeave(),false);
  h.editor.select(1);assert.equal(h.editor.selected,0);
  await h.editor.queueBox(1);assert.equal(h.queued(),0);
  h.panel.render();assert.equal(findAll(h.panel.root,n=>n.getAttribute?.('aria-label')==='Shot 2 start (seconds)')[0].value,'-1');
  h.panel.discardDrafts();assert.equal(h.panel.canLeave(),true);assert.equal(h.stored().boxes[0].prompt,prompt);
});
test('later starts serialize clean seconds while Shot 1 never has a timestamp input',()=>{
  const h=formHarness({prompt:'integrated_multimodal_description:\n[Shot 1] A room.\n[Shot 2] At 00:02.000, the camera cuts to a doorway.'});
  assert.equal(findAll(h.panel.root,n=>n.getAttribute?.('aria-label')==='Shot 1 start (seconds)').length,0);
  h.input('Shot 2 start (seconds)','2.5');
  assert.match(h.stored().boxes[0].prompt,/At 00:02\.500,/);assert.equal(h.panel.hasDrafts(),false);
});
test('a project or history reload explicitly discards an incompatible structural draft',()=>{
  const prompt='integrated_multimodal_description:\n[Shot 1] A room.\n[Shot 2] At 00:02.000, the camera cuts to a doorway.';
  const h=formHarness({prompt});const saved=JSON.stringify(h.stored());
  h.input('Shot 2 start (seconds)','-1');
  h.editor.host.read=()=>saved;h.editor.replacements={close(){}};h.editor.cast={changed(){}};h.editor.render=()=>h.panel.render();
  h.editor.load();
  assert.equal(h.panel.hasDrafts(),false);assert.equal(h.stored().boxes[0].prompt,prompt);
  assert.match(h.panel.root.textContent,/discarded.*history/i);
});
const advancedSwitch=h=>findAll(h.panel.root,n=>n.getAttribute?.('role')==='switch'&&/^Advanced/.test(n.textContent))[0];
const formField=(h,label)=>findAll(h.panel.root,n=>n.getAttribute?.('aria-label')===label)[0];
test('Advanced is on while the clip has advanced details; off removes them after confirming until it is on again',()=>{
  const prompt='integrated_multimodal_description:\n[Shot 1] A room.\nComposition: Wide shot\nLighting: Warm window light\nGaze: Down at the floor';
  const h=formHarness({prompt}),advanced=()=>advancedSwitch(h),field=label=>formField(h,label);
  const legend=advanced().parentNode.parentNode;
  assert.equal(legend.tagName,'LEGEND');assert.equal(h.panel.root.childNodes.find(n=>n.tagName==='LEGEND'),legend);
  assert.equal(advanced().getAttribute('aria-checked'),'true');
  assert.ok(field('Shot 1 Lighting'));assert.ok(field('Shot 1 Gaze'));
  const asked=[];globalThis.confirm=message=>{asked.push(message);return false;};
  advanced().click();
  assert.equal(advanced().getAttribute('aria-checked'),'true');assert.equal(h.stored().boxes[0].prompt,prompt);
  assert.match(asked[0],/Lighting, Gaze/);
  globalThis.confirm=()=>true;
  advanced().click();
  assert.equal(advanced().getAttribute('aria-checked'),'false');
  assert.equal(h.stored().boxes[0].prompt,'integrated_multimodal_description:\n[Shot 1] A room.\nComposition: Wide shot');
  assert.equal(field('Shot 1 Lighting'),undefined);assert.ok(field('Shot 1 Composition'));
  assert.equal(field('Shot 1 add detail').options.some(o=>o.value==='atmosphere'),false);
  advanced().click();
  assert.equal(h.stored().boxes[0].prompt,prompt);assert.ok(field('Shot 1 Lighting'));
  assert.equal(h.history.entries.length,3);
  delete globalThis.confirm;
});
test('Advanced brings removed details back into their shot after other edits, and an empty clip turns it on without changing text',()=>{
  const prompt='integrated_multimodal_description:\n[Shot 1] A room.\nComposition: Wide shot\nLighting: Warm window light';
  const h=formHarness({prompt}),advanced=()=>advancedSwitch(h),field=label=>formField(h,label);
  globalThis.confirm=()=>true;
  advanced().click();h.input('Shot 1 Composition','Close-up');advanced().click();
  assert.equal(h.stored().boxes[0].prompt,'integrated_multimodal_description:\n[Shot 1] A room.\nComposition: Close-up\nLighting: Warm window light');
  delete globalThis.confirm;
  const basic=formHarness({prompt:'integrated_multimodal_description:\n[Shot 1] A room.'});
  assert.equal(advancedSwitch(basic).getAttribute('aria-checked'),'false');
  advancedSwitch(basic).click();
  assert.equal(advancedSwitch(basic).getAttribute('aria-checked'),'true');
  assert.equal(formField(basic,'Shot 1 add detail').options.some(o=>o.value==='atmosphere'),true);
  advancedSwitch(basic).click();
  assert.equal(advancedSwitch(basic).getAttribute('aria-checked'),'false');
  assert.equal(basic.stored().boxes[0].prompt,'integrated_multimodal_description:\n[Shot 1] A room.');assert.equal(basic.history.entries.length,1);
});
test('on a read-only Timeline Advanced only shows or hides details and never changes the prompt',()=>{
  const prompt='integrated_multimodal_description:\n[Shot 1] A room.\nLighting: Warm window light';
  const h=formHarness({prompt});Object.defineProperty(h.editor,'readOnly',{value:['scene-map-1']});h.panel.render();
  assert.equal(advancedSwitch(h).getAttribute('aria-checked'),'true');assert.ok(formField(h,'Shot 1 Lighting'));
  advancedSwitch(h).click();
  assert.equal(advancedSwitch(h).getAttribute('aria-checked'),'false');assert.equal(formField(h,'Shot 1 Lighting'),undefined);
  assert.match(advancedSwitch(h).textContent,/1 hidden/);assert.equal(h.stored().boxes[0].prompt,prompt);
});
test('retention relationship is a choice of H3 markers with a Custom option that keeps imported markers',()=>{
  const h=formHarness({prompt:'subject_definitions:\n<Subject 1> is a woman.\n\nretention_analysis:\n<Subject 1> (appears in [Shot 1]): close_enough - Keeps the coat.\n\ndetailed_description:\n[Shot 1] A room.'});
  h.panel.section='retention_analysis';h.panel.render();
  const field=label=>formField(h,label),prompt=()=>h.stored().boxes[0].prompt;
  assert.equal(field('Relationship').tagName,'SELECT');
  assert.deepEqual(field('Relationship').options.map(o=>o.value).slice(1),['fully_preserved','partially_preserved','attribute_transfer','weak_reference','__custom']);
  assert.equal(field('Relationship').value,'__custom');assert.equal(field('Custom relationship').value,'close_enough');
  h.input('Relationship','partially_preserved');
  assert.match(prompt(),/\): partially_preserved - Keeps the coat\./);assert.equal(field('Custom relationship'),undefined);
  h.input('Relationship','__custom');
  assert.equal(field('Relationship').value,'__custom');assert.equal(field('Custom relationship').value,'');
  h.input('Custom relationship','newly_generated');
  assert.match(prompt(),/\): newly_generated - Keeps the coat\./);
});
test('prompt section tabs are icon and text tabs in the Studio section tab style',()=>{
  const h=formHarness({prompt:'integrated_multimodal_description:\n[Shot 1] A room.'});
  const list=findAll(h.panel.root,n=>n.getAttribute?.('role')==='tablist')[0];
  assert.match(list.className,/h3ct-section-tabs/);
  const tabs=findAll(list,n=>n.getAttribute?.('role')==='tab');
  assert.ok(tabs.length>=6);
  for(const tab of tabs) {
    assert.equal(tab.childNodes[0].tagName.toLowerCase(),'svg');
    assert.equal(tab.childNodes[1].className,'h3ci-caption');assert.ok(tab.childNodes[1].textContent);
  }
});
test('manual dialogue is an explicit choice and never duplicates recording-owned lines',()=>{
  const prompt='integrated_multimodal_description:\n[Shot 1] She waits.';
  const h=formHarness({prompt});
  assert.match(h.panel.root.textContent,/recording cues/i);
  assert.equal(findAll(h.panel.root,n=>n.tagName==='BUTTON'&&n.textContent==='Add dialogue').length,0);
  buttonNamed(h.panel.root,'Use typed dialogue').click();
  assert.equal(h.stored().boxes[0].dialogue,'manual');assert.equal(h.stored().boxes[0].prompt,prompt);
  buttonNamed(h.panel.root,'Add dialogue').click();
  assert.equal(h.stored().boxes[0].prompt,prompt);
});
test('dialogue metadata can be filled one field at a time before spoken text is added',()=>{
  const h=formHarness({prompt:'integrated_multimodal_description:\n[Shot 1] She waits.'});
  buttonNamed(h.panel.root,'Use typed dialogue').click();buttonNamed(h.panel.root,'Add dialogue').click();
  h.input('Shot 1 dialogue 1 speaker IDs','S1');h.input('Shot 1 dialogue 1 language','English');
  h.input('Shot 1 dialogue 1 speaker','<Subject 1>');h.input('Shot 1 dialogue 1 words','Hello.');
  assert.ok(h.stored().boxes[0].prompt.includes('<Subject 1> (S1) says: <d>[English] Hello.</d>'));
  assert.equal(h.panel.hasDrafts(),false);
});
test('an optional camera field chosen from the form writes to its own shot',()=>{
  const h=formHarness({prompt:'integrated_multimodal_description:\n[Shot 1] She waits.'});
  h.input('Shot 1 add detail','camera_movement');h.input('Shot 1 Camera movement','A slow orbit');
  assert.match(h.stored().boxes[0].prompt,/\[Shot 1\] She waits\.\nCamera movement: A slow orbit/);
});
