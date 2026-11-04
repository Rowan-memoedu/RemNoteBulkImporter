"""Load the website's canonical fields; never maintain a second Topic schema."""
import importlib.util
import os
import re
from pathlib import Path

from materials.common import file_sha, require


LABEL_NUMBER=r'(?:[\[【［]\s*)?(?:(?:例题?|习题|题|Example|Exercise)\s*)?(\d+)(?:\s*(?:多选|单选|填空|选择题|[★☆*]+))*\s*[\]】］]?[.．、:]?'


def question_number(label):
    match=re.fullmatch(LABEL_NUMBER,label,re.I)
    return match[1] if match else None


def printed_difficulty(question,atoms):
    number=question_number(question.get('label',''))
    found=[]
    for i in question['stem']:
        for match in re.finditer(r'[\[【［]\s*(?:例题?|习题|题|Example|Exercise)\s*(\d+)([^\]】］\r\n]{0,80})[\]】］]',atoms[i].get('text',''),re.I):
            if number and match[1]!=number:continue
            stars=re.search(r'[★☆⭐]+',match[2])
            if stars:found.append((match[1],stars[0]))
    values=set(found)
    return next(iter(values))[1] if len(values)==1 else None


def shared_contract():
    path=Path(os.getenv('RBI_TOPIC_CONTRACT','D:/Projects/GraspMemoEdu/graspmemoedu/topic_format.py'))
    require(path.is_file(),'Shared Topic contract is missing; set RBI_TOPIC_CONTRACT')
    spec=importlib.util.spec_from_file_location('rbi_shared_topic_format',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    require(module.VERSION==2,'Unsupported shared Topic contract version')
    return module,{'path':str(path.resolve()),'sha256':file_sha(path),'version':module.VERSION}


def question_source(question,title,atoms,contract):
    source=question.get('source',{})
    require(isinstance(source,dict) and set(source)<=set(contract.SOURCE_FIELDS)|{'difficulty'},'Unknown shared source field')
    require(all(isinstance(v,str) and v.strip() for v in source.values()),'Empty/invalid source field')
    evidence=question.get('source_evidence',[])
    require(all(type(i) is int and 0<=i<len(atoms) for i in evidence),'Invalid metadata evidence')
    original='\n'.join(atoms[i].get('text','') for i in evidence)
    for value in source.values():
        require(value in original,'Source/difficulty must be copied from original evidence, never inferred: '+value)
    difficulty=printed_difficulty(question,atoms)
    if difficulty and (not source.get('difficulty') or re.fullmatch(r'[★☆⭐]+',source['difficulty'])):
        source={**source,'difficulty':difficulty}
    if not any(source.get(k) for k in contract.SOURCE_FIELDS):source={**source,'name':title}
    requirement=question.get('requirement','')
    require(isinstance(requirement,str) and (not requirement or requirement in original),'Requirement lacks exact source evidence')
    return source,contract.source_label(source),requirement
