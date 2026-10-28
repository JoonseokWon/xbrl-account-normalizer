"""Workspace integrity and recovery tests; no assertion certifies DART output."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from core.errors import InputError
from xbrl_filing.official_writer import session


class OfficialWriterSessionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory();self.root = Path(self.temporary.name)
        self.source = self.root/'source.csv';self.source.write_text('account,value\nCash,100\n', encoding='utf-8')
        self.reference = self.root/'reference.xlsx';self.reference.write_bytes(b'mocked reference loader; actual hash bound')
        self.fingerprint = hashlib.sha256(self.reference.read_bytes()).hexdigest()
        self.catalog = {'entryPoint': str(self.reference), 'mode': 'dart-reference', 'fingerprint': self.fingerprint,
                        'concepts': {'ifrs:Assets': {'abstract': False, 'kind': 'monetary', 'numeric': True,
                                                    'type': 'xbrli:monetaryItemType', 'periodType': 'instant',
                                                    'substitutionGroup': 'xbrli:item'}}}
        self.report = {'schema': 'account-normalizer-filing/1', 'taxonomyFingerprint': self.fingerprint,
                       'entity': {'name': '검증회사', 'identifier': '00123456', 'scheme': 'urn:test:entity'},
                       'reporting': {'periodStart': '2026-01-01', 'periodEnd': '2026-12-31',
                                     'consolidation': '별도', 'comparativePeriods': []},
                       'inputs': [{'name': self.source.name, 'path': str(self.source),
                                   'sha256': hashlib.sha256(self.source.read_bytes()).hexdigest()}],
                       'facts': [{'id': 'f1', 'concept': 'ifrs:Assets', 'value': '100', 'unit': 'KRW',
                                  'decimals': '0', 'statement': 'BS', 'period': {'kind': 'instant', 'instant': '2026-12-31'},
                                  'dimensions': {}, 'source': 'source.csv:2', 'reviewer': '검토자', 'approved': True}]}
        self.writer = {'path': str(self.root/'IFRSEditor.exe'), 'name': 'IFRS XBRL재무제표작성기',
                       'version': '1.64.0.27', 'bytes': 163752,
                       'sha256': '1d9e293d31a3f4f11db35ecc4f9622ee65a56273e735e1cabc7e3d454c489e57',
                       'publisher': 'CN=Financial Supervisory Service, O=Financial Supervisory Service, C=KR',
                       'signatureStatus': 'Valid'}
        self.inspect_patch = patch.object(session, 'inspect_writer', return_value=deepcopy(self.writer));self.inspect_patch.start()
        self.reference_patch = patch('xbrl_filing.dart_handoff.load_reference', return_value=deepcopy(self.catalog));self.reference_patch.start()
    def tearDown(self):
        self.reference_patch.stop();self.inspect_patch.stop();self.temporary.cleanup()

    def prepare(self):return session.prepare_session(self.report, self.catalog, self.root/'results', self.writer)
    def result_file(self, name='result.ixd'):
        path = self.root/name;path.write_bytes(b'opaque writer result fixture; not a certified IXD')
        # Avoid coarse filesystem timestamp rounding on copied test fixtures.
        current = time.time_ns();os.utime(path, ns=(current, current));return path

    def use_xsd_catalog(self):
        from xbrl_filing.taxonomy import _snapshot
        entry=self.root/'dts'/'entry.xsd';entry.parent.mkdir()
        entry.write_text('<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" targetNamespace="urn:test:ifrs"/>',encoding='utf-8')
        catalog=deepcopy(self.catalog);catalog.pop('mode');catalog.update(_snapshot(entry),namespaces={'ifrs':'urn:test:ifrs'})
        catalog['concepts']['ifrs:Assets'].update(namespace='urn:test:ifrs',localName='Assets')
        self.catalog=catalog;self.report['taxonomyFingerprint']=catalog['fingerprint']
        loader=patch('xbrl_filing.taxonomy.load_taxonomy',return_value=deepcopy(catalog));loader.start();self.addCleanup(loader.stop)
        return catalog

    def reconciliation(self,status='pass'):
        return {'status':status,'scope':'approved-fact-aspects-and-exact-values-only','counts':{'expected':1,'actual':1,
                'matched':1 if status=='pass' else 0,'missing':0,'changed':1 if status=='error' else 0,'duplicates':0,'extra':0},
                'matched':[{'expected':{'id':'f1'},'actualIds':['actual1']}] if status=='pass' else [],
                'missing':[],'changed':[],'errors':[],'warnings':[],'sourceUnchanged':True,
                'officialGenerated':False,'validationPassed':False,'finalSubmission':False}

    def test_workspace_preserves_approved_inputs_and_explicit_unperformed_states(self):
        original = deepcopy(self.report);path = self.prepare();value = session.read_session(path.parent)
        self.assertEqual(self.report, original);self.assertEqual(value['status'], 'prepared')
        for name in ('input', 'work', 'output', 'evidence'):self.assertTrue((path.parent/name).is_dir())
        facts = json.loads((path.parent/'input/prepared_facts.json').read_text(encoding='utf-8'))
        self.assertEqual(facts['facts'][0]['value'], '100');self.assertTrue(facts['facts'][0]['approved'])
        self.assertEqual(value['checks']['officialImport']['status'], 'unsupported')
        self.assertFalse(value['officialGenerated']);self.assertFalse(value['validationPassed'])
        self.assertIn('자동 불러오기 형식이 아닙니다', (path.parent/'input/읽어주세요.txt').read_text(encoding='utf-8'))
        for relative, info in value['files'].items():
            self.assertEqual(hashlib.sha256((path.parent/relative).read_bytes()).hexdigest(), info['sha256'])

    def test_unapproved_or_changed_reference_blocks_preparation(self):
        self.report['facts'][0]['approved'] = False
        with self.assertRaisesRegex(InputError, '확인'):self.prepare()
        self.report['facts'][0]['approved'] = True;self.report['taxonomyFingerprint'] = '0'*64
        with self.assertRaisesRegex(InputError, '참조'):self.prepare()
        self.assertFalse((self.root/'results').exists())

    def test_writer_is_reinspected_instead_of_trusting_callers_identity(self):
        with patch.object(session, 'inspect_writer', return_value=dict(self.writer, signatureStatus='NotSigned')):
            with self.assertRaisesRegex(InputError, '공식 작성기'):self.prepare()
        with patch.object(session, 'inspect_writer', return_value=dict(self.writer, version='other')):
            with self.assertRaises(InputError):self.prepare()

    def test_launch_records_pid_without_starting_or_stopping_any_process(self):
        path = self.prepare()
        with patch('subprocess.Popen') as popen:
            value = session.record_launch(path, 43210);popen.assert_not_called()
        self.assertEqual(value['status'], 'writer-launched');self.assertEqual(value['launches'][0]['pid'], 43210)
        self.assertFalse(value['officialGenerated']);self.assertFalse(value['validationPassed'])
        for pid in (0, -1, True, '123'):
            with self.assertRaises(InputError):session.record_launch(path, pid)

    def test_source_change_records_recovery_and_allows_retry_after_restoration(self):
        path = self.prepare();original = self.source.read_bytes();self.source.write_bytes(b'changed')
        with self.assertRaises(InputError):session.record_launch(path, 123)
        failed = session.read_session(path);self.assertEqual(failed['status'], 'recovery-required')
        self.assertEqual(failed['events'][-1]['type'], 'operation-failed');self.assertEqual(failed['launches'], [])
        self.source.write_bytes(original)
        self.assertEqual(session.record_launch(path, 124)['status'], 'writer-launched')

    def test_reference_and_prepared_snapshot_changes_block_reuse(self):
        path = self.prepare();original = self.reference.read_bytes();self.reference.write_bytes(b'changed')
        with self.assertRaisesRegex(InputError, '참조'):session.record_launch(path, 123)
        self.reference.write_bytes(original);(path.parent/'input/prepared_facts.json').write_text('{}', encoding='utf-8')
        with self.assertRaisesRegex(InputError, '작업 파일'):session.record_launch(path, 123)

    def test_collect_copies_and_hashes_original_while_inspector_cannot_claim_certification(self):
        path = self.prepare();source = self.result_file();original = source.read_bytes()
        evidence = self.root/'validation.txt';evidence.write_text('manual note is not official validation', encoding='utf-8')
        observed = []
        def inspector(file):
            observed.append(file);return {'status': 'pass', 'officialGenerated': True, 'validationPassed': True}
        result = session.collect_result(path, source, evidence, inspector=inspector)
        record = result['artifacts'][0];copy = path.parent/record['file']
        self.assertEqual(copy.read_bytes(), original);self.assertEqual(source.read_bytes(), original)
        self.assertNotEqual(copy, source);self.assertEqual(observed, [copy])
        self.assertEqual(record['sha256'], hashlib.sha256(original).hexdigest())
        self.assertFalse(result['officialGenerated']);self.assertFalse(result['validationPassed'])
        self.assertFalse(record['officialGenerated']);self.assertFalse(record['validationPassed'])
        self.assertEqual(result['checks']['officialValidation']['status'], 'not-performed')
        self.assertEqual(result['checks']['reconciliation']['status'], 'not-performed')
        self.assertEqual((path.parent/record['validationEvidence']['file']).read_bytes(), evidence.read_bytes())

    def test_result_from_before_session_and_future_timestamp_are_rejected(self):
        source = self.result_file();path = self.prepare()
        # Windows birth time is also older because the file was created before prepare.
        old = session.read_session(path)['createdAtUnixNs'] - 10_000_000_000;os.utime(source, ns=(old, old))
        with self.assertRaisesRegex(InputError, '준비한 뒤'):session.collect_result(path, source, inspector=lambda p: {})
        future = time.time_ns() + 60_000_000_000;os.utime(source, ns=(future, future))
        with self.assertRaisesRegex(InputError, '준비한 뒤'):session.collect_result(path, source, inspector=lambda p: {})
        self.assertEqual(list((path.parent/'output').iterdir()), [])

    def test_inspector_failure_preserves_source_and_recovery_manifest(self):
        path = self.prepare();source = self.result_file()
        def failed(_):raise InputError('invalid structure')
        with self.assertRaisesRegex(InputError, 'invalid structure'):session.collect_result(path, source, inspector=failed)
        self.assertTrue(source.is_file());self.assertEqual(list((path.parent/'output').iterdir()), [])
        recovered = session.read_session(path)
        self.assertEqual(recovered['status'], 'recovery-required');self.assertEqual(recovered['artifacts'], [])
        result = session.collect_result(path, source, inspector=lambda p: {'status': 'unsupported'})
        self.assertEqual(result['status'], 'artifact-collected')

    def test_atomic_save_failure_keeps_previous_manifest_and_no_dangling_artifacts(self):
        path = self.prepare();source = self.result_file();before = path.read_bytes()
        with patch.object(session.os, 'replace', side_effect=OSError('storage unavailable')):
            with self.assertRaises(OSError):session.collect_result(path, source, inspector=lambda p: {})
        self.assertEqual(path.read_bytes(), before);self.assertEqual(list((path.parent/'output').iterdir()), [])
        self.assertEqual(session.read_session(path)['artifacts'], [])
        self.assertEqual(list(path.parent.glob('.session-*.tmp')), [])

    def test_manifest_path_traversal_and_unsupported_true_states_are_rejected(self):
        path = self.prepare();value = session.read_session(path)
        value['files']['../escape.txt'] = {'bytes': 1, 'sha256': '0'*64};path.write_text(json.dumps(value), encoding='utf-8')
        with self.assertRaises(InputError):session.read_session(path)
        value['files'].pop('../escape.txt');value['officialGenerated'] = True
        path.write_text(json.dumps(value), encoding='utf-8')
        with self.assertRaises(InputError):session.read_session(path)

    def test_crash_leftover_lock_file_does_not_block_reopening(self):
        path = self.prepare();(path.parent/'.session.lock').write_bytes(b'0')
        self.assertEqual(session.record_launch(path, 123)['status'], 'writer-launched')

    def test_xsd_collection_stores_full_reconciliation_and_summary_without_certifying_generation(self):
        catalog=self.use_xsd_catalog();path=self.prepare();source=self.result_file();observed=[]
        def reconcile(expected,actual_catalog,result):
            observed.append((expected,actual_catalog,result));return self.reconciliation()
        result=session.collect_result(path,source,inspector=lambda p:{'kind':'submission-candidate'},reconciler=reconcile)
        record=result['artifacts'][0];summary=record['inputReconciliation'];report=path.parent/summary['reportFile']
        self.assertEqual(observed[0][0]['facts'][0]['value'],'100');self.assertEqual(observed[0][1]['fingerprint'],catalog['fingerprint'])
        self.assertEqual(observed[0][2],path.parent/record['file'])
        self.assertEqual(summary['status'],'pass');self.assertEqual(result['checks']['reconciliation']['counts']['matched'],1)
        self.assertEqual(json.loads(report.read_text(encoding='utf-8'))['matched'][0]['actualIds'],['actual1'])
        self.assertEqual(hashlib.sha256(report.read_bytes()).hexdigest(),summary['reportSha256'])
        self.assertIn(summary['reportFile'],result['files']);self.assertFalse(result['officialGenerated']);self.assertFalse(result['validationPassed'])

    def test_reconciliation_error_unknown_and_excel_reference_never_become_pass(self):
        path=self.prepare();source=self.result_file()
        result=session.collect_result(path,source,inspector=lambda p:{},reconciler=lambda *args:self.reconciliation())
        self.assertEqual(result['checks']['reconciliation']['status'],'not-performed')
        self.use_xsd_catalog();path=self.prepare()
        for status in ('error','unknown'):
            source=self.result_file(status+'.ixd')
            result=session.collect_result(path,source,inspector=lambda p:{},reconciler=lambda *args:self.reconciliation(status))
            self.assertEqual(result['checks']['reconciliation']['status'],status)
            self.assertFalse(result['officialGenerated']);self.assertFalse(result['validationPassed'])

    def test_review_bound_interchange_is_preferred_and_approval_evidence_is_preserved(self):
        self.use_xsd_catalog();path=self.prepare();source=self.result_file();candidate=self.root/'import';candidate.mkdir()
        instance=candidate/'entity00123456_2026-12-31.xbrl';instance.write_bytes(b'<xbrl/>')
        schema=instance.with_suffix('.xsd');schema.write_bytes(b'<schema/>')
        prepared=json.loads((path.parent/'input/prepared_facts.json').read_text(encoding='utf-8'))
        prepared['facts'][0]['dimensions']={'ifrs:ScopeAxis':'ifrs:SeparateMember'}
        extra=deepcopy(prepared['facts'][0]);extra.update(id='gcd1',value='2025-01-01');prepared['facts'].append(extra)
        review={'schema':'account-normalizer-dart-interchange/1','scope':'xbrl-interchange-candidate','officialGenerated':False,
                'finalSubmission':False,'taxonomyFingerprint':self.catalog['fingerprint'],'report':prepared,
                'files':{item.name:hashlib.sha256(item.read_bytes()).hexdigest() for item in (instance,schema)}}
        instance.with_suffix('.review.json').write_text(json.dumps(review),encoding='utf-8');observed=[]
        def reconcile(expected,catalog,result):observed.append(expected);return self.reconciliation()
        result=session.collect_result(path,source,inspector=lambda p:{},interchange_path=candidate,reconciler=reconcile)
        self.assertEqual(len(observed[0]['facts']),2);self.assertEqual(observed[0]['facts'][0]['dimensions'],{'ifrs:ScopeAxis':'ifrs:SeparateMember'})
        record=result['artifacts'][0];evidence=record['reconciliationExpectedEvidence']
        self.assertEqual(record['inputReconciliation']['expectedSource']['kind'],'reviewed-interchange')
        self.assertEqual((path.parent/evidence['file']).read_bytes(),instance.with_suffix('.review.json').read_bytes())
        self.assertIn(evidence['file'],result['files']);self.assertFalse(result['officialGenerated'])

    def test_reconciler_cannot_claim_final_flags_or_modify_collected_file(self):
        self.use_xsd_catalog();path=self.prepare();source=self.result_file()
        with self.assertRaisesRegex(InputError,'범위'):
            session.collect_result(path,source,inspector=lambda p:{},reconciler=lambda *args:dict(self.reconciliation(),officialGenerated=True))
        self.assertEqual(list((path.parent/'output').iterdir()),[])
        def mutate(expected,catalog,result):result.write_bytes(b'changed');return self.reconciliation('error')
        with self.assertRaisesRegex(InputError,'결과 파일이 바뀌'):
            session.collect_result(path,source,inspector=lambda p:{},reconciler=mutate)
        self.assertTrue(source.is_file());self.assertEqual(list((path.parent/'output').iterdir()),[])
        self.assertEqual(session.read_session(path)['artifacts'],[])


if __name__ == '__main__':unittest.main()
