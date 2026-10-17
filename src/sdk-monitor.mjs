/** A timed-out SDK mutation is never retried in the same plugin instance. */
export function sdkMonitor({timeoutMs=60000,now=()=>Date.now()}={}) {
  const active=new Map();let sequence=0,lastCompleted=null,fault=null,context=null;
  const snapshot=()=>({restartRequired:!!fault,fault,context,active:[...active.values()].map(x=>({...x,elapsedMs:now()-x.startedAt})),lastCompleted});
  async function call(label,operation,limit=timeoutMs){
    if(fault)throw new Error(`SDK instance requires reload after: ${fault}`);
    const id=++sequence,entry={label,startedAt:now()};active.set(id,entry);let timer;
    try{
      const work=Promise.resolve().then(()=>{if(fault)throw new Error('SDK instance requires reload');return operation();});
      const deadline=new Promise((_,reject)=>{timer=setTimeout(()=>{
        fault=`${label} exceeded ${limit} ms; no automatic mutation retry`;
        reject(new Error(fault));
      },limit);});
      const result=await Promise.race([work,deadline]);
      lastCompleted={label,elapsedMs:now()-entry.startedAt};return result;
    }finally{clearTimeout(timer);active.delete(id);}
  }
  return {call,snapshot,setContext:value=>{context={...value};}};
}
