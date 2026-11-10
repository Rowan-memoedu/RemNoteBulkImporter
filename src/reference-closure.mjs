// Source-side completeness is checked before constructing an import package.
// Already copied nodes are anchors, never permission to discard their children.
export function referenceClosure({nodes, roots, contextRoots=[], existingIds=[]}) {
  const graph=new Map(nodes.map(n=>[n.id,n]));
  if(graph.size!==nodes.length)throw Error('Duplicate source snapshot ID');
  const existing=new Set(existingIds),included=new Set(),expanded=new Set();
  const generated=new Set(),requiredEdges=[],externalReferences=[];
  const get=id=>{const n=graph.get(id);if(!n)throw Error(`Missing source snapshot: ${id}`);return n;};
  const isGenerated=n=>n.type===6&&n.portalType!==0;
  const visit=(id,reason,from)=>{
    const n=get(id);
    if(isGenerated(n)){generated.add(id);return;}
    if(from)requiredEdges.push({from,to:id,reason});
    included.add(id);
    if(expanded.has(id))return;
    expanded.add(id);
    const aliases=new Set((n.aliases??[]).map(a=>a.id));
    for(const child of n.children??[])if(!aliases.has(child))visit(child,'child',id);
    for(const field of ['refs','tags','sources','portal'])for(const target of n[field]??[]){
      if(existing.has(target)&&!included.has(target)){
        externalReferences.push({from:id,to:target,reason:field});
      }else visit(target,field,id);
    }
  };
  for(const id of [...roots,...contextRoots])visit(id,'root');
  // Ancestors carry original headings and provenance without importing unrelated siblings.
  for(const id of included){
    let parent=get(id).parentId;const seen=new Set([id]);
    while(parent){
      if(seen.has(parent))throw Error(`Source parent cycle: ${parent}`);
      seen.add(parent);
      if(existing.has(parent)&&!included.has(parent))break;
      const n=get(parent);
      if(isGenerated(n))throw Error(`Content cannot be attached below a generated query: ${id}`);
      included.add(parent);
      parent=n.parentId;
    }
    // Set iteration also processes newly discovered ancestor dependencies and their paths.
    if(!expanded.has(id)){
      const n=get(id);
      for(const field of ['refs','tags','sources','portal'])for(const target of n[field]??[]){
        if(existing.has(target)&&!included.has(target))externalReferences.push({from:id,to:target,reason:field});
        else visit(target,field,id);
      }
    }
  }
  const ordered=[],ordering=new Set(),done=new Set();
  const order=id=>{
    if(done.has(id))return;
    if(ordering.has(id))throw Error(`Source parent cycle: ${id}`);
    ordering.add(id);const n=get(id);
    if(included.has(n.parentId))order(n.parentId);
    ordering.delete(id);done.add(id);ordered.push(n);
  };
  // Walk original sibling lists before fallback IDs to retain their source order.
  const descend=id=>{order(id);for(const child of get(id).children??[])if(included.has(child)&&!done.has(child))descend(child);};
  for(const id of included)if(!included.has(get(id).parentId))descend(id);
  for(const id of included)order(id);
  const added=ordered.filter(n=>!existing.has(n.id));
  const addedIds=new Set(added.map(n=>n.id));
  const packageExternalReferences=[];
  for(const n of added)for(const field of ['refs','tags','sources','portal'])for(const target of n[field]??[])
    if(!addedIds.has(target))packageExternalReferences.push({from:n.id,to:target,reason:field});
  return {
    sourceNodes:ordered,
    newNodes:added.map(n=>({...structuredClone(n),parentId:addedIds.has(n.parentId)?n.parentId:null})),
    attachments:added.filter(n=>!addedIds.has(n.parentId)).map(n=>({sourceId:n.id,sourceParentId:n.parentId})),
    existingAnchors:ordered.filter(n=>existing.has(n.id)).map(n=>({sourceId:n.id,sourceParentId:n.parentId})),
    coverage:{fullRoots:[...new Set([...roots,...contextRoots])],expandedIds:[...expanded],generatedQueriesExcluded:[...generated],requiredEdges,externalReferences,packageExternalReferences}
  };
}
