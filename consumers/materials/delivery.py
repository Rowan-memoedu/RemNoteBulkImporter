"""Explicit MCP delivery; source-scoped deduplication survives package revisions."""
import json
import os
import subprocess
import time
from pathlib import Path

from .common import REPO, STATE, file_sha, load, require, save
from .validate import inspect_package, validate


def mcp(command,*args):
    result=subprocess.run(['node',str(REPO/'src/cli.mjs'),command,*map(str,args)],capture_output=True,text=True,encoding='utf-8',timeout=120)
    require(result.returncode==0,'RemNote MCP call failed: '+(result.stderr or result.stdout)[-1200:])
    return json.loads(result.stdout)


def native(kb_id,action,**args):
    result=subprocess.run(['node',str(REPO/'consumers/material-native.mjs')],input=json.dumps({'kbId':kb_id,'action':action,**args}),capture_output=True,text=True,encoding='utf-8',timeout=120)
    require(result.returncode==0,'Exact-ID local MCP operation failed: '+(result.stderr or result.stdout)[-1200:])
    return json.loads(result.stdout)


def finish_replacement(folder,kb_id,receipt,previous,registry,archive):
    old=previous['rootRemId'];new=receipt['rootRemId']
    require(old!=new and archive not in (old,new),'Replacement and recovery roots must be distinct')
    rows=native(kb_id,'read',remIds=[old,new,archive])['nodes'];by_id={r['id']:r for r in rows}
    require(set(by_id)=={old,new,archive},'Replacement root or recovery container missing')
    require(by_id[new]['parentId']==receipt.get('parentRemId'),'Replacement root placement changed')
    require(by_id[old]['parentId'] in (previous.get('parentRemId'),archive),'Old root placement changed')
    require(by_id[archive]['parentId'] is None,'Recovery container must be at library root')
    moved=native(kb_id,'move',remId=old,parentRemId=archive,expectedParentRemId=previous.get('parentRemId'))
    recovery={'previous':previous,'replacement':receipt,'archiveParentRemId':archive,'move':moved}
    save(folder/'replacement-recovery.json',recovery)
    receipt={**receipt,'replacesRootRemId':old,'archiveParentRemId':archive}
    save(folder/'completion.json',receipt);save(registry,receipt)
    return receipt


def deliver(folder,kb_id,parent_rem_id=None,replace_root=None,archive_parent=None):
    require(kb_id,'import requires --kb-id; never infer the destination from the open window')
    report=validate(folder);info=report['info'];source=report['source_sha256']
    STATE.mkdir(parents=True,exist_ok=True)
    registry=STATE/(kb_id+'-'+source+'.json');primary=registry;previous=None
    live=mcp('status');save(folder/'destination-preflight.json',live)
    require(live.get('connected') and live.get('kbId')==kb_id,'Target RemNote knowledge base is disconnected or different')
    require(bool(replace_root)==bool(archive_parent),'Replacement requires both --replace-root and --archive-parent-rem-id')
    if replace_root:
        require(registry.exists(),'Replacement requires an existing completed source receipt')
        previous=load(registry)
        if previous.get('replacesRootRemId')==replace_root and previous['packageHash']==info['hash']:
            require(previous.get('archiveParentRemId')==archive_parent,'Recovery destination differs')
            print(json.dumps({**previous,'status':'already_imported'},ensure_ascii=False),flush=True)
            return previous
        require(previous.get('status')=='complete' and previous.get('rootRemId')==replace_root,'Replacement root must match the completed source receipt')
        require(previous.get('parentRemId')==parent_rem_id,'Replacement cannot change source placement')
        require(previous['packageHash']!=info['hash'],'Replacement package is unchanged')
        rows=native(kb_id,'read',remIds=[replace_root,archive_parent])['nodes'];by_id={r['id']:r for r in rows}
        require(replace_root in by_id and archive_parent in by_id and replace_root!=archive_parent,'Exact replacement/recovery roots missing or identical')
        require(by_id[replace_root]['parentId'] in (parent_rem_id,archive_parent) and by_id[archive_parent]['parentId'] is None,'Replacement preflight placement differs')
        save(folder/'replacement-preflight.json',{'previous':previous,'archiveParentRemId':archive_parent,'nodes':rows})
        registry=STATE/(kb_id+'-'+source+'.replace-'+replace_root+'.json')
    # Atomic filesystem claim protects two independent CLI invocations before
    # either reaches the service's single-writer guard. Existing claim is resumed.
    claim={'sourceSha256':source,'kbId':kb_id,'parentRemId':parent_rem_id,'packageHash':info['hash'],'folder':str(folder)}
    try:
        with registry.open('x',encoding='utf-8') as stream:json.dump(claim,stream,ensure_ascii=False)
    except FileExistsError:
        existing=load(registry)
        require(existing['packageHash']==info['hash'],'This source already has a different import package in this library; inspect the existing receipt instead of duplicating it')
        require(existing.get('parentRemId')==parent_rem_id,'This source already targets a different parent; inspect its existing placement instead of duplicating or moving it')
        if existing.get('status')=='complete':
            if replace_root:existing=finish_replacement(folder,kb_id,existing,previous,primary,archive_parent)
            print(json.dumps({**existing,'status':'already_imported'},ensure_ascii=False));return existing
    active=live.get('activeJob')
    require(not active or (isinstance(active,dict) and active.get('jobId')==info['hash']) or active==info['hash'],'Another RemNote job is active')
    target=Path('D:/Artifacts/RemNoteBulkImporter/packages')/('material.'+info['hash']+'.json')
    target.parent.mkdir(parents=True,exist_ok=True)
    data=(folder/'package.json').read_bytes()
    if target.exists():require(target.read_bytes()==data,'Immutable package differs')
    else:target.write_bytes(data)
    job=mcp('prepare',target)
    require(job['jobId']==info['hash'],'Prepared package identity mismatch')
    if job.get('kbId'):
        require(job['kbId']==kb_id and job.get('parentRemId')==parent_rem_id,'Existing job destination differs from the requested library or parent')
    save(folder/'import-request.json',{**claim,'jobId':job['jobId'],'packagePath':str(target)})
    if job['status'] not in ('complete','running','starting'):
        live=mcp('status')
        require(live.get('connected') and live.get('kbId')==kb_id,'Destination changed before start')
        require(not live.get('busy') and not live.get('activeJob'),'Writer became busy before start')
        job=mcp('start',job['jobId'],*([parent_rem_id] if parent_rem_id else []))
    last=None
    while job['status'] in ('starting','running'):
        if job.get('progress')!=last:
            last=job.get('progress');print(json.dumps({'status':job['status'],'progress':last},ensure_ascii=False),flush=True)
        time.sleep(10);job=mcp('job',job['jobId'])
    save(folder/'import-receipt.json',job)
    require(job['status']=='complete','Import not complete; resume with the same source and output after resolving the recorded error')
    require(job.get('parentRemId')==parent_rem_id,'Completed import parent differs from the request')
    readback=load(Path('D:/AppData/RemNoteBulkImporter')/(job['jobId']+'.result.json'))
    require(readback['kbId']==kb_id and readback['hash']==job['jobId'],'Readback identity mismatch')
    require(readback['verified']==info['nodes']+1 and job['verifiedManagedAssets']==info['assets'],'Incomplete node/media readback')
    receipt={**claim,'status':'complete','rootRemId':readback['rootRemId'],'nodesVerified':readback['verified'],
             'managedImagesVerified':job['verifiedManagedAssets'],'kbName':live.get('kbName')}
    save(folder/'remnote-map.json',readback['mapping']);save(registry,receipt)
    if replace_root:
        save(folder/'new-tree-completion.json',receipt)
        receipt=finish_replacement(folder,kb_id,receipt,previous,primary,archive_parent)
    else:save(folder/'completion.json',receipt)
    print(json.dumps(receipt,ensure_ascii=False),flush=True)
    return receipt
