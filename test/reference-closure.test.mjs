import test from 'node:test';
import assert from 'node:assert/strict';
import {referenceClosure} from '../src/reference-closure.mjs';
const n=(id,parentId=null,children=[],extra={})=>({id,parentId,children,text:[id],backText:null,type:0,meta:{document:false},refs:[],tags:[],sources:[],aliases:[],...extra});

test('an existing definition still requires all descendants and nested reference content',()=>{
  const nodes=[n('a',null,['b']),n('b','a',[],{refs:['c']}),n('c',null,['d']),n('d','c')];
  const r=referenceClosure({nodes,roots:['a'],existingIds:['a']});
  assert.deepEqual(new Set(r.sourceNodes.map(n=>n.id)),new Set(['a','b','c','d']));
  assert.deepEqual(r.attachments,[{sourceId:'b',sourceParentId:'a'},{sourceId:'c',sourceParentId:null}]);
  assert.equal(r.coverage.packageExternalReferences.length,0);
});
test('missing source children fail before any package can be produced',()=>{
  assert.throws(()=>referenceClosure({nodes:[n('a',null,['b'])],roots:['a']}),/Missing source snapshot: b/);
});
test('context roots retain real siblings and ancestor headings but do not import other branches',()=>{
  const nodes=[n('top',null,['section','unrelated']),n('section','top',['term','explanation']),n('term','section'),n('explanation','section'),n('unrelated','top')];
  const r=referenceClosure({nodes,roots:['term'],contextRoots:['section']});
  assert.deepEqual(r.sourceNodes.map(n=>n.id),['top','section','term','explanation']);
});
test('generated query infrastructure is excluded, ordinary portal dependencies are retained',()=>{
  const nodes=[n('a',null,['query','body','portal']),n('query','a',['derived'],{type:6,portalType:4}),n('body','a'),n('portal','a',[],{type:6,portalType:0,portal:['target']}),n('target')];
  const r=referenceClosure({nodes,roots:['a']});
  assert.deepEqual(r.coverage.generatedQueriesExcluded,['query']);
  assert.ok(r.sourceNodes.some(n=>n.id==='target'));
  assert.ok(!r.sourceNodes.some(n=>n.id==='derived'));
});
test('reference cycles terminate and parent cycles are rejected',()=>{
  const nodes=[n('a',null,[],{refs:['b']}),n('b',null,[],{refs:['a']})];
  assert.equal(referenceClosure({nodes,roots:['a']}).sourceNodes.length,2);
  assert.throws(()=>referenceClosure({nodes:[n('a','b'),n('b','a')],roots:['a']}),/parent cycle/);
});
test('references to existing destination anchors remain explicit instead of being erased',()=>{
  const r=referenceClosure({nodes:[n('new',null,[],{refs:['existing']})],roots:['new'],existingIds:['existing']});
  assert.deepEqual(r.coverage.packageExternalReferences,[{from:'new',to:'existing',reason:'refs'}]);
});
test('dependencies introduced by ancestor text bring their own parent context',()=>{
  const nodes=[n('root'),n('heading','root',['leaf'],{refs:['dependent']}),n('leaf','heading'),n('dependent','other'),n('other')];
  const r=referenceClosure({nodes,roots:['leaf']});
  assert.deepEqual(new Set(r.sourceNodes.map(n=>n.id)),new Set(['root','heading','leaf','other','dependent']));
});
