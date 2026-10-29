"""Synthetic DSD version fixtures; no editor or native input is used."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

from xbrl_filing.dsd_diff import compare_dsd_versions
from xbrl_filing.dsd_diff import service
from xbrl_filing.dsd_diff._document import read_document
from xbrl_filing import dsd_document
from xbrl_filing.dsd_document import extract_dsd_narratives


def table(title='현금및현금성자산', rows=None, headers=('구분', '2025년', '2024년')):
    rows = rows if rows is not None else [('보통예금', '1,000', '900'), ('현금', '20', '10')]
    header = '<THEAD><TR>' + ''.join(f'<TH>{value}</TH>' for value in headers) + '</TR></THEAD>'
    body = '<TBODY>' + ''.join('<TR>' + ''.join(f'<TD>{value}</TD>' for value in row) + '</TR>' for row in rows) + '</TBODY>'
    return f'<P>{title}</P><P>(단위: 천원)</P><TABLE>{header}{body}</TABLE>'


class DsdDiffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, body, member=None):
        path = self.root / name
        data = ('<?xml version="1.0" encoding="utf-8"?><DOCUMENT>' + body + '</DOCUMENT>').encode('utf-8')
        if member:
            with ZipFile(path, 'w', ZIP_DEFLATED) as archive:
                archive.writestr(member, data)
        else:
            path.write_bytes(data)
        return path

    def compare(self, old, new):
        return compare_dsd_versions(self.write('before.dsd', old), self.write('after.dsd', new))

    def test_member_and_filename_renaming_does_not_change_numbers(self):
        before = self.write('old.dsd', table(), 'old/contents.xml')
        after = self.write('new.dsd', table(), 'renamed/report.xml')
        original = before.read_bytes(), after.read_bytes()
        report = compare_dsd_versions(before, after)
        self.assertEqual(report['status'], 'pass', report)
        self.assertEqual(report['counts']['matchedTables'], 1)
        self.assertEqual(report['counts']['matchedCells'], 9)
        self.assertEqual(original, (before.read_bytes(), after.read_bytes()))
        self.assertTrue(report['sourceUnchanged'])
        self.assertNotIn(str(self.root), json.dumps(report, ensure_ascii=False))

    def test_exact_decimal_difference_and_sign_reversal(self):
        report = self.compare(table(rows=[('예금', '1,000.20', '900')]),
                              table(rows=[('예금', '(1,000.20)', '900')]))
        self.assertEqual(report['status'], 'differences', report)
        changed = [row for row in report['rows'] if row['kind'] == 'value-changed']
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0]['difference'], '-2000.40')
        self.assertEqual(changed[0]['diagnostics'], ['sign-reversed'])
        self.assertEqual(changed[0]['before']['text'], '1,000.20')
        self.assertEqual(changed[0]['after']['text'], '(1,000.20)')

    def test_inserted_table_does_not_pair_by_document_ordinal(self):
        original = table('현금', [('보통예금', '100', '90')]) + table('재고', [('상품', '50', '40')])
        extra = table('매출채권', [('외상매출금', '200', '190')])
        report = self.compare(original, extra + original)
        self.assertEqual(report['counts']['matchedTables'], 2)
        self.assertEqual(report['counts']['table-added'], 1)
        self.assertFalse(any(row['kind'] == 'value-changed' for row in report['rows']))
        self.assertEqual(report['tablePairs'][0]['afterId'], 'after.dsd#t2')

    def test_inserted_row_keeps_existing_rows_and_source_coordinates(self):
        old = table(rows=[('예금', '100', '90'), ('현금', '50', '40')])
        new = table(rows=[('예금', '100', '90'), ('외화예금', '25', '20'), ('현금', '50', '40')])
        report = self.compare(old, new)
        self.assertEqual(report['status'], 'differences', report)
        self.assertEqual(report['counts']['cell-added'], 3)
        self.assertEqual(report['counts']['movedCells'], 3)
        self.assertFalse(any(row['kind'] == 'value-changed' for row in report['rows']))

    def test_reordered_rows_are_structural_changes_not_pass_or_amount_changes(self):
        old_rows = [('예금', '100', '90'), ('현금', '50', '40')]
        report = self.compare(table(rows=old_rows), table(rows=list(reversed(old_rows))))
        self.assertEqual(report['status'], 'differences', report)
        self.assertGreater(report['counts']['structure-changed'], 0)
        self.assertEqual(report['counts']['movedCells'], 6)
        self.assertFalse(any(row['kind'] == 'value-changed' for row in report['rows']))

    def test_duplicate_changed_tables_remain_unresolved(self):
        old = table('예금', [('예금', '100', '90')]) * 2
        new = table('예금', [('예금', '200', '90')]) * 2
        report = self.compare(old, new)
        self.assertEqual(report['status'], 'needs-review', report)
        self.assertGreater(report['counts']['ambiguous'], 0)
        self.assertEqual(report['tablePairs'], [])
        self.assertFalse(any(row['kind'] == 'value-changed' for row in report['rows']))

    def test_identical_duplicate_tables_are_document_equality_not_ambiguous_pairing(self):
        body = table('예금', [('예금', '100', '90')]) * 2
        report = self.compare(body, body)
        self.assertEqual(report['status'], 'pass', report)
        self.assertEqual(report['counts']['matchedTables'], 2)

    def test_unchanged_merged_duplicate_headers_do_not_create_false_additions(self):
        body = '<P>예금</P><TABLE><TR><TH>구분</TH><TH COLSPAN="2">당기</TH></TR><TR><TD>예금</TD><TD>100</TD><TD>90</TD></TR></TABLE>'
        report = self.compare(body, body)
        self.assertEqual(report['status'], 'pass', report)
        self.assertEqual(report['rows'], [])

    def test_unchanged_multirow_parent_headers_not_ambiguous_when_amounts_change(self):
        old = ('<P>예금</P><TABLE><THEAD><TR><TH ROWSPAN="2">항목</TH><TH COLSPAN="2">잔액</TH></TR>'
               '<TR><TH>2025년 기말</TH><TH>2024년 기말</TH></TR></THEAD>'
               '<TBODY><TR><TD>보통예금</TD><TD>100</TD><TD>90</TD></TR></TBODY></TABLE>')
        report = self.compare(old, old.replace('<TD>100</TD>', '<TD>200</TD>').replace('<TD>90</TD>', '<TD>80</TD>'))
        self.assertEqual(report['status'], 'differences', report)
        self.assertEqual(report['counts']['value-changed'], 2)
        self.assertEqual(report['counts']['ambiguous'], 0)
        self.assertFalse(any(row['kind'] in ('cell-added', 'cell-removed') for row in report['rows']))

    def test_completely_changed_unmatched_tables_need_review(self):
        report = self.compare(table('현금', [('예금', '100', '90')]),
                              table('재고', [('상품', '10', '9')], ('항목', '금액1', '금액2')))
        self.assertEqual(report['status'], 'needs-review', report)
        self.assertEqual(report['counts']['matchedTables'], 0)

    def test_duplicate_changed_rows_do_not_pick_first_same_name(self):
        report = self.compare(table(rows=[('예금', '100', '90'), ('예금', '100', '90')]),
                              table(rows=[('예금', '200', '90'), ('예금', '300', '90')]))
        self.assertEqual(report['status'], 'needs-review', report)
        self.assertFalse(any(row['kind'] == 'value-changed' for row in report['rows']))

    def test_merged_cell_change_keeps_original_spans(self):
        old = '<P>자산 표</P><TABLE><TR><TH COLSPAN="2">당기</TH></TR><TR><TD>현금</TD><TD>100</TD></TR></TABLE>'
        new = '<P>자산 표</P><TABLE><TR><TH>당기</TH></TR><TR><TD>현금</TD><TD>100</TD></TR></TABLE>'
        report = self.compare(old, new)
        changes = [row for row in report['rows'] if row['kind'] == 'structure-changed']
        self.assertTrue(changes, report)
        self.assertEqual(changes[0]['before']['colspan'], 2)
        self.assertEqual(changes[0]['after']['colspan'], 1)

    def test_narrative_change_and_inline_text_not_duplicated(self):
        old = '<SECTION><TITLE>1. 회계정책</TITLE><P>정책은 <SPAN>원가법</SPAN>을 적용합니다.</P>' + table() + '</SECTION>'
        new = old.replace('원가법', '공정가치법')
        report = self.compare(old, new)
        changes = [row for row in report['rows'] if row['kind'] == 'narrative-changed']
        self.assertEqual(len(changes), 1, report)
        self.assertEqual(changes[0]['before']['text'], '정책은 원가법을 적용합니다.')
        self.assertEqual(changes[0]['after']['sectionPath'], ['1. 회계정책'])

    def test_narrative_insertion_does_not_change_later_paragraphs(self):
        old = '<P>첫 문단</P><P>둘째 문단</P>' + table()
        new = '<P>첫 문단</P><P>추가 설명</P><P>둘째 문단</P>' + table()
        report = self.compare(old, new)
        self.assertEqual(report['counts']['narrative-added'], 1)
        self.assertFalse(any(row['kind'] == 'narrative-changed' for row in report['rows']))

    def test_table_free_report_still_compares_narrative(self):
        report = self.compare('<P>첫 문단</P>', '<P>수정 문단</P>')
        self.assertEqual(report['status'], 'differences', report)
        self.assertEqual(report['counts']['narrative-changed'], 1)
        self.assertEqual(report['before']['tableCount'], 0)

    def test_blank_dash_zero_remain_different(self):
        for old, new in [('', '-'), ('-', '0'), ('0', '')]:
            with self.subTest(old=old, new=new):
                report = self.compare(table(rows=[('예금', old, '90')]), table(rows=[('예금', new, '90')]))
                changes = [row for row in report['rows'] if row['kind'] == 'text-changed']
                self.assertEqual(len(changes), 1, report)
                self.assertIn('공란·대시·0', changes[0]['message'])

    def test_same_number_different_presentation_not_amount_change(self):
        report = self.compare(table(rows=[('예금', '1,000.00', '10%')]),
                              table(rows=[('예금', '1000', '0.1')]))
        changes = [row for row in report['rows'] if row['kind'] == 'format-changed']
        self.assertEqual(len(changes), 2, report)
        self.assertFalse(any(row['kind'] == 'value-changed' for row in report['rows']))

    def test_unit_change_does_not_rescale_numbers(self):
        old = table()
        report = self.compare(old, old.replace('천원', '백만원'))
        self.assertEqual(report['counts']['unit-changed'], 1)
        self.assertFalse(any(row['kind'] == 'value-changed' for row in report['rows']))

    def test_column_reorder_uses_full_header_and_does_not_change_values(self):
        old = table(rows=[('예금', '100', '90')])
        new = table(rows=[('예금', '90', '100')], headers=('구분', '2024년', '2025년'))
        report = self.compare(old, new)
        self.assertFalse(any(row['kind'] == 'value-changed' for row in report['rows']), report)
        self.assertGreater(report['counts']['movedCells'], 0)

    def test_unsafe_dtd_and_zip_traversal_are_rejected(self):
        safe = self.write('safe.dsd', table())
        unsafe = self.root / 'unsafe.dsd'
        unsafe.write_bytes(b'<!DOCTYPE DOCUMENT [<!ENTITY x SYSTEM "file:///never-read">]><DOCUMENT><P>&x;</P></DOCUMENT>')
        report = compare_dsd_versions(safe, unsafe)
        self.assertEqual(report['status'], 'error', report)
        self.assertEqual(report['rows'], [])
        with ZipFile(unsafe, 'w', ZIP_DEFLATED) as archive:
            archive.writestr('../escape.xml', '<DOCUMENT/>')
        self.assertEqual(compare_dsd_versions(safe, unsafe)['status'], 'error')

    def test_source_changes_clear_partial_results(self):
        left = self.write('left.dsd', table())
        right = self.write('right.dsd', table())
        with patch.object(service, 'digest', side_effect=['a' * 64, 'b' * 64, 'c' * 64, 'b' * 64]):
            report = compare_dsd_versions(left, right)
        self.assertEqual(report['status'], 'error')
        self.assertEqual(report['rows'], [])
        self.assertFalse(report['sourceUnchanged'])
        self.assertIn('변경', report['errors'][0])

    def test_result_budget_exhaustion_never_looks_like_pass(self):
        with patch.object(service, 'MAX_REPORT_ROWS', 0):
            report = self.compare(table(), table(rows=[('예금', '200', '90')]))
        self.assertEqual(report['status'], 'error')
        self.assertEqual(report['rows'], [])

    def test_missing_file_error_excludes_absolute_source_path(self):
        report = compare_dsd_versions(self.root / 'secret' / 'missing.dsd', self.root / 'missing.dsd')
        self.assertEqual(report['status'], 'error')
        self.assertNotIn(str(self.root), json.dumps(report, ensure_ascii=False))

    def test_large_narrative_alignment_uses_bounded_fallback(self):
        with patch.object(service, 'MAX_NARRATIVE_ALIGNMENT_WORK', 1):
            report = self.compare('<P>원문</P>' + table(), '<P>수정</P>' + table())
        self.assertEqual(report['status'], 'needs-review', report)
        self.assertGreater(report['counts']['ambiguous'], 0)

    def test_large_narrative_reordering_does_not_disappear_as_pass(self):
        with patch.object(service, 'MAX_NARRATIVE_ALIGNMENT_WORK', 1):
            report = self.compare('<P>처음</P><P>다음</P><P>마지막</P>' + table(),
                                  '<P>마지막</P><P>처음</P><P>다음</P>' + table())
        self.assertEqual(report['status'], 'needs-review', report)
        self.assertTrue(any('순서' in row['message'] for row in report['rows']))

    def test_public_narrative_reader_preserves_full_headings_and_no_table_cell_duplicates(self):
        heading = '아주긴제목' * 500
        path = self.write('narratives.dsd', '<SECTION><TITLE>' + heading + '</TITLE><P>정책 <SPAN>내용</SPAN> 보충</P>' + table() + '</SECTION>')
        report = extract_dsd_narratives(path)
        texts = [row['text'] for row in report['narratives']]
        self.assertEqual(texts.count(heading), 1)
        self.assertIn('정책 내용 보충', texts)
        self.assertNotIn('보통예금', texts)
        self.assertEqual(report['narratives'][1]['sectionPath'], [heading[:2000]])
        self.assertTrue(report['sourceUnchanged'])
        self.assertEqual(len(report['sourceHash']), 64)

    def test_public_narrative_reader_preserves_plain_container_text_and_tails(self):
        path = self.write('mixed.xml', '<SECTION>직접 본문<P>안쪽 본문</P>뒤 본문</SECTION>')
        report = extract_dsd_narratives(path)
        self.assertEqual([row['text'] for row in report['narratives']], ['직접 본문', '안쪽 본문', '뒤 본문'])

    def test_public_narrative_reader_bound_is_rejection_not_truncation(self):
        path = self.write('many.xml', '<P>첫째</P><P>둘째</P>')
        with patch.object(dsd_document, 'MAX_NARRATIVES', 1):
            with self.assertRaisesRegex(ValueError, '문단'):
                extract_dsd_narratives(path)

    def test_public_narrative_reader_rejects_changed_sources(self):
        path = self.write('source.xml', '<P>본문</P>')
        with patch.object(dsd_document, 'digest', side_effect=['a' * 64, 'b' * 64]):
            with self.assertRaisesRegex(ValueError, '변경'):
                extract_dsd_narratives(path)

    def test_network_sources_are_rejected_before_open(self):
        with patch.object(Path, 'open', side_effect=AssertionError('must not open')):
            report = compare_dsd_versions(r'\\server\share\source.dsd', r'\\server\share\other.dsd')
            self.assertEqual(report['status'], 'error')
            with self.assertRaises(ValueError):
                extract_dsd_narratives('https://example.invalid/report.dsd')


if __name__ == '__main__':
    unittest.main()
