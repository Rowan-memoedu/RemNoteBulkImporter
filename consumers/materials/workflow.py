import json
import subprocess

from .common import REPO, load, save, require
from .extract import extract


def run(args,source,folder,identity):
    if args.phase=='validate':
        from .validate import validate
        print(json.dumps(validate(folder),ensure_ascii=False));return
    if args.phase=='import':
        from .delivery import deliver
        deliver(folder,args.kb_id,args.parent_rem_id);return
    from .structure import prepare_structure
    from .render import build
    from .validate import validate
    extraction=extract(source,folder)
    structure=prepare_structure(extraction,folder,args.model)
    bundle=build(extraction,structure,folder,args.title or source.stem)
    report=validate(folder)
    rendered=subprocess.run(['node',str(REPO/'consumers/render-material-preview.mjs'),str(folder)],capture_output=True,text=True,encoding='utf-8',timeout=120)
    require(rendered.returncode==0,'Offline math preview failed')
    from .render import local_preview
    (folder/'preview.html').write_text(local_preview(bundle,load(folder/'preview-math.json')),encoding='utf-8')
    save(folder/'run.json',{'source':identity,'title':bundle['title'],'status':'prepared','validation':report})
    print(json.dumps(report,ensure_ascii=False),flush=True)
