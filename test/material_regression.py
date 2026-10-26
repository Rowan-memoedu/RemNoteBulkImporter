"""Replay a previously validated source/structure fixture through new converters."""
import argparse
import copy
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'consumers'))
from materials.common import load,save,source_run,require
from materials.extract import extract
from materials.render import build
from materials.validate import validate


def regression(reference,output):
    previous=load(reference/'inventory.json');old=load(reference/'package.json')
    source,folder,_=source_run(previous['source'],output)
    extracted=extract(source,folder)
    atoms=copy.deepcopy(extracted['atoms'])
    require(len(atoms)==len(previous['atoms']),'Regression source atom count differs')
    for new,prior in zip(atoms,previous['atoms']):
        require(new['text']==prior['text'] and new['kind']==prior['kind'],'Regression source bytes differ')
        new['doc']=prior['doc']
    docs=copy.deepcopy(previous['documents']);ids={a['id']:b['id'] for a,b in zip(previous['atoms'],atoms)}
    for d in docs:
        if d['title_atom']:d['title_atom']=ids[d['title_atom']]
    groups=[]
    for path in sorted((reference/'hierarchy').glob('batch-*.json')):groups.extend(load(path)['groups'])
    structure={'atoms':atoms,'documents':docs,'groups':groups,'basis':'validated-regression-fixture'}
    save(folder/'structure.json',structure)
    build(extracted,structure,folder,old['title'])
    report=validate(folder)
    report['regression_reference']=str(reference);save(folder/'regression.json',report)
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('reference');p.add_argument('output');a=p.parse_args();regression(Path(a.reference),Path(a.output))
