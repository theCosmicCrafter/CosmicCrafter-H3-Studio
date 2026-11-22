import test from 'node:test';
import assert from 'node:assert/strict';
import {installDom} from './fake_dom.mjs';
import {ReferenceClient} from '../../../js/h3c_reference_preparation.mjs';
installDom();

const image={file:{type:'output',filename:'sheet.png'},sha256:'a'.repeat(64),prompt_id:'p1',batch_index:0};
const receipt=(state,extra={})=>({request_id:'r1',prompt_id:'p1',asset_key:'a',state,input_fingerprint:'old',provenance:{prompt:'x'},...extra});
function client({catalogFingerprint='new',requests=[],candidates=[]}={}) {
  const state={boxes:[],reference_preparation:{version:1,generate:{cast:true,locations:false,props:false},requests,
    assets:[{key:'a',category:'cast',role:'identity',candidates}]}};
  const host={referenceContext:()=> 'ctx',referenceState:()=>state,referenceChanged(){},request:async()=>({ok:true}),
    referenceCatalog:async()=>[{key:'a',category:'cast',status:'missing',input_fingerprint:catalogFingerprint}],
    writeReferenceState:async next=>{Object.assign(state,structuredClone(next));}};
  return {state,host,client:new ReferenceClient(host)};
}
const saved=state=>state.reference_preparation.assets[0].candidates;

test('a finished image is kept when the reference was edited while it rendered, and shows as out of date',async()=>{
  const {client:references,state}=client();
  await references.save(receipt('complete',{images:[image]}),'ctx');
  assert.equal(saved(state).length,1);
  assert.equal(saved(state)[0].input_fingerprint,'old');
  assert.notEqual(saved(state)[0].input_fingerprint,'new');
});

test('a finished image whose candidate was never saved is adopted once',async()=>{
  const {client:references,state}=client({requests:[receipt('complete',{images:[image]})]});
  assert.equal(await references.adoptFinished(),1);
  assert.deepEqual(saved(state).map(c=>c.id),['p1:0']);
  assert.equal(await references.adoptFinished(),0);
  assert.equal(saved(state).length,1);
});

test('adopting leaves unfinished requests and requests without a reference alone',async()=>{
  const {client:references,state}=client({requests:[receipt('queued',{images:[image]}),receipt('complete',{asset_key:'gone',images:[image]})]});
  assert.equal(await references.adoptFinished(),0);
  assert.equal(saved(state).length,0);
});
