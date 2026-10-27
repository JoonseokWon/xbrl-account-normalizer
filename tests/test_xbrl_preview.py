import hashlib,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from application import xbrl_preview as preview
from core.errors import InputError


class XbrlPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def record(self,number,document='journal-001.xbrl',**changes):
        value={'file':document,'detailId':f'd{number:07d}','company':'DUMMY','system':'ERP-X',
               'originalCode':'0001','originalName':'보통예금','standardCode':'A1102','source':f'원장.xlsx / 원장!{number+1}',
               'journalId':f'J{number:07d}','lineId':'001','debit':100,'credit':0,'author':'더미 작성자'}
        value.update(changes);return value
    def write(self,rows,counts=None):
        raw=b''.join((json.dumps(row,ensure_ascii=False)+'\n').encode('utf-8') for row in rows)
        (self.root/'row-map.jsonl').write_bytes(raw)
        if counts is None:
            counts={}
            for row in rows:counts[row['file']]=counts.get(row['file'],0)+1
        report={'schema':preview.REPORT_SCHEMA,'rowMap':'row-map.jsonl','rowMapSha256':hashlib.sha256(raw).hexdigest(),
                'documents':[{'file':name,'validation':{'rows':count}} for name,count in counts.items()]}
        for name in counts:(self.root/name).write_text('<synthetic-preview-test/>',encoding='utf-8')
        self.report(report);return report
    def report(self,value):
        (self.root/'validation-report.json').write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
    def test_pages_preserve_leading_zeros_and_legacy_missing_fields(self):
        self.write([self.record(i) for i in range(1,8)])
        first=preview.preview_rows(self.root,offset=0,limit=3)
        self.assertEqual((len(first['rows']),first['total'],first['hasMore']),(3,7,True))
        self.assertEqual(first['rows'][0]['originalCode'],'0001')
        self.assertEqual(first['rows'][0]['lineId'],'001')
        self.assertEqual(first['rows'][0]['standardName'],'')
        self.assertEqual(first['rows'][0]['dimensions'],{})
        last=preview.preview_rows(self.root,offset=6,limit=3)
        self.assertEqual((len(last['rows']),last['hasMore']),(1,False))
        self.assertEqual(preview.preview_rows(self.root,offset=7)['rows'],[])
    def test_document_filter_offsets_only_selected_document(self):
        self.write([self.record(1),self.record(1,'balance-001.xbrl',amount=-100),self.record(2),self.record(2,'balance-001.xbrl',amount=0)])
        page=preview.preview_rows(self.root,'balance-001.xbrl',offset=1,limit=1)
        self.assertEqual((page['total'],page['rows'][0]['amount'],page['hasMore']),(2,0,False))
    def test_new_metadata_fields_are_preserved(self):
        self.write([self.record(1,standardName='현금성 예금',postingDate='2026-01-05',leadCode='CASH',dimensions={'bank':'신한은행','bankAccount':'000-01'})])
        row=preview.preview_rows(self.root)['rows'][0]
        self.assertEqual(row['standardName'],'현금성 예금');self.assertEqual(row['dimensions']['bankAccount'],'000-01')
    def test_only_limit_plus_one_matching_rows_are_parsed(self):
        self.write([self.record(i) for i in range(1,5001)])
        with patch.object(preview,'_json_object',wraps=preview._json_object) as decode:
            page=preview.preview_rows(self.root,limit=100)
        self.assertTrue(page['hasMore']);self.assertEqual(decode.call_count,102)
    def test_page_parameters_are_bounded(self):
        self.write([self.record(1)])
        for changes in ({'limit':201},{'limit':0},{'limit':True},{'offset':-1},{'offset':False}):
            with self.subTest(changes=changes),self.assertRaises(InputError):preview.preview_rows(self.root,**changes)
    def test_document_path_escape_and_undeclared_document_are_rejected(self):
        self.write([self.record(1)])
        for name in ('../journal-001.xbrl','C:\\secret.xbrl','/secret.xbrl','unknown.xbrl'):
            with self.subTest(name=name),self.assertRaises(InputError):preview.preview_rows(self.root,name)
    def test_report_cannot_declare_arbitrary_rowmap_or_document_path(self):
        report=self.write([self.record(1)])
        for rowmap in ('../private.jsonl','private.jsonl','C:\\private.jsonl'):
            self.report(dict(report,rowMap=rowmap))
            with self.assertRaises(InputError):preview.preview_rows(self.root)
        report['documents'][0]['file']='../secret.xbrl';self.report(report)
        with self.assertRaises(InputError):preview.preview_rows(self.root)
    def test_map_change_fails_hash_check(self):
        self.write([self.record(1)]);(self.root/'row-map.jsonl').write_text(json.dumps(self.record(1,originalCode='0002'))+'\n',encoding='utf-8')
        with self.assertRaises(InputError):preview.preview_rows(self.root)
    def test_report_and_map_sizes_and_line_size_are_bounded(self):
        self.write([self.record(1)])
        for name,value in (('MAX_REPORT_BYTES',8),('MAX_MAP_BYTES',1),('MAX_LINE_BYTES',64)):
            with patch.object(preview,name,value),self.subTest(name=name),self.assertRaises(InputError):preview.preview_rows(self.root)
    def test_line_count_cannot_exceed_safety_limit(self):
        self.write([self.record(i) for i in range(1,6)],{'journal-001.xbrl':4})
        with patch.object(preview,'MAX_MAP_LINES',4),self.assertRaises(InputError):preview.preview_rows(self.root)
    def test_normal_long_korean_metadata_over_64kib_remains_supported(self):
        long_text='한'*2000
        changes={key:long_text for key in ('company','system','originalCode','originalName','standardCode','source','journalId','lineId','author','standardName','leadCode')}
        changes['dimensions']={key:long_text for key in ('bank','bankAccount','counterparty','department','project','document')}
        self.write([self.record(1,**changes)])
        self.assertGreater((self.root/'row-map.jsonl').stat().st_size,64*1024)
        page=preview.preview_rows(self.root)
        self.assertEqual(page['rows'][0]['originalName'],long_text)
    def test_actual_256kib_line_cap_is_enforced_before_json_parsing(self):
        self.write([self.record(1,padding='x'*preview.MAX_LINE_BYTES)])
        with self.assertRaises(InputError):preview.preview_rows(self.root)
    def test_schema_unsafe_metadata_and_bool_money_are_rejected(self):
        for changes in ({'source':{'path':'secret'}},{'debit':True},{'credit':-1},{'dimensions':{'unknown':'value'}},{'originalName':'x'*2001}):
            self.write([self.record(1,**changes)])
            with self.subTest(changes=list(changes)),self.assertRaises(InputError):preview.preview_rows(self.root)
    def test_record_with_unknown_document_is_rejected(self):
        self.write([self.record(1,'other.xbrl')],{'journal-001.xbrl':1})
        with self.assertRaises(InputError):preview.preview_rows(self.root)
    def test_missing_selected_rows_are_not_reported_as_empty_success(self):
        self.write([self.record(1,'balance-001.xbrl'),self.record(2,'balance-001.xbrl')],{'journal-001.xbrl':1,'balance-001.xbrl':1})
        with self.assertRaises(InputError):preview.preview_rows(self.root,'journal-001.xbrl')
    def test_file_changed_between_hash_and_read_is_rejected(self):
        self.write([self.record(1)]);original=preview._hash_map
        def changed(*args):
            result=original(*args)
            with (self.root/'row-map.jsonl').open('ab') as stream:stream.write(b'\n')
            return result
        with patch.object(preview,'_hash_map',side_effect=changed),self.assertRaises(InputError):preview.preview_rows(self.root)
    def test_file_changed_during_page_read_is_rejected(self):
        self.write([self.record(1)]);original=preview._safe_row
        def changed(*args):
            result=original(*args)
            with (self.root/'row-map.jsonl').open('ab') as stream:stream.write(b'\n')
            return result
        with patch.object(preview,'_safe_row',side_effect=changed),self.assertRaises(InputError):preview.preview_rows(self.root)
    def test_report_changed_during_read_is_rejected(self):
        self.write([self.record(1)]);original=preview._hash_map
        def changed(*args):
            result=original(*args)
            with (self.root/'validation-report.json').open('ab') as stream:stream.write(b' ')
            return result
        with patch.object(preview,'_hash_map',side_effect=changed),self.assertRaises(InputError):preview.preview_rows(self.root)
    def test_symlink_outside_result_folder_is_rejected(self):
        self.write([self.record(1)]);outside=self.root/'outside';outside.mkdir();secret=outside/'secret.jsonl';secret.write_text('private',encoding='utf-8')
        result=self.root/'result';result.mkdir();self.report_data=json.loads((self.root/'validation-report.json').read_text(encoding='utf-8'))
        (result/'validation-report.json').write_text(json.dumps(self.report_data),encoding='utf-8');(result/'journal-001.xbrl').write_text('<x/>',encoding='utf-8')
        try:(result/'row-map.jsonl').symlink_to(secret)
        except (OSError,NotImplementedError) as exc:self.skipTest('이 환경에서 파일 symlink를 만들 수 없음: '+str(exc))
        with self.assertRaises(InputError):preview.preview_rows(result)

if __name__=='__main__':unittest.main()
