/** Preserve non-imported child Rems; every owned child and its relative order
 * remain mandatory. Never treat a misplaced owned Rem as an external child. */
export function ownedChildren(actual,wanted,owned,allowExternal=false){
  const external=actual.filter(id=>!owned.has(id));
  const checked=allowExternal?actual.filter(id=>owned.has(id)):actual;
  if(new Set(actual).size!==actual.length||checked.length!==wanted.length||checked.some((id,i)=>id!==wanted[i]))return null;
  return external;
}
export function preserveExternalSlots(actual,wanted,owned){
  let next=0;
  if(actual.filter(id=>owned.has(id)).length!==wanted.length)throw new Error('Owned child count changed');
  return actual.map(id=>owned.has(id)?wanted[next++]:id);
}
