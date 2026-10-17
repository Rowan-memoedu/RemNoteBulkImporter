import importlib.util, unittest, argparse, tempfile
from pathlib import Path
spec=importlib.util.spec_from_file_location('ma',Path(__file__).parents[1]/'consumers'/'math_academy.py')
ma=importlib.util.module_from_spec(spec);spec.loader.exec_module(ma)

class ConversionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir='D:/Artifacts/RemNoteBulkImporter')
        self.c=ma.Converter(argparse.Namespace(output=self.tmp.name))
    def tearDown(self):self.tmp.cleanup()
    def test_formula_stays_one_native_segment_and_keeps_matrix_rows(self):
        blocks=self.c.field('Before\n\n\\[\\begin{bmatrix}1&2\\\\3&4\\end{bmatrix}\\]\n\nAfter','fixture')
        self.assertEqual(len(blocks),3);self.assertEqual(blocks[1][0]['kind'],'latex')
        self.assertIn('1&2\\\\3&4',blocks[1][0]['value']);self.assertEqual(blocks[2][0]['value'],'After')
    def test_html_formatting_and_symbol_text_are_preserved(self):
        blocks=self.c.field('<p><strong>Important</strong>: $a &lt; b$</p><p>Next &amp; final.</p>','fixture')
        self.assertEqual(blocks[0][0]['value'],'**Important**: ')
        self.assertEqual(blocks[0][1]['value'],'a < b');self.assertEqual(blocks[1][0]['value'],'Next & final.')
    def test_graphic_uses_exact_file_id_and_source_mismatch_is_rejected(self):
        self.c.graphic_index={'q-1-a-5':'SOURCE-FIVE','q-1-a-1':'SOURCE-ONE'}
        self.c.field('<img src="/graphics/q-1-a-5">','choice1')
        self.assertEqual(next(iter(self.c.drawings.values()))['source'],'SOURCE-FIVE')
        with self.assertRaises(ValueError):self.c.field('plain','bad','<img src="/graphics/missing">')
    def test_unknown_graphic_is_explicit_gap_not_wrong_image(self):
        b=self.c.field('<img src="/graphics/absent">','fixture')
        self.assertEqual(self.c.gaps[0]['kind'],'missing_graphic');self.assertEqual(b[0][0]['value'],'【原题配图缺失】')
    def test_align_environment_and_inline_math_are_distinct(self):
        b=self.c.field('Use [math]x[/math].\n\n\\begin{align*}a&=b\\\\c&=d\\end{align*}','fixture')
        self.assertEqual(b[0][1]['value'],'x');self.assertFalse(b[0][1]['block'])
        self.assertTrue(b[1][0]['block']);self.assertIn('\\begin{align*}',b[1][0]['value'])
    def test_tex_compatibility_does_not_change_math_content_and_rejects_io(self):
        self.assertEqual(ma.tex_compatible('before [math]x^2[/math] after'),'before $x^2$ after')
        with self.assertRaises(ValueError):ma.tex_compatible('\\input{C:/private.txt}')
    def test_malformed_repeated_math_opening_is_repaired_without_changing_payload(self):
        b=self.c.field('The rate is [math]0.20[math].','different-fixture')
        self.assertEqual(b[0][1]['value'],'0.20');self.assertEqual(b[0][2]['value'],'.')
    def test_legacy_vector_alias_keeps_endpoints_and_provides_arrow(self):
        raw=r'\begin{document}\tkzDrawVector[color=red](A,B)\end{document}'
        normalized=ma.tex_compatible(raw)
        self.assertIn(r'\tkzDrawSegment[->,#1]',normalized)
        self.assertIn(r'\tkzDrawVector[color=red](A,B)',normalized)
    def test_memory_fallback_splits_panels_without_changing_their_drawing_commands(self):
        body=r'\begin{tikzpicture}\draw(0,0)--(1,2);\end{tikzpicture}'
        raw=r'\documentclass[border=1mm]{standalone}\begin{document}'+body+body+r'\end{document}'
        result=ma.split_standalone(raw)
        self.assertIn('multi=tikzpicture',result);self.assertEqual(result.count(body),2)
    def test_mathjax_compatibility_preserves_payload_and_nested_math_subscripts(self):
        raw=r'\bbox[2pt,Gainsboro]{\mathbf{v}_2}+\eqalign{a&=b\\c&=d}'
        result=ma.latex_compatible(raw)
        self.assertIn(r'\colorbox{Gainsboro}{$\mathbf{v}_2$}',result)
        self.assertIn(r'\begin{aligned}a&=b\\c&=d\end{aligned}',result)
        self.assertIn(r'\mathbf{a}_1',ma.latex_compatible(r'\textrm{{$\mathbf{a}_1$}}'))
    def test_unpublished_comment_math_is_preserved_only_in_raw_source_not_lesson(self):
        b=self.c.field('Visible [math]x[/math]. <!-- [math]hidden[/math] -->','fixture')
        self.assertEqual(sum(s['kind']=='latex' for block in b for s in block),1)
        self.assertFalse(any(g['kind']=='token_loss' for g in self.c.gaps))
    def test_nested_dollars_in_text_group_do_not_split_or_truncate_expression(self):
        b=self.c.field(r'Basis $B=\textrm{{$\mathbf{u}_1,\mathbf{u}_2$}}$ is fixed.','independent-nesting')
        math=[s for block in b for s in block if s['kind']=='latex']
        self.assertEqual(len(math),1);self.assertEqual(math[0]['value'],r'B=\textrm{{$\mathbf{u}_1,\mathbf{u}_2$}}')

if __name__=='__main__':unittest.main()
