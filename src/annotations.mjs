const branchId=id=>id===null?'rbi.annotations.root':`${id}.annotations`;
export function annotateDocuments(plan){
  const nodes=structuredClone(plan.nodes),ids=new Set(nodes.map(n=>n.id));
  for(const parent of [null,...plan.nodes.filter(n=>n.document).map(n=>n.id)]){
    const id=branchId(parent);
    if(ids.has(id))throw new Error(`Annotation branch already exists: ${id}`);
    nodes.push({id,parentId:parent,document:false,text:[{kind:'text',value:'批注'}]});
    for(let i=1;i<=2;i++)nodes.push({id:`${id}.blank${i}`,parentId:id,document:false,text:[{kind:'text',value:''}]});
  }
  const result={...plan,nodes};auditAnnotations(result);return result;
}
export function auditAnnotations(plan){
  const children=new Map();for(const n of plan.nodes){if(!children.has(n.parentId))children.set(n.parentId,[]);children.get(n.parentId).push(n);}
  const plain=(n,value)=>!n.document&&n.text.length===1&&n.text[0].kind==='text'&&n.text[0].value===value;
  const parents=[null,...plan.nodes.filter(n=>n.document).map(n=>n.id)];
  for(const parent of parents){
    const branches=(children.get(parent)??[]).filter(n=>plain(n,'批注'));
    if(branches.length!==1)throw new Error(`Document needs exactly one annotation branch: ${parent}`);
    const blanks=children.get(branches[0].id)??[];
    if(blanks.length!==2||!blanks.every(n=>plain(n,'')&&!(children.get(n.id)?.length)))throw new Error(`Annotation needs exactly two empty leaves: ${parent}`);
  }
  return {documents:parents.length,annotationBranches:parents.length,emptyLeaves:parents.length*2};
}

/** Retain existing branches/IDs; add annotations to owned document-level
 * content, then place every annotation branch first without changing text. */
export function topAnnotationLayout(plan){
  const nodes=structuredClone(plan.nodes),byId=new Map(nodes.map(n=>[n.id,n]));
  const children=new Map();const add=n=>{if(!children.has(n.parentId))children.set(n.parentId,[]);children.get(n.parentId).push(n);};nodes.forEach(add);
  const plain=(n,value)=>!n.document&&n.text.length===1&&n.text[0].kind==='text'&&n.text[0].value===value;
  const docs=[null,...nodes.filter(n=>n.document).map(n=>n.id)];
  const direct=nodes.filter(n=>!n.document&&!plain(n,'批注')&&(n.parentId===null||byId.get(n.parentId)?.document)).map(n=>n.id);
  const branchByParent=new Map();
  for(const parent of [...docs,...direct]){
    const found=(children.get(parent)??[]).filter(n=>plain(n,'批注'));if(found.length>1)throw new Error('Duplicate annotation branches');
    let branch=found[0];
    if(!branch){const id=branchId(parent);if(byId.has(id))throw new Error(`Annotation ID collision: ${id}`);branch={id,parentId:parent,document:false,text:[{kind:'text',value:'批注'}]};nodes.push(branch);byId.set(id,branch);add(branch);
      for(let i=1;i<=2;i++){const blank={id:`${id}.blank${i}`,parentId:id,document:false,text:[{kind:'text',value:''}]};if(byId.has(blank.id))throw new Error('Empty annotation ID collision');nodes.push(blank);byId.set(blank.id,blank);add(blank);}
    }
    const blanks=children.get(branch.id)??[];if(blanks.length!==2||blanks.some(n=>!plain(n,'')||children.get(n.id)?.length))throw new Error('Existing annotation leaves must remain exactly two empty nodes');
    branchByParent.set(parent,branch.id);
  }
  const ordered=[];const walk=parent=>{const siblings=children.get(parent)??[],first=branchByParent.get(parent);for(const n of [...siblings.filter(n=>n.id===first),...siblings.filter(n=>n.id!==first)]){ordered.push(n);walk(n.id);}};walk(null);
  if(ordered.length!==nodes.length)throw new Error('Annotation layout lost unreachable nodes');
  return {...plan,nodes:ordered};
}
export function auditTopAnnotations(plan){
  const children=new Map(),byId=new Map(plan.nodes.map(n=>[n.id,n]));for(const n of plan.nodes){if(!children.has(n.parentId))children.set(n.parentId,[]);children.get(n.parentId).push(n);}
  const plain=(n,value)=>n&&!n.document&&n.text.length===1&&n.text[0].kind==='text'&&n.text[0].value===value;
  const docs=[null,...plan.nodes.filter(n=>n.document).map(n=>n.id)],direct=plan.nodes.filter(n=>!n.document&&!plain(n,'批注')&&(n.parentId===null||byId.get(n.parentId)?.document)).map(n=>n.id);
  for(const parent of [...docs,...direct]){const rows=children.get(parent)??[],branch=rows[0];if(!plain(branch,'批注')||rows.filter(n=>plain(n,'批注')).length!==1)throw new Error(`Annotation is not first: ${parent}`);const blanks=children.get(branch.id)??[];if(blanks.length!==2||blanks.some(n=>!plain(n,'')||children.get(n.id)?.length))throw new Error('Annotation requires two empty leaves');}
  return {documents:docs.length,directContentNodes:direct.length,annotationBranches:docs.length+direct.length,emptyLeaves:2*(docs.length+direct.length),position:'first'};
}
