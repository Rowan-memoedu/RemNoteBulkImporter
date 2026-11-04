// Exact-ID reads and recoverable root moves through the maintained local MCPs.
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StreamableHTTPClientTransport} from '@modelcontextprotocol/sdk/client/streamableHttp.js';
let input='';for await(const chunk of process.stdin)input+=chunk;
const request=JSON.parse(input);
const clients=[];
async function connect(port){const c=new Client({name:'material-replacement',version:'1'});await c.connect(new StreamableHTTPClientTransport(new URL(`http://127.0.0.1:${port}/mcp`)));clients.push(c);return c;}
async function call(c,name,args){const r=await c.callTool({name,arguments:args});if(r.isError)throw new Error(JSON.stringify(r.content));return r.structuredContent??JSON.parse(r.content.find(x=>x.type==='text').text);}
try{
  const bulk=await connect(43106),status=await call(bulk,'bulk_import_status',{});
  if(!status.connected||status.kbId!==request.kbId)throw new Error('Replacement library changed');
  const main=await connect(43101);
  const readNodes=async(ids)=>({kbId:request.kbId,nodes:await Promise.all(ids.map(async id=>{
    const r=await call(main,'remnote_read_note',{remId:id,depth:1,view:'full',contentMode:'structured',ancestorDepth:1,childLimit:500});
    if(r.remId!==id)throw new Error('Exact-ID read failed');
    return {id:r.remId,parentId:r.parentRemId??null,children:(r.contentStructured??[]).map(n=>n.remId),text:[r.title],document:r.remType==='document'};
  }))});
  if(request.action==='read'){
    console.log(JSON.stringify(await readNodes(request.remIds)));
  }else if(request.action==='move'){
    if(status.busy||status.activeJob)throw new Error('Writer is busy');
    const read=async()=>await readNodes([request.remId,request.parentRemId]);
    const before=await read(),node=before.nodes.find(n=>n.id===request.remId),parent=before.nodes.find(n=>n.id===request.parentRemId);
    if(!node||!parent||parent.parentId!==null||node.id===parent.id)throw new Error('Archive must be a separate library-root container');
    if(node.parentId!==request.parentRemId){
      if(node.parentId!==request.expectedParentRemId)throw new Error('Old root moved since replacement was requested');
      const writes=await call(main,'remnote_status',{});
      if(!writes.connected||!writes.acceptWriteOperations)throw new Error('Local RemNote MCP writes are disabled');
      await call(main,'remnote_move_note',{remId:node.id,newParentRemId:parent.id,position:'last',dryRun:false,...(node.parentId?{expectedOldParentRemId:node.parentId}:{}),ancestorDepth:1});
    }
    const after=await read();if(after.nodes.find(n=>n.id===request.remId)?.parentId!==request.parentRemId)throw new Error('Archive readback failed');
    console.log(JSON.stringify({before,after}));
  }else throw new Error('Unsupported exact-ID operation');
}finally{for(const c of clients.reverse())await c.close();}
