import {mkdir,writeFile} from 'node:fs/promises';
import {sha256,inspectPackage} from '../src/package.mjs';
const base64='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=';
const bytes=Uint8Array.from(atob(base64),c=>c.charCodeAt(0));
const p={schemaVersion:1,packageId:'rbi.acceptance.20261017',title:'批量导入插件验收',assets:{pixel:{mime:'image/png',base64,sha256:await sha256(bytes)}},nodes:[
  {id:'topic-a',parentId:null,document:true,text:[{kind:'text',value:'A：依赖知识'}]},
  {id:'prereqs',parentId:'topic-a',document:false,text:[{kind:'text',value:'前置知识：'},{kind:'ref',targetId:'topic-b'}]},
  {id:'math',parentId:'topic-a',document:false,text:[{kind:'text',value:'原生公式：'},{kind:'latex',value:'\\int_0^1 x^2\\,dx=\\frac13',block:true}]},
  {id:'multiline',parentId:'topic-a',document:false,text:[{kind:'text',value:'同一节点第一行\n同一节点第二行'}]},
  {id:'topic-b',parentId:null,document:true,text:[{kind:'text',value:'B：基础知识'}]},
  {id:'format',parentId:'topic-b',document:false,text:[{kind:'markdown',value:'**原生粗体**与 *斜体*'}]},
  {id:'image',parentId:'topic-b',document:false,text:[{kind:'image',assetId:'pixel'}]},
]};
const root='D:/Artifacts/RemNoteBulkImporter/packages';await mkdir(root,{recursive:true});await writeFile(`${root}/canary.json`,JSON.stringify(p,null,2));console.log(await inspectPackage(p));
