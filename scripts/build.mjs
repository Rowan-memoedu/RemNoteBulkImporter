import {build} from 'esbuild';
import {mkdir,readFile,writeFile,copyFile} from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
const out='D:/Artifacts/RemNoteBulkImporter/plugin';
await mkdir(out,{recursive:true});
for(const file of ['manifest.json','index.html'])await copyFile(`public/${file}`,path.join(out,file));
// SDK uses IMPORT_META for native index modules; sandbox must not evaluate it.
for(const sandbox of [false,true])await build({
  entryPoints:['src/plugin.ts'],bundle:true,platform:'browser',format:'esm',target:'es2020',
  outfile:path.join(out,sandbox?'index-sandbox.js':'index.js'),minify:true,
  banner:sandbox?undefined:{js:'const IMPORT_META=import.meta;'},
  define:{'process.env.NODE_ENV':'"production"'},
});
const files={};for(const f of ['manifest.json','index.html','index.js','index-sandbox.js']){
  const data=await readFile(path.join(out,f));files[f]={bytes:data.length,sha256:createHash('sha256').update(data).digest('hex')};
}
await writeFile('D:/Artifacts/RemNoteBulkImporter/build.json',JSON.stringify({version:'0.1.0',files},null,2));
console.log(JSON.stringify({build:'success',out,files}));
