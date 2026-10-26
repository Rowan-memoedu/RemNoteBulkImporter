"""Small checked-call adapter over the maintained Codex Exec batch transport."""
import json
import sys
import time
from pathlib import Path

from .common import READING, load, require, save, sha


class Producer:
    def __init__(self, folder, model=None):
        sys.path.insert(0,str(READING/'standard-preprocessing'))
        from batch_transport import BatchClient
        self.client=BatchClient(model=model)
        self.folder=folder/'codex'
        self.folder.mkdir(exist_ok=True)

    def call(self, name, instructions, data, validator, images=None):
        identity={'transport':self.client.cache_identity,'instructions':instructions,'data':data,
                  'images':images or []}
        digest=sha(json.dumps(identity,ensure_ascii=False,sort_keys=True))
        target=self.folder/(name+'-'+digest[:16]+'.json')
        # A model choice applies to remaining work. Previously accepted results
        # retain their actual backend/model receipt instead of being regenerated.
        semantic={k:v for k,v in identity.items() if k!='transport'}
        for previous in sorted(self.folder.glob(name+'-*.json')):
            cached=load(previous)
            if 'result' not in cached or {k:v for k,v in cached.get('identity',{}).items() if k!='transport'}!=semantic:
                continue
            validator(cached['result'])
            require(cached['response'].get('provider')=='codex_exec' and cached['response']['transport']['completed_event'],'Cached invalid producer receipt')
            return cached['result']
        if target.exists():
            cached=load(target)
            validator(cached['result'])
            require(cached['response']['transport']['completed_event'],'Cached incomplete model turn')
            return cached['result']
        feedback=''
        # Resume an objectively failed call with its specific validator feedback,
        # rather than making it rediscover the same rejected interval each run.
        rejected=sorted(self.folder.glob(name+f'-{digest[:16]}-rejected-*.json'))
        if rejected:
            old=load(rejected[-1]);raw=old['response']['choices'][0]['message']['content'].strip()
            if raw.startswith('```'):raw=raw.split('\n',1)[1].rsplit('```',1)[0]
            try:validator(json.loads(raw))
            except (ValueError,KeyError,TypeError,IndexError,AttributeError) as error:
                feedback='\n之前失败的具体原因：'+str(error)+'。从原始数据重新生成，避免该错误；不要输出无子项的零长度区间。'
        for attempt in range(3):
            print(f'CODEX {name}, attempt {attempt+1}, model {self.client.model}',flush=True)
            try:
                response=self.client.raw([{'role':'system','content':instructions+'\n只返回 JSON，不使用 Markdown 代码围栏。'+feedback},
                                          {'role':'user','content':json.dumps(data,ensure_ascii=False)}], images=images or [])
            except RuntimeError as error:
                save(self.folder/(name+f'-{digest[:16]}-transport-{attempt}.json'),{'error':str(error),'model':self.client.model,'provider':'codex_exec'})
                if attempt==2:raise
                time.sleep(5*(attempt+1));continue
            require(response.get('provider')=='codex_exec' and response.get('transport',{}).get('completed_event'), 'Incomplete/non-Codex response')
            raw=response['choices'][0]['message']['content'].strip()
            if raw.startswith('```'):
                raw=raw.split('\n',1)[1].rsplit('```',1)[0]
            try:
                result=json.loads(raw)
                validator(result)
            except (ValueError,KeyError,TypeError,IndexError,AttributeError) as error:
                save(self.folder/(name+f'-{digest[:16]}-rejected-{attempt}.json'),{'response':response,'error':str(error)})
                if attempt==2:raise
                feedback='\n上次结果未通过校验：'+str(error)+'。从原始输入重新生成完整 JSON，不修改来源。'
                continue
            save(target,{'identity':identity,'result':result,'response':response})
            return result
