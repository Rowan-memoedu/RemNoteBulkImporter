"""Convert an authorized, frozen Publish Markdown collection via material renderer.

No network or credentials: snapshot.json, cache.json and assets.json are local
receipts. Source page boundaries become Documents; headings/lists stay outlines.
"""
from __future__ import annotations

import argparse
import json
import posixpath
import re
import math
import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from bs4 import BeautifulSoup
from markdown_it import MarkdownIt

from .common import REPO, file_sha, load, require, save, sha
from .local_formats import markdown_atoms
from .render import build, local_preview
from .validate import validate


def page_anchor(path):
    return 'page-' + sha(path)[:24]


def resolve_link(value, page, paths):
    value = unquote(value.split('|', 1)[0].split('#', 1)[0])
    if not value:
        return page
    for candidate in (value, posixpath.normpath(posixpath.join(posixpath.dirname(page), value))):
        if candidate in paths:
            return candidate
        if not posixpath.splitext(value)[1] and candidate + '.md' in paths:
            return candidate + '.md'
    candidates = [p for p in paths if p.endswith('/' + value) or not posixpath.splitext(value)[1] and p.endswith('/' + value + '.md')]
    if not candidates and posixpath.splitext(value)[1].lower() in ('.webp', '.png', '.jpg', '.jpeg', '.svg', '.gif'):
        stem = posixpath.splitext(posixpath.basename(value))[0]
        candidates = [p for p in paths if posixpath.splitext(posixpath.basename(p))[0] == stem
                      and posixpath.splitext(p)[1].lower() in ('.webp', '.png', '.jpg', '.jpeg', '.svg', '.gif')]
        if len(candidates) != 1:
            return None
    def score(path):
        count = 0
        for a, b in zip(path.split('/'), page.split('/')):
            if a != b:
                break
            count += 1
        return (-count, path)
    return min(candidates, key=score) if candidates else None


def public_url(site, path):
    return site.rstrip('/') + '/' + '/'.join(quote(p) for p in path.removesuffix('.md').split('/'))


def svg_preview(path, root):
    """Screenshot foreignObject text with isolated headless Chrome, no network."""
    data=path.read_bytes()
    require(not re.search(rb'<!ENTITY',data,re.I),'SVG entities are unsupported')
    tree=ET.fromstring(data)
    for element in tree.iter():
        require(element.tag.split('}')[-1]!='script','Scripted SVG needs an explicit source representation')
        require(not any(k.split('}')[-1].lower().startswith('on') for k in element.attrib),'Active SVG attribute')
    chrome=Path(os.getenv('RBI_RENDER_CHROME',str(Path(os.getenv('LOCALAPPDATA',''))/'Google/Chrome/Application/chrome.exe')))
    require(chrome.is_file(),'Chrome is required to preserve SVG foreignObject labels')
    digest=sha(data)
    directory=root/'rendered';directory.mkdir(exist_ok=True)
    output=directory/(digest+'.png')
    viewbox=tree.get('viewBox','0 0 1600 1200').replace(',',' ').split()
    dimensions=[]
    for name,fallback in zip(('width','height'),viewbox[2:4]):
        raw=tree.get(name,fallback)
        dimensions.append(svg_dimension(raw,float(fallback)))
    width,height=dimensions
    require(1<=width<=16000 and 1<=height<=16000,'Invalid SVG viewport')
    if not output.exists():
        document=directory/(digest+'.html')
        document.write_text('<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'"><style>html,body{margin:0;padding:0;overflow:hidden;background:white}</style>'+data.decode('utf8'),encoding='utf8')
        profile=Path('D:/Caches/RemNoteBulkImporter/publish-render-chrome')
        result=subprocess.run([str(chrome),'--headless','--no-first-run','--no-default-browser-check',
                               '--disable-background-networking','--hide-scrollbars','--force-device-scale-factor=2',
                               '--user-data-dir='+str(profile),'--window-size='+str(width)+','+str(height),
                               '--virtual-time-budget=1000','--screenshot='+str(output),document.as_uri()],
                              capture_output=True,timeout=90)
        require(result.returncode==0 and output.is_file(),'SVG screenshot failed')
    from PIL import Image
    with Image.open(output) as image:
        image.verify()
    return output


def svg_dimension(raw, fallback):
    match=re.fullmatch(r'\s*([0-9.]+)\s*(px|pt|pc|in|cm|mm|%)?\s*',raw)
    require(match is not None,'Unsupported SVG dimension: '+raw)
    if match[2]=='%':return math.ceil(fallback)
    factor={None:1,'px':1,'pt':96/72,'pc':16,'in':96,'cm':96/2.54,'mm':96/25.4}[match[2]]
    return math.ceil(float(match[1])*factor)


def normalize(text, page, site, paths, aliases, media, headings, notes):
    def target(raw, label=None, embedded=False):
        value, _, display = raw.partition('|')
        title = label or display or value
        resolved = resolve_link(value, page, paths)
        if embedded and resolved in media:
            record = media[resolved]
            if posixpath.splitext(resolved)[1].lower() == '.pdf':
                notes.append({'page': page, 'kind': 'linked_pdf', 'target': resolved})
                return '[' + title + '](<' + public_url(site, resolved) + '>)'
            image='![](<'+ record['absolute'] + '>)'
            notes.append({'page':page,'kind':'image','target':resolved})
            if posixpath.splitext(resolved)[1].lower()=='.svg':
                image+=' [SVG 原图](<'+public_url(site,resolved)+'>)'
            return image
        if resolved in aliases:
            canonical = aliases[resolved]
            anchor = page_anchor(canonical)
            if '#' in value:
                heading = unquote(value.split('#', 1)[1])
                anchor = headings.get((canonical, heading), '')
            if anchor:
                return '[' + title.replace('[', '\\[').replace(']', '\\]') + '](#' + anchor + ')'
        if embedded:
            notes.append({'page': page, 'kind': 'missing_media', 'target': value})
            return '原站缺失附件：`' + raw.replace('`', '') + '`'
        notes.append({'page': page, 'kind': 'external_or_missing_link', 'target': value})
        location = resolved or value.split('#', 1)[0]
        url = public_url(site, location)
        if '#' in value:
            url += '#' + quote(value.split('#', 1)[1])
        return '[' + title.replace('[', '\\[').replace(']', '\\]') + '](<' + url + '>)'
    # Process Markdown text only: fenced/inline code must retain exact bytes.
    chunks = re.split(r'(```[\s\S]*?```|~~~[\s\S]*?~~~|`+[^`\n]+`+)', text)
    for i in range(0, len(chunks), 2):
        chunk = chunks[i]
        chunk = re.sub(r'!\[\[([^\]]+)\]\]', lambda m: target(m[1], embedded=True), chunk)
        chunk = re.sub(r'(?<!!)\[\[([^\]]+)\]\]', lambda m: target(m[1]), chunk)
        def remote_image(match):
            url = match[2]
            require(url in media, 'Remote image missing from snapshot: ' + url)
            notes.append({'page':page,'kind':'image','target':url})
            return '![' + match[1] + '](<' + media[url]['absolute'] + '>)'
        chunk = re.sub(r'!\[([^\]]*)\]\((https?[^\s)]+)(?:\s+[^)]*)?\)', remote_image, chunk)
        def embedded_html(match):
            soup = BeautifulSoup(match[0], 'html.parser')
            node = soup.find(['iframe', 'video', 'audio'])
            src = node.get('src') or (node.find('source') or {}).get('src')
            require(src and urlsplit(src).scheme in ('http', 'https'), 'Unsupported embedded object')
            label = '视频' if 'bilibili' in src or node.name == 'video' else '音频' if node.name == 'audio' else '交互演示'
            notes.append({'page': page, 'kind': 'embedded_link', 'url': src, 'html': match[0]})
            return '\n\n[' + label + '](<' + src + '>)\n\n'
        chunk = re.sub(r'<(iframe|video|audio)\b[^>]*>[\s\S]*?</\1>', embedded_html, chunk, flags=re.I)
        # These wrappers affect layout only; retaining their contents avoids
        # presenting HTML tags as prose in a non-HTML outline editor.
        chunk = re.sub(r'</?(?:center|div)\b[^>]*>', '', chunk, flags=re.I)
        chunks[i] = chunk
    return ''.join(chunks)


def source_outline(text, base):
    """Use real heading and list token nesting, without classifying prose by AI."""
    math_blocks = {}
    def protect(match):
        marker = 'RBIPUBLISHMATH' + str(len(math_blocks)) + 'TOKEN'
        math_blocks[marker] = match[0]
        return marker
    # Display math is one source unit even when its TeX contains blank lines.
    # Protect it before CommonMark; restore exact bytes before RichText parsing.
    chunks = re.split(r'(```[\s\S]*?```|~~~[\s\S]*?~~~)', text)
    for i in range(0, len(chunks), 2):
        chunks[i] = re.sub(r'(?<!\\)\$\$[\s\S]*?(?<!\\)\$\$', protect, chunks[i])
    atoms = markdown_atoms(''.join(chunks), base)
    for atom in atoms:
        for marker, value in math_blocks.items():
            atom['text'] = atom['text'].replace(marker, value)
    # markdown_atoms exposes list depth. Preserve continuation paragraphs under
    # their list item, and combine heading nesting with item nesting.
    groups = []
    heads = []
    items = []
    for i, atom in enumerate(atoms):
        level = atom.get('heading_level', 0)
        depth = atom.get('list_depth', 0)
        if level:
            while items:
                p = items.pop()[1]
                if i - 1 > p:
                    groups.append({'parent': p, 'through': i - 1})
            while heads and heads[-1][0] >= level:
                p = heads.pop()[1]
                if i - 1 > p:
                    groups.append({'parent': p, 'through': i - 1})
            heads.append((level, i))
        if depth:
            while items and items[-1][0] >= depth:
                p = items.pop()[1]
                if i - 1 > p:
                    groups.append({'parent': p, 'through': i - 1})
            items.append((depth, i))
        else:
            while items:
                p = items.pop()[1]
                if i - 1 > p:
                    groups.append({'parent': p, 'through': i - 1})
    for _, p in heads + items:
        if len(atoms) - 1 > p:
            groups.append({'parent': p, 'through': len(atoms) - 1})
    return atoms, groups


def audit_snapshot(source, folder):
    snapshot=load(source);root=source.parent
    extraction=load(folder/'extraction.json')
    require(file_sha(source)==extraction['source_sha256'],'Frozen snapshot manifest changed')
    for name,field in (('assets.json','assetsSha256'),('cache.json','cacheSha256')):
        if snapshot.get(field):require(file_sha(root/name)==snapshot[field],'Frozen index changed: '+name)
    media=load(root/'assets.json')
    for record in [*snapshot['pages'],*media['records']]:
        path=(root/record['file']).resolve(strict=True)
        require(path.is_relative_to(root.resolve()) and file_sha(path)==record['sha256'],'Snapshot bytes changed: '+record['path'])
    normalized=load(folder/'publish-normalization.json')
    structure=load(folder/'structure.json')
    if structure.get('catalog_sha256'):
        from .catalog import audit_catalog
        audit_catalog(structure,normalized['aliases'],folder)
    require(set(normalized['aliases'])=={p['path'] for p in snapshot['pages']},'Source page omitted from alias coverage')
    canonical=set(normalized['aliases'].values())
    require(canonical=={a['source_page'] for a in extraction['atoms']},'Source page omitted from extraction')
    for record in normalized.get('media_representations',[]):
        path=root/record['preview']
        require(file_sha(path)==record['preview_sha256'],'Rendered source image changed')
        require(any(r['path']==record['source'] and r['sha256']==record['source_sha256'] for r in media['records']), 'Rendered image has no matching original')
    package=load(folder/'package.json')
    expected=sum(n['kind']=='image' for n in normalized['notes'])
    actual=sum(s['kind']=='image' for n in package['nodes'] for s in n['text'])
    require(expected==actual,'Source image occurrence count differs from native package')
    report={'status':'VALIDATED','pages':len(snapshot['pages']),'unique_pages':len(canonical),'images':actual,
            'source_media':len(media['records']),'missing_media':[n for n in normalized['notes'] if n['kind']=='missing_media']}
    save(folder/'source-audit.json',report)
    return report


def render_preview(folder):
    result=subprocess.run(['node',str(REPO/'consumers/render-material-preview.mjs'),str(folder)],capture_output=True,timeout=180)
    require(result.returncode==0,'Offline formula preview failed')
    (folder/'preview.html').write_text(local_preview(load(folder/'package.json'),load(folder/'preview-math.json')),encoding='utf8')


def prepare(source, folder, title, catalog=None, extract_only=False):
    snapshot = load(source)
    require(not snapshot.get('failures'), 'Snapshot contains failed page downloads')
    root = source.parent
    paths = set(load(root / 'cache.json'))
    assets_receipt = load(root / 'assets.json')
    for name, field in (('assets.json', 'assetsSha256'), ('cache.json', 'cacheSha256')):
        if snapshot.get(field):
            require(file_sha(root/name) == snapshot[field], 'Frozen source index changed: ' + name)
    if snapshot.get('selectedPaths'):
        require(set(snapshot['selectedPaths']) == {p['path'] for p in snapshot['pages']}
                and len(snapshot['selectedPaths']) == len(snapshot['pages']), 'Snapshot selection is incomplete')
    require(not assets_receipt['failures'], 'Snapshot contains failed asset downloads')
    media = {}
    representations=[]
    for record in assets_receipt['records']:
        path = (root / record['file']).resolve(strict=True)
        require(path.is_relative_to(root.resolve()) and file_sha(path) == record['sha256'], 'Asset snapshot changed')
        # CommonMark deliberately rejects file: URLs; source-relative links
        # parse as images and the renderer resolves them under this source root.
        preview=svg_preview(path,root) if path.suffix.lower()=='.svg' else None
        selected=preview or path
        if preview:
            representations.append({'source':record['path'],'source_sha256':record['sha256'],'preview':preview.relative_to(root).as_posix(),'preview_sha256':file_sha(preview),'mode':'isolated_chrome_screenshot'})
        media[record['path']] = {**record, 'absolute': selected.relative_to(root).as_posix()}
    pages = []
    for record in snapshot['pages']:
        require(not record.get('notFound'), 'Snapshot contains missing source page')
        path = (root / record['file']).resolve(strict=True)
        require(path.is_relative_to(root.resolve()) and file_sha(path) == record['sha256'], 'Page snapshot changed')
        pages.append({**record, 'text': path.read_text(encoding='utf-8')})
    # Prefer the deepest/newest collection path for an exact same-name copy.
    pages.sort(key=lambda p: (-p['path'].count('/'), -p['path'].startswith('Part'), p['path']))
    identities = {}
    aliases = {}
    chosen = []
    for page in pages:
        identity = (posixpath.basename(page['path']), page['sha256'])
        canonical = identities.get(identity)
        if canonical is None:
            canonical = page['path']
            identities[identity] = canonical
            chosen.append(page)
        aliases[page['path']] = canonical
    chosen.sort(key=lambda p: p['path'])
    headings = {}
    parser = MarkdownIt('commonmark', {'html': True})
    for page in chosen:
        tokens = parser.parse(page['text'])
        for j, token in enumerate(tokens):
            if token.type == 'heading_open':
                value = tokens[j + 1].content
                headings.setdefault((page['path'], value), page_anchor(page['path']) + '-h-' + sha(value)[:16])
    atoms = []
    docs = []
    groups = []
    directories = {}
    notes = []
    normalized = {}
    for page in chosen:
        parts = page['path'].split('/')
        parent = None
        for depth in range(1, len(parts)):
            key = '/'.join(parts[:depth])
            if key not in directories:
                doc_id = 'dir-' + sha(key)[:24]
                directories[key] = doc_id
                docs.append({'id': doc_id, 'title': parts[depth-1], 'parent': parent, 'start': len(atoms), 'end': len(atoms), 'title_atom': None, 'basis': 'source_directories'})
            parent = directories[key]
        canonical = page['path']
        doc_id = page_anchor(canonical)
        text = normalize(page['text'], canonical, snapshot['site'], paths, aliases, media, headings, notes)
        normalized[canonical] = text
        body, intervals = source_outline(text, root)
        start = len(atoms)
        title_text = posixpath.basename(canonical).removesuffix('.md')
        # Title atom anchors are mapped directly to the real Document.
        page_atoms = [{'kind': 'text', 'text': title_text, 'heading_level': 0, 'anchors': [doc_id], 'base': str(root)},
                      {'kind': 'text', 'text': '[原文](<' + public_url(snapshot['site'], canonical) + '>)', 'heading_level': 0, 'base': str(root)}] + body
        for local, atom in enumerate(page_atoms):
            atom.update(id=f'a{start+local:06d}', page=len(normalized), block=local, source_type='local', field='text', doc=doc_id, source_page=canonical)
            atom.setdefault('anchors', [])
            if atom.get('heading_level'):
                anchor = headings.get((canonical, atom['text']))
                if anchor and not any(anchor in a.get('anchors', []) for a in page_atoms[:local]):
                    atom['anchors'].append(anchor)
        atoms.extend(page_atoms)
        groups.extend({'parent': start+2+g['parent'], 'through': start+2+g['through']} for g in intervals)
        docs.append({'id': doc_id, 'title': title_text, 'parent': parent, 'start': start, 'end': len(atoms), 'title_atom': atoms[start]['id'], 'basis': 'source_pages'})
    print(f'SOURCE {len(pages)} pages, {len(chosen)} unique pages, {len(atoms)} atoms, {len(media)} media', flush=True)
    folder.mkdir(parents=True, exist_ok=True)
    extraction = {'source': str(source), 'source_sha256': file_sha(source), 'atoms': [{k:v for k,v in a.items() if k!='doc'} for a in atoms],
                  'metadata': {'adapter': 'publish-snapshot'}, 'coverage': {'fields': len(atoms), 'pages': len(pages)}}
    structure = {'basis': 'source_pages_and_markdown_nesting', 'provider':'source_markup', 'contents_pages': [], 'documents': docs, 'atoms': atoms, 'groups': groups}
    if catalog:
        from .catalog import apply_catalog
        structure=apply_catalog(structure,Path(catalog),aliases,folder)
    save(folder/'source.json', {'source': str(source), 'source_sha256': file_sha(source)})
    save(folder/'extraction.json', extraction)
    save(folder/'structure.json', structure)
    save(folder/'publish-normalization.json', {'aliases': aliases, 'notes': notes, 'media_representations':representations,'normalized_sha256': {k: sha(v) for k,v in normalized.items()}, 'pages': len(pages), 'unique_pages': len(chosen)})
    if extract_only:return {'status':'extracted','adapter':'publish-snapshot','pages':len(pages),'unique_pages':len(chosen),'atoms':len(atoms)}
    bundle = build(extraction, structure, folder, title)
    require(sum(s['kind']=='image' for n in bundle['nodes'] for s in n['text']) == sum(n['kind']=='image' for n in notes),
            'Source image occurrence count differs from typed native images')
    audit_snapshot(source,folder)
    report = validate(folder)
    render_preview(folder)
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['prepare', 'validate', 'import', 'preview'])
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--title', default='网站资料')
    parser.add_argument('--kb-id')
    parser.add_argument('--parent-rem-id')
    args = parser.parse_args()
    if args.phase == 'prepare':
        prepare(args.source.resolve(strict=True), args.output.resolve(), args.title)
    elif args.phase == 'validate':
        audit_snapshot(args.source.resolve(strict=True),args.output)
        print(json.dumps(validate(args.output), ensure_ascii=False))
    elif args.phase == 'preview':
        render_preview(args.output)
    else:
        from .delivery import deliver
        audit_snapshot(args.source.resolve(strict=True),args.output)
        deliver(args.output, args.kb_id, args.parent_rem_id)


if __name__ == '__main__':
    main()
