"""Deterministic authored Markdown outline adapter; shared assets and MCP delivery.

One list item is one Rem, including its paragraphs, equations and code. Mermaid
gets a separate Rem when sharing a list item with prose. Only an initial H1
becomes the import root. No inference, categorization or LLM calls.
Unsupported/ambiguous source structures fail before any RemNote write.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .common import REPO, file_sha, load, require, save


def parse(text, fallback_title):
    lines=text.replace('\r\n','\n').replace('\r','\n').splitlines()
    nodes=[];stack=[];heads=[];title=fallback_title;root_line=None
    current=None;fence=None;display=None
    for number,line in enumerate(lines,1):
        if not line.strip():
            if current is not None:current['parts'].append('')
            continue
        indent=len(line)-len(line.lstrip(' '));body=line[indent:]
        require(not body.startswith('\t'),f'Tab indentation needs an explicit conversion (line {number})')
        if fence or display:
            require(current is not None and indent>=current['column'],f'Unindented block at line {number}')
            current['parts'].append(line[current['column']:])
            if fence and re.fullmatch(re.escape(fence[0])+r'{'+str(len(fence))+r',}\s*',body):fence=None
            elif display and body==display:display=None
            continue
        heading=re.fullmatch(r'(#{1,6})\s+(.+?)(?:\s+#+)?\s*',line)
        bullet=re.match(r'^( *)([-+*]|\d+[.)])( +)(.*)$',line)
        if heading:
            level=len(heading[1]);value=heading[2]
            if not nodes and root_line is None and level==1:
                title=value;root_line=number;current=None;continue
            require(level!=1 or root_line is None,'Multiple H1 roots are ambiguous in outline mode')
            stack=[]
            while heads and heads[-1]['level']>=level:heads.pop()
            current={'id':f'a{len(nodes):06d}','parentId':heads[-1]['id'] if heads else None,
                     'parts':[value],'column':0,'line':number,'level':level}
            heads.append(current);nodes.append(current)
        elif bullet:
            while stack and stack[-1]['indent']>=indent:stack.pop()
            require(not stack or indent>=stack[-1]['column'],f'Ambiguous list indentation at line {number}')
            parent=stack[-1] if stack else heads[-1] if heads else None
            value=bullet[4]
            if bullet[2][0].isdigit():value=bullet[2]+' '+value
            current={'id':f'a{len(nodes):06d}','parentId':parent['id'] if parent else None,
                     'parts':[value],'column':bullet.start(4),'indent':indent,'line':number}
            nodes.append(current);stack.append(current)
        else:
            # A continuation belongs to its actual list item. Parent text after
            # children cannot be represented in the same order as a native Rem.
            if stack:
                owner=next((n for n in reversed(stack) if indent>=n['column']),None)
                require(owner is not None,f'Unowned prose at line {number}')
                require(owner is current,f'Parent continuation after child list at line {number}')
            require(current is not None,f'Outline mode needs a heading/list node before prose (line {number})')
            require(not re.match(r'^(?:>|\|)',body),'Block quotes/tables require the general document adapter')
            current['parts'].append(line[current['column']:])
        # Standalone math/fence delimiters are structural only outside blocks.
        last=current['parts'][-1].strip() if current else ''
        if re.match(r'^(`{3,}|~{3,})([^`~]*)$',last):fence=re.match(r'^(`+|~+)',last)[1]
        elif last in ('$$',r'\['):display='$$' if last=='$$' else r'\]'
    require(not fence and not display,'Unclosed code or display-math block')
    require(nodes,'Empty outline')
    return {'title':title,'rootTitleLine':root_line,'nodes':[
        {'id':n['id'],'parentId':n['parentId'],'text':'\n'.join(n['parts']).strip(),
         'line':n['line']} for n in nodes]}


def rich_text(text,assets,base):
    from .render import segments, math_split
    # The shared HTML converter folds whitespace. Explicit br elements retain
    # authored paragraph/newline boundaries while math stays byte-for-byte TeX.
    result=[];prose=[];code=None;language=None;code_lines=[]
    def flush():
        if not prose:return
        value='\n'.join(prose);parts=[]
        for kind,content,block in math_split(value):
            if kind=='latex':
                delimiter='$$' if block else '$'
                parts.append(delimiter+content+delimiter)
            else:parts.append(content.replace('\n','<br>'))
        result.extend(segments(''.join(parts),assets,base));prose.clear()
    for line in text.split('\n'):
        if code:
            if re.fullmatch(re.escape(code[0])+r'{'+str(len(code))+r',}\s*',line):
                content='\n'.join(code_lines)+'\n'
                result.append({'kind':'mermaid' if language=='mermaid' else 'code','value':content})
                code=None;language=None;code_lines=[]
            else:code_lines.append(line)
        elif match:=re.fullmatch(r'(`{3,}|~{3,})[^`~]*',line):
            flush();code=match[1]
            info=line[len(code):].strip().split(maxsplit=1)
            language=info[0].casefold() if info else None
        else:prose.append(line)
    require(code is None,'Unclosed code fence');flush()
    return result or [{'kind':'text','value':''}]


def outline_nodes(node,runs):
    """The Mermaid widget reads the entire Rem as source, so isolate each fence."""
    chunks=[]
    prose=[]
    for run in runs:
        if run['kind'] != 'mermaid':
            prose.append(run)
            continue
        if prose:
            chunks.append(prose)
            prose=[]
        chunks.append([run])
    if prose:
        chunks.append(prose)
    for index,chunk in enumerate(chunks):
        yield {'id':node['id'] if index==0 else f"{node['id']}.part-{index}",
               'parentId':node['parentId'] if index==0 else node['id'],
               'document':False,'text':chunk}


def convert(source,folder,title=None):
    from .render import Assets
    tree=parse(source.read_text(encoding='utf-8-sig'),source.stem)
    assets=Assets(folder)
    nodes=[];source_lines={}
    for node in tree['nodes']:
        for part in outline_nodes(node,rich_text(node['text'],assets,source.parent)):
            nodes.append(part)
            source_lines[part['id']]=node['line']
    bundle={'schemaVersion':1,'packageId':'material.'+file_sha(source)[:24]+'.outline.v1',
            'title':title or tree['title'],'nodes':nodes,'assets':assets.records,
            'provenance':{'sourceSha256':file_sha(source),'structureBasis':'source-outline',
                          'structureProvider':'deterministic','sourceLines':source_lines}}
    return tree,bundle,assets.trace


def prepare(source,folder,title=None,extract_only=False):
    tree,bundle,trace=convert(source,folder,title)
    evidence={'source':str(source),'source_sha256':file_sha(source),'title_override':title,'tree':tree}
    save(folder/'outline-source.json',evidence)
    if extract_only:return {'status':'extracted','nodes':len(tree['nodes'])}
    save(folder/'package.json',bundle);save(folder/'asset-trace.json',trace)
    # An exact original copy is the human-readable outline; paths remain source-relative.
    (folder/'source-outline.md').write_bytes(source.read_bytes())
    report=validate(folder)
    from .publish_snapshot import render_preview
    render_preview(folder)
    save(folder/'run.json',{'source':str(source),'title':bundle['title'],'status':'prepared','validation':report})
    return report


def validate(folder):
    from .validate import inspect_package
    evidence=load(folder/'outline-source.json');source=Path(evidence['source'])
    require(file_sha(source)==evidence['source_sha256'],'Original outline changed')
    # Reparse the original, not a cached candidate; compare every parent, order,
    # text, math mode, newline, image and asset digest. No coverage normalization.
    tree,expected,trace=convert(source,folder,evidence['title_override'])
    require(tree==evidence['tree'],'Frozen outline extraction differs from source')
    bundle=load(folder/'package.json')
    require(bundle==expected,'Outline package differs from original source conversion')
    require(load(folder/'asset-trace.json')==trace,'Source media evidence changed')
    info=inspect_package(folder/'package.json')
    process=subprocess.run(['node',str(REPO/'consumers/audit-math.mjs'),str(folder/'package.json'),str(folder/'math-validation.json')],capture_output=True,text=True,encoding='utf-8',timeout=120)
    require(process.returncode==0,'Math audit failed')
    math=load(folder/'math-validation.json');require(math['errors']==0,'Native outline formula failed KaTeX')
    report={'status':'VALIDATED','source_sha256':evidence['source_sha256'],
            'package_sha256':file_sha(folder/'package.json'),'source_atoms':len(tree['nodes']),
            'directory_documents':0,'native_formulas':math['count'],'all_source_atoms_mapped':True,
            'structure_basis':'source-outline','info':info}
    save(folder/'validation.json',report)
    return report
