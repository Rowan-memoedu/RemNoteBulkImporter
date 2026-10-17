import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StreamableHTTPClientTransport} from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import {VERSION} from './version.mjs';
const [command,...args]=process.argv.slice(2);
const client=new Client({name:'remnote-bulk-import-cli',version:VERSION});
await client.connect(new StreamableHTTPClientTransport(new URL('http://127.0.0.1:43106/mcp')));
try{
  const commands={status:['bulk_import_status',{}],prepare:['bulk_import_prepare',{packagePath:args[0]}],start:['bulk_import_start',{jobId:args[0],...(args[1]?{parentRemId:args[1]}:{})}],job:['bulk_import_job',{jobId:args[0]}],pause:['bulk_import_pause',{jobId:args[0]}]};
  if(!commands[command])throw new Error('Usage: node src/cli.mjs status | prepare <absolute-package.json> | start <jobId> [parentRemId] | job <jobId> | pause <jobId>');
  const [name,input]=commands[command],result=await client.callTool({name,arguments:input});
  console.log(JSON.stringify(result.structuredContent ?? result.content,null,2));
  if(result.isError)process.exitCode=1;
}finally{await client.close();}
