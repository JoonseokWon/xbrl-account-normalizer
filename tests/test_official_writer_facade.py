from copy import deepcopy
from pathlib import Path
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch

from application.official_writer import writer_taxonomy,export_interchange,validate_interchange,read_technical_report
from core.errors import InputError


class WriterFacadeTests(unittest.TestCase):
    def test_unverified_binary_cannot_select_its_taxonomy(self):
        with patch('application.official_writer.inspect_writer',return_value={'path':'unknown.exe'}),patch('application.official_writer.profile_for_writer',return_value={'launchSupported':False}):
            with self.assertRaises(InputError):writer_taxonomy({'path':'unknown.exe'})

    def test_changed_taxonomy_blocks_interchange_before_any_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary)/'out'
            with patch('application.official_writer.verify_sources'),patch('application.official_writer.load_taxonomy',return_value={'fingerprint':'new'}):
                with self.assertRaises(InputError):export_interchange({'taxonomyFingerprint':'old'},{'entryPoint':'entry.xsd','fingerprint':'old'},{},folder)
            self.assertFalse(folder.exists())

    def test_partial_builder_failure_discards_only_new_staging(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary);prior=folder/'previous.ixd';prior.write_bytes(b'previous')
            report={'taxonomyFingerprint':'same','entity':{'identifier':'00123456'},'reporting':{'periodEnd':'2026-12-31'}};original=deepcopy(report)
            def bad_builder(value,catalog,settings,path):
                path.with_suffix('.xsd').write_text('<partial/>',encoding='utf-8');raise InputError('incomplete settings')
            with patch('application.official_writer.verify_sources'),patch('application.official_writer.load_taxonomy',return_value={'fingerprint':'same'}),patch('xbrl_filing.official_writer.interchange.build_interchange',side_effect=bad_builder):
                with self.assertRaises(InputError):export_interchange(report,{'entryPoint':'entry.xsd','fingerprint':'same'},{},folder)
            self.assertEqual(list(folder.iterdir()),[prior]);self.assertEqual(report,original)

    def test_interchange_filename_preserves_company_code_and_reporting_date(self):
        with tempfile.TemporaryDirectory() as temporary:
            report={'taxonomyFingerprint':'same','entity':{'identifier':'00123456'},'reporting':{'periodEnd':'2026-12-31'}}
            observed=[]
            def build(value,catalog,settings,path):observed.append(path.name);path.write_bytes(b'candidate')
            with patch('application.official_writer.verify_sources'),patch('application.official_writer.load_taxonomy',return_value={'fingerprint':'same'}), \
                    patch('xbrl_filing.official_writer.interchange.build_interchange',side_effect=build):
                folder=export_interchange(report,{'entryPoint':'entry.xsd','fingerprint':'same'},{},temporary)
            self.assertEqual(observed,['entity00123456_2026-12-31.xbrl'])
            self.assertTrue((folder/observed[0]).is_file())


class TechnicalValidationFacadeTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.root=Path(self.temporary.name)
        self.candidate=self.root/'prepared';self.candidate.mkdir();self.instance=self.candidate/'entity00123456_2026-12-31.xbrl'
        self.instance.write_bytes(b'<xbrl/>');self.schema=self.instance.with_suffix('.xsd');self.schema.write_bytes(b'<schema/>')
        self.review_path=self.instance.with_suffix('.review.json')
        self.original={'entity':{'name':'검증회사','identifier':'00123456','scheme':'urn:test:entity'},
                       'reporting':{'periodStart':'2026-01-01','periodEnd':'2026-12-31','consolidation':'별도'},
                       'inputs':[],'facts':[{'id':'f1','concept':'ifrs:Assets','value':'100','period':{'kind':'instant','instant':'2026-12-31'},
                                             'unit':'KRW','decimals':'0','source':'input:2','reviewer':'검토자','approved':True}]}
        self.review={'schema':'account-normalizer-dart-interchange/1','scope':'xbrl-interchange-candidate',
                     'officialGenerated':False,'finalSubmission':False,'taxonomyFingerprint':'a'*64,'report':deepcopy(self.original),
                     'files':{item.name:hashlib.sha256(item.read_bytes()).hexdigest() for item in (self.instance,self.schema)}}
        self.save_review();self.writer={'path':'official.exe','sha256':'b'*64,'version':'v','publisher':'p','signatureStatus':'Valid'}
        self.details={'writer':deepcopy(self.writer),'cacheRoot':str(self.root/'TaxonomyCache'),'entryPoint':'official.xsd'}
        self.report_path=self.root/'technical'/'report.json';self.report_path.parent.mkdir()
        self.report={'schema':'account-normalizer-official-technical-validation/1','technicalValidation':'pass',
                     'officialGenerated':False,'validationPassed':False,'finalSubmission':False,'log':{'status':'no-errors','counts':{'errors':0}}}
        self.report_path.write_text(json.dumps(self.report),encoding='utf-8')
    def tearDown(self):self.temporary.cleanup()
    def save_review(self):self.review_path.write_text(json.dumps(self.review),encoding='utf-8')

    def test_single_review_bound_candidate_and_installed_cache_are_passed_to_runner(self):
        with patch('application.official_writer.writer_taxonomy',return_value=self.details), \
                patch('xbrl_filing.official_writer.validation.run_official_validation',return_value=self.report_path) as runner:
            result=validate_interchange(self.candidate,self.writer)
        self.assertEqual(result,self.report_path)
        runner.assert_called_once_with(self.writer,self.instance.resolve(),self.details['cacheRoot'],self.candidate/'기술검사')
        self.assertFalse(read_technical_report(result)['officialGenerated'])

    def test_changed_companion_or_multiple_reviewed_candidates_block_before_runner(self):
        self.schema.write_bytes(b'changed')
        with patch('xbrl_filing.official_writer.validation.run_official_validation') as runner:
            with self.assertRaisesRegex(InputError,'바뀌'):validate_interchange(self.candidate,self.writer)
            runner.assert_not_called()
        self.schema.write_bytes(b'<schema/>')
        other=self.candidate/'second.xbrl';other.write_bytes(b'<xbrl/>');other.with_suffix('.xsd').write_bytes(b'<schema/>')
        other.with_suffix('.review.json').write_text('{}',encoding='utf-8')
        with patch('xbrl_filing.official_writer.validation.run_official_validation') as runner:
            with self.assertRaisesRegex(InputError,'하나'):validate_interchange(self.candidate,self.writer)
            runner.assert_not_called()

    def test_review_changed_during_execution_cannot_be_displayed_as_current_pass(self):
        def run(*args):self.review['changed']=True;self.save_review();return self.report_path
        with patch('application.official_writer.writer_taxonomy',return_value=self.details), \
                patch('xbrl_filing.official_writer.validation.run_official_validation',side_effect=run):
            with self.assertRaisesRegex(InputError,'검토 기록이 바뀌'):validate_interchange(self.instance,self.writer)

    def test_session_company_or_approved_fact_mismatch_blocks_runner(self):
        folder=self.root/'session';(folder/'input').mkdir(parents=True)
        (folder/'input/prepared_facts.json').write_text(json.dumps(self.original),encoding='utf-8')
        manifest={'sourceSnapshot':{'reference':{'mode':'xsd','fingerprint':'a'*64},
                                   'entity':self.original['entity'],'reporting':self.original['reporting']}}
        self.review['report']['facts'][0]['value']='200';self.save_review()
        with patch('xbrl_filing.official_writer.session.read_session',return_value=manifest), \
                patch('xbrl_filing.official_writer.session._verify_snapshot'), \
                patch('xbrl_filing.official_writer.validation.run_official_validation') as runner:
            with self.assertRaisesRegex(InputError,'승인 항목'):validate_interchange(self.candidate,self.writer,manifest_path=folder/'session.json')
            runner.assert_not_called()

    def test_writer_update_and_unsupported_final_result_are_not_accepted(self):
        with patch('application.official_writer.writer_taxonomy',return_value=dict(self.details,writer=dict(self.writer,sha256='c'*64))), \
                patch('xbrl_filing.official_writer.validation.run_official_validation') as runner:
            with self.assertRaisesRegex(InputError,'작성기가 바뀌'):validate_interchange(self.candidate,self.writer)
            runner.assert_not_called()
        self.report['officialGenerated']=True;self.report_path.write_text(json.dumps(self.report),encoding='utf-8')
        with self.assertRaises(InputError):read_technical_report(self.report_path)

    def test_error_unknown_and_no_errors_are_preserved_without_promotion(self):
        for status in ('pass','error','unknown'):
            with self.subTest(status=status):
                self.report['technicalValidation']=status;self.report_path.write_text(json.dumps(self.report),encoding='utf-8')
                value=read_technical_report(self.report_path)
                self.assertEqual(value['technicalValidation'],status);self.assertFalse(value['validationPassed']);self.assertFalse(value['finalSubmission'])

if __name__=='__main__':unittest.main()
