import test from 'node:test';
import assert from 'node:assert/strict';
import {checkpointStore} from '../src/checkpoint.mjs';
const clone=x=>structuredClone(x);
function storage(){
  const data=new Map(),writes=[];let failMeta=false;
  return {data,writes,set failMeta(v){failMeta=v;},
    async getLocal(key){return clone(data.get(key));},
    async setLocal(key,value){if(failMeta&&key.endsWith(':meta')){failMeta=false;throw new Error('meta write failed');}writes.push({key,bytes:JSON.stringify(value).length});data.set(key,clone(value));}
  };
}
function state(n){return {version:1,hash:'h',kbId:'kb',created:n,written:0,phase:'create',mapping:Object.fromEntries(Array.from({length:n},(_,i)=>[`n${i}`,`r${i}`])),expected:{},inFlight:null};}

test('legacy checkpoint migrates without deleting the original and roundtrips all IDs',async()=>{
  const s=storage(),old=state(1500);s.data.set('rbi:kb:h',clone(old));
  const store=checkpointStore(s,'kb');assert.deepEqual(await store.load('h'),old);
  await store.save('h',old);assert.deepEqual(await checkpointStore(s,'kb').load('h'),old);
  assert.deepEqual(s.data.get('rbi:kb:h'),old);assert.equal(s.writes.length,7);
});
test('appending one batch changes only the tail page and small metadata',async()=>{
  const s=storage(),store=checkpointStore(s,'kb');await store.save('h',state(4096));s.writes.length=0;
  await store.save('h',state(4112));assert.equal(s.writes.length,2);
  assert.ok(s.writes.every(w=>w.bytes<2000));
  const cp=await store.load('h');assert.equal(Object.keys(cp.mapping).length,4112);
  s.writes.length=0;cp.phase='write';await store.save('h',cp);assert.equal(s.writes.length,1);assert.match(s.writes[0].key,/:meta$/);
});
test('failed metadata commit does not expose uncommitted mapping entries',async()=>{
  const s=storage(),store=checkpointStore(s,'kb');await store.save('h',state(15));
  s.failMeta=true;await assert.rejects(store.save('h',state(31)),/meta write/);
  assert.deepEqual(await checkpointStore(s,'kb').load('h'),state(15));
  await checkpointStore(s,'kb').save('h',state(31));assert.deepEqual(await checkpointStore(s,'kb').load('h'),state(31));
});
test('missing checkpoint pages and count truncation are rejected',async()=>{
  const s=storage(),store=checkpointStore(s,'kb');await store.save('h',state(300));
  await assert.rejects(store.save('h',state(200)),/truncation/);
  s.data.delete('rbi2:kb:h:mapping:1');await assert.rejects(checkpointStore(s,'kb').load('h'),/Missing mapping/);
});
