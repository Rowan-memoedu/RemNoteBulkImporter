import {readFile,writeFile} from 'node:fs/promises';
import {topAnnotationLayout,auditTopAnnotations} from '../src/annotations.mjs';
import {inspectPackage} from '../src/package.mjs';
import {planStructureChange} from '../src/restructure.mjs';
const [source,output]=process.argv.slice(2);if(!source||!output||source===output)throw new Error('Usage: layout-annotations <immutable-source> <new-output>');
const base=JSON.parse(await readFile(source,'utf8')),plan=topAnnotationLayout(base),info=await inspectPackage(plan),change=planStructureChange(base,plan);
await writeFile(output,JSON.stringify(plan,null,2));console.log(JSON.stringify({...info,annotationLayout:auditTopAnnotations(plan),added:change.added.length,removed:change.removed.length,reparented:change.moved.length}));
