"""Exact source-image representations for objectively broken OCR formulas."""
import subprocess
from pathlib import Path

from .common import REPO, file_sha, load, require, save, sha


def math_audit(nodes, folder, name):
    source=folder/(name+'-input.json');target=folder/(name+'.json')
    save(source,{'nodes':nodes})
    result=subprocess.run(['node',str(REPO/'consumers/audit-math.mjs'),str(source),str(target)],
                          capture_output=True,text=True,encoding='utf-8',timeout=120)
    require(result.returncode==0,'Formula audit process failed')
    return load(target)


def outline_parent(index, structure):
    parents=[g['parent'] for g in structure['groups'] if g['parent']<index<=g['through']]
    return structure['atoms'][max(parents)]['id'] if parents else structure['atoms'][index]['doc']


def same_source_region(a,b):
    return all(a.get(k) is not None and a[k]==b.get(k) for k in ('block','page','bbox','doc'))


def pdf_crop(source, atom):
    import pymupdf
    require(Path(source).suffix.lower()=='.pdf','Broken OCR has no PDF source image')
    box=atom.get('bbox');page=atom.get('page')
    require(isinstance(box,list) and len(box)==4 and all(isinstance(x,(int,float)) for x in box)
            and 0<=box[0]<box[2]<=1000 and 0<=box[1]<box[3]<=1000,'Invalid OCR crop bounds')
    with pymupdf.open(source) as pdf:
        require(isinstance(page,int) and 1<=page<=len(pdf),'Invalid OCR crop page')
        view=pdf[page-1];r=view.rect
        # MinerU bounding boxes use a normalized 0..1000 page coordinate space.
        clip=pymupdf.Rect(r.x0+r.width*box[0]/1000,r.y0+r.height*box[1]/1000,
                         r.x0+r.width*box[2]/1000,r.y0+r.height*box[3]/1000)
        return view.get_pixmap(matrix=pymupdf.Matrix(3,3),clip=clip,alpha=False).tobytes('png')


def source_representation(extraction, structure, index, folder, assets, error):
    a=structure['atoms'][index]
    require(a.get('block') is not None and a.get('source_type') in ('text','table','equation'),
            'Broken formula has no OCR source evidence')
    record={'atom':a['id'],'raw_text_sha256':sha(a['text']),'error':error}
    following=structure['atoms'][index+1:index+2]
    companion=following[0] if following and a['kind']=='table' and following[0]['kind']=='image' and same_source_region(a,following[0]) else None
    if companion:
        require(file_sha(companion['path'])==companion['sha256'],'Source image changed')
        asset=assets.add_file(companion['path'])
        record.update(mode='ocr_table_image',source_image_atom=companion['id'],source_image_sha256=companion['sha256'])
    else:
        require(file_sha(extraction['source'])==extraction['source_sha256'],'Original source changed')
        data=pdf_crop(extraction['source'],a);digest=sha(data)
        target=folder/'source-crops'/(digest+'.png');target.parent.mkdir(exist_ok=True)
        if not target.exists():target.write_bytes(data)
        require(file_sha(target)==digest,'Source crop changed')
        asset=assets.add_file(target)
        record.update(mode='pdf_crop',page=a['page'],bbox=a['bbox'],source_sha256=extraction['source_sha256'],image_sha256=digest)
    record['assetId']=asset
    return [{'kind':'image','assetId':asset}],record


def image_aliases(atoms, structure, runs, fallbacks):
    records={r['atom']:r for r in fallbacks};aliases={}
    for i,a in enumerate(atoms):
        if not i:continue
        previous=atoms[i-1];p=records.get(previous['id'])
        if not p or not same_source_region(a,previous) or outline_parent(i,structure)!=outline_parent(i-1,structure):continue
        if a['id'] not in records and p.get('source_image_atom')!=a['id']:continue
        if runs[a['id']]!=runs[previous['id']]:continue
        aliases[a['id']]=aliases.get(previous['id'],previous['id'])
    return aliases
