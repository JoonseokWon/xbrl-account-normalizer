from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from xbrl_filing.dsd_reporting import export_dsd_review_html


class DsdHtmlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.report = {'schema': 'account-normalizer-dsd-diff/1', 'status': 'differences',
                       'rows': [{'id': 'r1', 'kind': 'value-changed', 'message': '변경',
                                 'before': {'text': '10', 'row': 2, 'column': 1},
                                 'after': {'text': '12', 'row': 2, 'column': 1}, 'difference': '2'}],
                       'sourceHashes': {}, 'warnings': [], 'errors': []}

    def tearDown(self):
        self.temp.cleanup()

    def test_standalone_csp_escaped_values_notes_and_scope(self):
        self.report['rows'][0]['after']['text'] = '<script>alert(1)</script><img src="https://bad/">'
        self.report['warnings'] = [r'C:\private\ledger.xlsx https://bad.example/info']
        result = export_dsd_review_html(self.report, self.root/'review.html', reviewer='<admin>', notes={'general': '전체 의견', 'r1': '<검토>'})
        text = (self.root/'review.html').read_text(encoding='utf-8')
        self.assertTrue('Content-Security-Policy' in text and "default-src 'none'" in text)
        self.assertNotIn('<script>', text)
        self.assertNotIn('<img', text)
        self.assertIn('&lt;script&gt;', text)
        self.assertIn('전체 의견', text)
        self.assertIn('&lt;검토&gt;', text)
        self.assertNotIn('https://bad', text)
        self.assertNotIn(r'C:\private', text)
        self.assertFalse(result['sourcesRechecked'])
        self.assertIn('재확인하지 않았습니다', text)
        self.assertFalse(result['submissionApproved'])

    def test_source_hashes_rechecked_and_changed_source_refused(self):
        source = self.root/'before.dsd'; source.write_bytes(b'original')
        self.report['sourceHashes'] = {'before': hashlib.sha256(b'original').hexdigest()}
        result = export_dsd_review_html(self.report, self.root/'ok.html', source_paths={'before': source})
        self.assertTrue(result['sourcesRechecked'])
        source.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, '변경'):
            export_dsd_review_html(self.report, self.root/'bad.html', source_paths={'before': source})
        self.assertFalse((self.root/'bad.html').exists())

    def test_existing_output_never_overwritten(self):
        target = self.root/'out.html'; target.write_text('previous')
        with self.assertRaises(FileExistsError):
            export_dsd_review_html(self.report, target)
        self.assertEqual(target.read_text(), 'previous')

    def test_existing_ixd_comparison_report_supported_without_mutation(self):
        report = {'schema': 'account-normalizer-disclosure-comparison/1', 'status': 'review',
                  'rows': [{'status': 'unmapped', 'label': '현금', 'dsdValue': '100', 'ixdValue': '',
                            'source': {'row': 1, 'column': 2}, 'dsdCellId': 'x', 'diagnostics': []}],
                  'errors': [], 'warnings': [], 'sourceHashes': {}}
        before = deepcopy(report)
        export_dsd_review_html(report, self.root/'ixd.html')
        self.assertEqual(report, before)
        self.assertIn('대응 미확인', (self.root/'ixd.html').read_text(encoding='utf-8'))

    def test_size_limit_does_not_leave_partial_file(self):
        with patch('xbrl_filing.dsd_reporting.html.MAX_HTML', 100):
            with self.assertRaises(ValueError):
                export_dsd_review_html(self.report, self.root/'huge.html')
        self.assertFalse((self.root/'huge.html').exists())


if __name__ == '__main__':
    unittest.main()
