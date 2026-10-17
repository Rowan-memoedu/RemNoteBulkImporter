import test from 'node:test';
import assert from 'node:assert/strict';
import {imageTransportHashMatches} from '../src/rich-hash.mjs';
import {stableJSON,sha256} from '../src/package.mjs';
test('original hash is required with mixed undefined geometry transport states',async()=>{
  const expected=['Body',{i:'i',url:'a',width:undefined,height:undefined},'Text',{i:'i',url:'b',title:'Preserve'}];
  const transported=JSON.parse(JSON.stringify(expected)),hash=await sha256(stableJSON(expected));
  assert.equal(await imageTransportHashMatches(transported,hash),true);
  for(const change of [r=>r[0]='Edited',r=>r[1].url='changed',r=>r[3].title='Changed',r=>r[1].width=99]){
    const bad=structuredClone(transported);change(bad);assert.equal(await imageTransportHashMatches(bad,hash),false);
  }
});
test('formulas and references stay exact and live input is never modified',async()=>{
  const original=[{i:'x',text:'x^2',block:true},{i:'q',_id:'topic'},{i:'i',url:'z',height:undefined,width:undefined}],actual=JSON.parse(JSON.stringify(original));
  const before=structuredClone(actual),hash=await sha256(stableJSON(original));
  assert.equal(await imageTransportHashMatches(actual,hash),true);assert.deepEqual(actual,before);
  actual[0].text='x^3';assert.equal(await imageTransportHashMatches(actual,hash),false);
});
