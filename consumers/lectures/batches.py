"""Bound model context by original chapter boundaries, with resumable receipts."""
import copy
from materials.common import load,require,save
from materials.producer import Producer
from .plan import make_plan,validate_plan
from .cleanup import normalize


def bounded_plan(extraction,base,folder,title,contract,model,previews,role=None):
    atoms=extraction['atoms'];structure=load(base/'structure.json')
    docs=structure['documents'];byid={d['id']:d for d in docs}
    def level(d):return 1+level(byid[d['parent']]) if d.get('parent') else 1
    outline=[{'title':d['title'],'level':level(d),'first':d['start']} for d in docs]
    if len(atoms)<=400 and len(previews)<=10:
        return make_plan(extraction,folder,title,contract,Producer(folder,model),previews,{'source_role':role} if role else None)
    edges=sorted({0,len(atoms)}|{d['start'] for d in docs}|{d['end'] for d in docs})
    spans=[]
    for a,z in zip(edges,edges[1:]):
        if a==z:continue
        pages={x['page'] for x in atoms[a:z]}
        require(z-a<=900 and len(pages)<=14,'Original chapter exceeds bounded semantic context; refine source chapter boundaries before production')
        if spans and z-spans[-1][0]<=300 and atoms[z-1]['page']-atoms[spans[-1][0]]['page']<7:
            spans[-1][1]=z
        else:spans.append([a,z])
    result={'chapters':[],'blocks':[],'features':[],'unresolved':[],'excluded':[]}
    for ordinal,(a,z) in enumerate(spans):
        work=folder/'segments'/f'{a:06d}-{z:06d}';work.mkdir(parents=True,exist_ok=True)
        part={**extraction,'atoms':copy.deepcopy(atoms[a:z])}
        pnums=sorted({x['page'] for x in part['atoms']})
        context={'source_role':role,'original_outline':outline,'previous_chapters':result['chapters'][-8:],
                 'source_atom_offset':a,'instruction':'当前只是原讲义片段，章节仍用原目录全局层级；不要创造片段目录或重复前文。整页图可能同时显示前一个或后一个片段的内容；只处理 rows 已给的索引，图中没有当前 rows 的相邻内容会在其他片段处理，不能因这类边界上下文而报遗漏或 unresolved。当前 rows 的题目本身缺少解答时才标记无答案或真实归属疑问。'}
        print(f'LECTURE SEGMENT {ordinal+1}/{len(spans)} original pages {pnums[0]}-{pnums[-1]}',flush=True)
        planned=make_plan(part,work,title,contract,Producer(work,model),[previews[p-1] for p in pnums],context)
        for c in planned['chapters']:c['at']+=a
        for b in planned['blocks']:
            b['first']+=a;b['last']+=a
            for q in b['questions']:
                for key in ('local','stem','answer','source_evidence'):q[key]=[i+a for i in q[key]]
        for e in planned.get('excluded',[]):e['indices']=[i+a for i in e['indices']]
        for key in ('chapters','blocks','excluded'):result[key].extend(planned.get(key,[]))
        result['features']=sorted(set(result['features']+planned['features']))
        save(work/'plan.json',planned)
    result=normalize(result);validate_plan(result,extraction,title,contract);return result
