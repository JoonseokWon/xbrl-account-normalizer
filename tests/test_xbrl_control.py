import sys,tempfile,unittest
from pathlib import Path
from threading import Event
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from application.xbrl_export import export_xbrl
from xbrl_gl.control import ExportCancelled
from workflow_fixtures import session

class XbrlControlTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name);self.session=session(self.folder,True)
    def tearDown(self):self.temp.cleanup()
    def test_progress_and_human_report(self):
        events=[];out=export_xbrl(self.session,self.folder/'out',events.append)
        self.assertEqual(events[-1]['stage'],'완료')
        self.assertTrue({'원본 확인','XML 저장','내용 확인','검사 보고서 저장'}.issubset({e['stage'] for e in events}))
        self.assertTrue((out/'검사결과.html').is_file())
    def test_cancel_before_start_leaves_no_folder(self):
        event=Event();event.set()
        with self.assertRaises(ExportCancelled):export_xbrl(self.session,self.folder/'out',cancel=event)
        self.assertFalse((self.folder/'out').exists())
    def test_cancel_during_write_and_validation_preserves_previous_results(self):
        for stage in ('XML 저장','내용 확인'):
            with self.subTest(stage=stage):
                target=self.folder/stage;target.mkdir();marker=target/'previous.txt';marker.write_text('keep',encoding='utf-8')
                event=Event()
                def progress(value):
                    if value['stage']==stage:event.set()
                with self.assertRaises(ExportCancelled):export_xbrl(self.session,target,progress,event)
                self.assertEqual(list(target.iterdir()),[marker]);self.assertEqual(marker.read_text(encoding='utf-8'),'keep')
                self.assertEqual(self.session.result['status'],'계정매핑완료')
    def test_cancel_after_commit_does_not_misreport_completed_output(self):
        event=Event()
        def progress(value):
            if value['stage']=='완료':event.set()
        output=export_xbrl(self.session,self.folder/'out',progress,event)
        self.assertTrue(event.is_set());self.assertTrue((output/'validation-report.json').is_file())

if __name__=='__main__':unittest.main()
