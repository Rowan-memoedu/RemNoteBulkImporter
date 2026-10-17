import {readFile,writeFile} from 'node:fs/promises';
import {inspectPackage} from '../src/package.mjs';
const course=JSON.parse(await readFile('D:/Artifacts/RemNoteBulkImporter/packages/course-154.json','utf8'));
const [assetId,asset]=Object.entries(course.assets).sort((a,b)=>b[1].base64.length-a[1].base64.length)[0];
const plan={schemaVersion:1,packageId:'rbi.mixed-richtext.canary',title:'内容格式验收',assets:{[assetId]:asset},nodes:[
  {id:'dependent',parentId:null,document:true,text:[{kind:'text',value:'后继内容'}]},
  {id:'reference',parentId:'dependent',document:false,text:[{kind:'ref',targetId:'foundation'}]},
  {id:'multiline',parentId:'dependent',document:false,text:Array.from({length:32},(_,i)=>[{kind:'text',value:`\n\n第 ${i+1} 段：`},{kind:'latex',value:'\\colorbox{Gainsboro}{$\\mathbf{v}_2$}+\\frac{a}{b}',block:false}]).flat()},
  {id:'foundation',parentId:null,document:true,text:[{kind:'text',value:'基础内容'}]},
  {id:'large-image',parentId:'foundation',document:false,text:[{kind:'image',assetId}]},
]};
const file='D:/Artifacts/RemNoteBulkImporter/packages/large-canary.json';await writeFile(file,JSON.stringify(plan));console.log(JSON.stringify({file,...await inspectPackage(plan)}));
