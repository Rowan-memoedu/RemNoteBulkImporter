/** Append-only paged checkpoint storage. Metadata commits last, so a failed
 * page/meta write cannot make uncommitted entries appear completed on resume.
 * The legacy full checkpoint is retained as a migration/recovery source.
 */
export function checkpointStore(storage,libraryId,{pageSize=256}={}) {
  const saved=new Map();
  const key=(hash)=>`rbi2:${libraryId}:${hash}`;
  async function load(hash){
    const meta=await storage.getLocal(`${key(hash)}:meta`);
    if(!meta){saved.delete(hash);return await storage.getLocal(`rbi:${libraryId}:${hash}`);}
    if(meta.format!==2)throw new Error('Unsupported checkpoint storage format');
    const result={...meta.state,mapping:{},expected:{}};
    for(const [field,count] of [['mapping',meta.mappingCount],['expected',meta.expectedCount]]){
      const entries=[];
      for(let page=0;page<Math.ceil(count/pageSize);page++){
        const rows=await storage.getLocal(`${key(hash)}:${field}:${page}`);
        if(!Array.isArray(rows))throw new Error(`Missing ${field} checkpoint page ${page}`);
        entries.push(...rows);
      }
      if(entries.length<count)throw new Error('Checkpoint page is incomplete');
      result[field]=Object.fromEntries(entries.slice(0,count));
    }
    saved.set(hash,{mapping:meta.mappingCount,expected:meta.expectedCount});
    return result;
  }
  async function save(hash,state){
    const previous=saved.get(hash)??{mapping:0,expected:0};
    const counts={};
    for(const field of ['mapping','expected']){
      const rows=Object.entries(state[field]??{});counts[field]=rows.length;
      if(rows.length<previous[field])throw new Error('Refusing checkpoint truncation');
      if(rows.length!==previous[field]){
        const start=Math.floor(previous[field]/pageSize);
        for(let page=start;page<Math.ceil(rows.length/pageSize);page++)await storage.setLocal(`${key(hash)}:${field}:${page}`,rows.slice(page*pageSize,(page+1)*pageSize));
      }
    }
    const {mapping,expected,...smallState}=state;
    await storage.setLocal(`${key(hash)}:meta`,{format:2,mappingCount:counts.mapping,expectedCount:counts.expected,state:smallState});
    saved.set(hash,counts);
  }
  return {load,save};
}
