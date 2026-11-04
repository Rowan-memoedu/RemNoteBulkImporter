"""Subject lectures: shared material preparation, original-image fields and feedback."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

from materials.common import REPO, file_sha, load, require, run_lock, save, source_run


def prepare(args,source,folder,identity):
    if source.suffix.lower()=='.json' and load(source).get('schema')=='lecture-collection/1':
        from lectures.collection import prepare_collection
        return prepare_collection(args,source,folder,identity)
    base=folder/'base'
    command=[sys.executable,str(REPO/'consumers/material.py'),'prepare',str(source),'--output',str(base),'--title',args.title or source.stem,'--layout',args.layout]
    if args.model:command+=['--model',args.model]
    if args.catalog:command+=['--catalog',args.catalog]
    result=subprocess.run(command)
    require(result.returncode==0,'Shared material preparation failed; preserve diagnostics and fix its generic workflow')
    from materials.validate import validate as validate_base
    validate_base(base)
    from materials.producer import Producer
    from lectures.contract import shared_contract
    from lectures.pixels import OriginalPages
    from lectures.batches import bounded_plan
    from lectures.build import compose,write_outputs
    from lectures.validate import validate
    title=args.title or load(base/'package.json')['title'];extraction=load(base/'extraction.json');contract,contract_id=shared_contract()
    pages=OriginalPages(source,folder/'original-pages')
    try:plan=bounded_plan(extraction,base,folder,title,contract,args.model,pages.previews(),getattr(args,'source_role',None))
    finally:pages.close()
    save(folder/'lecture-plan.json',plan)
    save(folder/'lecture-source.json',{**identity,'title':title,'base':str(base.resolve())})
    bundle=compose(base,folder,plan,title,contract,contract_id);write_outputs(bundle,folder)
    return validate(folder)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase',choices=['extract','prepare','validate','import','feedback','status'])
    p.add_argument('source',nargs='?');p.add_argument('--output');p.add_argument('--title');p.add_argument('--model')
    p.add_argument('--layout',choices=['document','mindmap'],default='document');p.add_argument('--catalog')
    p.add_argument('--source-role',choices=['questions','teaching'])
    p.add_argument('--kb-id');p.add_argument('--parent-rem-id');p.add_argument('--trial',action='store_true')
    p.add_argument('--replace-root');p.add_argument('--archive-parent-rem-id')
    p.add_argument('--result',choices=['accepted','needs-fix']);p.add_argument('--note')
    args=p.parse_args()
    if args.phase=='status':
        from materials.delivery import mcp
        print(json.dumps(mcp('status'),ensure_ascii=False));return
    if not args.source:p.error('source is required')
    source=Path(args.source).resolve(strict=True)
    output=args.output or str(Path('D:/Artifacts/RemNoteBulkImporter/lectures')/file_sha(source)[:24])
    source,folder,identity=source_run(source,output)
    with run_lock(folder):
        save(folder/'phase-status.json',{'phase':args.phase,'status':'running'})
        try:
            if args.phase=='prepare':result=prepare(args,source,folder,identity)
            elif args.phase=='extract':
                command=[sys.executable,str(REPO/'consumers/material.py'),'extract',str(source),'--output',str(folder/'base'),'--layout',args.layout]
                if args.model:command+=['--model',args.model]
                require(subprocess.run(command).returncode==0,'Shared material extraction failed');result={'status':'extracted'}
            else:
                require(load(folder/'lecture-source.json')['source_sha256']==identity['source_sha256'],'Prepared lecture belongs to another source')
                if args.phase=='validate':
                    from lectures.validate import validate
                    result=validate(folder)
                elif args.phase=='import':
                    from lectures.review import import_lecture
                    result=import_lecture(folder,args.kb_id,args.parent_rem_id,args.trial,args.replace_root,args.archive_parent_rem_id)
                else:
                    from lectures.review import feedback
                    result=feedback(folder,args.result,args.note)
            save(folder/'phase-status.json',{'phase':args.phase,'status':'complete'})
            print(json.dumps(result,ensure_ascii=False),flush=True)
        except Exception as error:
            save(folder/'phase-status.json',{'phase':args.phase,'status':'failed','error':str(error)})
            raise


if __name__=='__main__':main()
