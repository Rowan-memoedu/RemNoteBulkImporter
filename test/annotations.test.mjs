import test from 'node:test';
import assert from 'node:assert/strict';
import {annotateDocuments,auditAnnotations,topAnnotationLayout,auditTopAnnotations} from '../src/annotations.mjs';
test('every document including root gets one branch and two truly empty leaves; original tree stays exact',()=>{
  for(const nodes of [[{id:'topic',parentId:null,document:true,text:[{kind:'text',value:'Topic'}]}],[{id:'unit',parentId:null,document:true,text:[{kind:'text',value:'Unit'}]},{id:'topic',parentId:'unit',document:true,text:[{kind:'text',value:'Topic'}]}]]){
    const base={nodes},before=structuredClone(base),result=annotateDocuments(base),count=nodes.length+1;
    assert.deepEqual(base,before);assert.deepEqual(result.nodes.slice(0,nodes.length),nodes);
    assert.deepEqual(auditAnnotations(result),{documents:count,annotationBranches:count,emptyLeaves:count*2});
    const broken=structuredClone(result);broken.nodes.at(-1).text[0].value='Not empty';assert.throws(()=>auditAnnotations(broken),/empty leaves/);
    assert.throws(()=>annotateDocuments(result),/already exists/);
  }
});
test('top layout annotates document-level content and preserves all original IDs, text and content order',()=>{
  for(const name of ['Lesson','Independent exercise']){
    const base=annotateDocuments({nodes:[{id:'doc',parentId:null,document:true,text:[{kind:'text',value:name}]},{id:'step',parentId:'doc',document:false,text:[{kind:'text',value:'Example'}]},{id:'body',parentId:'step',document:false,text:[{kind:'text',value:'Original body'}]}]});
    const before=structuredClone(base),next=topAnnotationLayout(base),audit=auditTopAnnotations(next);
    assert.deepEqual(base,before);assert.equal(audit.documents,2);assert.equal(audit.directContentNodes,1);assert.equal(audit.annotationBranches,3);
    for(const n of base.nodes)assert.deepEqual(next.nodes.find(x=>x.id===n.id),n);
    for(const parent of [null,'doc','step'])assert.equal(next.nodes.filter(n=>n.parentId===parent)[0].text[0].value,'批注');
    assert.deepEqual(topAnnotationLayout(next),next);const broken=structuredClone(next),rows=broken.nodes.filter(n=>n.parentId==='doc');
    const annotation=broken.nodes.indexOf(rows[0]);broken.nodes.splice(annotation,1);broken.nodes.push(rows[0]);assert.throws(()=>auditTopAnnotations(broken),/not first/);
  }
});
