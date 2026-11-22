import {test} from 'node:test';
import assert from 'node:assert/strict';
import {CastPage} from '../../../js/h3c_cast.mjs';
import * as model from '../../../js/h3c_timeline_model.mjs';

function fixture(reply) {
  const state=model.parseState(JSON.stringify({boxes:[{id:'a',frames:96,exact:true,seed:1,prompt:'A room.'}],
    bible:{entities:[{id:'e1',kind:'character',name:'Mara',pictures:[],looks:[],description:'Mara'}]}}));
  const editor={state,editRevision:0,commits:0,steps:0,renderRefmods(){},
    commit(){this.commits++;this.editRevision++;},host:{bible:reply,undoStep(){editor.steps++;}}};
  const page=Object.assign(Object.create(CastPage.prototype),{editor,busy:false,drafts:new Map(),render(){}});
  return {page,editor};
}
const answer={ok:true,changed:true,subject:'<Subject 1>',prompts:{a:'subject_definitions:\n<Subject 1> is Mara.'},
  casts:{a:{'<Subject 1>':'e1'}},schedules:{a:{entities:['e1'],place:null}}};
test('Cast reply commits prompt, mapping and schedule together once',async()=>{
  const {page,editor}=fixture(async()=>structuredClone(answer));
  assert.equal(await page.change({action:'assign',box:'a',entity:'e1'}),true);
  assert.deepEqual(editor.state.boxes[0].schedule,answer.schedules.a);
  assert.equal(editor.commits,1);assert.equal(editor.steps,1);
});
test('late Cast reply after a schedule edit or Undo/Redo cannot overwrite newer state',async()=>{
  for(const change of [editor=>editor.state.boxes[0].schedule={entities:[],place:null},editor=>editor.editRevision+=2,
    editor=>editor.promptForm={hasDrafts:()=>true}]) {
    let finish;
    const {page,editor}=fixture(()=>new Promise(resolve=>{finish=resolve;}));
    const pending=page.change({action:'assign',box:'a',entity:'e1'});
    change(editor);finish(structuredClone(answer));
    assert.equal(await pending,false);assert.equal(editor.commits,0);assert.equal(editor.state.boxes[0].prompt,'A room.');
  }
});
test('already linked Cast selection does not create another history entry',async()=>{
  const {page,editor}=fixture(async()=>({...answer,changed:false,prompts:{},casts:{},schedules:{}}));
  assert.equal(await page.change({action:'assign',box:'a',entity:'e1'}),true);
  assert.equal(editor.commits,0);assert.equal(editor.steps,0);
});
