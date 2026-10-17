/** Describe SDK validation failures without logging source text or image bytes. */
export function describeRich(rich){
  if(!Array.isArray(rich))return {array:false,type:typeof rich,keys:rich&&typeof rich==='object'?Object.keys(rich):[]};
  return {array:true,length:rich.length,items:rich.map((value,index)=>{
    if(typeof value==='string')return {index,type:'string',chars:value.length};
    if(!value||typeof value!=='object')return {index,type:typeof value,value};
    return {index,type:value.i,fields:Object.fromEntries(Object.entries(value).map(([key,v])=>[key,
      typeof v==='string'?(key==='i'?v:{type:'string',chars:v.length,...(key==='url'?{prefix:v.slice(0,24)}:{})}):
      v===null||typeof v==='number'||typeof v==='boolean'?v:{type:typeof v,array:Array.isArray(v)}]))};
  })};
}
