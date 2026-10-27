"""Exercise saved-export checks, previews, source links, HTML and cancellation."""
import argparse,json,sys,tempfile,time
from pathlib import Path
from unittest.mock import patch,Mock
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
if (ROOT/'.build-tools').exists():sys.path.insert(0,str(ROOT/'.build-tools'))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from application.configuration import default_profile
from application.xbrl_inspection import inspect_export
from desktop.window import MainWindow
from desktop.controllers.app import AppController
from desktop.dialogs.xbrl_inspection import XbrlInspectionDialog
from desktop.theme.typography import configure_typography
from desktop.theme.styles import stylesheet
from xbrl_gl.control import ExportCancelled
from workflow_fixtures import csv_file,profile

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True);args=parser.parse_args()
    output=Path(args.out).resolve();output.mkdir(parents=True,exist_ok=False)
    app=QApplication([]);app.setStyle('Fusion');app.setStyleSheet(stylesheet(configure_typography(app)))
    def wait(predicate):
        deadline=time.monotonic()+45
        while predicate() and time.monotonic()<deadline:app.processEvents();time.sleep(.01)
        app.processEvents();assert not predicate(),'작업 시간 초과'
    with tempfile.TemporaryDirectory(dir=output) as temp:
        private=Path(temp)
        with patch('application.paths.user_data',return_value=private),patch('application.catalogs.user_data',return_value=private),patch('application.presets.user_data',return_value=private),patch('application.workfiles.user_data',return_value=private):
            window=MainWindow(default_profile());window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen);controller=AppController(window);window.controller=controller;window.show()
            controller.open_files([csv_file(private)]);wait(lambda:window.busy)
            controller.home.company.setText('A');controller.home.system.setText('ERP-X');controller.home.reviewer.setText('시험 설정');controller.home.history.setChecked(False)
            controller.columns.apply_profile(profile());controller.load();wait(lambda:window.busy)
            for code,target in {'001':'A1102','002':'A1201','003':'R4101'}.items():
                row=next(i for i,r in enumerate(controller.mapping.visible) if r['originalCode']==code);controller.mapping.table.selectRow(row);app.processEvents()
                editor=controller.mapping.editor;editor.target.setCurrentIndex(editor.target.findData(target));editor.accept.click();wait(lambda:window.busy)
            window.show_page(3)
            with patch('desktop.controllers.xbrl_export.QFileDialog.getExistingDirectory',return_value=str(output/'exports')):
                window.action.click();wait(lambda:window.busy)
            folder=controller.results.output_path;assert (folder/'검사결과.html').is_file() and controller.results.open_report.isEnabled()
            result=inspect_export(folder);assert result['passed']
            dialog=XbrlInspectionDialog(folder,result,controller.session,window);dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen);dialog.show();wait(lambda:dialog.loading)
            assert dialog.table.data_model.rowCount()==3 and dialog.original.isEnabled()
            app.processEvents();assert dialog.grab().save(str(output/'inspection-checks.png'))
            dialog.tabs.setCurrentIndex(1);app.processEvents();assert dialog.grab().save(str(output/'inspection-rows.png'))
            target=output/'reinspection.html'
            with patch('desktop.dialogs.xbrl_inspection.QFileDialog.getSaveFileName',return_value=(str(target),'')):dialog.save_report()
            assert target.is_file()
            source=Mock()
            with patch('desktop.dialogs.xbrl_inspection.SourceDialog',return_value=source):dialog.original.click()
            source.exec.assert_called_once();dialog.reject();dialog.jobs.pool.waitForDone()
            def cancellable(session,folder,progress,cancel):
                progress({'stage':'XML 저장','completed':100,'total':10000})
                assert cancel.wait(10),'취소 요청이 전달되지 않음'
                raise ExportCancelled('XML 저장을 취소했어요.')
            with patch('desktop.controllers.xbrl_export.export_xbrl',side_effect=cancellable),patch('desktop.controllers.xbrl_export.QFileDialog.getExistingDirectory',return_value=str(output/'cancelled')):
                window.action.click();assert window.cancel_export.isVisible();window.cancel_export.click();wait(lambda:window.busy)
            assert controller.session.result['status']=='계정매핑완료' and controller.results.output_path==folder
            assert not (output/'cancelled').exists() and not window.cancel_export.isVisible()
            assert any(action.text()=='저장한 XML 다시 검사' for menu in window.menuBar().actions() for action in menu.menu().actions())
            controller.force_close=True;window.close();controller.jobs.pool.waitForDone()
    report={'xmlSavedFromHeader':True,'htmlReportCreated':True,'savedExportReinspected':True,'pageRows':3,'sourceLinkClicked':True,
            'reinspectionHtmlSaved':True,'cancelButtonExercised':True,'workPreservedOnCancel':True,'standaloneInspectionMenu':True,
            'nativeFileDialogsMocked':True,'xmlCancelFunctionMocked':True}
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report))

if __name__=='__main__':main()
