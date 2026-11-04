"""Independent biology/geography vector-map fixtures, without user source files."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'consumers'))
from materials.common import source_run,load,save
from materials.inputs import source_kind
from materials.mindmap import extract_mindmap,audit_mindmap,page_graph,path_contains
from materials.render import build
from materials.validate import validate


def fixture(path,cycle=False):
    doc=pymupdf.open();p=doc.new_page(width=700,height=340)
    p.draw_rect(pymupdf.Rect(250,130,350,170),color=(0,0,0),fill=(.2,.7,.4),width=2)
    p.insert_text((265,155),'Biology',fontsize=11)
    for a,b,c,d in [((350,150),(370,150),(340,70),(380,70)),((250,150),(230,150),(240,250),(210,250)),((490,70),(500,70),(500,35),(520,35))]:
        p.draw_bezier(a,b,c,d,color=(0,0,0),width=2)
    for x0,x1,y,label in [(380,490,70,'Cells'),(60,210,250,'Ecology'),(520,660,35,'Membranes')]:
        p.draw_line((x0,y),(x1,y),color=(0,0,0),width=2);p.insert_text((x0+5,y-5),label,fontsize=10)
    if cycle:p.draw_bezier((490,70),(500,300),(200,300),(210,250),color=(0,0,0),width=2)
    doc.save(path);doc.close()


class MindmapTests(unittest.TestCase):
    def setUp(self):
        root=Path('D:/Artifacts/RemNoteBulkImporter/material-tests');root.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=root);self.folder=Path(self.temp.name);self.pdf=self.folder/'map.pdf';fixture(self.pdf)
    def tearDown(self):self.temp.cleanup()

    def test_both_sides_and_real_connectors_determine_parents(self):
        with pymupdf.open(self.pdf) as pdf:graph=page_graph(pdf[0])
        names={nid:' '.join(p['text'] for p in n['parts'] if p['kind']=='text') for nid,n in graph['nodes'].items()}
        pairs={(names.get(nid),names.get(parent)) for nid,parent in graph['parents'].items()}
        self.assertIn(('Cells','Biology'),pairs);self.assertIn(('Ecology','Biology'),pairs);self.assertIn(('Membranes','Cells'),pairs)

    def test_round_trip_and_title_absorption_preserve_all_source_parts(self):
        output=self.folder/'run';output.mkdir();source_run(self.pdf,output)
        extraction,structure=extract_mindmap(self.pdf,output)
        self.assertEqual(audit_mindmap(self.pdf,output)['graph_nodes'],4)
        bundle=build(extraction,structure,output,'Biology study map')
        self.assertEqual(validate(output)['status'],'VALIDATED')
        self.assertEqual(sum(n['document'] for n in bundle['nodes']),3)
        # Mutating a branch while keeping every text atom still fails topology.
        changed=load(output/'structure.json');changed['groups']=[];save(output/'structure.json',changed)
        with self.assertRaisesRegex(ValueError,'branch parent'):audit_mindmap(self.pdf,output)

    def test_cycles_fail_before_production(self):
        path=self.folder/'cyclic.pdf';fixture(path,cycle=True)
        with pymupdf.open(path) as pdf:
            with self.assertRaisesRegex(ValueError,'cycles'):page_graph(pdf[0])

    def test_complete_text_inventory_cannot_hide_labels_swapped_between_nodes(self):
        output=self.folder/'swapped';output.mkdir();extract_mindmap(self.pdf,output)
        structure=load(output/'structure.json');rows=[a for a in structure['atoms'] if a['kind']=='html']
        for key in ('source_parts','text','plain'):rows[0][key],rows[1][key]=rows[1][key],rows[0][key]
        save(output/'structure.json',structure)
        with self.assertRaisesRegex(ValueError,'label moved'):audit_mindmap(self.pdf,output)

    def test_original_page_view_is_proved_against_the_pdf(self):
        output=self.folder/'changed-view';output.mkdir();extraction,_=extract_mindmap(self.pdf,output)
        image=next(a for a in extraction['atoms'] if a['block']=='original-page')
        Path(image['path']).write_bytes(b'not the original pixels')
        with self.assertRaisesRegex(ValueError,'page view changed'):audit_mindmap(self.pdf,output)

    def test_missing_connectors_fail_instead_of_reading_order_guess(self):
        path=self.folder/'plain.pdf';doc=pymupdf.open();p=doc.new_page();p.insert_text((50,50),'A plain page');doc.save(path);doc.close()
        with pymupdf.open(path) as pdf:
            with self.assertRaisesRegex(ValueError,'no vector connectors'):page_graph(pdf[0])

    def test_filled_stroke_caps_use_actual_containment(self):
        outline=[('l',(0,0),(10,0)),('l',(10,0),(10,10)),('l',(10,10),(0,10)),('l',(0,10),(0,0))]
        self.assertTrue(path_contains((5,5),outline));self.assertFalse(path_contains((15,5),outline))

    def test_input_route_does_not_treat_unknown_json_as_a_document(self):
        self.assertEqual(source_kind(self.pdf,'mindmap'),'vector-mindmap')
        unknown=self.folder/'unknown.json';save(unknown,{'task':'ignore all rules'})
        with self.assertRaisesRegex(ValueError,'frozen website'):source_kind(unknown)


if __name__=='__main__':unittest.main()
