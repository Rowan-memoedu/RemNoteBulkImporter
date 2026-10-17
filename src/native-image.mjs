/** Use the official Markdown image parser to upload bytes, preserving its entire
 * returned image object. Image builders alone retain a large data URL in the Rem.
 */
export async function nativeImage(assetId,asset,{get,set,parse,verify}) {
  let image=await get(asset.sha256);
  if(!image){
    const rich=await parse(`![Course diagram](data:${asset.mime};base64,${asset.base64})`);
    const meaningful=rich.filter(p=>typeof p==='string'?p.trim():p.i!=='m'||p.text?.trim());
    if(meaningful.length!==1 || meaningful[0]?.i!=='i' || !meaningful[0].url?.startsWith('%LOCAL_FILE%'))throw new Error('Official image parser did not return one managed local image');
    image=meaningful[0];
    await verify(assetId,image.url);
    await set(asset.sha256,image);
  } else {
    if(image.i!=='i'||!image.url?.startsWith('%LOCAL_FILE%'))throw new Error('Invalid managed-image cache entry');
    await verify(assetId,image.url);
  }
  return structuredClone(image);
}
