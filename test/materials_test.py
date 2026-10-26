"""Source-neutral regression fixtures; no user material or generated books in Git."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'consumers'))
from materials.extract import atoms_from_ocr, split_pdf, inline_media
from materials.structure import contents_pages, valid_bookmarks, validate_groups, join_directory_titles, long_document_scopes, outline, concise_front_titles, refine_title_boundaries
from materials.local_formats import markdown_atoms, html_atoms
from materials.render import Assets, segments, native_table


class MaterialTests(unittest.TestCase):
    def setUp(self):
        root=Path('D:/Artifacts/RemNoteBulkImporter/material-tests')
        root.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=root)
        self.folder=Path(self.temp.name)
        self.assets=Assets(self.folder)

    def tearDown(self):self.temp.cleanup()

    def test_formula_delimiters_and_literal_currency(self):
        text=r'有 $a_1$，以及 \(\frac{b}{c}\)，尾部 $$x^2+y^2$$。'
        result=segments(text,self.assets,self.folder)
        self.assertEqual([s['value'] for s in result if s['kind']=='latex'],['a_1',r'\frac{b}{c}','x^2+y^2'])
        self.assertEqual(segments('price $5',self.assets,self.folder),[{'kind':'text','value':'price $5'}])
        inline=segments('Use `$HOME$` literally; then $x^2$.',self.assets,self.folder)
        self.assertEqual([s['value'] for s in inline if s['kind']=='latex'],['x^2'])

    def test_meaningful_headers_and_empty_ocr(self):
        blocks=[{'type':'text','text':'Body','page_idx':0,'bbox':[0,200,200,300]},
                {'type':'header','text':'2.1 Methods','page_idx':0,'bbox':[0,50,200,90]},
                {'type':'page_number','text':'4','page_idx':0},
                {'type':'text','text':'','page_idx':0}]
        atoms,coverage=atoms_from_ocr(blocks)
        self.assertEqual([a['text'] for a in atoms],['2.1 Methods','Body'])
        self.assertEqual({e['reason'] for e in coverage['excluded']},{'page_number','empty_ocr_block'})

    def test_cross_document_or_crossing_groups_rejected(self):
        atoms=[{'kind':'text','doc':'a' if i<5 else 'b'} for i in range(8)]
        with self.assertRaisesRegex(ValueError,'Cross-document'):validate_groups([{'parent':2,'through':5}],atoms,set(range(8)))
        with self.assertRaisesRegex(ValueError,'Crossing'):validate_groups([{'parent':0,'through':3},{'parent':2,'through':4}],atoms,set(range(8)))
        validate_groups([{'parent':0,'through':4},{'parent':1,'through':3}],atoms,set(range(8)))

    def test_scanner_bookmarks_are_not_a_directory(self):
        self.assertEqual(valid_bookmarks([[1,'20004406A',1],[1,'20004407B',2]]),[])
        self.assertEqual(len(valid_bookmarks([[1,'Introduction',2],[1,'Methods',5]])),2)

    def test_multilingual_chapter_title_requires_exact_body_evidence(self):
        entries=[{'title':title,'level':1,'printed_page':15} for title in ('CHAPTER 3','Waves','波动')]
        joined,trace=join_directory_titles(entries,[{'kind':'text','text':'CHAPTER 3 Waves 波动'}])
        self.assertEqual(len(joined),1);self.assertEqual(len(trace),1)
        separate,_=join_directory_titles(entries,[{'kind':'text','text':'Unrelated content'}])
        self.assertEqual(len(separate),3)

    def test_frontmatter_title_cleanup_keeps_source_and_body_titles(self):
        atoms=[{'kind':'text','text':'Astronomy third edition by Author'}]
        docs=[{'id':'front','basis':'front_matter','title':atoms[0]['text'],'start':0,'end':1},
              {'id':'body','basis':'printed_toc','title':'Chapter 1 Stars','start':1,'end':1}]
        class Producer:
            def call(self,name,prompt,data,validator):
                result={'titles':[{'id':'front','title':'书名页'}]};validator(result);return result
        concise_front_titles(docs,atoms,Producer())
        self.assertEqual(docs[0]['title'],'书名页');self.assertEqual(docs[1]['title'],'Chapter 1 Stars')
        self.assertEqual(atoms[0]['text'],'Astronomy third edition by Author')

    def test_split_chapter_prefix_moves_with_its_title(self):
        atoms=[{'id':f'a{i:06d}','kind':'text','text':text,'page':2,'doc':'first' if i<2 else 'next'}
               for i,text in enumerate(['Previous paragraph','第2讲','声波','Body'])]
        docs=[{'id':'first','title':'第1讲 力','basis':'printed_toc','start':0,'end':2},
              {'id':'next','title':'第2讲 声波','basis':'printed_toc','start':2,'end':4}]
        structure={'atoms':atoms,'documents':docs,'groups':[{'parent':0,'through':1}]}
        changes=refine_title_boundaries(structure)
        self.assertEqual(changes,[{'atom':'a000001','from':'first','to':'next'}])
        self.assertEqual(docs[1]['start'],1);self.assertEqual(structure['groups'],[])
        self.assertEqual(atoms[1]['doc'],'next')

    def test_contents_continuation_without_fixed_page_offset(self):
        atoms=[{'page':8,'text':'目 录'},{'page':9,'text':'A …… (1)'},{'page':9,'text':'B …… （6）'},{'page':9,'text':'C …… 8'},{'page':10,'text':'Body'}]
        self.assertEqual(contents_pages(atoms),[8,9])

    def test_unlabelled_contents_with_missing_first_page_numbers(self):
        atoms=[{'page':1,'text':f'{i}. Topic'} for i in range(8)]
        atoms += [{'page':p,'text':f'{i}. Topic {i+p+10}'} for p in (2,3) for i in range(8)]
        atoms += [{'page':4,'text':'This is a full paragraph without a page reference.'}]
        self.assertEqual(contents_pages(atoms),[1,2,3])

    def test_empty_epub_anchors_are_metadata(self):
        atoms=markdown_atoms('<a id="chapter-a"></a>\n\n# Stars\n\nStars emit light.',self.folder)
        self.assertEqual(len(atoms),2)
        self.assertEqual(atoms[0]['anchors'],['chapter-a'])

    def test_internal_link_becomes_native_reference_and_preview_link(self):
        from materials.render import local_preview
        self.assets.anchors['chapter']='target'
        result=segments('[Read chapter](#chapter)',self.assets,self.folder)
        self.assertIn({'kind':'ref','targetId':'target'},result)
        bundle={'title':'Links','assets':{},'nodes':[{'id':'source','parentId':None,'document':False,'text':result},
                {'id':'target','parentId':None,'document':True,'text':[{'kind':'text','value':'Chapter'}]}]}
        self.assertIn('href="#target"',local_preview(bundle))

    def test_markdown_heading_math_and_nested_list(self):
        atoms=markdown_atoms('# Biology\n\n## Cells\n\n- Membrane\n  - $r^2$\n\n```python\nx = "$literal"\n```\n',self.folder)
        self.assertEqual([a['heading_level'] for a in atoms[:2]],[1,2])
        self.assertEqual([a.get('list_depth') for a in atoms[2:4]],[1,2])
        self.assertEqual(atoms[-1]['text'],'x = "$literal"\n')

    def test_html_keeps_inline_formula_and_local_image(self):
        from PIL import Image
        image=self.folder/'tiny.png';Image.new('RGB',(4,4),'blue').save(image)
        atoms=html_atoms('<h1>Chemistry</h1><p>Mass <b>m</b> $v^2$ <img src="tiny.png"></p>',self.folder)
        result=segments(atoms[1]['text'],self.assets,self.folder,raw_html=True)
        self.assertTrue(any(s['kind']=='latex' and s['value']=='v^2' for s in result))
        self.assertEqual(sum(s['kind']=='image' for s in result),1)

    def test_table_spans_keep_each_cell_once(self):
        source='<table><tr><td colspan="2">Temperature</td></tr><tr><td>$T$</td><td>300 K</td></tr></table>'
        result,spans=native_table(source,self.assets,self.folder)
        self.assertTrue(spans)
        self.assertEqual(result[0]['value'].count('Temperature'),1)
        self.assertIn('{T}',result[0]['value'])

    def test_unicode_relations_in_table_are_math_glyphs(self):
        result,_=native_table('<table><tr><td>A≠B</td><td>P∉L</td></tr></table>',self.assets,self.folder)
        self.assertIn('≠',result[0]['value']);self.assertIn('∉',result[0]['value'])
        self.assertNotIn(r'\text{A≠B}',result[0]['value'])

    def test_ocr_inline_table_media_resolves_without_source_rewrite(self):
        from PIL import Image
        managed=self.folder/'managed.png';Image.new('RGB',(3,3),'red').save(managed)
        source='<table><tr><td><img src="images/original.png"></td><td>Diagram</td></tr></table>'
        block={'type':'table','table_body':source,'page_idx':0}
        mapping=inline_media(block,{'original.png':managed})
        self.assertEqual(block['table_body'],source)
        self.assets.aliases[(self.folder/'images/original.png').resolve()]=managed
        result,_=native_table(source,self.assets,self.folder)
        self.assertEqual(sum(s['kind']=='image' for s in result),1)
        self.assertEqual(mapping['images/original.png']['path'],str(managed))

    def test_long_document_skeleton_preserves_scope_boundaries(self):
        atoms=[{'kind':'text','text':f'Body {i}','doc':'d','heading_level':0} for i in range(850)]
        for i in (0,450):atoms[i].update(text=f'Chapter {i}',heading_level=1)
        class Producer:
            def call(self,name,prompt,data,validator):
                result={'headings':[{'i':0,'level':1},{'i':450,'level':1}]}
                validator(result);return result
        scopes,groups=long_document_scopes({'id':'d','title':'Lecture'},list(range(850)),atoms,Producer())
        self.assertEqual(groups,[{'parent':0,'through':449},{'parent':450,'through':849}])
        self.assertTrue(all(len(rows)<=400 for _,rows in scopes))
        self.assertEqual([i for _,rows in scopes for i in rows],[i for i in range(850) if i not in (0,450)])

    def test_failed_outline_batch_retries_only_at_document_boundaries(self):
        atoms=[{'id':f'a{i:06d}','kind':'text','text':f'Body {i}','doc':f'd{i//2}'} for i in range(4)]
        docs=[{'id':f'd{i}','title':'Topic','title_atom':None,'start':2*i,'end':2*i+2} for i in range(2)]
        class Producer:
            def call(self,name,prompt,data,validator):
                if len(data)>1:raise ValueError('Rejected compound batch')
                rows=data[0]['rows'];result={'groups':[{'parent':rows[0]['i'],'through':rows[-1]['i']}]}
                validator(result);return result
        self.assertEqual(outline({'atoms':atoms,'documents':docs},Producer()),[{'parent':0,'through':1},{'parent':2,'through':3}])

    def test_native_body_cannot_be_flattened_after_structure_validation(self):
        from materials.validate import validate_body_parent
        atom={'id':'a000001','doc':'d'};groups=[{'parent':0,'through':1}]
        node={'id':atom['id'],'parentId':'d'}
        with self.assertRaisesRegex(ValueError,'Body outline parent changed'):
            validate_body_parent(atom,1,groups,node,{'d':{}},{'a000000':'a000000'})
        node['parentId']='a000000'
        validate_body_parent(atom,1,groups,node,{'d':{}},{'a000000':'a000000'})

    def test_pdf_chunks_obey_both_limits_and_full_page_coverage(self):
        import pymupdf
        source=self.folder/'source.pdf'
        with pymupdf.open() as doc:
            for i in range(7):doc.new_page().insert_text((40,40),f'Page {i+1}')
            doc.save(source)
        parts=split_pdf(source,self.folder/'parts',max_pages=3,max_bytes=10000)
        self.assertEqual([p for x in parts for p in range(x['start'],x['end'])],list(range(7)))
        self.assertTrue(all(x['end']-x['start']<=3 and Path(x['path']).stat().st_size<=10000 for x in parts))

    def test_wrong_or_disconnected_library_never_prepares_or_writes(self):
        from materials.delivery import deliver
        report={'source_sha256':'a'*64,'info':{'hash':'b'*64}}
        for state in ({'connected':False},{'connected':True,'kbId':'other'}):
            with patch('materials.delivery.STATE',self.folder/'registry'),patch('materials.delivery.validate',return_value=report),patch('materials.delivery.mcp',return_value=state) as client:
                with self.assertRaisesRegex(ValueError,'disconnected or different'):deliver(self.folder,'expected')
                self.assertEqual(client.call_args_list[0].args,('status',))
                self.assertEqual(client.call_count,1)
                self.assertFalse(list((self.folder/'registry').glob('*.json')))

    def test_existing_source_cannot_be_reimported_with_another_package(self):
        from materials.delivery import deliver
        from materials.common import save
        state=self.folder/'registry';state.mkdir()
        save(state/('expected-'+'a'*64+'.json'),{'packageHash':'old','status':'complete'})
        report={'source_sha256':'a'*64,'info':{'hash':'new'}}
        with patch('materials.delivery.STATE',state),patch('materials.delivery.validate',return_value=report),patch('materials.delivery.mcp',return_value={'connected':True,'kbId':'expected'}) as client:
            with self.assertRaisesRegex(ValueError,'different import package'):deliver(self.folder,'expected')
            self.assertEqual(client.call_count,1)


if __name__=='__main__':unittest.main()
