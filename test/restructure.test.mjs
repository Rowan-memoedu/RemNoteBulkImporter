import test from 'node:test';
import assert from 'node:assert/strict';
import {inspectPackage,stableJSON} from '../src/package.mjs';
import {runImport} from '../src/engine.mjs';
import {planStructureChange,restructureImport} from '../src/restructure.mjs';
import {annotateDocuments,auditAnnotations,topAnnotationLayout,auditTopAnnotations} from '../src/annotations.mjs';
const clone=x=>structuredClone(x),text=value=>[{kind:'text',value}];
class MemoryAdapter {
  constructor(){this.rems=new Map();this.cps=new Map();this.sequence=0;}
  async kbId(){return 'kb';}
  async load(hash){return clone(this.cps.get(hash));}
  async save(hash,state){this.cps.set(hash,clone(state));}
  async find(id){return clone(this.rems.get(id));}
  async findMany(ids){return await Promise.all(ids.map(id=>this.find(id)));}
  async findSentinel(title,parent){return clone([...this.rems.values()].find(r=>r.parent===parent&&r.text[0]===title));}
  async createSentinel(title,parent,document){const r={_id:'r'+(++this.sequence),parent,document,text:[title],practice:false,children:[]};this.rems.set(r._id,r);if(parent)this.rems.get(parent).children.push(r._id);return clone(r);}
  async transaction(callback){return await callback();}
  async compile(parts,mapping){return parts.map(s=>s.kind==='text'?s.value:s.kind==='ref'?{ref:mapping[s.targetId]}:clone(s));}
  async canonical(rich){return stableJSON(rich);}
  async setText(rem,rich){this.rems.get(rem._id).text=clone(rich);}
  async disablePractice(rem){this.rems.get(rem._id).practice=false;}
  async practiceEnabled(rem){return rem.practice;}
  async isDocument(rem){return rem.document;}
  async refs(rem){return rem.text.flatMap(s=>s?.ref?[s.ref]:[]);}
  async children(rem){return rem.children;}
  async move(rem,parent,index){const current=this.rems.get(rem._id);if(current.parent){const old=this.rems.get(current.parent).children;old.splice(old.indexOf(rem._id),1);}current.parent=parent;this.rems.get(parent).children.splice(index,0,rem._id);}
}
async function fixture(){
  const a=new MemoryAdapter(),recovery=await a.createSentinel('Recovery',null,true);
  const base={schemaVersion:1,packageId:'structure.fixture',title:'Course',nodes:[
    {id:'a',parentId:null,document:true,text:text('A')},
    {id:'meta',parentId:'a',document:false,text:text('Unit / module metadata')},
    {id:'pre',parentId:'a',document:false,text:[{kind:'ref',targetId:'b'}]},
    {id:'b',parentId:null,document:true,text:text('B')},
    {id:'body',parentId:'b',document:false,text:text('Original complete content\nSecond line')},
  ]};
  const request={packageHash:(await inspectPackage(base)).hash,kbId:'kb',parentRemId:null};
  const original=await runImport(a,base,request,{batchSize:2,yieldMs:0});
  const next={...clone(base),nodes:[
    {id:'unit',parentId:null,document:true,text:text('Unit')},
    {id:'module',parentId:'unit',document:true,text:text('Module')},
    ...base.nodes.filter(n=>n.id!=='meta').map(n=>({...n,parentId:n.id==='a'||n.id==='b'?'module':n.parentId})),
  ]};
  const revision={packageHash:(await inspectPackage(next)).hash,kbId:'kb',parentRemId:null,baseHash:request.packageHash,basePlan:base,archiveParentRemId:recovery._id};
  return {a,base,next,revision,original};
}
test('structure-only migration preserves IDs, native reference targets, body and root, with reversible metadata recovery',async()=>{
  const {a,next,revision,original}=await fixture(),before=a.rems.size;
  const result=await restructureImport(a,next,revision,{yieldMs:0});
  assert.equal(result.status,'complete');assert.equal(result.rootRemId,original.rootRemId);assert.equal(a.rems.size,before+3);
  for(const id of ['a','b','body','pre'])assert.equal(result.mapping[id],original.mapping[id]);
  assert.deepEqual(a.rems.get(result.mapping.pre).text,[{ref:original.mapping.b}]);
  assert.equal(a.rems.get(result.mapping.a).parent,result.mapping.module);
  assert.equal(a.rems.get(result.mapping.module).parent,result.mapping.unit);
  const cp=await a.load(revision.packageHash);
  assert.equal(a.rems.get(original.mapping.meta).parent,cp.restructure.archiveRemId);
  assert.ok(!Object.values(result.mapping).includes(original.mapping.meta));
});
test('edited imported body stops restructuring before any Rem creation or move',async()=>{
  const {a,next,revision,original}=await fixture(),before=a.rems.size;
  a.rems.get(original.mapping.body).text=['User edit'];
  await assert.rejects(restructureImport(a,next,revision),/text was edited/);assert.equal(a.rems.size,before);
});
test('structure migration adds annotation branches and two empty leaves under every document while retaining old IDs',async()=>{
  const {a,next,revision,original}=await fixture(),annotated=annotateDocuments(next);
  revision.packageHash=(await inspectPackage(annotated)).hash;
  const result=await restructureImport(a,annotated,revision,{yieldMs:0});
  assert.equal(result.status,'complete');assert.equal(result.mapping.a,original.mapping.a);
  assert.equal(result.verified,annotated.nodes.length+1);assert.equal(auditAnnotations(annotated).emptyLeaves,10);
  for(const n of annotated.nodes.filter(n=>n.text.length===1&&n.text[0].value==='')){
    const live=a.rems.get(result.mapping[n.id]);assert.equal(live.document,false);assert.deepEqual(live.text,['']);assert.deepEqual(live.children,[]);
  }
});
test('move committed before checkpoint failure resumes with same IDs and no duplicate documents',async()=>{
  const {a,next,revision,original}=await fixture(),save=a.save.bind(a);let failed=false;
  a.save=async(hash,cp)=>{if(hash===revision.packageHash&&cp.restructure?.moved===1&&!failed){failed=true;throw new Error('move checkpoint failure');}return save(hash,cp);};
  await assert.rejects(restructureImport(a,next,revision),/move checkpoint/);const count=a.rems.size;
  const result=await restructureImport(a,next,revision,{yieldMs:0});
  assert.equal(a.rems.size,count);assert.equal(result.mapping.a,original.mapping.a);assert.equal(result.status,'complete');
});
test('structure plan cannot modify text, assets or referenced/non-leaf content',async()=>{
  const {base,next}=await fixture(),changed=clone(next);changed.nodes.find(n=>n.id==='body').text=text('Changed');
  assert.throws(()=>planStructureChange(base,changed),/retained content/);
  const referenced=clone(base);referenced.nodes.find(n=>n.id==='pre').text=[{kind:'ref',targetId:'meta'}];
  assert.throws(()=>planStructureChange(referenced,next));
});
test('user-added portal remains under the same Topic while all owned children are audited',async()=>{
  const {a,next,revision,original}=await fixture();a.preserveExternalChildren=true;
  const portal=await a.createSentinel('User portal',original.mapping.a,false);
  const result=await restructureImport(a,annotateDocuments(next),{...revision,packageHash:(await inspectPackage(annotateDocuments(next))).hash},{yieldMs:0});
  assert.equal(result.status,'complete');assert.equal(a.rems.get(portal._id).parent,original.mapping.a);
  assert.deepEqual(result.preservedExternalChildren[original.mapping.a],[portal._id]);
});
test('order-only annotation changes and new content annotations migrate together without rewriting retained content',async()=>{
  const {a,next,revision}=await fixture(),annotated=annotateDocuments(next),request={...revision,packageHash:(await inspectPackage(annotated)).hash};
  const first=await restructureImport(a,annotated,request,{yieldMs:0}),top=topAnnotationLayout(annotated),topRequest={...request,packageHash:(await inspectPackage(top)).hash,baseHash:request.packageHash,basePlan:annotated};
  const result=await restructureImport(a,top,topRequest,{yieldMs:0});assert.equal(result.status,'complete');auditTopAnnotations(top);
  for(const n of annotated.nodes)assert.equal(result.mapping[n.id],first.mapping[n.id]);
  for(const id of [null,'unit','module','a','b','pre','body']){
    const expected=top.nodes.find(n=>n.parentId===id);if(!expected)continue;
    const parent=id===null?result.rootRemId:result.mapping[id];assert.equal(a.rems.get(parent).children[0],result.mapping[expected.id]);
  }
});
test('batched annotation creation recovers a committed batch after mapping checkpoint failure',async()=>{
  const {a,next,revision}=await fixture(),top=topAnnotationLayout(annotateDocuments(next)),request={...revision,packageHash:(await inspectPackage(top)).hash},save=a.save.bind(a);let failed=false;
  a.save=async(hash,cp)=>{if(hash===request.packageHash&&cp.restructure?.preflight&&cp.restructure.added===0&&Object.keys(cp.mapping).length>12&&!failed){failed=true;throw new Error('batch mapping checkpoint failure');}return save(hash,cp);};
  await assert.rejects(restructureImport(a,top,request),/batch mapping/);const count=a.rems.size;
  const result=await restructureImport(a,top,request,{yieldMs:0});assert.equal(result.status,'complete');assert.equal(result.verified,top.nodes.length+1);
  assert.equal(a.rems.size,new Set(a.rems.keys()).size);for(const n of top.nodes)assert.ok(result.mapping[n.id]);
  assert.ok(a.rems.size>=count);assert.equal(a.rems.size,Object.keys(result.mapping).length+3);assert.equal([...a.rems.values()].filter(n=>n.text[0]?.startsWith?.('RBI:')).length,0);
});
