import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StreamableHTTPClientTransport} from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import path from 'node:path';
const [command,...args]=process.argv.slice(2),client=new Client({name:'selective-native-migration',version:'1.0.0'});
await client.connect(new StreamableHTTPClientTransport(new URL('http://127.0.0.1:43106/mcp')));
const call=async(name,input)=>{const r=await client.callTool({name,arguments:input},undefined,{timeout:150000});if(r.isError)throw new Error(r.content[0].text);return r.structuredContent??JSON.parse(r.content[0].text);};
try{
  if(command==='call'){console.log(JSON.stringify(await call(args[0],JSON.parse(args[1]??'{}')),null,2));}
  else if(command==='capture'){
    const [selectionFile,output]=args,input=JSON.parse(await readFile(selectionFile,'utf8')),selection=input.sourceKbId?{kbId:input.sourceKbId,roots:[],ancestors:input.ids}:input;
    await mkdir(output,{recursive:true});const snapshots=new Map(),full=new Set(),queue=selection.roots.map(id=>({id,full:true}));
    for(const id of selection.ancestors??[])queue.push({id,full:false});
    while(queue.length){
      const batch=[];while(queue.length&&batch.length<12){const item=queue.shift();if(snapshots.has(item.id)&&(!item.full||full.has(item.id)))continue;if(batch.some(x=>x.id===item.id)){queue.push(item);break;}batch.push(item);}
      if(!batch.length)continue;
      // A read batch uses full metadata even for context nodes; traversal remains selective.
      const result=await call('selective_native_read',{kbId:selection.kbId,remIds:batch.map(x=>x.id)});
      for(const n of result.nodes){const item=batch.find(x=>x.id===n.id);snapshots.set(n.id,n);await writeFile(path.join(output,`${n.id}.json`),JSON.stringify(n,null,2));if(n.parentId&&!snapshots.has(n.parentId))queue.push({id:n.parentId,full:false});if(item.full){full.add(n.id);const aliases=new Set(n.aliases.map(a=>a.id));for(const id of n.children)if(!aliases.has(id))queue.push({id,full:true});}}
      console.log(JSON.stringify({captured:snapshots.size,full:full.size,queued:queue.length}));
    }
    await writeFile(path.join(output,'index.json'),JSON.stringify({kbId:selection.kbId,roots:selection.roots,full:[...full],ids:[...snapshots.keys()]},null,2));
    console.log(JSON.stringify({status:'captured',nodes:snapshots.size,output}));
  }else if(command==='run'){
    const allowFolderDisplayDifference=args.includes('--allow-folder-display-difference');
    const [packagePath,phaseFilter,startOffset]=args.filter(x=>x!=='--allow-folder-display-difference'),prepared=await call('selective_native_prepare',{packagePath});
    const phases=phaseFilter?[phaseFilter]:['create','write','verify'];
    console.log(JSON.stringify({prepared}));
    for(const phase of phases)for(let offset=Number(startOffset??0);offset<prepared.nodes;offset+=8){const r=await call('selective_native_step',{jobId:prepared.jobId,phase,offset,limit:8,...(allowFolderDisplayDifference?{allowFolderDisplayDifference:true}:{})});console.log(JSON.stringify(r));}
  }else throw new Error('Usage: call <tool> <json> | capture <selection.json> <output-directory> | run <package.json> [phase] [offset]');
}finally{await client.close();}
