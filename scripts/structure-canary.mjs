import {readFile,writeFile} from 'node:fs/promises';
import {inspectPackage} from '../src/package.mjs';
import {planStructureChange} from '../src/restructure.mjs';
const [source,output]=process.argv.slice(2);
if(!source||!output)throw new Error('Usage: node scripts/structure-canary.mjs <immutable-canary-package> <output-package>');
const base=JSON.parse(await readFile(source,'utf8'));
if(!base.nodes.some(n=>n.id==='multiline')||base.nodes.some(n=>n.id.startsWith('fixture-')))throw new Error('Expected the independent generic canary fixture');
const next={...base,nodes:[
  {id:'fixture-unit',parentId:null,document:true,text:[{kind:'text',value:'验收单元'}]},
  {id:'fixture-module',parentId:'fixture-unit',document:true,text:[{kind:'text',value:'验收模块'}]},
  ...base.nodes.filter(n=>n.id!=='multiline').map(n=>({...n,parentId:n.id==='topic-a'||n.id==='topic-b'?'fixture-module':n.parentId})),
]};
const changes=planStructureChange(base,next),info=await inspectPackage(next);
await writeFile(output,JSON.stringify(next,null,2));
console.log(JSON.stringify({...info,added:changes.added.length,moved:changes.moved.length,archived:changes.removed.length}));
