import test from 'node:test';
import assert from 'node:assert/strict';
import {sdkTransaction} from '../src/sdk-transaction.mjs';

test('SDK transaction returns successful callback result',async()=>{
  assert.equal(await sdkTransaction(async fn=>await fn(),async()=>42),42);
});
test('callback failure reaches importer after host acknowledgement without rejecting inside host',async()=>{
  let acknowledged=false;
  const host=async fn=>{const result=await fn();acknowledged=true;return result;};
  await assert.rejects(sdkTransaction(host,async()=>{throw new Error('specific validation failure');}),/specific validation failure/);
  assert.equal(acknowledged,true);
});
test('SDK host errors remain visible independently of callback errors',async()=>{
  await assert.rejects(sdkTransaction(async()=>{throw new Error('host failure');},async()=>42),/host failure/);
});
