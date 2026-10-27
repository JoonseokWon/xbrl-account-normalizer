import sys,tempfile,unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from xbrl_gl.reporting import write_report


class Tags(HTMLParser):
    def __init__(self):super().__init__();self.tags=[];self.links=[]
    def handle_starttag(self,tag,attrs):
        self.tags.append(tag)
        if tag=='a':self.links.append(dict(attrs).get('href'))


class XbrlReportingTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.folder=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def render(self,report):
        target=write_report(self.folder/'report.html',report);return target.read_text(encoding='utf-8')
    def legacy(self):
        return {'status':'공식 스키마·원본 보존 확인 완료','version':'0.7.0','catalogVersion':'USER-TEST',
                'source':{'file':'원장.xlsx'},'documents':[{'file':'journal-001.xbrl','company':'A','type':'journal',
                'start':'2026-01-01','end':'2026-01-31','validation':{'officialSchemaValid':True,'rowPreservationValid':True,'rows':250000,'debitTotal':125000,'creditTotal':125000}}]}
    def test_legacy_report_has_traceable_rows_amounts_and_safe_links(self):
        text=self.render(self.legacy());parser=Tags();parser.feed(text)
        self.assertIn('검사를 통과했어요',text);self.assertIn('250,000',text);self.assertIn('125,000',text)
        self.assertIn('journal-001.xbrl',parser.links);self.assertIn('validation-report.json',parser.links)
        self.assertNotIn('script',parser.tags);self.assertNotIn('iframe',parser.tags);self.assertNotIn('img',parser.tags)
        self.assertIn('DART 공시 제출 형식이 아니에요',text)
    def test_failure_overrides_success_status(self):
        report=self.legacy();report['checks']=[{'code':'XML_HASH','status':'error','message':'금액이 달라요','file':'journal-001.xbrl'}]
        text=self.render(report)
        self.assertIn('확인할 오류가 있어요',text);self.assertNotIn('<h1>검사를 통과했어요',text)
        self.assertIn('role="status">확인할 오류가 있어요',text)
        report['checks']=[{'code':'HASH','status':'pass','message':'해시 일치'}]
        report['documents'][0]['validation']['officialSchemaValid']=False
        path=self.folder/'inconsistent.html';write_report(path,report)
        self.assertIn('role="status">확인할 오류가 있어요',path.read_text(encoding='utf-8'))
    def test_warnings_and_missing_checks_are_not_success(self):
        text=self.render({'passed':True,'status':'주의','checks':[{'code':'SOURCE','status':'warning','message':'원본을 비교하지 않았어요'}]})
        self.assertIn('추가 확인이 필요해요',text)
        other=self.folder/'empty.html';write_report(other,{})
        self.assertIn('검사 기록을 확인해 주세요',other.read_text(encoding='utf-8'))
    def test_escaping_and_unsafe_paths_never_create_markup_or_external_links(self):
        report=self.legacy();report['source']={'file':'<script>alert(1)</script>.xlsx'}
        report['status']='<img src=x onerror=alert(1)>'
        report['checks']=[{'code':'<svg onload=alert(1)>','status':'error','message':'<script>bad()</script>','source':'<b>원본</b>'}]
        unsafe=['../secret.xbrl','C:\\secret.xbrl','https://evil.test/a.xbrl','javascript:alert(1)','%2e%2e%2fsecret.xbrl','sub/file.xbrl','CON.xbrl']
        report['documents']=[{'file':name,'company':'<script>x</script>'} for name in unsafe]
        report['rowMap']='//evil.test/data.jsonl'
        text=self.render(report);parser=Tags();parser.feed(text)
        self.assertNotIn('script',parser.tags);self.assertNotIn('img',parser.tags);self.assertNotIn('svg',parser.tags)
        self.assertTrue(all(link not in unsafe for link in parser.links));self.assertIn('&lt;script&gt;bad()&lt;/script&gt;',text)
    def test_reinspection_saved_elsewhere_has_no_misleading_file_links(self):
        report={'passed':True,'status':'재검사 완료','documents':[{'file':'journal-001.xbrl','rows':3,'schemaValid':True}],
                'checks':[{'code':'XSD','status':'pass','message':'스키마 일치'}]}
        text=self.render(report);parser=Tags();parser.feed(text)
        self.assertEqual(parser.links,[]);self.assertIn('링크를 생략했어요',text)
    def test_bs_unknown_totals_remain_unavailable_and_existing_file_is_not_overwritten(self):
        report=self.legacy();report['documents'][0].update(type='BS balances',start=None)
        report['documents'][0]['validation'].update(debitTotal=None,creditTotal=None)
        text=self.render(report)
        self.assertIn('BS 기말 표시값',text);self.assertIn('>—</td>',text)
        with self.assertRaises(FileExistsError):write_report(self.folder/'report.html',report)


if __name__=='__main__':unittest.main()
