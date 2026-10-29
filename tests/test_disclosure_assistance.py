"""Document context, explainable candidates and non-permissive diagnostics."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from xbrl_filing.disclosure_compare import compare_disclosures, inspect_disclosures
from xbrl_filing.disclosure_compare.dsd import read_dsd
from xbrl_filing.disclosure_compare.diagnostics import numeric_diagnostics
from xbrl_filing.disclosure_compare.examples import create_comparison_example
from xbrl_filing.disclosure_compare.suggestions import suggest_correspondences


class DisclosureAssistanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.sample = create_comparison_example(self.root)
        self.inspection = inspect_disclosures(self.sample['dsd'], self.sample['ixd'])
        self.cell = next(c for c in self.inspection['dsd']['cells'] if c['text'] == '1,234')

    def tearDown(self):
        self.temp.cleanup()

    def codes(self, raw, actual, scale):
        return [item['code'] for item in numeric_diagnostics(raw, actual, scale)]

    def test_merged_column_paths_and_spanning_row_labels_survive(self):
        path = self.root / 'context.xml'
        path.write_text('<DOCUMENT><TABLE><THEAD>'
            '<TR><TH ROWSPAN="2">자산</TH><TH ROWSPAN="2">구분</TH><TH COLSPAN="2">2025년</TH><TH>2024년</TH></TR>'
            '<TR><TH>기초</TH><TH>기말</TH><TH>기말</TH></TR></THEAD>'
            '<TR><TD ROWSPAN="2">무형자산</TD><TD>소프트웨어</TD><TD>1</TD><TD>2</TD><TD>3</TD></TR>'
            '<TR><TD>개발비</TD><TD>4</TD><TD>5</TD><TD>6</TD></TR></TABLE></DOCUMENT>', encoding='utf-8')
        cells = read_dsd(path)['cells']
        cell = next(c for c in cells if c['text'] == '5')
        self.assertEqual(cell['columnHeaders'], ['2025년', '기말'])
        self.assertEqual(cell['columnHeaderPath'], '2025년 / 기말')
        self.assertEqual(cell['rowHeaders'], ['무형자산', '개발비'])
        self.assertEqual(cell['label'], '무형자산 / 개발비')
        self.assertNotIn('소프트웨어', cell['label'])

    def test_equal_number_candidates_remain_unapproved_and_input_unchanged(self):
        before = deepcopy(self.inspection)
        result = suggest_correspondences(self.inspection, self.cell['id'], scale='1000')
        self.assertEqual(result['candidates'][0]['ixdFactId'], 'cash-current')
        self.assertFalse(result['approved'])
        self.assertFalse(result['candidates'][0]['approved'])
        self.assertIn('이름 근거가 약해요', result['candidates'][0]['warnings'][0])
        self.assertEqual(result['sourceHashes'], self.inspection['sourceHashes'])
        self.assertEqual(self.inspection, before)

    def test_long_header_context_is_shared_and_bounded_without_truncating_original(self):
        path = self.root / 'long-header.xml'
        long_text = '주석' * 1500
        path.write_text('<DOCUMENT><TABLE><TR><TH>구분</TH><TH>' + long_text + '</TH></TR>' +
                        ''.join(f'<TR><TD>항목</TD><TD>{i}</TD></TR>' for i in range(200)) +
                        '</TABLE></DOCUMENT>', encoding='utf-8')
        cells = read_dsd(path)['cells']
        self.assertEqual(next(c for c in cells if c['isHeader'] and c['source']['column'] == 2)['text'], long_text)
        numbers = [c for c in cells if c['number'] is not None]
        self.assertEqual(len(numbers), 200)
        self.assertLessEqual(len(numbers[0]['columnHeaderPath']), 600)
        self.assertEqual(len(numbers[0]['columnHeaders'][0]), 2000)
        self.assertIs(numbers[0]['columnHeaders'][0], numbers[-1]['columnHeaders'][0])
        self.assertIs(numbers[0]['columnHeaderPath'], numbers[-1]['columnHeaderPath'])

    def test_local_taxonomy_uses_expanded_qname_not_prefix(self):
        namespace = self.inspection['ixd']['facts'][0]['concept'].split('}')[0][1:]
        catalog = {'fingerprint': 'local-catalog', 'concepts': {'differentPrefix:Cash': {
            'namespace': namespace, 'localName': 'Cash', 'label': '현금및현금성자산'}}}
        # Change the value so the recommendation must rest on the actual label.
        self.cell['number'] = '999'
        result = suggest_correspondences(self.inspection, self.cell['id'], scale='1000', catalog=catalog)
        self.assertEqual(result['candidates'][0]['ixdFactId'], 'cash-current')
        self.assertEqual(result['candidates'][0]['label'], '현금및현금성자산')
        self.assertEqual(result['taxonomyFingerprint'], 'local-catalog')
        self.assertTrue(any('숫자가 달라' in s for s in result['candidates'][0]['warnings']))

    def test_period_evidence_is_explicit_and_not_read_from_nearby_prose(self):
        self.cell['columnHeaders'] = ['2024년', '기말']
        self.cell['rowHeaders'] = ['Cash']
        result = suggest_correspondences(self.inspection, self.cell['id'], scale='1000')
        self.assertEqual(result['candidates'][0]['ixdFactId'], 'cash-prior')
        current = next(c for c in result['candidates'] if c['ixdFactId'] == 'cash-current')
        self.assertTrue(any('연도' in warning for warning in current['warnings']))

    def test_never_pads_three_with_unrelated_facts(self):
        result = suggest_correspondences(self.inspection, self.cell['id'], scale='1000')
        self.assertEqual(len(result['candidates']), 1)
        result = suggest_correspondences(self.inspection, self.cell['id'], scale='1')
        self.assertEqual(result['candidates'], [])

    def test_currency_conflict_and_duplicate_contexts_are_disclosed(self):
        fact = self.inspection['ixd']['facts'][0]
        fact['unit']['numerator'] = ['{http://www.xbrl.org/2003/iso4217}USD']
        self.inspection['ixd']['facts'].append(dict(deepcopy(fact), id='another-cash'))
        result = suggest_correspondences(self.inspection, self.cell['id'], scale='1000')
        warnings = result['candidates'][0]['warnings']
        self.assertTrue(any('통화' in warning and '달라' in warning for warning in warnings))
        self.assertTrue(any('중복' in warning for warning in warnings))

    def test_duplicate_ids_and_unsupported_contexts_are_not_suggested(self):
        fact = self.inspection['ixd']['facts'][0]
        self.inspection['ixd']['facts'].append(deepcopy(fact))
        self.assertEqual(suggest_correspondences(self.inspection, self.cell['id'], scale='1000')['candidates'], [])
        self.inspection['ixd']['facts'].pop()
        fact['period'] = {'kind': 'forever'}
        self.assertEqual(suggest_correspondences(self.inspection, self.cell['id'], scale='1000')['candidates'], [])

    def test_header_dash_and_invalid_source_or_scale_block_candidates(self):
        header = next(c for c in self.inspection['dsd']['cells'] if c['isHeader'])
        with self.assertRaises(ValueError): suggest_correspondences(self.inspection, header['id'])
        self.cell['number'] = None
        with self.assertRaises(ValueError): suggest_correspondences(self.inspection, self.cell['id'])
        self.cell['number'] = '1234'
        with self.assertRaises(ValueError): suggest_correspondences(self.inspection, self.cell['id'], scale='0')
        self.inspection['sourceUnchanged'] = False
        with self.assertRaises(ValueError): suggest_correspondences(self.inspection, self.cell['id'])

    def test_three_candidate_cap_and_ties_are_deterministic(self):
        original = self.inspection['ixd']['facts'][0]
        self.inspection['ixd']['facts'] = [dict(deepcopy(original), id=f'cash-{i}') for i in range(6)]
        result = suggest_correspondences(self.inspection, self.cell['id'], scale='1000')
        self.assertEqual([c['ixdFactId'] for c in result['candidates']], ['cash-0', 'cash-1', 'cash-2'])

    def test_sign_scale_and_rounding_are_separate_hints(self):
        self.assertEqual(self.codes('1234', '-1234000', '1000'), ['sign'])
        self.assertEqual(self.codes('1234', '1234000', '1'), ['scale'])
        self.assertEqual(self.codes('1234', '1234499', '1000'), ['display-rounding'])
        self.assertEqual(self.codes('1234', '1234501', '1000'), [])
        self.assertEqual(self.codes('1234.00', '1234001', '1000'), ['display-rounding'])
        self.assertEqual(self.codes('1234.00', '1234006', '1000'), [])
        self.assertEqual(self.codes('0', '0', '1000'), [])

    def test_tiny_difference_against_huge_amount_is_preserved(self):
        raw = '123456789012345678901234567890123456789012345678901234567890.00'
        actual = raw[:-2] + '01'
        self.assertEqual(self.codes(raw, actual, '1'), [])

    def test_diagnostic_hint_never_makes_a_mismatch_pass(self):
        import json
        mapping = json.loads(self.sample['mapping'].read_text(encoding='utf-8'))
        mapping['mappings'][0]['scale'] = '1'
        report = compare_disclosures(self.sample['dsd'], self.sample['ixd'], mapping)
        self.assertEqual(report['status'], 'differences')
        row = next(r for r in report['rows'] if r['status'] == 'value-mismatch')
        self.assertEqual(row['diagnostics'][0]['code'], 'scale')
        self.assertNotEqual(row['difference'], '0')
        self.assertEqual(row['columnHeaders'], ['2025-12-31'])


if __name__ == '__main__':
    unittest.main()
