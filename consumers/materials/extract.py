"""Format adapters. Raw extraction is immutable; no LLM rewrites source atoms."""
from __future__ import annotations

import copy
import mimetypes
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .common import BOOK, CACHE, READING, file_sha, key, load, require, save, sha

FIELDS = ('text', 'latex', 'code_body', 'content', 'table_caption', 'table_body',
          'image_caption', 'image_footnote', 'table_footnote', 'chart_caption',
          'chart_footnote', 'list_items')
OCR_EXTENSIONS = {'.pdf', '.png', '.jpg', '.jpeg', '.jp2', '.webp', '.gif', '.bmp',
                  '.doc', '.docx', '.ppt', '.pptx'}


def inline_media(block, renamed):
    """Resolve inline OCR images without rewriting the original source fields."""
    from bs4 import BeautifulSoup
    from markdown_it import MarkdownIt
    parser=MarkdownIt('commonmark',{'html':True})
    references=set()
    for field in FIELDS:
        value=block.get(field)
        for item in value if isinstance(value,list) else [value]:
            if not isinstance(item,str):continue
            references.update(img.get('src') for img in BeautifulSoup(item,'html.parser').find_all('img') if img.get('src'))
            for token in parser.parseInline(item):
                references.update(child.attrGet('src') for child in token.children or [] if child.type=='image')
    result={}
    for url in references:
        parsed=urlsplit(url)
        require(not parsed.scheme and not parsed.netloc,'Unexpected remote OCR image')
        name=Path(unquote(parsed.path)).name
        require(name in renamed,'Missing inline OCR image '+name)
        target=renamed[name]
        result[url]={'path':str(target),'sha256':file_sha(target)}
    return result


def ocr_functions():
    if str(BOOK) not in sys.path:
        sys.path.insert(0, str(BOOK))
    from booksimplifier.pdf import run_mineru, validate_ocr_pages
    return run_mineru, validate_ocr_pages


def split_pdf(source, directory, max_pages=150, max_bytes=180_000_000):
    """Check actual saved bytes, recursively split; never upload oversize chunks."""
    import pymupdf
    require(max_pages > 0 and max_bytes > 0, 'Invalid OCR chunk limits')
    directory.mkdir(parents=True, exist_ok=True)
    with pymupdf.open(source) as document:
        if len(document) <= max_pages and source.stat().st_size <= max_bytes:
            return [{'path': str(source), 'start': 0, 'end': len(document), 'sha256': file_sha(source)}]
        parts = []
        def emit(start, end):
            target = directory / f'pages-{start+1}-{end}.pdf'
            if not target.exists():
                with pymupdf.open() as selected:
                    selected.insert_pdf(document, from_page=start, to_page=end-1)
                    selected.save(target, no_new_id=True)
            if target.stat().st_size > max_bytes:
                require(end-start > 1, f'Single PDF page {start+1} exceeds OCR byte limit')
                middle = (start+end)//2
                emit(start, middle)
                emit(middle, end)
            else:
                parts.append({'path': str(target), 'start': start, 'end': end, 'sha256': file_sha(target)})
        for start in range(0, len(document), max_pages):
            emit(start, min(len(document), start+max_pages))
        require([p for item in parts for p in range(item['start'], item['end'])] == list(range(len(document))), 'Chunk coverage mismatch')
        return parts


def ocr_extract(source, folder):
    import pymupdf
    run_mineru, validate_pages = ocr_functions()
    digest = file_sha(source)
    work = CACHE / digest
    work.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() == '.pdf':
        parts = split_pdf(source, work / 'chunks')
        with pymupdf.open(source) as document:
            metadata = {'pages': len(document), 'bookmarks': document.get_toc(),
                        'page_labels': document.get_page_labels()}
    else:
        require(source.stat().st_size <= 180_000_000, 'Office/image file exceeds OCR upload limit; split it before import')
        parts = [{'path': str(source), 'start': 0, 'end': None, 'sha256': digest}]
        metadata = {'pages': None, 'bookmarks': []}
    save(folder / 'ocr-chunks.json', parts)
    images = folder / 'source-assets'
    images.mkdir(exist_ok=True)
    blocks, receipts, blanks = [], [], []
    for ordinal, part in enumerate(parts):
        print(f'OCR {ordinal+1}/{len(parts)} pages {part["start"]+1}-{part["end"] or "?"}', flush=True)
        existing = Path('D:/AppData/BookSimplifier/cache/pdf/ocr')
        old_state = existing / part['sha256'] / 'state.json'
        cache_root = existing if old_state.exists() and load(old_state).get('state') == 'downloaded' else CACHE / 'ocr'
        parsed = run_mineru(Path(part['path']), cache_root)
        if source.suffix.lower() == '.pdf':
            validate_pages(Path(part['path']), parsed)
        renamed = {}
        for image in Path(parsed['images_dir']).glob('*'):
            if image.is_file():
                name = file_sha(image) + image.suffix.lower()
                target = images / name
                if not target.exists():
                    shutil.copyfile(image, target)
                renamed[image.name] = target
        for block in copy.deepcopy(parsed['content_list']):
            block['page_idx'] = int(block.get('page_idx', 0)) + part['start']
            references=inline_media(block,renamed)
            if references:block['_inline_media']=references
            for field in ('img_path', 'image_path'):
                if block.get(field):
                    name = Path(block[field]).name
                    require(name in renamed, f'Missing OCR asset {name}')
                    block[field] = str(renamed[name])
            blocks.append(block)
        blanks.extend({**b, 'page': b['page']+part['start']} for b in parsed.get('blank_pages', []))
        receipts.append({'cache': parsed['cache'], 'cache_hit': parsed.get('cache_hit', False), **part})
    metadata.update(adapter='mineru-vlm', chunks=receipts, blank_pages=blanks)
    metadata['pages'] = metadata['pages'] or max(b['page_idx'] for b in blocks)+1
    return blocks, metadata


def atoms_from_ocr(blocks):
    ordered, excluded = [], []
    for page in sorted({b['page_idx'] for b in blocks}):
        body = [(i,b) for i,b in enumerate(blocks) if b['page_idx']==page and b['type'] not in ('page_number','header')]
        for pair in [(i,b) for i,b in enumerate(blocks) if b['page_idx']==page and b['type']=='header']:
            at = next((j for j,(_,b) in enumerate(body) if b.get('bbox',[0,1000])[1] > pair[1].get('bbox',[0,0])[1]), len(body))
            body.insert(at,pair)
        ordered.extend(body)
    atoms = []
    for bi,b in enumerate(blocks):
        if b['type']=='page_number':
            excluded.append({'block':bi, 'reason':'page_number', 'source':b})
    for bi,b in ordered:
        common = {'block':bi,'page':b['page_idx']+1,'source_type':b['type'],
                  'heading_level':b.get('text_level',0),'bbox':b.get('bbox')}
        if b.get('_inline_media'):common['inline_media']=b['_inline_media']
        before = len(atoms)
        for field in FIELDS:
            value = b.get(field)
            if field in ('latex','code_body') and value==b.get('text'):
                continue
            for vi,item in enumerate(value if isinstance(value,list) else [value]):
                if not isinstance(item,str) or not item.strip():
                    continue
                kind = 'table' if field=='table_body' else 'equation' if b['type']=='equation' else 'code' if b['type']=='code' else 'text'
                for li,part in enumerate(item.strip().splitlines() if kind=='text' else [item.strip()]):
                    if part.strip():
                        atoms.append({**common,'field':field,'field_item':vi,'line':li,'kind':kind,'text':part.strip()})
        for field in ('img_path','image_path'):
            if b.get(field):
                image = Path(b[field])
                require(image.is_file(), f'Missing source image {image.name}')
                atoms.append({**common,'field':field,'kind':'image','text':'','path':str(image),'sha256':file_sha(image)})
        if len(atoms)==before:
            unknown=set(b)-set(FIELDS)-{'type','bbox','page_idx','text_level','img_path','image_path','_inline_media'}
            require(not unknown, f'Unrepresented OCR block {bi} ({b["type"]}): {sorted(unknown)}')
            excluded.append({'block':bi,'reason':'empty_ocr_block','source':b})
    for i,a in enumerate(atoms):
        a['id'] = f'a{i:06d}'
    # Independent field inventory: retain every substantive recognized source field.
    expected, actual = {}, defaultdict(list)
    for bi,b in enumerate(blocks):
        if b['type']=='page_number':
            continue
        for field in FIELDS:
            value=b.get(field)
            if field in ('latex','code_body') and value==b.get('text'):
                continue
            for vi,item in enumerate(value if isinstance(value,list) else [value]):
                if isinstance(item,str) and item.strip():
                    expected[(bi,field,vi)]=item
    for a in atoms:
        if a['kind']!='image':
            actual[(a['block'],a['field'],a.get('field_item',0))].append(a['text'])
    normal=lambda s:re.sub(r'\s+','',s)
    require(set(expected)==set(actual), 'OCR source-field set changed')
    for k,v in expected.items():
        require(normal(v)==normal('\n'.join(actual[k])),f'OCR field changed {k}')
    return atoms, {'fields':len(expected),'atoms':len(atoms),'excluded':excluded}


def extract(source, folder):
    checkpoint=folder/'extraction.json'
    adapter_hash=sha(Path(__file__).read_bytes()+Path(__file__).with_name('local_formats.py').read_bytes())
    if checkpoint.exists():
        result=load(checkpoint)
        require(result['source_sha256']==file_sha(source), 'Source changed after extraction')
        if result.get('adapter_sha256')==adapter_hash:
            if result.get('raw_ocr_sha256'):
                require(file_sha(folder/'ocr-blocks.json')==result['raw_ocr_sha256'],'Raw OCR checkpoint changed')
            return result
    if source.suffix.lower() in OCR_EXTENSIONS:
        blocks, metadata=ocr_extract(source,folder)
        save(folder/'ocr-blocks.json',blocks)
        atoms,coverage=atoms_from_ocr(blocks)
    else:
        from .local_formats import local_extract
        atoms,metadata,coverage=local_extract(source,folder)
    require(atoms, 'Empty extraction')
    result={'schema':'material-source/1','source':str(source),'source_sha256':file_sha(source),
            'atoms':atoms,'metadata':metadata,'coverage':coverage,'adapter_sha256':adapter_hash,
            'raw_ocr_sha256':file_sha(folder/'ocr-blocks.json') if (folder/'ocr-blocks.json').exists() else None}
    save(checkpoint,result)
    print(f'EXTRACTED {len(atoms)} atoms, {metadata.get("pages", "local")} pages',flush=True)
    return result
