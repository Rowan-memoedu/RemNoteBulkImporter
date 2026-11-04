"""Independent full-pipeline canary generated from a small synthetic source.

The producer sees only the PNG and the normal shared instructions. Assertions
are kept here, never passed to OCR or semantic planning.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image,ImageDraw,ImageFont


def main():
    parser=argparse.ArgumentParser();parser.add_argument('output');args=parser.parse_args()
    folder=Path(args.output);folder.mkdir(parents=True,exist_ok=True)
    source=folder/'mechanics.png'
    font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',30)
    bold=ImageFont.truetype('C:/Windows/Fonts/arialbd.ttf',36)
    image=Image.new('RGB',(1600,1360),'white');draw=ImageDraw.Draw(image)
    rows=[(60,'Mechanics notes',bold,'black'),(150,'Section 1: Motion',bold,'black'),
          (240,'We measure travel time to compare moving objects.',font,'black'),
          (300,'This comparison helps us discuss everyday journeys.',font,'black'),
          (390,'Definition: speed is distance divided by time.',font,'black'),
          (480,'Definition: acceleration is velocity change divided by elapsed time.',font,'black'),
          (620,'1. A cart travels 12 metres in 3 seconds. Find its speed.',font,'black'),
          (700,'Answer: v = 12 / 3 = 4 metres per second.',font,'blue'),
          (900,'2. A runner travels 18 metres in 6 seconds. Find the speed.',font,'black'),
          (1240,'ADVERTISEMENT: Subscribe to Example Sponsor for paid courses.',font,'gray')]
    for y,text,f,color in rows:draw.text((80,y),text,font=f,fill=color)
    draw.ellipse((70,616,104,660),outline='red',width=4)
    draw.line((1100,740,1450,770),fill='blue',width=6)
    image.save(source)
    repo=Path(__file__).resolve().parents[1];run=folder/'run'
    result=subprocess.run(['node',str(repo/'consumers/lecture-workflow.mjs'),'prepare',str(source),'--output',str(run),'--title','Mechanics notes'])
    if result.returncode:raise SystemExit(result.returncode)
    report=json.loads((run/'validation.json').read_text(encoding='utf8'))
    assert report['questions']==2,report
    assert report['with_answers']==1,report
    assert report['all_source_atoms_mapped'] and report['question_fields_are_single_image_nodes'],report
    plan=json.loads((run/'lecture-plan.json').read_text(encoding='utf8'))
    assert sum(b['kind']=='motivation' for b in plan['blocks'])==1,plan
    assert sum(b['kind']=='memory' for b in plan['blocks'])>=2,plan
    assert report['excluded_non_teaching_atoms']>=1,report
    (folder/'canary.json').write_text(json.dumps({'status':'PASSED','independent_source':True,'questions':2,'with_answers':1,'validation':str(run/'validation.json')},indent=2)+'\n',encoding='utf8')
    print('INDEPENDENT LECTURE CANARY PASSED',flush=True)


if __name__=='__main__':main()
