import test from 'node:test';
import assert from 'node:assert/strict';
import {remapRich,sdkPortableRich,canonicalRemType,inspectNativePlan,snapshotNative,copyNativeBatch} from '../src/selective-native.mjs';
const node=(id,parentId=null)=>({id,parentId,text:[id],backText:null,type:0,meta:{document:false},tags:[],sources:[],refs:[]});
test('default Rem type has the same meaning across absent, zero and SDK token encodings',()=>{for(const value of [undefined,null,0,'DEFAULT_TYPE'])assert.equal(canonicalRemType(value),0);assert.equal(canonicalRemType(1),1);assert.equal(canonicalRemType(2),2);assert.equal(canonicalRemType(6),6);assert.equal(canonicalRemType('unknown'),'unknown');});
test('native references remap while text, formula, cloze and image bytes remain unchanged',()=>{
  const input=['literal a',{i:'q',_id:'a',aliasId:'alias'},{i:'m',text:'a',qId:'b',cId:'a'},{i:'x',text:'a+b',block:true},{i:'i',url:'%LOCAL_FILE%abc.png',blocks:[{linkedRemId:'b',label:[{i:'q',_id:'a'}]}]}];
  const before=JSON.stringify(input),out=remapRich(input,{a:'A',b:'B',alias:'AL'});
  assert.equal(JSON.stringify(input),before);assert.equal(out[1]._id,'A');assert.equal(out[1].aliasId,'AL');assert.equal(out[2].text,'a');assert.equal(out[2].cId,'a');assert.equal(out[2].qId,'B');assert.equal(out[3].text,'a+b');assert.equal(out[4].url,input[4].url);assert.equal(out[4].blocks[0].label[0]._id,'A');
});
test('plans reject missing references, implicit same-KB migration, bad order and unsupported native types',()=>{
  const p={schemaVersion:1,title:'sample',sourceKbId:'old',destinationKbId:'new',nodes:[node('a'),node('b','a')]};
  assert.equal(inspectNativePlan(p).nodes,2);
  assert.throws(()=>inspectNativePlan({...p,destinationKbId:'old'}));
  assert.equal(inspectNativePlan({...p,destinationKbId:'old',operation:'copy'}).nodes,2);
  assert.throws(()=>inspectNativePlan({...p,destinationKbId:'old',operation:'migrate'}));
  assert.throws(()=>inspectNativePlan({...p,operation:'replace'}));
  assert.throws(()=>inspectNativePlan({...p,nodes:[{...node('a'),refs:['missing']}]}));
  assert.throws(()=>inspectNativePlan({...p,nodes:[node('b','a'),node('a')]}));
  assert.throws(()=>inspectNativePlan({...p,nodes:[{...node('a'),type:4}]}));
});

test('explicit same-KB copy allocates fresh IDs and leaves the source tree untouched',async()=>{
  const f=fixture(),source=await f.plugin.rem.createRem(),child=await f.plugin.rem.createRem();
  await source.setText(['independent source']);await child.setText(['detail',{i:'x',text:'x^2+1'}]);await child.setParent(source._id);
  const original=JSON.stringify([source.text,child.text,source.parent,child.parent]);
  const nodes=[{...node(source._id),text:structuredClone(source.text)},{...node(child._id,source._id),text:structuredClone(child.text)}];
  inspectNativePlan({schemaVersion:1,operation:'copy',title:'copy',sourceKbId:'new',destinationKbId:'new',nodes});
  const req={kbId:'new',jobId:'d'.repeat(64),title:'copy',nodes,allNodes:nodes};
  const {mapping}=await copyNativeBatch(f.plugin,{...req,phase:'create'},f.monitor);
  for(const n of nodes)assert.notEqual(mapping[n.id],n.id);
  await copyNativeBatch(f.plugin,{...req,phase:'write',mapping},f.monitor);
  const verified=await copyNativeBatch(f.plugin,{...req,phase:'verify',mapping},f.monitor);
  assert.equal(verified.diagnostics.length,2);
  assert.equal(JSON.stringify([source.text,child.text,source.parent,child.parent]),original);
  assert.deepEqual(f.rems.get(mapping[child._id]).text,child.text);
});
test('unsupported image viewport percentages retain exact managed asset, pixel geometry, label and original snapshot',()=>{
  const input=[{i:'i',url:'%LOCAL_FILE%fixture.png',width:213.5,height:97.2,percent:42.6,title:'caption',imgId:'source-id',uploadDevice:{id:'device'}},{i:'x',text:'x+y'}];
  const before=JSON.stringify(input),portable=sdkPortableRich(input);assert.equal(JSON.stringify(input),before);
  assert.deepEqual(portable,[{i:'i',url:'%LOCAL_FILE%fixture.png',width:213.5,height:97.2,title:'caption',imgId:'source-id'},{i:'x',text:'x+y'}]);
  assert.equal(sdkPortableRich([{i:'i',url:'x',percent:50}])[0].percent,50);
  assert.throws(()=>sdkPortableRich([{i:'i',url:'x',percent:42.6}]),/geometry/);
});
test('source and destination KB guards reject before touching notes',async()=>{
  let touched=false;const plugin={kb:{getCurrentKnowledgeBaseData:async()=>({_id:'other'})},rem:{findOne:()=>{touched=true;}}};
  const monitor={call:async(_,fn)=>fn()};
  await assert.rejects(snapshotNative(plugin,{kbId:'old',remIds:['a']},monitor),/identity/);
  await assert.rejects(copyNativeBatch(plugin,{kbId:'new',jobId:'a'.repeat(64),nodes:[]},monitor),/identity/);assert.equal(touched,false);
});

function fixture(){
  let seq=0;const rems=new Map(),store=new Map();
  const getters={isDocument:'document',isFolder:'folder',isListItem:'listItem',isCardItem:'cardItem',isQuote:'quote',isCode:'code',isTodo:'todo',getFontSize:'fontSize',getHighlightColor:'highlight',getEnablePractice:'practice',getPracticeDirection:'direction'};
  const make=async(portal=false)=>{const r={_id:`new-${++seq}`,parent:null,text:[],type:portal?6:0,meta:{},tags:[],sources:[],portal:[]};
    r.setText=async t=>{r.text=structuredClone(t);};r.setBackText=async t=>{r.backText=structuredClone(t);};r.setParent=async p=>{r.parent=p;};r.setType=async t=>{if(!['DEFAULT_TYPE',1,2].includes(t))throw new Error('SDK enum token differs');r.type=t==='DEFAULT_TYPE'?0:t;};r.getChildrenRem=async()=>[...rems.values()].filter(x=>x.parent===r._id);r.getAliases=async()=>[];r.getTagRems=async()=>r.tags.map(id=>rems.get(id));r.getSources=async()=>r.sources.map(id=>rems.get(id));r.addTag=async id=>{if(!r.tags.includes(id))r.tags.push(id);};r.addSource=async id=>{if(!r.sources.includes(id))r.sources.push(id);};r.addToPortal=async p=>{if(!p.portal.includes(r._id))p.portal.push(r._id);};r.getPortalDirectlyIncludedRem=async()=>r.portal.map(id=>rems.get(id));r.getPortalType=async()=>0;
    for(const [get,key] of Object.entries(getters)){r[get]=async()=>r.meta[key];r[get.replace(/^is/,'setIs').replace(/^get/,'set')]=async v=>{r.meta[key]=v;};}
    r.setIsDocument=async value=>{r.meta.document=value;if(value)r.meta.folder=true;};
    rems.set(r._id,r);return r;
  };
  const plugin={kb:{getCurrentKnowledgeBaseData:async()=>({_id:'new'})},storage:{getLocal:async k=>store.get(k),setLocal:async(k,v)=>{store.set(k,v);}},app:{transaction:async fn=>fn()},rem:{findOne:async id=>rems.get(id),findByName:async(text,parent)=>[...rems.values()].find(r=>r.parent===parent&&JSON.stringify(r.text)===JSON.stringify(text)),createRem:()=>make(),createPortal:()=>make(true)}};
  return {plugin,rems,store,monitor:{call:async(_,fn)=>fn()}};
}
test('whole selective copy preserves native content, order, portal and references, resumes without duplicates, detects edited content',async()=>{
  const f=fixture(),nodes=[{...node('doc'),meta:{document:true,folder:false}}, {...node('body','doc'),text:[{i:'q',_id:'target'},{i:'x',text:'E=mc^2'},{i:'i',url:'image.png'}],backText:['answer'],tags:['target'],refs:['target']},node('target','doc'),{...node('portal','doc'),type:6,portalType:0,portal:['target']}];
  const req={kbId:'new',jobId:'b'.repeat(64),title:'fixture',nodes,allNodes:nodes};
  let result=await copyNativeBatch(f.plugin,{...req,phase:'create'},f.monitor);const mapping=result.mapping,count=f.rems.size;
  await copyNativeBatch(f.plugin,{...req,phase:'create',mapping},f.monitor);assert.equal(f.rems.size,count);
  result=await copyNativeBatch(f.plugin,{...req,phase:'write',mapping},f.monitor);
  assert.equal(f.rems.get(mapping.body).text[0]._id,mapping.target);assert.deepEqual(f.rems.get(mapping.body).backText,['answer']);
  result=await copyNativeBatch(f.plugin,{...req,phase:'verify',mapping},f.monitor);assert.equal(result.diagnostics.length,nodes.length);
  f.rems.get(mapping.body).text=['user edit'];
  await assert.rejects(copyNativeBatch(f.plugin,{...req,phase:'write',mapping},f.monitor),/content changed/);
  await assert.rejects(copyNativeBatch(f.plugin,{...req,phase:'verify',mapping},f.monitor),/verification failed/);
});

test('folder display exception is opt-in and never excuses a document mismatch',async()=>{
  const f=fixture(),nodes=[{...node('doc'),meta:{document:true,folder:false}}];
  const req={kbId:'new',jobId:'c'.repeat(64),title:'folder fixture',nodes,allNodes:nodes};
  const {mapping}=await copyNativeBatch(f.plugin,{...req,phase:'create'},f.monitor);
  await copyNativeBatch(f.plugin,{...req,phase:'write',mapping,allowFolderDisplayDifference:true},f.monitor);
  await assert.rejects(copyNativeBatch(f.plugin,{...req,phase:'verify',mapping},f.monitor),/Metadata folder differs/);
  const result=await copyNativeBatch(f.plugin,{...req,phase:'verify',mapping,allowFolderDisplayDifference:true},f.monitor);
  assert.deepEqual(result.diagnostics[0].acceptedDifferences,[{field:'folder',source:false,destination:true}]);
  f.rems.get(mapping.doc).meta.document=false;
  await assert.rejects(copyNativeBatch(f.plugin,{...req,phase:'verify',mapping,allowFolderDisplayDifference:true},f.monitor),/Metadata document differs/);
});
