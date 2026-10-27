from PySide6.QtWidgets import QFileDialog
from application.xbrl_inspection import inspect_export
from application.paths import default_outputs
from desktop.dialogs.xbrl_inspection import XbrlInspectionDialog

def choose_and_inspect(controller):
    if controller.window.busy:return
    path=QFileDialog.getExistingDirectory(controller.window,'검사할 XBRL 결과 폴더 선택',str(controller.results.output_path or default_outputs()))
    if not path:return
    controller.window.set_busy(True,'저장한 XML·원본 연결·스키마를 다시 확인하고 있어요.')
    def ready(result):
        controller.finish_job()
        dialog=XbrlInspectionDialog(path,result,controller.session,controller.window)
        dialog.exec()
    controller.jobs.start(lambda:inspect_export(path),ready,controller.failure)
