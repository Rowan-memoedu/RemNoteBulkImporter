import test from 'node:test';
import assert from 'node:assert/strict';
import {inspectPackage,stableJSON,sha256} from '../src/package.mjs';
import {runImport} from '../src/engine.mjs';

const clone=value=>structuredClone(value);
const fixture=()=>({schemaVersion:1,packageId:'canary.forward',title:'独立导入测试',nodes:[
  {id:'dependent',parentId:null,document:true,text:[{kind:'text',value:'后继 Topic'}]},
  {id:'prereq-line',parentId:'dependent',document:false,text:[{kind:'text',value:'前置：'},{kind:'ref',targetId:'foundation'}]},
  {id:'foundation',parentId:null,document:true,text:[{kind:'text',value:'基础 Topic'}]},
  {id:'math',parentId:'foundation',document:false,text:[{kind:'text',value:'公式 '},{kind:'latex',value:'x^2+y^2=1',block:true}]},
]});
class MockAdapter {
  constructor(){this.rems=new Map();this.cps=new Map();this.lib='kb-A';this.sequence=0;this.saves=0;this.failSave=0;this.creates=0;this.failCreate=0;}
  async kbId(){return this.lib;}
  async find(id){const r=this.rems.get(id);return r?clone(r):undefined;}
  async load(hash){return clone(this.cps.get(hash));}
  async save(hash,cp){this.saves++;if(this.saves===this.failSave)throw new Error('simulated checkpoint failure');this.cps.set(hash,clone(cp));}
  async findSentinel(title,parent){return clone([...this.rems.values()].find(r=>r.parent===parent && r.text[0]===title));}
  async createSentinel(title,parent,document){
    this.creates++;if(this.creates===this.failCreate)throw new Error('simulated SDK failure');
    const r={_id:`rem-${++this.sequence}`,parent,document,text:[title],practice:false,children:[]};
    this.rems.set(r._id,r);if(parent)this.rems.get(parent).children.push(r._id);return clone(r);
  }
  async transaction(fn){const snapshot=clone(this.rems);try{return await fn();}catch(e){this.rems=snapshot;throw e;}}
  async compile(segments,mapping,assets){return segments.map(s=>s.kind==='ref'?{ref:mapping[s.targetId]}:s.kind==='text'?s.value:{...s});}
  async canonical(text){return stableJSON(text);}
  async setText(rem,rich){this.rems.get(rem._id).text=clone(rich);}
  async disablePractice(rem){this.rems.get(rem._id).practice=false;}
  async practiceEnabled(rem){return rem.practice;}
  async isDocument(rem){return rem.document;}
  async refs(rem){return rem.text.flatMap(s=>s?.ref?[s.ref]:[]);}
  async children(rem){return rem.children;}
}
const request=async p=>({packageHash:(await inspectPackage(p)).hash,kbId:'kb-A',parentRemId:null});
const options={batchSize:2,yieldMs:0};

test('creates real document hierarchy, forward references and exact sibling order; repeat creates nothing',async()=>{
  const a=new MockAdapter(),p=fixture(),r=await request(p),result=await runImport(a,p,r,options);
  assert.equal(result.status,'complete');assert.equal(result.verified,5);assert.equal(a.rems.size,5);
  assert.deepEqual(a.rems.get(result.mapping['prereq-line']).text,['前置：',{ref:result.mapping.foundation}]);
  assert.deepEqual(a.rems.get(result.rootRemId).children,[result.mapping.dependent,result.mapping.foundation]);
  assert.equal((await runImport(a,p,r,options)).status,'complete');assert.equal(a.creates,5);
});
test('a committed creation followed by failed checkpoint recovers exact sentinels without duplicates',async()=>{
  const a=new MockAdapter(),p=fixture(),r=await request(p);a.failSave=3;
  await assert.rejects(runImport(a,p,r,options),/checkpoint/);assert.equal(a.rems.size,2);
  a.failSave=0;const result=await runImport(a,p,r,options);assert.equal(result.status,'complete');assert.equal(a.rems.size,5);assert.equal(a.creates,5);
});
test('SDK creation failure rolls back the small batch, same package resumes',async()=>{
  const a=new MockAdapter(),p=fixture(),r=await request(p);a.failCreate=2;
  await assert.rejects(runImport(a,p,r,options),/SDK failure/);assert.equal(a.rems.size,0);
  a.failCreate=0;assert.equal((await runImport(a,p,r,options)).status,'complete');assert.equal(a.rems.size,5);
});
test('pause leaves checkpoint and resumes; no transient complete claim',async()=>{
  const a=new MockAdapter(),p=fixture(),r=await request(p);let pause=false;
  const result=await runImport(a,p,r,{...options,progress:x=>{if(x.created>=2)pause=true;},shouldPause:()=>pause});
  assert.equal(result.status,'paused');assert.equal(a.rems.size,2);
  assert.equal((await runImport(a,p,r,options)).status,'complete');assert.equal(a.rems.size,5);
});

test('partial creation without host rollback recovers exact sentinels without duplicates',async()=>{
  const a=new MockAdapter(),p=fixture(),r=await request(p);
  a.transaction=async fn=>await fn();a.failCreate=2;
  await assert.rejects(runImport(a,p,r,options),/SDK failure/);assert.equal(a.rems.size,1);
  const originalRoot=[...a.rems.keys()][0];a.failCreate=0;
  const result=await runImport(a,p,r,options);
  assert.equal(result.rootRemId,originalRoot);assert.equal(a.rems.size,5);assert.equal(result.verified,5);
});
test('reconnecting after text commit but checkpoint failure repeats only owned, identical text',async()=>{
  const a=new MockAdapter(),p=fixture(),r=await request(p);let fail=false;
  const original=a.save.bind(a);a.save=async(h,cp)=>{if(!fail&&cp.written===2){fail=true;throw new Error('text checkpoint failure');}return original(h,cp);};
  await assert.rejects(runImport(a,p,r,options),/text checkpoint/);
  assert.equal((await runImport(a,p,r,options)).status,'complete');assert.equal(a.rems.size,5);
});
test('changed knowledge base or destination is rejected before mutation',async()=>{
  const a=new MockAdapter(),p=fixture(),r=await request(p);a.lib='kb-B';
  await assert.rejects(runImport(a,p,r,options),/knowledge base/);assert.equal(a.rems.size,0);
});
test('knowledge base change during a job stops at next batch',async()=>{
  const a=new MockAdapter(),p=fixture(),r=await request(p);
  await assert.rejects(runImport(a,p,r,{...options,progress:x=>{if(x.created===2)a.lib='kb-B';}}),/Knowledge base changed/);assert.equal(a.rems.size,2);
});
test('user edits or deletion prevent overwrite and blind recreation',async()=>{
  const a=new MockAdapter(),p=fixture(),r=await request(p);let pause=false;
  await runImport(a,p,r,{...options,progress:x=>{if(x.created===5)pause=true;},shouldPause:()=>pause});
  const cp=await a.load(r.packageHash);a.rems.get(cp.mapping.dependent).text=['用户自己的修改'];
  await assert.rejects(runImport(a,p,r,options),/refusing overwrite/);
  a.rems.delete(cp.mapping.foundation);await assert.rejects(runImport(a,p,r,options),/refusing duplicate/);
});
test('readback catches incorrect references and extra/moved children',async()=>{
  const p=fixture(),r=await request(p),a=new MockAdapter();a.refs=async()=>[];
  await assert.rejects(runImport(a,p,r,options),/reference targets/);
  const b=new MockAdapter();b.children=async()=>['unrelated'];await assert.rejects(runImport(b,p,r,options),/child order/);
});
test('independent canary has inline multiline source and cyclic cross references without hierarchy cycles',async()=>{
  const p={schemaVersion:1,packageId:'canary.independent',title:'Second source',nodes:[
    {id:'a',parentId:null,document:false,text:[{kind:'text',value:'line one\nline two '},{kind:'ref',targetId:'b'}]},
    {id:'b',parentId:null,document:true,text:[{kind:'ref',targetId:'a'}]},
  ]};const a=new MockAdapter();const result=await runImport(a,p,await request(p),options);
  assert.equal(result.status,'complete');assert.equal(result.references,2);assert.match(a.rems.get(result.mapping.a).text[0],/\n/);
});
test('invalid packages, unresolved refs and implicit markdown refs/media fail before writes',async()=>{
  for(const mutate of [p=>p.nodes.push(p.nodes[0]),p=>p.nodes[0].parentId='unknown',p=>p.nodes[1].text[1].targetId='missing',p=>p.nodes[0].text=[{kind:'markdown',value:'[[pretend reference]]'}],p=>p.nodes[0].text=[{kind:'markdown',value:'![remote](https://x)'}]]){
    const p=fixture();mutate(p);await assert.rejects(inspectPackage(p));
  }
});
test('image bytes must have correct hash and MIME signature',async()=>{
  const p=fixture(),data=new Uint8Array([137,80,78,71,13,10,26,10]);p.assets={image:{mime:'image/png',base64:Buffer.from(data).toString('base64'),sha256:await sha256(data)}};
  p.nodes[0].text.push({kind:'image',assetId:'image'});assert.equal((await inspectPackage(p)).assets,1);
  p.assets.image.sha256='0'.repeat(64);await assert.rejects(inspectPackage(p),/hash mismatch/);
});
test('resume validates existing IDs in bounded SDK batches instead of one read per ID',async()=>{
  const a=new MockAdapter(),p={schemaVersion:1,packageId:'batch.resume.canary',title:'Batch resume',nodes:Array.from({length:300},(_,i)=>({id:`n${i}`,parentId:null,document:false,text:[{kind:'text',value:`Item ${i}`}]}))};
  const r=await request(p);let pause=false;
  await runImport(a,p,r,{...options,batchSize:32,progress:x=>{if(x.created===301)pause=true;},shouldPause:()=>pause});
  const batchSizes=[],progress=[];
  a.findMany=async ids=>{batchSizes.push(ids.length);return Promise.all(ids.map(id=>a.find(id)));};
  const result=await runImport(a,p,r,{...options,batchSize:32,progress:x=>progress.push(x)});
  assert.equal(result.status,'complete');assert.deepEqual(batchSizes.slice(0,3),[128,128,45]);
  assert.equal(batchSizes.slice(3).reduce((a,b)=>a+b,0),301);assert.ok(batchSizes.slice(3).every(size=>size<=32));
  assert.equal(progress.filter(x=>x.phase==='resume-check').at(-1).checked,301);
});
