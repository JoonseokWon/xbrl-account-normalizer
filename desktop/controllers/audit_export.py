from PySide6.QtWidgets import QFileDialog
from application.audit_export import export_audit_input
from application.paths import default_outputs


def choose_and_export(controller):
    if controller.window.busy or not controller.session:return
    support,_=QFileDialog.getOpenFileName(controller.window,'시산표·통제가 있는 보조파일 선택','','엑셀 통합문서 (*.xlsx)')
    if not support:return
    folder=QFileDialog.getExistingDirectory(controller.window,'통합감사 입력을 저장할 위치 선택',str(default_outputs().parent))
    if not folder:return
    controller.window.set_busy(True,'보조자료와 원장을 비교하고 통합감사 입력을 만들고 있어요.')
    session=controller.session
    controller.jobs.start(lambda:export_audit_input(session,support,folder),controller.audit_export_ready,controller.failure)
