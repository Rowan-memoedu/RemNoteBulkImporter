import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,writeFile} from 'node:fs/promises';
import http from 'node:http';
import {WebSocket} from 'ws';
import {createService} from '../src/server.mjs';
import {VERSION} from '../src/version.mjs';

test('dual loopback bootstrap preserves opaque-sandbox authentication',async()=>{
 const root=await mkdtemp('D:/Artifacts/RemNoteBulkImporter-test-network-');
 await writeFile(root+'/index.html','<!doctype html><script>/* synthetic */</script>');
 const service=await createService({port:0,importRoot:root+'/packages',stateRoot:root+'/state',buildRoot:root});
 const get=(host,headers={})=>new Promise((resolve,reject)=>{
  http.get({host,port:service.port,path:'/index.html',headers,agent:false},res=>{
   let body='';res.on('data',x=>body+=x);res.on('end',()=>resolve({status:res.statusCode,body,headers:res.headers}));
  }).on('error',reject);
 });
 try{
  const ordinary=await get('127.0.0.1',{Origin:'null','Sec-Fetch-Dest':'empty','Sec-Fetch-Mode':'cors'});
  assert.ok(!ordinary.body.includes('__REMNOTE_TRANSPORT_TOKEN='));assert.equal(ordinary.headers['access-control-allow-origin'],undefined);
  const response=await get('::1',{'Sec-Fetch-Dest':'iframe','Sec-Fetch-Mode':'navigate'});
  assert.equal(response.status,200);assert.equal(response.headers['access-control-allow-origin'],undefined);
  assert.equal(response.headers['content-security-policy'],'frame-ancestors app://js https://www.remnote.com https://remnote.com');
  const token=JSON.parse(response.body.match(/__REMNOTE_TRANSPORT_TOKEN=([^;]+);/)[1]);
  for(const value of ['wrong',token]){
   const ws=new WebSocket(`ws://127.0.0.1:${service.port}/bridge`,{origin:'null'});
   await new Promise((resolve,reject)=>{ws.once('open',resolve);ws.once('error',reject);});
   if(value==='wrong'){
    const closed=new Promise(resolve=>ws.once('close',resolve));ws.send(JSON.stringify({type:'hello',pluginId:'remnote-bulk-importer',version:VERSION,token:value}));await closed;
   }else{
    ws.send(JSON.stringify({type:'hello',pluginId:'remnote-bulk-importer',version:VERSION,token:value}));
    const closed=new Promise(resolve=>ws.once('close',resolve));ws.close();await closed;
   }
  }
 }finally{await service.close();}
});
