import {inspectPackage,stableJSON,sha256} from './package.mjs';
import {runImport} from './engine.mjs';
import {boundedRead} from './bounded-read.mjs';
import {ownedChildren,preserveExternalSlots} from './owned-children.mjs';
const requireValue=(ok,message)=>{if(!ok)throw new Error(message);};
const root=plan=>({id:'$root',parentId:null,document:true,text:[{kind:'text',value:plan.title}]});

/** Only structure may change: retained text/assets/refs remain byte-identical.
 * Add plain-text documents/nodes, reparent retained Rems, archive obsolete plain leaves.
 */
export function planStructureChange(base,next){
  requireValue(base.packageId===next.packageId&&base.title===next.title,'Structure revision must retain package identity and title');
  requireValue(stableJSON(base.assets??{})===stableJSON(next.assets??{}),'Structure revision cannot change assets');
  const old=new Map(base.nodes.map(n=>[n.id,n])),fresh=new Map(next.nodes.map(n=>[n.id,n]));
  const added=next.nodes.filter(n=>!old.has(n.id)),removed=base.nodes.filter(n=>!fresh.has(n.id));
  for(const n of next.nodes)if(old.has(n.id)){
    requireValue(n.document===old.get(n.id).document&&stableJSON(n.text)===stableJSON(old.get(n.id).text),`Structure revision changes retained content: ${n.id}`);
  }
  for(const n of added)requireValue(n.text.every(s=>s.kind==='text'),'Structure revision may add plain-text documents and nodes only');
  for(const n of removed)requireValue(!n.document&&n.text.every(s=>s.kind==='text')&&!base.nodes.some(c=>c.parentId===n.id)&&!base.nodes.some(c=>c.text.some(s=>s.kind==='ref'&&s.targetId===n.id)),`Cannot archive non-leaf or referenced content: ${n.id}`);
  const moved=next.nodes.filter(n=>old.has(n.id)&&n.parentId!==old.get(n.id).parentId);
  return {added,removed,moved};
}

export async function restructureImport(adapter,plan,request,options={}){
  const info=await inspectPackage(plan),baseInfo=await inspectPackage(request.basePlan);
  requireValue(info.hash===request.packageHash&&baseInfo.hash===request.baseHash,'Structure package hash mismatch');
  const changes=planStructureChange(request.basePlan,plan),kbId=await adapter.kbId();
  requireValue(kbId===request.kbId,'Knowledge base changed before structure revision');
  const base=await adapter.load(baseInfo.hash);
  requireValue(base?.phase==='complete'&&base.kbId===kbId&&base.parentRemId===(request.parentRemId??null),'Base import must have completed exact readback in this destination');
  requireValue(request.archiveParentRemId&&await adapter.find(request.archiveParentRemId),'Recovery parent is required');
  requireValue(!Object.values(base.mapping).includes(request.archiveParentRemId),'Recovery parent must be outside the course subtree');
  let cp=await adapter.load(info.hash);
  if(!cp){
    const retained=new Set(['$root',...plan.nodes.map(n=>n.id)]);
    cp={version:1,hash:info.hash,kbId,parentRemId:base.parentRemId,phase:'restructure',mapping:Object.fromEntries(Object.entries(base.mapping).filter(([id])=>retained.has(id))),expected:Object.fromEntries(Object.entries(base.expected).filter(([id])=>retained.has(id))),created:0,written:0,verified:0,inFlight:null,restructure:{baseHash:baseInfo.hash,archiveParentRemId:request.archiveParentRemId,preflight:false,added:0,moved:0,archived:0,ordered:0,archiveRemId:null,complete:false}};
    await adapter.save(info.hash,cp);
  }
  const state=cp.restructure;
  const baseOwned=new Set(Object.values(base.mapping));
  requireValue(state?.baseHash===baseInfo.hash&&state.archiveParentRemId===request.archiveParentRemId&&cp.kbId===kbId&&cp.parentRemId===base.parentRemId,'Structure checkpoint identity mismatch');
  const emit=(phase,done,total)=>options.progress?.({phase,created:cp.created,written:cp.written,verified:cp.verified,total:plan.nodes.length+1,rootRemId:cp.mapping.$root,checked:done,resumeTotal:total});
  const guard=async()=>{
    requireValue(await adapter.kbId()===kbId,'Knowledge base changed during structure revision');
    if(options.shouldPause?.()){await adapter.save(info.hash,cp);return true;}return false;
  };
  const paused=()=>({status:'paused',...info,rootRemId:cp.mapping.$root});
  const mappedParent=(n,mapping)=>n.id==='$root'?base.parentRemId:n.parentId===null?mapping.$root:mapping[n.parentId];
  const owned=async(id,expectedHash,allowedParents)=>{
    const rem=await adapter.find(id);requireValue(rem,'Owned structure node is missing');
    requireValue(allowedParents.includes(rem.parent),'Owned structure node moved outside expected parents');
    requireValue(adapter.matchesExpected?await adapter.matchesExpected(rem.text??[],expectedHash):await sha256(await adapter.canonical(rem.text??[]))===expectedHash,'Owned structure node text was edited');return rem;
  };
  if(!state.preflight){
    const all=[root(request.basePlan),...request.basePlan.nodes],expectedChildren=new Map();
    for(const n of all.slice(1)){
      const parent=mappedParent(n,base.mapping);if(!expectedChildren.has(parent))expectedChildren.set(parent,[]);expectedChildren.get(parent).push(base.mapping[n.id]);
    }
    for(let start=0;start<all.length;start+=128){
      if(await guard())return paused();const rows=all.slice(start,start+128);
      const snapshots=adapter.findMany?await adapter.findMany(rows.map(n=>base.mapping[n.id])):await Promise.all(rows.map(n=>adapter.find(base.mapping[n.id])));
      const found=new Map(snapshots.map(r=>[r._id,r]));
      await boundedRead(rows,async n=>{
        const rem=found.get(base.mapping[n.id]);requireValue(rem,`Missing base node ${n.id}`);
        requireValue(rem.parent===mappedParent(n,base.mapping),`Base node was moved: ${n.id}`);
        requireValue(adapter.matchesExpected?await adapter.matchesExpected(rem.text??[],base.expected[n.id]):await sha256(await adapter.canonical(rem.text??[]))===base.expected[n.id],`Base node text was edited: ${n.id}`);
        requireValue(await adapter.isDocument(rem)===n.document,`Base document flag changed: ${n.id}`);
        requireValue(ownedChildren(await adapter.children(rem),expectedChildren.get(rem._id)??[],baseOwned,adapter.preserveExternalChildren)!==null,`Base children changed: ${n.id}`);
      },4);
      emit('structure-preflight',Math.min(start+128,all.length),all.length);
    }
    state.preflight=true;await adapter.save(info.hash,cp);
  }
  for(let start=state.added;start<changes.added.length;start+=16){
    if(await guard())return paused();const rows=changes.added.slice(start,start+16);
    await adapter.transaction(async()=>{for(const n of rows){
      const parent=mappedParent(n,cp.mapping),title=`RBI:${info.hash}:${n.id}`;
      let rem=cp.mapping[n.id]?await adapter.find(cp.mapping[n.id]):await adapter.findSentinel(title,parent);
      if(!rem)rem=await adapter.createSentinel(title,parent,n.document);rem=await adapter.find(rem._id);
      requireValue(rem&&rem.parent===parent&&await adapter.isDocument(rem)===n.document,'Added node identity mismatch');cp.mapping[n.id]=rem._id;
    }});
    // Mapping commits before final titles. A committed batch with failed storage
    // is recovered by exact sentinel; partial text commits accept identical text.
    await adapter.save(info.hash,cp);const prepared=[];
    for(const n of rows){const rich=await adapter.compile(n.text,cp.mapping,plan.assets??{});prepared.push({n,rich,expected:await adapter.canonical(rich)});}
    await adapter.transaction(async()=>{for(const {n,rich,expected} of prepared){
      const rem=await adapter.find(cp.mapping[n.id]),parent=mappedParent(n,cp.mapping),title=`RBI:${info.hash}:${n.id}`;requireValue(rem?.parent===parent,'New structure node moved');
      const actual=await adapter.canonical(rem.text??[]);requireValue(actual===expected||actual===await adapter.canonical([title]),'New structure node was edited');await adapter.setText(rem,rich);await adapter.disablePractice(rem);
    }});
    for(const {n,expected} of prepared)cp.expected[n.id]=await sha256(expected);
    state.added=start+rows.length;await adapter.save(info.hash,cp);emit('structure-documents',state.added,changes.added.length);
  }
  if(changes.removed.length&&!state.archiveRemId){
    const title=`RBI:${info.hash}:recovery`,parent=state.archiveParentRemId;
    let rem=await adapter.findSentinel(title,parent);if(!rem)rem=await adapter.createSentinel(title,parent,true);
    state.archiveRemId=rem._id;await adapter.save(info.hash,cp);
  }
  if(state.archiveRemId&&!state.archiveNamed){
    const rem=await adapter.find(state.archiveRemId),title=`RBI:${info.hash}:recovery`,text=['课程结构调整恢复资料'];
    requireValue(rem?.parent===state.archiveParentRemId,'Recovery document moved');
    const actual=await adapter.canonical(rem.text??[]);requireValue(actual===await adapter.canonical([title])||actual===await adapter.canonical(text),'Recovery document was edited');
    await adapter.setText(rem,text);state.archiveNamed=true;await adapter.save(info.hash,cp);
  }
  const children=new Map();for(const n of plan.nodes){const parent=mappedParent(n,cp.mapping);if(!children.has(parent))children.set(parent,[]);children.get(parent).push(cp.mapping[n.id]);}
  for(let i=state.moved;i<changes.moved.length;i++){
    if(await guard())return paused();const n=changes.moved[i],previous=request.basePlan.nodes.find(x=>x.id===n.id),parent=mappedParent(n,cp.mapping);
    const rem=await owned(cp.mapping[n.id],cp.expected[n.id],[mappedParent(previous,base.mapping),parent]);
    await adapter.move(rem,parent,children.get(parent).indexOf(rem._id));state.moved=i+1;await adapter.save(info.hash,cp);emit('structure-topics',state.moved,changes.moved.length);
  }
  for(let i=state.archived;i<changes.removed.length;i++){
    if(await guard())return paused();const n=changes.removed[i];
    const rem=await owned(base.mapping[n.id],base.expected[n.id],[mappedParent(n,base.mapping),state.archiveRemId]);
    await adapter.move(rem,state.archiveRemId,i);state.archived=i+1;await adapter.save(info.hash,cp);emit('structure-recovery',state.archived,changes.removed.length);
  }
  const sourceChildren=p=>{const index=new Map();for(const n of p.nodes){const parent=n.parentId??'$root';if(!index.has(parent))index.set(parent,[]);index.get(parent).push(n.id);}return index;};
  const before=sourceChildren(request.basePlan),after=sourceChildren(plan);
  const parents=[...new Set([...after.keys(),...before.keys()])].filter(id=>cp.mapping[id]&&stableJSON(before.get(id)??[])!==stableJSON(after.get(id)??[])).map(id=>cp.mapping[id]);
  const finalOwned=new Set(Object.values(cp.mapping));
  for(let start=state.ordered;start<parents.length;start+=16){
    if(await guard())return paused();const end=Math.min(start+16,parents.length);
    await adapter.transaction(async()=>{for(let i=start;i<end;i++){
    const parent=parents[i],wanted=children.get(parent)??[],rem=await adapter.find(parent);requireValue(rem,'Structure parent missing');
    const actual=await adapter.children(rem),actualOwned=adapter.preserveExternalChildren?actual.filter(id=>finalOwned.has(id)):actual;
    requireValue(actualOwned.length===wanted.length&&actualOwned.every(id=>wanted.includes(id)),'Unexpected owned children during structure ordering');
    const target=adapter.preserveExternalChildren?preserveExternalSlots(actual,wanted,finalOwned):wanted;
    const working=[...actual];
    if(stableJSON(actual)!==stableJSON(target))for(let position=0;position<target.length;position++){
      if(!finalOwned.has(target[position]))continue;
      if(working[position]===target[position])continue;
      const child=await adapter.find(target[position]);requireValue(child?.parent===parent,'Structure child moved while ordering');await adapter.move(child,parent,position);
      working.splice(working.indexOf(child._id),1);working.splice(position,0,child._id);
    }
    requireValue(stableJSON(working)===stableJSON(target),'Structure ordering did not converge');
    }});
    // Commit progress only after this small transaction. A partial native commit
    // is safely re-read on resume; already-correct positions are never moved again.
    state.ordered=end;await adapter.save(info.hash,cp);emit('structure-order',state.ordered,parents.length);
  }
  state.complete=true;cp.created=plan.nodes.length+1;cp.written=cp.created;cp.phase='write';await adapter.save(info.hash,cp);
  return await runImport(adapter,plan,request,options);
}
