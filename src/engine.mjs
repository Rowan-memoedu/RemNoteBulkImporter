import { inspectPackage, stableJSON, sha256 } from './package.mjs';
import {boundedRead} from './bounded-read.mjs';
import {ownedChildren} from './owned-children.mjs';

const delay = ms => new Promise(resolve=>setTimeout(resolve,ms));
const assert = (condition,message) => { if(!condition) throw new Error(message); };

/** All data access goes through an official SDK adapter, with bounded transactions.
 * Creation uses durable sentinel titles. If a commit succeeds but checkpointing fails,
 * the next run recovers the exact sentinel instead of blindly creating a second node.
 * No mutation is ever made to a Rem outside the recorded import mapping.
 * @param {any} adapter
 * @param {any} plan
 * @param {any} request
 * @param {{progress?:(state:any)=>void,shouldPause?:()=>boolean,batchSize?:number,yieldMs?:number}} options
 */
export async function runImport(adapter,plan,request,{progress=()=>{},shouldPause=()=>false,batchSize=16,yieldMs=25}={}) {
  assert(Number.isInteger(batchSize) && batchSize>=1 && batchSize<=32,'batchSize must be 1..32');
  const info = await inspectPackage(plan);
  assert(info.hash === request.packageHash,'Package hash mismatch');
  const kbId = await adapter.kbId();
  assert(kbId === request.kbId,'Active knowledge base differs from submitted destination');
  const destination = request.parentRemId ?? null;
  if(destination) assert(await adapter.find(destination),'Destination Rem not found');
  let cp = await adapter.load(info.hash);
  if(cp) {
    assert(cp.hash===info.hash && cp.kbId===kbId && cp.parentRemId===destination,'Checkpoint identity/destination mismatch');
    assert(cp.version===1,'Unsupported checkpoint');
  } else {
    cp = {version:1,hash:info.hash,kbId,parentRemId:destination,phase:'create',mapping:{},created:0,written:0,verified:0,expected:{},inFlight:null};
    await adapter.save(info.hash,cp);
  }
  const nodes = [{id:'$root',parentId:null,document:true,text:[{kind:'text',value:plan.title}]},...plan.nodes];
  const parentFor = n => n.id==='$root' ? destination : n.parentId===null ? cp.mapping.$root : cp.mapping[n.parentId];
  const sentinel = id => `RBI:${info.hash}:${id}`;
  const emit = () => progress({phase:cp.phase,created:cp.created,written:cp.written,verified:cp.verified,total:nodes.length,rootRemId:cp.mapping.$root ?? null});
  const guard = async () => {
    assert(await adapter.kbId() === kbId,'Knowledge base changed during import');
    if(shouldPause()) { cp.phaseBeforePause=cp.phase; await adapter.save(info.hash,cp); emit(); return true; }
    return false;
  };
  // Mapped Rems must still exist. Never silently recreate deleted user-edited material.
  const mapped=Object.entries(cp.mapping);
  if(cp.written>=nodes.length){
    // No further Rem writes are needed. The full fresh audit below checks every
    // mapped ID, avoiding a second existence scan before that same audit.
  } else if(mapped.length && adapter.findMany){
    for(let start=0;start<mapped.length;start+=128){
      if(await guard())return {status:'paused',...info,rootRemId:cp.mapping.$root};
      const rows=mapped.slice(start,start+128);
      const snapshots=await adapter.findMany(rows.map(([,id])=>id));
      assert(await adapter.kbId()===kbId,'Knowledge base changed during resume check');
      const found=new Set((snapshots??[]).map(rem=>rem._id));
      for(const [key,id] of rows)assert(found.has(id),`Mapped Rem missing (${key}); refusing duplicate recreation`);
      progress({phase:'resume-check',created:cp.created,written:cp.written,verified:cp.verified,total:nodes.length,checked:Math.min(start+128,mapped.length),resumeTotal:mapped.length,rootRemId:cp.mapping.$root??null});
      await delay(yieldMs);
    }
  } else for(const [key,id] of mapped)assert(await adapter.find(id),`Mapped Rem missing (${key}); refusing duplicate recreation`);
  emit();
  while(cp.created<nodes.length) {
    if(await guard()) return {status:'paused',...info,rootRemId:cp.mapping.$root};
    const start=cp.created,end=Math.min(nodes.length,start+batchSize);
    // Journal intent before the transaction; recoverable sentinel is stable across retries.
    cp.inFlight={phase:'create',start,end}; await adapter.save(info.hash,cp);
    const addition={};
    await adapter.transaction(async()=>{
      for(let i=start;i<end;i++) {
        const n=nodes[i], parent = n.id==='$root' ? destination : n.parentId===null ? (addition.$root ?? cp.mapping.$root) : (addition[n.parentId] ?? cp.mapping[n.parentId]);
        let rem=await adapter.findSentinel(sentinel(n.id),parent);
        if(!rem) rem=await adapter.createSentinel(sentinel(n.id),parent,n.document);
        assert(rem,'SDK failed to create node');
        assert(await adapter.isDocument(rem)===n.document,`Sentinel document flag mismatch: ${n.id}`);
        addition[n.id]=rem._id;
      }
    });
    Object.assign(cp.mapping,addition); cp.created=end;cp.inFlight=null;
    await adapter.save(info.hash,cp);emit();await delay(yieldMs);
  }
  cp.phase='write'; await adapter.save(info.hash,cp);emit();
  while(cp.written<nodes.length) {
    if(await guard()) return {status:'paused',...info,rootRemId:cp.mapping.$root};
    const start=cp.written,end=Math.min(nodes.length,start+batchSize),prepared=[];
    // Prepare RichText outside a transaction; include exact native reference targets.
    for(let i=start;i<end;i++) {
      adapter.context?.({phase:'compile',index:i,nodeId:nodes[i].id});
      const n=nodes[i],rich=await adapter.compile(n.text,cp.mapping,plan.assets ?? {});
      prepared.push({node:n,rich,canonical:await adapter.canonical(rich)});
    }
    await adapter.transaction(async()=>{
      for(const {node:n,rich,canonical} of prepared) {
        adapter.context?.({phase:'write',nodeId:n.id,remId:cp.mapping[n.id]});
        const rem=await adapter.find(cp.mapping[n.id]);assert(rem,`Missing mapped node ${n.id}`);
        const actual=await adapter.canonical(rem.text ?? []),initial=await adapter.canonical([sentinel(n.id)]);
        assert(actual===initial || actual===canonical,`Imported text was edited (${n.id}); refusing overwrite`);
        assert(rem.parent===parentFor(n),`Imported node moved (${n.id}); refusing mutation`);
        await adapter.setText(rem,rich);
        await adapter.disablePractice(rem);
      }
    });
    for(const {node:n,canonical} of prepared) cp.expected[n.id]=await sha256(canonical);
    cp.written=end;await adapter.save(info.hash,cp);emit();await delay(yieldMs);
  }
  cp.phase='verify';cp.verified=0;await adapter.save(info.hash,cp);emit();
  // Read fresh Rems after writes. Verify every node, not a sample or rendered markdown.
  const expectedChildren=new Map();
  const ownedIds=new Set(Object.values(cp.mapping));cp.externalChildren={};
  for(const n of nodes.slice(1)) {
    const parent=parentFor(n);if(!expectedChildren.has(parent))expectedChildren.set(parent,[]);
    expectedChildren.get(parent).push(cp.mapping[n.id]);
  }
  for(let start=0;start<nodes.length;start+=batchSize) {
    if(await guard()) return {status:'paused',...info,rootRemId:cp.mapping.$root};
    const rows=nodes.slice(start,start+batchSize);
    const snapshots=adapter.findMany?await adapter.findMany(rows.map(n=>cp.mapping[n.id])):null;
    const found=snapshots?new Map(snapshots.map(rem=>[rem._id,rem])):null;
    await boundedRead(rows,async(n,offset)=>{
    adapter.context?.({phase:'verify',index:start+offset,nodeId:n.id});
    const rem=found?found.get(cp.mapping[n.id]):await adapter.find(cp.mapping[n.id]);assert(rem,`Readback missing ${n.id}`);
    assert(rem.parent===parentFor(n),`Readback parent mismatch ${n.id}`);
    assert(await adapter.isDocument(rem)===n.document,`Readback document mismatch ${n.id}`);
    const richMatches=adapter.matchesExpected?await adapter.matchesExpected(rem.text??[],cp.expected[n.id]):await sha256(await adapter.canonical(rem.text ?? []))===cp.expected[n.id];
    if(!richMatches){adapter.context?.({phase:'verify',index:start+offset,nodeId:n.id});await adapter.diagnoseMismatch?.(n,cp.mapping,plan.assets??{},rem.text??[],cp.expected[n.id]);}
    assert(richMatches,`Readback RichText mismatch ${n.id}`);
    assert(!await adapter.practiceEnabled(rem),`Unexpected practice card ${n.id}`);
    const actualRefs=await adapter.refs(rem),expectedRefs=n.text.filter(s=>s.kind==='ref').map(s=>cp.mapping[s.targetId]);
    assert(stableJSON([...new Set(actualRefs)].sort())===stableJSON([...new Set(expectedRefs)].sort()),`Readback reference targets mismatch ${n.id}`);
    const children=await adapter.children(rem);
    const external=ownedChildren(children,expectedChildren.get(rem._id)??[],ownedIds,adapter.preserveExternalChildren);
    assert(external!==null,`Readback child order/count mismatch ${n.id}`);
    if(external.length)cp.externalChildren[rem._id]=external;
    },4);
    cp.verified=start+rows.length;emit();await delay(yieldMs);
  }
  cp.phase='complete';cp.inFlight=null;await adapter.save(info.hash,cp);emit();
  return {status:'complete',...info,rootRemId:cp.mapping.$root,mapping:cp.mapping,verified:cp.verified,kbId,preservedExternalChildren:cp.externalChildren};
}
