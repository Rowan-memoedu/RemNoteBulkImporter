import path from 'node:path';
import {readFile,realpath} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {atomicJSON} from './atomic-json.mjs';
import {inspectNativePlan} from './selective-native.mjs';
import {stableJSON} from './package.mjs';

export function selectiveTools({rpc,importRoot,stateRoot,isIdle}){
  const prepare=async({packagePath})=>{
    const source=await realpath(packagePath),rel=path.relative(await realpath(importRoot),source);
    if(rel.startsWith('..')||path.isAbsolute(rel)||!source.endsWith('.json'))throw new Error('Package outside import root');
    const bytes=await readFile(source);if(bytes.length>64*1024*1024)throw new Error('Selective package too large');
    const plan=JSON.parse(bytes),info=inspectNativePlan(plan),jobId=createHash('sha256').update(stableJSON(plan)).digest('hex');
    await atomicJSON(path.join(stateRoot,`${jobId}.selective-package.json`),plan);
    return {jobId,...info};
  };
  const ready=async()=>{if(!isIdle())throw new Error('Importer is busy');const live=await rpc('status');if(live.busy||live.diagnostics?.restartRequired)throw new Error('Plugin is busy or fenced');if(live.selectiveProtocol!==7)throw new Error('Reload the selective migration plugin before use');return live;};
  const read=async(args)=>{await ready();return rpc('selective-read',args,120000);};
  const step=async({jobId,phase,offset=0,limit=8,allowFolderDisplayDifference})=>{
    await ready();
    if(!/^[a-f0-9]{64}$/.test(jobId)||!['create','write','verify'].includes(phase)||!Number.isInteger(offset)||offset<0||!Number.isInteger(limit)||limit<1||limit>12)throw new Error('Invalid step');
    const plan=JSON.parse(await readFile(path.join(stateRoot,`${jobId}.selective-package.json`),'utf8'));inspectNativePlan(plan);
    if(createHash('sha256').update(stableJSON(plan)).digest('hex')!==jobId)throw new Error('Immutable native snapshot changed');
    const checkpoint=path.join(stateRoot,`${jobId}.selective-state.json`);
    let state={mapping:{},done:{create:[],write:[],verify:[]}};
    try{state=JSON.parse(await readFile(checkpoint,'utf8'));}catch(e){if(e.code!=='ENOENT')throw e;}
    if(allowFolderDisplayDifference!==undefined){if(typeof allowFolderDisplayDifference!=='boolean')throw new Error('Invalid folder-display policy');state.policy={...state.policy,allowFolderDisplayDifference};}
    const nodes=plan.nodes.slice(offset,offset+limit);
    if(phase!=='create'&&Object.keys(state.mapping).length<plan.nodes.length)throw new Error('Allocate all native nodes before writing or verifying');
    if(phase==='verify'&&state.done.write.length<plan.nodes.length)throw new Error('Write all nodes before final verification');
    if(phase==='write'){const rewritten=new Set(nodes.map(n=>n.id));state.done.verify=state.done.verify.filter(id=>!rewritten.has(id));state.complete=false;await atomicJSON(checkpoint,state);}
    const result=await rpc('selective-copy',{kbId:plan.destinationKbId,jobId,title:plan.title,phase,nodes,mapping:state.mapping,allowFolderDisplayDifference:state.policy?.allowFolderDisplayDifference===true,allNodes:phase==='verify'?plan.nodes.map(n=>({id:n.id,parentId:n.parentId})):[]},120000);
    state.mapping=result.mapping;state.rootId=result.rootId;state.done[phase]=[...new Set([...state.done[phase],...nodes.map(n=>n.id)])];
    state.updatedAt=new Date().toISOString();state.complete=state.done.verify.length===plan.nodes.length;
    state.acceptedDifferences??={};for(const d of result.diagnostics??[])if(d.acceptedDifferences?.length)state.acceptedDifferences[d.sourceId]=d.acceptedDifferences;
    await atomicJSON(checkpoint,state);
    return {jobId,phase,offset,count:result.count,total:plan.nodes.length,rootId:state.rootId,done:{create:state.done.create.length,write:state.done.write.length,verify:state.done.verify.length},acceptedFolderDisplayDifferences:Object.keys(state.acceptedDifferences).length,complete:state.complete};
  };
  return {prepare,read,step};
}
