"""Real-service disclosure UI contracts using Qt offscreen, with no OS input."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    from PySide6.QtWidgets import QApplication
    from desktop.disclosure_compare import DisclosureCompareDialog, export_comparison_csv
    from desktop.disclosure_workspace import DisclosureWorkspaceDialog
    QT = True
except ImportError:
    QT = False


def report_fixture():
    return {'schema': 'account-normalizer-filing/1',
            'entity': {'name': '새 회사', 'identifier': '00990011', 'scheme': 'urn:test:entity'},
            'reporting': {'periodStart': '2025-01-01', 'periodEnd': '2025-12-31', 'consolidation': '별도', 'comparativePeriods': []},
            'facts': [{'id': 'cash', 'statement': 'BS', 'originalName': '현금', 'concept': 'e:Cash', 'value': '100', 'unit': 'KRW', 'decimals': '0',
                       'period': {'kind': 'instant', 'instant': '2025-12-31'}, 'dimensions': {}, 'approved': True, 'reviewer': '이전 확인자', 'source': '합성'}]}


@unittest.skipUnless(QT, 'PySide6 required for native disclosure UI tests')
class DisclosureUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.dialogs = []

    def tearDown(self):
        for dialog in self.dialogs:
            self.wait(dialog)
            dialog.dirty = False
            dialog.close(); dialog.deleteLater()
        self.app.processEvents(); self.temporary.cleanup()

    def wait(self, dialog):
        deadline = time.monotonic() + 20
        while dialog.loading and time.monotonic() < deadline:
            self.app.processEvents(); time.sleep(0.002)
        self.assertFalse(dialog.loading, 'background disclosure job did not finish')
        self.app.processEvents()

    def workspace(self):
        from application.disclosure_workspace import create_workspace
        dialog = DisclosureWorkspaceDialog(); self.dialogs.append(dialog)
        dialog.set_workspace(create_workspace(report_fixture()), dirty=False)
        return dialog

    def test_new_company_is_entered_by_user_without_a_fixed_sample_company(self):
        dialog = DisclosureWorkspaceDialog(); self.dialogs.append(dialog)
        dialog.new_workspace()
        self.assertEqual(dialog.entity_name.text(), '')
        dialog.entity_name.setText('사용자 신규 회사'); dialog.entity_id.setText('00550066'); dialog.entity_scheme.setText('urn:company:test')
        dialog.period_start.setText('2026-01-01'); dialog.period_end.setText('2026-12-31'); dialog.consolidation.setCurrentText('연결')
        self.assertTrue(dialog.apply_metadata())
        state = dialog.workspace['state']['report']
        self.assertEqual(state['entity']['name'], '사용자 신규 회사')
        self.assertEqual(state['entity']['identifier'], '00550066')
        self.assertEqual(state['reporting']['consolidation'], '연결')
        self.assertEqual(state['facts'], [])

    def test_note_and_fact_edits_are_both_committed_and_show_before_after_history(self):
        dialog = self.workspace(); dialog.actor.setText('공시 담당자'); dialog.add_note()
        dialog.note_title.setText('현금 주석'); dialog.note_text.setPlainText('제한성 예금은 없습니다.'); dialog.note_fact_ids.setText('cash')
        dialog.fact_value.setPlainText('125'); dialog.fact_concept.setText('e:CashAndCashEquivalents')
        self.assertTrue(dialog.apply_note())
        state = dialog.workspace['state']
        self.assertEqual(state['notes'][0]['text'], '제한성 예금은 없습니다.')
        self.assertEqual(state['notes'][0]['factIds'], ['cash'])
        self.assertEqual(state['report']['facts'][0]['value'], '125')
        self.assertFalse(state['report']['facts'][0]['approved'])
        dialog.history.selectRow(len(dialog.revisions) - 1)
        text = dialog.history_detail.toPlainText()
        self.assertIn('변경 전:', text); self.assertIn('변경 후:', text); self.assertIn('125', text)
        self.assertEqual(dialog.revisions[-1]['actor'], '공시 담당자')

    def test_save_twice_keeps_storage_hash_then_reopens_all_revisions(self):
        from application.disclosure_workspace import load_workspace
        dialog = self.workspace(); dialog.add_note(); dialog.note_text.setPlainText('첫 내용'); dialog.apply_note()
        target = self.directory / '새회사.acdisclosure'
        with patch('desktop.disclosure_workspace.QFileDialog.getSaveFileName', return_value=(str(target), '')):
            dialog.save_workspace(); self.wait(dialog)
            self.assertFalse(dialog.dirty)
            dialog.note_text.setPlainText('두 번째 내용'); dialog.apply_note()
            dialog.save_workspace(); self.wait(dialog)
        self.assertFalse(dialog.dirty, dialog.notice.text())
        loaded = load_workspace(target)
        self.assertEqual(loaded['state']['notes'][0]['text'], '두 번째 내용')
        self.assertEqual(len(loaded['revisions']), len(dialog.workspace['revisions']))

    def test_restore_retains_the_selected_revision_and_records_a_new_change(self):
        dialog = self.workspace(); dialog.add_note(); dialog.note_text.setPlainText('원래 서술'); dialog.apply_note()
        restore_to = len(dialog.revisions)
        dialog.note_text.setPlainText('수정 서술'); dialog.apply_note()
        dialog.history.selectRow(restore_to - 1)
        self.assertTrue(dialog.history.currentIndex().isValid())
        with patch('desktop.disclosure_workspace.confirm', return_value=True): dialog.restore_revision()
        self.assertEqual(dialog.workspace['state']['notes'][0]['text'], '원래 서술')
        self.assertEqual(dialog.workspace['revisions'][-1]['action'], 'revision-restore')
        self.assertFalse(dialog.workspace['state']['report']['facts'][0]['approved'])

    def test_new_note_fact_can_be_edited_and_draft_exported_without_approval(self):
        dialog = self.workspace(); dialog.add_fact()
        dialog.fact_name.setText('현금 서술'); dialog.fact_concept.setText('e:CashNote'); dialog.fact_value.setPlainText('한' * 100_000)
        dialog.fact_language.setText('ko')
        self.assertTrue(dialog.apply_fact())
        self.assertEqual(len(dialog.workspace['state']['report']['facts'][1]['value']), 100_000)
        path = self.directory / '초안.json'
        with patch('desktop.disclosure_workspace.QFileDialog.getSaveFileName', return_value=(str(path), '')):
            dialog.export_report(); self.wait(dialog)
        exported = json.loads(path.read_text(encoding='utf-8'))
        self.assertTrue(all(not row['approved'] for row in exported['facts']))
        self.assertEqual(len(exported['facts'][1]['value']), 100_000)
        self.assertTrue(exported['disclosureWorkspace']['notesAreDraftMetadata'])

    def test_next_year_reuses_notes_and_comparatives_but_clears_new_current_values(self):
        dialog = self.workspace(); dialog.add_note(); dialog.note_title.setText('보유 현금'); dialog.note_fact_ids.setText('cash'); dialog.apply_note()
        target = self.directory / '원본.acdisclosure'
        with patch('desktop.disclosure_workspace.QFileDialog.getSaveFileName', return_value=(str(target), '')):
            dialog.save_workspace(); self.wait(dialog)
        original_id = dialog.workspace['workspaceId']
        with patch('desktop.disclosure_workspace.confirm', return_value=True): dialog.roll_forward()
        self.wait(dialog)
        state = dialog.workspace['state']; facts = state['report']['facts']
        self.assertNotEqual(dialog.workspace['workspaceId'], original_id)
        self.assertEqual(state['report']['reporting']['periodEnd'], '2026-12-31')
        self.assertEqual([fact['value'] for fact in facts if fact['rolloverRole'] == 'current-awaiting-values'], [''])
        self.assertEqual([fact['value'] for fact in facts if fact['rolloverRole'] == 'comparative-preserved'], ['100'])
        self.assertEqual(state['notes'][0]['title'], '보유 현금')
        self.assertFalse(state['review']['taxonomyConfirmed'])

    def test_importing_an_exported_draft_preserves_note_prose_links_and_fact_values(self):
        from application.disclosure_workspace import create_workspace, add_note, export_report
        workspace = add_note(create_workspace(report_fixture()), '보존할 주석', '공시 입력 초안의 서술', ['cash'])
        draft = export_report(workspace, self.directory / '주석초안.json')
        dialog = DisclosureWorkspaceDialog(); self.dialogs.append(dialog)
        with patch('desktop.disclosure_workspace.QFileDialog.getOpenFileName', return_value=(str(draft), '')):
            dialog.import_report(); self.wait(dialog)
        self.assertIsNotNone(dialog.workspace, dialog.notice.text())
        state = dialog.workspace['state']
        self.assertEqual(state['notes'][0]['title'], '보존할 주석')
        self.assertEqual(state['notes'][0]['text'], '공시 입력 초안의 서술')
        self.assertEqual(state['notes'][0]['factIds'], ['cash'])
        self.assertEqual(state['report']['facts'][0]['value'], '100')
        self.assertFalse(state['report']['facts'][0]['approved'])

    def test_actual_background_comparison_requires_explicit_conditions_and_applies_scale(self):
        from xbrl_filing.disclosure_compare.examples import create_comparison_example
        example = create_comparison_example(self.directory / 'comparison')
        dialog = DisclosureCompareDialog(); self.dialogs.append(dialog)
        dialog.set_source('dsd', example['dsd']); dialog.set_source('ixd', example['ixd']); dialog.inspect(); self.wait(dialog)
        self.assertIsNotNone(dialog.inspection, dialog.notice.text())
        plan = json.loads(example['mapping'].read_text(encoding='utf-8'))
        for pair in plan['mappings']:
            cell = next(i for i, item in enumerate(dialog.inspection['dsd']['cells']) if item['id'] == pair['dsdCellId'])
            fact = next(i for i, item in enumerate(dialog.inspection['ixd']['facts']) if item['id'] == pair['ixdFactId'])
            dialog.cells.selectRow(cell); dialog.facts.selectRow(fact); dialog.scale.setCurrentIndex(1)
            self.assertIn('202', dialog.conditions.toPlainText())
            dialog.condition_confirmed.setChecked(False); dialog.bind_selected()
            self.assertIn('체크', dialog.notice.text())
            dialog.condition_confirmed.setChecked(True); dialog.bind_selected()
        self.assertEqual(len(dialog.mapping['mappings']), 3)
        dialog.compare(); self.wait(dialog)
        self.assertEqual(dialog.report['status'], 'pass', dialog.report)
        self.assertEqual(dialog.report['counts']['matched'], 3)
        self.assertIn('일치', dialog.result_summary.text())
        self.assertNotIn('mappedPairs', dialog.result_summary.text())

    def test_changed_source_cannot_load_an_old_mapping_or_replace_current_work(self):
        from xbrl_filing.disclosure_compare.examples import create_comparison_example
        from xbrl_filing.disclosure_compare import inspect_disclosures
        example = create_comparison_example(self.directory / 'changed')
        dialog = DisclosureCompareDialog(); self.dialogs.append(dialog)
        dialog.set_source('dsd', example['dsd']); dialog.set_source('ixd', example['ixd'])
        dialog.inspection_ready(inspect_disclosures(example['dsd'], example['ixd']))
        original = deepcopy(dialog.mapping)
        plan = json.loads(example['mapping'].read_text(encoding='utf-8')); plan['sourceHashes']['dsd'] = '0' * 64
        target = self.directory / 'old-mapping.json'; target.write_text(json.dumps(plan), encoding='utf-8')
        with patch('desktop.disclosure_compare.QFileDialog.getOpenFileName', return_value=(str(target), '')): dialog.open_mapping()
        self.assertEqual(dialog.mapping, original)
        self.assertIn('달라', dialog.notice.text())

    def test_search_preserves_original_fact_id_and_blocks_hidden_previous_selection(self):
        from xbrl_filing.disclosure_compare.examples import create_comparison_example
        from xbrl_filing.disclosure_compare import inspect_disclosures
        example = create_comparison_example(self.directory / 'search')
        dialog = DisclosureCompareDialog(); self.dialogs.append(dialog)
        dialog.set_source('dsd', example['dsd']); dialog.set_source('ixd', example['ixd'])
        dialog.inspection_ready(inspect_disclosures(example['dsd'], example['ixd']))
        cells = dialog.inspection['dsd']['cells']; facts = dialog.inspection['ixd']['facts']
        prior_cell = next(i for i, row in enumerate(cells) if row['text'] == '1,100')
        prior_fact = next(i for i, row in enumerate(facts) if row['id'] == 'cash-prior')
        current_fact = next(i for i, row in enumerate(facts) if row['id'] == 'cash-current')
        dialog.cells.selectRow(prior_cell); dialog.facts.selectRow(current_fact)
        dialog.fact_search.setText('Cash 2024-12-31'); dialog.cell_search.setText('1,100')
        self.assertTrue(dialog.facts.isRowHidden(current_fact)); self.assertFalse(dialog.facts.isRowHidden(prior_fact))
        dialog.condition_confirmed.setChecked(True); dialog.bind_selected(); self.assertEqual(dialog.mapping['mappings'], [])
        dialog.facts.selectRow(prior_fact); dialog.scale.setCurrentIndex(1); dialog.condition_confirmed.setChecked(True); dialog.bind_selected()
        self.assertEqual(dialog.mapping['mappings'][0]['ixdFactId'], 'cash-prior')
        self.assertEqual(dialog.mapping['mappings'][0]['expected']['period']['instant'], '2024-12-31')

    def test_csv_export_writes_numbers_as_values_and_neutralizes_formula_source_labels(self):
        path = self.directory / 'comparison.csv'
        export_comparison_csv({'rows': [{'status': 'value-mismatch', 'label': '=HYPERLINK("bad")', 'dsdValue': '100', 'ixdValue': '99', 'difference': '1'}]}, path)
        text = path.read_text(encoding='utf-8-sig')
        self.assertIn("'=HYPERLINK", text)
        self.assertIn('100,99,1', text)


if __name__ == '__main__':
    unittest.main()
