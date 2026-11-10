import {readFile,writeFile,mkdir} from 'node:fs/promises';
import path from 'node:path';
import {inspectNativePlan} from '../src/selective-native.mjs';
const argv=process.argv.slice(2),copy=argv.includes('--copy'),positional=argv.filter(x=>x!=='--copy');
const [sourceFolder,selectionFile,output,title,referenceFolder]=positional,selection=JSON.parse(await readFile(selectionFile,'utf8')),index=JSON.parse(await readFile(path.join(sourceFolder,'index.json'),'utf8'));
const map=new Map();for(const id of index.ids)map.set(id,JSON.parse(await readFile(path.join(sourceFolder,`${id}.json`),'utf8')));
// Context ancestors are copied without their unrelated branches. Selected trees
// remain native snapshots; this stage changes only destination parent selection.
const wanted=new Set(),excluded=new Set(selection.excludedSubtrees??[]);const take=id=>{if(wanted.has(id)||excluded.has(id))return;const n=map.get(id);if(!n)throw new Error(`Missing snapshot ${id}`);wanted.add(id);for(const child of n.children??[])if(index.full.includes(child))take(child);};
for(const id of selection.roots)take(id);
// A same-KB copy starts at precisely the selected roots. Cross-KB migrations
// retain their previous context-ancestor behavior.
if(!copy)for(const id of [...wanted]){let parent=map.get(id).parentId;while(parent){if(!map.has(parent))throw new Error(`Missing ancestor ${parent}`);wanted.add(parent);parent=map.get(parent).parentId;}}
const definitions=[];
for(const id of selection.referenceDefinitions??[]){if(wanted.has(id))continue;if(!referenceFolder)throw new Error('Reference definition snapshot folder is required');const n=JSON.parse(await readFile(path.join(referenceFolder,`${id}.json`),'utf8'));if(n.id!==id)throw new Error('Reference definition identity differs');map.set(id,n);definitions.push(id);wanted.add(id);}
const unresolved=new Set();for(const id of wanted){const n=map.get(id);for(const target of [...(n.refs??[]),...(n.tags??[]),...(n.sources??[]),...(n.portal??[])])if(!wanted.has(target))unresolved.add(target);}
if(unresolved.size){const deps=output+'.dependencies.json';await writeFile(deps,JSON.stringify({sourceKbId:index.kbId,ids:[...unresolved]},null,2));throw new Error(`Resolve ${unresolved.size} exact dependencies first: ${deps}`);}
const nodes=[],seen=new Set();const walk=id=>{if(seen.has(id)||!wanted.has(id))return;seen.add(id);const n=structuredClone(map.get(id));n.parentId=wanted.has(n.parentId)?n.parentId:null;nodes.push(n);for(const child of n.children??[])walk(child);};
for(const id of wanted)if(!definitions.includes(id)&&!wanted.has(map.get(id).parentId))walk(id);
if(definitions.length){const id='__selective_reference_definitions__';if(wanted.has(id))throw new Error('Generated reference container ID collision');nodes.push({id,parentId:null,text:['引用与标签'],backText:null,type:0,meta:{document:true},tags:[],sources:[],refs:[],aliases:[]});for(const id of definitions){const n=structuredClone(map.get(id));n.parentId='__selective_reference_definitions__';nodes.push(n);seen.add(id);}}
if(seen.size!==wanted.size||nodes.length!==wanted.size+(definitions.length?1:0))throw new Error('Snapshot hierarchy contains a cycle or disconnected nodes');
const plan={schemaVersion:1,...(copy?{operation:'copy'}:{}),title,sourceKbId:index.kbId,destinationKbId:copy?index.kbId:'6ade03fcad32f02e2a3f02e4',selectedRoots:selection.roots,nodes};
const info=inspectNativePlan(plan);await mkdir(path.dirname(output),{recursive:true});await writeFile(output,JSON.stringify(plan,null,2));
const counts={...info,selectedRoots:selection.roots.length,documents:nodes.filter(n=>n.meta.document).length,formulas:0,images:0,references:nodes.reduce((n,x)=>n+x.refs.length,0),tags:nodes.reduce((n,x)=>n+x.tags.length,0),aliases:nodes.reduce((n,x)=>n+x.aliases.length,0),portals:nodes.filter(n=>n.type===6).length};
const scan=v=>{if(Array.isArray(v))v.forEach(scan);else if(v&&typeof v==='object'){if(v.i==='i')counts.images++;if(v.i==='x')counts.formulas++;Object.values(v).forEach(scan);}};nodes.forEach(n=>{scan(n.text);scan(n.backText);});
await writeFile(output+'.audit.json',JSON.stringify(counts,null,2));console.log(JSON.stringify({output,...counts}));
