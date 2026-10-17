import {readFile,writeFile} from 'node:fs/promises';
import {inspectPackage} from '../src/package.mjs';
import {planStructureChange} from '../src/restructure.mjs';
const [source,output]=process.argv.slice(2);
if(!source||!output||source===output)throw new Error('Usage: read-canary <completed-fixture-package> <new-fixture-package>');
const base=JSON.parse(await readFile(source,'utf8'));
if(base.nodes.length>128)throw new Error('Only a small independent fixture is accepted');
const next={...base,nodes:[...base.nodes,{id:'read-batch-canary',parentId:null,document:false,text:[{kind:'text',value:'独立批量回读验收'}]}]};
planStructureChange(base,next);const info=await inspectPackage(next);await writeFile(output,JSON.stringify(next,null,2));console.log(JSON.stringify(info));
