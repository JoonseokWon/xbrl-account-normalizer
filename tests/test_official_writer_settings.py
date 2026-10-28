"""Required GCD date entry tests; dates are explicit and never guessed."""
from copy import deepcopy
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
try:
    from PySide6.QtWidgets import QApplication
    from desktop.dialogs.official_writer_settings import WriterSettingsDialog
    QT=True
except ImportError:QT=False


@unittest.skipUnless(QT,'PySide6 required for native settings tests')
class OfficialWriterSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.report={'entity':{'name':'검증회사','identifier':'00123456'},
                     'reporting':{'periodStart':'2026-01-01','periodEnd':'2026-12-31','consolidation':'별도'},
                     'facts':[{'reviewer':'검토자'}]}
        self.original=deepcopy(self.report);self.dialog=WriterSettingsDialog(self.report)
        for key,value in {'companyNameEn':'Reviewed Company','ordinalYear':'12'}.items():self.dialog.fields[key].setText(value)
        for key,value in {'BS':'D1001','PL':'D2001','CE':'D3001','CF':'D4002'}.items():self.dialog.forms[key].setText(value)
    def tearDown(self):self.dialog.close();self.dialog.deleteLater();self.app.processEvents()
    def fill_periods(self):
        for key,values in {'priorPeriod':{'start':'2025-01-01','end':'2025-12-31'},
                           'secondPriorPeriod':{'start':'2024-01-01','end':'2024-12-31'}}.items():
            for boundary,value in values.items():self.dialog.periods[key][boundary].setText(value)

    def test_all_four_prior_dates_are_required_and_not_derived_from_current_period(self):
        for fields in self.dialog.periods.values():
            for field in fields.values():self.assertEqual(field.text(),'')
        self.dialog.accept_settings();self.assertIsNone(self.dialog.value);self.assertIn('네 날짜',self.dialog.notice.text())
        self.fill_periods();self.dialog.periods['secondPriorPeriod']['end'].clear();self.dialog.accept_settings()
        self.assertIsNone(self.dialog.value);self.assertIn('네 날짜',self.dialog.notice.text())

    def test_explicit_dates_are_passed_and_namespace_remains_derived_from_cik_and_date(self):
        self.fill_periods();self.dialog.accept_settings();value=self.dialog.value
        self.assertIsNotNone(value);self.assertEqual(value['priorPeriod'],{'start':'2025-01-01','end':'2025-12-31'})
        self.assertEqual(value['secondPriorPeriod'],{'start':'2024-01-01','end':'2024-12-31'})
        self.assertEqual(value['extensionPrefix'],'entity00123456')
        self.assertEqual(value['extensionNamespace'],'http://dart.fss.or.kr/taxonomy/2026-12-31/entity00123456')
        self.assertNotIn('extensionNamespace',self.dialog.fields);self.assertEqual(self.report,self.original)

    def test_invalid_calendar_dates_and_period_overlap_block_acceptance(self):
        cases=[('priorPeriod','start','2025-02-30','실제 달력'),('priorPeriod','start','20250101','YYYY-MM-DD'),
               ('priorPeriod','start','2026-01-01','시작일'),('priorPeriod','end','2026-01-01','당기 시작일'),
               ('secondPriorPeriod','end','2025-01-01','전기 시작일')]
        for key,boundary,value,message in cases:
            with self.subTest(key=key,boundary=boundary,value=value):
                self.fill_periods();self.dialog.periods[key][boundary].setText(value);self.dialog.accept_settings()
                self.assertIsNone(self.dialog.value);self.assertIn(message,self.dialog.notice.text())

    def test_zero_or_negative_ordinal_and_unverified_quarterly_route_are_blocked(self):
        self.fill_periods()
        for value in ('0','-1','1.5'):
            self.dialog.fields['ordinalYear'].setText(value);self.dialog.accept_settings()
            self.assertIsNone(self.dialog.value);self.assertIn('1 이상의 정수',self.dialog.notice.text())
        self.dialog.fields['ordinalYear'].setText('12');self.dialog.title.setCurrentText('반기보고서');self.dialog.accept_settings()
        self.assertIsNone(self.dialog.value);self.assertIn('사업보고서만 지원',self.dialog.notice.text())

    def test_saved_explicit_period_settings_can_be_reopened_without_guessing(self):
        report=deepcopy(self.report);report['officialWriterSettings']={
            'priorPeriod':{'start':'2025-04-01','end':'2025-12-31'},
            'secondPriorPeriod':{'start':'2024-04-01','end':'2025-03-31'}}
        reopened=WriterSettingsDialog(report)
        try:
            self.assertEqual(reopened.periods['priorPeriod']['start'].text(),'2025-04-01')
            self.assertEqual(reopened.periods['secondPriorPeriod']['end'].text(),'2025-03-31')
        finally:reopened.close();reopened.deleteLater();self.app.processEvents()


if __name__=='__main__':unittest.main()
