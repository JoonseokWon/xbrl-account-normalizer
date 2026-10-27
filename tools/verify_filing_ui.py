"""Exercise real filing services through Qt; OS file choosers use test paths.

Requires a user-supplied official local DTS and optionally a DART reference
workbook. The script never downloads or redistributes either taxonomy.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
if (ROOT/'.build-tools').exists():sys.path.insert(0,str(ROOT/'.build-tools'))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from application.filing import load_filing_work
from desktop.dialogs.filing import FilingDialog
from desktop.theme.styles import stylesheet
from desktop.theme.typography import configure_typography
from tools.verify_filing import example_report
from version import VERSION


def run_checks(folder,taxonomy,dart_reference=None):
    start=time.monotonic();output=Path(folder).resolve();output.mkdir(parents=True,exist_ok=False)
    app=QApplication.instance() or QApplication([]);app.setStyle('Fusion');app.setStyleSheet(stylesheet(configure_typography(app)))
    diagnostics=[];dialogs=[]
    def step(name):
        record={'step':name,'seconds':round(time.monotonic()-start,3)};diagnostics.append(record)
        print(json.dumps(record,ensure_ascii=False),flush=True)
    def wait(dialog,name):
        deadline=time.monotonic()+150
        while dialog.loading and time.monotonic()<deadline:app.processEvents();time.sleep(.01)
        app.processEvents()
        if dialog.loading:raise AssertionError(name+': Qt 작업 시간 초과')
        step(name)
    def create():
        dialog=FilingDialog(session=None);dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen);dialog.show();app.processEvents();dialogs.append(dialog)
        assert dialog.session is None and not dialog.from_session_button.isEnabled()
        return dialog
    def choose_input(dialog,path):
        with patch('desktop.dialogs.filing.QFileDialog.getOpenFileName',return_value=(str(path),'')):dialog.action_buttons[1].click()
        wait(dialog,'input-loaded')
        assert len(dialog.report['facts'])>0,dialog.notice.text()
    def approve_every_row(dialog,expected):
        dialog.tabs.setCurrentIndex(1);dialog.reviewer.setText('GUI 시험 확인자')
        assert len(dialog.report['facts'])==expected,dialog.notice.text()
        for index in range(expected):
            dialog.fact_table.selectRow(index);app.processEvents()
            assert dialog.active_row==index
            assert dialog.concept.currentData()==dialog.report['facts'][index]['concept']
            dialog.approve.click();app.processEvents()
            assert dialog.report['facts'][index]['approved'],(index,dialog.notice.text())
        assert all(f['reviewer']=='GUI 시험 확인자' for f in dialog.report['facts'])
        step('rows-approved-'+str(expected))
    def export(dialog,name):
        parent=output/name;parent.mkdir()
        with patch('desktop.dialogs.filing.QFileDialog.getExistingDirectory',return_value=str(parent)):dialog.export_button.click()
        wait(dialog,'export-'+name)
        assert dialog.last_export and dialog.last_export.is_dir(),dialog.notice.text()
        assert dialog.open_folder.isEnabled()
        return dialog.last_export,json.loads((dialog.last_export/'validation-report.json').read_text(encoding='utf-8'))
    with tempfile.TemporaryDirectory(prefix='private-ui-',dir=output) as private:
        private=Path(private)
        with patch('application.paths.user_data',return_value=private):
            try:
                dialog=create();source=output/'공시예제.json'
                source.write_text(json.dumps(example_report(),ensure_ascii=False,indent=2),encoding='utf-8')
                choose_input(dialog,source)
                assert len(dialog.report['facts'])==30 and all(not f['approved'] for f in dialog.report['facts'])
                with patch('desktop.dialogs.filing.QFileDialog.getOpenFileName',return_value=(str(Path(taxonomy).resolve()),'')):dialog.action_buttons[0].click()
                wait(dialog,'official-dts-loaded')
                assert dialog.catalog and dialog.catalog.get('mode')!='dart-reference',dialog.notice.text()
                assert dialog.catalog['concepts'].get('ifrs-full:Assets')
                approve_every_row(dialog,30)
                work=output/'공시업무.acfiling'
                with patch('desktop.dialogs.filing.QFileDialog.getSaveFileName',return_value=(str(work),'')):dialog.action_buttons[5].click()
                wait(dialog,'work-saved')
                restored=load_filing_work(work)
                assert restored['facts']==dialog.report['facts'] and all(f['approved'] for f in restored['facts'])
                with patch('desktop.dialogs.filing.QFileDialog.getOpenFileName',return_value=(str(work),'')):dialog.action_buttons[4].click()
                wait(dialog,'work-reopened')
                assert all(f['approved'] for f in dialog.report['facts']),dialog.notice.text()
                dialog.tabs.setCurrentIndex(0);app.processEvents();assert dialog.grab().save(str(output/'filing-company.png'))
                dialog.tabs.setCurrentIndex(1);dialog.fact_table.selectRow(28);app.processEvents();assert dialog.grab().save(str(output/'filing-facts.png'))
                target,validation=export(dialog,'xml-exports')
                assert validation['passed'] and validation['factCount']==30
                assert (target/'financial-report.xbrl').is_file() and (target/'공시검사결과.html').is_file()
                assert validation['validator']=='Arelle' and validation['dartSubmission']['status']=='not-performed'
                app.processEvents();assert dialog.grab().save(str(output/'filing-saved.png'))
                assert dialog.session is None
                result={'version':VERSION,'ok':True,'syntheticOnly':True,'nativeFileDialogsMocked':True,'exportFunctionsMocked':False,
                    'currentGlSession':None,'glSessionPreserved':True,'ifrsFactsApprovedThroughUi':30,'workSavedAndReopened':True,
                    'sameTaxonomyApprovalsRestored':True,'xmlOutput':target.relative_to(output).as_posix(),
                    'validator':validation['validator'],'validatorVersion':validation['version'],'actualDtsValidated':True,
                    'dartSubmissionValidated':False,'scope':'실제 Qt 입력/승인/업무/출력 서비스 확인. OS 파일선택창만 시험 경로로 대체. 공시 접수·회계 적정성·실사용 자료 검증은 아님.'}
                if dart_reference:
                    dart=create();draft=deepcopy(example_report())
                    draft['facts']=[f for f in draft['facts'] if f['statement']=='BS' and f['period'].get('instant')=='2026-12-31']
                    source=output/'DART_공시예제.json';source.write_text(json.dumps(draft,ensure_ascii=False,indent=2),encoding='utf-8')
                    choose_input(dart,source)
                    with patch('desktop.dialogs.filing.QFileDialog.getOpenFileName',return_value=(str(Path(dart_reference).resolve()),'')):dart.action_buttons[6].click()
                    wait(dart,'dart-reference-loaded')
                    assert dart.catalog and dart.catalog.get('mode')=='dart-reference',dart.notice.text()
                    assert dart.role_filter.count()>1
                    assert '대사표' in dart.export_button.text()
                    approve_every_row(dart,7)
                    target,checked=export(dart,'dart-exports')
                    assert checked['metadataChecksPassed'] and checked['xmlGenerated'] is False
                    assert checked['validationScope']=='concept-metadata-only'
                    assert not list(target.glob('*.xbrl')) and not list(target.glob('*.xml'))
                    assert (target/'공시대사결과.html').is_file()
                    app.processEvents();assert dart.grab().save(str(output/'dart-handoff-saved.png'))
                    assert dart.session is None
                    result.update(dartFactsApprovedThroughUi=7,dartRoleChoices=dart.role_filter.count(),dartMetadataOnly=True,
                        dartXmlGenerated=False,dartOutput=target.relative_to(output).as_posix())
                result.update(seconds=round(time.monotonic()-start,3),steps=diagnostics)
                (output/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
                print(json.dumps(result,ensure_ascii=False),flush=True);return result
            except Exception as error:
                (output/'failure.json').write_text(json.dumps({'error':str(error),'steps':diagnostics,
                    'notices':[d.notice.text() for d in dialogs]},ensure_ascii=False,indent=2),encoding='utf-8')
                raise
            finally:
                for dialog in dialogs:
                    if dialog.loading:dialog.jobs.pool.waitForDone(190_000);app.processEvents()
                    dialog.dirty=False;dialog.close();dialog.jobs.pool.waitForDone()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True);parser.add_argument('--taxonomy',required=True)
    parser.add_argument('--dart-reference');args=parser.parse_args();run_checks(args.out,args.taxonomy,args.dart_reference)


if __name__=='__main__':main()
