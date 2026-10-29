"""Independent review regressions for exact amounts and cumulative XML bounds."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

from xbrl_filing.disclosure_compare import compare_disclosures, inspect_disclosures
from xbrl_filing.disclosure_compare.examples import create_comparison_example
from xbrl_filing.disclosure_compare.dsd import read_dsd


def rezip(path, transform):
    with ZipFile(path) as archive:
        entries = [(info.filename, archive.read(info)) for info in archive.infolist()]
    result = BytesIO()
    with ZipFile(result, 'w', ZIP_DEFLATED) as archive:
        for name, data in entries:
            archive.writestr(name, transform(name, data))
    path.write_bytes(result.getvalue())


class DisclosureComparisonReviewTests(unittest.TestCase):
    def test_legal_large_ixd_value_has_exact_unrounded_difference(self):
        with tempfile.TemporaryDirectory() as directory:
            example = create_comparison_example(Path(directory) / 'example')
            actual = '9' * 600
            rezip(example['dsd'], lambda name, data: data.replace(b'1,234', b'0.01'))
            rezip(example['ixd'], lambda name, data: data.replace(b'>1234000<', ('>' + actual + '<').encode()) if name.endswith('.xbrl') else data)
            mappings = json.loads(example['mapping'].read_text(encoding='utf-8'))
            mappings['sourceHashes'] = inspect_disclosures(example['dsd'], example['ixd'])['sourceHashes']
            result = compare_disclosures(example['dsd'], example['ixd'], mappings)
            self.assertEqual(result['status'], 'differences')
            self.assertEqual(result['rows'][0]['difference'], str(10 - int(actual)))

    def test_subtraction_retains_tiny_fraction_against_large_integer(self):
        with tempfile.TemporaryDirectory() as directory:
            example = create_comparison_example(Path(directory) / 'example')
            tiny = '0.' + '0' * 180 + '1'
            actual = '9' * 999
            rezip(example['dsd'], lambda name, data: data.replace(b'1,234', tiny.encode()))
            rezip(example['ixd'], lambda name, data: data.replace(b'>1234000<', ('>' + actual + '<').encode()) if name.endswith('.xbrl') else data)
            mappings = json.loads(example['mapping'].read_text(encoding='utf-8'))
            mappings['mappings'][0]['scale'] = '1'
            mappings['sourceHashes'] = inspect_disclosures(example['dsd'], example['ixd'])['sourceHashes']
            result = compare_disclosures(example['dsd'], example['ixd'], mappings)
            # 999...999 - 10^-181 is 999...998.999...999 (181 fraction digits).
            expected = '-' + str(int(actual) - 1) + '.' + '9' * 181
            self.assertEqual(result['rows'][0]['difference'], expected)

    def test_cumulative_member_cell_budget_fails_before_later_xml_is_parsed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'many.dsd'
            xml = b'<DOCUMENT><TABLE><TR><TD>1</TD><TD>2</TD></TR></TABLE></DOCUMENT>'
            with ZipFile(path, 'w', ZIP_DEFLATED) as archive:
                archive.writestr('one.xml', xml)
                archive.writestr('two.xml', xml)
                archive.writestr('z-last.xml', b'<BROKEN')
            with patch('xbrl_filing.disclosure_compare.dsd.MAX_CELLS', 3):
                # The fourth cell already breaches the cross-member budget;
                # malformed later XML must never be reached first.
                with self.assertRaisesRegex(ValueError, '셀|한도'):
                    read_dsd(path)


if __name__ == '__main__':
    unittest.main()
