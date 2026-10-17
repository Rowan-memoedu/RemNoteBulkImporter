import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import {mkdir,mkdtemp,writeFile,readFile,rm} from 'node:fs/promises';
import {parseArgs,consumerArgs,Stages,prepareCourse,importCourse,assertRegistration,writePreparedPackage} from '../consumers/course-workflow.mjs';
import {inspectPackage} from '../src/package.mjs';

const root='D:/Artifacts/RemNoteBulkImporter/workflow-tests';
async function fixture(t){await mkdir(root,{recursive:true});const dir=await mkdtemp(path.join(root,'case-'));t.after(()=>rm(dir,{recursive:true,force:true}));return dir;}
const put=(file,value)=>writeFile(file,JSON.stringify(value));
const get=async file=>JSON.parse(await readFile(file,'utf8'));
const plan=()=>({schemaVersion:1,packageId:'ma.course7.source-export',title:'Fixture',nodes:[{id:'t1',parentId:null,document:true,text:[{kind:'text',value:'Source text'}]}],assets:{},provenance:{courseId:7}});

test('prepare is default and only explicit import/adopt accepts RemNote operations',()=>{
  const args=['--graph','g','--topics','t','--course-id','7','--title','Fixture','--output','o','--package','p'];
  const parsed=parseArgs(args);assert.equal(parsed.mode,'prepare');assert.equal(parsed.workers,1);
  assert.throws(()=>parseArgs(['import',...args]),/expected-kb-id/);
  assert.throws(()=>parseArgs([...args,'--workers','0']),/Invalid workers/);
  const options={...parsed,allowMissingProgress:true,includeExternalPrerequisites:true,externalCourseId:109,unitLabels:'numeric'};
  const forwarded=consumerArgs(options,'convert');assert.ok(forwarded.includes('--allow-missing-progress'));assert.ok(forwarded.includes('--include-external-prerequisites'));assert.ok(forwarded.includes('109'));assert.ok(forwarded.includes('numeric'));
});

test('stages retain success but invalidate changed inputs, changed outputs and failures',async t=>{
  const dir=await fixture(t),file=path.join(dir,'out.json'),stages=new Stages(dir);await stages.init();let runs=0;
  const action=async()=>{runs++;await put(file,{runs});};
  await stages.step('one',{source:1},[file],action);await stages.step('one',{source:1},[file],action);assert.equal(runs,1);
  await put(file,{tampered:true});await stages.step('one',{source:1},[file],action);assert.equal(runs,2);
  await stages.step('one',{source:2},[file],action);assert.equal(runs,3);
  await assert.rejects(stages.step('broken',{},[file],async()=>{throw new Error('fixture failure');}),/fixture failure/);
  await stages.step('broken',{},[file],action);assert.equal(runs,4);
});

test('prepare pipeline regenerates original sources on math failure, applies annotations and resumes without CLI',async t=>{
  const dir=await fixture(t),output=path.join(dir,'output'),graph=path.join(dir,'graph.zip'),topics=path.join(dir,'topics.zip');
  await writeFile(graph,'fixture graph');await writeFile(topics,'fixture topics');
  const options={courseId:7,title:'Fixture',graph,topics,output,package:path.join(dir,'final.json'),workers:1,allowMissingProgress:true,python:'fixture-python',tectonic:'fixture-tectonic',pdftoppm:'fixture-poppler'};
  const calls=[];
  const run=async(executable,args)=>{
    calls.push({executable,args:[...args]});
    assert.ok(!args.some(v=>v.endsWith('cli.mjs')),'prepare must never contact RemNote');
    if(args[0].endsWith('audit-course-source.py')){await put(args[args.indexOf('--report')+1],{status:'PASSED',counts:{topics:1},errors:[]});return '';}
    if(args[0].endsWith('audit-math.mjs')){await put(args[2],{count:0,errors:args[2].endsWith('math-initial-audit.json')?1:0,details:[]});return '';}
    const stage=args[1];
    if(stage==='convert'){
      await mkdir(path.join(output,'source'),{recursive:true});await put(path.join(output,'source','topic-1.json'),{fixture:true});
      await put(path.join(output,'draft-package.json'),plan());
      for(const file of ['drawings-index.json','conversion-summary.json'])await put(path.join(output,file),{});
      for(const file of ['source-coverage.json','source-gaps.json'])await put(path.join(output,file),[]);
    }else if(stage==='render')await put(path.join(output,'render-results.json'),{failed:[],total:0,passed:0});
    else if(stage==='pack')await put(args[args.indexOf('--package')+1],plan());
    else if(stage==='audit')await put(path.join(output,'package-audit.json'),{status:'PASSED',topics:1});
    else throw new Error(`Unexpected stage ${stage}`);
    return '';
  };
  const receipt=await prepareCourse(options,{run});assert.equal(receipt.status,'prepared');assert.equal(receipt.annotations.annotationBranches,2);
  assert.equal(calls.filter(c=>c.args[1]==='convert').length,2);assert.ok(calls.find(c=>c.args.includes('--math-audit')));
  const count=calls.length;await prepareCourse(options,{run});assert.equal(calls.length,count,'all intact stages must resume');
  await put(path.join(output,'source','topic-1.json'),{tampered:true});await prepareCourse(options,{run});assert.equal(calls.filter(c=>c.args[1]==='convert').length,3,'modified source snapshot must force source regeneration');
  await writeFile(graph,'changed original source');await prepareCourse(options,{run});assert.ok(calls.length>count,'source changes must invalidate conversion');
});

test('render failure stops packing and is preserved as a failed stage',async t=>{
  const dir=await fixture(t),stages=new Stages(dir);await stages.init();
  await assert.rejects(stages.step('render',{},[],async()=>{throw new Error('diagram failed');}),/diagram failed/);
  assert.equal((await get(path.join(dir,'workflow-stages.json'))).stages.render.status,'failed');
});

test('registration rejects a second package/destination but permits the same resumable job',()=>{
  const record={jobId:'abc',kbId:'kb',parentRemId:null};assertRegistration(record,{...record});
  assert.throws(()=>assertRegistration(record,{...record,jobId:'def'}),/already registered/);
  assert.throws(()=>assertRegistration(record,{...record,kbId:'other'}),/already registered/);
});

test('prepare refuses to overwrite registered package evidence with a changed candidate',async t=>{
  const dir=await fixture(t),packagePath=path.join(dir,'immutable.json'),registry=path.join(dir,'registry.json');
  await put(packagePath,plan());const before=await readFile(packagePath,'utf8');
  await put(registry,{courses:{7:{jobId:'registered-other-hash'}}});
  const changed=plan();changed.title='Changed';
  await assert.rejects(writePreparedPackage({courseId:7,registry,package:packagePath},changed),/immutable/);
  assert.equal(await readFile(packagePath,'utf8'),before);
});

test('adopt records an independently completed course and never prepares or starts',async t=>{
  const dir=await fixture(t),registry=path.join(dir,'registry.json'),commands=[];
  const options={mode:'adopt',courseId:7,expectedKbId:'kb',adoptJobId:'complete-job',registry,stateRoot:dir};
  const run=async(_,args)=>{const command=args[1];commands.push(command);return JSON.stringify(command==='status'?{connected:true,kbId:'kb'}:{jobId:'complete-job',packageId:'ma.course7.source-export',kbId:'kb',parentRemId:null,status:'complete',info:{nodes:1},result:{status:'complete',rootRemId:'root',verified:2}});};
  const result=await importCourse(options,{run});assert.equal(result.rootRemId,'root');assert.deepEqual(commands,['status','job']);
  assert.equal((await get(registry)).courses['7'].jobId,'complete-job');
  await importCourse(options,{run});assert.ok(!commands.includes('start'));
});

test('import detects a prior service job with a different hash before preparing a duplicate course',async t=>{
  const dir=await fixture(t),packagePath=path.join(dir,'package.json');await put(packagePath,plan());
  const prior={jobId:'a'.repeat(64),packageId:'ma.course7.source-export',status:'complete'};await put(path.join(dir,`${prior.jobId}.job.json`),prior);
  const commands=[],run=async(_,args)=>{commands.push(args[1]);return JSON.stringify(args[1]==='status'?{connected:true,kbId:'kb',activeJob:null}:prior);};
  await assert.rejects(importCourse({mode:'import',courseId:7,expectedKbId:'kb',registry:path.join(dir,'registry.json'),stateRoot:dir,package:packagePath},{run}),/already has job/);
  assert.deepEqual(commands,['status','job']);
});

test('import persists identity before prepare/start and repeats only the completed native job',async t=>{
  const dir=await fixture(t),packagePath=path.join(dir,'package.json'),registry=path.join(dir,'registry.json');await put(packagePath,plan());
  const info=await inspectPackage(plan()),options={mode:'import',courseId:7,expectedKbId:'kb',registry,stateRoot:dir,package:packagePath,pollMs:1,maxPolls:2};
  let completed=false,starts=0;
  const summary=status=>({jobId:info.hash,packageId:plan().packageId,kbId:'kb',parentRemId:null,status,info,...(status==='complete'?{result:{status:'complete',rootRemId:'existing-root',verified:info.nodes+1}}:{})});
  const run=async(_,args)=>{
    const command=args[1];
    if(command==='status')return JSON.stringify({connected:true,kbId:'kb',activeJob:null});
    if(command==='prepare'){
      const saved=(await get(registry)).courses['7'];assert.equal(saved.jobId,info.hash);assert.equal(saved.kbId,'kb');assert.equal(saved.parentRemId,null);
      return JSON.stringify(summary(completed?'complete':'prepared'));
    }
    if(command==='start'){starts++;assert.equal((await get(registry)).courses['7'].status,'prepared');return JSON.stringify(summary('running'));}
    if(command==='job'){completed=true;return JSON.stringify(summary('complete'));}
    throw new Error(`Unexpected command ${command}`);
  };
  await importCourse(options,{run,sleep:async()=>{}});await importCourse(options,{run,sleep:async()=>{}});
  assert.equal(starts,1);assert.equal((await get(registry)).courses['7'].rootRemId,'existing-root');
});
