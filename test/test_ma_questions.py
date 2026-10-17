import argparse, importlib.util, tempfile, unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location('ma_questions',Path(__file__).parents[1]/'consumers'/'math_academy.py')
ma=importlib.util.module_from_spec(spec);spec.loader.exec_module(ma)

class QuestionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir='D:/Artifacts/RemNoteBulkImporter')
        self.c=ma.Converter(argparse.Namespace(output=self.tmp.name))
    def tearDown(self):self.tmp.cleanup()
    def run_question(self,q):
        self.c.question('991',{'id':473,'number':4,'question':q},'t991')
        return {n['id']:n for n in self.c.nodes}
    def values(self,nodes):return '\n'.join(s.get('value','') for n in nodes.values() for s in n['text'])
    def test_independent_free_response_keeps_prose_each_input_and_source_answers(self):
        nodes=self.run_question({'text':'Compute the following values.','format':'FR','freeAnswerChoice':'RAW_DUPLICATE',
            'freeResponse':{'segments':[{'newline':True},{'text':'$a+b=$'},
                {'textbox':{'type':'number','answer':'\\dfrac{5}{7}'}},{'text':' and $c=$'},
                {'textbox':{'type':'number','answer':'0'}},{'text':' and explain: '},
                {'textbox':{'type':'text','answer':'a supplied reason'}}]}})
        text=self.values(nodes)
        self.assertIn('a+b=',text);self.assertIn('[填空 1]',text);self.assertIn('[填空 3]',text)
        self.assertNotIn('RAW_DUPLICATE',text)
        self.assertEqual(nodes['t991.s473.fr.answer0.text.p0']['text'],[{'kind':'latex','value':r'\dfrac{5}{7}','block':False}])
        self.assertEqual(nodes['t991.s473.fr.answer1.text.p0']['text'][0]['value'],'0')
        self.assertIn('a supplied reason',text)
        self.assertIn('来源中附带的解答',nodes['t991.s473.fr.answer2']['text'][0]['value'])
    def test_missing_main_text_does_not_drop_available_body_or_invent_answer(self):
        nodes=self.run_question({'text':'','body':{'segments':[{'text':'Available prompt $x=$'},
            {'textbox':{'type':'number'}}]}})
        self.assertIn('Available prompt',self.values(nodes))
        self.assertTrue(any(g['kind']=='missing_question' for g in self.c.gaps))
        self.assertFalse(any('.fr.answer' in k for k in nodes))
    def test_partial_multisection_source_preserves_every_option_once(self):
        a={'index':0,'id':123,'sectionIndex':0,'options':['first','$z$'],'context':'text','answers':[]}
        b={'index':1,'id':124,'sectionIndex':1,'options':['p^2','q^2'],'context':'mathJax','answers':[]}
        nodes=self.run_question({'format':'DS','text':'Choose entries.','body':{'segments':[
            {'mathJax':r'\[F='},{'select':a},{'mathJax':r'\]'}]},'selects':[a,b,{'id':None,'answers':[]}],
            'sections':[{'complete':False},{'complete':True}]})
        self.assertEqual(sum(k.endswith('.o0.text.p0') for k in nodes),2)
        self.assertIn('t991.s473.select1.o1.text.p0',nodes)
        self.assertEqual(nodes['t991.s473.select1']['parentId'],'t991.s473.section1')
        self.assertEqual(nodes['t991.s473.select1.o0.text.p0']['text'][0]['kind'],'latex')
        self.assertIn(r'\boxed{\text{选择 1}}',nodes['t991.s473.body.p0']['text'][0]['value'])
        self.assertNotIn('complete',self.values(nodes));self.assertNotIn('t991.s473.section0.missing',nodes)
        self.assertEqual([g['kind'] for g in self.c.gaps],['missing_question_section'])
    def test_selection_dedup_uses_source_index_when_only_top_level_has_id(self):
        a={'index':2,'sectionIndex':0,'options':['yes','no']}
        nodes=self.run_question({'text':'Prompt','body':{'segments':[{'select':a}]},'selects':[{**a,'id':792}]})
        self.assertEqual(sum(k.endswith('.o0.text.p0') for k in nodes),1)
        self.assertIn('[选择 3]',self.values(nodes));self.assertNotIn(r'\boxed',self.values(nodes))
    def test_plain_mc_fields_and_existing_source_ids_stay_unchanged(self):
        nodes=self.run_question({'text':'Pick $t$.','choice1':'$u$','choice2':'$v$','answer':None})
        self.assertIn('t991.s473.choice1',nodes);self.assertIn('t991.s473.choice2',nodes)
        self.assertFalse(any('.fr' in k for k in nodes))
    def test_unknown_segment_is_recorded_without_losing_other_source(self):
        nodes=self.run_question({'text':'Prompt','body':{'segments':[{'text':'Keep me'},{'opaque':{'data':'x'}}]}})
        self.assertIn('Keep me',self.values(nodes));self.assertEqual(self.c.gaps[0]['kind'],'unknown_body_segment')
    def test_html_inline_code_and_separator_keep_text_without_unknown_tags(self):
        parser=ma.ToMarkdown();parser.feed('<p>Use <code class="language-python">mod</code>.</p><hr/><p>Then <code>a`b</code>.</p>')
        result=''.join(parser.out)
        self.assertIn('Use `mod`.',result);self.assertIn('Then ``a`b``.',result)
        self.assertIn('\n\n',result);self.assertEqual(parser.unknown,set())
    def test_html_pre_keeps_python_code_exactly_including_blank_lines_and_indentation(self):
        code='def compute(n):\n    value = n & 7\n\n    if value < 3:\n        return "```"\n\n    return value\n'
        parser=ma.ToMarkdown();parser.feed('<pre><code class="language-python">'+code.replace('&','&amp;').replace('<','&lt;')+'</code></pre>')
        block=parser.code_blocks[0]
        self.assertEqual(block,{'token':'RBICODEBLOCK00000001END','value':code,'language':'python'})
        self.assertIn(block['token'],''.join(parser.out));self.assertEqual(parser.unknown,set())
    def test_html_pre_without_nested_code_keeps_large_numeric_lines(self):
        code='98765432109876543210\n12345678901234567890\n'
        parser=ma.ToMarkdown();parser.feed('<pre>'+code+'</pre>')
        self.assertEqual(parser.code_blocks,[{'token':'RBICODEBLOCK00000001END','value':code,'language':''}])

if __name__=='__main__':unittest.main()
