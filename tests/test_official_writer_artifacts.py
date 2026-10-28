"""Synthetic inspection fixtures; no official writer data is redistributed."""
from io import BytesIO
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

from xbrl_filing.official_writer import artifacts


def zip_bytes(entries, compression=ZIP_DEFLATED):
    output = BytesIO()
    with ZipFile(output, 'w', compression=compression) as archive:
        for name, value in entries:
            archive.writestr(name, value)
    return output.getvalue()


def editor_entries(full=True):
    items = [
        ('Report.xml', '<DocumentInfo><DocumentTitle>작성시험</DocumentTitle>'
         '<ProgramVersion>9.01</ProgramVersion></DocumentInfo>'),
        ('EditorMenu.xml', '<ArrayOfMenuItem/>'),
        ('D210005.frm', '<TestForm/>'),
    ]
    if full:
        items.extend((name, '<TestData/>') for name in (
            'TaxonomyItemCompanyT.xml', 'TaxonomyItemCompanyV.xml', 'TaxonomyItemDart.xml'))
    return items


def submission_entries():
    references = {
        'INSTANCE': 'EntityTaxonomy/entity_2026.xbrl',
        'SCHEMA': 'EntityTaxonomy/entity_2026.xsd',
        'PRESENTATION': 'EntityTaxonomy/entity_pre.xml',
        'CALCULATION': 'EntityTaxonomy/entity_cal.xml',
        'DEFINITION': 'EntityTaxonomy/entity_def.xml',
        'LABEL_KO': 'EntityTaxonomy/entity_ko.xml',
        'LABEL_EN': 'EntityTaxonomy/entity_en.xml',
    }
    # Deliberately synthetic: classification is a candidate, never proof of an
    # official output, even when this packaging resembles the installed writer.
    dart = b'<SYNTHETIC_DART_DOCUMENT/>'
    meta = ('<METAINFO><GENERATOR editver="9.01" Adate="8.6" DocumentTitle="X00080"/>'
            f'<XBRLDOCUMENT FileName="X00080.xml" Size="{len(dart)}" '
            'CreateDateTime="custom-value" PeriodFrom="20260101" PeriodTo="20261231"/>'
            '<XBRL>' + ''.join(f'<{tag} filename="{path}"/>' for tag, path in references.items())
            + '</XBRL><VERIFY validate="" expand=""/></METAINFO>')
    return [('meta.xml', meta), ('UserData.ifm', zip_bytes(editor_entries(full=False))),
            ('X00080.xml', dart)] + [(path, '<SyntheticReference/>') for path in references.values()]


class OfficialWriterArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def artifact(self, entries, name='report.ixd', **kwargs):
        path = self.root / name
        path.write_bytes(zip_bytes(entries, **kwargs))
        return path, artifacts.inspect_artifact(path)

    def test_extension_alone_and_unrelated_zip_are_unknown(self):
        path = self.root / 'renamed.ixd'
        path.write_text('not an official archive', encoding='utf-8')
        self.assertEqual(artifacts.inspect_artifact(path)['kind'], 'unknown')
        _, result = self.artifact([('unrelated.xml', '<root/>')])
        self.assertEqual(result['kind'], 'unknown')
        self.assertTrue(result['errors'])
        _, result = self.artifact(editor_entries(), name='report.xlsx')
        self.assertEqual(result['kind'], 'unknown')

    def test_editor_content_is_inspected_for_both_extensions_read_only(self):
        for extension in ('ixd', 'zip'):
            path, result = self.artifact(editor_entries(), name='editor.' + extension)
            before = path.read_bytes()
            self.assertEqual(result['kind'], 'editor-document')
            self.assertEqual(result['metadata']['editor']['ProgramVersion'], '9.01')
            self.assertFalse(result['officialGenerated'])
            self.assertFalse(result['validationPassed'])
            self.assertTrue(result['checks']['archiveIntegrity'])
            self.assertEqual(path.read_bytes(), before)

    def test_submission_structure_does_not_certify_empty_verify(self):
        _, result = self.artifact(submission_entries())
        self.assertEqual(result['kind'], 'submission-candidate')
        self.assertFalse(result['officialGenerated'])
        self.assertFalse(result['validationPassed'])
        self.assertEqual(result['period'], {'from': '20260101', 'to': '20261231'})
        self.assertEqual(result['metadata']['nestedFileCount'], 3)

    def test_missing_reference_size_mismatch_and_duplicate_metadata_fail(self):
        original = submission_entries()
        changes = [original[:-1],
                   [(name, data.replace('Size="', 'Size="9') if name == 'meta.xml'
                     else data) for name, data in original],
                   [(name, data.replace('<XBRL>', '<XBRL><SCHEMA filename="EntityTaxonomy/a.xsd"/>')
                     if name == 'meta.xml' else data) for name, data in original]]
        for entries in changes:
            with self.subTest(entries=entries[:1]):
                _, result = self.artifact(entries)
                self.assertEqual(result['kind'], 'unknown')
                self.assertTrue(result['errors'])

    def test_backslash_metadata_reference_is_safely_normalized(self):
        entries = [(name, value.replace('EntityTaxonomy/', 'EntityTaxonomy\\')
                    if name == 'meta.xml' else value) for name, value in submission_entries()]
        _, result = self.artifact(entries)
        self.assertEqual(result['kind'], 'submission-candidate')

    def test_unsafe_paths_case_collisions_and_symlinks_are_rejected(self):
        for name in ('../Report.xml', 'C:/Report.xml', '//host/Report.xml',
                     'directory\\..\\Report.xml', 'folder/CON.xml', 'folder /Report.xml'):
            _, result = self.artifact([(name, 'bad')])
            self.assertEqual(result['kind'], 'unknown', name)
            self.assertTrue(result['errors'], name)
        _, result = self.artifact([('Report.xml', 'a'), ('REPORT.XML', 'b')])
        self.assertTrue(result['errors'])
        link = ZipInfo('linked.xml')
        link.create_system = 3
        link.external_attr = (0o120777 << 16)
        _, result = self.artifact([(link, '../outside')])
        self.assertTrue(result['errors'])

    def test_encrypted_member_flag_is_rejected_without_password_attempt(self):
        raw = bytearray(zip_bytes([('test.xml', '<root/>')], compression=ZIP_STORED))
        local = raw.index(b'PK\x03\x04')
        central = raw.index(b'PK\x01\x02')
        struct.pack_into('<H', raw, local + 6, struct.unpack_from('<H', raw, local + 6)[0] | 1)
        struct.pack_into('<H', raw, central + 8, struct.unpack_from('<H', raw, central + 8)[0] | 1)
        path = self.root / 'encrypted.ixd'
        path.write_bytes(raw)
        result = artifacts.inspect_artifact(path)
        self.assertEqual(result['kind'], 'unknown')
        self.assertTrue(result['errors'])

    def test_crc_corruption_is_detected(self):
        raw = bytearray(zip_bytes(editor_entries(), compression=ZIP_STORED))
        position = raw.index(b'<DocumentInfo>')
        raw[position] = ord('!')
        path = self.root / 'damaged.ixd'
        path.write_bytes(raw)
        result = artifacts.inspect_artifact(path)
        self.assertEqual(result['kind'], 'unknown')
        self.assertTrue(result['errors'])

    def test_size_entry_and_nesting_budgets_are_enforced(self):
        for setting, limit in (('MAX_ARCHIVE_BYTES', 10), ('MAX_MEMBER_BYTES', 10),
                               ('MAX_EXPANDED_BYTES', 10), ('MAX_ENTRIES', 2),
                               ('MAX_METADATA_BYTES', 10)):
            with self.subTest(setting=setting), patch.object(artifacts, setting, limit):
                _, result = self.artifact(editor_entries())
                self.assertEqual(result['kind'], 'unknown')
                self.assertTrue(result['errors'])
        entries = submission_entries()
        entries[1] = ('UserData.ifm', zip_bytes(editor_entries(False) + [('another.ifm', b'PK')]))
        _, result = self.artifact(entries)
        self.assertEqual(result['kind'], 'unknown')
        self.assertTrue(result['errors'])

    def test_dtd_and_entity_in_editor_metadata_are_rejected(self):
        for declaration in ('<!DOCTYPE DocumentInfo SYSTEM "https://example.invalid/no.dtd">',
                            '<!DOCTYPE DocumentInfo [<!ENTITY local SYSTEM "file:///secret">]>'):
            entries = editor_entries()
            entries[0] = ('Report.xml', declaration + '<DocumentInfo/>')
            _, result = self.artifact(entries)
            self.assertEqual(result['kind'], 'unknown')
            self.assertTrue(result['errors'])


class OfficialWriterValidationLogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def log(self, document):
        path = self.root / 'Report_00000000_9.01_CHKINFO_X.json'
        path.write_text(json.dumps(document), encoding='utf-8')
        return artifacts.inspect_validation(path)

    def entry(self, level='info'):
        return {'code': 'synthetic.validation', 'level': level,
                'message': {'text': 'Synthetic technical log', 'args': {}},
                'refs': [{'href': 'EntityTaxonomy/test.xbrl', 'sourceLine': 3}]}

    def test_populated_technical_log_is_not_full_validation_pass(self):
        result = self.log({'log': [self.entry(), self.entry('warning')]})
        self.assertEqual(result['status'], 'no-errors')
        self.assertEqual(result['counts'], {'errors': 0, 'warnings': 1, 'info': 1, 'other': 0})
        self.assertFalse(result['officialGenerated'])
        self.assertFalse(result['validationPassed'])

    def test_error_and_unknown_level_are_distinct(self):
        result = self.log({'log': [self.entry('error')]})
        self.assertEqual(result['status'], 'errors')
        self.assertEqual(result['counts']['errors'], 1)
        result = self.log({'log': [self.entry('new-version-level')]})
        self.assertEqual(result['status'], 'unknown')

    def test_empty_missing_and_wrong_shapes_do_not_pass(self):
        for value in ({'log': []}, {}, {'log': {}}, {'log': [None]},
                      {'log': [{'level': 'info'}]}):
            result = self.log(value)
            self.assertEqual(result['status'], 'unknown')
        self.assertEqual(artifacts.inspect_validation(self.root / 'missing.json')['status'], 'unknown')

    def test_pascal_case_model_aliases_match_newtonsoft_but_collisions_fail(self):
        result = self.log({'Log': [{'Code': 'test', 'Level': 'error',
                                  'Message': {'Text': 'error'}, 'Refs': []}]})
        self.assertEqual(result['status'], 'errors')
        path = self.root / 'duplicate.json'
        path.write_text('{"log":[],"Log":[]}', encoding='utf-8')
        result = artifacts.inspect_validation(path)
        self.assertEqual(result['status'], 'unknown')
        self.assertTrue(result['errors'])

    def test_nonstandard_json_and_log_budgets_fail_closed(self):
        path = self.root / 'invalid.json'
        path.write_text('{"log":NaN}', encoding='utf-8')
        self.assertEqual(artifacts.inspect_validation(path)['status'], 'unknown')
        with patch.object(artifacts, 'MAX_LOG_BYTES', 5):
            result = self.log({'log': [self.entry()]})
            self.assertEqual(result['status'], 'unknown')
        with patch.object(artifacts, 'MAX_LOG_ENTRIES', 1):
            result = self.log({'log': [self.entry(), self.entry()]})
            self.assertEqual(result['status'], 'unknown')


if __name__ == '__main__':
    unittest.main()
