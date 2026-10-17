import test from 'node:test';
import assert from 'node:assert/strict';
import {atomicJSON} from '../src/atomic-json.mjs';
test('transient Windows sharing conflicts retry rename without rewriting/truncating destination',async()=>{
  let writes=0,renames=0;const waits=[];
  await atomicJSON('checkpoint.json',{progress:16},{write:async(file,text)=>{writes++;assert.match(file,/checkpoint\.json\..+\.tmp$/);assert.equal(text,'{"progress":16}');},replace:async()=>{if(++renames<4)throw Object.assign(new Error('sharing'),{code:'EPERM'});},wait:async ms=>{waits.push(ms);}});
  assert.equal(writes,1);assert.equal(renames,4);assert.deepEqual(waits,[25,50,100]);
});
test('permanent and exhausted rename errors remain explicit, without destructive fallback',async()=>{
  let attempts=0;const options={write:async()=>{},replace:async()=>{attempts++;throw Object.assign(new Error('full'),{code:'ENOSPC'});},wait:async()=>assert.fail('not transient')};
  await assert.rejects(atomicJSON('state.json',{},options),/full/);assert.equal(attempts,1);
  attempts=0;options.replace=async()=>{attempts++;throw Object.assign(new Error('locked'),{code:'EBUSY'});};options.wait=async()=>{};
  await assert.rejects(atomicJSON('state.json',{},options),/locked/);assert.equal(attempts,8);
});
