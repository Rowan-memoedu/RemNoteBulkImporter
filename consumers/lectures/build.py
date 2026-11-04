"""Deterministic lecture overlay; generic extraction and rich conversion stay intact."""
import base64
import copy
import json
import re
from pathlib import Path

from materials.common import file_sha, load, require, save, sha
from materials.render import markdown_text
from .contract import question_source
from .pixels import OriginalPages
from .plan import KINDS, validate_plan
from .cleanup import excluded_indices,masks

VERSION='lecture/2'


def implementation():
    return sha(b''.join(p.name.encode()+p.read_bytes() for p in sorted(Path(__file__).parent.glob('*.py'))))


def compose(base,folder,plan,title,contract,contract_identity):
    extraction=load(base/'extraction.json');original=load(base/'package.json')
    structure=load(base/'structure.json');runs=load(base/'rich-atoms.json')
    validate_plan(plan,extraction,title,contract)
    atoms=extraction['atoms'];nodes=[];assets=copy.deepcopy(original.get('assets',{}));mapping={};crops=[];questions=[];body_records=[]
    removed=excluded_indices(plan,atoms);exclusions=masks(plan,extraction)
    pages=OriginalPages(extraction['source'],folder/'original-pages',exclusions)
    def node(ident,parent,text,document=False):
        nodes.append({'id':ident,'parentId':parent,'document':document,'text':text});return ident
    def literal(ident,parent,text,document=False):return node(ident,parent,[{'kind':'text','value':text}],document)
    def images(ident,parent,selected,label=''):
        segments=[{'kind':'text','value':label+'\n'}] if label else []
        for region in pages.regions(atoms,selected):
            aid='img-'+region['sha256'];assets[aid]={'mime':'image/png','base64':base64.b64encode(region['data']).decode(),'sha256':region['sha256']}
            if segments and segments[-1]['kind']=='image':segments.append({'kind':'text','value':'\n'})
            segments.append({'kind':'image','assetId':aid})
            crops.append({k:v for k,v in region.items() if k!='data'}|{'node':ident,'asset':aid,'atoms':[i for i in selected if atoms[i]['page']==region['page']]})
        return node(ident,parent,segments)
    def question(q,parent,ident,container=True):
        answer=q['answer'];status='有答案' if answer else '无答案'
        if container:literal(ident,parent,('例题 '+q['label'] if q['label'] else '例题')+'（'+status+'）')
        else:ident=parent
        stem_id=images(ident+'-stem',ident,q['stem'],'题面')
        answer_id=None
        if answer:
            # Keep the whole annotated local question with its solution. Detached
            # answer rows retain their original shared context and position too.
            selected=sorted(set(answer+(q['local'] if set(answer)&set(q['local']) else [])))
            answer_id=images(ident+'-answer',ident,selected,'答案')
        source,label,requirement=question_source(q,title,atoms,contract)
        literal(ident+'-source',ident,'题源：'+label)
        if source.get('difficulty'):literal(ident+'-difficulty',ident,'难度系数：'+source['difficulty'])
        if requirement:literal(ident+'-requirement',ident,'要求：'+requirement)
        for i in q['local']:mapping.setdefault(atoms[i]['id'],stem_id if i in q['stem'] else answer_id)
        questions.append({'node':ident,'stem':stem_id,'answer':answer_id,'status':status,'source':source,'requirement':requirement,'local':q['local'],'stemAtoms':q['stem'],'answerAtoms':answer})
    chapter_at={c['at']:c for c in plan['chapters']};block_at={b['first']:b for b in plan['blocks']};stack=[]
    chapters=plan['chapters']
    root_heading=chapters[0]['at'] if chapters and chapters[0]['title']==title and chapters[0]['level']==1 and all(c['level']>1 for c in chapters[1:]) else None
    for i in sorted(set(chapter_at)|set(block_at)):
        if i in chapter_at:
            c=chapter_at[i]
            if i==root_heading:
                # The importer creates and audits this exact title as its root.
                # Do not nest a duplicate book Document above real chapters.
                mapping[atoms[i]['id']]='__root__'
                continue
            while stack and stack[-1][0]>=c['level']:stack.pop()
            ident=f'lecture-ch-{i:06d}'
            literal(ident,stack[-1][1] if stack else None,c['title'],True)
            stack.append((c['level'],ident));mapping[atoms[i]['id']]=ident
            continue
        b=block_at[i];ident=f'lecture-b-{i:06d}';parent=stack[-1][1] if stack else None
        name=KINDS[b['kind']]
        if b['kind']=='question':name+='（'+('有答案' if b['questions'][0]['answer'] else '无答案')+'）'
        literal(ident,parent,name)
        if b['kind']=='question':question(b['questions'][0],ident,ident,False);continue
        occupied={x for q in b['questions'] for x in q['local']};starts={}
        for q in b['questions']:starts.setdefault(min(q['local']),[]).append(q)
        pending=[]
        def flush():
            if not pending:return
            indices=list(pending);pending.clear();body_id=f'lecture-image-{indices[0]:06d}'
            images(body_id,ident,indices)
            for x in indices:mapping[atoms[x]['id']]=body_id
            body_records.append({'node':body_id,'atoms':indices,'original':True})
        for x in range(b['first'],b['last']+1):
            if x in removed:continue
            if x in starts:
                flush()
                for ordinal,q in enumerate(starts[x]):question(q,ident,f'lecture-q-{x:06d}-{ordinal}')
            if x in occupied:continue
            if b['original']:
                pending.append(x);continue
            a=atoms[x];ancestors=[g['parent'] for g in structure['groups'] if g['parent']<x<=g['through'] and b['first']<=g['parent'] and g['parent'] not in occupied]
            owner=atoms[max(ancestors)]['id'] if ancestors else ident
            node(a['id'],owner,copy.deepcopy(runs[a['id']]));mapping[a['id']]=a['id']
            body_records.append({'node':a['id'],'atoms':[x],'original':False})
        flush()
    # Retain generic native references even when their source node was wrapped.
    redirect={old:mapping[aid] for aid,old in original['provenance']['atomToNode'].items() if aid in mapping}
    ids={n['id'] for n in nodes}
    for n in nodes:
        for s in n['text']:
            if s['kind']=='ref' and s['targetId'] not in ids:
                require(s['targetId'] in redirect,'Reference needs a verified lecture mapping')
                s['targetId']=redirect[s['targetId']]
    used={s['assetId'] for n in nodes for s in n['text'] if s['kind']=='image'}
    assets={k:v for k,v in assets.items() if k in used}
    pages.close()
    return {'schemaVersion':1,'packageId':'lecture.'+extraction['source_sha256'][:24]+'.v1','title':title,'nodes':nodes,'assets':assets,
        'provenance':{'materialAdapter':'lecture','sourceSha256':extraction['source_sha256'],'atomToNode':mapping,
            'lecture':{'version':VERSION,'implementation':implementation(),'base':str(base.resolve()),'basePackageSha256':file_sha(base/'package.json'),
                'sharedContract':contract_identity,'planSha256':sha(json.dumps(plan,ensure_ascii=False,sort_keys=True)),
                'features':sorted(plan['features']),'crops':crops,'questions':questions,'body':body_records,
                'excludedAtoms':sorted(removed),'masks':exclusions}}}


def write_outputs(bundle,folder):
    directory=folder/'markdown/_assets';directory.mkdir(parents=True,exist_ok=True)
    for asset in bundle['assets'].values():
        suffix={'image/png':'.png','image/jpeg':'.jpg','image/webp':'.webp','image/gif':'.gif'}[asset['mime']]
        target=directory/(asset['sha256']+suffix);data=base64.b64decode(asset['base64'])
        if not target.exists():target.write_bytes(data)
        require(file_sha(target)==asset['sha256'],'Exported image differs')
    save(folder/'package.json',bundle)
    nodes=bundle['nodes'];byid={n['id']:n for n in nodes};depths={None:0};lines=['# '+bundle['title'],'']
    for n in nodes:
        depths[n['id']]=depths[n['parentId']]+1
        text=markdown_text(n['text'],folder).replace('\n','\n'+'  '*depths[n['id']])
        lines.append('  '*(depths[n['id']]-1)+'- '+text)
    (folder/'markdown/全书大纲.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    index=['# '+bundle['title'],''];paths={}
    for d in [n for n in nodes if n['document']]:
        title=''.join(s.get('value','') for s in d['text']);safe=re.sub(r'[<>:"/\\|?*\x00-\x1f]',' ',title)[:75].strip(' .') or '章节'
        path=folder/'markdown/分篇'/(d['id']+' '+safe+'.md');path.parent.mkdir(exist_ok=True)
        output=['# '+title,''];descendants={d['id']}
        for n in nodes:
            if n['parentId'] not in descendants:continue
            descendants.add(n['id']);depth=depths[n['id']]-depths[d['id']]-1
            output.append('  '*depth+'- '+markdown_text(n['text'],folder,'../_assets/').replace('\n','\n'+'  '*(depth+1)))
        path.write_text('\n'.join(output)+'\n',encoding='utf8');paths[d['id']]=str(path)
        index.append('  '*(depths[d['id']]-1)+'- ['+title+'](<'+path.relative_to(folder/'markdown').as_posix()+'>)')
    (folder/'markdown/阅读目录.md').write_text('\n'.join(index)+'\n',encoding='utf8');save(folder/'markdown-map.json',paths)
    from materials.publish_snapshot import render_preview
    render_preview(folder)
