import test from 'node:test';
import assert from 'node:assert/strict';
import {boundedRead} from '../src/bounded-read.mjs';
test('read concurrency stays bounded and every input is checked exactly once',async()=>{
  let active=0,maximum=0;const seen=[];
  await boundedRead(Array.from({length:19},(_,i)=>i),async row=>{
    maximum=Math.max(maximum,++active);await new Promise(r=>setTimeout(r,2));seen.push(row);active--;
  },4);
  assert.equal(maximum,4);assert.equal(active,0);assert.deepEqual(seen.sort((a,b)=>a-b),Array.from({length:19},(_,i)=>i));
});
test('failed read stops new work and drains existing reads before rejection',async()=>{
  let active=0,started=0;
  await assert.rejects(boundedRead([0,1,2,3,4,5],async row=>{
    started++;active++;await new Promise(r=>setTimeout(r,row===0?1:8));active--;if(row===0)throw new Error('changed source');
  },3),/changed source/);
  assert.equal(active,0);assert.equal(started,3);
});
