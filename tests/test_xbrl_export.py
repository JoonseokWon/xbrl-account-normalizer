import hashlib,json,sys,tempfile,unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from lxml import etree as ET
from workflow_fixtures import session
from application.xbrl_export import export_xbrl
from application.configuration import default_catalog,default_profile
from application.session import Session
from normalizer import normalize
from review_history import ReviewHistory
from core.errors import InputError
from xbrl_gl.taxonomy import q,OfflineResolver
from xbrl_gl.validation import validate_instance


def balance_session(folder):
    source=Path(folder)/'bs-source.json';source.write_text('synthetic BS source',encoding='utf-8')
    raw={'fs':[]};rules=[]
    for i,(code,name,target,amount,rowtype) in enumerate([('0001','예금','A1102',1450000,'상세'),('0002','현금및현금성자산','A1100',1450000,'소계'),('0003','충당금','A1291',-30000,'상세')],1):
        raw['fs'].append(dict(company='A',account=code,name=name,date='2026-01-31',amount=amount,unit='원',rowType=rowtype,statement='BS',_source=f'BS!{i+1}'))
        rules.append(dict(zip(('입력종류','회사코드','원천시스템','원본계정코드','원본계정명','표준계정코드','상태','확인자'),['재무제표','A','ERP-X',code,name,target,'확인','더미 정의'])))
    profile=default_profile();profile.update(companyCode='A',sourceSystem='ERP-X');catalog=default_catalog()
    metadata={'file':source.name,'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
    result=normalize(raw,rules,catalog,profile,metadata)
    return Session(source,profile,catalog,raw,rules,{},metadata,result,ReviewHistory(),False)


class XbrlExportTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.folder=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def output(self):
        value=session(self.folder,True);out=export_xbrl(value,self.folder/'out');return value,out
    def validate_changed(self,value,out,change,balance=False):
        path=next(out.glob('*.xbrl'));tree=ET.parse(str(path));change(tree);path.write_bytes(ET.tostring(tree,encoding='utf-8',xml_declaration=True))
        return validate_instance(path,value.result['financial'] if balance else value.result['ledger'],'A','2026-01-31',balance)
    def test_official_gl_rows_codes_compound_and_totals(self):
        value,out=self.output();report=json.loads((out/'validation-report.json').read_text(encoding='utf-8'))
        self.assertEqual(report['documents'][0]['validation']['rows'],3)
        self.assertEqual(report['documents'][0]['validation']['debitTotal'],150)
        tree=ET.parse(str(next(out.glob('*.xbrl'))))
        self.assertEqual(tree.find('.//'+q('gl-cor','accountMainID')).text,'001')
        self.assertEqual(tree.find('.//'+q('gl-cor','lineNumber')).text,'001')
        self.assertFalse(report['officialFinancialReportingTaxonomyMapping'])
        self.assertFalse(report['regulatoryFilingValidated'])
        self.assertTrue((out/'xbrl-gl-2015-taxonomy.zip').is_file())
        self.assertEqual(len((out/'row-map.jsonl').read_text(encoding='utf-8').splitlines()),3)
    def test_pending_cannot_export(self):
        value=session(self.folder)
        with self.assertRaises(InputError):export_xbrl(value,self.folder/'out')
        self.assertFalse((self.folder/'out').exists())
    def test_source_change_blocks_export(self):
        value=session(self.folder,True);value.input_path.write_text('changed',encoding='utf-8')
        with self.assertRaises(InputError):export_xbrl(value,self.folder/'out')
    def test_original_and_standard_codes_are_independent(self):
        value,out=self.output()
        self.assertEqual(ET.parse(str(next(out.glob('*.xbrl')))).find('.//'+q('gl-cor','accountSubID')).text,'A1102')
    def test_tampered_valid_xsd_amount_is_detected(self):
        value,out=self.output()
        with self.assertRaises(InputError):self.validate_changed(value,out,lambda t:setattr(t.find('.//'+q('gl-cor','amount')),'text','101'))
    def test_invalid_dc_enum_is_detected(self):
        value,out=self.output()
        with self.assertRaises(InputError):self.validate_changed(value,out,lambda t:setattr(t.find('.//'+q('gl-cor','debitCreditCode')),'text','X'))
    def test_missing_context_is_detected(self):
        value,out=self.output()
        with self.assertRaises(InputError):self.validate_changed(value,out,lambda t:t.getroot().remove(t.find(q('xbrli','context'))))
    def test_changed_company_is_detected(self):
        value,out=self.output()
        with self.assertRaises(InputError):self.validate_changed(value,out,lambda t:setattr(t.find('.//'+q('xbrli','identifier')),'text','B'))
    def test_header_total_change_is_detected(self):
        value,out=self.output()
        with self.assertRaises(InputError):self.validate_changed(value,out,lambda t:setattr(t.find('.//'+q('gl-bus','totalDebit')),'text','151'))
    def test_source_code_zero_loss_is_detected(self):
        value,out=self.output()
        with self.assertRaises(InputError):self.validate_changed(value,out,lambda t:setattr(t.find('.//'+q('gl-cor','accountMainID')),'text','1'))
    def test_dtd_is_rejected(self):
        value,out=self.output();path=next(out.glob('*.xbrl'));data=path.read_bytes()
        path.write_bytes(data.replace(b'?>',b'?>\n<!DOCTYPE xbrl []>',1))
        with self.assertRaises(InputError):validate_instance(path,value.result['ledger'],'A','2026-01-31')
    def test_invalid_xml_character_does_not_leave_partial_export(self):
        value=session(self.folder,True);value.result['ledger'][0]['description']='bad\x01text'
        with self.assertRaises(ValueError):export_xbrl(value,self.folder/'out')
        self.assertEqual(list((self.folder/'out').iterdir()),[])
    def test_external_schema_resolver_cannot_read_arbitrary_files(self):
        resolver=OfflineResolver()
        for uri in ('https://example.com/a.xsd',str(self.folder/'secret.xsd'),'ftp://www.xbrl.org/a.xsd'):
            with self.assertRaises(InputError):resolver.resolve(uri,None,None)
    def test_bs_values_and_subtotals_are_preserved_without_summing(self):
        value=balance_session(self.folder);out=export_xbrl(value,self.folder/'out')
        report=json.loads((out/'validation-report.json').read_text(encoding='utf-8'))
        self.assertEqual(report['documents'][0]['type'],'BS balances')
        self.assertEqual(report['documents'][0]['validation']['rows'],3)
        tree=ET.parse(str(next(out.glob('*.xbrl'))))
        self.assertEqual([int(n.text) for n in tree.findall('.//'+q('gl-cor','amount'))],[1450000,1450000,-30000])
        self.assertEqual(tree.findall('.//'+q('gl-cor','debitCreditCode')),[])
    def test_bs_rowtype_change_is_detected(self):
        value=balance_session(self.folder);out=export_xbrl(value,self.folder/'out')
        def mutate(tree):
            for sub in tree.findall('.//'+q('gl-cor','accountSub')):
                if sub.findtext(q('gl-cor','accountSubType'))=='source-row-type':sub.find(q('gl-cor','accountSubID')).text='合計';break
        with self.assertRaises(InputError):self.validate_changed(value,out,mutate,True)

if __name__=='__main__':unittest.main()
