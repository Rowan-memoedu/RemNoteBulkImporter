import { declareIndexPlugin, type ReactRNPlugin } from '@remnote/plugin-sdk';
import { runImport } from './engine.mjs';
import { sdkAdapter } from './sdk-adapter';
import { VERSION } from './version.mjs';
import { sdkMonitor } from './sdk-monitor.mjs';
import { restructureImport } from './restructure.mjs';
import { snapshotNative, copyNativeBatch, SELECTIVE_PROTOCOL } from './selective-native.mjs';

let ws: WebSocket|undefined;
let timer: ReturnType<typeof setTimeout>|undefined;
let stopped=false,busy=false,pause=false;
const address='ws://127.0.0.1:43106/bridge';
const send = (msg:unknown) => { if(ws?.readyState===WebSocket.OPEN) ws.send(JSON.stringify(msg)); };

async function activate(plugin:ReactRNPlugin) {
  stopped=false;
  const monitor=sdkMonitor();
  const mediaPending=new Map<string,{resolve:(value:any)=>void,reject:(error:any)=>void}>();
  await plugin.app.registerCommand({id:'bulk-import-status',name:'批量导入：查看连接状态',quickCode:'rbi',action:async()=>{
    await plugin.app.toast(busy?'批量导入正在运行':ws?.readyState===WebSocket.OPEN?'批量导入已连接本地服务':'批量导入未连接本地服务');
  }});
  const connect=async()=>{
    if(stopped)return;
    const token=(globalThis as typeof globalThis & {__REMNOTE_TRANSPORT_TOKEN?:string}).__REMNOTE_TRANSPORT_TOKEN;
    if(!token){if(!stopped)timer=setTimeout(connect,2500);return;}
    if(stopped)return;
    ws=new WebSocket(address);
    ws.onopen=()=>send({type:'hello',token,pluginId:'remnote-bulk-importer',version:VERSION,busy});
    ws.onmessage=async(event)=>{
      let m:any;
      try { m=JSON.parse(event.data); } catch { return; }
      if(m.type==='media-reply'){
        const entry=mediaPending.get(m.id);if(entry){mediaPending.delete(m.id);m.error?entry.reject(new Error(m.error)):entry.resolve(m.result);}return;
      }
      if(m.type==='pause'){pause=true;return;}
      if(m.type==='status'){
        try {const kb=await plugin.kb.getCurrentKnowledgeBaseData();send({type:'reply',id:m.id,result:{kbId:kb._id,kbName:kb.name,busy,selectiveProtocol:SELECTIVE_PROTOCOL,diagnostics:monitor.snapshot()}});}
        catch(e){send({type:'reply',id:m.id,error:String(e)});}return;
      }
      if(m.type==='selective-read'||m.type==='selective-copy'){
        if(busy||monitor.snapshot().restartRequired){send({type:'reply',id:m.id,error:'Plugin is busy or fenced after a timeout'});return;}
        busy=true;
        try{const fn=m.type==='selective-read'?snapshotNative:copyNativeBatch;send({type:'reply',id:m.id,result:await fn(plugin,m,monitor)});}
        catch(e){send({type:'reply',id:m.id,error:e instanceof Error?e.message:String(e)});}finally{busy=false;}return;
      }
      if(m.type!=='import')return;
      if(monitor.snapshot().restartRequired){send({type:'reply',id:m.id,error:'Reload the plugin after an SDK timeout before resuming'});return;}
      if(busy){send({type:'reply',id:m.id,error:'An import is already running in this plugin'});return;}
      busy=true;pause=false;send({type:'reply',id:m.id,result:{accepted:true}});
      try {
        const verifyMedia=(assetId:string,url:string)=>new Promise((resolve,reject)=>{
          const id=crypto.randomUUID();mediaPending.set(id,{resolve,reject});send({type:'media-verify',id,jobId:m.jobId,assetId,url});
        });
        const execute=m.request.baseHash?restructureImport:runImport;
        const result=await execute(sdkAdapter(plugin,m.request.kbId,monitor,verifyMedia,m.plan.assets??{}),m.plan,m.request,{
          progress:(p:any)=>send({type:'progress',jobId:m.jobId,...p}),
          shouldPause:()=>pause||stopped||ws?.readyState!==WebSocket.OPEN,
          batchSize:16,yieldMs:30,
        });
        send({type:'result',jobId:m.jobId,result});
        await plugin.app.toast(result.status==='complete'?'批量导入完成，回读校验通过':'批量导入已暂停，可继续同一任务');
      } catch(e) {send({type:'failure',jobId:m.jobId,error:e instanceof Error?e.message:String(e)});}
      finally{busy=false;}
    };
    ws.onerror=()=>{};
    ws.onclose=()=>{pause=true;for(const p of mediaPending.values())p.reject(new Error('Media verification connection closed'));mediaPending.clear();if(!stopped)timer=setTimeout(connect,2500);};
  };
  connect();
}
async function deactivate(){stopped=true;pause=true;if(timer)clearTimeout(timer);ws?.close();}
declareIndexPlugin(activate,deactivate);
