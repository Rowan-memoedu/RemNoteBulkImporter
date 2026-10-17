import test from 'node:test';
import assert from 'node:assert/strict';
import {inspectPackage,stableJSON} from '../src/package.mjs';
import {runImport} from '../src/engine.mjs';
import {planStructureChange,restructureImport} from '../src/restructure.mjs';
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
