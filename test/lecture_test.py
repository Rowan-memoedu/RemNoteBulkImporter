"""Independent small fixtures; neither private notes nor model answers in Git."""
import base64
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image,ImageDraw

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'consumers'))
from materials.common import file_sha,load,save
from materials.render import build
from lectures.build import compose,write_outputs
from lectures.contract import shared_contract
from lectures.pixels import OriginalPages
from lectures.plan import validate_plan
from lectures.review import check
from lectures.validate import validate
from lectures.cleanup import normalize,masks


class LectureTests(unittest.TestCase):
    def setUp(self):
        root=Path('D:/Artifacts/RemNoteBulkImporter/lecture-tests');root.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=root);self.folder=Path(self.temp.name);self.base=self.folder/'base';self.base.mkdir()
        self.source=self.folder/'source.png'
        image=Image.new('RGB',(1000,800),'white');draw=ImageDraw.Draw(image)
        draw.text((70,60),'A. Mechanics',fill='black');draw.text((70,140),'A useful fact.',fill='black')
        draw.text((70,240),'1. Find a quantity. Exam Alpha',fill='black');draw.line((45,225,770,300),fill='red',width=4)
        draw.text((70,350),'The original answer.',fill='blue');draw.text((70,520),'2. No supplied answer.',fill='black')
        image.save(self.source)
        specs=[('A. Mechanics',[60,70,650,110]),('A useful fact.',[60,160,750,220]),('1. Find a quantity. Exam Alpha',[60,280,800,360]),('The original answer.',[60,420,800,480]),('2. No supplied answer.',[60,630,800,700])]
        atoms=[{'id':f'a{i:06d}','kind':'text','text':text,'page':1,'bbox':box} for i,(text,box) in enumerate(specs)]
        self.e={'source':str(self.source),'source_sha256':file_sha(self.source),'atoms':atoms,'metadata':{},'coverage':{'fields':len(atoms)}}
        self.s={'atoms':[dict(a,doc='d') for a in atoms],'documents':[{'id':'d','title':'Mechanics','title_atom':None,'parent':None,'start':0,'end':len(atoms)}],'groups':[],'basis':'fixture'}
        save(self.base/'source.json',{'source':str(self.source),'source_sha256':file_sha(self.source)})
        save(self.base/'extraction.json',self.e);save(self.base/'structure.json',self.s);build(self.e,self.s,self.base,'Mechanics')
        self.contract,self.contract_id=shared_contract()
        self.plan={'chapters':[{'at':0,'title':'A. Mechanics','level':1}],
            'blocks':[{'first':1,'last':1,'kind':'memory','original':False,'questions':[]},
                {'first':2,'last':3,'kind':'question','original':True,'questions':[{'local':[2,3],'stem':[2],'answer':[3],'source':{'name':'Exam Alpha'},'source_evidence':[2],'requirement':'','label':'1.'}]},
                {'first':4,'last':4,'kind':'question','original':True,'questions':[{'local':[4],'stem':[4],'answer':[],'source':{},'source_evidence':[],'requirement':'','label':'2.'}]}],
            'features':['printed','handwritten','inline_answers'],'unresolved':[]}

    def tearDown(self):self.temp.cleanup()

    def bundle(self):return compose(self.base,self.folder,self.plan,'Mechanics',self.contract,self.contract_id)

    def prepared(self):
        bundle=self.bundle();save(self.folder/'lecture-plan.json',self.plan)
        save(self.folder/'lecture-source.json',{'source_sha256':self.e['source_sha256'],'base':str(self.base),'title':'Mechanics'})
        write_outputs(bundle,self.folder);return bundle

    def test_original_question_answer_fields_and_fallback_source(self):
        bundle=self.prepared();report=validate(self.folder)
        self.assertEqual(report['questions'],2);self.assertEqual(report['with_answers'],1)
        questions=bundle['provenance']['lecture']['questions'];self.assertEqual(questions[1]['source'],{'name':'Mechanics'})
        nodes={n['id']:n for n in bundle['nodes']}
        for q in questions:
            for field in ('stem','answer'):
                if q[field]:self.assertEqual(sum(s['kind']=='image' for s in nodes[q[field]]['text']),1)
        self.assertNotIn('The original answer.',json.dumps([nodes[q['answer']] for q in questions if q['answer']]))

    def test_crops_are_exact_original_pixels_with_side_marks(self):
        bundle=self.bundle();crop=bundle['provenance']['lecture']['crops'][0]
        import io
        actual=Image.open(io.BytesIO(base64.b64decode(bundle['assets'][crop['asset']]['base64'])))
        with Image.open(self.source) as source:expected=source.crop(tuple(crop['pixel_rect']))
        self.assertEqual(actual.tobytes(),expected.tobytes());self.assertEqual(actual.width,1000)
        self.assertTrue(any(r>200 and g<80 and b<80 for r,g,b in actual.getdata()))

    def test_missing_source_and_cross_chapter_are_rejected(self):
        bad=copy.deepcopy(self.plan);bad['blocks'].pop()
        with self.assertRaisesRegex(ValueError,'Every original'):validate_plan(bad,self.e,'Mechanics',self.contract)
        bad=copy.deepcopy(self.plan);bad['blocks'][0]['first']=0
        with self.assertRaisesRegex(ValueError,'crosses a source chapter'):validate_plan(bad,self.e,'Mechanics',self.contract)

    def test_invented_source_is_rejected(self):
        bad=copy.deepcopy(self.plan);bad['blocks'][1]['questions'][0]['source']['year']='2099'
        with self.assertRaisesRegex(ValueError,'never inferred'):validate_plan(bad,self.e,'Mechanics',self.contract)

    def test_printed_star_difficulty_is_copied_even_when_model_omits_it(self):
        from lectures.contract import question_source
        e=copy.deepcopy(self.e);e['atoms'][2]['text']='[例 1 多选★★★] Find a quantity. Exam Alpha'
        q=copy.deepcopy(self.plan['blocks'][1]['questions'][0]);q['label']='[例 1 多选★★★]'
        source,_,_=question_source(q,'Mechanics',e['atoms'],self.contract)
        self.assertEqual(source['difficulty'],'★★★');self.assertEqual(source['name'],'Exam Alpha')
        q['source']['difficulty']='★★'
        self.assertEqual(question_source(q,'Mechanics',e['atoms'],self.contract)[0]['difficulty'],'★★★')

    def test_tampering_and_stale_source_are_rejected(self):
        bundle=self.prepared();bundle['nodes'][-1]['text'][0]['value']='Invented source';save(self.folder/'package.json',bundle)
        with self.assertRaisesRegex(ValueError,'differs'):validate(self.folder)
        self.prepared();self.source.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'Original source changed'):validate(self.folder)

    def test_user_feedback_is_required_for_the_next_material(self):
        bundle=self.bundle();e=bundle['provenance']['lecture']
        with self.assertRaisesRegex(ValueError,'discussed trial'):check(bundle,False,None)
        self.assertEqual(check(bundle,True,None),'trial')
        pending={'status':'awaiting_user_feedback','sourceSha256':'another'}
        with self.assertRaisesRegex(ValueError,'awaiting user feedback'):check(bundle,True,pending)
        accepted={'status':'accepted','implementation':e['implementation'],'sharedContract':e['sharedContract']}
        self.assertEqual(check(bundle,False,accepted),'accepted')
        accepted['implementation']='old'
        with self.assertRaisesRegex(ValueError,'discussed trial'):check(bundle,False,accepted)

    def test_detached_answers_and_paradigm_examples_keep_order(self):
        self.plan['blocks'][1]['kind']='paradigm'
        self.plan['blocks'][1]['questions'][0]['local']=[2]
        # A detached answer remains at its original position as well as in the
        # question's single answer field, so answer pairing cannot reorder prose.
        bundle=self.bundle();mapping=bundle['provenance']['atomToNode']
        self.assertNotEqual(mapping['a000002'],mapping['a000003'])
        self.assertTrue(any(n['text']==[{'kind':'text','value':'范式'}] for n in bundle['nodes']))

    def test_landscape_independent_canary_with_multicolumn_notes(self):
        image=Image.new('RGB',(1600,600),'white');draw=ImageDraw.Draw(image)
        draw.rectangle((15,170,300,240),outline='blue',width=5);draw.rectangle((1200,170,1580,240),outline='green',width=5)
        path=self.folder/'landscape.png';image.save(path);pages=OriginalPages(path,self.folder/'landscape-pages')
        atoms=[{'page':1,'bbox':[40,280,180,410]},{'page':1,'bbox':[760,280,980,410]}]
        crop=pages.regions(atoms,[0,1])[0]
        import io
        actual=Image.open(io.BytesIO(crop['data']))
        self.assertEqual(actual.width,1600);self.assertEqual(actual.tobytes(),image.crop(tuple(crop['pixel_rect'])).tobytes())
        pages.close()

    def test_merged_ocr_examples_reuse_original_region_without_invented_split(self):
        from lectures.plan import shared_original
        atoms=[{'text':'Example 3: task A. Example 4: task B.'}]
        left={'label':'Example 3','stem':[0]};right={'label':'Example 4','stem':[0]}
        self.assertTrue(shared_original(left,right,{0},atoms))
        self.assertFalse(shared_original(right,left,{0},atoms))
        self.assertFalse(shared_original({'label':'3(1)','stem':[0]},{'label':'3(2)','stem':[0]},{0},atoms))
        self.assertFalse(shared_original(left,{'label':'Example 5','stem':[0]},{0},atoms))

    def test_solution_tail_and_next_stem_share_one_original_ocr_rectangle(self):
        from lectures.plan import shared_original
        atoms=[{'text':'[例 1 ★] First original task.'},{'text':'Original solution tail. [例 2 多选★★] Next original task.'}]
        left={'label':'[例 1 ★]','stem':[0],'answer':[1]}
        right={'label':'[例 2 多选★★]','stem':[1],'answer':[]}
        self.assertTrue(shared_original(left,right,{1},atoms))
        self.assertFalse(shared_original(left,{**right,'label':'[例 1 ★]'}, {1},atoms))
        self.assertFalse(shared_original({**left,'answer':[]},right,{1},atoms))

    def test_cross_block_shared_stem_keeps_one_owner_and_all_original_images(self):
        e=copy.deepcopy(self.e);e['atoms'][3]['text']='Original answer tail. 2. Next question begins.'
        p=copy.deepcopy(self.plan);q=p['blocks'][2]['questions'][0]
        q['local']=[3,4];q['stem']=[3,4]
        normalized=normalize(p)
        self.assertEqual(normalized['blocks'][2]['questions'][0]['local'],[4])
        self.assertEqual(normalized['blocks'][2]['questions'][0]['stem'],[3,4])
        validate_plan(normalized,e,'Mechanics',self.contract)
        # The same shared pixel rectangle cannot justify an unrelated stem.
        bad=copy.deepcopy(normalized);old=bad['blocks'][1]['questions'][0]
        old['stem']=[2,3];old['answer']=[]
        with self.assertRaisesRegex(ValueError,'Borrowed stem'):validate_plan(bad,e,'Mechanics',self.contract)

    def test_valid_old_geometry_receipt_reuses_only_identical_source_and_policy(self):
        from lectures.plan import make_plan,PROMPT,REVISION
        class MustReuse:
            folder=self.folder/'semantic-cache'
            def call(self,*args):raise RuntimeError('fresh call needed')
        producer=MustReuse();producer.folder.mkdir()
        data={'title':'Mechanics','shared_source_fields':list(self.contract.SOURCE_FIELDS),'rows':[
            {'i':i,'page':a['page'],'bbox':a['bbox'],'kind':a['kind'],'text':a['text']} for i,a in enumerate(self.e['atoms'])],'chapter_context':[]}
        save(producer.folder/'lecture-structure-old.json',{'identity':{'instructions':PROMPT+REVISION,'data':data,'images':[]},'result':self.plan,'response':{'provider':'codex_exec','transport':{'completed_event':True}}})
        self.assertEqual(make_plan(self.e,self.folder,'Mechanics',self.contract,producer,[]),self.plan)
        changed=copy.deepcopy(self.e);changed['atoms'][1]['text']='Another real source'
        with self.assertRaisesRegex(RuntimeError,'fresh call'):make_plan(changed,self.folder,'Mechanics',self.contract,producer,[])

    def test_adjacent_commentary_merges_across_removed_brand_only(self):
        p={'chapters':[],'excluded':[{'indices':[2],'reason':'trademark'}],'blocks':[
            {'first':0,'last':1,'kind':'motivation','original':False,'questions':[]},
            {'first':3,'last':4,'kind':'motivation','original':True,'questions':[]},
            {'first':5,'last':5,'kind':'memory','original':True,'questions':[]},
            {'first':6,'last':6,'kind':'memory','original':True,'questions':[]}]}
        actual=normalize(p)
        self.assertEqual(len(actual['blocks']),3);self.assertEqual(actual['blocks'][0]['last'],4)
        self.assertTrue(actual['blocks'][0]['original'])
        self.assertEqual(p['blocks'][0]['last'],1)

    def test_cleanup_changes_only_verified_noise_pixels(self):
        import io,math
        box=[860,280,980,350]
        image=Image.open(self.source).convert('RGB');draw=ImageDraw.Draw(image);draw.rectangle((860,224,979,279),fill='purple');image.save(self.source)
        atoms=self.e['atoms']+[{'page':1,'bbox':box,'text':'Synthetic sponsor'}]
        ex={**self.e,'atoms':atoms};plan={'excluded':[{'indices':[5],'reason':'advertisement'}]}
        marks=masks(plan,ex);pages=OriginalPages(self.source,self.folder/'clean',marks)
        region=pages.regions(atoms,[2])[0];actual=Image.open(io.BytesIO(region['data']))
        original=image.crop(tuple(region['pixel_rect']));x0,y0,_,_=region['pixel_rect']
        for y in range(actual.height):
            for x in range(actual.width):
                if 860<=x+x0<980 and 224<=y+y0<280:self.assertEqual(actual.getpixel((x,y)),(255,255,255))
                else:self.assertEqual(actual.getpixel((x,y)),original.getpixel((x,y)))
        pages.close()
        ex['atoms'][-1]['bbox']=[70,300,300,330]
        with self.assertRaisesRegex(ValueError,'overlaps retained'):masks(plan,ex)

    def test_multi_material_stems_primary_and_both_original_answers_one_node(self):
        from lectures.collection import compose_collection
        self.prepared()
        other=LectureTests();other.setUp()
        try:
            with Image.open(other.source) as source:image=source.convert('RGB')
            ImageDraw.Draw(image).ellipse((850,350,880,380),fill='blue');image.save(other.source)
            other.e['source_sha256']=file_sha(other.source)
            save(other.base/'source.json',{'source':str(other.source),'source_sha256':file_sha(other.source)})
            save(other.base/'extraction.json',other.e);build(other.e,other.s,other.base,'Mechanics');other.prepared()
            sources=[{'id':'solutions','roles':['questions','answers'],'folder':str(self.folder)},
                     {'id':'notes','roles':['teaching','answers'],'folder':str(other.folder)}]
            local=load(other.folder/'package.json')['provenance']['lecture']['questions']
            pairs=[{'source':'notes','note':q['node'],'primary':q['node'],'evidence':'identical fixture question'} for q in local]
            bundle=compose_collection(self.folder,sources,pairs,'Combined',{'source_sha256':'a'*64})
            qs=bundle['provenance']['lecture']['questions'];nodes={n['id']:n for n in bundle['nodes']}
            self.assertEqual(len(qs),2);self.assertEqual(qs[0]['answerSources'],['solutions','notes'])
            self.assertEqual(sum(s['kind']=='image' for s in nodes[qs[0]['answer']]['text']),2)
            original=load(self.folder/'package.json');orig={n['id']:n for n in original['nodes']}
            self.assertEqual(nodes[qs[0]['stem']]['text'],orig[original['provenance']['lecture']['questions'][0]['stem']]['text'])
            self.assertIsNone(qs[1]['answer'])
            supplement=copy.deepcopy(pairs);supplement[1]['primary']=None
            combined=compose_collection(self.folder,sources,supplement,'Combined',{'source_sha256':'a'*64})
            self.assertEqual(len(combined['provenance']['lecture']['questions']),2)
            self.assertTrue(any(n['text']==[{'kind':'text','value':'范式'}] for n in combined['nodes']))
            self.assertTrue(any(n['id'].endswith('-original') and any(s['kind']=='image' for s in n['text']) for n in combined['nodes']))
            # A notes-only subchapter remains visible beneath the shared parent
            # rather than being confused with a globally numbered section.
            ob=load(other.folder/'package.json');doc=next(n for n in ob['nodes'] if n['document'])
            at=ob['nodes'].index(doc)+1;extra='notes-only-subchapter'
            ob['nodes'].insert(at,{'id':extra,'parentId':doc['id'],'document':True,'text':[{'kind':'text','value':'1. Worked details'}]})
            for n in ob['nodes']:
                if n['id']!=extra and n['parentId']==doc['id']:n['parentId']=extra
            save(other.folder/'package.json',ob)
            combined=compose_collection(self.folder,sources,pairs,'Combined',{'source_sha256':'a'*64})
            self.assertTrue(any(n['id']=='notes-'+extra and n['document'] for n in combined['nodes']))
            self.assertEqual(next(n for n in combined['nodes'] if n['id']==qs[0]['node'])['parentId'],'notes-'+extra)
            with self.assertRaisesRegex(ValueError,'Incomplete cross-source'):compose_collection(self.folder,sources,pairs[:1],'Combined',{'source_sha256':'a'*64})
        finally:other.tearDown()

    def test_repeated_background_cleanup_preserves_overlapping_original_ink(self):
        import io,pymupdf
        source=self.folder/'layers.pdf';background=Image.new('RGB',(500,500),'white')
        ImageDraw.Draw(background).rectangle((380,20,449,49),fill='blue')
        buffer=io.BytesIO();background.save(buffer,format='PNG')
        with pymupdf.open() as doc:
            first=doc.new_page(width=500,height=500);xref=first.insert_image(first.rect,stream=buffer.getvalue())
            second=doc.new_page(width=500,height=500);second.insert_image(second.rect,xref=xref)
            second.draw_line((375,30),(460,60),color=(1,0,0),width=4)
            second.draw_line((400,10),(420,80),color=(0,0,0),width=3)
            doc.save(source)
        atoms=[{'page':1,'bbox':[760,40,900,100]}, {'page':2,'bbox':[750,20,920,120]}, {'page':2,'bbox':[800,100,960,170]}]
        plan={'excluded':[{'indices':[0,1],'reason':'trademark'}]}
        marks=masks(plan,{'source':str(source),'atoms':atoms})
        self.assertIn('backgroundLayer',marks[1]);self.assertEqual(marks[1]['preserveAtoms'],[2])
        pages=OriginalPages(source,self.folder/'layer-pages',marks)
        cleaned=pages.page(2);region=pages.regions(atoms,[2])[0]
        self.assertLessEqual(region['bbox'][1],20)
        with pymupdf.open(source) as doc:
            before=doc[1].get_pixmap(matrix=pymupdf.Matrix(3,3),alpha=False)
            original=Image.frombytes('RGB',(before.width,before.height),before.samples)
        for color in [(255,0,0),(0,0,0)]:
            self.assertEqual(sum(p==color for p in cleaned.getdata()),sum(p==color for p in original.getdata()))
        self.assertFalse(any(b>200 and r<50 and g<50 for r,g,b in cleaned.getdata()))
        self.assertEqual(cleaned.crop((0,200,1500,1500)).tobytes(),original.crop((0,200,1500,1500)).tobytes())
        pages.close()

    def test_independent_pdf_inventory_catches_a_missing_multiple_choice_question(self):
        import pymupdf
        from lectures.collection import native_question_inventory
        path=self.folder/'inventory.pdf'
        with pymupdf.open() as doc:
            page=doc.new_page();page.insert_text((50,70),'[例1 ★] 简单题',fontname='china-s',fontsize=12)
            page.insert_text((50,170),'[例2 多选★★] 多选题',fontname='china-s',fontsize=12);doc.save(path)
        with self.assertRaisesRegex(ValueError,'missing from plan'):native_question_inventory(path,[{'number':'1','pages':[1]}])
        report=native_question_inventory(path,[{'number':'1','pages':[1]},{'number':'2','pages':[1]}])
        self.assertEqual(report['native_markers'],2)


if __name__=='__main__':unittest.main()
