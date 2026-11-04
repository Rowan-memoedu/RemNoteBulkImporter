// Read-only, offline browser verification. Never opens the user's browser profile.
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {createRequire} from 'node:module';
import {createHash} from 'node:crypto';
const [folder,dependencyRoot,chrome]=process.argv.slice(2);
if(!chrome)throw Error('Usage: lecture_preview.mjs <lecture folder> <node_modules> <Chrome executable>');
const require=createRequire(path.join(dependencyRoot,'_lecture.cjs'));
const {chromium}=require('playwright');
const packageBytes=await fs.readFile(path.join(folder,'package.json'));
const bundle=JSON.parse(packageBytes.toString('utf8'));
const output=path.join(folder,'visual-check');await fs.mkdir(output,{recursive:true});
const profile=path.join('D:/Caches/RemNoteBulkImporter','lecture-preview');
const browser=await chromium.launchPersistentContext(profile,{executablePath:chrome,headless:true,viewport:{width:1280,height:1000}});
try{
  const page=await browser.newPage();await page.route(/https?:\/\//,route=>route.abort());
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.goto(pathToFileURL(path.join(folder,'preview.html')).href,{waitUntil:'load'});
  const dom=await page.evaluate(()=>({
    title:document.title,
    images:document.images.length,
    brokenImages:[...document.images].filter(i=>!i.complete||!i.naturalWidth).length,
    imageOverflow:[...document.images].filter(i=>i.getBoundingClientRect().right>innerWidth+2).length,
    documentOverflow:document.documentElement.scrollWidth>innerWidth+2,
    mathErrors:document.querySelectorAll('.katex-error').length,
    anchors:[...document.querySelectorAll('a[id]')].map(a=>a.id)
  }));
  await page.screenshot({path:path.join(output,'top.png')});
  const questions=bundle.provenance.lecture.questions;
  const selected=[['question',questions[0]],['handwritten',questions.find(q=>q.answer&&(q.answerSources?.length>1||q.answerAtoms?.some(i=>q.local.includes(i))&&q.stemAtoms.length>1))]];
  for(const [name,q] of selected)if(q){
    const item=page.locator(`a[id="${q.node}"]`).locator('xpath=ancestor::li[1]');
    await item.screenshot({path:path.join(output,name+'.png')});
  }
  const report={...dom,pageErrors:errors,expectedAnchors:bundle.nodes.length,externalRequestsAllowed:false,
    packageSha256:createHash('sha256').update(packageBytes).digest('hex'),
    previewSha256:createHash('sha256').update(await fs.readFile(path.join(folder,'preview.html'))).digest('hex')};
  await fs.writeFile(path.join(output,'dom-readback.json'),JSON.stringify(report,null,2)+'\n');
  if(errors.length||dom.brokenImages||dom.imageOverflow||dom.documentOverflow||dom.mathErrors||dom.anchors.length!==bundle.nodes.length||new Set(dom.anchors).size!==dom.anchors.length)throw Error('Lecture preview failed; see dom-readback.json');
  console.log(JSON.stringify({status:'PASSED',images:dom.images,nodes:dom.anchors.length,output}));
}finally{await browser.close();}
