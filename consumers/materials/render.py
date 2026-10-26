"""Deterministic native rich text and portable Markdown, with source mapping."""
from __future__ import annotations

import base64
import copy
import html
import io
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup
from markdown_it import MarkdownIt

from .common import HYPER, REPO, file_sha, key, load, require, save, sha

sys.path.insert(0,str(HYPER))
from outline import rich, preview_html, validate_svg
from table_latex import table_latex

MD=MarkdownIt('commonmark',{'html':True}).enable('strikethrough')


def math_split(text, strict=False):
    result=[];pos=0;search=0
    code_spans=[(m.start(),m.end()) for m in re.finditer(r'(`+)([\s\S]*?)\1',text)]
    opening=re.compile(r'(?<!\\)(\$\$|\$)|\\\(|\\\[')
    while match:=opening.search(text,search):
        containing=next((end for begin,end in code_spans if begin<=match.start()<end),None)
        if containing is not None:
            search=containing;continue
        token=match[0];close={'$':'$','$$':'$$',r'\(':r'\)',r'\[':r'\]'}[token]
        end=re.search(r'(?<!\\)'+re.escape(close),text[match.end():])
        if end is None:
            require(not strict and token=='$', 'Unclosed mathematical delimiter')
            break
        at=match.end()+end.start()
        if match.start()>pos:result.append(('text',text[pos:match.start()],False))
        result.append(('latex',text[match.end():at],token in ('$$',r'\[')))
        pos=at+len(close);search=pos
    if pos<len(text):result.append(('text',text[pos:],False))
    return result or [('text',text,False)]


class Assets:
    def __init__(self,folder):
        self.folder=folder;self.records={};self.trace=[];self.anchors={};self.reference_markers={};self.allowed_roots={folder.resolve()};self.aliases={}
        self.directory=folder/'markdown/_assets';self.directory.mkdir(parents=True,exist_ok=True)

    def add(self,url):
        parsed=urlsplit(url)
        if parsed.scheme=='file':
            raw=unquote(parsed.path)
            if re.match(r'^/[A-Za-z]:',raw):raw=raw[1:]
            path=Path(raw)
        else:
            require(not parsed.scheme, 'Remote HTML/Markdown media must be downloaded with the source before import')
            path=Path(unquote(url))
        path=self.aliases.get(path.resolve(),path)
        resolved=path.resolve(strict=True)
        require(any(resolved.is_relative_to(root) for root in self.allowed_roots),'Linked media escapes the local source directory')
        return self.add_file(resolved)

    def add_file(self,path):
        path=Path(path).resolve(strict=True)
        data=path.read_bytes();original=sha(data)
        if path.suffix.lower()=='.svg':
            validate_svg(data)
            target=self.directory/(original+'.png')
            code="import{Resvg}from'@resvg/resvg-js';import{readFile,writeFile}from'node:fs/promises';await writeFile(process.argv[2],new Resvg(await readFile(process.argv[1]),{fitTo:{mode:'width',value:1600}}).render().asPng());"
            result=subprocess.run(['node','--input-type=module','-e',code,str(path),str(target)],cwd=REPO,capture_output=True,text=True,encoding='utf-8')
            require(result.returncode==0,'SVG rendering failed')
            data=target.read_bytes();suffix='.png'
        else:
            from PIL import Image
            with Image.open(io.BytesIO(data)) as image:
                image.verify()
            suffix=path.suffix.lower()
            if suffix not in ('.png','.jpg','.jpeg','.gif','.webp'):
                with Image.open(io.BytesIO(data)) as image:
                    require(getattr(image,'n_frames',1)==1,'Animated non-native image needs a frame-preserving adapter')
                    buffer=io.BytesIO();image.save(buffer,format='PNG');data=buffer.getvalue();suffix='.png'
        digest=sha(data);aid='img-'+digest
        target=self.directory/(digest+suffix)
        if not target.exists():target.write_bytes(data)
        self.records[aid]={'mime':mimetypes.guess_type(target.name)[0],'base64':base64.b64encode(data).decode(),'sha256':digest}
        self.trace.append({'source':str(path),'source_sha256':original,'asset':aid,'managed_sha256':digest})
        return aid


def protect_html_math(source):
    soup=BeautifulSoup(source,'html.parser')
    for text in list(soup.find_all(string=True)):
        if text.find_parent(['code','pre']) or text.find_parent(class_='math-tex'):continue
        parts=math_split(str(text))
        if not any(kind=='latex' for kind,_,_ in parts):continue
        for kind,value,block in parts:
            if kind=='latex':
                span=soup.new_tag('span');span['class']='math-tex'
                span.string=(r'\[' if block else r'\(')+value+(r'\]' if block else r'\)')
                text.insert_before(span)
            else:text.insert_before(value)
        text.extract()
    return soup


def segments(text,assets,base,raw_html=False,literal=False,equation=False):
    if literal:return [{'kind':'text','value':text}]
    assets.allowed_roots.add(Path(base).resolve())
    if raw_html:
        soup=protect_html_math(text)
    else:
        # Placeholders stop the Markdown parser interpreting TeX backslashes.
        parts=math_split(text,strict=equation);formulas={};joined=[]
        for kind,value,block in parts:
            if kind=='latex':
                marker='RBI_MATH_'+str(len(formulas))+'_TOKEN'
                formulas[marker]=(value,block);joined.append(marker)
            else:joined.append(value)
        soup=BeautifulSoup(MD.renderInline(''.join(joined)),'html.parser')
        for node in list(soup.find_all(string=True)):
            value=str(node)
            for marker,(math,block) in formulas.items():
                if marker in value:
                    # Replace in a parsed text node, never splice markup into a formula.
                    pieces=value.split(marker)
                    if len(pieces)!=2:raise ValueError('Ambiguous formula placeholder')
                    node.insert_before(pieces[0]);span=soup.new_tag('span');span['class']='math-tex'
                    span.string=(r'\[' if block else r'\(')+math+(r'\]' if block else r'\)')
                    node.insert_before(span);node.replace_with(pieces[1]);break
        # Multiple formulas may share one source text node; process until resolved.
        unresolved=[m for m in formulas if m in soup.get_text()]
        for marker in unresolved:
            math,block=formulas[marker]
            for node in list(soup.find_all(string=True)):
                if marker not in str(node):continue
                before,after=str(node).split(marker,1);node.insert_before(before)
                span=soup.new_tag('span');span['class']='math-tex';span.string=(r'\[' if block else r'\(')+math+(r'\]' if block else r'\)')
                node.insert_before(span);node.replace_with(after)
    for link in list(soup.find_all('a')):
        if not link.get('href'):
            link.unwrap();continue
        href=link['href']
        if href.startswith('#'):
            target=assets.anchors.get(unquote(href[1:]))
            require(target is not None,'Unresolved source anchor '+href)
            marker='RBIREF'+str(len(assets.reference_markers))+'TOKEN'
            assets.reference_markers[marker]={'kind':'ref','targetId':target}
            label=link.get_text()
            link.replace_with(label+' '+marker)
    rendered=rich(list(soup.children),assets,Path(base).resolve().as_uri()+'/') or [{'kind':'text','value':''}]
    output=[]
    for segment in rendered:
        if segment['kind']!='text':output.append(segment);continue
        value=segment['value'];pos=0
        for match in re.finditer(r'RBIREF\d+TOKEN',value):
            if match.start()>pos:output.append({'kind':'text','value':value[pos:match.start()]})
            output.append(assets.reference_markers[match[0]]);pos=match.end()
        if pos<len(value):output.append({'kind':'text','value':value[pos:]})
    return output


def native_table(source,assets,base):
    soup=protect_html_math(source);table=soup.find('table')
    require(table is not None,'Missing source table')
    # Unicode relation/operator glyphs are mathematical even when OCR omitted
    # delimiters. KaTeX cannot place some of them (e.g. !=) inside \text{}.
    for node in list(table.find_all(string=True)):
        if node.find_parent(class_='math-tex') or not any(ord(c)>127 and unicodedata.category(c)=='Sm' for c in str(node)):continue
        for piece in re.split(r'([^\x00-\x7f])',str(node)):
            if len(piece)==1 and unicodedata.category(piece)=='Sm':
                span=soup.new_tag('span');span['class']='math-tex';span.string=r'\('+piece+r'\)';node.insert_before(span)
            else:node.insert_before(piece)
        node.extract()
    captions=[]
    for caption in list(table.find_all('caption',recursive=False)):
        captions.extend(segments(caption.decode_contents(),assets,base,raw_html=True))
        captions.append({'kind':'text','value':'\n'})
        caption.extract()
    spans=any(int(c.get('rowspan',1))>1 or int(c.get('colspan',1))>1 for c in table.select('td,th'))
    if spans:
        # A cell appears exactly once in the expanded logical grid. Original HTML
        # and OCR table image remain in the source artifact for its exact layout.
        grid={};height=0;width=0
        for r,row in enumerate(table.find_all('tr')):
            c=0
            for cell in row.find_all(['td','th'],recursive=False):
                while (r,c) in grid:c+=1
                rs,cs=int(cell.get('rowspan',1)),int(cell.get('colspan',1))
                require(1<=rs<=1000 and 1<=cs<=1000,'Invalid table span')
                for rr in range(r,r+rs):
                    for cc in range(c,c+cs):
                        require((rr,cc) not in grid,'Overlapping table cells')
                        grid[(rr,cc)]=cell.decode_contents() if (rr,cc)==(r,c) else ''
                height=max(height,r+rs);width=max(width,c+cs);c+=cs
        table=BeautifulSoup('<table>'+''.join('<tr>'+''.join('<td>'+grid.get((r,c),'')+'</td>' for c in range(width))+'</tr>' for r in range(height))+'</table>','html.parser').table
    result=captions+[{'kind':'latex','value':table_latex(table),'block':True}]
    for image in table.find_all('img'):
        result.extend(segments(str(image),assets,base,raw_html=True))
    for link in table.find_all('a'):
        result.extend(segments(str(link),assets,base,raw_html=True))
    return result,spans


def build(extraction,structure,folder,title):
    atoms=structure['atoms'];assets=Assets(folder);runs={};table_spans=[]
    title_nodes={d['title_atom']:d['id'] for d in structure['documents'] if d['title_atom']}
    for a in atoms:
        for anchor in a.get('anchors',[]):
            require(anchor not in assets.anchors,'Duplicate source anchor '+anchor)
            assets.anchors[anchor]=title_nodes.get(a['id'],a['id'])
    for a in atoms:
        base=a.get('base',str(Path(extraction['source']).parent))
        assets.aliases={}
        for original,record in a.get('inline_media',{}).items():
            require(file_sha(record['path'])==record['sha256'],'Inline OCR image changed')
            assets.allowed_roots.add(Path(record['path']).resolve().parent)
            assets.aliases[(Path(base)/unquote(urlsplit(original).path)).resolve()]=Path(record['path'])
        if a['kind']=='image':
            require(file_sha(a['path'])==a['sha256'],'Source image changed')
            value=[{'kind':'image','assetId':assets.add_file(a['path'])}]
        elif a['kind']=='code':value=[{'kind':'code','value':a['text']}]
        elif a['kind']=='table':
            value,spans=native_table(a['text'],assets,base)
            if spans:table_spans.append(a['id'])
        else:value=segments(a['text'],assets,base,raw_html=a['kind']=='html',literal=a.get('literal',False),equation=a['kind']=='equation')
        runs[a['id']]=value
    nodes=[];mapping={};groups=structure['groups']
    for d in structure['documents']:
        head=runs[d['title_atom']] if d['title_atom'] else segments(d['title'],assets,folder)
        nodes.append({'id':d['id'],'parentId':d['parent'],'document':True,'text':head})
        if d['title_atom']:mapping[d['title_atom']]=d['id']
        for i in range(d['start'],d['end']):
            a=atoms[i]
            if a['id']==d['title_atom']:continue
            ancestors=[g['parent'] for g in groups if g['parent']<i<=g['through']]
            parent=atoms[max(ancestors)]['id'] if ancestors else d['id']
            nodes.append({'id':a['id'],'parentId':parent,'document':False,'text':runs[a['id']]});mapping[a['id']]=a['id']
    bundle={'schemaVersion':1,'packageId':'material.'+extraction['source_sha256'][:24]+'.v1','title':title,
            'nodes':nodes,'assets':assets.records,'provenance':{'sourceSha256':extraction['source_sha256'],
            'structureBasis':structure['basis'],'atomToNode':mapping,'llmProvider':'codex_exec'}}
    save(folder/'rich-atoms.json',runs);save(folder/'asset-trace.json',assets.trace)
    save(folder/'package.json',bundle)
    save(folder/'representation-notes.json',{'merged_tables_expanded_to_grid':table_spans})
    export_markdown(bundle,structure,folder)
    (folder/'preview.html').write_text(local_preview(bundle),encoding='utf-8')
    return bundle


def markdown_text(runs,folder,prefix='_assets/'):
    parts=[]
    for s in runs:
        if s['kind']=='image':
            filename=next((folder/'markdown/_assets').glob(s['assetId'][4:]+'.*')).name
            parts.append('![](<'+prefix+filename+'>)')
        elif s['kind']=='latex':parts.append('$$\n'+s['value']+'\n$$' if s['block'] else '$'+s['value']+'$')
        elif s['kind']=='code':
            fence='`'*(max([2]+[len(x) for x in re.findall('`+',s['value'])])+1)
            parts.append(fence+'\n'+s['value']+'\n'+fence)
        elif s['kind']=='ref':parts.append('[↗](<'+prefix.removesuffix('_assets/')+'全书大纲.md#'+s['targetId']+'>)')
        else:parts.append(s['value'])
    return ''.join(parts)


def local_preview(bundle, rendered_math=None):
    view=copy.deepcopy(bundle)
    for node in view['nodes']:
        converted=[{'kind':'markdown','value':'<a id="'+node['id']+'"></a>'}]
        for s in node['text']:
            converted.append({'kind':'markdown','value':'[↗](#'+s['targetId']+')'} if s['kind']=='ref' else s)
        node['text']=converted
    return preview_html(view,rendered_math)


def export_markdown(bundle,structure,folder):
    byid={n['id']:n for n in bundle['nodes']};depths={None:0};lines=['# '+bundle['title'],'']
    for n in bundle['nodes']:
        depths[n['id']]=depths[n['parentId']]+1
        lines.append('  '*(depths[n['id']]-1)+'- <a id="'+n['id']+'"></a>'+markdown_text(n['text'],folder).replace('\n','\n'+'  '*depths[n['id']]))
    (folder/'markdown/全书大纲.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    paths={};index=['# '+bundle['title'],''];mapping=bundle['provenance']['atomToNode']
    for number,d in enumerate(structure['documents'],1):
        safe=re.sub(r'[<>:"/\\|?*\x00-\x1f]',' ',d['title']).strip(' .')[:70] or '资料'
        target=folder/'markdown/分篇'/f'{number:04d} {safe}.md';target.parent.mkdir(exist_ok=True)
        paths[d['id']]=target
        output=['# '+markdown_text(byid[d['id']]['text'],folder,'../_assets/'),'']
        for a in structure['atoms'][d['start']:d['end']]:
            nid=mapping[a['id']]
            if nid==d['id']:continue
            indent=depths[nid]-depths[d['id']]-1
            output.append('  '*indent+'- '+markdown_text(byid[nid]['text'],folder,'../_assets/').replace('\n','\n'+'  '*(indent+1)))
        target.write_text('\n'.join(output)+'\n',encoding='utf-8')
        index.append('  '*(depths[d['id']]-1)+'- ['+d['title'].replace('[','\\[').replace(']','\\]')+'](<'+target.relative_to(folder/'markdown').as_posix()+'>)')
    for d in structure['documents']:
        children=[c for c in structure['documents'] if c['parent']==d['id']]
        if children:
            target=paths[d['id']]
            with target.open('a',encoding='utf-8') as stream:
                stream.write('\n'+ '\n'.join('- ['+c['title'].replace('[','\\[').replace(']','\\]')+'](<'+paths[c['id']].name+'>)' for c in children)+'\n')
    (folder/'markdown/阅读目录.md').write_text('\n'.join(index)+'\n',encoding='utf-8')
    save(folder/'markdown-map.json',{k:str(v) for k,v in paths.items()})
