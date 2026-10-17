import test from 'node:test';
import assert from 'node:assert/strict';
import {annotateDocuments,auditAnnotations} from '../src/annotations.mjs';
test('every document including root gets one branch and two truly empty leaves; original tree stays exact',()=>{
  for(const nodes of [[{id:'topic',parentId:null,document:true,text:[{kind:'text',value:'Topic'}]}],[{id:'unit',parentId:null,document:true,text:[{kind:'text',value:'Unit'}]},{id:'topic',parentId:'unit',document:true,text:[{kind:'text',value:'Topic'}]}]]){
    const base={nodes},before=structuredClone(base),result=annotateDocuments(base),count=nodes.length+1;
    assert.deepEqual(base,before);assert.deepEqual(result.nodes.slice(0,nodes.length),nodes);
    assert.deepEqual(auditAnnotations(result),{documents:count,annotationBranches:count,emptyLeaves:count*2});
    const broken=structuredClone(result);broken.nodes.at(-1).text[0].value='Not empty';assert.throws(()=>auditAnnotations(broken),/empty leaves/);
    assert.throws(()=>annotateDocuments(result),/already exists/);
  }
});
