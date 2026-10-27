"""Review-state regression checks; these do not certify DART acceptance."""
import os
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
try:
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from desktop.dialogs.filing import FilingDialog,empty_report,parse_comparative_periods
    QT=True
except ImportError:
    QT=False


@unittest.skipUnless(QT,'PySide6 is required for native UI review tests')
class FilingUiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.dialog=FilingDialog()
        self.dialog.catalog={'fingerprint':'abc123','entryPoint':'official.xsd','concepts':{'ifrs:Assets':{'label':'자산','periodType':'instant','abstract':False,'type':'monetaryItemType'}}}
        self.dialog.report=empty_report()
        self.dialog.report['facts']=[{'id':'f1','originalName':'자산총계','concept':'ifrs:Assets','statement':'BS',
            'value':'100','period':{'kind':'instant','instant':'2026-12-31'},'unit':'KRW','decimals':'0',
            'dimensions':{},'source':'source.csv:2','reviewer':'검토자','approved':True}]
        self.dialog.populate_report();self.dialog.dirty=False

    def tearDown(self):
        self.dialog.dirty=False;self.dialog.close();self.dialog.deleteLater();self.app.processEvents()

    def test_editing_an_approved_fact_revokes_approval(self):
        self.dialog.fact_value.setFocus();QTest.keyClicks(self.dialog.fact_value,'1')
        self.assertFalse(self.dialog.report['facts'][0]['approved'])
        self.assertTrue(self.dialog.editor_dirty)
        self.assertTrue(self.dialog.apply_fact(False))
        self.assertEqual(self.dialog.report['facts'][0]['value'],'1001')

    def test_pending_facts_cannot_reach_the_export_file_picker(self):
        self.dialog.report['facts'][0]['approved']=False
        with patch('desktop.dialogs.filing.QFileDialog.getExistingDirectory') as chooser:
            self.dialog.export();chooser.assert_not_called()
        self.assertIn('승인',self.dialog.notice.text())

    def test_period_mismatch_and_malformed_dimensions_cannot_be_approved(self):
        self.dialog.period_kind.setCurrentText('duration');self.dialog.fact_start.setText('2026-01-01');self.dialog.fact_end.setText('2026-12-31')
        self.assertFalse(self.dialog.apply_fact(True))
        self.assertFalse(self.dialog.report['facts'][0]['approved'])
        self.dialog.period_kind.setCurrentText('instant');self.dialog.dimensions.setPlainText('[]')
        self.assertFalse(self.dialog.apply_fact(True))
        self.assertIn('JSON',self.dialog.notice.text())

    def test_company_scope_edit_revokes_every_fact_approval(self):
        self.dialog.entity_id.setFocus();QTest.keyClicks(self.dialog.entity_id,'12345678')
        self.assertTrue(all(not row['approved'] for row in self.dialog.report['facts']))

    def test_switching_rows_keeps_edits_and_selects_the_requested_row(self):
        other=deepcopy(self.dialog.report['facts'][0]);other.update(id='f2',value='200',originalName='비교 자산총계')
        self.dialog.report['facts'].append(other);self.dialog.populate_report()
        self.dialog.fact_value.setFocus();QTest.keyClicks(self.dialog.fact_value,'1')
        self.dialog.fact_table.selectRow(1)
        self.assertEqual(self.dialog.report['facts'][0]['value'],'1001')
        self.assertFalse(self.dialog.report['facts'][0]['approved'])
        self.assertEqual(self.dialog.active_row,1)
        self.assertEqual(self.dialog.fact_table.currentIndex().row(),1)
        self.assertEqual(self.dialog.fact_value.text(),'200')

    def test_approval_binds_the_current_taxonomy_and_reviewer(self):
        self.dialog.reviewer.setText('확인자')
        self.assertTrue(self.dialog.apply_fact(True))
        self.assertTrue(self.dialog.report['facts'][0]['approved'])
        self.assertEqual(self.dialog.report['facts'][0]['reviewer'],'확인자')
        self.assertEqual(self.dialog.report['taxonomyFingerprint'],'abc123')

    def test_a_supported_long_note_is_not_silently_truncated_when_approved(self):
        self.dialog.catalog['concepts']['ifrs:Note']={'label':'주석','periodType':'duration','abstract':False,'type':'stringItemType'}
        note='가'*100_000
        self.dialog.report['facts'][0].update(concept='ifrs:Note',statement='NOTE',value=note,unit='',decimals='',
            period={'kind':'duration','start':'2026-01-01','end':'2026-12-31'})
        self.dialog.populate_report();self.dialog.reviewer.setText('확인자')
        self.assertEqual(self.dialog.fact_value.text(),note)
        self.assertTrue(self.dialog.apply_fact(True))
        self.assertEqual(self.dialog.report['facts'][0]['value'],note)

    def test_comparative_periods_are_explicit_unique_and_bounded(self):
        periods=parse_comparative_periods('2025-01-01~2025-12-31;2024-01-01~2024-12-31')
        self.assertEqual(len(periods),2)
        for text in ('2025-01-01~2025-12-31;2025-01-01~2025-12-31','2025-12-31~2025-01-01','20250101~20251231',
                     ';'.join(str(year)+'-01-01~'+str(year)+'-12-31' for year in range(2021,2025))):
            with self.subTest(text=text),self.assertRaises(ValueError):parse_comparative_periods(text)


if __name__=='__main__':unittest.main()
