import test from 'node:test';
import assert from 'node:assert/strict';
import {ownedChildren,preserveExternalSlots} from '../src/owned-children.mjs';
test('external additions are preserved but misplaced or missing owned Rems never pass',()=>{
  const owned=new Set(['a','b','elsewhere']);
  assert.deepEqual(ownedChildren(['a','portal','b'],['a','b'],owned,true),['portal']);
  assert.equal(ownedChildren(['a','portal','b'],['a','b'],owned),null);
  assert.equal(ownedChildren(['a','elsewhere','b'],['a','b'],owned,true),null);
  assert.equal(ownedChildren(['a','portal'],['a','b'],owned,true),null);
  assert.equal(ownedChildren(['b','portal','a'],['a','b'],owned,true),null);
  assert.deepEqual(preserveExternalSlots(['b','portal','a'],['a','b'],owned),['a','portal','b']);
});
