import {installDom,findAll} from './fake_dom.mjs';
import * as model from '../../../js/h3c_timeline_model.mjs';
import {TimelineEditor} from '../../../js/h3c_timeline_editor.mjs';
import {EditHistory} from '../../../js/h3c_history.mjs';
import {PromptFormPanel} from '../../../js/h3c_prompt_form.mjs';
installDom();
export function formHarness({prompt=''}) {
  let queued=0;
  const editor=Object.assign(Object.create(TimelineEditor.prototype),{
    state:model.parseState(JSON.stringify({boxes:[{id:'a',frames:192,exact:true,seed:1,prompt}]})),selected:0,picked:null,
    host:{context:()=>39,queue:async()=>queued++},
    video(){return this.state.boxes[this.selected];},box(){return this.video();},
    referenceOptions:()=>[],connectedSets:()=>({images:new Set(),audios:new Set(),videos:new Set(),video_audios:new Set()}),
  });
  const history=new EditHistory({timeline:structuredClone(editor.state),settings:{}});
  const record=()=>history.record({timeline:structuredClone(editor.state),settings:{}},'Prompt');
  editor.typed=record;editor.commit=record;
  const panel=new PromptFormPanel(editor);editor.promptForm=panel;panel.render();
  return {panel,editor,history,queued:()=>queued,stored:()=>structuredClone(editor.state),input(label,value){
    const node=findAll(panel.root,n=>n.getAttribute?.('aria-label')===label)[0];
    if(!node)throw new Error(`No field ${label}`);node.value=value;node.fire('input');if(node.tagName!=='TEXTAREA')node.fire('change');
  }};
}
