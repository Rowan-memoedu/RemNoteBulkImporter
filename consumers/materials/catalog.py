"""Editorial website catalogs, separate from unchanged source page bodies."""
import copy

from .common import load,require,save,file_sha


def organize(structure,plan,aliases):
    result=copy.deepcopy(structure);original=result['documents'];old={d['id']:d for d in original}
    pages={d['id']:d for d in original if d['basis']=='source_pages'}
    path_to_id={a['source_page']:a['doc'] for a in result['atoms']}
    containers=plan.get('containers',[]);placements=plan.get('pages',[])
    require(isinstance(containers,list) and isinstance(placements,list),'Catalog requires containers/pages arrays')
    added=[];ids=set(old)
    for item in containers:
        require(isinstance(item.get('id'),str) and item['id'].startswith('catalog-') and item['id'] not in ids,'Catalog container ID must be new and begin catalog-')
        require(isinstance(item.get('title'),str) and item['title'].strip(),'Catalog title missing')
        ids.add(item['id']);added.append({'id':item['id'],'title':item['title'],'parent':item.get('parent'),'start':0,'end':0,'title_atom':None,'basis':'editorial_catalog'})
    mapped={}
    for item in placements:
        path=aliases.get(item.get('path'),item.get('path'));pid=path_to_id.get(path)
        require(pid in pages and pid not in mapped,'Unknown/duplicate catalog page placement')
        parent=item.get('parent');parent=path_to_id.get(aliases.get(parent,parent),parent)
        require(parent is None or parent in ids,'Catalog parent is missing')
        mapped[pid]=parent
    require(set(mapped)==set(pages),'Catalog must place every unique source page exactly once')
    for pid,parent in mapped.items():pages[pid]['parent']=parent
    retained=[*added,*pages.values()]
    require(all(d['parent'] is None or d['parent'] in {x['id'] for x in retained} for d in retained),'Catalog parent references an obsolete source folder')
    children={}
    for d in retained:children.setdefault(d['parent'],[]).append(d)
    ordered=[];seen=set()
    def visit(parent):
        for d in children.get(parent,[]):
            require(d['id'] not in seen,'Cyclic catalog');seen.add(d['id']);ordered.append(d);visit(d['id'])
    visit(None);require(len(seen)==len(retained),'Cyclic/unreachable catalog')
    result['documents']=ordered
    require(result['atoms']==structure['atoms'] and result['groups']==structure['groups'],'Catalog changed source content')
    return result


def apply_catalog(structure,path,aliases,folder):
    result=organize(structure,load(path),aliases)
    result['catalog_sha256']=file_sha(path)
    save(folder/'catalog-plan.json',{'source':str(path),'sha256':file_sha(path),'plan':load(path)})
    return result


def audit_catalog(structure,aliases,folder):
    receipt=load(folder/'catalog-plan.json')
    require(structure['catalog_sha256']==receipt['sha256']==file_sha(receipt['source']),'Catalog plan changed after preparation')
    require(load(receipt['source'])==receipt['plan'],'Frozen catalog plan differs from original')
    base={**structure,'documents':[d for d in structure['documents'] if d['basis']!='editorial_catalog']}
    expected=organize(base,receipt['plan'],aliases)
    require(expected['documents']==structure['documents'],'Website catalog differs from the complete editorial plan')
