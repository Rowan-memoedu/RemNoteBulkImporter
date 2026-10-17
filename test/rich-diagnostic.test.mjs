import test from 'node:test';
import assert from 'node:assert/strict';
import {describeRich} from '../src/rich-diagnostic.mjs';
test('RichText diagnostic exposes structural field types without source prose or image bytes',()=>{
  const source='private source phrase',url='data:image/png;base64,'+'A'.repeat(1000);
  const report=describeRich([source,{i:'i',url,width:309,height:276,loading:false,percent:null}]),json=JSON.stringify(report);
  assert.ok(!json.includes(source));assert.ok(!json.includes('A'.repeat(100)));assert.equal(report.items[1].fields.width,309);assert.equal(report.items[1].fields.percent,null);
});
