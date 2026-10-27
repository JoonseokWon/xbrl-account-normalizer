import hashlib,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from lxml import etree as ET
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from workflow_fixtures import session
from test_xbrl_export import balance_session
from application.xbrl_export import export_xbrl
from application.xbrl_inspection import inspect_export
from xbrl_gl.taxonomy import q


class XbrlInspectionTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.folder=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def exported(self,balance=False):
        value=balance_session(self.folder) if balance else session(self.folder,True)
        return value,export_xbrl(value,self.folder/'out')
    def report(self,out):return json.loads((out/'validation-report.json').read_text(encoding='utf-8'))
    def save_report(self,out,report):(out/'validation-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    def test_saved_result_passes_without_source_file_and_does_not_write(self):
        value,out=self.exported();value.input_path.unlink()
        before={p.name:p.read_bytes() for p in out.iterdir() if p.is_file()}
        result=inspect_export(out)
        self.assertTrue(result['passed'],result['errors']);self.assertEqual(result['documents'][0]['rows'],3)
        self.assertTrue(result['documents'][0]['schemaValid']);self.assertEqual(result['documents'][0]['debitTotal'],150)
        self.assertEqual(result['source'],value.source);self.assertEqual(result['catalogVersion'],value.catalog['version'])
        self.assertEqual(before,{p.name:p.read_bytes() for p in out.iterdir() if p.is_file()})
        self.assertFalse(result['warnings'])
        self.assertTrue(any(c['code']=='INSPECTION_SCOPE' and c['status']=='info' for c in result['checks']))
        json.dumps(result,ensure_ascii=False)
    def test_valid_xsd_amount_tamper_is_found_even_when_xml_hash_updated(self):
        value,out=self.exported();report=self.report(out);path=out/report['documents'][0]['file'];tree=ET.parse(path)
        tree.find('.//'+q('gl-cor','amount')).text='101';path.write_bytes(ET.tostring(tree,encoding='utf-8',xml_declaration=True))
        report['documents'][0]['sha256']=hashlib.sha256(path.read_bytes()).hexdigest();self.save_report(out,report)
        result=inspect_export(out)
        self.assertFalse(result['passed']);self.assertTrue(any(c['code']=='XML_CONTENT' for c in result['errors']))
        self.assertTrue(result['documents'][0]['schemaValid'])
        mismatch=next(c for c in result['errors'] if c['code']=='XML_CONTENT')
        self.assertEqual(mismatch['source'],value.result['ledger'][0]['source']);self.assertEqual(mismatch['detailId'],'d0000001')
    def test_xml_hash_tamper_is_reported(self):
        _,out=self.exported();path=next(out.glob('*.xbrl'));path.write_bytes(path.read_bytes()+b'\n')
        result=inspect_export(out)
        self.assertFalse(result['passed']);self.assertTrue(any(c['code']=='XML_HASH' for c in result['errors']))
    def test_exponential_xml_amount_cannot_allocate_an_unbounded_integer(self):
        _,out=self.exported();report=self.report(out);path=out/report['documents'][0]['file'];tree=ET.parse(path)
        tree.find('.//'+q('gl-cor','amount')).text='1e999999999';path.write_bytes(ET.tostring(tree,encoding='utf-8',xml_declaration=True))
        report['documents'][0]['sha256']=hashlib.sha256(path.read_bytes()).hexdigest();self.save_report(out,report)
        self.assertFalse(inspect_export(out)['passed'])
    def test_report_path_traversal_cannot_be_read(self):
        _,out=self.exported();report=self.report(out);report['documents'][0]['file']='../secret.xbrl';self.save_report(out,report)
        result=inspect_export(out)
        self.assertFalse(result['passed']);self.assertEqual(result['documents'],[])
    def test_duplicate_document_is_rejected(self):
        _,out=self.exported();report=self.report(out);report['documents'].append(report['documents'][0]);self.save_report(out,report)
        self.assertFalse(inspect_export(out)['passed'])
    def test_unreported_xml_is_rejected(self):
        _,out=self.exported();(out/'extra.xbrl').write_bytes(next(out.glob('*.xbrl')).read_bytes())
        self.assertFalse(inspect_export(out)['passed'])
    def test_dtd_is_rejected_even_when_hash_updated(self):
        _,out=self.exported();report=self.report(out);path=out/report['documents'][0]['file']
        path.write_bytes(path.read_bytes().replace(b'?>',b'?>\n<!DOCTYPE xbrl []>',1))
        report['documents'][0]['sha256']=hashlib.sha256(path.read_bytes()).hexdigest();self.save_report(out,report)
        result=inspect_export(out);self.assertFalse(result['passed']);self.assertFalse(result['documents'][0]['schemaValid'])
    def test_row_map_tamper_is_detected_even_when_hash_updated(self):
        _,out=self.exported();report=self.report(out);path=out/report['rowMap'];lines=path.read_text(encoding='utf-8').splitlines();first=json.loads(lines[0]);first['originalCode']='1';lines[0]=json.dumps(first,ensure_ascii=False)
        path.write_text('\n'.join(lines)+'\n',encoding='utf-8');report['rowMapSha256']=hashlib.sha256(path.read_bytes()).hexdigest();self.save_report(out,report)
        self.assertFalse(inspect_export(out)['passed'])
    def test_missing_row_map_is_reported_without_exception(self):
        _,out=self.exported();(out/'row-map.jsonl').unlink();self.assertFalse(inspect_export(out)['passed'])
    def test_large_but_bounded_unicode_row_map_record_is_supported(self):
        _,out=self.exported();report=self.report(out);path=out/report['rowMap'];lines=path.read_text(encoding='utf-8').splitlines();first=json.loads(lines[0]);first['source']='원본: '+'가'*50000;lines[0]=json.dumps(first,ensure_ascii=False)
        path.write_text('\n'.join(lines)+'\n',encoding='utf-8');report['rowMapSha256']=hashlib.sha256(path.read_bytes()).hexdigest();self.save_report(out,report)
        result=inspect_export(out);self.assertTrue(result['passed'],result['errors'])
    def test_unexpected_top_level_facts_are_rejected(self):
        _,out=self.exported();report=self.report(out);path=out/report['documents'][0]['file'];tree=ET.parse(path)
        node=ET.SubElement(tree.getroot(),q('gl-cor','accountMainID'),contextRef='ctx');node.text='추가 사실'
        path.write_bytes(ET.tostring(tree,encoding='utf-8',xml_declaration=True));report['documents'][0]['sha256']=hashlib.sha256(path.read_bytes()).hexdigest();self.save_report(out,report)
        self.assertFalse(inspect_export(out)['passed'])
    def test_bounded_report_size(self):
        _,out=self.exported()
        with patch('application.xbrl_inspection.MAX_REPORT_BYTES',10):self.assertFalse(inspect_export(out)['passed'])
    def test_changed_file_while_checking_is_reported(self):
        _,out=self.exported();from application import xbrl_inspection as module
        original=module._digest;calls={}
        def changed(path,limit):
            calls[path.name]=calls.get(path.name,0)+1
            if path.name=='row-map.jsonl' and calls[path.name]==2:path.write_bytes(path.read_bytes()+b'\n')
            return original(path,limit)
        with patch('application.xbrl_inspection._digest',side_effect=changed):result=inspect_export(out)
        self.assertFalse(result['passed']);self.assertTrue(any('변경' in c['message'] for c in result['errors']))
    def test_bs_sign_and_rowtypes_reinspect(self):
        _,out=self.exported(True);result=inspect_export(out)
        self.assertTrue(result['passed'],result['errors']);self.assertIsNone(result['documents'][0]['debitTotal'])
    def test_symlink_escape_is_rejected(self):
        _,out=self.exported();report=self.report(out);path=out/report['documents'][0]['file'];outside=self.folder/'outside.xbrl';outside.write_bytes(path.read_bytes());path.unlink()
        try:path.symlink_to(outside)
        except OSError:self.skipTest('환경에서 파일 symlink 권한을 제공하지 않습니다.')
        self.assertFalse(inspect_export(out)['passed'])

if __name__=='__main__':unittest.main()
