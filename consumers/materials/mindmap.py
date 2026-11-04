"""Vector PDF mind maps: source text/images and explicit connector topology.

This adapter never guesses a hierarchy from OCR reading order. Unsupported or
ambiguous connector graphs stop before package generation. Original page views
also retain embedded screenshots and non-text vector artwork.
"""
from __future__ import annotations

import collections
import copy
import html
import math
from pathlib import Path

from .common import file_sha, load, require, save, sha


def near(a,b,tolerance=.8):
    return math.dist(a,b)<=tolerance


def path_segments(items):
    segments=[]
    for item in items:
        if item[0]=='l':segments.append((tuple(item[1]),tuple(item[2])))
        elif item[0]=='c':
            p=list(item[1:]);previous=tuple(p[0])
            for step in range(1,17):
                t=step/16;current=tuple((1-t)**3*p[0][j]+3*(1-t)**2*t*p[1][j]+3*(1-t)*t*t*p[2][j]+t**3*p[3][j] for j in (0,1))
                segments.append((previous,current));previous=current
    return segments


def path_contains(point,items):
    crossings=0
    for a,b in path_segments(items):
        if (a[1]>point[1])!=(b[1]>point[1]) and point[0]<(b[0]-a[0])*(point[1]-a[1])/(b[1]-a[1])+a[0]:crossings+=1
    return bool(crossings%2)


def path_distance(point,items):
    """Distance to inert PDF paths, including outlined-stroke export shapes."""
    best=float('inf')
    for a,b in path_segments(items):
        vx,vy=b[0]-a[0],b[1]-a[1];length=vx*vx+vy*vy
        t=max(0,min(1,((point[0]-a[0])*vx+(point[1]-a[1])*vy)/length)) if length else 0
        best=min(best,math.dist(point,(a[0]+t*vx,a[1]+t*vy)))
    return best


def page_graph(page):
    drawings=page.get_drawings()
    widths=collections.Counter(round(d['width'],3) for d in drawings
        if d.get('width') and d['type']=='s' and len(d['items'])==1 and d['items'][0][0] in ('c','l'))
    require(widths,'PDF has no vector connectors; use a verified visual/OCR graph adapter')
    width=widths.most_common(1)[0][0]
    selected=[(i,d) for i,d in enumerate(drawings) if d.get('width') and abs(d['width']-width)<.001]
    boxes=[{'id':f'shape-{i}','bbox':list(d['rect']),'drawing':i,'box':True,'parts':[]} for i,d in selected
           if (len(d['items'])>=4 or d['items'][0][0]=='re') and d['rect'].height>5 and d['rect'].width>10]
    roots=[b for b in boxes if drawings[b['drawing']].get('fill') and
           max(drawings[b['drawing']]['fill'])-min(drawings[b['drawing']]['fill'])>.1]
    require(len(roots)==1,'Mind-map root is not uniquely identified by its filled vector shape')
    nodes={b['id']:b for b in boxes}; points=[]; edges=[]; owner={}
    def point(p):
        p=tuple(p)
        for b in boxes:
            x0,y0,x1,y1=b['bbox']
            if x0-.8<=p[0]<=x1+.8 and y0-.8<=p[1]<=y1+.8:return b['id']
        for key,value in points:
            if near(p,value):return key
        key='point-'+str(len(points));points.append((key,p));return key
    for i,d in selected:
        if len(d['items'])!=1 or d['items'][0][0] not in ('c','l'):continue
        item=d['items'][0];a,b=item[1],item[-1];pa,pb=point(a),point(b)
        if pa==pb:continue
        horizontal=max(p.y for p in item[1:])-min(p.y for p in item[1:])<.15
        nid=f'line-{i}' if horizontal and pa not in nodes and pb not in nodes else None
        if nid:nodes[nid]={'id':nid,'bbox':list(d['rect']),'drawing':i,'box':False,'parts':[]}
        edges.append((pa,pb,nid,i))
    # Some PDF exporters expand thick connectors into narrow closed outlines.
    # Recover only the two existing graph endpoints touched by that actual
    # painted path; bounding-box overlap alone never establishes a connection.
    bridges=[]
    selected_ids={i for i,d in selected}
    for i,d in enumerate(drawings):
        if i in selected_ids or len(d['items'])<4 or d['rect'].height<5:continue
        if not d.get('fill') or max(d['fill'])>.15:continue
        rect=d['rect'];touched=[]
        candidates=list(points)+[(b['id'],(x,y)) for b in boxes for x,y in
            [(b['bbox'][0],(b['bbox'][1]+b['bbox'][3])/2),(b['bbox'][2],(b['bbox'][1]+b['bbox'][3])/2)]]
        for key,value in candidates:
            if rect.x0-width*2<=value[0]<=rect.x1+width*2 and rect.y0-width*2<=value[1]<=rect.y1+width*2 and (path_contains(value,d['items']) or path_distance(value,d['items'])<width*2):
                touched.append(key)
        touched=sorted(set(touched))
        if len(touched)==2:
            edges.append((*touched,None,i));bridges.append(i)
    # Collapse each underlined label into a vertex. Other curves remain edges.
    # A junction with three incident paths is a real branch even when its
    # parent and one child share a baseline. Contracting that junction would
    # turn the child label into part of its parent and flatten its siblings.
    degree=collections.Counter(p for a,b,_,_ in edges for p in (a,b))
    representative={};expanded=[]
    def find(x):
        while x in representative:x=representative[x]
        return x
    for a,b,nid,_ in edges:
        if nid:
            original_a,original_b=a,b;a,b=find(a),find(b)
            # Exporters may split one underline into adjacent flat Béziers.
            # Merge only endpoint-connected collinear segments, retaining all
            # source drawing ordinals; never infer an edge from proximity alone.
            for original,old in ((original_a,a),(original_b,b)):
                if degree[original]<=2 and old in nodes:
                    prior=nodes.pop(old);current=nodes[nid]
                    current['bbox']=[min(current['bbox'][0],prior['bbox'][0]),min(current['bbox'][1],prior['bbox'][1]),max(current['bbox'][2],prior['bbox'][2]),max(current['bbox'][3],prior['bbox'][3])]
                    current.setdefault('merged_drawings',[]).extend([prior['drawing'],*prior.get('merged_drawings',[])])
                if degree[original]<=2:representative[old]=nid
            expanded.extend([(original_a,nid,None,0),(nid,original_b,None,0)])
        else:expanded.append((a,b,None,0))
    adjacent=collections.defaultdict(set)
    for a,b,nid,i in expanded:
        a,b=find(a),find(b)
        if a!=b:adjacent[a].add(b);adjacent[b].add(a)
    root=roots[0]['id'];parents={root:None};queue=[root];cross=[]
    for current in queue:
        for other in sorted(adjacent[current]):
            if other==parents[current]:continue
            if other in parents:
                cross.append(sorted([current,other]));continue
            parents[other]=current;queue.append(other)
    require(not cross,'Mind map contains cycles/cross links; explicit graph references are required')
    disconnected=[(nid,nodes[nid]['bbox']) for nid in set(nodes)-set(parents)]
    require(not disconnected,f'Disconnected vector labels on page {page.number+1}: {disconnected[:12]}')
    # Text blocks can contain two labels side-by-side. Group only vertically
    # adjacent lines with the same left edge, retaining each original line.
    parts=[]
    for bi,block in enumerate(page.get_text('dict')['blocks']):
        if block['type']==1:
            parts.append({'id':f'image-{bi}','kind':'image','bbox':list(block['bbox']),'block':bi,'bytes':block['image'],'ext':block['ext']})
            continue
        groups=[]
        for li,line in enumerate(block.get('lines',[])):
            text=''.join(s['text'] for s in line['spans']);bbox=list(line['bbox'])
            if not text.strip():continue
            part={'id':f'text-{bi}-{li}','kind':'text','bbox':bbox,'text':text}
            if groups and abs(groups[-1][-1]['bbox'][0]-bbox[0])<2 and 0<bbox[1]-groups[-1][-1]['bbox'][1]<30:
                groups[-1].append(part)
            else:groups.append([part])
        for group in groups:
            bbox=[min(p['bbox'][0] for p in group),min(p['bbox'][1] for p in group),max(p['bbox'][2] for p in group),max(p['bbox'][3] for p in group)]
            parts.append({'id':'+'.join(p['id'] for p in group),'kind':'text','bbox':bbox,'text':'\n'.join(p['text'] for p in group),'line_ids':[p['id'] for p in group]})
    unresolved=[]
    for part in parts:
        x0,y0,x1,y1=part['bbox'];candidates=[]
        # Standalone arrow captions can have a filled label background, without
        # belonging to the dominant branch graph. Keep them at page level.
        annotation=part['kind']=='text' and any(d['type']=='f' and d.get('fill') and min(d['fill'])>.95 and
            d['rect'].x0-2<=x0 and x1<=d['rect'].x1+2 and d['rect'].y0-2<=y0 and y1<=d['rect'].y1+2 and
            not any(not n['box'] and abs(n['bbox'][1]-d['rect'].y1)<2 and n['bbox'][0]-7<=x0 and x1<=n['bbox'][2]+7 for n in nodes.values())
            for d in drawings)
        if annotation:part['detached_caption']=True;unresolved.append(part);continue
        for node in nodes.values():
            a,b,c,d=node['bbox']
            if node['box']:
                if a-1<=x0 and x1<=c+1 and b-1<=y0 and y1<=d+1:candidates.append((0,node['id']))
            elif a-7<=x0 and x1<=c+7 and -1<=b-y1:
                candidates.append((b-y1+1,node['id']))
        candidates.sort()
        if not candidates or len(candidates)>1 and abs(candidates[0][0]-candidates[1][0])<.1:
            unresolved.append(part);continue
        nodes[candidates[0][1]]['parts'].append(part)
    # Empty connecting labels are topology only, not invented prose nodes.
    kept={nid for nid,n in nodes.items() if n['parts'] or nid==root}
    relation={}
    for nid in kept:
        parent=parents[nid]
        while parent is not None and parent not in kept:parent=parents[parent]
        relation[nid]=parent
    return {'root':root,'nodes':nodes,'parents':relation,'unresolved':unresolved,
            'parts':parts,'connector_width':width,'drawings':len(drawings),'edges':len(edges),'outlined_connectors':bridges}


def extract_mindmap(source,folder):
    import pymupdf
    folder.mkdir(parents=True,exist_ok=True);assets=folder/'source-assets';assets.mkdir(exist_ok=True)
    atoms=[];documents=[];groups=[];evidence=[]
    def atom(value,doc,page,source_node,source_parts=None,**extra):
        row={'id':f'a{len(atoms):06d}','page':page,'block':source_node,'source_type':'vector-mindmap',
             'field':'text','heading_level':0,'base':str(folder),'doc':doc,'source_parts':source_parts or [],**value,**extra}
        atoms.append(row);return len(atoms)-1
    with pymupdf.open(source) as pdf:
        for pi,page in enumerate(pdf):
            graph=page_graph(page);nodes=graph['nodes'];parents=graph['parents'];root=graph['root']
            # All text must belong to a proved branch. Detached images are kept
            # as page supplements with exact source coordinates and bytes.
            missing=[p['id'] for p in graph['unresolved'] if p['kind']=='text' and not p.get('detached_caption')]
            require(not missing,f'Unassigned source text on page {pi+1}: {missing[:12]}')
            for part in graph['parts']:
                if part['kind']=='image':
                    target=assets/(sha(part['bytes'])+'.'+part['ext']);target.write_bytes(part['bytes']);part['path']=str(target);part['sha256']=file_sha(target)
            def label(nid):return '\n'.join(p['text'] for p in nodes[nid]['parts'] if p['kind']=='text')
            require(label(root),'Root shape lacks source text')
            children=collections.defaultdict(list)
            for nid,parent in parents.items():
                if parent is not None:children[parent].append(nid)
            # Clockwise-independent curriculum order: source coordinates within
            # each side, with right branches before left branches.
            for parent,items in children.items():
                mid=(nodes[parent]['bbox'][0]+nodes[parent]['bbox'][2])/2
                items.sort(key=lambda nid:(nodes[nid]['bbox'][0]<mid,nodes[nid]['bbox'][1],nodes[nid]['bbox'][0]))
            page_doc=f'map-page-{pi+1}';start=len(atoms)
            require(all(p['kind']=='text' for p in nodes[root]['parts']),'Root image needs an explicit mixed-media title')
            title_index=atom({'kind':'text','text':label(root)},page_doc,pi+1,root,[p['id'] for p in nodes[root]['parts']])
            view=assets/f'page-{pi+1}.png';page.get_pixmap(matrix=pymupdf.Matrix(1.5,1.5)).save(view)
            atom({'kind':'image','text':'','path':str(view),'sha256':file_sha(view)},page_doc,pi+1,'original-page')
            for part in graph['unresolved']:
                value={'kind':'text','text':part['text']} if part['kind']=='text' else {'kind':'image','text':'','path':part['path'],'sha256':part['sha256']}
                atom({**value,'bbox_pdf':part['bbox']},page_doc,pi+1,part['id'],[part['id']])
            documents.append({'id':page_doc,'title':label(root),'parent':None,'start':start,'end':len(atoms),'title_atom':atoms[title_index]['id'],'basis':'vector_graph'})
            def emit(nid,doc):
                node=nodes[nid];parts=sorted(node['parts'],key=lambda p:(round(p['bbox'][1]/10),p['bbox'][0]))
                content=[]
                for part in parts:
                    if part['kind']=='text':content.append(html.escape(part['text']).replace('\n','<br>'))
                    else:content.append('<img src="'+html.escape(Path(part['path']).resolve().as_uri(),quote=True)+'">')
                begin=atom({'kind':'html','text':' '.join(content),'plain':label(nid),'bbox_pdf':node['bbox']},doc,pi+1,nid,[p['id'] for p in parts])
                for child in children[nid]:emit(child,doc)
                if len(atoms)-1>begin:groups.append({'parent':begin,'through':len(atoms)-1})
            for nid in children[root]:
                doc=f'map-page-{pi+1}-{nid}';begin=len(atoms);emit(nid,doc)
                title=label(nid) or '图示'
                # A chapter root may contain images; keep its complete label as
                # a body node rather than flattening the picture into a title.
                only_text=all(p['kind']=='text' for p in nodes[nid]['parts'])
                documents.append({'id':doc,'title':title,'parent':page_doc,'start':begin,'end':len(atoms),'title_atom':atoms[begin]['id'] if only_text else None,'basis':'vector_graph'})
            evidence.append({'page':pi+1,'root':root,'parents':parents,'nodes':[{k:v for k,v in n.items() if k!='parts'}|{'parts':[p['id'] for p in n['parts']]} for n in nodes.values()],
                             'source_parts':[{k:v for k,v in p.items() if k!='bytes'} for p in graph['parts']],
                             'supplement_images':[p['id'] for p in graph['unresolved'] if p['kind']=='image'],'detached_captions':[p['id'] for p in graph['unresolved'] if p['kind']=='text'],'connector_width':graph['connector_width'],'connector_edges':graph['edges'],'page_view_sha256':file_sha(view)})
    extraction={'schema':'material-source/1','source':str(source),'source_sha256':file_sha(source),
                'atoms':[{k:v for k,v in a.items() if k!='doc'} for a in atoms],
                'metadata':{'adapter':'vector-mindmap','pages':len(evidence)},'coverage':{'fields':len(atoms),'pages':len(evidence)}}
    structure={'basis':'vector_connector_graph','provider':'pdf_vector_geometry','contents_pages':[],
               'documents':documents,'atoms':atoms,'groups':groups}
    save(folder/'extraction.json',extraction);save(folder/'structure.json',structure)
    save(folder/'mindmap-graph.json',{'source_sha256':extraction['source_sha256'],'pages':evidence})
    return extraction,structure


def audit_mindmap(source,folder):
    """Reconstruct topology/text from original PDF, independently of the package."""
    import pymupdf
    receipt=load(folder/'mindmap-graph.json');require(receipt['source_sha256']==file_sha(source),'Mind-map source changed')
    extraction=load(folder/'extraction.json');structure=load(folder/'structure.json')
    require(extraction['metadata']['adapter']=='vector-mindmap','Wrong mind-map extraction adapter')
    require(extraction['source_sha256']==file_sha(source),'Mind-map extraction source changed')
    with pymupdf.open(source) as pdf:
        require(len(pdf)==len(receipt['pages']),'Mind-map page omitted')
        for page,record in zip(pdf,receipt['pages']):
            graph=page_graph(page)
            require(graph['parents']==record['parents'],'Mind-map connector topology changed')
            expected=[{k:v for k,v in p.items() if k not in ('bytes','path','sha256')} for p in graph['parts']]
            actual=[{k:v for k,v in p.items() if k not in ('path','sha256')} for p in record['source_parts']]
            require(expected==actual,'Mind-map text/image inventory changed')
            page_atoms=[a for a in structure['atoms'] if a['page']==record['page']]
            covered=[key for a in page_atoms for key in a.get('source_parts',[])]
            require(collections.Counter(covered)==collections.Counter(p['id'] for p in graph['parts']),'Mind-map source part omitted or duplicated')
            by_source={a['block']:a for a in page_atoms if a['block'] in graph['parents']}
            require(set(by_source)==set(graph['parents']),'Mind-map graph node omitted or duplicated')
            require(sum(a['block'] in graph['parents'] for a in page_atoms)==len(by_source),'Mind-map graph node duplicated')
            for nid,a in by_source.items():
                require(set(a.get('source_parts',[]))=={p['id'] for p in graph['nodes'][nid]['parts']},'Mind-map label moved to a different source node')
            docs={d['id']:d for d in structure['documents']}
            for index,a in enumerate(structure['atoms']):
                if a not in page_atoms or a['block'] not in graph['parents']:continue
                source_parent=graph['parents'][a['block']]
                ancestors=[g['parent'] for g in structure['groups'] if g['parent']<index<=g['through']]
                if source_parent is None:
                    require(docs[a['doc']]['parent'] is None,'Mind-map page root moved')
                elif source_parent==graph['root']:
                    require(docs[a['doc']]['parent']==by_source[source_parent]['doc'] and not ancestors,'Mind-map primary branch changed')
                else:
                    require(ancestors and structure['atoms'][max(ancestors)]['block']==source_parent,'Mind-map branch parent differs from source connectors')
            # Compare exact source label construction and media bytes, not just
            # a cached manifest that could drift together with the candidate.
            for a in page_atoms:
                parts_by_id={p['id']:p for p in graph['parts']}
                parts=[parts_by_id[k] for k in a.get('source_parts',[])]
                if a['kind']=='html':
                    chunks=[]
                    for p in parts:
                        if p['kind']=='text':chunks.append(html.escape(p['text']).replace('\n','<br>'))
                        else:
                            path=folder/'source-assets'/(sha(p['bytes'])+'.'+p['ext'])
                            require(file_sha(path)==sha(p['bytes']),'Mind-map embedded image changed')
                            chunks.append('<img src="'+html.escape(path.resolve().as_uri(),quote=True)+'">')
                    require(a['text']==' '.join(chunks),'Mind-map source label changed')
                elif a['kind']=='text':require(a['text']=='\n'.join(p['text'] for p in parts),'Mind-map source text changed')
                elif parts:
                    require(len(parts)==1 and file_sha(a['path'])==sha(parts[0]['bytes']),'Mind-map detached image changed')
                else:
                    require(a['block']=='original-page' and file_sha(a['path'])==sha(page.get_pixmap(matrix=pymupdf.Matrix(1.5,1.5)).tobytes('png')),'Mind-map original page view changed')
    require(all(a.get('source_type')=='vector-mindmap' for a in structure['atoms']),'Invented mind-map source')
    report={'status':'VALIDATED','pages':len(receipt['pages']),
            'graph_nodes':sum(len(p['parents']) for p in receipt['pages']),
            'source_parts':sum(len(p['source_parts']) for p in receipt['pages']),
            'supplement_images':sum(len(p['supplement_images']) for p in receipt['pages'])}
    save(folder/'mindmap-audit.json',report);return report
