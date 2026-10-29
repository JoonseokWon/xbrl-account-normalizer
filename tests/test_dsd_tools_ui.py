"""End-to-end DSD desktop contracts without OS mouse or keyboard input."""
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    from PySide6.QtWidgets import QApplication
    from desktop.dsd_tools import DsdToolsDialog
    QT = True
except ImportError:
    QT = False

XML = '''<?xml version="1.0" encoding="UTF-8"?>
<DOCUMENT><TITLE>재무제표 검토 예제</TITLE><P>단위: 원</P>
<TABLE><THEAD><TR><TH>과목</TH><TH>2025년</TH><TH>2024년</TH></TR></THEAD>
<TBODY><TR><TD>보통예금</TD><TD>100</TD><TD>80</TD></TR>
<TR><TD>재고자산</TD><TD>200</TD><TD>150</TD></TR></TBODY></TABLE></DOCUMENT>'''


@unittest.skipUnless(QT, 'PySide6 is required')
class DsdToolsUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.before = self.root / '원본.xml'; self.before.write_text(XML, encoding='utf-8')
        self.after = self.root / '수정.xml'; self.after.write_text(XML.replace('>100<', '>120<'), encoding='utf-8')
        self.dialog = DsdToolsDialog()

    def tearDown(self):
        self.wait(); self.dialog.close(); self.dialog.deleteLater(); self.app.processEvents(); self.temp.cleanup()

    def wait(self):
        deadline = time.monotonic() + 30
        while self.dialog.loading and time.monotonic() < deadline:
            self.app.processEvents(); time.sleep(.002)
        self.app.processEvents()
        self.assertFalse(self.dialog.loading, self.dialog.notice.text())

    def extracted(self):
        panel = self.dialog.extract; panel.source.setText(str(self.before)); path = self.root / '표.xlsx'
        panel.export_to(path); self.wait(); self.assertTrue(path.is_file(), self.dialog.notice.text())
        return path

    def test_four_menu_actions_open_the_requested_tab(self):
        from application.configuration import default_profile
        from desktop.window import MainWindow
        window = MainWindow(default_profile())
        self.assertEqual(len(window.dsd_tools_actions), 4)
        with patch('desktop.dsd_tools.DsdToolsDialog') as dialog:
            for index, action in enumerate(window.dsd_tools_actions):
                action.trigger(); self.assertEqual(dialog.call_args.kwargs['tab'], index)
        window.close(); window.deleteLater()

    def test_extraction_is_a_background_operation_and_does_not_overwrite(self):
        path = self.extracted(); previous = path.read_bytes()
        self.dialog.extract.export_to(path); self.wait()
        self.assertEqual(path.read_bytes(), previous)
        self.assertFalse(self.dialog.loading)

    def compare(self):
        panel = self.dialog.versions; panel.before.setText(str(self.before)); panel.after.setText(str(self.after))
        panel.compare(); self.wait()
        self.assertIsNotNone(self.dialog.version_report, self.dialog.notice.text())

    def test_comparison_html_and_source_change_invalidation(self):
        self.compare(); self.dialog.html.reviewer.setText('검토 담당자')
        self.dialog.html.notes.setPlainText('예금 증감 확인')
        output = self.root / '검토.html'; self.dialog.html.export_to(output); self.wait()
        self.assertTrue(output.is_file(), self.dialog.notice.text())
        html = output.read_text(encoding='utf-8'); self.assertIn('예금 증감 확인', html)
        self.dialog.versions.after.setText(str(self.before))
        self.assertIsNone(self.dialog.version_report); self.assertFalse(self.dialog.html.export_button.isEnabled())

    def test_changed_source_blocks_html_export(self):
        self.compare(); self.after.write_text(XML.replace('>100<', '>130<'), encoding='utf-8')
        output = self.root / 'stale.html'; self.dialog.html.export_to(output); self.wait()
        self.assertFalse(output.exists())

    def test_direct_mapping_requires_confirmation_and_source_hash_stays_bound(self):
        workbook = self.extracted(); panel = self.dialog.roundtrip
        panel.mode.setCurrentIndex(1); panel.template.setText(str(self.before)); panel.workbook_path.setText(str(workbook))
        panel.read(); self.wait(); self.assertIsNotNone(panel.inventory, self.dialog.notice.text())
        source = next(c for c in panel.workbook['cells'] if str(c.get('value')) == '100')
        panel.sheet.setCurrentText(source['sheet']); panel.coordinate.setText(source['cell'])
        target = next(i for i, c in enumerate(panel.visible_targets) if c['text'] == '200')
        panel.targets.selectRow(target); panel.add_link()
        self.assertEqual(len(panel.links), 1)
        output = self.root / '새초안.xml'; self.assertFalse(panel.export_to(output)); self.assertFalse(output.exists())
        panel.confirmed.setChecked(True); panel.export_to(output); self.wait()
        self.assertTrue(output.is_file(), self.dialog.notice.text())
        from xbrl_filing.disclosure_compare.dsd import read_dsd
        self.assertEqual(sum(c['text'] == '100' for c in read_dsd(output)['cells']), 2)
        # Re-read is required; a changed source must never be rebound silently.
        self.before.write_text(XML.replace('>200<', '>999<'), encoding='utf-8')
        panel.confirmed.setChecked(True); stale = self.root / '바뀐초안.xml'; panel.export_to(stale); self.wait()
        self.assertFalse(stale.exists())

    def test_busy_dialog_cannot_close_or_start_a_second_job(self):
        self.dialog.loading = True
        try:
            self.assertFalse(self.dialog.run_job(lambda: 1, lambda _: None, '작업 중'))
            self.dialog.reject(); self.assertTrue(self.dialog.loading)
        finally: self.dialog.finish()


if __name__ == '__main__': unittest.main()
