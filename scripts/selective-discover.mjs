import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StreamableHTTPClientTransport} from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import {readFile} from 'node:fs/promises';
import {atomicJSON} from '../src/atomic-json.mjs';
const [kbId,output,...queries]=process.argv.slice(2);
const reader=new Client({name:'selective-source-discovery',version:'1.0.0'}),identity=new Client({name:'selective-source-identity',version:'1.0.0'});
await reader.connect(new StreamableHTTPClientTransport(new URL('http://127.0.0.1:43101/mcp')));await identity.connect(new StreamableHTTPClientTransport(new URL('http://127.0.0.1:43106/mcp')));
const unpack=r=>{if(r.isError)throw new Error(r.content[0].text);return r.structuredContent??JSON.parse(r.content[0].text);};
const check=async()=>{const status=unpack(await identity.callTool({name:'bulk_import_status',arguments:{}}));if(status.kbId!==kbId)throw new Error('Discovery KB identity differs');};
try{
  let results={kbId,queries:{},scanStates:{}};
  try{results=JSON.parse(await readFile(output,'utf8'));if(results.kbId!==kbId)throw new Error('Saved discovery KB differs');results.scanStates??={};}catch(e){if(e.code!=='ENOENT')throw e;}
  for(const query of queries){
    await check();
    if(results.queries[query]&&(!results.scanStates[query]||results.scanStates[query].complete)){console.log(JSON.stringify({query,status:'cached',matches:results.queries[query].length}));continue;}
    let cursor=results.scanStates[query]?.cursor,limit=30;const found=results.queries[query]??[];
    do{
      let r;
      for(const size of [...new Set([limit,10,5])]){
        try{r=unpack(await reader.callTool({name:'remnote_search',arguments:{query,limit:size,depth:0,contentMode:'none',view:'standard',ancestorDepth:4,...(cursor?{cursor}:{})}}));limit=size;break;}
        catch(e){if(!/Request timeout: search/.test(String(e))||size===5)throw e;console.log(JSON.stringify({query,status:'retry-smaller-page',limit:size,captured:found.length}));await check();}
      }
      if(r.truncated)throw new Error('Discovery snapshot truncated');
      if(r.hasMore&&!r.nextCursor)throw new Error('Discovery cursor missing');
      await check();found.push(...r.results);cursor=r.hasMore?r.nextCursor:undefined;
      results.queries[query]=found;results.scanStates[query]={complete:!cursor,...(cursor?{cursor}:{})};await atomicJSON(output,results);
      console.log(JSON.stringify({query,scannedMatches:found.length,hasMore:r.hasMore}));
    }while(cursor);
    console.log(JSON.stringify({query,matches:found.length,documents:found.filter(x=>x.remType==='document').length}));
  }
}finally{await reader.close();await identity.close();}
