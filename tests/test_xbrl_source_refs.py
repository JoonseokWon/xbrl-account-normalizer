import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from application.xbrl_source_refs import source_hashes

class XbrlSourceReferenceTests(unittest.TestCase):
    def test_single_and_batch(self):
        self.assertEqual(source_hashes({'sha256':'A'*64}),{'a'*64})
        self.assertEqual(source_hashes({'files':[{'sha256':'a'*64},{'sha256':'b'*64}]}),{'a'*64,'b'*64})
    def test_malformed_unsigned_metadata_disables_source_jump(self):
        for value in (None,[],{'files':None},{'files':{}},{'files':[]},{'sha256':['not-a-hash']},{'sha256':'x'*64},{'files':[None]},{'files':[{'sha256':'a'*64},{'sha256':{}}]}):
            with self.subTest(value=value):self.assertEqual(source_hashes(value),set())
    def test_duplicate_and_excessive_files_do_not_match_a_single_source(self):
        self.assertEqual(source_hashes({'files':[{'sha256':'a'*64}]*2}),set())
        self.assertEqual(source_hashes({'files':[{'sha256':'a'*64}]*25}),set())

if __name__=='__main__':unittest.main()
