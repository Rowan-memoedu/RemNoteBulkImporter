import http from 'node:http';
import path from 'node:path';
import {readFile,writeFile,mkdir,rename,realpath,readdir} from 'node:fs/promises';
import {randomUUID} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {WebSocketServer,WebSocket} from 'ws';
import {McpServer} from '@modelcontextprotocol/sdk/server/mcp.js';
import {StreamableHTTPServerTransport} from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import {z} from 'zod';
import {inspectPackage} from './package.mjs';
import {VERSION} from './version.mjs';
import {managedMediaRoots,verifyManagedImage} from './media.mjs';
import {planStructureChange} from './restructure.mjs';
import {atomicJSON} from './atomic-json.mjs';

export async function createService({port=43106,buildRoot='D:/Artifacts/RemNoteBulkImporter/plugin',importRoot='D:/Artifacts/RemNoteBulkImporter/packages',stateRoot='D:/AppData/RemNoteBulkImporter'}={}) {
  for(const dir of [importRoot,stateRoot])await mkdir(dir,{recursive:true});
  let bridge=null,identity=null,active=null,activeAssets=null;
  const pending=new Map(),jobs=new Map();
  const atomic=atomicJSON;
  for(const name of await readdir(stateRoot))if(/^[a-f0-9]{64}\.job\.json$/.test(name)){
    const job=JSON.parse(await readFile(path.join(stateRoot,name),'utf8'));
    if(['running','starting'].includes(job.status))job.status='interrupted';jobs.set(job.jobId,job);
  }
  const jobFile=id=>path.join(stateRoot,`${id}.job.json`);
  const persist=job=>atomic(jobFile(job.jobId),job);
  const summary=job=>{const {planPath,result,mediaAudit,...rest}=job;return {...rest,verifiedManagedAssets:Object.keys(mediaAudit??{}).length,...(result?{result:{status:result.status,rootRemId:result.rootRemId,verified:result.verified,nodes:result.nodes,documents:result.documents,references:result.references,assets:result.assets}}:{})};};
  const rpc=(type,data={})=>new Promise((resolve,reject)=>{
    if(!bridge || bridge.readyState!==WebSocket.OPEN){reject(new Error('Bulk Importer plugin is not connected'));return;}
    const id=randomUUID(),timer=setTimeout(()=>{pending.delete(id);reject(new Error('Plugin reply timed out; inspect job before retrying'));},20000);
    pending.set(id,{resolve,reject,timer});bridge.send(JSON.stringify({type,id,...data}));
  });
  const status=async()=>({connected:!!bridge,plugin:identity,...(bridge?await rpc('status'):{}),activeJob:active});
  const prepare=async({packagePath})=>{
    const source=await realpath(packagePath),root=await realpath(importRoot),rel=path.relative(root,source);
    if(rel.startsWith('..')||path.isAbsolute(rel)||path.extname(source).toLowerCase()!=='.json')throw new Error('Package must be a JSON file inside the configured import directory');
    const text=await readFile(source,'utf8');if(Buffer.byteLength(text)>384*1024*1024)throw new Error('Package exceeds 384 MiB');
    const plan=JSON.parse(text),info=await inspectPackage(plan),old=jobs.get(info.hash);
    if(old)return summary(old);
    const planPath=path.join(stateRoot,`${info.hash}.package.json`);
    await atomic(planPath,plan);
    const job={jobId:info.hash,packageId:plan.packageId,title:plan.title,info,status:'prepared',planPath,createdAt:new Date().toISOString()};
    jobs.set(job.jobId,job);await persist(job);return summary(job);
  };
  const start=async({jobId,parentRemId=null})=>{
    const job=jobs.get(jobId);if(!job)throw new Error('Prepare package first');
    if(job.status==='complete')return summary(job);
    if(active)throw new Error(`Another import is active: ${active}`);
    if(identity?.version!==VERSION)throw new Error(`Reload the independent Bulk Importer plugin to ${VERSION} before resuming; existing checkpoint and nodes are retained`);
    const live=await rpc('status');if(live.busy)throw new Error('Plugin is busy finishing its previous task');
    if(live.diagnostics?.restartRequired)throw new Error('Reload plugin after its SDK timeout before resuming');
    if(job.kbId && (job.kbId!==live.kbId || job.parentRemId!==parentRemId))throw new Error('Cannot resume in a different knowledge base or destination');
    const plan=JSON.parse(await readFile(job.planPath,'utf8'));if((await inspectPackage(plan)).hash!==jobId)throw new Error('Prepared package changed');
    let revision={};
    if(job.restructureFrom){
      const base=jobs.get(job.restructureFrom);if(base?.status!=='complete')throw new Error('Base import must be complete before structure revision');
      const basePlan=JSON.parse(await readFile(base.planPath,'utf8'));planStructureChange(basePlan,plan);
      if(base.kbId!==live.kbId||base.parentRemId!==parentRemId)throw new Error('Structure base destination differs');
      revision={baseHash:base.jobId,basePlan,archiveParentRemId:job.archiveParentRemId};
    }
    job.kbId=live.kbId;job.parentRemId=parentRemId;job.status='starting';job.error=null;active=jobId;activeAssets=plan.assets??{};await persist(job);
    try {
      await rpc('import',{jobId,plan,request:{packageHash:jobId,kbId:live.kbId,parentRemId,...revision}});
      if(job.status==='starting')job.status='running';await persist(job);
    } catch(e){job.status='interrupted';job.error=String(e);active=null;await persist(job);throw e;}
    return summary(job);
  };
  const pause=async({jobId})=>{if(active!==jobId)throw new Error('Job is not active');bridge.send(JSON.stringify({type:'pause'}));return {jobId,status:'pause_requested'};};
  const restructure=async({baseJobId,packagePath,archiveParentRemId})=>{
    const base=jobs.get(baseJobId);if(base?.status!=='complete')throw new Error('Base import must complete full readback first');
    const prepared=await prepare({packagePath}),job=jobs.get(prepared.jobId);
    if(job.jobId===baseJobId)throw new Error('Structure revision must have a distinct package');
    if(job.restructureFrom&&(job.restructureFrom!==baseJobId||job.archiveParentRemId!==archiveParentRemId))throw new Error('Structure revision checkpoint differs');
    planStructureChange(JSON.parse(await readFile(base.planPath,'utf8')),JSON.parse(await readFile(job.planPath,'utf8')));
    job.restructureFrom=baseJobId;job.archiveParentRemId=archiveParentRemId;await persist(job);
    return start({jobId:job.jobId,parentRemId:base.parentRemId});
  };
  const toolResult=data=>({content:[{type:'text',text:JSON.stringify(data)}],structuredContent:data});
  const makeMcp=()=>{
    const mcp=new McpServer({name:'remnote-bulk-importer',version:VERSION});
    const register=(name,description,inputSchema,fn)=>mcp.registerTool(name,{description,inputSchema},async(args)=>{
      try{return toolResult(await fn(args));}catch(e){return {isError:true,content:[{type:'text',text:e instanceof Error?e.message:String(e)}]};}
    });
    register('bulk_import_status','Read plugin connection, current knowledge base and active import status.',{},status);
    register('bulk_import_prepare','Validate an entire source-neutral local package without RemNote writes; persist an immutable snapshot. Package path stays within the configured D: import directory.',{packagePath:z.string()},prepare);
    register('bulk_import_start','Submit a prepared package as one resumable import job. Creates only a new subtree; no deletion or existing-note replacement.',{jobId:z.string().regex(/^[a-f0-9]{64}$/),parentRemId:z.string().min(1).nullable().optional()},start);
    register('bulk_import_job','Read compact progress and final audit counts. Completion requires exact full readback.',{jobId:z.string().regex(/^[a-f0-9]{64}$/)},async({jobId})=>{const job=jobs.get(jobId);if(!job)throw new Error('Unknown job');return summary(job);});
    register('bulk_import_pause','Pause at the next safe batch boundary; resume with bulk_import_start.',{jobId:z.string()},pause);
    register('bulk_import_restructure','Reparent a completed owned import using an immutable structure-only package; preserve all retained Rem IDs, text, assets and references. Archive obsolete plain leaf metadata beneath an explicit recovery parent.',{baseJobId:z.string().regex(/^[a-f0-9]{64}$/),packagePath:z.string(),archiveParentRemId:z.string().min(1)},restructure);
    return mcp;
  };
  const server=http.createServer(async(req,res)=>{
    const host=req.headers.host;
    if(!host || !['127.0.0.1','localhost'].includes(host.split(':')[0])){res.writeHead(403).end();return;}
    const url=new URL(req.url,'http://localhost');
    if(url.pathname==='/mcp'){
      // MCP is for local clients. No browser CORS and no DNS-rebinding access.
      if(req.headers.origin){res.writeHead(403).end('Browser access to MCP is disabled');return;}
      if(req.method!=='POST'){res.writeHead(405).end();return;}
      const mcp=makeMcp(),transport=new StreamableHTTPServerTransport({sessionIdGenerator:undefined,enableJsonResponse:true});
      res.on('close',()=>{transport.close().catch(()=>{});mcp.close().catch(()=>{});});
      try{await mcp.connect(transport);await transport.handleRequest(req,res);}catch(e){if(!res.headersSent)res.writeHead(500).end('MCP transport error');}return;
    }
    if(url.pathname==='/health'){
      res.setHeader('Content-Type','application/json');res.end(JSON.stringify({service:'remnote-bulk-importer',version:VERSION,connected:!!bridge,activeJob:active}));return;
    }
    const file=({'/':'index.html','/index.html':'index.html','/index.js':'index.js','/index-sandbox.js':'index-sandbox.js','/manifest.json':'manifest.json'})[url.pathname];
    if(!file || !['GET','HEAD'].includes(req.method)){res.writeHead(404).end();return;}
    try{
      const data=await readFile(path.join(buildRoot,file));
      res.setHeader('Access-Control-Allow-Origin','*');res.setHeader('Cache-Control','no-store');
      res.setHeader('Content-Type',file.endsWith('.json')?'application/json':file.endsWith('.js')?'text/javascript':'text/html');
      res.end(req.method==='HEAD'?undefined:data);
    }catch{res.writeHead(503).end('Build plugin before loading it');}
  });
  const wss=new WebSocketServer({noServer:true,maxPayload:384*1024*1024});
  server.on('upgrade',(req,socket,head)=>{
    const actualPort=server.address().port;
    const origins=new Set([`http://localhost:${actualPort}`,`http://127.0.0.1:${actualPort}`,'https://www.remnote.com','https://remnote.com','https://plugins.remnote.com','https://beta.remnote.com']);
    if(req.url!=='/bridge'||!origins.has(req.headers.origin)||bridge){socket.write('HTTP/1.1 403 Forbidden\r\n\r\n');socket.destroy();return;}
    wss.handleUpgrade(req,socket,head,ws=>wss.emit('connection',ws,req));
  });
  wss.on('connection',socket=>{
    bridge=socket;let greeted=false;
    const helloTimer=setTimeout(()=>{if(!greeted)socket.close(1008,'Missing hello');},5000);
    let queued=Promise.resolve();
    socket.on('message',raw=>{
      queued=queued.then(async()=>{
        const m=JSON.parse(raw.toString());
        if(!greeted){if(m.type!=='hello'||m.pluginId!=='remnote-bulk-importer'||!['0.1.0','0.1.1','0.1.2','0.1.3','0.1.4','0.1.5','0.1.6','0.1.7',VERSION].includes(m.version))throw new Error('Incompatible plugin');greeted=true;clearTimeout(helloTimer);identity={id:m.pluginId,version:m.version};return;}
        if(m.type==='reply'){
          const entry=pending.get(m.id);if(entry){clearTimeout(entry.timer);pending.delete(m.id);m.error?entry.reject(new Error(m.error)):entry.resolve(m.result);}return;
        }
        const job=jobs.get(m.jobId);if(!job||active!==m.jobId)return;
        if(m.type==='media-verify'){
          try{
            const asset=activeAssets?.[m.assetId];if(!asset)throw new Error('Image is outside active package');
            const result=await verifyManagedImage(m.url,asset,await managedMediaRoots());
            job.mediaAudit??={};job.mediaAudit[m.assetId]={url:m.url,...result};await persist(job);
            socket.send(JSON.stringify({type:'media-reply',id:m.id,result}));
          }catch(error){socket.send(JSON.stringify({type:'media-reply',id:m.id,error:error.message}));}return;
        }
        if(m.type==='progress'){job.progress={phase:m.phase,created:m.created,written:m.written,verified:m.verified,total:m.total,rootRemId:m.rootRemId,...(m.checked!==undefined?{checked:m.checked,resumeTotal:m.resumeTotal}:{})};}
        else if(m.type==='result'){
          // Only an engine result after full audit can be complete.
          if(!['complete','paused'].includes(m.result?.status))throw new Error('Invalid result status');
          if(m.result.status==='complete' && m.result.verified!==job.info.nodes+1)throw new Error('Incomplete audit result');
          job.result=m.result;job.status=m.result.status;active=null;
          await atomic(path.join(stateRoot,`${job.jobId}.result.json`),m.result);
        }else if(m.type==='failure'){job.status='failed';job.error=m.error;active=null;}
        job.updatedAt=new Date().toISOString();await persist(job);
      }).catch(error=>{console.error('Bridge message rejected:',error.message);socket.close(1008,'Invalid bridge message');});
    });
    socket.on('close',()=>{
      clearTimeout(helloTimer);if(bridge===socket){bridge=null;identity=null;}
      for(const p of pending.values()){clearTimeout(p.timer);p.reject(new Error('Plugin disconnected'));}pending.clear();
      if(active){const job=jobs.get(active);job.status='interrupted';job.error='Plugin disconnected; resume the same immutable package';job.updatedAt=new Date().toISOString();active=null;persist(job).catch(()=>{});}
    });
  });
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(port,'127.0.0.1',resolve);});
  return {port:server.address().port,jobs,close:async()=>{bridge?.close();wss.close();await new Promise(r=>server.close(r));}};
}

if(process.argv[1] && fileURLToPath(import.meta.url)===path.resolve(process.argv[1])){
  const service=await createService();console.log(JSON.stringify({service:'RemNoteBulkImporter',port:service.port,mcp:'http://127.0.0.1:43106/mcp',plugin:'http://localhost:43106',state:'D:/AppData/RemNoteBulkImporter'}));
  const shutdown=async()=>{await service.close();process.exit(0);};process.on('SIGINT',shutdown);process.on('SIGTERM',shutdown);
}
