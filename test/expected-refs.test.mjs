import test from 'node:test';
import assert from 'node:assert/strict';
import {expectedReferenceTargets} from '../src/expected-refs.mjs';

test('mailto targets come from exact source compilation alongside explicit references',async()=>{
  const calls=[];
  const node={text:[{kind:'ref',targetId:'topic'},
    {kind:'markdown',value:'[Contact](mailto:fixture@example.org)'},
    {kind:'text',value:'mailto:literal@example.org'},
    {kind:'code',value:'mailto:code@example.org'}]};
  const got=await expectedReferenceTargets(node,{topic:'owned-topic'},{
    parse:async value=>{calls.push(value);return [{qId:'sdk-link'}];},
    refs:async rich=>rich.map(x=>x.qId),
  });
  assert.deepEqual(got,['owned-topic','sdk-link']);
  assert.deepEqual(calls,['[Contact](mailto:fixture@example.org)']);
});

test('unrelated markdown does not acquire implicit reference targets',async()=>{
  const got=await expectedReferenceTargets({text:[{kind:'markdown',value:'[Web](https://example.org)'}]}, {},{
    parse:async()=>{throw Error('Unexpected compile');},refs:async()=>{throw Error('Unexpected reference inference');},
  });
  assert.deepEqual(got,[]);
});
