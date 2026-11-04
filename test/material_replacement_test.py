import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'consumers'))
from materials.common import save,load
from materials.delivery import deliver,finish_replacement


class ReplacementTests(unittest.TestCase):
    def setUp(self):
        root=Path('D:/Artifacts/RemNoteBulkImporter/material-tests');root.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=root);self.folder=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()

    def test_exact_completed_source_root_is_required_before_any_write(self):
        state=self.folder/'state';state.mkdir();registry=state/('kb-'+'a'*64+'.json')
        save(registry,{'packageHash':'old-hash','status':'complete','rootRemId':'original','parentRemId':None})
        report={'source_sha256':'a'*64,'info':{'hash':'new-hash'}}
        with patch('materials.delivery.STATE',state),patch('materials.delivery.validate',return_value=report),patch('materials.delivery.mcp',return_value={'connected':True,'kbId':'kb'}) as bulk,patch('materials.delivery.native') as native:
            with self.assertRaisesRegex(ValueError,'match the completed'):deliver(self.folder,'kb',replace_root='wrong',archive_parent='trash')
            self.assertEqual(bulk.call_count,1);native.assert_not_called()
            self.assertEqual(load(registry)['rootRemId'],'original')

    def test_recovery_moves_whole_old_root_then_promotes_receipt(self):
        previous={'rootRemId':'old','parentRemId':None,'status':'complete','packageHash':'old-hash'}
        receipt={'rootRemId':'new','parentRemId':None,'status':'complete','packageHash':'new-hash'}
        registry=self.folder/'registry.json';save(registry,previous)
        before={'nodes':[{'id':'old','parentId':None},{'id':'new','parentId':None},{'id':'trash','parentId':None}]}
        with patch('materials.delivery.native',side_effect=[before,{'after':{'nodes':[{'id':'old','parentId':'trash'}]}}]) as client:
            result=finish_replacement(self.folder,'kb',receipt,previous,registry,'trash')
        self.assertEqual(client.call_args_list[1].kwargs,{'remId':'old','parentRemId':'trash','expectedParentRemId':None})
        self.assertEqual(load(registry)['rootRemId'],'new');self.assertEqual(result['replacesRootRemId'],'old')
        self.assertEqual(load(self.folder/'replacement-recovery.json')['previous'],previous)

    def test_archive_failure_keeps_primary_source_receipt_recoverable(self):
        previous={'rootRemId':'old','parentRemId':None};receipt={'rootRemId':'new','parentRemId':None}
        registry=self.folder/'registry.json';save(registry,previous)
        read={'nodes':[{'id':'old','parentId':None},{'id':'new','parentId':None},{'id':'trash','parentId':None}]}
        with patch('materials.delivery.native',side_effect=[read,ValueError('disconnected')]):
            with self.assertRaisesRegex(ValueError,'disconnected'):finish_replacement(self.folder,'kb',receipt,previous,registry,'trash')
        self.assertEqual(load(registry),previous)


if __name__=='__main__':unittest.main()
