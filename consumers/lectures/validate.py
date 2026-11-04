"""Source, pixel, field and package checks. Human form acceptance stays separate."""
import base64
from pathlib import Path

from materials.common import file_sha, load, require, save, sha
from materials.source_images import math_audit
from materials.validate import inspect_package
from .contract import shared_contract
from .build import compose


def validate(folder):
    if (folder/'collection.json').exists():
        from .collection import validate_collection
        return validate_collection(folder)
    identity=load(folder/'lecture-source.json');base=Path(identity['base'])
    require(base.resolve()!=folder.resolve() and not (base/'lecture-source.json').exists(),'Lecture must reference a generic material base')
    from materials.validate import validate as validate_base
    baseline=validate_base(base);source=load(base/'source.json')
    require(source['source_sha256']==identity['source_sha256'],'Lecture source differs from generic source')
    bundle=load(folder/'package.json');plan=load(folder/'lecture-plan.json');contract,contract_id=shared_contract()
    expected=compose(base,folder,plan,identity['title'],contract,contract_id)
    if (folder/'completion.json').exists() and bundle['provenance']['lecture']['implementation']!=expected['provenance']['lecture']['implementation']:
        # An already imported immutable artifact keeps its historical code
        # fingerprint. A later unrelated workflow edit must not falsify that
        # receipt or prevent the user from reviewing the completed trial.
        receipt=load(folder/'completion.json');info=inspect_package(folder/'package.json')
        registered=Path('D:/Artifacts/RemNoteBulkImporter/packages')/('material.'+info['hash']+'.json')
        require(receipt['packageHash']==info['hash'] and registered.is_file() and registered.read_bytes()==(folder/'package.json').read_bytes(),'Historical import is not its immutable registered package')
        expected['provenance']['lecture']['implementation']=bundle['provenance']['lecture']['implementation']
    require(bundle==expected,'Lecture package differs from its source/plan/contract; regenerate from original inputs')
    nodes={n['id']:n for n in bundle['nodes']};evidence=bundle['provenance']['lecture'];atoms=load(base/'extraction.json')['atoms']
    retained=[a for i,a in enumerate(atoms) if i not in evidence['excludedAtoms']]
    require(set(bundle['provenance']['atomToNode'])=={a['id'] for a in retained},'Lecture source coverage incomplete')
    for a in retained:
        target=bundle['provenance']['atomToNode'][a['id']]
        require(target in nodes or (target=='__root__' and a.get('text')==bundle['title']),'Unrepresented source atom')
    for crop in evidence['crops']:
        asset=bundle['assets'][crop['asset']]
        require(sha(base64.b64decode(asset['base64'],validate=True))==crop['sha256'],'Original crop bytes changed')
        require(crop['bbox'][0]==0 and crop['bbox'][2]==1000,'Side context was trimmed')
        for i in crop['atoms']:
            a=atoms[i];box=a['bbox']
            require(a['page']==crop['page'] and crop['bbox'][1]<=box[1]<=box[3]<=crop['bbox'][3],'Crop cuts off selected original content')
    for q in evidence['questions']:
        for field in ('stem','answer'):
            if not q[field]:continue
            n=nodes[q[field]]
            require(n['parentId']==q['node'] and not n['document'],'Question field hierarchy changed')
            require(any(s['kind']=='image' for s in n['text']) and all(s['kind']=='image' or (s['kind']=='text' and s['value'] in ('题面\n','答案\n','\n')) for s in n['text']),'Question/answer must be one original-image node, never OCR prose')
    info=inspect_package(folder/'package.json');math=math_audit(bundle['nodes'],folder,'math-validation')
    require(math['errors']==0,'Lecture native formula validation failed')
    for path in load(folder/'markdown-map.json').values():require(Path(path).is_file(),'Missing lecture Markdown')
    report={'status':'VALIDATED','source_sha256':identity['source_sha256'],'package_sha256':file_sha(folder/'package.json'),
        'source_atoms':baseline['source_atoms'],'retained_atoms':len(retained),'excluded_non_teaching_atoms':len(evidence['excludedAtoms']),'all_source_atoms_mapped':True,'chapters':sum(n['document'] for n in bundle['nodes']),
        'blocks':len(plan['blocks']),'questions':len(evidence['questions']),'with_answers':sum(q['answer'] is not None for q in evidence['questions']),
        'original_page_crops':len(evidence['crops']),'question_fields_are_single_image_nodes':True,'native_formulas':math['count'],
        'user_acceptance':'separate_from_automatic_validation','info':info}
    save(folder/'validation.json',report);return report
