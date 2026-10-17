/** Source-neutral MA stage orchestration. RemNote writes use only the existing CLI. */
import path from 'node:path';
import os from 'node:os';
import {fileURLToPath} from 'node:url';
import {spawn} from 'node:child_process';
import {createHash} from 'node:crypto';
import {readFile,writeFile,mkdir,open,unlink,readdir,access} from 'node:fs/promises';
import {atomicJSON} from '../src/atomic-json.mjs';
import {inspectPackage,stableJSON} from '../src/package.mjs';
import {topAnnotationLayout,auditTopAnnotations} from '../src/annotations.mjs';

const repo=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const hash=data=>createHash('sha256').update(data).digest('hex');
const json=async file=>JSON.parse(await readFile(file,'utf8'));
const exists=async file=>{try{await access(file);return true;}catch(e){if(e.code==='ENOENT')return false;throw e;}};
const fingerprint=async files=>Object.fromEntries(await Promise.all(files.map(async f=>[f,hash(await readFile(f))])));
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));

/** argv arrays only; source text never becomes a command. Logs retain complete child output. */
export async function runProcess(executable,args,{log,quiet=false}={}){
  const chunks=[];
  const child=spawn(executable,args,{cwd:repo,shell:false,windowsHide:true,env:process.env});
  for(const stream of [child.stdout,child.stderr])stream.on('data',chunk=>{chunks.push(chunk);if(!quiet)process.stdout.write(chunk);});
  const code=await new Promise((resolve,reject)=>{child.once('error',reject);child.once('close',resolve);});
  const output=Buffer.concat(chunks).toString('utf8');
  if(log)await writeFile(log,output);
  if(code!==0)throw new Error(`${path.basename(executable)} ${args[0]} exited ${code}${log?`; see ${log}`:''}: ${output.slice(-1200)}`);
  return output;
}

export function parseArgs(argv){
  const options={mode:'prepare',workers:1,pollMs:5000,maxPolls:720,stateRoot:'D:/AppData/RemNoteBulkImporter'};
  if(argv[0]&&!argv[0].startsWith('--'))options.mode=argv.shift();
  const flags=new Set(['allow-missing-progress','include-external-prerequisites']);
  const names=new Set(['graph','progress','topics','course-id','title','output','package','workers','python','tectonic','pdftoppm','external-course-id','unit-labels','expected-kb-id','parent-rem-id','adopt-job-id','state-root','registry','poll-ms','max-polls']);
  for(let i=0;i<argv.length;i++){
    const name=argv[i].replace(/^--/,'');
    if(argv[i]!==`--${name}`||(!names.has(name)&&!flags.has(name)))throw new Error(`Unknown option ${argv[i]}`);
    const key=name.replace(/-([a-z])/g,(_,s)=>s.toUpperCase());
    if(flags.has(name))options[key]=true;
    else{if(!argv[i+1]||argv[i+1].startsWith('--'))throw new Error(`Missing --${name} value`);options[key]=argv[++i];}
  }
  if(!['prepare','import','adopt'].includes(options.mode))throw new Error('Mode must be prepare, import or adopt');
  for(const k of ['courseId','workers','pollMs','maxPolls','externalCourseId'])if(options[k]!==undefined){options[k]=Number(options[k]);if(!Number.isSafeInteger(options[k])||options[k]<1)throw new Error(`Invalid ${k}`);}
  if(!options.courseId)throw new Error('--course-id is required');
  if(options.mode==='adopt'){if(!options.adoptJobId)throw new Error('adopt requires --adopt-job-id');}
  else for(const k of ['graph','topics','title','output','package'])if(!options[k])throw new Error(`--${k} is required`);
  if(options.mode!=='prepare'&&!options.expectedKbId)throw new Error('RemNote access requires --expected-kb-id');
  if(options.unitLabels&&!['source','numeric'].includes(options.unitLabels))throw new Error('--unit-labels must be source or numeric');
  if(options.includeExternalPrerequisites&&!options.externalCourseId)throw new Error('External prerequisites require --external-course-id');
  for(const k of ['graph','progress','topics','output','package','stateRoot','registry'])if(options[k])options[k]=path.resolve(options[k]);
  options.registry??=path.join(options.stateRoot,'course-workflow-registry.json');
  return options;
}

export function consumerArgs(options,stage,extra=[]){
  const args=[path.join(repo,'consumers/math_academy.py'),stage,'--output',options.output,'--course-id',String(options.courseId)];
  for(const [key,flag] of [['graph','graph'],['progress','progress'],['topics','topics'],['title','title'],['externalCourseId','external-course-id'],['unitLabels','unit-labels']])if(options[key]!==undefined)args.push(`--${flag}`,String(options[key]));
  for(const [key,flag] of [['allowMissingProgress','allow-missing-progress'],['includeExternalPrerequisites','include-external-prerequisites']])if(options[key])args.push(`--${flag}`);
  return [...args,...extra];
}

/** A stage resumes only when both its inputs and every recorded output still match. */
export class Stages{
  constructor(root,run=runProcess){this.root=root;this.run=run;this.file=path.join(root,'workflow-stages.json');}
  async init(){await mkdir(this.root,{recursive:true});this.state=await exists(this.file)?await json(this.file):{schemaVersion:1,stages:{}};}
  async step(name,inputs,outputs,action){
    const key=hash(stableJSON(inputs)),prior=this.state.stages[name];
    if(prior?.key===key&&prior.status==='complete'){
      try{if(stableJSON(await fingerprint(Object.keys(prior.outputs)))===stableJSON(prior.outputs)){console.log(JSON.stringify({stage:name,status:'cached'}));return;}}catch(e){if(e.code!=='ENOENT')throw e;}
    }
    this.state.stages[name]={key,status:'running'};await atomicJSON(this.file,this.state);
    console.log(JSON.stringify({stage:name,status:'running'}));
    try{await action();const files=typeof outputs==='function'?await outputs():outputs;this.state.stages[name]={key,status:'complete',outputs:await fingerprint(files)};await atomicJSON(this.file,this.state);}
    catch(e){this.state.stages[name]={key,status:'failed',error:String(e)};await atomicJSON(this.file,this.state);throw e;}
  }
}

async function runtime(options){
  const base=path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies');
  options.python??=process.env.RBI_PYTHON??(await exists(path.join(base,'python/python.exe'))?path.join(base,'python/python.exe'):'python');
  options.tectonic??=process.env.RBI_TECTONIC??process.env.CODEX_TECTONIC_PATH??'tectonic';
  options.pdftoppm??=process.env.RBI_PDFTOPPM??(await exists(path.join(base,'native/poppler/Library/bin/pdftoppm.exe'))?path.join(base,'native/poppler/Library/bin/pdftoppm.exe'):'pdftoppm');
}

export async function prepareCourse(options,{run=runProcess}={}){
  await runtime(options);await mkdir(options.output,{recursive:true});await mkdir(path.dirname(options.package),{recursive:true});
  const stages=new Stages(options.output,run);await stages.init();
  const draft=path.join(options.output,'draft-package.json'),index=path.join(options.output,'drawings-index.json');
  const initial=path.join(options.output,'math-initial-audit.json'),finalMath=path.join(options.output,'math-final-audit.json');
  const packed=path.join(options.output,'packed-package.json');
  const sources=await fingerprint([options.graph,options.topics,...(options.progress?[options.progress]:[])]);
  const independent=path.join(repo,'consumers/audit-course-source.py');
  const implementation=await fingerprint([fileURLToPath(import.meta.url),path.join(repo,'consumers/math_academy.py'),path.join(repo,'consumers/audit-math.mjs'),independent,path.join(repo,'consumers/render-svg.mjs'),path.join(repo,'src/annotations.mjs'),path.join(repo,'src/package.mjs')]);
  const common={sources,implementation,courseId:options.courseId,title:options.title,allowMissingProgress:!!options.allowMissingProgress,includeExternalPrerequisites:!!options.includeExternalPrerequisites,externalCourseId:options.externalCourseId??null,unitLabels:options.unitLabels??'source'};
  const drawingSources=async()=>Object.entries(await json(index)).flatMap(([key,value])=>
    ['original','drawing'].map(name=>path.join(options.output,'drawings',key,`${name}.${value.format==='svg'?'svg':'tex'}`)));
  const convertedFiles=async()=>[draft,index,path.join(options.output,'source-coverage.json'),path.join(options.output,'source-gaps.json'),path.join(options.output,'conversion-summary.json'),
    ...(await readdir(path.join(options.output,'source'))).filter(name=>/^topic-\d+\.json$/.test(name)).sort().map(name=>path.join(options.output,'source',name)),...await drawingSources()];
  const py=async(stage,args=[])=>run(options.python,consumerArgs(options,stage,args),{log:path.join(options.output,`workflow-${stage}.log`)});
  const math=async(source,target)=>{await run(process.execPath,[path.join(repo,'consumers/audit-math.mjs'),source,target],{log:`${target}.log`});return json(target);};
  // Retain the immutable first draft so fallback-convert never invalidates its own prerequisite.
  const originalDraft=path.join(options.output,'initial-draft-package.json');
  await stages.step('convert',common,[originalDraft],async()=>{await py('convert');await writeFile(originalDraft,await readFile(draft));});
  await stages.step('audit-math-initial',await fingerprint([originalDraft]),[initial],()=>math(originalDraft,initial));
  const audit=await json(initial);
  await stages.step('convert-final',{...common,initial:hash(await readFile(originalDraft)),audit:hash(await readFile(initial))},convertedFiles,async()=>{
    // Always reconstruct from the original ZIPs; no candidate node is hand patched.
    await py('convert',audit.errors?['--math-audit',initial]:[]);
  });
  await stages.step('audit-math-final',await fingerprint([draft]),[finalMath],async()=>{const report=await math(draft,finalMath);if(report.errors)throw new Error(`${report.errors} native formulas still fail; revise the generic consumer and rerun`);});
  const drawingFiles=async()=>Object.keys(await json(index)).flatMap(key=>['drawing.png','success.json'].map(file=>path.join(options.output,'drawings',key,file)));
  await stages.step('render',{...await fingerprint([index,...await drawingSources()]),implementation,tectonic:options.tectonic,pdftoppm:options.pdftoppm},async()=>[path.join(options.output,'render-results.json'),...await drawingFiles()],async()=>{
    await py('render',['--tectonic',options.tectonic,'--pdftoppm',options.pdftoppm,'--workers',String(options.workers??1)]);
    const result=await json(path.join(options.output,'render-results.json'));if(result.failed.length)throw new Error(`${result.failed.length} drawings failed; see render-results.json`);
  });
  await stages.step('pack',{...await fingerprint([draft,finalMath,...await drawingFiles()]),implementation},[packed],()=>py('pack',['--package',packed]));
  await stages.step('annotation-layout',{...await fingerprint([packed]),implementation},[options.package],async()=>{
    const plan=topAnnotationLayout(await json(packed));auditTopAnnotations(plan);await writePreparedPackage(options,plan);
  });
  // Also guard a cached layout after a registry was added by a later import.
  await assertRegisteredPackage(options,(await inspectPackage(await json(options.package))).hash);
  // The Python source audit expects this filename and verifies formula counts after layout.
  await stages.step('audit-package-math',await fingerprint([options.package]),[path.join(options.output,'math-package-audit.json')],async()=>{
    const report=await math(options.package,path.join(options.output,'math-package-audit.json'));if(report.errors)throw new Error('Final package math audit failed');
  });
  await stages.step('audit-source',{...await fingerprint([options.package,finalMath]),implementation},[path.join(options.output,'package-audit.json')],()=>py('audit',['--package',options.package]));
  const independentReport=path.join(options.output,'source-independent-audit.json');
  await stages.step('audit-independent',{sources,...await fingerprint([options.package,independent])},[independentReport],async()=>{
    const args=[independent,'--graph',options.graph,'--topics',options.topics,'--course-id',String(options.courseId),'--package',options.package,'--report',independentReport];
    if(options.progress)args.push('--progress',options.progress);
    if(options.includeExternalPrerequisites)args.push('--external-course-id',String(options.externalCourseId));
    await run(options.python,args,{log:path.join(options.output,'workflow-audit-independent.log')});
    if((await json(independentReport)).status!=='PASSED')throw new Error('Independent source audit failed');
  });
  const report=await inspectPackage(await json(options.package));
  const receipt={status:'prepared',courseId:options.courseId,packagePath:options.package,...report,annotations:auditTopAnnotations(await json(options.package)),sourceAudit:await json(path.join(options.output,'package-audit.json')),independentSourceAudit:await json(independentReport)};
  await atomicJSON(path.join(options.output,'workflow-prepared.json'),receipt);console.log(JSON.stringify(receipt));return receipt;
}

export function assertRegistration(existing,next){
  if(existing&&(existing.jobId!==next.jobId||existing.kbId!==next.kbId||existing.parentRemId!==next.parentRemId))throw new Error('Course already registered to a different package or destination; adopt its existing job instead of creating another root');
}

export async function assertRegisteredPackage(options,packageHash){
  const file=options.registry??path.join(options.stateRoot??'D:/AppData/RemNoteBulkImporter','course-workflow-registry.json');
  const record=await exists(file)?(await json(file)).courses?.[String(options.courseId)]:null;
  if(record&&record.jobId!==packageHash)throw new Error('Registered course package is immutable; a content change requires an explicit revision/migration workflow. Existing final package preserved.');
}

export async function writePreparedPackage(options,plan){
  const info=await inspectPackage(plan);await assertRegisteredPackage(options,info.hash);
  if(await exists(options.package)){
    const prior=await json(options.package);
    // Keep completed evidence byte-exact when the semantic package is identical.
    if((await inspectPackage(prior)).hash===info.hash)return;
  }
  await atomicJSON(options.package,plan);
}

async function withLock(file,action){
  await mkdir(path.dirname(file),{recursive:true});let handle;
  try{handle=await open(file,'wx');await handle.writeFile(JSON.stringify({pid:process.pid,startedAt:new Date().toISOString()}));}
  catch(e){if(e.code==='EEXIST')throw new Error(`Workflow lock exists: ${file}; inspect its PID before removing a stale lock`);throw e;}
  try{return await action();}finally{await handle.close();await unlink(file);}
}

export async function importCourse(options,{run=runProcess,sleep=wait}={}){
  return withLock(`${options.registry}.lock`,async()=>{
    const cli=async(command,...args)=>JSON.parse(await run(process.execPath,[path.join(repo,'src/cli.mjs'),command,...args],{quiet:true}));
    const live=await cli('status');if(!live.connected||live.kbId!==options.expectedKbId)throw new Error('Live knowledge base does not match --expected-kb-id');
    const registry=await exists(options.registry)?await json(options.registry):{schemaVersion:1,courses:{}};
    const key=String(options.courseId),old=registry.courses[key];
    let jobId=options.adoptJobId??old?.jobId,info;
    if(options.mode==='adopt'){
      info=await cli('job',jobId);
      if(info.status!=='complete'||info.result?.status!=='complete'||!info.result.rootRemId||info.result.verified!==info.info.nodes+1)throw new Error('Only an existing job with complete exact readback can be adopted');
      if(!new RegExp(`^ma\\.course${options.courseId}(?:\\.|$)`).test(info.packageId))throw new Error('Adopted job belongs to another course');
    }else{
      const plan=await json(options.package),inspection=await inspectPackage(plan);jobId=inspection.hash;
      if(plan.provenance?.courseId!==options.courseId)throw new Error('Package belongs to a different course');
      assertRegistration(old,{jobId,kbId:options.expectedKbId,parentRemId:options.parentRemId??null});
      // Discover prior service jobs, then read authoritative status through the CLI.
      // Never read the active job receipt while the service is atomically replacing it.
      const candidates=[];
      if(live.activeJob)candidates.push(await cli('job',live.activeJob));
      for(const name of await readdir(options.stateRoot))if(/^[a-f0-9]{64}\.job\.json$/.test(name)&&!name.startsWith(live.activeJob??'!')){
        const stored=await json(path.join(options.stateRoot,name));
        if(new RegExp(`^ma\\.course${options.courseId}(?:\\.|$)`).test(stored.packageId))candidates.push(await cli('job',stored.jobId));
      }
      for(const prior of candidates)if(new RegExp(`^ma\\.course${options.courseId}(?:\\.|$)`).test(prior.packageId)&&prior.jobId!==jobId)throw new Error(`Course already has job ${prior.jobId}; adopt or resume it instead of preparing a second root`);
      // Persist the chosen native job identity before even prepare, so a process
      // loss around start can never leave an unregistered newly created root.
      registry.courses[key]={jobId,kbId:options.expectedKbId,parentRemId:options.parentRemId??null,status:'selected',rootRemId:old?.rootRemId??null};
      await atomicJSON(options.registry,registry);
      info=await cli('prepare',options.package);if(info.jobId!==jobId)throw new Error('Service prepared hash mismatch');
    }
    const record={jobId,kbId:info.kbId??options.expectedKbId,parentRemId:info.parentRemId??options.parentRemId??null,status:info.status,rootRemId:info.result?.rootRemId??info.progress?.rootRemId??null};
    if(record.kbId!==options.expectedKbId||record.parentRemId!==(options.parentRemId??null))throw new Error('Existing job destination differs');
    assertRegistration(old,record);registry.courses[key]=record;await atomicJSON(options.registry,registry);
    if(options.mode==='adopt'){console.log(JSON.stringify({status:'adopted',courseId:options.courseId,...record}));return record;}
    if(info.status!=='complete'&&!['running','starting'].includes(info.status))info=await cli('start',jobId,...(options.parentRemId?[options.parentRemId]:[]));
    for(let poll=0;poll<(options.maxPolls??720);poll++){
      if(info.status==='complete'){
        if(info.result?.status!=='complete'||info.result.verified!==info.info.nodes+1||!info.result.rootRemId)throw new Error('Incomplete final readback');
        Object.assign(record,{status:'complete',rootRemId:info.result.rootRemId,verified:info.result.verified});await atomicJSON(options.registry,registry);console.log(JSON.stringify(record));return record;
      }
      console.log(JSON.stringify({courseId:options.courseId,jobId,status:info.status,progress:info.progress}));
      if(!['running','starting'].includes(info.status))throw new Error(`Job ${info.status}; preserved jobId ${jobId}. Inspect/fence any timed-out SDK mutation before explicitly rerunning import.`);
      await sleep(options.pollMs??5000);info=await cli('job',jobId);
    }
    throw new Error(`Polling limit reached; job ${jobId} remains registered. Rerun import to resume polling without creating another root.`);
  });
}

export async function main(argv=process.argv.slice(2)){
  const options=parseArgs([...argv]);
  if(options.mode==='adopt')return importCourse(options);
  return withLock(path.join(options.output,'workflow.lock'),async()=>{const receipt=await prepareCourse(options);return options.mode==='import'?importCourse(options):receipt;});
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url))main().catch(error=>{console.error(error.stack);process.exitCode=1;});
