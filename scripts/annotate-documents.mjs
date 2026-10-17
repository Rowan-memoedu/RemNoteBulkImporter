import {readFile,writeFile} from 'node:fs/promises';
import {annotateDocuments,auditAnnotations} from '../src/annotations.mjs';
import {inspectPackage} from '../src/package.mjs';
const [source,output]=process.argv.slice(2);
if(!source||!output||source===output)throw new Error('Usage: annotate-documents <immutable-source> <new-output>');
const plan=annotateDocuments(JSON.parse(await readFile(source,'utf8'))),info=await inspectPackage(plan);
await writeFile(output,JSON.stringify(plan,null,2));
const {documents:annotatedDocuments,...audit}=auditAnnotations(plan);
console.log(JSON.stringify({...info,annotatedDocuments,...audit}));
