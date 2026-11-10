// Selective SDK snapshots and create-only native copies. No database access,
// global enumeration, export file, history migration, or existing-note writes.
import {stableJSON} from './package.mjs';
import {sdkTransaction} from './sdk-transaction.mjs';

export const SELECTIVE_PROTOCOL=7;
const metadata=[['document','isDocument','setIsDocument'],['folder','isFolder','setIsFolder'],['listItem','isListItem','setIsListItem'],['cardItem','isCardItem','setIsCardItem'],['quote','isQuote','setIsQuote'],['code','isCode','setIsCode'],['todo','isTodo','setIsTodo'],['fontSize','getFontSize','setFontSize'],['highlight','getHighlightColor','setHighlightColor'],['practice','getEnablePractice','setEnablePractice'],['direction','getPracticeDirection','setPracticeDirection']];
const clone=value=>JSON.parse(JSON.stringify(value));
export const canonicalRemType=value=>value===undefined||value===null||value==='DEFAULT_TYPE'?0:value;
export function remapRich(value,mapping){
  if(Array.isArray(value))return value.map(v=>remapRich(v,mapping));
  if(!value||typeof value!=='object')return value;
  const out={};
  for(const [k,v] of Object.entries(value)){
    const reference=(k==='_id'&&['q','g'].includes(value.i))||['aliasId','qId','linkedRemId'].includes(k);
    out[k]=reference&&typeof v==='string'&&mapping[v]?mapping[v]:remapRich(v,mapping);
  }
  return out;
}
export function sdkPortableRich(value){
  if(Array.isArray(value))return value.map(sdkPortableRich);
  if(!value||typeof value!=='object')return value;
  const out=Object.fromEntries(Object.entries(value).map(([k,v])=>[k,sdkPortableRich(v)]));
  if(out.i==='i'){
    // Existing RemNote images permit fractional viewport percentages, but the
    // public SDK accepts only these discrete tokens. Keep exact pixel geometry
    // and the same managed asset. Upload-device telemetry stays in the source
    // snapshot, not the copied content.
    if(out.percent!==undefined&&![5,25,50,100].includes(out.percent)){
      if(!Number.isFinite(out.width)||out.width<=0||!Number.isFinite(out.height)||out.height<=0)throw new Error('Cannot preserve image geometry through the public SDK');
      delete out.percent;
    }
    delete out.uploadDevice;
  }
  return out;
}
export function inspectNativePlan(plan){
  if(plan.schemaVersion!==1||!plan.sourceKbId||!plan.destinationKbId||!plan.title||!Array.isArray(plan.nodes)||!plan.nodes.length)throw new Error('Invalid selective migration package');
  if(plan.operation!==undefined&&!['copy','migrate'].includes(plan.operation))throw new Error('Invalid selective operation');
  if(plan.sourceKbId===plan.destinationKbId&&plan.operation!=='copy')throw new Error('Same-KB plans require an explicit copy operation');
  const seen=new Set(),all=new Set(plan.nodes.map(n=>n.id));
  if(all.size!==plan.nodes.length)throw new Error('Duplicate source IDs');
  for(const n of plan.nodes){
    if(!n.id||!Array.isArray(n.text)||!n.meta)throw new Error('Missing native node fields');
    if(n.parentId&&!seen.has(n.parentId))throw new Error('Parents must precede children');
    if(![0,1,2,6].includes(n.type))throw new Error(`Unsupported native Rem type ${n.type}`);
    for(const target of [...(n.refs??[]),...(n.tags??[]),...(n.sources??[]),...(n.portal??[])])if(!all.has(target))throw new Error(`Unmapped dependency ${target} in ${n.id}`);
    if(n.type===6&&n.portalType!==0)throw new Error('Only ordinary portals are supported');
    seen.add(n.id);
  }
  return {nodes:seen.size,sourceKbId:plan.sourceKbId,destinationKbId:plan.destinationKbId};
}
export async function snapshotNative(plugin,{kbId,remIds,shallow=false},monitor){
  const call=monitor.call,live=await call('selective.kb',()=>plugin.kb.getCurrentKnowledgeBaseData());
  if(live._id!==kbId)throw new Error('Source KB identity differs');
  if(!Array.isArray(remIds)||remIds.length>24||!remIds.length)throw new Error('Read 1-24 exact Rem IDs');
  const nodes=[];
  for(const id of remIds){
    const r=await call('selective.find',()=>plugin.rem.findOne(id));if(!r)throw new Error(`Source Rem missing: ${id}`);
    const meta={};
    const getters=shallow?metadata.filter(([k])=>['document','folder'].includes(k)):metadata;
    await Promise.all(getters.map(async([key,get])=>{meta[key]=(await call(`selective.${get}`,()=>r[get]()))??null;}));
    if(!shallow&&meta.todo)meta.todoStatus=(await call('selective.todoStatus',()=>r.getTodoStatus()))??null;
    const tags=shallow?[]:await call('selective.tags',()=>r.getTagRems());
    const userTags=[];for(const tag of tags)if(!await call('selective.isPowerup',()=>tag.isPowerup()))userTags.push(tag._id);
    const sources=shallow?[]:await call('selective.sources',()=>r.getSources());
    const refs=await call('selective.references',()=>r.remsBeingReferenced());
    const aliases=shallow?[]:await call('selective.aliases',()=>r.getAliases());
    const children=await call('selective.children',()=>r.getChildrenRem());
    const type=canonicalRemType(r.type??(await call('selective.getType',()=>r.getType())));
    const node={id:r._id,parentId:r.parent??null,children:children.map(x=>x._id),text:r.text??[],backText:r.backText??null,type,updatedAt:r.updatedAt,meta,tags:userTags,sources:sources.map(x=>x._id),refs:refs.map(x=>x._id),aliases:aliases.map(x=>({id:x._id,text:x.text??[]}))};
    if(type===6){node.portalType=await call('selective.portalType',()=>r.getPortalType());node.portal=(await call('selective.portal',()=>r.getPortalDirectlyIncludedRem())).map(x=>x._id);}
    nodes.push(clone(node));
  }
  if((await call('selective.kb',()=>plugin.kb.getCurrentKnowledgeBaseData()))._id!==kbId)throw new Error('KB changed during snapshot');
  return {protocol:SELECTIVE_PROTOCOL,kbId,nodes};
}
export async function copyNativeBatch(plugin,request,monitor){
  const {kbId,jobId,title,phase,nodes,mapping:incoming={},allNodes=[],allowFolderDisplayDifference=false}=request,call=monitor.call;
  if(!/^[a-f0-9]{64}$/.test(jobId)||!Array.isArray(nodes)||nodes.length>12)throw new Error('Invalid selective copy request');
  if((await call('selective.kb',()=>plugin.kb.getCurrentKnowledgeBaseData()))._id!==kbId)throw new Error('Destination KB identity differs');
  const prefix=`selective-v1:${kbId}:${jobId}:`,mapping={...incoming};
  const load=id=>call('selective.checkpoint.read',()=>plugin.storage.getLocal(prefix+id));
  const save=(id,value)=>call('selective.checkpoint.save',()=>plugin.storage.setLocal(prefix+id,value));
  const get=id=>call('selective.find',()=>plugin.rem.findOne(id));
  const create=async(id,parent,isPortal=false)=>{
    const saved=await load(id);if(saved){const existing=await get(saved);if(!existing||existing.parent!==parent)throw new Error('Owned migration Rem missing or moved');return saved;}
    const sentinel=`__selective_${jobId}_${id}__`;
    let rem=await call('selective.sentinel',()=>plugin.rem.findByName([sentinel],parent));
    if(!rem)await call('selective.createTransaction',()=>sdkTransaction(fn=>plugin.app.transaction(fn),async()=>{
      rem=await call('selective.create',()=>isPortal?plugin.rem.createPortal():plugin.rem.createRem());if(!rem)throw new Error('SDK returned no new Rem');
      await call('selective.sentinelText',()=>rem.setText([sentinel]));
      const p=parent?await get(parent):null,position=p?(await call('selective.parentChildren',()=>p.getChildrenRem())).length:undefined;
      await call('selective.parent',()=>rem.setParent(parent,position));
    }),180000);
    await save(id,rem._id);return rem._id;
  };
  let rootId=await load('$root');
  if(!rootId){if(phase!=='create')throw new Error('Create migration root first');rootId=await create('$root',null);}
  const root=await get(rootId);if(!root||root.parent!==null)throw new Error('Owned root missing or moved');
  if(phase==='create'){
    const current=stableJSON(root.text??[]),expected=stableJSON([title]),sentinel=stableJSON([`__selective_${jobId}_$root__`]);
    if(current!==expected&&current!==sentinel)throw new Error('Owned root title was edited');
    await call('selective.rootText',()=>root.setText([title]));await call('selective.rootDocument',()=>root.setIsDocument(true));
    for(const n of nodes){const parent=n.parentId?mapping[n.parentId]:rootId;if(!parent)throw new Error('Parent not allocated');mapping[n.id]=await create(n.id,parent,n.type===6);}
    return {rootId,mapping,phase,count:nodes.length};
  }
  const diagnostics=[];
  for(const n of nodes){
    const owned=await load(n.id);if(!owned||mapping[n.id]!==owned)throw new Error('Rem is not owned by this migration');
    const r=await get(owned),parent=n.parentId?mapping[n.parentId]:rootId;
    if(!r||r.parent!==parent)throw new Error('Owned Rem missing or reparented');
    const text=sdkPortableRich(remapRich(n.text,mapping)),back=n.backText===null?undefined:sdkPortableRich(remapRich(n.backText,mapping));
    if(phase==='write'){
      const prev=await load(`written:${n.id}`),actual=stableJSON([r.text??[],r.backText??null]);
      const sentinel=stableJSON([[`__selective_${jobId}_${n.id}__`],null]),desired=stableJSON([text,back??null]);
      if(actual!==desired&&actual!==sentinel&&actual!==prev)throw new Error(`Owned content changed: ${n.id}`);
      await call('selective.text',()=>r.setText(text));
      if(back!==undefined)await call('selective.backText',()=>r.setBackText(back));
      // The live SDK validator represents the default enum by its string token,
      // although the published TypeScript enum declares numeric zero.
      if(n.type!==6)await call('selective.type',()=>r.setType(n.type===0?'DEFAULT_TYPE':n.type));
      // Explicit false values matter: setting document status can enable the
      // folder flag on the live host. Restore the entire declared flag set.
      for(const [key,,set] of metadata)if(n.meta[key]!==undefined&&n.meta[key]!==null&&!(key==='folder'&&allowFolderDisplayDifference))await call(`selective.${set}`,()=>r[set](n.meta[key]));
      if(n.meta.todoStatus)await call('selective.todoStatus',()=>r.setTodoStatus(n.meta.todoStatus));
      for(const id of n.tags??[])await call('selective.tag',()=>r.addTag(mapping[id]));
      for(const id of n.sources??[])await call('selective.source',()=>r.addSource(mapping[id]));
      for(const id of n.portal??[])await call('selective.portal',async()=>{const target=await get(mapping[id]);await target.addToPortal(r);});
      for(const a of n.aliases??[]){const alias=await call('selective.alias',()=>r.getOrCreateAliasWithText(remapRich(a.text,mapping)));if(alias)mapping[a.id]=alias._id;}
      await save(`written:${n.id}`,desired);
    }else if(phase==='verify'){
      if(stableJSON(r.text??[])!==stableJSON(text)||stableJSON(r.backText??null)!==stableJSON(back??null))throw new Error(`Native content verification failed: ${n.id}`);
      if(canonicalRemType(r.type??(await call('selective.verify.type',()=>r.getType())))!==n.type)throw new Error(`Rem type differs: ${n.id}`);
      const acceptedDifferences=[];
      for(const [key,get] of metadata){if(n.meta[key]===undefined)continue;const value=(await call(`selective.verify.${get}`,()=>r[get]()))??null;if(value!==n.meta[key]){if(key==='folder'&&allowFolderDisplayDifference)acceptedDifferences.push({field:key,source:n.meta[key],destination:value});else throw new Error(`Metadata ${key} differs: ${n.id}: ${JSON.stringify(value)} != ${JSON.stringify(n.meta[key])}`);}}
      const children=(await call('selective.verify.children',()=>r.getChildrenRem())).map(x=>x._id);
      const expected=allNodes.filter(x=>x.parentId===n.id).map(x=>mapping[x.id]);
      // Alias nodes are created by the official alias API, outside visible content order.
      const aliasIds=(await call('selective.verify.aliases',()=>r.getAliases())).map(x=>x._id);
      if(stableJSON(children.filter(id=>!aliasIds.includes(id)))!==stableJSON(expected.filter(id=>!aliasIds.includes(id))))throw new Error(`Child order differs: ${n.id}`);
      const tags=await call('selective.verify.tags',()=>r.getTagRems());for(const id of n.tags??[])if(!tags.some(t=>t._id===mapping[id]))throw new Error(`Missing migrated tag: ${n.id}`);
      const sources=await call('selective.verify.sources',()=>r.getSources());for(const id of n.sources??[])if(!sources.some(t=>t._id===mapping[id]))throw new Error(`Missing migrated source: ${n.id}`);
      if(n.type===6){const targets=(await call('selective.verify.portal',()=>r.getPortalDirectlyIncludedRem())).map(x=>x._id);if(stableJSON(targets)!==stableJSON((n.portal??[]).map(id=>mapping[id]))||await call('selective.verify.portalType',()=>r.getPortalType())!==n.portalType)throw new Error('Portal differs');}
      diagnostics.push({sourceId:n.id,remId:r._id,verified:true,acceptedDifferences});
    }else throw new Error('Unknown migration phase');
  }
  if((await call('selective.kb',()=>plugin.kb.getCurrentKnowledgeBaseData()))._id!==kbId)throw new Error('KB changed during migration');
  return {rootId,mapping,phase,count:nodes.length,diagnostics};
}
