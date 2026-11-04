"""One material entry point; input-specific adapters share delivery and audits."""
from pathlib import Path

from .common import load, require, save


def source_kind(source,layout='document'):
    if layout=='mindmap':
        require(source.suffix.lower()=='.pdf','Mind-map mode currently requires a vector PDF')
        return 'vector-mindmap'
    if source.suffix.lower()=='.json':
        value=load(source)
        require(isinstance(value,dict) and isinstance(value.get('site'),str) and isinstance(value.get('pages'),list),
                'JSON input must be a frozen website Markdown snapshot with site/pages')
        require((source.parent/'assets.json').is_file() and (source.parent/'cache.json').is_file(),'Website snapshot lacks media/path receipts')
        return 'publish-snapshot'
    return 'document'


def run_special(args,source,folder,kind):
    if args.phase in ('validate','import'):
        from .validate import validate
        if args.phase=='validate':return validate(folder)
        from .delivery import deliver
        return deliver(folder,args.kb_id,args.parent_rem_id)
    if kind=='publish-snapshot':
        from .publish_snapshot import prepare
        return prepare(source,folder,args.title or load(source).get('title') or '网站资料',getattr(args,'catalog',None),extract_only=args.phase=='extract')
    from .mindmap import extract_mindmap
    extraction,structure=extract_mindmap(source,folder)
    if args.phase=='extract':return {'status':'extracted','atoms':len(extraction['atoms']),'adapter':kind}
    from .render import build
    from .validate import validate
    from .publish_snapshot import render_preview
    bundle=build(extraction,structure,folder,args.title or source.stem)
    report=validate(folder);render_preview(folder)
    save(folder/'run.json',{'source':str(source),'title':bundle['title'],'status':'prepared','validation':report,'adapter':kind})
    return report
