import {stableJSON,sha256} from './package.mjs';
/** JSON may omit the legacy SDK's own undefined image geometry keys. Try only
 * those semantically identical key-presence states against the ORIGINAL hash.
 * The caller first validates exact asset bytes/geometry through rich-compat. */
export async function imageTransportHashMatches(normalized,expected){
  async function matchesUnsetMetadata(value){
    if(await sha256(stableJSON(value))===expected)return true;
    // SDK reads can add own undefined cId/onlyAudio fields which were absent
    // in the parser response. Defined values are never removed or changed.
    for(let mask=0;mask<4;mask++){
      const projected=value.map(p=>{
        if(p?.i!=='i')return p;
        const copy={...p};
        ['cId','onlyAudio'].forEach((key,bit)=>{
          if(copy[key]!==undefined)return;
          if(mask&(1<<bit))copy[key]=undefined;else delete copy[key];
        });
        return copy;
      });
      if(await sha256(stableJSON(projected))===expected)return true;
    }
    return false;
  }
  if(await matchesUnsetMetadata(normalized))return true;
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
    if(await matchesUnsetMetadata(candidate))return true;
    // The native parser may also return an own undefined percent field. JSON
    // removes it, just as it removes undefined width/height. A defined percentage
    // is never changed, and the stored original hash is still mandatory.
    const optional=candidate.map(p=>p?.i==='i'&&p.percent===undefined?{...p,percent:undefined}:p);
    if(await matchesUnsetMetadata(optional))return true;
  }
  return false;
}
