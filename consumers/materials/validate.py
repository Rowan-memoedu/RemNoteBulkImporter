"""Independent source-to-native validation, separate from content production."""
import base64
import json
import re
import subprocess
from pathlib import Path

from bs4 import BeautifulSoup
from markdown_it import MarkdownIt

from .common import REPO, file_sha, load, require, save, sha
from .structure import validate_groups
from .source_images import math_audit, source_representation, image_aliases


def markdown_visible_with_math(text, parser):
    """Project prose formatting as a whole; math must not split ** wrappers."""
    from .render import math_split,inline_markup
    formulas={};pieces=[]
    for kind,value,_ in math_split(text):
        if kind=='latex':
            marker='RBICOVERAGEMATH'+str(len(formulas))+'TOKEN'
            require(marker not in text,'Ambiguous source coverage marker')
            formulas[marker]=value;pieces.append(marker)
        else:pieces.append(value)
    visible=BeautifulSoup(inline_markup(''.join(pieces),parser),'html.parser').get_text()
    for marker,value in formulas.items():visible=visible.replace(marker,value)
    return visible


def inspect_package(path):
    code="import{readFile}from'node:fs/promises';import{inspectPackage}from'./src/package.mjs';console.log(JSON.stringify(await inspectPackage(JSON.parse(await readFile(process.argv[1],'utf8')))));"
    result=subprocess.run(['node','--input-type=module','-e',code,str(path)],cwd=REPO,capture_output=True,text=True,encoding='utf-8',timeout=120)
    require(result.returncode==0,'Package contract failed: '+result.stderr[-1200:])
    return json.loads(result.stdout)


def validate_body_parent(atom,index,groups,native,documents,mapping):
    if native['id'] in documents:return
    ancestors=[g['parent'] for g in groups if g['parent']<index<=g['through']]
    expected=mapping[f'a{max(ancestors):06d}'] if ancestors else atom['doc']
    require(native['parentId']==expected,'Body outline parent changed: '+atom['id'])


def validate_image_fallbacks(extraction,structure,bundle,runs,folder):
    from .render import Assets, native_table, segments, prepare_inline_assets
    records=bundle['provenance'].get('sourceImageFallbacks',[])
    fallbacks={r['atom']:r for r in records};atoms=structure['atoms']
    require(len(fallbacks)==len(records),'Duplicate image fallback evidence')
    require(set(fallbacks)<={a['id'] for a in atoms},'Unknown image fallback atom')
    failed_runs=[];assets=Assets(folder)
    for i,a in enumerate(atoms):
        if a['id'] not in fallbacks:continue
        record=fallbacks[a['id']];base=a.get('base',str(Path(extraction['source']).parent))
        prepare_inline_assets(a,assets,base)
        require(a['kind'] in ('text','equation','table'),'Invalid image fallback kind')
        try:
            candidate=native_table(a['text'],assets,base)[0] if a['kind']=='table' else segments(a['text'],assets,base,equation=a['kind']=='equation')
        except ValueError as error:
            require(str(error)==record['error']=='Unclosed mathematical delimiter','Unproved conversion fallback')
        else:
            failed_runs.append({'id':a['id'],'text':candidate})
        value,expected=source_representation(extraction,structure,i,folder,assets,record['error'])
        require(record==expected and runs[a['id']]==value,'Source image fallback evidence changed')
        asset=bundle['assets'][record['assetId']]
        require(asset['sha256']==assets.records[record['assetId']]['sha256'],'Source image fallback digest changed')
    if failed_runs:
        audit=math_audit(failed_runs,folder,'fallback-proof-math')
        failures={e['nodeId']:e['error'] for e in audit['details']}
        require(set(failures)=={n['id'] for n in failed_runs},'Fallback replaced a valid formula')
        for aid,error in failures.items():require(fallbacks[aid]['error']==error,'Fallback error evidence changed')
    aliases=image_aliases(atoms,structure,runs,records)
    mapping=bundle['provenance']['atomToNode']
    for aid,target in aliases.items():require(mapping[aid]==mapping[target],'Source image alias changed')
    remaining=[mapped for aid,mapped in mapping.items() if aid not in aliases]
    require(len(set(remaining))==len(remaining),'Source atoms merged without image evidence')
    return fallbacks


def validate(folder):
    if (folder/'lecture-source.json').exists():
        from lectures.validate import validate as validate_lecture
        return validate_lecture(folder)
    extraction=load(folder/'extraction.json');structure=load(folder/'structure.json');bundle=load(folder/'package.json')
    if extraction.get('metadata',{}).get('adapter')=='publish-snapshot':
        from .publish_snapshot import audit_snapshot
        audit_snapshot(Path(extraction['source']),folder)
    elif extraction.get('metadata',{}).get('adapter')=='vector-mindmap':
        from .mindmap import audit_mindmap
        audit_mindmap(Path(extraction['source']),folder)
    elif extraction.get('metadata',{}).get('adapter')=='mindmap-readable':
        from .mindmap_readable import audit_readable
        audit_readable(Path(extraction['source']),folder)
    require(file_sha(extraction['source'])==extraction['source_sha256'],'Original source changed')
    if extraction.get('raw_ocr_sha256'):
        require(file_sha(folder/'ocr-blocks.json')==extraction['raw_ocr_sha256'],'Raw OCR evidence changed')
    original={a['id']:a for a in extraction['atoms']};atoms=structure['atoms']
    require(len(atoms)==len(original),'Source atom count changed')
    for a in atoms:
        require({k:v for k,v in a.items() if k!='doc'}==original[a['id']],f'Source atom changed {a["id"]}')
    validate_groups(structure['groups'],atoms,set(range(len(atoms))))
    mapping=bundle['provenance']['atomToNode'];nodes={n['id']:n for n in bundle['nodes']};runs=load(folder/'rich-atoms.json')
    require(set(mapping)==set(original),'Unmapped or invented source atom')
    fallbacks=validate_image_fallbacks(extraction,structure,bundle,runs,folder)
    documents={d['id']:d for d in structure['documents']}
    parser=MarkdownIt('commonmark',{'html':True}).enable('strikethrough')
    normal=lambda x:re.sub(r'\s+','',x)
    formulas=0
    for index,a in enumerate(atoms):
        native=nodes[mapping[a['id']]]
        validate_body_parent(a,index,structure['groups'],native,documents,mapping)
        require(native['text']==runs[a['id']],'Built native text differs from frozen conversion')
        if a['id'] in fallbacks:pass  # Pixel/hash and concrete conversion failure proved above.
        elif a['kind'] in ('text','equation'):
            from .render import math_split
            if a['kind']=='equation':math_split(a['text'],strict=True)
            expected=a['text'] if a.get('literal') else markdown_visible_with_math(a['text'],parser)
            actual=''.join(BeautifulSoup(parser.renderInline(s['value']),'html.parser').get_text() if s['kind']=='markdown' else s.get('value','') for s in native['text'])
            require(normal(expected)==normal(actual),f'Source text/formula changed: {a["id"]}')
        elif a['kind']=='html':
            from .render import protect_html_math
            source_html=protect_html_math(a['text'])
            for math_node in source_html.select('.math-tex'):
                value=math_node.get_text();math_node.replace_with(value[2:-2])
            expected=source_html.get_text()
            actual=''.join(BeautifulSoup(parser.renderInline(s['value']),'html.parser').get_text() if s['kind']=='markdown' else s.get('value','') for s in native['text'])
            require(normal(expected)==normal(actual),'HTML visible text changed: '+a['id'])
        elif a['kind']=='code':require(native['text']==[{'kind':'code','value':a['text']}],'Code bytes changed')
        elif a['kind']=='image':require(file_sha(a['path'])==a['sha256'],'Source image changed')
        formulas+=sum(s['kind']=='latex' for s in native['text'])
        require(native['document']==(native['id'] in documents),'Unexpected body Document')
    for d in structure['documents']:
        require(nodes[d['id']]['parentId']==d['parent'] and nodes[d['id']]['document'],'Directory hierarchy changed')
        # A source heading may become the Document title while a separately OCR'd
        # chapter-number prefix remains its first body node. Body order is exact;
        # the absorbed heading is checked independently by the atom mapping above.
        sequence=list(dict.fromkeys(mapping[a['id']] for a in atoms[d['start']:d['end']] if mapping[a['id']]!=d['id']))
        actual=[n['id'] for n in bundle['nodes'] if n['id'] in set(sequence)]
        require(actual==sequence,'Source ordering changed')
    for asset in bundle['assets'].values():require(sha(base64.b64decode(asset['base64'],validate=True))==asset['sha256'],'Asset digest mismatch')
    info=inspect_package(folder/'package.json')
    result=subprocess.run(['node',str(REPO/'consumers/audit-math.mjs'),str(folder/'package.json'),str(folder/'math-validation.json')],capture_output=True,text=True,encoding='utf-8',timeout=120)
    require(result.returncode==0,'Math validation process failed')
    math=load(folder/'math-validation.json')
    require(math['errors']==0,f'Native formulas failed KaTeX: {math["errors"]}; see math-validation.json')
    for target in load(folder/'markdown-map.json').values():require(Path(target).is_file(),'Missing Markdown document')
    report={'status':'VALIDATED','source_sha256':extraction['source_sha256'],'package_sha256':file_sha(folder/'package.json'),
            'source_atoms':len(atoms),'source_fields':extraction['coverage'].get('fields'),
            'directory_documents':len(documents),'leaf_documents':sum(not any(x['parent']==d for x in documents.values()) for d in documents),
            'native_formulas':math['count'],'all_source_atoms_mapped':True,'info':info}
    if fallbacks:report['source_image_fallbacks']=len(fallbacks)
    save(folder/'validation.json',report)
    return report
