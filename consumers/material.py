"""One command for local material extraction, structure, validation and MCP import."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from materials.common import source_run, run_lock, save, require, load
from materials.extract import extract


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['extract','prepare','validate','import','status'])
    parser.add_argument('source',nargs='?')
    parser.add_argument('--output')
    parser.add_argument('--title')
    parser.add_argument('--model')
    parser.add_argument('--kb-id')
    parser.add_argument('--parent-rem-id')
    parser.add_argument('--replace-root',help='Explicitly replace this completed source root; keep the old tree recoverable')
    parser.add_argument('--archive-parent-rem-id',help='Exact library-root recovery container for the replaced tree')
    parser.add_argument('--layout',choices=['document','mindmap'],default='document',help='mindmap follows proved vector PDF connectors instead of linear reading order')
    parser.add_argument('--catalog',help='Editorial catalog JSON for a frozen website snapshot; every source page must be placed')
    args=parser.parse_args()
    if args.phase=='status':
        from materials.delivery import mcp
        print(json.dumps(mcp('status'),ensure_ascii=False));return
    if not args.source:
        parser.error('source is required')
    source,folder,identity=source_run(args.source,args.output)
    print('RUN '+str(folder),flush=True)
    with run_lock(folder):
        require(load(folder/'source.json')['source_sha256']==identity['source_sha256'],'Concurrent source identity change')
        save(folder/'phase-status.json',{'status':'running','phase':args.phase})
        try:
            from materials.inputs import source_kind,run_special
            kind=source_kind(source,args.layout)
            require(not args.catalog or kind=='publish-snapshot','--catalog requires a website snapshot')
            if kind!='document':
                result=run_special(args,source,folder,kind)
                if args.phase!='import' and not (args.phase=='prepare' and kind=='publish-snapshot'):print(json.dumps(result,ensure_ascii=False),flush=True)
            elif args.phase=='extract':extract(source,folder)
            else:
                from materials.workflow import run
                run(args,source,folder,identity)
        except Exception as error:
            save(folder/'phase-status.json',{'status':'failed','phase':args.phase,'error':str(error)})
            raise
        save(folder/'phase-status.json',{'status':'complete','phase':args.phase})


if __name__=='__main__':
    main()
