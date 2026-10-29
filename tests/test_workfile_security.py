"""Portable work imports cannot select files outside their embedded originals."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

from application.workfiles import save_work, load_work
from application.support_preparation import prepare_support
from core.errors import InputError
from workflow_fixtures import session, support_config


class WorkfileSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.session = session(self.root)
        source = save_work(self.session, self.root / 'legit.acwork')
        with ZipFile(source) as archive: self.entries = {n: archive.read(n) for n in archive.namelist()}
        self.data = json.loads(self.entries['manifest.json'])
        self.cache = patch('application.workfiles.user_data', return_value=self.root / 'cache'); self.cache.start()

    def tearDown(self):
        self.cache.stop(); self.temp.cleanup()

    def work(self, data=None, raw=None, special=None):
        entries = dict(self.entries)
        entries['manifest.json'] = raw if raw is not None else json.dumps(data if data is not None else self.data, ensure_ascii=False).encode('utf-8')
        path = self.root / 'untrusted.acwork'
        with ZipFile(path, 'w', ZIP_DEFLATED) as archive:
            for name, value in entries.items(): archive.writestr(special if special is not None and name == special.filename else name, value)
        return path

    def blocked_before_input_read(self, path):
        with patch('application.workfiles.load_batch') as loader, patch('application.support_preparation.prepare_support') as support:
            with self.assertRaises(InputError): load_work(path)
            loader.assert_not_called(); support.assert_not_called()
        self.assertFalse((self.root / 'cache').exists())

    def test_external_absolute_unc_url_and_relative_support_paths_are_rejected_before_io(self):
        for source in ('C:/outside/private.csv', '//server/share/private.csv', 'file:///C:/private.csv',
                       'https://example.invalid/private.csv', '../outside.csv', 'inputs/001.csv'):
            with self.subTest(source=source):
                data = deepcopy(self.data)
                data['supportSetup'] = {'tables': {'시산표': {'path': source}}}
                self.blocked_before_input_read(self.work(data))

    def test_legitimate_embedded_support_reopens_after_originals_are_removed(self):
        config = support_config(self.root)
        self.session.support_setup = config
        self.session.support_bundle = prepare_support(config)
        source = save_work(self.session, self.root / 'supported.acwork')
        for spec in config['tables'].values(): Path(spec['path']).unlink()
        reopened = load_work(source)
        try:
            self.assertEqual(len(reopened.support_bundle.tables['시산표']), 3)
            self.assertTrue(all(Path(spec['path']).is_relative_to(Path(reopened._restored_temp.name))
                                for spec in reopened.support_setup['tables'].values()))
        finally: reopened._restored_temp.cleanup()

    def test_attached_support_cannot_be_swapped_for_another_table_or_local_path(self):
        config = support_config(self.root)
        self.session.support_setup = config; self.session.support_bundle = prepare_support(config)
        source = save_work(self.session, self.root / 'supported.acwork')
        with ZipFile(source) as archive: self.entries = {n: archive.read(n) for n in archive.namelist()}
        data = json.loads(self.entries['manifest.json'])
        data['supportSetup']['tables']['시산표']['path'] = data['supportSetup']['tables']['독립통제']['path']
        self.blocked_before_input_read(self.work(data))

    def test_duplicate_table_attachment_names_are_rejected(self):
        config = support_config(self.root)
        self.session.support_setup = config; self.session.support_bundle = prepare_support(config)
        source = save_work(self.session, self.root / 'supported.acwork')
        with ZipFile(source) as archive: self.entries = {n: archive.read(n) for n in archive.namelist()}
        data = json.loads(self.entries['manifest.json'])
        data['supportInputs'][1]['table'] = data['supportInputs'][0]['table']
        self.blocked_before_input_read(self.work(data))

    def test_reserved_device_path_ads_and_extension_mismatch_names_are_rejected(self):
        for name in ('NUL.csv', 'con.csv', 'COM1.csv', 'LPT².csv', '..', '../outside.csv',
                     'input.csv:secret', 'input.csv ', 'input.csv.', 'input.xlsx', 'nul\x00.csv'):
            with self.subTest(name=name):
                data = deepcopy(self.data); data['inputs'][0]['name'] = name
                self.blocked_before_input_read(self.work(data))

    def test_json_duplicate_keys_nonfinite_root_types_and_deep_nesting_fail_closed(self):
        base = json.dumps(self.data)
        duplicate = '{"schema":"account-normalizer-work/1",' + base[1:]
        bad_values = [duplicate, '[]', 'null', base[:-1] + ',"extra":NaN}', base[:-1] + ',"extra":1e10000}', base[:-1] + ',"extra":' + '[' * 35 + '0' + ']' * 35 + '}']
        for raw in bad_values:
            with self.subTest(raw=raw[:40]): self.blocked_before_input_read(self.work(raw=raw.encode('utf-8')))

    def test_symlink_zip_member_is_rejected_before_reading_any_source(self):
        entry = self.data['inputs'][0]['entry']
        special = ZipInfo(entry); special.create_system = 3; special.external_attr = 0o120777 << 16
        self.blocked_before_input_read(self.work(special=special))

    def test_per_attachment_size_and_invalid_hash_format_are_checked_before_io(self):
        with patch('application.workfile_guard.MAX_FILE_BYTES', 1): self.blocked_before_input_read(self.work())
        data = deepcopy(self.data); data['inputs'][0]['sha256'] = 'invalid'
        self.blocked_before_input_read(self.work(data))

    def test_changed_oversized_source_cannot_replace_an_existing_saved_work(self):
        target = self.root / 'legit.acwork'; before = target.read_bytes()
        with patch('application.workfiles.MAX_FILE_BYTES', 1):
            with self.assertRaises(InputError): save_work(self.session, target)
        self.assertEqual(target.read_bytes(), before)

    def test_filing_source_references_cannot_probe_network_or_device_paths(self):
        from application.filing import verify_sources
        for source in ('\\\\server\\share\\private.xlsx', '//server/share/private.xlsx',
                       '\\\\?\\UNC\\server\\share\\private.xlsx', 'file://server/private.xlsx',
                       'https://example.invalid/private.xlsx', 'smb://server/private.xlsx'):
            with self.subTest(source=source), patch.object(Path, 'is_file', side_effect=AssertionError('metadata must not probe network')):
                with self.assertRaises(InputError): verify_sources({'inputs': [{'path': source, 'name': 'private.xlsx', 'sha256': '0' * 64}]})


if __name__ == '__main__': unittest.main()
