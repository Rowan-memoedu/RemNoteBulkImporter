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


def deliver(folder,kb_id):
    require(kb_id,'import requires --kb-id; never infer the destination from the open window')
    report=validate(folder);info=report['info'];source=report['source_sha256']
    STATE.mkdir(parents=True,exist_ok=True)
    registry=STATE/(kb_id+'-'+source+'.json')
    live=mcp('status');save(folder/'destination-preflight.json',live)
    require(live.get('connected') and live.get('kbId')==kb_id,'Target RemNote knowledge base is disconnected or different')
    # Atomic filesystem claim protects two independent CLI invocations before
    # either reaches the service's single-writer guard. Existing claim is resumed.
    claim={'sourceSha256':source,'kbId':kb_id,'packageHash':info['hash'],'folder':str(folder)}
    try:
        with registry.open('x',encoding='utf-8') as stream:json.dump(claim,stream,ensure_ascii=False)
    except FileExistsError:
        previous=load(registry)
        require(previous['packageHash']==info['hash'],'This source already has a different import package in this library; inspect the existing receipt instead of duplicating it')
        if previous.get('status')=='complete':
            print(json.dumps({**previous,'status':'already_imported'},ensure_ascii=False));return previous
    active=live.get('activeJob')
    require(not active or (isinstance(active,dict) and active.get('jobId')==info['hash']) or active==info['hash'],'Another RemNote job is active')
    target=Path('D:/Artifacts/RemNoteBulkImporter/packages')/('material.'+info['hash']+'.json')
    target.parent.mkdir(parents=True,exist_ok=True)
    data=(folder/'package.json').read_bytes()
    if target.exists():require(target.read_bytes()==data,'Immutable package differs')
    else:target.write_bytes(data)
    job=mcp('prepare',target)
    require(job['jobId']==info['hash'],'Prepared package identity mismatch')
    save(folder/'import-request.json',{**claim,'jobId':job['jobId'],'packagePath':str(target)})
    if job['status'] not in ('complete','running','starting'):
        live=mcp('status')
        require(live.get('connected') and live.get('kbId')==kb_id,'Destination changed before start')
        require(not live.get('busy') and not live.get('activeJob'),'Writer became busy before start')
        job=mcp('start',job['jobId'])
    last=None
    while job['status'] in ('starting','running'):
        if job.get('progress')!=last:
            last=job.get('progress');print(json.dumps({'status':job['status'],'progress':last},ensure_ascii=False),flush=True)
        time.sleep(10);job=mcp('job',job['jobId'])
    save(folder/'import-receipt.json',job)
    require(job['status']=='complete','Import not complete; resume with the same source and output after resolving the recorded error')
    native=load(Path('D:/AppData/RemNoteBulkImporter')/(job['jobId']+'.result.json'))
    require(native['kbId']==kb_id and native['hash']==job['jobId'],'Readback identity mismatch')
    require(native['verified']==info['nodes']+1 and job['verifiedManagedAssets']==info['assets'],'Incomplete node/media readback')
    receipt={**claim,'status':'complete','rootRemId':native['rootRemId'],'nodesVerified':native['verified'],
             'managedImagesVerified':job['verifiedManagedAssets'],'kbName':live.get('kbName')}
    save(folder/'remnote-map.json',native['mapping']);save(folder/'completion.json',receipt);save(registry,receipt)
    print(json.dumps(receipt,ensure_ascii=False),flush=True)
    return receipt
