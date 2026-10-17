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
