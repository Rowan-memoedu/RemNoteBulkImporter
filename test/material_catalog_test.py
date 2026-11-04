import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'consumers'))
from materials.catalog import organize


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.source={'documents':[{'id':'old-folder','basis':'source_directories'},
            {'id':'p1','basis':'source_pages','title':'One','parent':'old-folder'},
            {'id':'p2','basis':'source_pages','title':'Two','parent':'old-folder'}],
            'atoms':[{'source_page':'a/One.md','doc':'p1','text':'Exact $x$'}, {'source_page':'a/Two.md','doc':'p2','text':'Exact two'}],'groups':[]}
        self.plan={'containers':[{'id':'catalog-methods','title':'Methods'}],
            'pages':[{'path':'a/One.md','parent':'catalog-methods'},{'path':'a/Two.md','parent':'a/One.md'}]}
    def test_reparenting_is_source_neutral_and_does_not_change_input(self):
        before=copy.deepcopy(self.source);result=organize(self.source,self.plan,{})
        self.assertEqual(self.source,before);self.assertEqual(result['atoms'],before['atoms'])
        self.assertEqual([d['id'] for d in result['documents']],['catalog-methods','p1','p2'])
        self.assertEqual(result['documents'][2]['parent'],'p1')
    def test_omission_duplicate_and_cycles_fail(self):
        plan=copy.deepcopy(self.plan);plan['pages'].pop()
        with self.assertRaisesRegex(ValueError,'every unique'):organize(self.source,plan,{})
        plan=copy.deepcopy(self.plan);plan['pages'][1]['path']='a/One.md'
        with self.assertRaisesRegex(ValueError,'duplicate'):organize(self.source,plan,{})
        plan=copy.deepcopy(self.plan);plan['pages'][0]['parent']='a/Two.md'
        with self.assertRaisesRegex(ValueError,'Cyclic'):organize(self.source,plan,{})


if __name__=='__main__':unittest.main()
