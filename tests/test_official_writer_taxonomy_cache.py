from pathlib import Path
import tempfile
import unittest
from xbrl_filing.taxonomy import _root_for,_catalog_rules,_schema_ref


class WriterTaxonomyCacheTests(unittest.TestCase):
    def test_official_layout_maps_hosts_without_copying_or_network(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'TaxonomyCache';entry=root/'dart.fss.or.kr/Resource/Taxonomy/ifrs/2026-01-31/dart_all_2026-01-31.xsd'
            entry.parent.mkdir(parents=True);entry.write_text('<schema/>',encoding='utf-8')
            (root/'www.xbrl.org').mkdir()
            actual,manifest=_root_for(entry)
            self.assertEqual(actual,root);self.assertIsNone(manifest)
            snapshot={'root':str(root),'entryPoint':str(entry)};rules=_catalog_rules(snapshot)
            self.assertEqual(len(rules),4)
            self.assertEqual(_schema_ref(snapshot,rules),'http://dart.fss.or.kr/Resource/Taxonomy/ifrs/2026-01-31/dart_all_2026-01-31.xsd')
            self.assertEqual(list(entry.parent.iterdir()),[entry])

    def test_arbitrary_cache_name_does_not_expand_snapshot_scope(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'TaxonomyCache';entry=root/'other.example/arbitrary.xsd';entry.parent.mkdir(parents=True);entry.touch()
            self.assertEqual(_root_for(entry),(entry.parent,None))

if __name__=='__main__':unittest.main()
