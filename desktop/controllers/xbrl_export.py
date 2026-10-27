from PySide6.QtWidgets import QFileDialog
from application.xbrl_export import export_xbrl
from application.paths import default_outputs

def choose_and_export_xbrl(controller):
    if controller.window.busy or not controller.session:return
    folder=QFileDialog.getExistingDirectory(controller.window,'XBRL GL XML을 저장할 위치 선택',str(default_outputs().parent))
    if not folder:return
    session=controller.session
    controller.window.set_busy(True,'XBRL GL XML을 만들고 공식 스키마와 원본 행을 확인하고 있어요.')
    controller.jobs.start(lambda:export_xbrl(session,folder),controller.xbrl_export_ready,controller.failure)
