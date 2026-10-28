"""Native launch argument and UI state contracts; no official output certification."""
from copy import deepcopy
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.errors import InputError
from xbrl_filing.official_writer import launch


def writer():
    return {'path': r'C:\DART\Bin64\IFRSEditor.exe', 'name': 'IFRS XBRL재무제표작성기',
            'version': '1.64.0.27', 'bytes': 163752,
            'sha256': '1d9e293d31a3f4f11db35ecc4f9622ee65a56273e735e1cabc7e3d454c489e57',
            'publisher': 'CN=Financial Supervisory Service, O=Financial Supervisory Service, C=KR',
            'signatureStatus': 'Valid'}


def needs_elevation():
    error = OSError('elevation required');error.winerror = 740;return error


class OfficialWriterLaunchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory();self.root = Path(self.temporary.name)
        self.metadata = writer();self.inspection = patch.object(launch, 'inspect_writer', return_value=deepcopy(self.metadata))
        self.inspection.start()
    def tearDown(self):self.inspection.stop();self.temporary.cleanup()

    def test_native_argv_preserves_literal_document_and_official_working_directory(self):
        document = self.root/'공시 문서 ;$(whoami).ixd';document.write_bytes(b'editor document fixture')
        process = SimpleNamespace(pid=4123)
        with patch.object(launch.subprocess, 'Popen', return_value=process) as popen:
            result = launch.launch_editor(self.metadata, document)
        args, options = popen.call_args
        self.assertEqual(args[0], [self.metadata['path'], str(document.resolve())])
        self.assertFalse(options['shell']);self.assertEqual(options['cwd'], str(Path(self.metadata['path']).parent))
        self.assertEqual(result['pid'], 4123);self.assertEqual(result['document'], str(document.resolve()))
        self.assertFalse(result['officialGenerated']);self.assertFalse(result['validationPassed'])
        self.assertFalse(result['elevated']);self.assertFalse(result['elevationRequested'])

    def test_only_one_explicit_ixd_argument_is_supported(self):
        document = self.root/'report.xbrl';document.write_bytes(b'<xbrl/>')
        with patch.object(launch.subprocess, 'Popen') as popen:
            with self.assertRaisesRegex(InputError, '.ixd'):launch.launch_editor(self.metadata, document)
            with self.assertRaises(InputError):launch.launch_editor(self.metadata, self.root/'missing.ixd')
            popen.assert_not_called()

    def test_name_matching_unsigned_or_changed_binary_is_not_launched(self):
        for change in ({'signatureStatus': 'NotSigned'}, {'sha256': '0'*64}, {'version': 'changed'}):
            with patch.object(launch, 'inspect_writer', return_value=dict(self.metadata, **change)), \
                    patch.object(launch.subprocess, 'Popen') as popen:
                with self.assertRaises(InputError):launch.launch_editor(self.metadata)
                popen.assert_not_called()

    def test_prelaunch_second_inspection_detects_update(self):
        with patch.object(launch, 'inspect_writer', side_effect=[self.metadata, dict(self.metadata, sha256='0'*64)]), \
                patch.object(launch.subprocess, 'Popen') as popen:
            with self.assertRaises(InputError):launch.launch_editor(self.metadata)
            popen.assert_not_called()

    def test_admin_requirement_does_not_request_uac_without_explicit_ui_choice(self):
        with patch.object(launch.subprocess, 'Popen', side_effect=needs_elevation()), \
                patch.object(launch, '_elevated_start') as elevated:
            with self.assertRaisesRegex(InputError, 'Windows 권한 승인'):launch.launch_editor(self.metadata)
            elevated.assert_not_called()

    def test_explicit_elevation_uses_fixed_application_document_directory_fields(self):
        document = self.root/'문서 ;$(x).ixd';document.write_bytes(b'fixture')
        with patch.object(launch.subprocess, 'Popen', side_effect=needs_elevation()), \
                patch.object(launch, '_elevated_start', return_value=5123) as elevated:
            result = launch.launch_editor(self.metadata, document, allow_elevation=True)
        elevated.assert_called_once_with(Path(self.metadata['path']), document.resolve(), Path(self.metadata['path']).parent)
        self.assertEqual(result['pid'], 5123);self.assertTrue(result['elevated']);self.assertTrue(result['elevationRequested'])

    def test_windows_uac_cancellation_is_reported_and_never_retried_silently(self):
        with patch.object(launch.subprocess, 'Popen', side_effect=needs_elevation()), \
                patch.object(launch, '_elevated_start', side_effect=InputError('Windows 권한 승인을 취소했습니다.')) as elevated:
            with self.assertRaisesRegex(InputError, '취소'):launch.launch_editor(self.metadata, allow_elevation=True)
            self.assertEqual(elevated.call_count, 1)

    def test_non_permission_launch_failure_does_not_attempt_elevation(self):
        with patch.object(launch.subprocess, 'Popen', side_effect=OSError('unavailable')), \
                patch.object(launch, '_elevated_start') as elevated:
            with self.assertRaises(InputError):launch.launch_editor(self.metadata, allow_elevation=True)
            elevated.assert_not_called()

    def test_post_launch_identity_change_keeps_pid_and_does_not_kill_process(self):
        process = SimpleNamespace(pid=6789)
        with patch.object(launch, 'inspect_writer', side_effect=[self.metadata, self.metadata, dict(self.metadata, version='updated')]), \
                patch.object(launch.subprocess, 'Popen', return_value=process):
            result = launch.launch_editor(self.metadata)
        self.assertEqual(result['pid'], 6789);self.assertEqual(result['identityAfterLaunch'], 'unverified')
        self.assertTrue(result['warnings']);self.assertFalse(result['officialGenerated'])

    def test_document_change_after_open_is_visible_without_discarding_pid(self):
        document = self.root/'report.ixd';document.write_bytes(b'before')
        def start(*args, **kwargs):document.write_bytes(b'after');return SimpleNamespace(pid=7890)
        with patch.object(launch.subprocess, 'Popen', side_effect=start):
            result = launch.launch_editor(self.metadata, document)
        self.assertEqual(result['pid'], 7890);self.assertTrue(result['warnings'])


os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    from PySide6.QtWidgets import QApplication
    from desktop.dialogs.official_writer import OfficialWriterDialog
    QT = True
except ImportError:QT = False


@unittest.skipUnless(QT, 'PySide6 required for writer dialog state tests')
class OfficialWriterDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app = QApplication.instance() or QApplication([])
    def setUp(self):
        self.report = {'entity': {'name': '검증회사'}, 'facts': [{'approved': True, 'value': '100'}]}
        self.dialog = OfficialWriterDialog(self.report, {'fingerprint': 'test'})
    def tearDown(self):
        self.dialog.set_busy(False);self.dialog.close();self.dialog.deleteLater();self.app.processEvents()

    def test_dialog_owns_snapshot_and_never_changes_parent_report(self):
        self.dialog.report['facts'][0]['value'] = 'changed'
        self.assertEqual(self.report['facts'][0]['value'], '100')

    def test_verified_writer_is_default_and_unknown_candidate_cannot_launch(self):
        unverified = dict(writer(), name='Fss.Dart.Loader', sha256='0'*64)
        self.dialog.writers_ready([unverified, writer()])
        self.assertEqual(self.dialog.selected_writer()['name'], writer()['name'])
        self.assertTrue(self.dialog.prepare_button.isEnabled())
        self.dialog.manifest_path = Path('session.json');self.dialog.writer_choice.setCurrentIndex(1)
        self.assertFalse(self.dialog.launch_button.isEnabled());self.assertFalse(self.dialog.prepare_button.isEnabled())

    def test_busy_dialog_reject_and_close_are_blocked_until_job_completes(self):
        self.dialog.show();self.app.processEvents();self.dialog.set_busy(True, '처리 중')
        self.dialog.reject();self.assertTrue(self.dialog.isVisible());self.assertFalse(self.dialog.close())
        self.assertFalse(self.dialog.close_button.isEnabled())
        self.dialog.set_busy(False);self.assertTrue(self.dialog.close())

    def test_structure_candidate_and_unperformed_checks_are_separate(self):
        self.dialog.manifest_path = Path('workspace/session.json')
        self.dialog.manifest = {'status': 'artifact-collected', 'officialGenerated': False,
                                'checks': {'reconciliation': {'status': 'not-performed'}},
                                'artifacts': [{'inspection': {'kind': 'submission-candidate'}, 'validationEvidence': {'file': 'evidence/CHKINFO.xml'}}]}
        self.dialog.render_manifest()
        self.assertIn('제출 파일 구조 후보', self.dialog.structure_status.text())
        self.assertIn('근거 파일 보관', self.dialog.technical_status.text())
        self.assertIn('미수행', self.dialog.reconciliation_status.text());self.assertIn('미확인', self.dialog.generation_status.text())

    def test_launched_pid_is_visible_even_if_session_recording_fails(self):
        self.dialog.writers_ready([writer()]);self.dialog.manifest_path = Path('workspace/session.json')
        self.dialog.run = lambda function, success, message: success(function())
        result = {'pid': 9012, 'warnings': [], 'officialGenerated': False}
        with patch('xbrl_filing.official_writer.launch.launch_editor', return_value=result), \
                patch('xbrl_filing.official_writer.session.record_launch', side_effect=InputError('원본 확인 필요')):
            self.dialog.launch()
        self.assertIn('9012', self.dialog.notice.text());self.assertIn('원본 확인 필요', self.dialog.notice.text())

    def test_switching_session_clears_previous_files_status_and_company_scope(self):
        first = {'sessionId': 'first', 'writer': writer(), 'status': 'artifact-collected', 'officialGenerated': False,
                 'sourceSnapshot': {'entity': {'name': '첫 회사'}, 'reporting': {'periodStart': '2026-01-01',
                                    'periodEnd': '2026-12-31', 'consolidation': '별도'}, 'factCount': 7},
                 'checks': {'reconciliation': {'status': 'pass'}},
                 'artifacts': [{'inspection': {'kind': 'submission-candidate'}, 'validationEvidence': {'file': 'CHKINFO.xml'}}]}
        self.dialog.session_ready((Path('first/session.json'), first))
        self.dialog.document.setText('first/editor.ixd');self.dialog.result_file.setText('first/result.ixd')
        self.dialog.validation_file.setText('first/CHKINFO.xml')
        self.dialog.last_interchange=Path('first/import');self.dialog.last_technical_validation=Path('first/technical/report.json')
        self.dialog.technical_xml_status.setText('이전 XML 기술검사 통과')
        self.assertIn('후보', self.dialog.structure_status.text());self.assertIn('근거 파일 보관', self.dialog.technical_status.text())
        second = {'sessionId': 'second', 'writer': writer(), 'status': 'prepared', 'officialGenerated': False,
                  'sourceSnapshot': {'entity': {'name': '다음 회사'}, 'reporting': {'periodStart': '2025-01-01',
                                     'periodEnd': '2025-12-31', 'consolidation': '연결'}, 'factCount': 12},
                  'checks': {'reconciliation': {'status': 'not-performed'}}, 'artifacts': []}
        self.dialog.session_ready((Path('second/session.json'), second))
        for field in (self.dialog.document, self.dialog.result_file, self.dialog.validation_file):self.assertEqual(field.text(), '')
        self.assertIn('아직 수집하지', self.dialog.structure_status.text());self.assertIn('아직 확인하지', self.dialog.technical_status.text())
        self.assertIn('미수행', self.dialog.reconciliation_status.text());self.assertIn('미확인', self.dialog.generation_status.text())
        self.assertIn('다음 회사', self.dialog.scope_summary.text());self.assertIn('연결', self.dialog.scope_summary.text())
        self.assertIn('2025-01-01~2025-12-31', self.dialog.scope_summary.text());self.assertIn('12개', self.dialog.scope_summary.text())
        self.assertNotIn('첫 회사', self.dialog.scope_summary.text());self.assertNotIn('검증회사', self.dialog.scope_summary.text())
        self.assertFalse(self.dialog.collect_button.isEnabled())
        self.assertIsNone(self.dialog.last_interchange);self.assertIsNone(self.dialog.last_technical_validation)
        self.assertIn('미수행',self.dialog.technical_xml_status.text());self.assertFalse(self.dialog.technical_report_button.isEnabled())
        self.assertFalse(self.dialog.technical_xml_button.isEnabled())

    def test_rendering_empty_artifacts_resets_previous_structure_and_technical_labels(self):
        self.dialog.manifest_path = Path('workspace/session.json')
        self.dialog.manifest = {'status': 'prepared', 'officialGenerated': False, 'checks': {}, 'artifacts': []}
        self.dialog.structure_status.setText('이전 제출 후보');self.dialog.technical_status.setText('이전 기술 로그')
        self.dialog.render_manifest()
        self.assertIn('아직 수집하지', self.dialog.structure_status.text());self.assertIn('아직 확인하지', self.dialog.technical_status.text())

    def test_technical_xml_check_dispatches_background_job_for_explicit_candidate(self):
        self.dialog.writers_ready([writer()]);self.dialog.last_interchange=Path('prepared/company')
        self.dialog.update_controls();self.assertTrue(self.dialog.technical_xml_button.isEnabled())
        report={'technicalValidation':'pass','officialGenerated':False,'validationPassed':False,'finalSubmission':False,
                'log':{'status':'no-errors','counts':{'errors':0,'warnings':2}},'warnings':[]}
        with patch('application.official_writer.validate_interchange',return_value=Path('technical/report.json')) as validate, \
                patch('application.official_writer.read_technical_report',return_value=report), \
                patch.object(self.dialog.jobs,'start') as dispatch:
            self.dialog.validate_interchange()
            self.assertTrue(self.dialog.loading);self.assertFalse(self.dialog.close_button.isEnabled());dispatch.assert_called_once()
            operation,success,failure=dispatch.call_args.args;success(operation())
        validate.assert_called_once_with(Path('prepared/company'),writer(),manifest_path=None)
        self.assertFalse(self.dialog.loading);self.assertIn('기술검사 통과',self.dialog.technical_xml_status.text())
        self.assertIn('최종 IXD 생성·전체 DART 검사 통과와 별도',self.dialog.technical_xml_status.text())
        self.assertIn('미확인',self.dialog.generation_status.text());self.assertIn('미수행',self.dialog.reconciliation_status.text())
        self.assertTrue(self.dialog.technical_report_button.isEnabled())

    def test_technical_error_and_unknown_are_not_promoted_by_zero_error_log(self):
        self.dialog.writers_ready([writer()]);self.dialog.last_interchange=Path('prepared/company')
        self.dialog.run=lambda operation,success,message: success(operation())
        for status,expected in (('error','기술검사 오류'),('unknown','판정 불가')):
            report={'technicalValidation':status,'log':{'status':'no-errors','counts':{'errors':0}},'errors':['검사 오류'],'warnings':[]}
            with patch('application.official_writer.validate_interchange',return_value=Path('technical/report.json')), \
                    patch('application.official_writer.read_technical_report',return_value=report):self.dialog.validate_interchange()
            self.assertIn(expected,self.dialog.technical_xml_status.text())
            self.assertNotIn('· 기술검사 통과',self.dialog.technical_xml_status.text());self.assertIn('미확인',self.dialog.generation_status.text())

    def test_technical_report_folder_opens_separately_from_session_folder(self):
        self.dialog.last_technical_validation=Path('technical/run/report.json')
        with patch('desktop.dialogs.official_writer.QDesktopServices.openUrl') as open_url:self.dialog.open_technical_report()
        self.assertEqual(open_url.call_args.args[0].toLocalFile(),str(Path('technical/run')).replace('\\','/'))

    def test_failed_new_technical_check_clears_stale_pass_and_report_link(self):
        self.dialog.writers_ready([writer()]);self.dialog.last_interchange=Path('prepared/company')
        self.dialog.last_technical_validation=Path('old/report.json');self.dialog.technical_xml_status.setText('이전 기술검사 통과')
        with patch.object(self.dialog.jobs,'start') as dispatch:
            self.dialog.validate_interchange();operation,success,failure=dispatch.call_args.args
            failure('검사 준비 실패','')
        self.assertIsNone(self.dialog.last_technical_validation);self.assertFalse(self.dialog.technical_report_button.isEnabled())
        self.assertIn('미수행',self.dialog.technical_xml_status.text());self.assertIn('검사 준비 실패',self.dialog.notice.text())

    def test_reconciliation_summary_displays_matches_missing_and_changes_separately(self):
        self.dialog.manifest_path=Path('session/session.json')
        self.dialog.manifest={'status':'artifact-collected','officialGenerated':False,'artifacts':[],
            'checks':{'reconciliation':{'status':'error','counts':{'matched':8,'missing':2,'changed':1}}}}
        self.dialog.render_manifest()
        self.assertIn('입력 차이 확인',self.dialog.reconciliation_status.text())
        for text in ('일치 8','누락 2','변경 1'):self.assertIn(text,self.dialog.reconciliation_status.text())
        self.assertIn('미확인',self.dialog.generation_status.text())

    def test_collect_passes_explicit_interchange_and_does_not_claim_final_generation(self):
        self.dialog.manifest_path=Path('session/session.json');self.dialog.last_interchange=Path('reviewed/import')
        self.dialog.result_file.setText('result.ixd');self.dialog.run=lambda operation,success,message:success(operation())
        manifest={'status':'artifact-collected','officialGenerated':False,'artifacts':[{'inspection':{'kind':'submission-candidate'}}],
                  'checks':{'reconciliation':{'status':'pass','counts':{'matched':9,'missing':0,'changed':0}}}}
        with patch('xbrl_filing.official_writer.session.collect_result',return_value=manifest) as collect:self.dialog.collect()
        collect.assert_called_once_with(Path('session/session.json'),'result.ixd',None,interchange_path=Path('reviewed/import'))
        self.assertIn('승인 입력 일치',self.dialog.reconciliation_status.text());self.assertIn('일치 9',self.dialog.reconciliation_status.text())
        self.assertIn('미확인',self.dialog.generation_status.text())


if __name__ == '__main__':unittest.main()
