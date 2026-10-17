import test from 'node:test';
import assert from 'node:assert/strict';
import {sdkMonitor} from '../src/sdk-monitor.mjs';

test('SDK monitor exposes pending call and clears it after success',async()=>{
  const m=sdkMonitor({timeoutMs:1000});let finish;
  const result=m.call('rem.findOne',()=>new Promise(resolve=>{finish=resolve;}));
  await Promise.resolve();assert.equal(m.snapshot().active[0].label,'rem.findOne');
  finish('value');assert.equal(await result,'value');
  assert.equal(m.snapshot().active.length,0);assert.equal(m.snapshot().lastCompleted.label,'rem.findOne');
  assert.equal(m.snapshot().restartRequired,false);
});
test('timeout fences further writes even if the pending request later completes',async()=>{
  const m=sdkMonitor({timeoutMs:15});let finish,writes=0;
  await assert.rejects(m.call('rem.setText',()=>new Promise(resolve=>{finish=resolve;})),/no automatic mutation retry/);
  assert.equal(m.snapshot().restartRequired,true);
  await assert.rejects(m.call('rem.setText',()=>{writes++;}),/requires reload/);
  finish();await Promise.resolve();assert.equal(writes,0);
  await assert.rejects(m.call('rem.setText',()=>{writes++;}),/requires reload/);
});
test('normal SDK rejection preserves the original error without fencing healthy calls',async()=>{
  const m=sdkMonitor();await assert.rejects(m.call('read',()=>{throw new Error('specific failure');}),/specific failure/);
  assert.equal(m.snapshot().restartRequired,false);assert.equal(await m.call('read',async()=>42),42);
});
