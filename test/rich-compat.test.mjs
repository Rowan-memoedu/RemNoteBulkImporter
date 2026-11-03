import test from 'node:test';
import assert from 'node:assert/strict';
import {imageReadbackCompatibility,automaticImageGeometry} from '../src/rich-compat.mjs';
import {imageTransportHashMatches} from '../src/rich-hash.mjs';
import {sha256,stableJSON} from '../src/package.mjs';
const asset={mime:'image/png',base64:'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',sha256:'fixture'};
const url=`data:${asset.mime};base64,${asset.base64}`;
const factory=(extra={})=>imageReadbackCompatibility({a:asset},{loadCached:async()=>null,verify:async()=>{},...extra});

test('automatic container fit retains exact source aspect ratio across independent window and indentation widths',()=>{
  assert.equal(automaticImageGeometry({width:900,height:562.5},{width:1600,height:1000}),true);
  assert.equal(automaticImageGeometry({width:900,height:150},{width:2400,height:400}),true);
  assert.equal(automaticImageGeometry({width:899,height:561.875},{width:1600,height:1000}),true);
  assert.equal(automaticImageGeometry({width:640,height:400},{width:1600,height:1000}),true);
  assert.equal(automaticImageGeometry({width:318,height:53},{width:2400,height:400}),true);
  assert.equal(automaticImageGeometry({width:900,height:563},{width:1600,height:1000}),false);
  assert.equal(automaticImageGeometry({width:900,height:900},{width:100,height:100}),false);
  assert.equal(automaticImageGeometry({width:0,height:0},{width:100,height:100}),false);
  assert.equal(automaticImageGeometry({width:NaN,height:100},{width:100,height:100}),false);
});
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

test('a cache gaining natural geometry can match only its original checkpoint states',async()=>{
  const original={i:'i',url:'%LOCAL_FILE%natural.png',title:'Exact title',percent:0};
  const actual={...original,width:1,height:1};let verified=0;
  const c=factory({loadCached:async()=>actual,verify:async()=>{verified++;}});
  const normalized=await c.input([actual]),variants=await c.automaticGeometryVariants(normalized);
  const expected=await sha256(stableJSON([original]));
  assert.equal(await imageTransportHashMatches(normalized,expected),false);
  assert.equal((await Promise.all(variants.map(v=>imageTransportHashMatches(v,expected)))).some(Boolean),true);
  const changed=await c.automaticGeometryVariants([{...actual,title:'Edited title'}]);
  assert.equal((await Promise.all(changed.map(v=>imageTransportHashMatches(v,expected)))).some(Boolean),false);
  assert.deepEqual(await c.automaticGeometryVariants([{...actual,width:2}]),[]);
  assert.deepEqual(await c.automaticGeometryVariants([{...actual,percent:50}]),[]);
  assert.equal(verified,1);assert.equal(actual.width,1);
});

test('raw natural geometry retains a zero-percent hash even if the cache omitted that field',async()=>{
  const cached={i:'i',url:'%LOCAL_FILE%automatic.png',title:'Diagram'};
  const raw={...cached,width:1,height:1,percent:0};
  const c=factory({loadCached:async()=>cached});
  const input=await c.input([raw]);assert.deepEqual(input,[cached]);
  const expected=await sha256(stableJSON([{...cached,percent:0}]));
  assert.equal(await imageTransportHashMatches(input,expected),false);
  const variants=await c.automaticGeometryVariants([raw]);
  assert.equal((await Promise.all(variants.map(v=>imageTransportHashMatches(v,expected)))).some(Boolean),true);
});
