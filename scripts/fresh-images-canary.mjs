/** Two cold image uploads separated by a mutation batch, plus literal code. */
import {randomBytes} from 'node:crypto';
import {writeFile} from 'node:fs/promises';
import {Resvg} from '@resvg/resvg-js';
import {inspectPackage,sha256} from '../src/package.mjs';
const output=process.argv[2];if(!output)throw new Error('Provide an artifact package path');
const assets={};
for(let i=0;i<2;i++){
  const color=randomBytes(3).toString('hex');
  const png=new Resvg(`<svg xmlns="http://www.w3.org/2000/svg" width="17" height="19"><rect width="17" height="19" fill="#${color}"/></svg>`).render().asPng();
  assets[`image${i}`]={mime:'image/png',base64:png.toString('base64'),sha256:await sha256(png)};
}
const nodes=[];for(let i=0;i<35;i++)nodes.push({id:`item${i}`,parentId:null,document:false,text:i===0||i===33?[{kind:'image',assetId:i===0?'image0':'image1'}]:i===34?[{kind:'code',value:'if x < 3:\n    print("$literal$")\n\n    x += 1'}]:[{kind:'text',value:`Checkpoint ${i}`}]});
const plan={schemaVersion:1,packageId:'rbi.fresh-images-canary',title:'Bulk Importer 冷缓存图片校验',nodes,assets};
await writeFile(output,JSON.stringify(plan));console.log(JSON.stringify(await inspectPackage(plan)));
