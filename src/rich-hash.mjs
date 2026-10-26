import {stableJSON,sha256} from './package.mjs';
/** JSON may omit the legacy SDK's own undefined image geometry keys. Try only
 * those semantically identical key-presence states against the ORIGINAL hash.
 * The caller first validates exact asset bytes/geometry through rich-compat. */
export async function imageTransportHashMatches(normalized,expected){
  if(await sha256(stableJSON(normalized))===expected)return true;
  const slots=normalized.flatMap((p,i)=>p?.i==='i'&&p.width===undefined&&p.height===undefined?[i]:[]);
  if(!slots.length||slots.length>12)return false;
  const candidate=normalized.map(p=>p&&typeof p==='object'?{...p}:p),limit=2**slots.length;
  // Uniform restored/omitted states are common; mixed cache states follow.
  const masks=[limit-1,0,...Array.from({length:limit-2},(_,i)=>i+1)];
  for(const mask of masks){
    slots.forEach((index,bit)=>{
      if(mask&(2**bit)){candidate[index].width=undefined;candidate[index].height=undefined;}
      else {delete candidate[index].width;delete candidate[index].height;}
    });
    if(await sha256(stableJSON(candidate))===expected)return true;
    // The native parser may also return an own undefined percent field. JSON
    // removes it, just as it removes undefined width/height. A defined percentage
    // is never changed, and the stored original hash is still mandatory.
    const optional=candidate.map(p=>p?.i==='i'&&p.percent===undefined?{...p,percent:undefined}:p);
    if(await sha256(stableJSON(optional))===expected)return true;
  }
  return false;
}
