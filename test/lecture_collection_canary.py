"""Independent two-source end-to-end canary, with no answers in production prompts."""
import json
import subprocess
import sys
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont

folder=Path(sys.argv[1]);folder.mkdir(parents=True,exist_ok=True)
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',30)
bold=ImageFont.truetype('C:/Windows/Fonts/arialbd.ttf',38)
for name,rows in {
    'notes':[(70,'1. Motion',bold,'black'),
             (170,'Journeys let us compare rates of travel.',font,'black'),
             (235,'This is useful when planning a trip.',font,'black'),
             (350,'Definition: distance is the length of a path.',font,'black'),
             (450,'Definition: speed is distance divided by time.',font,'black'),
             (540,'1.1 Worked illustrations',bold,'black'),
             (620,'[Example 1] Travel 20 metres in 5 seconds. Find the speed.',font,'black'),
             (730,'Original note: 20 / 5 = 4 metres per second.',font,'blue'),
             (850,'Variant: travel 9 metres in 3 seconds. Find the speed.',font,'black'),
             (960,'Worked variant: 9 / 3 = 3 metres per second.',font,'blue')],
    'solutions':[(70,'1. Motion',bold,'black'),
                 (240,'[Example 1] Travel 20 metres in 5 seconds. Find the speed.',font,'black'),
                 (350,'Answer: v = distance / time = 20 / 5 = 4 metres per second.',font,'black'),
                 (640,'[Example 2] Travel 30 metres in 6 seconds. Find the speed.',font,'black'),
                 (950,'ADVERTISEMENT: Buy the Example Brand subscription.',font,'gray')]
}.items():
    image=Image.new('RGB',(1700,1120),'white');draw=ImageDraw.Draw(image)
    for y,text,f,c in rows:draw.text((80,y),text,font=f,fill=c)
    if name=='notes':draw.ellipse((50,615,75,660),outline='red',width=5)
    image.save(folder/(name+'.png'))
manifest=folder/'input.json'
manifest.write_text(json.dumps({'schema':'lecture-collection/1','title':'Motion collection','sources':[
    {'id':'notes','path':str(folder/'notes.png'),'roles':['teaching','answers']},
    {'id':'solutions','path':str(folder/'solutions.png'),'roles':['questions','answers']}]},indent=2),encoding='utf8')
repo=Path(__file__).resolve().parents[1];run=folder/'run'
result=subprocess.run(['node',str(repo/'consumers/lecture-workflow.mjs'),'prepare',str(manifest),'--output',str(run)])
if result.returncode:raise SystemExit(result.returncode)
report=json.loads((run/'validation.json').read_text(encoding='utf8'))
assert report['questions']==2 and report['with_answers']==1 and report['answers_from_multiple_sources']==1 and report['supplementary_teaching_examples']==1,report
matches=json.loads((run/'question-matches.json').read_text(encoding='utf8'));assert len(matches)==2,matches
bundle=json.loads((run/'package.json').read_text(encoding='utf8'))
assert not any('ADVERTISEMENT' in s.get('value','') for n in bundle['nodes'] for s in n['text'])
(folder/'canary.json').write_text(json.dumps({'status':'PASSED','independent_sources':2,'questions':2,'multiple_original_answers':1,'validation':str(run/'validation.json')},indent=2)+'\n',encoding='utf8')
print('INDEPENDENT MULTI-MATERIAL CANARY PASSED',flush=True)
