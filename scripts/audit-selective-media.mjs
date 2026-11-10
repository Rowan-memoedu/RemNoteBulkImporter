import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StreamableHTTPClientTransport} from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
const argv=process.argv.slice(2),recordMissingMedia=argv.includes('--record-missing-media');
const [packagePath,kbId,output,mappingFile]=argv.filter(x=>x!=='--record-missing-media'),plan=JSON.parse(await readFile(packagePath,'utf8')),mapping=mappingFile?JSON.parse(await readFile(mappingFile,'utf8')).mapping:null;
const reader=new Client({name:'selective-media-audit',version:'1.0.0'}),identity=new Client({name:'selective-media-identity',version:'1.0.0'});
const unpack=r=>{if(r.isError)throw new Error(r.content[0].text);return r.structuredContent??JSON.parse(r.content[0].text);};
await reader.connect(new StreamableHTTPClientTransport(new URL('http://127.0.0.1:43101/mcp')));await identity.connect(new StreamableHTTPClientTransport(new URL('http://127.0.0.1:43106/mcp')));
await mkdir(output,{recursive:true});
try{
 const evidence=[],unavailable=[];
 for(const n of plan.nodes){if(![...(n.text??[]),...(n.backText??[])].some(x=>x?.i==='i'))continue;
  const live=unpack(await identity.callTool({name:'bulk_import_status',arguments:{}}));if(live.kbId!==kbId)throw new Error('Media audit KB differs');
  const remId=mapping?mapping[n.id]:n.id;if(!remId)throw new Error('Image Rem not mapped');
  const note=unpack(await reader.callTool({name:'remnote_read_note',arguments:{remId,depth:0,contentMode:'none',includeMediaMetadata:true}}));
  for(const field of ['text','backText']){
   const expected=(n[field]??[]).filter(x=>x?.i==='i'),media=(note.media??[]).filter(x=>x.field===field);if(expected.length!==media.length)throw new Error(`Image count differs in ${n.id}`);
   for(let index=0;index<media.length;index++){
    const r=await reader.callTool({name:'remnote_get_media',arguments:{remId,field,mediaId:media[index].mediaId,maxInlineBytes:10485760}});
    if(r.isError){const error=r.content[0].text;if(recordMissingMedia&&/^Error: Media file missing:/.test(error)){unavailable.push({sourceRemId:n.id,remId,field,index,error});continue;}throw new Error(error);}
    const content=r.content.find(c=>c.type==='image');if(!content)throw new Error('Managed image bytes not returned');const bytes=Buffer.from(content.data,'base64'),sha256=createHash('sha256').update(bytes).digest('hex');
    const file=`${n.id}-${field}-${index}.${content.mimeType==='image/png'?'png':content.mimeType==='image/jpeg'?'jpg':'bin'}`;await writeFile(path.join(output,file),bytes);evidence.push({sourceRemId:n.id,remId,field,index,bytes:bytes.length,sha256,mimeType:content.mimeType});
   }
  }
 }
 const status=unavailable.length?'incomplete-missing-media':'verified-managed-bytes';
 await writeFile(path.join(output,'audit.json'),JSON.stringify({status,kbId,evidence,unavailable},null,2));console.log(JSON.stringify({status,kbId,images:evidence.length,unavailable,evidence}));
}finally{await reader.close();await identity.close();}
