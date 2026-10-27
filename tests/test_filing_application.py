import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from application.filing import export_filing,suggest_concepts,verify_sources
from core.errors import InputError
from xbrl_filing.reconciliation import balance_checks
from xbrl_filing.reporting import write_handoff


class FilingApplicationTests(unittest.TestCase):
    def test_candidates_do_not_approve_or_aggregate(self):
        report={'facts':[{'originalName':'Cash','value':'50','period':{'kind':'instant'},'approved':False}]}
        catalog={'concepts':{'p:Cash':{'label':'Cash','localName':'Cash','abstract':False,'periodType':'instant','kind':'monetary'}}}
        value=suggest_concepts(report,catalog)
        self.assertEqual(value['facts'][0]['suggestions'],['p:Cash']);self.assertFalse(value['facts'][0]['approved'])
        self.assertEqual(value['facts'][0]['value'],'50');self.assertNotIn('suggestions',report['facts'][0])

    def test_changed_input_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'input.csv';path.write_text('changed',encoding='utf-8')
            with self.assertRaises(InputError):verify_sources({'inputs':[{'path':str(path),'name':path.name,'sha256':'0'*64}]})

    def test_balance_equation_uses_context_and_accuracy(self):
        catalog={'concepts':{q:{'namespace':'https://xbrl.ifrs.org/taxonomy/2025-03-27/ifrs-full','localName':q} for q in ['Assets','Liabilities','Equity']}}
        facts=[{'id':q,'concept':q,'unit':'KRW','value':v,'period':{'kind':'instant','instant':'2026-12-31'},'dimensions':{},'decimals':'0'} for q,v in [('Assets','100'),('Liabilities','40'),('Equity','60')]]
        self.assertEqual(balance_checks({'facts':facts},catalog)[0]['status'],'pass')
        facts[0]['value']='103';self.assertEqual(balance_checks({'facts':facts},catalog)[0]['status'],'error')
        facts[-1]['period']['instant']='2025-12-31';self.assertEqual(balance_checks({'facts':facts},catalog)[0]['status'],'skipped')

    def test_csv_text_never_becomes_formula_and_code_zero_remains(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'table.csv';report={'entity':{'name':'=name','identifier':'0012'},'reporting':{'consolidation':'별도'},'facts':[
                {'id':'f1','originalCode':'0001','originalName':'+name','statement':'NOTE','concept':'p:Text','value':'=HYPERLINK("x")','unit':'','decimals':'','period':{'kind':'duration','start':'2026-01-01','end':'2026-12-31'},'dimensions':{},'source':'input:2','reviewer':'Tester'}]}
            write_handoff(path,report)
            with path.open(encoding='utf-8-sig',newline='') as stream:row=list(csv.reader(stream))[1]
            self.assertEqual(row[5],"'0001");self.assertTrue(row[8].startswith("'="));self.assertTrue(row[0].startswith("'="))

    def test_taxonomy_binding_cannot_be_bypassed_by_ui_metadata(self):
        with patch('application.filing.load_taxonomy',return_value={'fingerprint':'actual'}):
            with self.assertRaises(InputError):export_filing({'taxonomyFingerprint':'old'},{'entryPoint':'entry.xsd','fingerprint':'old'},'unused')

if __name__=='__main__':unittest.main()
