import test from 'node:test';
import assert from 'node:assert/strict';
import os from 'node:os';
import path from 'node:path';
import {mkdtemp,mkdir,writeFile} from 'node:fs/promises';
import {WebSocket} from 'ws';
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StreamableHTTPClientTransport} from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import {createService} from '../src/server.mjs';
import {VERSION} from '../src/version.mjs';

test('older loaded plugin can report status but cannot receive a new or resumed import',async()=>{
  const root=await mkdtemp('D:/Artifacts/RemNoteBulkImporter-test-'),imports=path.join(root,'packages');
  await mkdir(imports);
  const file=path.join(imports,'canary.json');
  await writeFile(file,JSON.stringify({schemaVersion:1,packageId:'version.canary',title:'Version guard',nodes:[{id:'t',parentId:null,document:true,text:[{kind:'text',value:'Topic'}]}]}));
  const service=await createService({port:0,importRoot:imports,stateRoot:path.join(root,'state'),buildRoot:root});
  const base=`http://127.0.0.1:${service.port}`,client=new Client({name:'version-test',version:'1.0.0'});
  let socket,importsReceived=0;
  try{
    await client.connect(new StreamableHTTPClientTransport(new URL(`${base}/mcp`)));
    const prepared=await client.callTool({name:'bulk_import_prepare',arguments:{packagePath:file}});
    assert.ok(!prepared.isError);const job=prepared.structuredContent;
    socket=new WebSocket(`${base.replace('http','ws')}/bridge`,{origin:`http://localhost:${service.port}`});
    await new Promise((resolve,reject)=>{socket.once('open',resolve);socket.once('error',reject);});
    socket.on('message',raw=>{
      const m=JSON.parse(raw);
      if(m.type==='import')importsReceived++;
      if(m.type==='status')socket.send(JSON.stringify({type:'reply',id:m.id,result:{kbId:'fixture-kb',busy:false}}));
    });
    socket.send(JSON.stringify({type:'hello',pluginId:'remnote-bulk-importer',version:'0.1.0'}));
    const status=(await client.callTool({name:'bulk_import_status',arguments:{}})).structuredContent;
    assert.equal(status.plugin.version,'0.1.0');
    const rejected=await client.callTool({name:'bulk_import_start',arguments:{jobId:job.jobId}});
    assert.equal(rejected.isError,true);assert.match(rejected.content[0].text,/Reload/);
    assert.equal(importsReceived,0);
    assert.equal((await client.callTool({name:'bulk_import_job',arguments:{jobId:job.jobId}})).structuredContent.status,'prepared');
  }finally{socket?.close();await client.close();await service.close();}
});

test('real MCP transport supports preflight and one-job submission; blocks path/origin escape',async()=>{
  const root=await mkdtemp('D:/Artifacts/RemNoteBulkImporter-test-'),imports=path.join(root,'packages'),state=path.join(root,'state');
  await mkdir(imports);const plan={schemaVersion:1,packageId:'service.canary',title:'Transport canary',nodes:[{id:'t',parentId:null,document:true,text:[{kind:'text',value:'hello'}]}]};
  const file=path.join(imports,'canary.json');await writeFile(file,JSON.stringify(plan));
  const service=await createService({port:0,importRoot:imports,stateRoot:state,buildRoot:root});
  const base=`http://127.0.0.1:${service.port}`;
  const client=new Client({name:'integration-test',version:'1.0.0'});
  let socket;
  try{
    await client.connect(new StreamableHTTPClientTransport(new URL(`${base}/mcp`)));
    assert.equal((await client.listTools()).tools.length,5);
    assert.equal((await client.callTool({name:'bulk_import_status',arguments:{}})).structuredContent.connected,false);
    const invalid=await client.callTool({name:'bulk_import_prepare',arguments:{packagePath:path.join(imports,'..','outside.json')}});assert.equal(invalid.isError,true);
    const prepared=(await client.callTool({name:'bulk_import_prepare',arguments:{packagePath:file}})).structuredContent;assert.equal(prepared.status,'prepared');
    assert.equal((await fetch(`${base}/mcp`,{method:'POST',headers:{Origin:'https://untrusted.example'}})).status,403);
    socket=new WebSocket(`${base.replace('http','ws')}/bridge`,{origin:`http://localhost:${service.port}`});
    await new Promise((resolve,reject)=>{socket.once('open',resolve);socket.once('error',reject);});
    socket.send(JSON.stringify({type:'hello',pluginId:'remnote-bulk-importer',version:VERSION}));
    socket.on('message',raw=>{
      const m=JSON.parse(raw);
      if(m.type==='status')socket.send(JSON.stringify({type:'reply',id:m.id,result:{kbId:'fixture-kb',kbName:'Test',busy:false}}));
      if(m.type==='import'){
        socket.send(JSON.stringify({type:'reply',id:m.id,result:{accepted:true}}));
        setTimeout(()=>socket.send(JSON.stringify({type:'result',jobId:m.jobId,result:{status:'complete',verified:2,rootRemId:'test-root',mapping:{t:'topic'},nodes:1,documents:1,references:0,assets:0}})),30);
      }
    });
    const started=(await client.callTool({name:'bulk_import_start',arguments:{jobId:prepared.jobId}})).structuredContent;assert.ok(['running','complete'].includes(started.status));
    await new Promise(r=>setTimeout(r,80));
    const result=(await client.callTool({name:'bulk_import_job',arguments:{jobId:prepared.jobId}})).structuredContent;assert.equal(result.status,'complete');assert.equal(result.result.verified,2);
    assert.equal((await client.callTool({name:'bulk_import_start',arguments:{jobId:prepared.jobId}})).structuredContent.status,'complete');
    assert.ok(!JSON.stringify(result).includes('planPath'));
  }finally{socket?.close();await client.close();await service.close();}
});
