"""Open the financial-reporting workflow without replacing the ledger session."""
from desktop.dialogs.filing import FilingDialog


def open_filing(controller):
    if controller.window.busy:
        return
    dialog=FilingDialog(controller.session,controller.window)
    controller._filing_dialog=dialog
    try:dialog.exec()
    finally:controller._filing_dialog=None
    if dialog.last_export:
        controller.window.notice.set_message('공시 결과와 검사 기록을 저장했어요. 결과 폴더에서 출력 종류와 검사 범위를 확인할 수 있어요.')
