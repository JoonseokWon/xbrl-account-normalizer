from pathlib import Path
import tempfile
import unittest
import warnings
from unittest.mock import patch
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED, ZIP_BZIP2

from core.errors import InputError
from io_xlsx.package_guard import check_package


class PackageGuardSecurityTests(unittest.TestCase):
    def setUp(self): self.temp = tempfile.TemporaryDirectory(); self.path = Path(self.temp.name) / 'source.xlsx'
    def tearDown(self): self.temp.cleanup()

    def package(self, entries, compression=ZIP_DEFLATED):
        with warnings.catch_warnings(), ZipFile(self.path, 'w', compression) as archive:
            warnings.simplefilter('ignore', UserWarning)
            for name, data in entries: archive.writestr(name, data)
        return self.path

    def test_duplicate_case_collision_traversal_absolute_and_special_members_rejected(self):
        special = ZipInfo('xl/workbook.xml'); special.create_system = 3; special.external_attr = 0o120777 << 16
        for entries in ([('xl/workbook.xml', '<a/>'), ('XL/workbook.xml', '<a/>')],
                        [('../outside.xml', '<a/>')], [('/outside.xml', '<a/>')],
                        [('xl\\workbook.xml', '<a/>')], [(special, '<a/>')]):
            with self.subTest(entries=str(entries)[:60]):
                path = self.package(entries)
                if isinstance(entries[0][0], str) and '\\' in entries[0][0]:
                    # Windows zipfile normalizes slashes when writing. Change
                    # both ZIP headers to exercise an actually hostile name.
                    raw = path.read_bytes()
                    changed = raw.replace(b'xl/workbook.xml', b'xl\\workbook.xml')
                    self.assertNotEqual(raw, changed); path.write_bytes(changed)
                with self.assertRaises(InputError): check_package(path)

    def test_external_relationship_targets_and_hidden_macro_types_rejected(self):
        for xml in ('<Relationships><Relationship TargetMode="External" Target="file:///C:/private.csv"/></Relationships>',
                    '<Relationships><Relationship Target="https://example.invalid/private.csv"/></Relationships>',
                    '<Relationships><Relationship Target="//server/share/private.csv"/></Relationships>',
                    '<Types><Override ContentType="application/vnd.ms-excel.sheet.macroEnabled.main+xml"/></Types>'):
            with self.subTest(xml=xml):
                with self.assertRaises(InputError): check_package(self.package([('_rels/.rels', xml)]))

    def test_utf16_entities_deep_xml_and_formulas_are_rejected(self):
        payloads = [('xl/workbook.xml', '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE a [<!ENTITY x "bad">]><a>&x;</a>'.encode('utf-16')),
                    ('xl/workbook.xml', '<a>' * 65 + '</a>' * 65),
                    ('xl/worksheets/sheet1.xml', '<worksheet><row r="1"><c r="A1"><f>1+1</f></c></row></worksheet>')]
        for name, raw in payloads:
            with self.subTest(name=name):
                with self.assertRaises(InputError): check_package(self.package([(name, raw)]))

    def test_repeated_row_indices_cannot_bypass_physical_row_budget(self):
        xml = '<worksheet>' + '<row r="1"><c r="A1"><v>0</v></c></row>' * 103 + '</worksheet>'
        with patch('io_xlsx.package_guard.MAX_ROWS', 2):
            with self.assertRaises(InputError): check_package(self.package([('xl/worksheets/sheet1.xml', xml)]))

    def test_xml_is_streamed_and_internal_relative_relationships_are_accepted(self):
        path = self.package([('xl/_rels/workbook.xml.rels', '<Relationships><Relationship Target="worksheets/sheet1.xml"/></Relationships>'),
                             ('xl/worksheets/sheet1.xml', '<worksheet><row r="1"><c r="A1"><v>123</v></c></row></worksheet>')])
        with patch.object(ZipFile, 'read', side_effect=AssertionError('whole XML allocation is forbidden')): check_package(path)

    def test_unsupported_compression_and_invalid_cell_coordinates_fail_closed(self):
        with self.assertRaises(InputError): check_package(self.package([('xl/workbook.xml', '<a/>')], ZIP_BZIP2))
        for coordinate in ('ZZ1', 'A0', 'A9999999', 'A-1'):
            with self.subTest(coordinate=coordinate):
                with self.assertRaises(InputError):
                    check_package(self.package([('xl/worksheets/sheet1.xml', f'<worksheet><row r="1"><c r="{coordinate}"/></row></worksheet>')]))

    def test_csv_formula_prefixes_after_whitespace_stay_text(self):
        from xbrl_filing.reporting import _safe_cell
        for value in (' =1+1', ' \t=1+1', '  @SUM(1)', '\n=1', ' +1+2', ' -1+2', '＝1+1', ' ＋1+2', '－1+2', '＠SUM(1)'):
            self.assertTrue(_safe_cell(value).startswith("'"))
        self.assertEqual(_safe_cell('정상 계정'), '정상 계정')


if __name__ == '__main__': unittest.main()
