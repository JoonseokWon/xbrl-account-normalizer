"""Synthetic document comparison checks. No proprietary competitor fixtures."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

from xbrl_filing.disclosure_compare import build_mapping, compare_disclosures, inspect_disclosures
from xbrl_filing.disclosure_compare.dsd import _number
from xbrl_filing.disclosure_compare.examples import create_comparison_example
from xbrl_filing.disclosure_compare import service


def zip_bytes(entries):
    output = BytesIO()
    with ZipFile(output, 'w', compression=ZIP_DEFLATED) as archive:
        for name, value in entries:
            archive.writestr(name, value)
    return output.getvalue()


def rewrite_archive(path, transform):
    with ZipFile(path) as archive:
        entries = [(info.filename, archive.read(info)) for info in archive.infolist()]
    path.write_bytes(zip_bytes([(name, transform(name, data)) for name, data in entries]))


class DisclosureComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.example = create_comparison_example(self.root / 'example')
        self.dsd, self.ixd = self.example['dsd'], self.example['ixd']
        self.mapping = json.loads(self.example['mapping'].read_text(encoding='utf-8'))

    def tearDown(self):
        self.temp.cleanup()

    def compare(self, mapping=None):
        return compare_disclosures(self.dsd, self.ixd, mapping if mapping is not None else self.mapping)

    def rebind_sources(self):
        inventory = inspect_disclosures(self.dsd, self.ixd)
        self.assertFalse(inventory['errors'], inventory['errors'])
        self.mapping['sourceHashes'] = inventory['sourceHashes']
        return inventory

    def test_current_prior_scaled_and_parenthesis_values_match_without_writing_sources(self):
        before = self.dsd.read_bytes(), self.ixd.read_bytes()
        report = self.compare()
        self.assertEqual(report['status'], 'pass', report)
        self.assertEqual(report['counts']['matched'], 3)
        self.assertEqual([row['dsdValue'] for row in report['rows']], ['1234000', '1100000', '-20000'])
        self.assertTrue(report['sourceUnchanged'])
        self.assertEqual(before, (self.dsd.read_bytes(), self.ixd.read_bytes()))
        for name in ('officialGenerated', 'validationPassed', 'finalSubmission'):
            self.assertIs(report[name], False)

    def test_unmapped_and_unapproved_do_not_count_as_matches(self):
        report = compare_disclosures(self.dsd, self.ixd)
        self.assertEqual(report['status'], 'review')
        self.assertEqual(report['counts']['unmapped'], 3)
        self.mapping['mappings'][0]['approved'] = False
        report = self.compare()
        self.assertEqual(report['status'], 'review')
        self.assertEqual(report['counts']['needs-review'], 1)

    def test_amount_difference_is_exact_after_user_scale(self):
        rewrite_archive(self.dsd, lambda name, raw: raw.replace(b'1,234', b'1,235'))
        self.rebind_sources()
        report = self.compare()
        self.assertEqual(report['status'], 'differences')
        self.assertEqual(report['rows'][0]['difference'], '1000')
        self.assertEqual(report['counts']['value-mismatch'], 1)

    def test_changed_source_cannot_reuse_saved_mapping(self):
        rewrite_archive(self.dsd, lambda name, raw: raw.replace(b'1,234', b'1,235'))
        report = self.compare()
        self.assertEqual(report['status'], 'error')
        self.assertIn('해시', report['errors'][0])
        self.assertEqual(report['counts']['matched'], 0)
        self.assertEqual(compare_disclosures(self.dsd, self.ixd, self.mapping['mappings'])['status'], 'error')

    def test_each_measurement_condition_is_separate(self):
        replacements = {
            'concept': '{urn:other}Cash',
            'entity': {'scheme': 'urn:synthetic:entity', 'identifier': '00000001'},
            'period': {'kind': 'instant', 'instant': '2024-12-31'},
            'unit': {'numerator': ['{http://www.xbrl.org/2003/iso4217}USD'], 'denominator': []},
            'dimensions': [{'placement': 'scenario', 'axis': '{urn:synthetic}Axis', 'member': '{urn:synthetic}ConsolidatedMember'}],
        }
        for aspect, value in replacements.items():
            with self.subTest(aspect=aspect):
                mapping = deepcopy(self.mapping)
                mapping['mappings'][0]['expected'][aspect] = value
                report = self.compare(mapping)
                self.assertEqual(report['status'], 'differences', report)
                self.assertEqual(report['rows'][0]['status'], 'aspect-mismatch')
                self.assertIn(aspect, report['rows'][0]['differingAspects'])

    def test_mapping_missing_a_required_aspect_stays_pending(self):
        del self.mapping['mappings'][0]['expected']['dimensions']
        report = self.compare()
        self.assertEqual(report['status'], 'review')
        self.assertEqual(report['counts']['needs-review'], 1)

    def test_same_measurement_duplicate_ixd_is_ambiguous_not_summed(self):
        def add_duplicate(name, raw):
            if name.endswith('.xbrl'):
                return raw.replace(b'</xbrli:xbrl>', b'<e:Cash id="duplicate" contextRef="current" unitRef="KRW" decimals="0">1234000</e:Cash></xbrli:xbrl>')
            return raw
        rewrite_archive(self.ixd, add_duplicate)
        self.rebind_sources()
        report = self.compare()
        self.assertEqual(report['status'], 'review')
        self.assertEqual(report['counts']['ambiguous'], 1)
        self.assertEqual(report['counts']['matched'], 2)

    def test_duplicate_dsd_pair_is_ambiguous(self):
        self.mapping['mappings'].append(deepcopy(self.mapping['mappings'][0]))
        report = self.compare()
        self.assertEqual(report['status'], 'review')
        self.assertEqual(report['counts']['ambiguous'], 2)

    def test_missing_fact_and_cell_are_reported(self):
        self.mapping['mappings'][0]['ixdFactId'] = 'absent'
        report = self.compare()
        self.assertEqual(report['status'], 'differences')
        self.assertEqual(report['counts']['missing'], 1)
        self.assertEqual(report['counts']['unmapped'], 1)

    def test_dash_is_not_zero_and_nil_is_not_blank(self):
        rewrite_archive(self.dsd, lambda name, raw: raw.replace(b'1,234', b'-'))
        self.rebind_sources()
        report = self.compare()
        self.assertEqual(report['status'], 'review')
        self.assertEqual(report['counts']['unsupported'], 1)
        def use_nil(name, raw):
            if name.endswith('.xbrl'):
                return raw.replace(b'<xbrli:xbrl ', b'<xbrli:xbrl xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" ').replace(
                    b'unitRef="KRW" decimals="0">1234000', b'unitRef="KRW" decimals="0" xsi:nil="true">')
            return raw
        rewrite_archive(self.ixd, use_nil)
        self.rebind_sources()
        report = self.compare()
        self.assertEqual(report['counts']['nil-mismatch'], 1)
        self.mapping['mappings'][0]['dsdNil'] = True
        self.assertEqual(self.compare()['status'], 'pass')

    def test_text_fact_language_and_exact_text(self):
        def add_text(name, raw):
            if name.endswith('.xbrl'):
                return raw.replace(b'</xbrli:xbrl>', '<e:Note id="note" contextRef="current" xml:lang="ko">전기 없음</e:Note></xbrli:xbrl>'.encode())
            return raw
        rewrite_archive(self.ixd, add_text)
        inventory = self.rebind_sources()
        cell = next(cell for cell in inventory['dsd']['cells'] if cell['text'] == '전기 없음')
        mapping = build_mapping(inventory, cell['id'], 'note')
        self.mapping['mappings'].append(mapping)
        self.assertEqual(self.compare()['counts']['matched'], 4)
        mapping['expected']['language'] = 'en'
        self.assertEqual(self.compare()['rows'][-1]['status'], 'aspect-mismatch')
        mapping['expected']['language'] = 'ko'
        mapping['scale'] = '1000'
        self.assertEqual(self.compare()['rows'][-1]['status'], 'unsupported')

    def test_invalid_scale_is_pending_not_rounded_or_silently_reset(self):
        for value in ('NaN', 'Infinity', '0', '-1', '100000000000000000000', 'bad'):
            with self.subTest(value=value):
                self.mapping['mappings'][0]['scale'] = value
                report = self.compare()
                self.assertEqual(report['counts']['needs-review'], 1)

    def test_numbers_do_not_misread_commas_dash_text_or_annotations(self):
        self.assertEqual(_number('(1,234.50)'), '-1234.50')
        self.assertEqual(_number('10%'), '0.1')
        self.assertEqual(_number('−20'), '-20')
        for text in ('-', '', '1,23', '1,234 주석', '1 234', '2025-12-31', 'NaN', '(+12)'):
            self.assertIsNone(_number(text), text)
        self.assertEqual(_number('1234567890123456789012345678901234567890%'), '12345678901234567890123456789012345678.9')

    def test_merged_rows_and_columns_keep_real_anchor_positions(self):
        self.dsd.write_text('<DOCUMENT><TABLE><TR><TH ROWSPAN="2">구분</TH><TH COLSPAN="2">기간</TH></TR>'
                            '<TR><TH>당기</TH><TH>전기</TH></TR><TR><TD>현금</TD><TD>1</TD><TD>2</TD></TR></TABLE></DOCUMENT>', encoding='utf-8')
        inventory = inspect_disclosures(self.dsd, self.ixd)
        self.assertFalse(inventory['errors'])
        cells = inventory['dsd']['cells']
        prior = next(cell for cell in cells if cell['text'] == '전기')
        self.assertEqual(prior['source']['column'], 3)
        self.assertEqual(prior['source']['row'], 2)
        self.assertEqual(next(cell for cell in cells if cell['text'] == '2')['columnLabel'], '전기')

    def test_zip_traversal_case_collision_and_executables_are_rejected(self):
        payloads = [[('../contents.xml', '<DOCUMENT/>')],
                    [('contents.xml', '<DOCUMENT/>'), ('CONTENTS.XML', '<DOCUMENT/>')],
                    [('contents.xml', '<DOCUMENT/>'), ('run.exe', 'bad')]]
        for entries in payloads:
            with self.subTest(entries=entries):
                self.dsd.write_bytes(zip_bytes(entries))
                inventory = inspect_disclosures(self.dsd, self.ixd)
                self.assertTrue(inventory['errors'])
                self.assertEqual(inventory['dsd']['cells'], [])

    def test_dtd_entities_bad_xml_and_binary_formats_fail_closed(self):
        for xml in ('<!DOCTYPE DOCUMENT SYSTEM "file:///secret"><DOCUMENT/>',
                    '<!DOCTYPE DOCUMENT [<!ENTITY local SYSTEM "file:///secret">]><DOCUMENT>&local;</DOCUMENT>',
                    '<DOCUMENT><TABLE>', 'not an XML document'):
            with self.subTest(xml=xml):
                self.dsd.write_text(xml, encoding='utf-8')
                report = compare_disclosures(self.dsd, self.ixd, self.mapping)
                self.assertEqual(report['status'], 'error')
                self.assertEqual(report['rows'], [])

    def test_editor_document_does_not_expose_submission_facts(self):
        self.ixd.write_bytes(zip_bytes([('Report.xml', '<DocumentInfo/>'), ('EditorMenu.xml', '<ArrayOfMenuItem/>'),
                                       ('TaxonomyItemCompanyT.xml', '<T/>'), ('TaxonomyItemCompanyV.xml', '<V/>'), ('TaxonomyItemDart.xml', '<D/>')]))
        inventory = inspect_disclosures(self.dsd, self.ixd)
        self.assertTrue(inventory['errors'])
        self.assertEqual(inventory['ixd']['facts'], [])

    def test_xml_and_mapping_budgets_are_enforced(self):
        with patch('xbrl_filing.disclosure_compare.dsd.MAX_CELLS', 2):
            self.assertTrue(inspect_disclosures(self.dsd, self.ixd)['errors'])
        with patch.object(service, 'MAX_MAPPINGS', 1):
            self.assertEqual(self.compare()['status'], 'error')

    def test_read_time_source_change_discards_inventory(self):
        original = service.read_ixd
        def change_dsd(path):
            parsed = original(path)
            rewrite_archive(self.dsd, lambda name, raw: raw.replace(b'1,234', b'1,235'))
            return parsed
        with patch.object(service, 'read_ixd', side_effect=change_dsd):
            inventory = inspect_disclosures(self.dsd, self.ixd)
        self.assertFalse(inventory['sourceUnchanged'])
        self.assertTrue(inventory['errors'])
        self.assertEqual(inventory['dsd']['cells'], [])


if __name__ == '__main__':
    unittest.main()
