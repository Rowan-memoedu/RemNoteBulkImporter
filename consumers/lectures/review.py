"""Natural user feedback controls reuse of a material form, not import integrity."""
import json
import os
from pathlib import Path

from materials.common import load, require, save, sha, run_lock
from .build import implementation

STATE=Path(os.getenv('RBI_LECTURE_STATE','D:/AppData/RemNoteBulkImporter/lectures'))


def form(bundle):
    evidence=bundle['provenance']['lecture']
    return {'source_kind':Path(load(Path(evidence['base'])/'source.json')['source']).suffix.lower(),
            'features':evidence['features'],'representation':'original-question-and-answer/2',
            'source_roles':sorted(sorted(s['roles']) for s in evidence.get('sources',[]))}


def state_path(bundle):
    return STATE/(sha(json.dumps(form(bundle),sort_keys=True))[:24]+'.json')


def check(bundle,trial,state):
    evidence=bundle['provenance']['lecture'];source=bundle['provenance']['sourceSha256']
    if state and state.get('status')=='accepted' and state.get('implementation')==evidence['implementation']==implementation() and state.get('sharedContract')==evidence['sharedContract']:
        return 'accepted'
    require(trial,'This material form needs a discussed trial; use --trial only for the user-selected first sample')
    if state and state.get('status')!='accepted':
        require(state.get('sourceSha256')==source,'Another sample of this form is awaiting user feedback; do not proceed to the next material')
    return 'trial'


def import_lecture(folder,kb_id,parent=None,trial=False,replace_root=None,archive=None):
    from .validate import validate
    from materials.delivery import deliver
    validate(folder);bundle=load(folder/'package.json');path=state_path(bundle)
    STATE.mkdir(parents=True,exist_ok=True)
    with run_lock(STATE):
        state=load(path) if path.exists() else None
        mode=check(bundle,trial,state)
        evidence=bundle['provenance']['lecture']
        if mode=='trial':
            # Persist the claim before writing; an interrupted trial still blocks
            # automatic submission of a different source with the same form.
            state={'form':form(bundle),'status':'trial_running','sourceSha256':bundle['provenance']['sourceSha256'],
                'implementation':evidence['implementation'],'sharedContract':evidence['sharedContract'],'folder':str(folder)}
            save(path,state)
        receipt=deliver(folder,kb_id,parent,replace_root,archive)
        if mode=='trial':
            state.update(status='awaiting_user_feedback',rootRemId=receipt['rootRemId'],packageHash=receipt['packageHash'])
            save(path,state)
        result={'mode':mode,'user_acceptance':'accepted' if mode=='accepted' else 'awaiting_user_feedback','rootRemId':receipt['rootRemId']}
        save(folder/'lecture-review.json',result);return result


def feedback(folder,result,note):
    require(result in ('accepted','needs-fix') and isinstance(note,str) and note.strip(),'Record the user\'s actual feedback')
    from .validate import validate
    validate(folder);bundle=load(folder/'package.json');path=state_path(bundle)
    require((folder/'completion.json').exists(),'Feedback requires a completed real import')
    receipt=load(folder/'completion.json')
    with run_lock(STATE):
        require(path.exists(),'No trial of this material form is registered')
        state=load(path)
        require(state['sourceSha256']==bundle['provenance']['sourceSha256'] and state.get('rootRemId')==receipt['rootRemId'] and state.get('packageHash')==receipt['packageHash'],'Feedback does not match this completed trial')
        require(state['implementation']==bundle['provenance']['lecture']['implementation'],'Regenerated workflow needs a new real trial before acceptance')
        state.update(status=result,feedback=note.strip());save(path,state)
    save(folder/'lecture-review.json',{'user_acceptance':result,'rootRemId':receipt['rootRemId'],'feedback':note.strip()})
    return {'status':result,'next_materials_allowed':result=='accepted'}
