import test from 'node:test';
import assert from 'node:assert/strict';
import {imageReadbackCompatibility} from '../src/rich-compat.mjs';
const asset={mime:'image/png',base64:'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',sha256:'fixture'};
const url=`data:${asset.mime};base64,${asset.base64}`;
const factory=(extra={})=>imageReadbackCompatibility({a:asset},{loadCached:async()=>null,verify:async()=>{},...extra});
test('only automatic zero-percent natural geometry is projected; source payload and other rich fields stay exact',async()=>{
  const original=['Text',{i:'x',text:'x^2',block:true},{i:'i',url,width:undefined,height:undefined}],actual=structuredClone(original);
  Object.assign(actual[2],{width:1,height:1,percent:0});
  assert.deepEqual(await factory().input(actual),original);assert.equal(actual[2].percent,0);
});
test('resized geometry or a changed source image is rejected, rather than silently accepted',async()=>{
  await assert.rejects(factory().input([{i:'i',url,width:2,height:1,percent:0}]),/differs from verified natural size/);
  await assert.rejects(factory().input([{i:'i',url:url+'changed'}]),/outside source assets/);
});
test('legacy builder undefined geometry survives absent JSON keys',async()=>{
  assert.deepEqual(await factory().input([{i:'i',url}]),[{i:'i',url,width:undefined,height:undefined}]);
});
test('managed images retain the parser metadata, verify real bytes once, and preserve explicit geometry',async()=>{
  let verified=0;const original={i:'i',url:'%LOCAL_FILE%test.png',width:80,height:60,title:'Source title'};
  const compatible=factory({loadCached:async()=>original,verify:async(id,locator)=>{assert.equal(id,'a');assert.equal(locator,original.url);verified++;}});
  assert.deepEqual(await compatible.input([{...original,percent:0}]),[original]);
  assert.deepEqual(await compatible.input([original]),[original]);assert.equal(verified,1);
  assert.deepEqual(await compatible.input([{...original,percent:50}]),[{...original,percent:50}]);
});
test('independent GIF geometry follows the same rule without PNG-specific dimensions',async()=>{
  const bytes=Uint8Array.from([71,73,70,56,57,97,32,0,48,0]),gif={mime:'image/gif',base64:btoa(String.fromCharCode(...bytes)),sha256:'gif'};
  const uri=`data:${gif.mime};base64,${gif.base64}`,c=imageReadbackCompatibility({g:gif},{loadCached:async()=>null,verify:async()=>{}});
  assert.deepEqual(await c.input([{i:'i',url:uri,width:32,height:48,percent:0}]),[{i:'i',url:uri,width:undefined,height:undefined}]);
});

test('new uploads register after the initial cache scan without weakening source verification',async()=>{
  const b={...asset,sha256:'independent'},first={i:'i',url:'%LOCAL_FILE%first.png'},later={i:'i',url:'%LOCAL_FILE%later.png',title:'Exact original'};
  const checked=[];let scans=0;
  const c=imageReadbackCompatibility({a:asset,b},{loadCached:async sha=>{scans++;return sha===asset.sha256?first:null;},verify:async(id,u)=>checked.push([id,u])});
  assert.deepEqual(await c.input([first]),[first]);assert.equal(scans,2);
  c.register('b',later);
  assert.deepEqual(await c.input([{...later,width:1,height:1,percent:0}]),[later]);
  assert.deepEqual(checked,[['a',first.url],['b',later.url]]);
  await assert.rejects(c.input([{i:'i',url:'%LOCAL_FILE%unknown.png'}]),/outside source/);
  assert.throws(()=>c.register('missing',later),/outside source/);
  assert.throws(()=>c.register('a',later),/different source bytes/);
  assert.equal(later.width,undefined);
});

test('registration never bypasses managed-file byte verification',async()=>{
  const c=factory({verify:async()=>{throw new Error('Actual bytes differ');}}),image={i:'i',url:'%LOCAL_FILE%wrong.png'};
  c.register('a',image);await assert.rejects(c.input([image]),/Actual bytes differ/);
});
