"""Executable identity tests do not certify writer import or DART acceptance."""
import hashlib
import json
import os
from pathlib import Path
import platform
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.errors import InputError
from xbrl_filing.official_writer import discovery, profiles


def pe_image():
    """Small structural PE fixture; real native executable coverage is below."""
    value = bytearray(1024);value[:2] = b'MZ';struct.pack_into('<I', value, 60, 128)
    value[128:132] = b'PE\0\0'
    struct.pack_into('<HH', value, 132, 0x8664, 1)
    struct.pack_into('<HH', value, 148, 240, 0x22)
    struct.pack_into('<H', value, 152, 0x20b)
    value[392:400] = b'.text\0\0\0'
    struct.pack_into('<II', value, 408, 512, 512)
    return value


def metadata(status='NotSigned'):
    return {'productName': 'IFRS XBRL재무제표작성기', 'description': 'writer', 'version': '1.64.0.27',
            'publisher': '', 'signatureStatus': status}


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory();self.root = Path(self.temporary.name)
        self.executable = self.root / 'IFRSEditor.exe';self.executable.write_bytes(pe_image())
    def tearDown(self):self.temporary.cleanup()

    def test_non_windows_is_explicit(self):
        with patch.object(discovery.platform, 'system', return_value='Linux'):
            for operation in (lambda: discovery.inspect_writer(self.executable), discovery.discover_writers):
                with self.assertRaisesRegex(InputError, 'Windows'):operation()

    def test_requires_executable_path_and_valid_pe(self):
        with patch.object(discovery.platform, 'system', return_value='Windows'), \
                patch.object(discovery, '_read_windows_metadata') as query:
            for path, content in ((self.root/'writer.txt', pe_image()), (self.root/'wrong.exe', b'not PE')):
                path.write_bytes(content)
                with self.assertRaises(InputError):discovery.inspect_writer(path)
            query.assert_not_called()

    def test_pe_header_and_section_corruption_fail_before_metadata(self):
        corruptions = []
        value = pe_image();value[128:132] = b'BAD!';corruptions.append(value)
        value = pe_image();struct.pack_into('<I', value, 60, 1020);corruptions.append(value)
        value = pe_image();struct.pack_into('<H', value, 150, 0x2022);corruptions.append(value)
        value = pe_image();struct.pack_into('<I', value, 412, 9999);corruptions.append(value)
        for value in corruptions:
            with self.subTest(header=hashlib.sha256(value).hexdigest()):
                self.executable.write_bytes(value)
                with self.assertRaises(InputError):discovery._inspect_pe(self.executable)

    def test_reads_hash_bytes_version_and_unsigned_state_without_official_claim(self):
        with patch.object(discovery.platform, 'system', return_value='Windows'), \
                patch.object(discovery, '_read_windows_metadata', return_value=metadata()):
            value = discovery.inspect_writer(self.executable)
        self.assertEqual(value['sha256'], hashlib.sha256(pe_image()).hexdigest())
        self.assertEqual((value['bytes'], value['version'], value['signatureStatus']), (1024, '1.64.0.27', 'NotSigned'))
        self.assertEqual((value['machine'], value['peFormat']), ('0x8664', 'PE32+'))
        self.assertEqual(profiles.profile_for_writer(value)['identityStatus'], 'unverified')

    def test_file_changed_during_metadata_query_is_rejected(self):
        def changed(path):
            path.write_bytes(path.read_bytes() + b'changed');return metadata()
        with patch.object(discovery.platform, 'system', return_value='Windows'), \
                patch.object(discovery, '_read_windows_metadata', side_effect=changed):
            with self.assertRaisesRegex(InputError, '바뀌었'):discovery.inspect_writer(self.executable)

    def test_powershell_receives_path_in_environment_with_no_shell(self):
        path = self.root / 'a;$(whoami).exe'
        response = SimpleNamespace(returncode=0, stdout=json.dumps(metadata(), ensure_ascii=False))
        with patch.object(discovery, '_powershell_path', return_value=Path('trusted-system-powershell.exe')), \
                patch.object(discovery.subprocess, 'run', return_value=response) as run:
            result = discovery._read_windows_metadata(path)
        args, options = run.call_args
        self.assertFalse(options['shell']);self.assertEqual(options['timeout'], 20)
        self.assertEqual(options['env']['ACCOUNT_NORMALIZER_INSPECT_EXE'], str(path))
        self.assertNotIn(str(path), args[0][-1]);self.assertNotIn('PSModulePath', options['env'])
        self.assertEqual(result['signatureStatus'], 'NotSigned')

    def test_failed_or_unknown_signature_query_is_never_passed(self):
        responses = [SimpleNamespace(returncode=1, stdout=''), SimpleNamespace(returncode=0, stdout='not JSON'),
                     SimpleNamespace(returncode=0, stdout=json.dumps(dict(metadata(), signatureStatus='Pass')))]
        with patch.object(discovery, '_powershell_path', return_value=Path('powershell.exe')):
            for response in responses:
                with patch.object(discovery.subprocess, 'run', return_value=response), self.assertRaises(InputError):
                    discovery._read_windows_metadata(self.executable)
            with patch.object(discovery.subprocess, 'run', side_effect=subprocess.TimeoutExpired('powershell', 20)), \
                    self.assertRaises(InputError):discovery._read_windows_metadata(self.executable)

    def test_icon_parser_accepts_only_path_and_optional_resource_index(self):
        self.assertEqual(discovery._registry_exe('"'+str(self.executable)+'",0'), self.executable)
        for text in (str(self.executable)+' --other', '"'+str(self.executable)+'"; evil.exe', 'relative.exe'):
            self.assertIsNone(discovery._registry_exe(text))

    def test_registry_and_limited_folder_discovery_deduplicate_and_skip_corruption(self):
        (self.root/'Bin64').mkdir();nested = self.root/'Bin64'/'DARTXBRL.exe';nested.write_bytes(pe_image())
        bad = self.root/'invalidXBRL.exe';bad.write_text('bad')
        with patch.object(discovery.platform, 'system', return_value='Windows'), \
                patch.object(discovery, '_powershell_path', return_value=Path('powershell.exe')), \
                patch.object(discovery, '_registry_candidates', return_value=([self.executable,self.executable,bad], [self.root])), \
                patch.object(discovery, '_known_folders', return_value=[self.root]), \
                patch.object(discovery, '_read_windows_metadata', return_value=metadata()):
            result = discovery.discover_writers()
        self.assertEqual({Path(item['path']) for item in result}, {self.executable, nested})
        self.assertEqual(len(result), 2)

    def test_folder_scan_excludes_installers_and_does_not_recurse_beyond_two_levels(self):
        deep = self.root/'one'/'two'/'three';deep.mkdir(parents=True)
        (deep/'IFRSEditor.exe').write_bytes(pe_image())
        (self.root/'XBRLSetup.exe').write_bytes(pe_image())
        self.assertEqual(list(discovery._folder_candidates([self.root])), [self.executable])

    @unittest.skipUnless(platform.system() == 'Windows', 'native Windows PE fixture')
    def test_real_python_executable_pe_headers(self):
        result = discovery._inspect_pe(Path(sys.executable))
        self.assertIn(result['peFormat'], ('PE32', 'PE32+'))
        self.assertRegex(result['machine'], '^0x[0-9a-f]{4}$')

    @unittest.skipUnless(platform.system() == 'Windows', 'native Windows metadata integration')
    def test_real_windows_executable_metadata_and_signature(self):
        executable = Path(os.environ.get('SystemRoot', r'C:\Windows'))/'System32'/'cmd.exe'
        result = discovery.inspect_writer(executable)
        self.assertTrue(result['version']);self.assertEqual(result['signatureStatus'], 'Valid')
        self.assertEqual(result['bytes'], executable.stat().st_size)
        self.assertEqual(result['sha256'], hashlib.sha256(executable.read_bytes()).hexdigest())
        self.assertEqual(profiles.profile_for_writer(result)['identityStatus'], 'unverified')


class ProfileTests(unittest.TestCase):
    def identity(self):
        return {'name': 'IFRS XBRL재무제표작성기', 'version': '1.64.0.27',
                'sha256': '1d9e293d31a3f4f11db35ecc4f9622ee65a56273e735e1cabc7e3d454c489e57',
                'publisher': 'CN=Financial Supervisory Service, O=Financial Supervisory Service, C=KR',
                'signatureStatus': 'Valid'}

    def test_exact_observed_identity_enables_launch_but_no_unverified_format(self):
        result = profiles.profile_for_writer(self.identity())
        self.assertEqual(result['identityStatus'], 'verified-local-binary');self.assertTrue(result['launchSupported'])
        self.assertFalse(result['automatedImportSupported']);self.assertFalse(result['finalSubmissionSupported'])
        self.assertEqual(result['submissionFormats'], [])
        self.assertEqual(result['sourceFormats'][0]['role'], 'editor-source')

    def test_name_or_publisher_alone_cannot_claim_official_identity(self):
        for key, change in (('sha256', '0'*64), ('version', '9.01'), ('name', 'IFRSEditor.exe'),
                            ('signatureStatus', 'NotTrusted'), ('publisher', 'CN=O=Financial Supervisory Service')):
            with self.subTest(key=key):
                value = dict(self.identity(), **{key: change})
                self.assertEqual(profiles.profile_for_writer(value)['identityStatus'], 'unverified')
                self.assertFalse(profiles.profile_for_writer(value)['launchSupported'])

    def test_profile_return_values_cannot_mutate_verified_definition(self):
        result = profiles.profile_for_writer(self.identity());result['sourceFormats'].clear()
        self.assertEqual(len(profiles.profile_for_writer(self.identity())['sourceFormats']), 1)


if __name__ == '__main__':unittest.main()
