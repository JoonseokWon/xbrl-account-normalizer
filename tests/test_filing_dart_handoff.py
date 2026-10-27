from copy import deepcopy
import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from openpyxl import Workbook
from core.errors import InputError
from xbrl_filing.dart_handoff import load_reference, export_handoff
from xbrl_filing import reporting


class DartHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.path=self.root/'reference.xlsx';self.outputs=self.root/'outputs';self.outputs.mkdir()
        wb=Workbook();ws=wb.active;ws.title='Concepts'
        ws.append(['#','prefix','name','id','type','enumerations','substitutionGroup','balance','periodType','abstract','nillable','typedDomainRef','ext. enum domain','ext. enum linkrole','ext. enum headUsable','comment'])
        rows=[('Assets','monetaryItemType','instant','','item'),('Revenue','monetaryItemType','duration','','item'),
              ('Note','stringItemType','duration','','item'),('EquityAxis','stringItemType','duration','true','dimensionItem'),
              ('CapitalMember','domainItemType','duration','true','item'),('Title','stringItemType','duration','true','item'),
              ('ForeignType','customItemType','duration','','item'),('Shares','sharesItemType','instant','','item'),
              ('EarningsPerShare','perShareItemType','duration','','item'),('Count','integerItemType','duration','','item')]
        for index,(name,kind,period,abstract,group) in enumerate(rows,1):
            ws.append([index,'t',name,'t_'+name,'xbrli:'+kind,'',('xbrldt:' if group=='dimensionItem' else 'xbrli:')+group,'',period,abstract,'true'])
        wb.save(self.path);wb.close()
        self.cat=load_reference(self.path)
        self.source=self.root/'source.csv';self.source.write_text('account,value\ncash,1200\n',encoding='utf-8')
    def tearDown(self):self.temp.cleanup()
    def report(self):
        return {'schema':'account-normalizer-filing/1','taxonomyFingerprint':self.cat['fingerprint'],
                'entity':{'name':'보고회사','identifier':'00001234','scheme':'urn:example:company'},
                'reporting':{'periodStart':'2026-01-01','periodEnd':'2026-12-31','consolidation':'별도','comparativePeriods':[]},
                'inputs':[{'path':str(self.source),'name':self.source.name,'sha256':hashlib.sha256(self.source.read_bytes()).hexdigest()}],
                'facts':[{'id':'f1','concept':'t:Assets','statement':'BS','period':{'kind':'instant','instant':'2026-12-31'},
                          'value':'001200.50','unit':'KRW','decimals':'0','dimensions':{},'source':'source.csv / BS!2',
                          'reviewer':'확인자','approved':True,'originalName':'현금','rowType':'total'}]}
    def export(self,value=None,cat=None):return export_handoff(value or self.report(),cat or self.cat,self.outputs)
    def check_bad_fact(self,changes):
        value=self.report();value['facts'][0].update(changes)
        with self.assertRaises(InputError):self.export(value)
        self.assertEqual(list(self.outputs.iterdir()),[])
    def test_load_reference_retains_metadata_only_scope(self):
        self.assertEqual(self.cat['fingerprint'],hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertEqual(self.cat['entryPoint'],str(self.path.resolve()))
        self.assertEqual(self.cat['mode'],'dart-reference')
        self.assertEqual(self.cat['namespaces'],{})
        self.assertIn('t:ForeignType',self.cat['unsupportedConcepts'])
        self.assertEqual(self.cat['concepts']['t:Note']['kind'],'string')
        self.assertEqual(self.cat['concepts']['t:ForeignType']['kind'],'unsupported')
    def test_exports_all_facts_without_xml_or_full_validation_claim(self):
        value=self.report();before=deepcopy(value);path=self.export(value)
        self.assertTrue(path.name.startswith('DART_공시대사_'))
        self.assertEqual({p.name for p in path.iterdir()},{'facts.json','validation-report.json','DART_입력대사.csv','공시대사결과.html'})
        result=json.loads((path/'validation-report.json').read_text(encoding='utf-8'))
        self.assertEqual(result['validationScope'],'concept-metadata-only');self.assertFalse(result['xmlGenerated'])
        for check in ('officialXsd','dimensions','calculation','dartSubmission','completeness'):
            self.assertEqual(result[check]['status'],'not-performed')
        self.assertEqual(result['sourceFilesChecked'],1)
        facts=json.loads((path/'facts.json').read_text(encoding='utf-8'))
        self.assertEqual(facts['facts'][0]['value'],'1200.5')
        self.assertEqual(facts['facts'][0]['rowType'],'total')
        self.assertNotIn('path',facts['inputs'][0]);self.assertEqual(value,before)
        self.assertNotIn('검사를 통과했어요',(path/'공시대사결과.html').read_text(encoding='utf-8'))
        self.assertEqual(list(self.outputs.iterdir()),[path])
    def test_explicit_approval_reviewer_and_source_required(self):
        for changes in ({'approved':False},{'approved':1},{'reviewer':''},{'source':None}):
            with self.subTest(changes=changes):self.check_bad_fact(changes)
    def test_company_scheme_dates_and_comparatives_checked(self):
        cases=[]
        for field,value in (('name',''),('identifier',''),('scheme','relative')):
            item=self.report();item['entity'][field]=value;cases.append(item)
        for field,value in (('periodStart','2026-13-01'),('periodEnd','2025-01-01'),('consolidation','unknown')):
            item=self.report();item['reporting'][field]=value;cases.append(item)
        item=self.report();item['reporting']['comparativePeriods']=[{'periodStart':'2026-01-01','periodEnd':'2026-12-31'}];cases.append(item)
        for item in cases:
            with self.subTest(item=item),self.assertRaises(InputError):self.export(item)
        self.assertEqual(list(self.outputs.iterdir()),[])
    def test_no_unsupported_abstract_or_missing_concept_is_silently_dropped(self):
        for name in ('t:ForeignType','t:Title','missing:Assets','t:EquityAxis'):
            with self.subTest(name=name):self.check_bad_fact({'concept':name})
    def test_numeric_lexical_unit_period_and_accuracy_checks(self):
        for changes in ({'value':'1e3'},{'value':'NaN'},{'value':12},{'value':'１２３'},
                        {'value':'1,200'},{'unit':'pure'},{'decimals':'13'},
                        {'period':{'kind':'duration','start':'2026-01-01','end':'2026-12-31'}},
                        {'period':{'kind':'instant','instant':'2024-12-31'}}):
            with self.subTest(changes=changes):self.check_bad_fact(changes)
    def test_duplicate_ids_and_equivalent_facts_not_summed(self):
        for field in ('id','concept-key'):
            value=self.report();other=deepcopy(value['facts'][0])
            if field=='id':other['concept']='t:Revenue';other['period']={'kind':'duration','start':'2026-01-01','end':'2026-12-31'}
            else:other['id']='f2'
            value['facts'].append(other)
            with self.subTest(field=field),self.assertRaises(InputError):self.export(value)
    def test_dimension_names_exist_but_no_dimensional_validation_claim(self):
        value=self.report();value['facts'][0]['dimensions']={'t:EquityAxis':'t:CapitalMember'}
        path=self.export(value);result=json.loads((path/'validation-report.json').read_text(encoding='utf-8'))
        self.assertEqual(result['dimensions']['status'],'not-performed')
        value['facts'][0]['dimensions']={'t:EquityAxis':'t:NoSuchMember'}
        with self.assertRaises(InputError):self.export(value)
    def test_fingerprint_reference_change_and_catalogue_tampering(self):
        value=self.report();value['taxonomyFingerprint']='a'*64
        with self.assertRaises(InputError):self.export(value)
        cat=deepcopy(self.cat);cat['concepts']['t:Assets']['abstract']=True
        path=self.export(cat=cat);self.assertTrue(path.is_dir())
        self.path.write_bytes(self.path.read_bytes()+b'changed')
        with self.assertRaises(InputError):self.export()
    def test_source_change_before_and_during_export_discards_staging(self):
        value=self.report();self.source.write_text('changed',encoding='utf-8')
        with self.assertRaises(InputError):self.export(value)
        current=self.report();original=reporting.write_handoff
        def write_then_change(path,report):
            original(path,report);self.source.write_text('changed-again',encoding='utf-8')
        with patch.object(reporting,'write_handoff',write_then_change),self.assertRaises(InputError):self.export(current)
        self.assertEqual(list(self.outputs.iterdir()),[])
    def test_reference_change_during_export_discards_staging(self):
        original=reporting.write_handoff
        def write_then_change(path,report):
            original(path,report);self.path.write_bytes(self.path.read_bytes()+b'changed')
        with patch.object(reporting,'write_handoff',write_then_change),self.assertRaises(InputError):self.export()
        self.assertEqual(list(self.outputs.iterdir()),[])
    def test_csv_formula_escaping_and_html_escaping(self):
        value=self.report();fact=value['facts'][0]
        fact.update(concept='t:Note',value='=1+1',unit='',decimals='',period={'kind':'duration','start':'2026-01-01','end':'2026-12-31'},originalName='<script>alert(1)</script>')
        path=self.export(value)
        with (path/'DART_입력대사.csv').open(encoding='utf-8-sig',newline='') as stream:rows=list(csv.reader(stream))
        self.assertEqual(rows[1][8],"'=1+1")
        html=(path/'공시대사결과.html').read_text(encoding='utf-8')
        self.assertNotIn('<script>',html);self.assertIn('&lt;script&gt;',html)
    def test_per_share_and_integer_types_keep_their_units(self):
        value=self.report();value['facts'][0].update(concept='t:EarningsPerShare',value='-123.45',unit='KRW/shares',period={'kind':'duration','start':'2026-01-01','end':'2026-12-31'})
        path=self.export(value);self.assertTrue(path.is_dir())
        value['facts'][0].update(concept='t:Count',value='1.5',unit='pure')
        with self.assertRaises(InputError):self.export(value)


if __name__=='__main__':unittest.main()
