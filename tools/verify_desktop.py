"""Exercise source Qt widgets and worker jobs; OS file dialogs use test paths."""
import argparse,json,sys,tempfile,time
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
if (ROOT/'.build-tools').exists():sys.path.insert(0,str(ROOT/'.build-tools'))
from PySide6.QtWidgets import QApplication,QTabWidget,QTableWidgetItem
from PySide6.QtCore import Qt,QTimer
from application.configuration import default_profile
from application.paths import user_data
from desktop.window import MainWindow
from desktop.controllers.app import AppController
from desktop.theme.typography import configure_typography
from desktop.theme.styles import stylesheet
from desktop.dialogs.catalog import CatalogDialog
from desktop.dialogs.support import SupportDialog
from desktop.dialogs.source import SourceDialog
from workflow_fixtures import csv_file,profile,support_config

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True);args=parser.parse_args()
    output=Path(args.out).resolve();output.mkdir(parents=True,exist_ok=False)
    app=QApplication([]);app.setStyle('Fusion');app.setStyleSheet(stylesheet(configure_typography(app)))
    def wait(controller):
        deadline=time.monotonic()+40
        while controller.window.busy and time.monotonic()<deadline:app.processEvents();time.sleep(.01)
        app.processEvents();assert not controller.window.busy,'작업 시간 초과'
    def shot(window,name):
        app.processEvents();assert window.grab().save(str(output/(name+'.png')))
    with tempfile.TemporaryDirectory(dir=output,prefix='qa-private-') as temp:
        private=Path(temp)
        with patch('application.paths.user_data',return_value=private),patch('application.catalogs.user_data',return_value=private),patch('application.presets.user_data',return_value=private),patch('application.workfiles.user_data',return_value=private):
            window=MainWindow(default_profile());window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen);controller=AppController(window);window.controller=controller;window.show()
            source=csv_file(private);controller.open_files([source]);wait(controller)
            controller.home.company.setText('A');controller.home.system.setText('ERP-X');controller.home.reviewer.setText('시험 검토자');controller.home.history.setChecked(False)
            controller.home.period_start.setText('2026-01-01');controller.home.period_end.setText('2026-01-31')
            shot(window,'overview');controller.columns.apply_profile(profile());window.show_page(1);shot(window,'columns')
            controller.load();wait(controller);assert controller.session.result['counts']['pendingRows']==3
            targets={'001':'A1102','002':'A1201','003':'R4101'}
            for code,target in targets.items():
                i=next(i for i,r in enumerate(controller.mapping.visible) if r['originalCode']==code)
                controller.mapping.table.selectRow(i);app.processEvents();editor=controller.mapping.editor
                editor.target.setCurrentIndex(editor.target.findData(target));editor.accept.click();wait(controller)
            assert controller.session.result['counts']['pendingRows']==0;shot(window,'mapping')
            window.show_page(3);tabs=controller.results.findChild(QTabWidget);tabs.setCurrentWidget(controller.results.journals);app.processEvents()
            assert controller.results.journals.debits.data_model.rowCount()==2 and controller.results.journals.credits.data_model.rowCount()==1
            shot(window,'journals');window.resize(1070,740);shot(window,'journals-minimum');window.resize(1420,960)
            ref=controller.session.result['ledger'][0]['source'];original=SourceDialog(controller.session,ref,window);original.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen);original.show();shot(original,'original-row');original.close()
            support=support_config(private);dialog=SupportDialog(controller.session,window)
            for name,spec in support['tables'].items():
                pane=dialog.tables[name];pane.path=spec['path'];pane.restore(spec);pane.inspect()
            shot(dialog,'support-columns')
            support_tabs=dialog.findChild(QTabWidget)
            support_tabs.setCurrentIndex(1);shot(dialog,'support-trialbalance')
            support_tabs.setCurrentIndex(2);shot(dialog,'support-controls')
            with patch('desktop.controllers.app.SupportDialog',return_value=dialog):
                QTimer.singleShot(0,dialog.accept);controller.connect_support();wait(controller)
            assert controller.session.support_bundle and all(r['status']=='일치' for r in controller.results.checks)
            tabs.setCurrentWidget(controller.results.reconciliation);shot(window,'reconciliation')
            controller.work_actions.save_preset();assert list((private/'input_presets').glob('*.json'))
            controller.columns.selectors['gl'].controls['account'].setCurrentIndex(0)
            controller.work_actions.load_preset();wait(controller)
            assert controller.columns.selectors['gl'].controls['account'].currentData()=='Code'
            work=private/'saved.acwork'
            with patch('desktop.controllers.work_actions.QFileDialog.getSaveFileName',return_value=(str(work),'')):
                controller.work_actions.save_work();wait(controller)
            assert work.is_file() and not controller.session.dirty
            with patch('desktop.controllers.work_actions.QFileDialog.getOpenFileName',return_value=(str(work),'')):
                controller.work_actions.open_work();wait(controller)
            assert controller.session.result['counts']['pendingRows']==0 and controller.session.support_bundle
            resumed_support=SupportDialog(controller.session,window)
            assert resumed_support.start.text()=='2026-01-01' and resumed_support.tables['시산표'].path
            assert resumed_support.tables['독립통제'].controls['차변합계'][0].currentData()=='source_5'
            resumed_support.reject()
            with patch('desktop.controllers.audit_export.QFileDialog.getExistingDirectory',return_value=str(output/'audit-output')):
                controller.results.audit_save.click();wait(controller)
            assert controller.results.output_path and (controller.results.output_path/'통합감사_원장입력.xlsx').is_file()
            assert controller.results.xbrl_save.isEnabled()
            assert window.action.text()=='XBRL GL XML 저장'
            with patch('desktop.controllers.xbrl_export.QFileDialog.getExistingDirectory',return_value=str(output/'xbrl-output')):
                window.action.click();wait(controller)
            assert (controller.results.output_path/'validation-report.json').is_file()
            assert len(list(controller.results.output_path.glob('*.xbrl')))==1
            shot(window,'xbrl-result')
            initial_accounts=len(controller.catalog['accounts'])
            editor=CatalogDialog(controller.catalog,window);editor.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen);editor.add_row()
            values=['X999','사용자 추가 계정','상세계정','','CUSTOM','BS','원장·리드','별도 계정']
            for col,value in enumerate(values):editor.table.setItem(editor.table.rowCount()-1,col,QTableWidgetItem(value))
            editor.show();shot(editor,'catalog')
            with patch('desktop.controllers.work_actions.CatalogDialog',return_value=editor):
                QTimer.singleShot(0,editor.submit);controller.work_actions.catalog();wait(controller)
            assert len(controller.catalog['accounts'])==initial_accounts+1 and controller.session.result['counts']['pendingRows']==3
            window.show_page(4);shot(window,'help')
            controller.force_close=True;window.close();controller.jobs.pool.waitForDone();controller.session._restored_temp.cleanup()
    report={'sourceWidgetsExercised':True,'mappingButtonsClicked':3,'compoundDebitRows':2,'compoundCreditRows':1,
            'supportMappingDialog':True,'reconciliationMatched':True,'presetSavedAndLoaded':True,'workSavedAndReopened':True,
            'catalogEditedAndMappingsInvalidated':True,
            'auditSaveButtonClicked':True,'auditWorkbookCreated':True,'minimumWindowRendered':[1070,740],
            'xbrlSaveButtonClicked':True,'xbrlInstanceCreated':True,
            'nativeFileDialogsMocked':True,'actualOsFilePickerExercised':False}
    (output/'desktop-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
