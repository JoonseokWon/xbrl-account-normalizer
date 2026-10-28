"""Mock process contracts only: these tests never execute the official EXE."""
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from core.errors import InputError
from xbrl_filing.official_writer import validation


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class OfficialTechnicalValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bin = self.root / 'DART/Bin64'
        self.bin.mkdir(parents=True)
        self.writer = self.bin / 'IFRSEditor.exe'
        self.validator = self.bin / 'validate_only.exe'
        self.writer.write_bytes(b'synthetic writer identity; not executable')
        self.validator.write_bytes(b'synthetic validator identity; never executed')
        self.writer_hash = digest(self.writer)
        self.validator_hash = digest(self.validator)
        self.writer_info = self.metadata(self.writer)
        self.profile = {'id': validation._PROFILE_ID, 'identityStatus': 'verified-local-binary'}
        self.inputs = self.root / 'inputs'
        self.inputs.mkdir()
        self.instance = self.inputs / 'company.xbrl'
        self.instance.write_text('<xbrl xmlns:link="http://www.xbrl.org/2003/linkbase" '
                                 'xmlns:xlink="http://www.w3.org/1999/xlink">'
                                 '<link:schemaRef xlink:href="company.xsd"/></xbrl>', encoding='utf-8')
        (self.inputs / 'company.xsd').write_text(
            '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
            '<xs:import namespace="urn:test" schemaLocation="http://example.test/base.xsd"/>'
            '</xs:schema>', encoding='utf-8')
        self.cache = self.root / 'DART/Resource/Taxonomy/ifrs'
        self.host = self.cache / 'TaxonomyCache/example.test'
        self.host.mkdir(parents=True)
        (self.host / 'base.xsd').write_text(
            '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
            '<xs:include schemaLocation="common.xsd"/></xs:schema>', encoding='utf-8')
        (self.host / 'common.xsd').write_text('<schema/>', encoding='utf-8')
        # Unreachable cache contents must not be scanned or copied.
        (self.host / 'old-unused.xsd').write_text('invalid old taxonomy', encoding='utf-8')
        self.out = self.root / 'results'
        self.process_calls = []
        self.process = None
        self.mode = 'valid'
        self.exit_code = 0
        self.mutate = None
        self.identity_patch = patch.object(validation, 'inspect_writer', side_effect=self.metadata)
        self.profile_patch = patch.object(validation, 'profile_for_writer', side_effect=self.profile_for)
        self.pin_patch = patch.dict(validation._VALIDATOR_IDENTITY,
                                    sha256=self.validator_hash, bytes=self.validator.stat().st_size)
        self.process_patch = patch.object(validation.subprocess, 'Popen', side_effect=self.spawn)
        self.identity_patch.start()
        self.profile_patch.start()
        self.pin_patch.start()
        self.popen = self.process_patch.start()

    def tearDown(self):
        self.process_patch.stop()
        self.pin_patch.stop()
        self.profile_patch.stop()
        self.identity_patch.stop()
        self.temp.cleanup()

    def metadata(self, path):
        path = Path(path).resolve()
        is_writer = path.name == 'IFRSEditor.exe'
        return {'path': str(path), 'name': 'IFRS XBRL재무제표작성기' if is_writer else 'validate_only.exe',
                'version': '1.64.0.27' if is_writer else '', 'sha256': digest(path),
                'bytes': path.stat().st_size,
                'publisher': 'O=Financial Supervisory Service' if is_writer else '',
                'signatureStatus': 'Valid' if is_writer else 'NotSigned',
                'machine': '0x8664', 'peFormat': 'PE32+'}

    def profile_for(self, writer):
        if writer['sha256'] == self.writer_hash:
            return dict(self.profile)
        return {'id': None, 'identityStatus': 'unverified'}

    def spawn(self, command, **kwargs):
        self.process_calls.append((command, kwargs))
        self.assertIsInstance(command, list)
        self.assertFalse(kwargs['shell'])
        self.assertEqual(kwargs['cwd'], str(self.bin))
        self.assertEqual(command[0], str(self.validator))
        self.assertEqual(command[1], '--internetConnectivity=offline')
        self.assertEqual(command[2], '--cacheDirectory')
        self.assertEqual(command[4], '--validate')
        self.assertEqual(command[5], '--file')
        self.assertEqual(command[7], '--logfile')
        self.assertEqual(len(command), 9)
        source = Path(command[6])
        cache = Path(command[3])
        log = Path(command[8])
        self.assertNotEqual(source, self.instance)
        self.assertEqual(source.read_bytes(), self.instance.read_bytes())
        self.assertEqual((source.parent / 'company.xsd').read_bytes(), (self.inputs / 'company.xsd').read_bytes())
        self.assertTrue((cache / 'http/example.test/base.xsd').is_file())
        self.assertTrue((cache / 'http/example.test/common.xsd').is_file())
        self.assertFalse((cache / 'http/example.test/old-unused.xsd').exists())
        if b'xbrldi:explicitMember' in source.read_bytes():
            self.assertEqual((cache / 'http/www.xbrl.org/2006/xbrldi-2006.xsd').read_bytes(),
                             (self.cache / 'TaxonomyCache/www.xbrl.org/2006/xbrldi-2006.xsd').read_bytes())
        self.assertFalse(log.exists())
        self.assertNotEqual(kwargs['env']['APPDATA'], os.environ.get('APPDATA'))
        self.assertEqual(kwargs['env']['APPDATA'], kwargs['env']['TEMP'])
        if self.mode == 'malformed':
            log.write_text('{invalid', encoding='utf-8')
        elif self.mode != 'missing':
            entry = {'code': 'info', 'level': 'info', 'message': {'text': 'validated in 0.10 secs'},
                     'refs': [{'href': str(source)}]}
            if self.mode == 'loaded-only':
                entry['message']['text'] = 'loaded in 0.10 secs'
            if self.mode == 'rendered-completion':
                entry['message']['text'] = f'[info] validated in 36.70 secs - {source} '
            if self.mode == 'different-instance-completion':
                entry['message']['text'] = f'[info] validated in 36.70 secs - {source.parent / "other.xbrl"} '
            if self.mode == 'reported-errors':
                entry['level'] = 'error'
            log.write_text(json.dumps({'log': [] if self.mode == 'empty' else [entry]}), encoding='utf-8')
            if self.mode == 'stale':
                os.utime(log, (1, 1))
        if self.mode == 'stderr':
            kwargs['stderr'].write(b'synthetic failure')
            kwargs['stderr'].flush()
        if self.mutate:
            self.mutate(source, cache)
        self.process = SimpleNamespace(pid=987654321, returncode=self.exit_code,
                                       wait=Mock(return_value=self.exit_code), kill=Mock())
        if self.mode == 'timeout':
            self.process.wait.side_effect = subprocess.TimeoutExpired(command, 0.25)
        return self.process

    def run_validation(self):
        path = validation.run_official_validation(self.writer_info, self.instance, self.cache, self.out)
        self.assertEqual(path.name, 'report.json')
        return path, json.loads(path.read_text(encoding='utf-8'))

    def test_exact_cli_snapshots_reachable_cache_and_never_claims_submission(self):
        originals = {path: digest(path) for path in [self.instance, self.inputs / 'company.xsd',
                                                    self.host / 'base.xsd', self.host / 'common.xsd']}
        path, result = self.run_validation()
        self.assertEqual(result['technicalValidation'], 'pass')
        self.assertEqual(result['cache']['reachableFileCount'], 2)
        self.assertFalse(result['cache']['sourceModified'])
        self.assertTrue(all(result['checks'].values()))
        for key in ('officialGenerated', 'validationPassed', 'finalSubmission'):
            self.assertFalse(result[key])
        for original, expected in originals.items():
            self.assertEqual(digest(original), expected)
        names = {item.name for item in path.parent.iterdir()}
        self.assertEqual(names, {'report.json', 'technical-log.json', 'stdout.txt', 'stderr.txt'})
        self.assertFalse(Path(self.process_calls[0][0][6]).exists())
        self.assertFalse(any(item.name.startswith('.official-validation-') for item in self.out.iterdir()))

    def test_zero_exit_without_fresh_complete_valid_log_is_unknown(self):
        for mode in ('missing', 'malformed', 'empty', 'loaded-only', 'stale', 'different-instance-completion'):
            with self.subTest(mode=mode):
                self.mode = mode
                _, result = self.run_validation()
                self.assertEqual(result['technicalValidation'], 'unknown')
                self.assertFalse(result['validationPassed'])

    def test_nonzero_stderr_and_log_errors_are_errors(self):
        for mode, exit_code in (('valid', 2), ('stderr', 0), ('reported-errors', 0)):
            with self.subTest(mode=mode):
                self.mode = mode
                self.exit_code = exit_code
                _, result = self.run_validation()
                self.assertEqual(result['technicalValidation'], 'error')
                self.assertTrue(result['errors'])

    def test_timeout_is_bounded_and_terminates_only_spawned_process(self):
        self.mode = 'timeout'
        with patch.object(validation, 'VALIDATION_TIMEOUT_SECONDS', 1000), \
             patch.object(validation.time, 'monotonic', side_effect=[0, 601]), \
             patch.object(validation, '_terminate') as terminate:
            _, result = self.run_validation()
        self.assertEqual(result['technicalValidation'], 'error')
        self.assertTrue(result['execution']['timedOut'])
        self.assertEqual(result['execution']['timeoutSeconds'], 600)
        terminate.assert_called_once_with(self.process)

    def test_original_snapshot_and_program_changes_invalidate_success(self):
        mutations = [lambda source, cache: self.instance.write_text('<changed/>', encoding='utf-8'),
                     lambda source, cache: source.write_text('<changed/>', encoding='utf-8'),
                     lambda source, cache: (self.host / 'common.xsd').write_text('<changed/>', encoding='utf-8'),
                     lambda source, cache: self.validator.write_bytes(b'changed validator')]
        # Each mutation is tested with a newly reconstructed setUp fixture.
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                saved = {path: path.read_bytes() for path in (self.instance, self.host / 'common.xsd', self.validator)}
                self.mutate = mutation
                _, result = self.run_validation()
                self.assertEqual(result['technicalValidation'], 'error')
                self.assertTrue(result['errors'])
                for path, data in saved.items():
                    path.write_bytes(data)
        self.mutate = None

    def test_unrecognized_validator_or_writer_is_never_launched(self):
        self.validator.write_bytes(b'different unsigned file')
        with self.assertRaises(InputError):
            self.run_validation()
        self.popen.assert_not_called()
        self.validator.write_bytes(b'synthetic validator identity; never executed')
        self.writer.write_bytes(b'different writer')
        with self.assertRaises(InputError):
            self.run_validation()
        self.popen.assert_not_called()

    def test_dtd_absolute_reference_and_budget_fail_before_launch(self):
        original = self.instance.read_bytes()
        for xml in ('<!DOCTYPE xbrl SYSTEM "https://example.invalid/secret.dtd"><xbrl/>',
                    '<schema schemaLocation="file:///outside/schema.xsd"/>'):
            self.instance.write_text(xml, encoding='utf-8')
            _, result = self.run_validation()
            self.assertEqual(result['technicalValidation'], 'error')
            self.popen.assert_not_called()
        self.instance.write_bytes(original)
        with patch.object(validation, 'MAX_SOURCE_FILES', 1):
            _, result = self.run_validation()
            self.assertEqual(result['technicalValidation'], 'error')
            self.popen.assert_not_called()

    def test_process_start_failure_produces_error_report(self):
        self.popen.side_effect = OSError('synthetic start failure')
        _, result = self.run_validation()
        self.assertEqual(result['technicalValidation'], 'error')
        self.assertTrue(result['checks']['sourceUnchanged'])
        self.assertTrue(result['errors'])

    def test_leading_xml_comments_at_document_root_do_not_break_stream_cleanup(self):
        for path in (self.instance, self.inputs / 'company.xsd', self.host / 'base.xsd'):
            path.write_bytes(b'<!-- leading document comment -->\n' + path.read_bytes())
        _, result = self.run_validation()
        self.assertEqual(result['technicalValidation'], 'pass')
        self.assertTrue(result['checks']['sourceUnchanged'])
        self.popen.assert_called_once()

    def test_official_rendered_completion_matches_structured_instance_reference(self):
        self.mode = 'rendered-completion'
        _, result = self.run_validation()
        self.assertEqual(result['technicalValidation'], 'pass')
        self.assertTrue(result['checks']['completionInformation'])

    def test_xbrldi_namespace_adds_only_observed_implicit_schema_and_hashes_it(self):
        self.instance.write_text(
            '<xbrl xmlns:link="http://www.xbrl.org/2003/linkbase" '
            'xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:xbrldi="http://xbrl.org/2006/xbrldi">'
            '<link:schemaRef xlink:href="company.xsd"/>'
            '<xbrldi:explicitMember dimension="synthetic:Axis">synthetic:Member</xbrldi:explicitMember>'
            '</xbrl>', encoding='utf-8')
        implicit = self.cache / 'TaxonomyCache/www.xbrl.org/2006/xbrldi-2006.xsd'
        implicit.parent.mkdir(parents=True)
        implicit.write_text('<schema/>', encoding='utf-8')
        before = digest(implicit)
        _, result = self.run_validation()
        self.assertEqual(result['technicalValidation'], 'pass')
        self.assertEqual(result['cache']['reachableFileCount'], 3)
        record = next(item for item in result['sources'] if item['path'] == str(implicit))
        self.assertEqual(record['sha256'], before)
        self.assertEqual(digest(implicit), before)


if __name__ == '__main__':
    unittest.main()
