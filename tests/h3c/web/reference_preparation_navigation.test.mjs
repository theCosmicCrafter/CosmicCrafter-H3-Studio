import test from 'node:test';
import assert from 'node:assert/strict';
import {installDom,findAll} from './fake_dom.mjs';
import {ReferencePreparationPanel} from '../../../js/h3c_reference_preparation.mjs';
installDom();
const row=(key,name,category)=>({key,name,category,role:category==='cast'?'character':'place',status:'missing',input_fingerprint:key+'-v1',included:true,clips:['A'],prompt:name+' visual description',candidates:[],existing_images:[]});
const rows=[row('a','Mara','cast'),row('b','The field','locations')];
async function open(){const editor={state:{boxes:[{id:'A',frames:48,cut:true}],reference_preparation:{version:1,generate:{cast:true,locations:true,props:false},assets:[],requests:[]}},readOnly:[],selected:0,commit(){},inspectClip(){},host:{referenceContext:()=> 'fixture',referenceCatalog:async()=>structuredClone(rows),stillControls:async()=>({adapter:'pixels'}),viewUrl:()=>'/image'}};const panel=new ReferencePreparationPanel(editor);panel.root.open=true;await panel.refresh();return panel;}
test('reference preparation edits one selected asset instead of rendering every form',async()=>{
 const panel=await open();let inputs=findAll(panel.body,n=>n.tagName==='TEXTAREA');assert.equal(inputs.length,1);assert.equal(inputs[0].getAttribute('aria-label'),'Mara image prompt');
 panel.choose('b');inputs=findAll(panel.body,n=>n.tagName==='TEXTAREA');assert.equal(inputs.length,1);assert.equal(inputs[0].getAttribute('aria-label'),'The field image prompt');
 panel.setFilter('cast');assert.equal(panel.selectedKey,'a');assert.equal(panel.editor.state.reference_preparation.generate.locations,true);
});
test('category tabs replace batch checkboxes: each category tab owns its preparation switch',async()=>{
 const panel=await open(),edits=[];panel.editor.commit=()=>edits.push(structuredClone(panel.editor.state.reference_preparation.generate));
 const prepare=()=>findAll(panel.body,n=>n.getAttribute?.('role')==='switch')[0];
 assert.equal(findAll(panel.body,n=>n.classList?.contains('h3cr-batch-options')).length,0);
 assert.equal(prepare(),undefined);
 panel.setFilter('props');assert.equal(prepare().getAttribute('aria-label'),'Prepare objects references');assert.equal(prepare().getAttribute('aria-checked'),'false');
 prepare().fire('click');assert.deepEqual(edits.at(-1),{cast:true,locations:true,props:true});
 panel.setFilter('cast');const generate=findAll(panel.body,n=>n.tagName==='BUTTON'&&n.textContent.startsWith('Generate missing'))[0];
 assert.equal(generate.textContent,'Generate missing characters (1)');
});
test('late catalog replies cannot replace a newer selection or catalog',async()=>{
 const panel=await open();panel.choose('b');const pending=[];panel.host.referenceCatalog=()=>new Promise(resolve=>pending.push(resolve));
 const first=panel.refresh(),second=panel.refresh();pending[1]([{...rows[0]},{...rows[1],name:'Updated field'}]);await second;
 pending[0]([rows[0]]);await first;assert.equal(panel.selectedKey,'b');assert.ok(panel.body.textContent.includes('Updated field'));
});

test('a catalog refresh preserves an unsaved description draft',async()=>{
 const panel=await open(),input=findAll(panel.body,n=>n.tagName==='TEXTAREA')[0];input.value='User description in progress';input.fire('input');await panel.refresh();
 assert.equal(findAll(panel.body,n=>n.tagName==='TEXTAREA')[0].value,'User description in progress');assert.equal(panel.editor.state.reference_preparation.assets.length,0);
});
test('stale candidate approval stays disabled, current candidate sends the selected asset identity',async()=>{
 const panel=await open(),candidate={id:'candidate1',file:{type:'input',filename:'candidate.png'},sha256:'a'.repeat(64),input_fingerprint:'old',request_id:'r',prompt_id:'p',batch_index:0,provenance:{origin:'uploaded'}};
 panel.host.referenceCatalog=async()=>[{...rows[0],candidates:[candidate]}];await panel.refresh();
 let approve=findAll(panel.body,n=>n.tagName==='BUTTON'&&n.textContent==='Use as reference')[0];assert.equal(approve.disabled,true);
 candidate.input_fingerprint='a-v1';await panel.refresh();approve=findAll(panel.body,n=>n.tagName==='BUTTON'&&n.textContent==='Use as reference')[0];assert.equal(approve.disabled,false);
 const sent=[];panel.host.approveReference=async request=>sent.push(request);approve.fire('click');await new Promise(setImmediate);
 assert.deepEqual(sent,[{asset_key:'a',candidate_id:'candidate1',expected_revision:0}]);
});

test('a reference shows the text added to its prompt and edits or switches it off for that reference only',async()=>{
 const parts=[{id:'layout',label:'Character sheet layout',where:'before',text:'A 16:9 sheet.',default:'A 16:9 sheet.',enabled:true,edited:false},
  {id:'style',label:'Visual style',where:'after',text:'Visual style: Painted.',default:'Visual style: Painted.',enabled:true,edited:false}];
 const panel=await open();
 // The server answers with the saved edits applied, as catalog() does.
 panel.host.referenceCatalog=async()=>{
  const own=panel.editor.state.reference_preparation.assets.find(a=>a.key==='a')?.part_overrides??{};
  return [{...rows[0],part_overrides:own,prompt_parts:parts.map(p=>({...p,text:own[p.id]?.text??p.text,enabled:own[p.id]?.enabled!==false,edited:own[p.id]?.text!=null}))},rows[1]];
 };await panel.refresh();
 const box=()=>findAll(panel.body,n=>n.classList?.contains('h3cr-parts'))[0];
 assert.ok(box().textContent.includes('Also sent with this prompt'));
 const fields=()=>findAll(box(),n=>n.tagName==='TEXTAREA');
 assert.deepEqual(fields().map(n=>n.value),['A 16:9 sheet.','Visual style: Painted.']);
 const saved=()=>panel.editor.state.reference_preparation.assets.find(a=>a.key==='a');
 fields()[1].value='Visual style: Flat.';fields()[1].fire('change');await new Promise(setImmediate);
 assert.deepEqual(saved().part_overrides,{style:{text:'Visual style: Flat.'}});
 assert.equal(saved().prompt_parts,undefined);
 const off=()=>findAll(box(),n=>n.getAttribute?.('role')==='switch'&&n.getAttribute('aria-label')==='Send visual style with Mara')[0];
 await new Promise(setImmediate);off().fire('click');await new Promise(setImmediate);
 assert.deepEqual(saved().part_overrides,{style:{text:'Visual style: Flat.',enabled:false}});
 // Switched off, the part shows only its switch: no text to edit, and the layout part is untouched.
 assert.equal(fields().length,1);assert.deepEqual(fields().map(n=>n.value),['A 16:9 sheet.']);
 assert.equal(off().getAttribute('aria-checked'),'false');
 off().fire('click');await new Promise(setImmediate);
 assert.deepEqual(saved().part_overrides,{style:{text:'Visual style: Flat.'}});
 assert.deepEqual(fields().map(n=>n.value),['A 16:9 sheet.','Visual style: Flat.']);
 fields()[1].value='Visual style: Painted.';fields()[1].fire('change');await new Promise(setImmediate);
 assert.equal(saved().part_overrides,undefined);
});

test('a character sheet layout is picked from pictures, with a layout of your own as the third',async()=>{
 const layout=(choice,text)=>({id:'layout',label:'Character sheet layout',where:'before',text,default:text,enabled:true,edited:false,choice,choices:['human','creature','custom']});
 const panel=await open();
 panel.host.referenceCatalog=async()=>{
  const own=panel.editor.state.reference_preparation.assets.find(a=>a.key==='a')?.part_overrides??{};
  const choice=own.layout?.choice??'human';
  return [{...rows[0],part_overrides:own,prompt_parts:[layout(choice,choice==='custom'?'':'Sheet for {description}')]},rows[1]];
 };await panel.refresh();
 const picks=()=>findAll(panel.body,n=>n.getAttribute?.('role')==='radio');
 assert.deepEqual(picks().map(n=>n.dataset.layout),['human','creature','custom']);
 assert.deepEqual(picks().map(n=>n.getAttribute('aria-checked')),['true','false','false']);
 assert.ok(findAll(picks()[0],n=>n.tagName==='IMG')[0].src.startsWith('data:image/svg+xml'));
 for(const word of ['Person template','Creature template'])assert.ok(!panel.body.textContent.includes(word));
 const saved=()=>panel.editor.state.reference_preparation.assets.find(a=>a.key==='a');
 picks()[1].fire('click');await new Promise(setImmediate);
 assert.deepEqual(saved().part_overrides,{layout:{choice:'creature'}});
 assert.deepEqual(picks().map(n=>n.getAttribute('aria-checked')),['false','true','false']);
 picks()[2].fire('click');await new Promise(setImmediate);
 assert.deepEqual(saved().part_overrides,{layout:{choice:'custom'}});
 const own=findAll(panel.body,n=>n.tagName==='TEXTAREA'&&n.getAttribute('aria-label')==='Character sheet layout for Mara')[0];
 assert.ok(own.placeholder.includes('{description}'));
 own.value='A turnaround on ivory.';own.fire('change');await new Promise(setImmediate);
 assert.deepEqual(saved().part_overrides,{layout:{choice:'custom',text:'A turnaround on ivory.'}});
 picks()[0].fire('click');await new Promise(setImmediate);
 assert.equal(saved().part_overrides,undefined);
});

test('switching the sheet layout off hides its pictures and text',async()=>{
 const layout=enabled=>({id:'layout',label:'Character sheet layout',where:'before',text:'Sheet for {description}',default:'Sheet for {description}',enabled,edited:false,choice:'human',choices:['human','creature','custom']});
 const panel=await open();let enabled=true;
 panel.host.referenceCatalog=async()=>[{...rows[0],part_overrides:enabled?{}:{layout:{enabled:false}},prompt_parts:[layout(enabled)]},rows[1]];await panel.refresh();
 const radios=()=>findAll(panel.body,n=>n.getAttribute?.('role')==='radio').length,fields=()=>findAll(panel.body,n=>n.tagName==='TEXTAREA'&&n.getAttribute('aria-label')==='Character sheet layout for Mara').length;
 assert.deepEqual([radios(),fields()],[3,1]);
 enabled=false;findAll(panel.body,n=>n.getAttribute?.('role')==='switch'&&n.getAttribute('aria-label')==='Send character sheet layout with Mara')[0].fire('click');await new Promise(setImmediate);
 assert.deepEqual([radios(),fields()],[0,0]);
});

test('a location picks the grid of views or a layout of your own, and is drawn 16:9 unless sized',async()=>{
 const panel=await open();panel.choose('b');
 panel.host.referenceCatalog=async()=>{
  const own=panel.editor.state.reference_preparation.assets.find(a=>a.key==='b')?.part_overrides??{};
  const choice=own.layout?.choice??'grid';
  return [rows[0],{...rows[1],role:'location',part_overrides:own,prompt_parts:[{id:'layout',label:'Location sheet layout',where:'before',text:choice==='custom'?'':'Grid of {description}',default:choice==='custom'?'':'Grid of {description}',enabled:true,edited:false,choice,choices:['grid','custom']}]}];
 };await panel.refresh();
 const picks=()=>findAll(panel.body,n=>n.getAttribute?.('role')==='radio');
 assert.deepEqual(picks().map(n=>n.dataset.layout),['grid','custom']);
 assert.deepEqual(picks().map(n=>n.getAttribute('aria-checked')),['true','false']);
 const saved=()=>panel.editor.state.reference_preparation.assets.find(a=>a.key==='b');
 picks()[1].fire('click');await new Promise(setImmediate);
 assert.deepEqual(saved().part_overrides,{layout:{choice:'custom'}});
 picks()[0].fire('click');await new Promise(setImmediate);
 assert.equal(saved().part_overrides,undefined);
 const sizes=findAll(panel.body,n=>n.tagName==='INPUT'&&/ (width|height)$/.test(n.getAttribute('aria-label')??''));
 assert.deepEqual(sizes.map(n=>n.placeholder),['width (16:9, native size)','height (16:9, native size)']);
});

test('typing one dimension of a sheet fills the other at 16:9, and an object keeps the native size',async()=>{
 const panel=await open();
 const input=(label)=>findAll(panel.body,n=>n.tagName==='INPUT'&&n.getAttribute('aria-label')===label)[0];
 const saved=()=>panel.editor.state.reference_preparation.assets.find(a=>a.key==='a');
 const width=input('Mara width');width.value='3072';width.fire('change');await new Promise(setImmediate);
 assert.deepEqual(saved().size,{width:3072,height:1728});
 const prop=await open();prop.host.referenceCatalog=async()=>[{...row('c','Pry bar','props'),role:'prop'}];await prop.refresh();
 assert.equal(findAll(prop.body,n=>n.tagName==='INPUT'&&n.getAttribute('aria-label')==='Pry bar width')[0].placeholder,'width (native)');
});
