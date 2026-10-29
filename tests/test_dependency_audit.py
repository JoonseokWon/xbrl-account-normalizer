from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.audit_dependencies import inventory, query_osv, run


class DependencyAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.runtime = self.root / 'runtime'; self.runtime.mkdir()
        (self.runtime / 'AccountDataNormalizer.exe').write_bytes(b'SYNTHETIC_FIXTURE')
        (self.runtime / 'licenses').mkdir()
        self.metadata = self.runtime / '_internal/demo_package-1.0.dist-info'
        self.metadata.mkdir(parents=True)
        (self.metadata / 'METADATA').write_text('Name: demo-package\nVersion: 1.0\n', encoding='utf-8')
        self.packages = [{'name': 'demo-package', 'version': '1.0'}]

    def tearDown(self): self.temp.cleanup()

    def test_offline_inventory_does_not_send_network_requests(self):
        with patch('tools.audit_dependencies.build_opener') as network:
            result = run(self.runtime, self.root / 'out')
        network.assert_not_called()
        self.assertEqual(result['status'], 'not-requested')
        bom = json.loads((self.root / 'out/software-bom.json').read_text(encoding='utf-8'))
        self.assertEqual(bom['bomFormat'], 'CycloneDX')
        self.assertEqual(bom['components'][0]['version'], '1.0')
        self.assertNotIn(str(self.runtime), json.dumps(bom))

    def test_empty_or_conflicting_package_metadata_cannot_report_a_clean_inventory(self):
        other = self.runtime / '_internal/duplicate-2.dist-info'; other.mkdir()
        (other / 'METADATA').write_text('Name: demo-package\nVersion: 2.0\n', encoding='utf-8')
        with self.assertRaises(ValueError): inventory(self.runtime)
        (self.metadata / 'METADATA').unlink(); (other / 'METADATA').unlink()
        with self.assertRaises(ValueError): inventory(self.runtime)

    def test_online_payload_is_package_metadata_only_and_follows_all_pages(self):
        class Opener:
            calls = []
            def open(inner, request, timeout):
                payload = json.loads(request.data)
                self.assertEqual(request.full_url, 'https://api.osv.dev/v1/querybatch')
                self.assertEqual(set(payload), {'queries'})
                for query in payload['queries']:
                    self.assertEqual(query['package'], {'ecosystem': 'PyPI', 'name': 'demo-package'})
                    self.assertEqual(query['version'], '1.0')
                    self.assertTrue(set(query) <= {'package', 'version', 'page_token'})
                inner.calls.append(payload)
                value = {'vulns': [{'id': 'GHSA-synthetic-test'}]}
                if len(inner.calls) == 1: value['next_page_token'] = 'next'
                return BytesIO(json.dumps({'results': [value]}).encode('utf-8'))
        opener = Opener()
        with patch('tools.audit_dependencies.build_opener', return_value=opener): result = query_osv(self.packages)
        self.assertEqual(len(opener.calls), 2)
        self.assertEqual(result[0]['ids'], ['GHSA-synthetic-test'])

    def test_network_failure_is_incomplete_instead_of_zero_findings(self):
        with patch('tools.audit_dependencies.query_osv', side_effect=OSError('PRIVATE_RAW_ERROR')):
            result = run(self.runtime, self.root / 'failed', online=True)
        self.assertEqual(result['status'], 'incomplete')
        self.assertNotIn('PRIVATE_RAW_ERROR', json.dumps(result))

    def test_malformed_server_response_cannot_become_a_clean_result(self):
        class Opener:
            def open(self, *args, **kwargs): return BytesIO(b'{"results":[]}')
        with patch('tools.audit_dependencies.build_opener', return_value=Opener()):
            with self.assertRaises(ValueError): query_osv(self.packages)


if __name__ == '__main__': unittest.main()
