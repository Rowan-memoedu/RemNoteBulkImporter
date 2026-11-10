"""Source-neutral authored-outline regressions and independent physics canary."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'consumers'))
from materials.common import load,save
from materials.source_outline import parse,convert,prepare,validate
from materials.inputs import source_kind


class OutlineTests(unittest.TestCase):
    def setUp(self):
        root=Path('D:/Artifacts/RemNoteBulkImporter/outline-tests');root.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=root);self.folder=Path(self.temp.name)
        self.source=self.folder/'source.md';self.output=self.folder/'output';self.output.mkdir()

    def tearDown(self):self.temp.cleanup()

    def test_multiline_equation_and_prose_stay_in_one_parent(self):
        text='# Test\n\n- Method\n  - Given $x$,\n\n    $$\n    \\begin{aligned}\n    y&=x+1\\\\\n    &=2.\n    \\end{aligned}\n    $$\n\n    Therefore $y=2$.\n  - Next\n- Other\n'
        tree=parse(text,'fallback')
        self.assertEqual([n['parentId'] for n in tree['nodes']],[None,'a000000','a000000',None])
        self.assertEqual(len(tree['nodes']),4)
        self.source.write_text(text,encoding='utf8')
        _,bundle,_=convert(self.source,self.output)
        runs=bundle['nodes'][1]['text']
        self.assertEqual([(s['value'],s['block']) for s in runs if s['kind']=='latex'],[
            ('x',False),('\n\\begin{aligned}\ny&=x+1\\\\\n&=2.\n\\end{aligned}\n',True),('y=2',False)])
        self.assertTrue(any('\n\n' in s.get('value','') for s in runs))
        self.assertEqual(bundle['title'],'Test')
        self.assertFalse(any(n['document'] for n in bundle['nodes']))

    def test_fences_protect_fake_headings_lists_and_math(self):
        text='# Code\n- Snippet\n\n  ```text\n  # literal\n  - literal\n  $$open literal\n  ```\n- End\n'
        self.source.write_text(text,encoding='utf8')
        tree,bundle,_=convert(self.source,self.output)
        self.assertEqual(len(tree['nodes']),2)
        self.assertEqual([s['value'] for s in bundle['nodes'][0]['text'] if s['kind']=='code'],['# literal\n- literal\n$$open literal\n'])

    def test_heading_order_and_explicit_ordered_labels(self):
        tree=parse('# Book\n## Part A\n3. Item\n   - Nested\n4. Next\n## Part B\n- End\n','fallback')
        self.assertEqual([n['parentId'] for n in tree['nodes']],[None,'a000000','a000001','a000000',None,'a000004'])
        self.assertEqual(tree['nodes'][1]['text'],'3. Item')
        self.assertEqual(tree['nodes'][3]['text'],'4. Next')

    def test_ambiguous_or_incomplete_source_stops(self):
        for text in ('- Parent\n  - Child\n\n  Later parent prose',
                     '- Formula\n\n  $$\n  x=1',
                     '# One\n- A\n# Two\n- B',
                     '- Parent\n - Bad indent'):
            with self.subTest(text=text),self.assertRaises(ValueError):parse(text,'fallback')

    def test_physics_canary_images_bold_math_and_tampering(self):
        from PIL import Image
        Image.new('RGB',(8,7),'blue').save(self.folder/'figure.png')
        self.source.write_text('# Motion\n\n- Constant acceleration\n  - **Velocity $v$** obeys\n\n    $$\n    v=v_0+at\n    $$\n\n    Keep $t\\geq0$.\n  - ![Diagram](figure.png)\n- Energy\n  - $E=\\frac12mv^2$.\n',encoding='utf8')
        report=prepare(self.source,self.output)
        self.assertEqual(report['status'],'VALIDATED')
        self.assertEqual(report['source_atoms'],5)
        self.assertEqual(report['native_formulas'],4)
        self.assertEqual(report['info']['assets'],1)
        original=load(self.output/'package.json')
        for mutation in ('parent','text','order','formula'):
            candidate=copy.deepcopy(original)
            if mutation=='parent':candidate['nodes'][1]['parentId']=None
            elif mutation=='text':candidate['nodes'][0]['text'][0]['value']='Changed'
            elif mutation=='order':candidate['nodes'][1:3]=reversed(candidate['nodes'][1:3])
            else:next(s for s in candidate['nodes'][1]['text'] if s['kind']=='latex')['block']=True
            save(self.output/'package.json',candidate)
            with self.subTest(mutation=mutation),self.assertRaisesRegex(ValueError,'differs'):validate(self.output)
        save(self.output/'package.json',original)
        self.assertEqual(validate(self.output)['status'],'VALIDATED')

    def test_layout_rejects_preview_and_missing_assets(self):
        self.assertEqual(source_kind(Path('file.md'),'outline'),'source-outline')
        with self.assertRaises(ValueError):source_kind(Path('preview.html'),'outline')
        self.source.write_text('- ![Missing](missing.png)',encoding='utf8')
        with self.assertRaises(FileNotFoundError):convert(self.source,self.output)

    def test_mermaid_renders_to_verified_image_and_tampering_stops(self):
        self.source.write_text('# Water cycle\n- Process\n\n  ```mermaid\n  flowchart LR\n    A[Evaporation] --> B[Condensation]\n    B --> C[Rain]\n  ```\n',encoding='utf8')
        tree,bundle,_=convert(self.source,self.output)
        self.assertEqual(len(tree['nodes']),1)
        self.assertEqual(sum(s['kind']=='image' for s in bundle['nodes'][0]['text']),1)
        self.assertFalse(any(s['kind']=='code' for s in bundle['nodes'][0]['text']))
        self.assertEqual(convert(self.source,self.output)[1],bundle)
        image=next((self.output/'diagrams').glob('*.png'));image.write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError,'rendering changed'):convert(self.source,self.output)


if __name__=='__main__':unittest.main()
