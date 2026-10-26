/** Compatibility for RemNote's automatic natural-size image metadata. This is a
 * read-only projection: unknown images, resized geometry and all other fields
 * remain strict. Neither source text nor live RichText is rewritten.
 */
export async function naturalDimensions(asset){
  const bytes=Uint8Array.from(atob(asset.base64),x=>x.charCodeAt(0)),view=new DataView(bytes.buffer);
  if(asset.mime==='image/png'&&bytes.length>=24)return {width:view.getUint32(16),height:view.getUint32(20)};
  if(asset.mime==='image/gif'&&bytes.length>=10)return {width:view.getUint16(6,true),height:view.getUint16(8,true)};
  if(typeof createImageBitmap==='function'){
    const bitmap=await createImageBitmap(new Blob([bytes],{type:asset.mime}));
    const size={width:bitmap.width,height:bitmap.height};bitmap.close();return size;
  }
  throw new Error('Cannot establish natural image dimensions for SDK compatibility');
}
export function imageReadbackCompatibility(assets,{loadCached,verify}){
  const sources=new Map(),verified=new Set(),dimensions=new Map();let cachedLoaded=false;
  for(const [id,asset] of Object.entries(assets))sources.set(`data:${asset.mime};base64,${asset.base64}`,{id,asset,original:{i:'i',url:`data:${asset.mime};base64,${asset.base64}`}});
  function register(id,original){
    const asset=assets[id];
    if(!asset||original?.i!=='i'||!original.url?.startsWith('%LOCAL_FILE%'))throw new Error('Cannot register image outside source assets');
    const prior=sources.get(original.url);
    if(prior&&prior.asset.sha256!==asset.sha256)throw new Error('Managed image URL maps to different source bytes');
    sources.set(original.url,{id,asset,original:structuredClone(original)});
  }
  async function source(url){
    if(!sources.has(url)&&!cachedLoaded){
      for(const [id,asset] of Object.entries(assets)){
        const original=await loadCached(asset.sha256);
        if(original?.i==='i'&&original.url?.startsWith('%LOCAL_FILE%'))register(id,original);
      }
      cachedLoaded=true;
    }
    const value=sources.get(url);if(!value)throw new Error('Readback image is outside source assets');
    if(url.startsWith('%LOCAL_FILE%')&&!verified.has(url)){await verify(value.id,url);verified.add(url);}
    return value;
  }
  async function input(rich){
    const result=[];
    for(const part of rich){
      if(!part||typeof part!=='object'||part.i!=='i'){result.push(part);continue;}
      const {asset,original}=await source(part.url);let image=part;
      if(part.percent===0&&original.percent===undefined){
        image={...part};delete image.percent;
        if(original.width===undefined&&original.height===undefined&&(part.width!==undefined||part.height!==undefined)){
          if(!dimensions.has(asset.sha256))dimensions.set(asset.sha256,await naturalDimensions(asset));
          const natural=dimensions.get(asset.sha256);
          if(part.width!==natural.width||part.height!==natural.height)throw new Error('Image geometry differs from verified natural size; refusing compatibility projection');
          if(part.url.startsWith('data:')){image.width=undefined;image.height=undefined;}
          else {delete image.width;delete image.height;}
        }
      }
      // The legacy SDK image builder explicitly emitted undefined geometry;
      // JSON transport drops those own keys even before natural-size loading.
      if(part.url.startsWith('data:')&&image.width===undefined&&image.height===undefined)image={...image,width:undefined,height:undefined};
      result.push(image);
    }
    return result;
  }
  async function automaticGeometryVariants(rich){
    // The native parser's cached object may itself gain natural dimensions after
    // first display. Only offer byte-verified automatic states, and let the
    // caller compare every candidate against the ORIGINAL checkpoint hash.
    const eligible=new Set();
    for(let i=0;i<rich.length;i++){
      const part=rich[i];if(part?.i!=='i'||part.percent!==0||part.width===undefined||part.height===undefined)continue;
      const {asset}=await source(part.url);
      if(!dimensions.has(asset.sha256))dimensions.set(asset.sha256,await naturalDimensions(asset));
      const natural=dimensions.get(asset.sha256);
      if(part.width===natural.width&&part.height===natural.height)eligible.add(i);
    }
    if(!eligible.size)return [];
    return ['dimensions','both','percent'].map(mode=>rich.map((part,i)=>{
      if(!eligible.has(i))return part;const projected={...part};
      if(mode!=='percent'){delete projected.width;delete projected.height;}
      if(mode!=='dimensions')delete projected.percent;
      return projected;
    }));
  }
  return {input,register,automaticGeometryVariants};
}
