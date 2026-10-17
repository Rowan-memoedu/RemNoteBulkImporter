import importlib.util, unittest, argparse, tempfile, zipfile, json
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

    def test_units_modules_and_topics_are_nested_documents_with_stable_cross_module_refs(self):
        c=self.c;c.args.course_id=999;c.args.title='Independent hierarchy fixture';c.course={'name':'Independent course'}
        c.graph={str(i):{'id':i,'name':f'Topic {i}','unit':{'number':u,'name':f'Unit {u}'},'module':{'number':m,'name':f'Module {m}'},'prerequisites':pre}
                 for i,u,m,pre in [(31,2,1,[]),(32,2,3,[31]),(41,5,1,[32])]}
        c.order=list(c.graph);c.lessons={k:{'steps':[]} for k in c.graph};c.source_hashes={};c.progress_name='fixture'
        c.convert();nodes={n['id']:n for n in c.nodes}
        self.assertEqual(nodes['t32']['parentId'],'u2.m3');self.assertEqual(nodes['u2.m3']['parentId'],'u2')
        self.assertIsNone(nodes['u5']['parentId']);self.assertEqual(nodes['t41']['parentId'],'u5.m1')
        self.assertTrue(all(nodes[k]['document'] for k in ['u2','u5','u2.m1','u2.m3','u5.m1','t31','t32','t41']))
        self.assertFalse(any(k.endswith('.meta') for k in nodes))
        self.assertEqual(nodes['t41.pre32']['text'],[{'kind':'ref','targetId':'t32'}])

    def test_empty_fields_and_lessons_get_visible_placeholders(self):
        self.c.add_field('field','parent',None,'field')
        self.c.labeled_field('example','parent','解答','','example')
        self.assertEqual([g['kind'] for g in self.c.gaps],['missing_content']*2)
        self.assertIn('源资料未提供',self.c.nodes[0]['text'][0]['value'])
        self.assertIn('源资料未提供',self.c.nodes[1]['text'][1]['value'])

    def test_external_source_must_be_explicit_when_catalogs_disagree(self):
        def topic(tid,cid,pre):return {'id':tid,'name':str(tid),'course':{'id':cid},'prerequisites':pre}
        path=Path(self.tmp.name)/'graphs.zip'
        with zipfile.ZipFile(path,'w') as z:
            for cid,ts in [(999,{'30':topic(30,999,[10])}),(111,{'10':topic(10,111,[5]),'5':topic(5,111,[])}),(222,{'10':topic(10,222,[])})]:
                z.writestr(f'course-knowledge-graph/course-{cid}.json',json.dumps({'topics':ts}))
        with self.assertRaisesRegex(ValueError,'explicit'):ma.course_graph(path,999)
        with self.assertRaisesRegex(ValueError,'Conflicting'):ma.course_graph(path,999,True)
        graph,main=ma.course_graph(path,999,True,111)
        self.assertEqual(main,{'30'});self.assertEqual(set(graph),{'30','10','5'})
        self.assertLess(ma.dependency_order(graph)['5'],ma.dependency_order(graph)['10'])
        self.assertLess(ma.dependency_order(graph)['10'],ma.dependency_order(graph)['30'])

    def test_external_hierarchy_is_namespaced_and_numeric_unit_policy_preserves_number(self):
        t={'course':{'id':111},'unit':{'number':3,'name':'Source label'},'module':{'number':8}}
        self.assertEqual(ma.hierarchy_ids(t,999),('external.c111.u3','external.c111.u3.m8'))
        self.assertEqual(ma.unit_label(t,argparse.Namespace(unit_labels='numeric',course_id=111)),'单元 3')
        self.assertEqual(t['unit']['name'],'Source label')

    def test_missing_snapshot_requires_opt_in_and_does_not_fabricate_progress(self):
        root=Path(self.tmp.name);graph=root/'g.zip';progress=root/'p.zip';topics=root/'t.zip'
        t={'id':17,'name':'Fixture','prerequisites':[],'course':{'id':999,'name':'Source'},'unit':{'number':1,'name':'U'},'module':{'number':1,'name':'M'}}
        with zipfile.ZipFile(graph,'w') as z:z.writestr('course-knowledge-graph/course-999.json',json.dumps({'topics':{'17':t}}))
        with zipfile.ZipFile(progress,'w'):pass
        with zipfile.ZipFile(topics,'w') as z:z.writestr('topic-json/topic-17.json',json.dumps({'lesson':{'topic':{'id':17},'steps':[]}}))
        self.c.args=argparse.Namespace(output=self.tmp.name,graph=str(graph),progress=str(progress),topics=str(topics),course_id=999,title='Fixture')
        with self.assertRaisesRegex(ValueError,'explicit'):self.c.load()
        self.c.args.allow_missing_progress=True;self.c.load();self.c.convert()
        self.assertIsNone(self.c.progress);self.assertIsNone(self.c.progress_name)
        self.assertEqual(self.c.plan['provenance']['topicOrderSource'],'source-groups-and-prerequisite-DAG')
        self.assertEqual(self.c.gaps,[{'kind':'missing_lesson','where':'t17'}])

    def test_dependency_cycle_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'cycle'):ma.dependency_order({'10':{'prerequisites':[11]},'11':{'prerequisites':[10]}})

    def test_field_local_macro_definitions_expand_across_separate_expressions(self):
        source=r'[math]\newcommand{\myop}{\mathop{\rm custom}\nolimits}[/math] Value [math]\myop{x}+2[/math].'
        blocks=self.c.field(source,'independent-macro')
        formula=[s for b in blocks for s in b if s['kind']=='latex']
        self.assertEqual(len(formula),1)
        self.assertEqual(formula[0]['value'],r'\mathop{\rm custom}\nolimits{x}+2')
        self.assertNotIn('newcommand',str(blocks))

    def test_field_local_macros_do_not_modify_drawing_source_or_other_fields(self):
        drawing=r'\documentclass{standalone}\newcommand{\same}{picture}\begin{document}X\end{document}'
        self.c.field(drawing+r'[math]\newcommand{\same}{lesson}\same[/math]','different-context')
        self.assertEqual(next(iter(self.c.drawings.values()))['source'],drawing)
        blocks=self.c.field(r'[math]\same[/math]','another-field')
        self.assertEqual(blocks[0][0]['value'],r'\same')

    def test_math_macro_cycles_reject_instead_of_silently_changing_payload(self):
        with self.assertRaisesRegex(ValueError,'Recursive'):ma.expand_source_macros(r'\a', {r'\a':r'\b',r'\b':r'\a'})

    def test_code_is_protected_before_math_or_paragraph_parsing(self):
        original='if x &lt; 3:\n    print("$literal$")\n\n    # still indented\n    x += 1'
        blocks=self.c.field('<p>Before</p><pre><code>'+original+'</code></pre><p>After</p>','code-fixture')
        code=[s for b in blocks for s in b if s['kind']=='code']
        self.assertEqual(code,[{'kind':'code','value':original.replace('&lt;','<')}])
        self.assertEqual(self.c.stats['formulas'],0);self.assertFalse(self.c.gaps)

    def test_rendered_field_selects_one_copy_of_code_and_keeps_math(self):
        source='<p><code>mod</code> [math]x[/math]</p>'
        rendered='<body><p><code>mod</code> <svg><title>x</title></svg></p></body>'
        blocks=self.c.field(source,'rendered-code',rendered)
        self.assertEqual([s['value'] for b in blocks for s in b if s['kind']=='code'],['mod'])
        self.assertFalse(self.c.gaps)

    def test_legacy_body_prefers_structured_response_and_never_parses_embedded_answers(self):
        step={'id':819,'number':1,'question':{'text':'Compute','body':'legacy answer: 99',
            'freeResponse':{'segments':[{'text':'$x=$'},{'textbox':{'type':'number','answer':'17'}}]}}}
        self.c.question('47',step,'t47')
        nodes={n['id']:n for n in self.c.nodes}
        self.assertEqual(nodes['t47.s819.fr.answer0.text.p0']['text'][0]['value'],'17')
        self.assertNotIn('t47.s819.body-source.raw',nodes)
        step['id']=820;step['question'].pop('freeResponse');self.c.question('47',step,'t47')
        nodes={n['id']:n for n in self.c.nodes}
        self.assertEqual(nodes['t47.s820.body-source.raw']['text'],[{'kind':'code','value':'legacy answer: 99'}])

if __name__=='__main__':unittest.main()
