import {readFile,writeFile,mkdir,cp} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import katex from 'katex';
const folder=process.argv[2];
const bundle=JSON.parse(await readFile(path.join(folder,'package.json'),'utf8'));
const output={};
for(const node of bundle.nodes)for(const segment of node.text)if(segment.kind==='latex'){
  // Python's default JSON separator contains one space after a comma.
  const key=JSON.stringify([segment.value,segment.block]).replace(/,(true|false)\]$/u,', $1]');
  output[key]=katex.renderToString(segment.value,{displayMode:segment.block,throwOnError:true,strict:'ignore',trust:false,output:'htmlAndMathml'});
}
await writeFile(path.join(folder,'preview-math.json'),JSON.stringify(output));
const support=path.join(folder,'preview-support');
await mkdir(support,{recursive:true});
const distribution=fileURLToPath(new URL('../node_modules/katex/dist/',import.meta.url));
await cp(path.join(distribution,'katex.min.css'),path.join(support,'katex.min.css'));
await cp(path.join(distribution,'fonts'),path.join(support,'fonts'),{recursive:true});
console.log(JSON.stringify({formulas:Object.keys(output).length,previewAssets:support}));
