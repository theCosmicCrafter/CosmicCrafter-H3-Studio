import test from 'node:test';
import assert from 'node:assert/strict';
import {captureRecipe} from '../../../js/h3c_stills.mjs';

test('MiniMax H3 Image Still connects directly and through a switch in a native group', () => {
  for (const nested of [false, true]) {
    const id = nested ? '9:5' : '5';
    const node = {id:5, type:'H3C_MiniMaxH3ImageStill', inputs:[]};
    const workflow = nested ? {nodes:[{id:9,type:'sg'}], definitions:{subgraphs:[{id:'sg',nodes:[node]}]}} : {nodes:[node]};
    const output = {'1':{class_type:'H3C_Timeline',inputs:{still_recipe:['2',0]}},
      '2':{class_type:'LazySwitchKJ',inputs:{switch:true,on_true:[id,1]}},
      [id]:{class_type:node.type,inputs:{prompt:'A room.',instruction:'',seed:1,width:2048,height:2048}}};
    const recipe = captureRecipe({workflow,output}, '1');
    assert.equal(recipe.label, 'MiniMax H3 Image');
    assert.deepEqual(recipe.output, [id,0]);
    assert.equal(recipe.bindings.references.length, 8);
    assert.equal(recipe.bindings.references[7].node, id);
    assert.equal(recipe.reference_label, '<Picture {index}>');
  }
});
