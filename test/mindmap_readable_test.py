"""Independent connected biology canary and readable-map failure regressions."""
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pymupdf
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'consumers'))
from materials.common import load,save,source_run
from materials.mindmap import page_graph
from materials.mindmap_readable import extract_readable,audit_readable,ocr_rows,isolated_image,build_structure
from materials.render import build
from materials.validate import validate


def canary(path):
    doc=pymupdf.open()
    for detailed in (False,True):
        p=doc.new_page(width=700,height=300)
        p.draw_rect((30,125,130,165),color=(0,0,0),fill=(.2,.7,.4),width=2)
        p.insert_text((45,150),'Biology',fontsize=11)
        p.draw_bezier((130,145),(150,145),(150,80),(170,80),width=2)
        p.draw_line((170,80),(280,80),width=2);p.insert_text((175,75),'Cells',fontsize=10)
        if detailed:
            # Child shares its parent's baseline and junction with another child.
            p.draw_line((280,80),(450,80),width=2);p.insert_text((300,75),'Membranes',fontsize=10)
            p.draw_bezier((280,80),(295,80),(295,160),(310,160),width=2)
            p.draw_line((310,160),(460,160),width=2);p.insert_text((315,155),'Nucleus',fontsize=10)
    doc.save(path);doc.close()


class NoProducer:
    def __init__(self,*args):pass
    def call(self,*args):raise AssertionError('Canary has no visual ambiguity')


class ReadableTests(unittest.TestCase):
    def setUp(self):
        root=Path('D:/Artifacts/RemNoteBulkImporter/material-tests');root.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=root);self.folder=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()

    def test_cross_page_single_tree_and_collinear_branching(self):
        source=self.folder/'biology.pdf';canary(source);out=self.folder/'run';out.mkdir();source_run(source,out)
        with patch('materials.mindmap_readable.Producer',NoProducer):e,s=extract_readable(source,out)
        tree=load(out/'readable-tree.json');self.assertEqual(len(tree['chapters']),1)
        children=tree['chapters'][0]['children']
        self.assertEqual([x['parts'][0]['text'] for x in children],['Membranes','Nucleus'])
        bundle=build(e,s,out,'Biology')
        self.assertEqual(sum(n['document'] for n in bundle['nodes']),1)
        self.assertEqual(validate(out)['status'],'VALIDATED')
        self.assertEqual(audit_readable(source,out)['whole_page_images'],0)
        changed=load(out/'structure.json');changed['groups']=[{'parent':1,'through':2}];save(out/'structure.json',changed)
        with self.assertRaisesRegex(ValueError,'source topology'):audit_readable(source,out)

    def test_ocr_columns_join_and_parallel_formula_rows_survive(self):
        rows=ocr_rows([{'type':'text','text':'Area','bbox':[0,0,40,20]},
                       {'type':'equation','latex':'$$r^2$$','bbox':[50,0,90,20]},
                       {'type':'equation','latex':'$$2r$$','bbox':[50,30,90,50]}])
        self.assertEqual([x['text'] for x in rows],['Area $r^2$','$2r$'])

    def test_soft_mask_is_flattened_onto_white_without_page_neighbors(self):
        png=io.BytesIO();im=Image.new('RGBA',(10,10),(0,0,0,0));im.putpixel((5,5),(0,0,0,255));im.save(png,format='PNG')
        with pymupdf.open() as doc:
            p=doc.new_page();p.insert_image((0,0,10,10),stream=png.getvalue());p.insert_text((0,15),'Neighbor')
            block=next(b for b in p.get_text('dict')['blocks'] if b['type']==1)
            result=Image.open(io.BytesIO(isolated_image(block)))
        self.assertEqual(result.mode,'RGB');self.assertEqual(result.size,(40,40))
        self.assertEqual(result.getpixel((0,0)),(255,255,255));self.assertLess(sum(result.getpixel((22,22))),100)

    def test_formula_glyph_is_inserted_into_actual_text_gap(self):
        parts=[{'source':'t','kind':'text','text':'For  >0','bbox':[0,0,80,10],
                'lines':[{'bbox':[0,0,80,10],'chars':[{'c':c,'bbox':[i*10,0,i*10+9,10]} for i,c in enumerate('For  >0')]}]},
               {'source':'i','kind':'image','visual_id':'v','bbox':[40,0,49,10]}]
        tree={'chapters':[{'key':'c','title':'Definition','sources':[],'children':[{'parts':parts,'children':[]}]}],'source_pages':1,'source_parts':2}
        source=self.folder/'source';source.write_text('fixture')
        e,s=build_structure(source,self.folder,{'visuals':[{'id':'v'}]},tree,{'v':'text_math'},{'v':[{'kind':'text','text':r'$\epsilon$'}]})
        self.assertIn(r'For $\epsilon$',e['atoms'][1]['text'])
        self.assertEqual(set(e['atoms'][1]['contributors']),{'t','i'})


if __name__=='__main__':unittest.main()
