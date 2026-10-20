/** The SDK represents Markdown mailto links as Link-Rem references. Derive
 * those exact targets by compiling the immutable source segment with that same
 * SDK. Never ignore an observed reference or infer a target from its label. */
export async function expectedReferenceTargets(node,mapping,{parse,refs}){
  const result=node.text.filter(s=>s.kind==='ref').map(s=>mapping[s.targetId]);
  for(const segment of node.text){
    if(segment.kind==='markdown' && /mailto:/i.test(segment.value)){
      result.push(...await refs(await parse(segment.value)));
    }
  }
  return [...new Set(result)];
}
