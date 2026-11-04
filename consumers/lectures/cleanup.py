"""Auditable removal of non-teaching marks; never reconstruct covered content."""
import copy
import io
import math
from pathlib import Path
from materials.common import require

NOISE={'advertisement','watermark','trademark','running_header','page_number'}


def intersects(a,b):
    return min(a[2],b[2])>max(a[0],b[0]) and min(a[3],b[3])>max(a[1],b[1])


def separate_background(mark,marks,doc,info_cache):
    """Prove noise belongs to a repeated raster, not the overlying ink.

    Another page must independently classify every non-white raster pixel in
    this rectangle as noise. The same image object and placement are required.
    Only that image is changed; all other PDF objects remain original.
    """
    from PIL import Image,ImageDraw,ImageChops
    import pymupdf
    def info(number):
        if number not in info_cache:info_cache[number]=doc[number-1].get_image_info(xrefs=True)
        return info_cache[number]
    page=doc[mark['page']-1]
    if page.rotation:return None
    box=pymupdf.Rect(mark['bbox']);box=pymupdf.Rect(box.x0*page.rect.width/1000,box.y0*page.rect.height/1000,box.x1*page.rect.width/1000,box.y1*page.rect.height/1000)
    for item in info(mark['page']):
        t=item['transform'];xref=item['xref']
        if not xref or item.get('has-mask') or abs(t[1])+abs(t[2])>1e-6 or t[0]<=0 or t[3]<=0:continue
        if not pymupdf.Rect(item['bbox']).contains(box):continue
        raw=doc.extract_image(xref)['image'];image=Image.open(io.BytesIO(raw)).convert('RGB');w,h=image.size
        rect=[math.floor((box.x0-t[4])/t[0]*w),math.floor((box.y0-t[5])/t[3]*h),math.ceil((box.x1-t[4])/t[0]*w),math.ceil((box.y1-t[5])/t[3]*h)]
        if not (0<=rect[0]<rect[2]<=w and 0<=rect[1]<rect[3]<=h):continue
        ink=image.crop(rect);ink=ImageChops.darker(ImageChops.darker(ink.getchannel('R'),ink.getchannel('G')),ink.getchannel('B')).point(lambda x:255 if x<245 else 0)
        if not ink.getbbox():continue
        for number in sorted({m['page'] for m in marks if m['page']!=mark['page'] and not m.get('preserveAtoms')}):
            reference=doc[number-1]
            if reference.rotation or reference.rect!=page.rect or xref not in {i[0] for i in reference.get_images(full=True)}:continue
            if not any(i['xref']==xref and i['transform']==t for i in info(number)):continue
            refs=[m for m in marks if m['page']==number and not m.get('preserveAtoms') and intersects(m['bbox'],mark['bbox'])]
            covered=Image.new('L',ink.size,0);draw=ImageDraw.Draw(covered)
            for ref in refs:
                b=ref['bbox'];r=[math.floor((b[0]*page.rect.width/1000-t[4])/t[0]*w)-rect[0],math.floor((b[1]*page.rect.height/1000-t[5])/t[3]*h)-rect[1],math.ceil((b[2]*page.rect.width/1000-t[4])/t[0]*w)-rect[0],math.ceil((b[3]*page.rect.height/1000-t[5])/t[3]*h)-rect[1]]
                draw.rectangle((r[0],r[1],r[2]-1,r[3]-1),fill=255)
            if not ImageChops.subtract(ink,covered).getbbox():
                from materials.common import sha
                return {'imageXref':xref,'imageSha256':sha(raw),'pixelRect':rect,'referencePage':number,'referenceBoxes':[r['bbox'] for r in refs]}
    return None


def excluded_indices(plan,atoms):
    result=set()
    for item in plan.get('excluded',[]):
        require(set(item)=={'indices','reason'},'Invalid exclusion record')
        require(item['reason'] in NOISE,'Only non-teaching marks can be excluded')
        values=item['indices']
        require(isinstance(values,list) and values and values==sorted(set(values)),'Invalid exclusion indices')
        require(all(type(i) is int and 0<=i<len(atoms) for i in values),'Exclusion outside source')
        require(not result.intersection(values),'Duplicate excluded source atom')
        result.update(values)
    return result


def masks(plan,extraction):
    atoms=extraction['atoms'];removed=excluded_indices(plan,atoms);result=[]
    for i in sorted(removed):
        a=atoms[i]
        result.append({'page':a['page'],'bbox':a['bbox'],'atom':i})
    # Generic OCR excludes page numbers from its atom stream. They must also
    # disappear from any original-page crop that intersects the footer.
    for item in extraction.get('coverage',{}).get('excluded',[]):
        if item['reason']=='page_number':
            a=item['source'];result.append({'page':a['page_idx']+1,'bbox':a['bbox'],'reason':'page_number'})
    for m in result:
        box=m['bbox'];require(isinstance(box,list) and len(box)==4,'Exclusion has no verified geometry')
        preserved=[]
        for i,a in enumerate(atoms):
            if i in removed or a['page']!=m['page']:continue
            b=a['bbox']
            if intersects(box,b):preserved.append(i)
        if preserved:m['preserveAtoms']=preserved
    overlapping=[m for m in result if m.get('preserveAtoms')]
    if overlapping:
        require(Path(extraction['source']).suffix.lower()=='.pdf','A non-teaching mark overlaps retained OCR content; cannot erase it without a verified separation')
        import pymupdf
        with pymupdf.open(extraction['source']) as doc:
            cache={}
            for m in overlapping:
                layer=separate_background(m,result,doc,cache)
                require(layer is not None,'A non-teaching mark overlaps retained OCR content; cannot erase it without a verified separation')
                m['backgroundLayer']=layer
    # Multiple OCR fields can share one printed rectangle.
    unique={ (m['page'],tuple(m['bbox'])):m for m in result }
    return list(unique.values())


def normalize(plan):
    """Join adjacent commentary mechanically, including across removed headers."""
    result=copy.deepcopy(plan);removed={i for e in result.get('excluded',[]) for i in e['indices']}
    chapters={c['at'] for c in result['chapters']};blocks=[]
    for block in result['blocks']:
        # Local is exclusive placement inside this block, whereas stem/answer
        # are image references. Preserve the references and let validate_plan
        # prove any borrowed stem against its earlier original question owner.
        for q in block['questions']:
            q['local']=[i for i in q['local'] if block['first']<=i<=block['last']]
        previous=blocks[-1] if blocks else None
        if previous and previous['kind']==block['kind']=='motivation' and not any(previous['last']<i<block['first'] for i in chapters) and all(i in removed for i in range(previous['last']+1,block['first'])):
            previous['last']=block['last'];previous['original']|=block['original'];previous['questions'].extend(block['questions'])
        else:blocks.append(block)
    result['blocks']=blocks
    return result
