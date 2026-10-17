import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {nativeImage} from '../src/native-image.mjs';
import {verifyManagedImage} from '../src/media.mjs';

test('official upload path retains complete native metadata and verifies cached bytes before reuse',async()=>{
  const data=new Map();let parses=0,verified=0;
  const image={i:'i',url:'%LOCAL_FILE%test.png',width:160,height:96,title:'original'},asset={sha256:'a'.repeat(64),mime:'image/png',base64:'AAAA'};
  const dependencies={get:async k=>data.get(k),set:async(k,v)=>data.set(k,v),parse:async markdown=>{parses++;assert.match(markdown,/data:image\/png;base64,AAAA/);return ['',image];},verify:async()=>{verified++;}};
  assert.deepEqual(await nativeImage('asset',asset,dependencies),image);
  assert.deepEqual(await nativeImage('asset',asset,dependencies),image);assert.equal(parses,1);assert.equal(verified,2);
  dependencies.verify=async()=>{throw new Error('bytes differ');};await assert.rejects(nativeImage('asset',asset,dependencies),/bytes differ/);
});
test('embedded or multiple parser results never become accepted managed assets',async()=>{
  const d={get:async()=>null,set:async()=>assert.fail('must not save'),verify:async()=>assert.fail('must not verify'),parse:async()=>[{i:'i',url:'data:image/png;base64,AAAA'}]};
  await assert.rejects(nativeImage('a',{sha256:'h',mime:'image/png',base64:'AAAA'},d),/one managed local image/);
  d.parse=async()=>[{i:'i',url:'%LOCAL_FILE%a.png'},{i:'i',url:'%LOCAL_FILE%b.png'}];
  await assert.rejects(nativeImage('a',{sha256:'h',mime:'image/png',base64:'AAAA'},d),/one managed local image/);
});
test('managed media verification is byte-exact and rejects traversal and corrupt files',async()=>{
  const root=await mkdtemp('D:/Artifacts/RemNoteBulkImporter-media-test-'),bytes=Buffer.from('89504e470d0a1a0a','hex');
  await writeFile(root+'/file.png',bytes);const asset={sha256:createHash('sha256').update(bytes).digest('hex'),mime:'image/png'};
  assert.equal((await verifyManagedImage('%LOCAL_FILE%file.png',asset,[root])).sha256,asset.sha256);
  for(const locator of ['%LOCAL_FILE%../file.png','%LOCAL_FILE%..%2ffile.png','file:///file.png'])await assert.rejects(verifyManagedImage(locator,asset,[root]));
  await assert.rejects(verifyManagedImage('%LOCAL_FILE%file.png',{...asset,sha256:'f'.repeat(64)},[root]),/bytes differ/);
});
