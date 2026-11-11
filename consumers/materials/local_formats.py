"""Local text/HTML/EPUB adapters, retaining explicit source heading/list hints."""
from __future__ import annotations

import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup, Comment, NavigableString
from markdown_it import MarkdownIt

from .common import READING, require, save


def markdown_atoms(text, base):
    parser=MarkdownIt('commonmark',{'html':True}).enable(['table','strikethrough'])
    tokens=parser.parse(text)
    atoms=[]; levels=[]; lists=[]; list_depth=0; i=0; pending=[]
    while i<len(tokens):
        token=tokens[i]
        if token.type in ('bullet_list_open','ordered_list_open'):
            lists.append({'number':token.attrGet('start') or 1,'ordered':token.type=='ordered_list_open'})
            list_depth+=1
        elif token.type in ('bullet_list_close','ordered_list_close'):
            lists.pop();list_depth-=1
        elif token.type=='list_item_close' and lists:
            lists[-1]['number']+=1
        elif token.type=='inline':
            previous=tokens[i-1] if i else None
            heading=int(previous.tag[1:]) if previous and previous.type=='heading_open' else 0
            value=token.content
            anchor=BeautifulSoup(value,'html.parser')
            if not anchor.get_text().strip() and anchor.find('a',id=True) and not anchor.find('img'):
                pending.extend(a['id'] for a in anchor.find_all('a',id=True))
                i+=1
                continue
            # Keep source ordered numbering; bullets are structural, not text.
            if lists and lists[-1]['ordered']:
                value=str(lists[-1]['number'])+'. '+value
            atoms.append({'kind':'text','text':value,'heading_level':heading,'list_depth':list_depth,'line':token.map[0] if token.map else None,'base':str(base),'anchors':pending})
            pending=[]
        elif token.type in ('fence','code_block'):
            language=token.info.strip().split(maxsplit=1)
            kind='mermaid' if language and language[0].casefold()=='mermaid' else 'code'
            atoms.append({'kind':kind,'text':token.content,'heading_level':0,'base':str(base)})
        elif token.type=='html_block':
            atoms.extend(html_atoms(token.content,base))
        elif token.type=='table_open':
            end=i+1
            while tokens[end].type!='table_close':end+=1
            # Render table cells from raw inline content so TeX slashes survive.
            rows=[];cells=[]
            import html
            for t in tokens[i:end+1]:
                if t.type=='inline':
                    # Parse inline Markdown in cells (including image/link
                    # nodes), while shielding TeX backslashes from CommonMark.
                    from .render import math_split
                    formulas={};pieces=[]
                    for kind,value,block in math_split(t.content):
                        if kind=='latex':
                            marker='RBICELLMATH'+str(len(formulas))+'TOKEN'
                            formulas[marker]=('$$' if block else '$')+value+('$$' if block else '$');pieces.append(marker)
                        else:pieces.append(value)
                    cell=parser.renderInline(''.join(pieces))
                    for marker,value in formulas.items():cell=cell.replace(marker,html.escape(value))
                    cells.append('<td>'+cell+'</td>')
                elif t.type=='tr_close':rows.append('<tr>'+''.join(cells)+'</tr>');cells=[]
            atoms.append({'kind':'table','text':'<table>'+''.join(rows)+'</table>','heading_level':0,'base':str(base)})
            i=end
        i+=1
    return atoms


def html_atoms(text, base):
    soup=BeautifulSoup(text,'html.parser')
    require(not soup.find(['iframe','object','embed','canvas','video','audio']), 'HTML contains unsupported embedded media')
    for element in soup.find_all(['script','style','head']):
        require(element.name!='script' or element.get('type','') not in ('math/tex','math/tex; mode=display'), 'HTML TeX script requires an explicit adapter')
        element.decompose()
    atoms=[]
    def walk(node, depth=0):
        if isinstance(node,Comment):return
        if isinstance(node,NavigableString):
            if str(node).strip():atoms.append({'kind':'text','text':str(node).strip(),'heading_level':0,'base':str(base),'list_depth':depth})
            return
        name=node.name
        if name=='table':
            atoms.append({'kind':'table','text':str(node),'heading_level':0,'base':str(base)})
        elif name=='pre':
            code=node.find('code',recursive=False)
            is_mermaid='mermaid' in node.get('class',[]) or (code and 'language-mermaid' in code.get('class',[]))
            atoms.append({'kind':'mermaid' if is_mermaid else 'code','text':node.get_text(),'heading_level':0,'base':str(base)})
        elif name and re.fullmatch('h[1-6]',name):
            atoms.append({'kind':'html','text':node.decode_contents(),'plain':node.get_text(' ',strip=True),'heading_level':int(name[1]),'base':str(base)})
        elif name in ('p','figcaption','summary') or name=='li' and not node.find(['p','ul','ol'],recursive=False):
            atoms.append({'kind':'html','text':node.decode_contents(),'plain':node.get_text(' ',strip=True),'heading_level':0,'list_depth':depth,'base':str(base)})
        elif name in ('img','span','a','b','strong','em','i','code','sup','sub','math'):
            require(name!='math','MathML needs a verified TeX adapter; source retained')
            atoms.append({'kind':'html','text':str(node),'plain':node.get_text(' ',strip=True),'heading_level':0,'base':str(base)})
        else:
            for child in node.children:walk(child,depth+(name in ('ul','ol')))
    walk(soup.body or soup)
    return atoms


def local_extract(source, folder):
    suffix=source.suffix.lower()
    metadata={'adapter':'local-markup','bookmarks':[],'pages':None}
    if suffix=='.epub':
        sys.path.insert(0,str(READING/'rich-text-import/src'))
        from rich_text_import.epub import extract_epub
        raw=extract_epub(source,folder/'epub-assets')
        save(folder/'adapter-source.json',raw)
        require(raw['status']=='completed','EPUB extraction incomplete: '+str(raw.get('warnings')))
        text=raw['markdown']
        (folder/'raw.md').write_text(text,encoding='utf-8')
        atoms=markdown_atoms(text,folder)
        metadata.update(adapter=raw['extractor'],source_metadata=raw['metadata'])
    elif suffix in ('.md','.markdown','.txt','.html','.htm'):
        data=source.read_bytes()
        try:text=data.decode('utf-8-sig')
        except UnicodeDecodeError:
            # Do not guess a legacy encoding and silently corrupt the source.
            raise ValueError('Text input must be UTF-8; convert its known encoding before import') from None
        if suffix in ('.html','.htm'):atoms=html_atoms(text,source.parent)
        elif suffix=='.txt':atoms=[{'kind':'text','text':line,'heading_level':0,'literal':True,'base':str(source.parent)} for line in text.splitlines() if line.strip()]
        else:atoms=markdown_atoms(text,source.parent)
    else:raise ValueError('Unsupported input format: '+suffix)
    for i,a in enumerate(atoms):
        a.update(id=f'a{i:06d}',block=i,page=1,source_type='local',field='text')
    return atoms,metadata,{'atoms':len(atoms),'excluded':[]}
