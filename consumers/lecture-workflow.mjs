// Third consumer: the same material runtime and MCP importer, with lecture policy.
import {spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
const python=process.env.RBI_MATERIAL_PYTHON||'D:/AppData/RemNoteBulkImporter/material-venv/Scripts/python.exe';
if(!existsSync(python))throw Error('Material runtime missing; follow consumers/material-workflow.md');
const child=spawn(python,[fileURLToPath(new URL('./lecture.py',import.meta.url)),...process.argv.slice(2)],{stdio:'inherit',windowsHide:true});
child.on('error',error=>{console.error(error.message);process.exitCode=1;});
child.on('exit',code=>{process.exitCode=code??1;});
