import katex from 'katex';
import {readFile,writeFile} from 'node:fs/promises';
const [source,output]=process.argv.slice(2);
const plan=JSON.parse(await readFile(source,'utf8'));
let count=0;const cached=new Map(),errors=[];
for(const node of plan.nodes)for(const s of node.text)if(s.kind==='latex'){
  count++;const key=JSON.stringify([s.value,s.block]);
  if(!cached.has(key)){
    try{katex.renderToString(s.value,{displayMode:s.block,throwOnError:true,strict:'ignore',trust:false,output:'mathml'});cached.set(key,null);}
    catch(e){cached.set(key,e.message);}
  }
  if(cached.get(key))errors.push({nodeId:node.id,value:s.value,error:cached.get(key)});
}
const byError={};for(const e of errors){const key=e.error.split(':').slice(0,3).join(':');byError[key]=(byError[key]??0)+1;}
const report={count,unique:cached.size,errors:errors.length,byError,details:errors};
await writeFile(output,JSON.stringify(report,null,2));
console.log(JSON.stringify({count,unique:cached.size,errors:errors.length,groups:Object.entries(byError).slice(0,15),examples:errors.slice(0,8)}));
